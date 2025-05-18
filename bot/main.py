import os
import asyncio
import pkgutil
import importlib
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
import logging
from logging.handlers import RotatingFileHandler

from bot.config import settings

# === ЛОГИРОВАНИЕ ===
log_dir = os.path.join(os.getcwd(), "logs", datetime.now().strftime("%Y%m%d_%H%M%S"))
os.makedirs(log_dir, exist_ok=True)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
fmt = logging.Formatter('%(asctime)s %(levelname)-8s [%(name)s:%(lineno)d] %(message)s')

# Консоль
sh = logging.StreamHandler()
sh.setFormatter(fmt)
logger.addHandler(sh)

# Файл с ротацией
fh = RotatingFileHandler(os.path.join(log_dir, "bot.log"),
                         maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
fh.setFormatter(fmt)
logger.addHandler(fh)
# ==================

async def main():
    bot = Bot(token=settings.bot_token)
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)


    from bot import commands

    module_names = [name for _, name, _ in pkgutil.iter_modules(commands.__path__)]

    module_names = sorted(module_names, key=lambda n: (n != "start", n))


    for module_name in module_names:
        module = importlib.import_module(f"bot.commands.{module_name}")
        if hasattr(module, 'register_handlers'):
            module.register_handlers(dp)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    logger.info("Start Bot: %s", datetime.today())
    asyncio.run(main())
