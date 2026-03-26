from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # Pinecone
    pinecone_api_key: str
    pinecone_index_name: str = "scholarbridge"
    pinecone_environment: str = "us-east-1-aws"

    # Gemini
    gemini_api_key: str

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # CORS
    frontend_url: str = "http://localhost:3000"

    # Database
    database_url: str = "sqlite+aiosqlite:///./scholarbridge.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
