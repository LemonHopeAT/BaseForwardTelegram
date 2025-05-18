from aiogram import Router
from aiogram.types import CallbackQuery

router = Router()

@router.callback_query(lambda c: c.data == "help")
async def cb_help(query: CallbackQuery):
    await query.message.answer("Доступные команды:\n/start — запустить бота\n/help — справка\n/forward <текст> — переслать админам")
    await query.answer()

@router.callback_query(lambda c: c.data == "forward_prompt")
async def cb_forward_prompt(query: CallbackQuery):
    await query.message.answer("Введите команду в формате:\n/forward ваш текст")
    await query.answer()

def register_handlers(dp):
    dp.include_router(router)
