from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    bot_token: str
    admin_chat_id: int
    redis_url: str = 'redis://localhost:6379/0'
    start_message: str
    
    model_config = {
        'env_file': '.env',
        'case_sensitive': False,
    }

settings = Settings()