import time
import asyncio
import logging

from typing import Dict, List

from aiogram import Router, F
from aiogram.types import (
    Message, InputMediaPhoto, InputMediaVideo,
    InputMediaDocument, ChatPermissions
)
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.utils.markdown import hbold

from bot.config import settings
from bot.services.redis_client import RedisClient
from bot.states import ForwardStates

# ——— Общие переменные ———————————————————————————————
logger = logging.getLogger(__name__)
router = Router()

_ALBUM_WAIT = 0.1
_album_buffer: dict[str, list[Message]] = {}

BANNED_SET = "banned_users"
RATE_LIMIT_TTL = 1  # секунда

# ——— Redis ключи ————————————————————————————————————————
def banned_key(user_id: int) -> str:
    return f"ban:{user_id}"

def reply_map_key(msg_id: int) -> str:
    return f"reply_map:{msg_id}"

def rate_limit_key(user_id: int) -> str:
    return f"user_rate_limit:{user_id}"

async def is_banned(user_id: int) -> bool:
    redis = RedisClient.get_client()
    return await redis.sismember(BANNED_SET, user_id)

# ——— ХЕНДЛЕРЫ АДМИНА ———————————————————————————————————————————————

@router.message(F.chat.id == settings.admin_chat_id, F.reply_to_message, F.text.startswith("/ban"))
async def admin_ban(message: Message):
    reply = message.reply_to_message
    redis = RedisClient.get_client()

    user_id = (
        reply.forward_from.id
        if reply.forward_from
        else int(await redis.get(reply_map_key(reply.message_id)) or 0)
    )
    if not user_id:
        return await message.reply("❗ Не удалось определить пользователя для бана.")

    reason = (message.text.split(" ", 1)[1] or "Без причины").strip()

    username = (
        f"@{reply.forward_from.username}" if reply.forward_from and reply.forward_from.username
        else reply.forward_from.full_name if reply.forward_from
        else str(user_id)
    )

    await message.bot.ban_chat_member(settings.admin_chat_id, user_id)
    await redis.sadd(BANNED_SET, user_id)
    await redis.hset(banned_key(user_id), mapping={"username": username, "reason": reason})

    logger.info("Banned user: %s (%s)", username, user_id)
    await message.reply(
        f"✅ Забанен {username} (<code>{user_id}</code>)\nПричина: <i>{reason}</i>",
        parse_mode="HTML"
    )


@router.message(F.chat.id == settings.admin_chat_id, F.reply_to_message, F.text.startswith("/unban"))
async def admin_unban(message: Message):
    reply = message.reply_to_message
    redis = RedisClient.get_client()

    user_id = (
        reply.forward_from.id
        if reply.forward_from
        else int(await redis.get(reply_map_key(reply.message_id)) or 0)
    )
    if not user_id:
        return await message.reply("❗ Не удалось определить пользователя.")

    await message.bot.unban_chat_member(settings.admin_chat_id, user_id)
    await redis.srem(BANNED_SET, user_id)
    await redis.delete(banned_key(user_id))

    logger.info("Unbanned user: %s", user_id)
    await message.reply(f"✅ Разбанен <code>{user_id}</code>", parse_mode="HTML")


@router.message(F.chat.id == settings.admin_chat_id, Command("unban"))
async def admin_unban_by_id(message: Message, command: CommandObject):
    redis = RedisClient.get_client()
    args = (command.args or "").strip()

    if not args.isdigit():
        return await message.reply("❗ Использование: /unban <user_id>")

    user_id = int(args)
    if not await redis.sismember(BANNED_SET, user_id):
        return await message.reply(f"❗ Пользователь <code>{user_id}</code> не в бан‑листе.", parse_mode="HTML")

    await redis.srem(BANNED_SET, user_id)
    await redis.delete(banned_key(user_id))
    logger.info("Unbanned user by ID: %s", user_id)
    await message.reply(f"✅ Пользователь <code>{user_id}</code> разбанен.", parse_mode="HTML")


@router.message(F.chat.id == settings.admin_chat_id, Command("banlist"))
async def cmd_banlist(message: Message):
    redis = RedisClient.get_client()
    banned = await redis.smembers(BANNED_SET)
    if not banned:
        return await message.reply("📋 Список забаненных пользователей пуст.")

    lines = []
    for i, uid in enumerate(sorted(banned), 1):
        data = await redis.hgetall(banned_key(uid))
        uname = data.get("username", uid)
        reason = data.get("reason", "")
        lines.append(f"{i}. {hbold(uname)} (<code>{uid}</code>) — {reason}")

    text = "📋 <b>Забаненные пользователи:</b>\n" + "\n".join(lines)
    await message.reply(text, parse_mode="HTML")


# ——— ХЕНДЛЕРЫ ПОЛЬЗОВАТЕЛЕЙ: Пересылка ————————————————————————————

@router.message(
    (F.text | F.caption | F.photo | F.document | F.video | F.sticker) &
    (F.chat.id != settings.admin_chat_id)
)
async def forward_any_message(message: Message):
    redis = RedisClient.get_client()
    user_id = message.from_user.id

    # 1) бан-лист / игнор команд
    if await is_banned(user_id):
        return
    if message.text and message.text.startswith("/"):
        return

    # 2) на какое сообщение юзер реплаился?
    reply_to = message.reply_to_message
    reply_to_forwarded_id = None
    if reply_to:
        val = await redis.get(reply_map_key(reply_to.message_id))
        if val:
            reply_to_forwarded_id = int(val)

    # 3) стикер отдельно
    if message.sticker:
        fwd = await message.forward(
            chat_id=settings.admin_chat_id,
            reply_to_message_id=reply_to_forwarded_id
        )
        # мапим именно этот оригинал
        await redis.set(reply_map_key(message.message_id), fwd.message_id)
        await redis.set(reply_map_key(fwd.message_id), message.from_user.id)
        return

    # 4) медиа‑группа (альбом)
    if message.media_group_id:
        mgid = message.media_group_id
        buf = _album_buffer.setdefault(mgid, [])
        buf.append(message)

        # Только на первой части ждём остальных
        if len(buf) == 1:
            await asyncio.sleep(_ALBUM_WAIT)
            group = _album_buffer.pop(mgid, [])

            if not group:
                return

            # 1) Форвардим первую часть
            first_orig = group[0]
            fwd_first = await first_orig.forward(
                chat_id=settings.admin_chat_id,
                reply_to_message_id=reply_to_forwarded_id
            )
            await redis.set(reply_map_key(first_orig.message_id), fwd_first.message_id)
            await redis.set(reply_map_key(fwd_first.message_id), message.from_user.id)
            logger.info("Forwarded first of group %s → %s", first_orig.message_id, fwd_first.message_id)

            # 2) Готовим единый альбом из оставшихся частей
            rest = group[1:]
            if rest:
                caption = None  # подписи уже были в первом форварде
                media = []
                media_msg_map = []

                for msg in rest:
                    if msg.photo:
                        media.append(InputMediaPhoto(media=msg.photo[-1].file_id, caption=caption))
                        media_msg_map.append(msg)
                    elif msg.video:
                        media.append(InputMediaVideo(media=msg.video.file_id, caption=caption))
                        media_msg_map.append(msg)
                    elif msg.document:
                        media.append(InputMediaDocument(media=msg.document.file_id, caption=caption))
                        media_msg_map.append(msg)

                # отправляем всё одним send_media_group
                sent_group = await message.bot.send_media_group(
                    chat_id=settings.admin_chat_id,
                    media=media,
                )

                # сохраняем маппинг каждого оригинального → отправленного сообщения, и наоборот
                for orig_msg, sent_msg in zip(media_msg_map, sent_group):
                    await redis.set(reply_map_key(orig_msg.message_id), sent_msg.message_id)
                    await redis.set(reply_map_key(sent_msg.message_id), message.from_user.id)

                logger.info(
                    "Sent rest of group (%d items) as single album starting at %s",
                    len(rest), sent_group[0].message_id
                )

        return


    # 5) одиночное медиа
    if message.photo or message.video or message.document or message.sticker:
        # пересылаем сообщение в админ‑чат как forward
        fwd = await message.forward(
            chat_id=settings.admin_chat_id,
            reply_to_message_id=reply_to_forwarded_id
        )
        # сохраняем маппинг original.message_id → fwd.message_id
        await redis.set(reply_map_key(message.message_id), fwd.message_id)
        await redis.set(reply_map_key(fwd.message_id), message.from_user.id)
        logger.info(
            "Forward single media/sticker %s → msg %s (as reply to %s)",
            user_id, fwd.message_id, reply_to_forwarded_id
        )
        return

    # 6) простой текст
    text = (message.text or "").strip()
    if text:
        fwd = await message.forward(
            chat_id=settings.admin_chat_id,
            reply_to_message_id=reply_to_forwarded_id
        )
        await redis.set(reply_map_key(message.message_id), fwd.message_id)
        await redis.set(reply_map_key(fwd.message_id), message.from_user.id)
        logger.info("Forward text %s → msg %s", user_id, fwd.message_id)

# ——— Ответы от Админа пользователю ———————————————————————————————————

@router.message(F.chat.id == settings.admin_chat_id, F.reply_to_message)
async def admin_reply(message: Message):
    redis = RedisClient.get_client()
    reply = message.reply_to_message

    user_id = reply.forward_from.id if reply.forward_from else None
    if not user_id:
        redis_id = await redis.get(reply_map_key(reply.message_id))
        if redis_id:
            user_id = int(redis_id)
    if not user_id:
        return

    try:
        if message.text:
            await message.bot.send_message(user_id, message.text)
        elif message.sticker:
            await message.bot.send_sticker(user_id, message.sticker.file_id)
        elif message.photo:
            await message.bot.send_photo(user_id, message.photo[-1].file_id, caption=message.caption)
        elif message.video:
            await message.bot.send_video(user_id, message.video.file_id, caption=message.caption)
        elif message.document:
            await message.bot.send_document(user_id, message.document.file_id, caption=message.caption)
        else:
            return await message.reply("❗ Тип контента не поддерживается.")
    
    except Exception as e:
        logger.exception("Ошибка при отправке ответа")
        await message.reply(f"❌ Не удалось отправить сообщение: {e}")


# ——— Команды пересылки через кнопку и /forward —————————————————————

@router.message(F.text == "📤 Переслать")
async def start_forward_by_button(message: Message, state: FSMContext):
    if await is_banned(message.from_user.id):
        return
    await message.answer("Введите текст для пересылки:")
    await state.set_state(ForwardStates.waiting_for_text)


@router.message(ForwardStates.waiting_for_text)
async def forward_from_state(message: Message, state: FSMContext):
    raw = message.text or message.caption or ""
    text = raw.strip()

    if not text and not (message.photo or message.document or message.video):
        return await message.reply("Текст не может быть пустым.")

    await do_forward(message, text)
    await message.reply("Сообщение отправлено.")
    await state.clear()


@router.message(Command("forward"))
async def cmd_forward(message: Message, command: CommandObject):
    text = (command.args or "").strip()
    await do_forward(message, text)
    await message.reply("Сообщение отправлено.")


# ——— Вспомогательная логика —————————————————————————————————————

async def do_forward(message: Message, text: str):
    redis = RedisClient.get_client()
    now = time.time()

    key = rate_limit_key(message.from_user.id)
    last = await redis.get(key)
    if last and now - float(last) < RATE_LIMIT_TTL:
        return await message.reply("⏳ Подождите перед следующей отправкой.")

    await redis.set(key, now, ex=RATE_LIMIT_TTL)
    await redis.lpush(f"user:{message.from_user.id}:forwards", text)

    fwd = await message.forward(settings.admin_chat_id)
    await redis.set(reply_map_key(fwd.message_id), message.from_user.id)


def register_handlers(dp):
    dp.include_router(router)
