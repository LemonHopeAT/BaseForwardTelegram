from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from bot.keyboards import kb_main
from bot.config import settings

import logging

logger = logging.getLogger(__name__)
router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message):
    logger.info("User %s click start", message.from_user.id)
    start_text = settings.start_message.replace("\\n", "\n")
    await message.answer(start_text, reply_markup=kb_main)

def register_handlers(dp):
    dp.include_router(router)
