# ——— Импорты и настройки ——————————————————————————————————————————
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


# ——— Инициализация ——————————————————————————————————————————————
logger = logging.getLogger(__name__)
router = Router()

RATE_LIMIT_TTL = 1
_ALBUM_WAIT = 0.1
_album_buffer: dict[str, list[Message]] = {}

BANNED_SET = "banned_users"


# ——— Redis ключи ————————————————————————————————————————————————
def banned_key(user_id: int) -> str:
    return f"ban:{user_id}"

def reply_map_key(msg_id: int) -> str:
    return f"reply_map:{msg_id}"

def rate_limit_key(user_id: int) -> str:
    return f"user_rate_limit:{user_id}"


# ——— Проверка бана ———————————————————————————————————————————————
async def is_banned(user_id: int) -> bool:
    redis = RedisClient.get_client()
    return await redis.sismember(BANNED_SET, user_id)


# ——— Админ-хендлеры: бан / разбан / список —————————————————————————
@router.message(F.chat.id == settings.admin_chat_id, F.reply_to_message, F.text.startswith("/ban"))
async def admin_ban(message: Message):
    redis = RedisClient.get_client()
    reply = message.reply_to_message

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
    await message.reply(f"✅ Забанен {username} (<code>{user_id}</code>)\nПричина: <i>{reason}</i>", parse_mode="HTML")


@router.message(F.chat.id == settings.admin_chat_id, F.reply_to_message, F.text.startswith("/unban"))
async def admin_unban(message: Message):
    redis = RedisClient.get_client()
    reply = message.reply_to_message

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

    await message.reply("📋 <b>Забаненные пользователи:</b>\n" + "\n".join(lines), parse_mode="HTML")


# ——— Пересылка сообщений от пользователей ——————————————————————————
@router.message((F.text | F.caption | F.photo | F.document | F.video | F.sticker) & (F.chat.id != settings.admin_chat_id))
async def forward_user_message(message: Message):
    redis = RedisClient.get_client()
    user_id = message.from_user.id

    if await is_banned(user_id) or (message.text and message.text.startswith("/")):
        return

    reply_to = message.reply_to_message
    reply_to_forwarded_id = None
    if reply_to:
        redis_val = await redis.get(reply_map_key(reply_to.message_id))
        if redis_val:
            reply_to_forwarded_id = int(redis_val)

    if message.sticker:
        forwarded_msg = await message.forward(chat_id=settings.admin_chat_id, reply_to_message_id=reply_to_forwarded_id)
        await redis.set(reply_map_key(message.message_id), forwarded_msg.message_id)
        await redis.set(reply_map_key(forwarded_msg.message_id), user_id)
        return

    if message.media_group_id:
        await handle_media_group(message, reply_to_forwarded_id)
        return

    forwarded_msg = await message.forward(chat_id=settings.admin_chat_id, reply_to_message_id=reply_to_forwarded_id)
    await redis.set(reply_map_key(message.message_id), forwarded_msg.message_id)
    await redis.set(reply_map_key(forwarded_msg.message_id), user_id)
    logger.info("Forwarded message %s → %s", message.message_id, forwarded_msg.message_id)


async def handle_media_group(message: Message, reply_to_forwarded_id: int):
    redis = RedisClient.get_client()
    media_group_id = message.media_group_id
    buffer = _album_buffer.setdefault(media_group_id, [])
    buffer.append(message)

    if len(buffer) == 1:
        await asyncio.sleep(_ALBUM_WAIT)
        group = _album_buffer.pop(media_group_id, [])

        if not group:
            return

        first = group[0]
        first_fwd = await first.forward(chat_id=settings.admin_chat_id, reply_to_message_id=reply_to_forwarded_id)
        await redis.set(reply_map_key(first.message_id), first_fwd.message_id)
        await redis.set(reply_map_key(first_fwd.message_id), first.from_user.id)

        media = []
        msg_map = []

        for msg in group[1:]:
            if msg.photo:
                media.append(InputMediaPhoto(media=msg.photo[-1].file_id))
            elif msg.video:
                media.append(InputMediaVideo(media=msg.video.file_id))
            elif msg.document:
                media.append(InputMediaDocument(media=msg.document.file_id))
            msg_map.append(msg)

        if media:
            sent = await message.bot.send_media_group(chat_id=settings.admin_chat_id, media=media, reply_to_message_id=first_fwd.message_id)
            for orig, sent_msg in zip(msg_map, sent):
                await redis.set(reply_map_key(orig.message_id), sent_msg.message_id)
                await redis.set(reply_map_key(sent_msg.message_id), orig.from_user.id)


# ——— Ответ администратора пользователю ————————————————————————————
@router.message(F.chat.id == settings.admin_chat_id, F.reply_to_message)
async def admin_reply(message: Message):
    redis = RedisClient.get_client()
    reply = message.reply_to_message

    user_id = reply.forward_from.id if reply.forward_from else None
    if not user_id:
        redis_id = await redis.get(reply_map_key(reply.message_id))
        user_id = int(redis_id) if redis_id else None
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
            await message.reply("❗ Тип контента не поддерживается.")
    except Exception as e:
        logger.exception("Ошибка при отправке ответа")
        await message.reply(f"❌ Не удалось отправить сообщение: {e}")


# ——— Команды /forward и кнопка пересылки ——————————————————————————
@router.message(F.text == "📤 Переслать")
async def start_forward_by_button(message: Message, state: FSMContext):
    if await is_banned(message.from_user.id):
        return
    await message.answer("Введите текст для пересылки:")
    await state.set_state(ForwardStates.waiting_for_text)


@router.message(ForwardStates.waiting_for_text)
async def forward_from_state(message: Message, state: FSMContext):
    text = (message.text or message.caption or "").strip()
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


# ——— Вспомогательные функции —————————————————————————————————————————
async def do_forward(message: Message, text: str):
    redis = RedisClient.get_client()
    now = time.time()
    key = rate_limit_key(message.from_user.id)

    last = await redis.get(key)
    if last and now - float(last) < RATE_LIMIT_TTL:
        return await message.reply("⏳ Подождите перед следующей отправкой.")

    await redis.set(key, now, ex=RATE_LIMIT_TTL)
    await redis.lpush(f"user:{message.from_user.id}:forwards", text)

    forwarded = await message.forward(settings.admin_chat_id)
    await redis.set(reply_map_key(forwarded.message_id), message.from_user.id)


def register_handlers(dp):
    dp.include_router(router)
