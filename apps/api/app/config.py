"""Application configuration, loaded from environment variables.

Uses pydantic-settings so config is validated and typed. In local dev the values come from
the repo-root .env (see .env.example); in Docker they are injected by docker-compose.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "NorthStar API"
    environment: str = "development"

    # Database. Full SQLAlchemy URL. Defaults match docker-compose for zero-config local dev.
    database_url: str = "postgresql+psycopg://northstar:northstar@localhost:5432/northstar"

    # CORS: which web origins may call the API. The Next.js dev server by default.
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance so we parse the environment only once."""
    return Settings()
