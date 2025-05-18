from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# Reply‑клавиатура
kb_main = ReplyKeyboardMarkup(
    keyboard=[
        #[KeyboardButton(text="📤 Переслать")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

# Inline‑клавиатура
ikb_main = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="Помощь", callback_data="help"),
        InlineKeyboardButton(text="Переслать", callback_data="forward_prompt"),
        InlineKeyboardButton(text="Переслать ▶️", callback_data="forward_prompt")
    ]
])
