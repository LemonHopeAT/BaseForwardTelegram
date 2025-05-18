from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

import logging
logger = logging.getLogger(__name__)

router = Router()

@router.message(Command("help"))
async def cmd_help(message: Message):
    logger.info("User %s click help", message.from_user.id)
    help_text = (
        "📖 <b>Справка по командам бота</b>\n\n"
        "👤 <u>Пользовательский функционал</u>:\n"
        "  • Отправка сообщений и файлов\n"
        "🛠 <u>Админский функционал</u> (в админ‑чате):\n"
        "  • Ответ на пересланное сообщение командой <code>/ban [причина]</code>\n"
        "    — заблокировать пользователя; причина опциональна\n"
        "  • Ответ на пересланное сообщение командой <code>/unban</code>\n"
        "    — снять бан с пользователя\n"
        "  • <code>/unban &lt;user_id&gt;</code> — разбанить по ID без reply\n"
        "  • <code>/banlist</code> — показать список забаненных\n\n"
        "🤖 Примеры:\n"
        "  /ban Спам в чате\n"
        "  /unban 123456789\n\n"
    )
    await message.reply(help_text, parse_mode="HTML")

def register_handlers(dp):
    dp.include_router(router)
