from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # Set USE_MOCK_API=true to run without real Pinecone/Gemini keys.
    # In mock mode the three Optional fields below are never accessed.
    use_mock_api: bool = False

    # Pinecone — required in production; optional in mock mode
    pinecone_api_key: str | None = None
    pinecone_index_name: str = "scholarbridge"
    pinecone_environment: str = "us-east-1-aws"

    # Gemini — required in production; optional in mock mode
    gemini_api_key: str | None = None

    # JWT — required in production; optional in mock mode
    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Semantic Scholar — optional; raises rate limit from ~0.3 req/s to 1 req/s
    semantic_scholar_api_key: str | None = None

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
