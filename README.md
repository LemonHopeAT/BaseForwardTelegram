# Telegram Bot on Aiogram with Redis and Docker

## 📦 Project structure
```
aiogram_redis_bot/
├── bot/
│ ├── init.py
│ ├── config.py # Load env settings (token, Redis, admin ID)
│ ├── main.py # Bot startup and dispatcher
│ ├── commands/ # Modular command handlers
│ │ ├── init.py
│ │ ├── start.py # /start command
│ │ ├── help.py # /help command
│ │ └── forward.py # Logic for forwarding user messages
│ └── services/
│ ├── init.py
│ └── redis_client.py # Singleton Redis connection
├── Dockerfile # App Dockerfile
├── docker-compose.yml # App + Redis setup
└── requirements.txt # Python dependencies
```

## 🚀 Description

This is a modular and production-ready Telegram bot using:

- **[Aiogram 3.x](https://docs.aiogram.dev/)** for asynchronous bot logic  
- **Redis** as a fast in-memory store to track user-message mappings and state  
- **Docker** for consistent deployment and local development  

---

## 🔧 Key Components

### `bot/config.py`
Loads required settings via `os.environ`:
- `BOT_TOKEN`: Telegram bot token
- `ADMIN_CHAT_ID`: Admin or support chat
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`: Redis connection details

### `bot/main.py`
Entrypoint of the bot:
- Initializes dispatcher, middleware
- Loads all command handlers from `bot/commands`
- Starts polling via `asyncio`

### `bot/commands/`
Each command lives in its own file and defines:
```python
def register_handlers(router: Router):
    router.message(commands=["..."])(your_handler)
```
You can add a new command by dropping a file here.

bot/services/redis_client.py
Provides a global, shared Redis client:

redis = RedisClient.get_client()
await redis.set(...)

Docker & Deployment
Dockerfile: Builds the bot image

docker-compose.yml: Combines the bot and Redis

Example .env file:
```
BOT_TOKEN=123456:ABCDEF...
ADMIN_CHAT_ID=123456789
REDIS_HOST=redis
REDIS_PORT=6379
START_MESSAGE=some text start
```

Run with:
```
docker-compose up --build
```

## 🧠 Core Logic
All user messages (text, media, stickers) are forwarded to an admin chat.

If a user replies to a message in chat, the bot tracks reply context using Redis.

Admin can reply to forwarded messages in the admin chat, and the bot routes replies back to the correct user, supporting all content types.

Media groups are handled as first-part forward + remaining as a single sendMediaGroup to preserve context and minimize clutter.

## 🛡 License
This project is licensed under the MIT License — feel free to use, modify, and distribute.
