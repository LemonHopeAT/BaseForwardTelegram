from aiogram.fsm.state import StatesGroup, State

class ForwardStates(StatesGroup):
    waiting_for_text = State()  # ждём от пользователя текст для пересылки