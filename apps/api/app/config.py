"""Application configuration, loaded from environment variables.

Uses pydantic-settings so config is validated and typed. In local dev the values come from
the repo-root .env (see .env.example); in Docker they are injected by docker-compose.
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The signing key a local stack uses when none is configured. Public, because it is in this
# file, so it is refused anywhere but development (see `_refuse_the_development_secret`).
DEVELOPMENT_JWT_SECRET = "northstar-development-only-signing-key-do-not-deploy"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "NorthStar API"
    environment: str = "development"

    # Database. Full SQLAlchemy URL. Defaults match docker-compose for zero-config local dev.
    database_url: str = "postgresql+psycopg://northstar:northstar@localhost:5432/northstar"

    # CORS: which web origins may call the API. The Next.js dev server by default.
    cors_origins: list[str] = ["http://localhost:3000"]

    # Where the sport modules live (packages/shared/sports). Unset means "find them from the
    # repository checkout", which is right for local runs; the API image sets it explicitly.
    sport_modules_dir: str | None = None

    # The local language model behind the profile summary (app/services/summary.py). Ollama
    # runs in docker-compose behind the `llm` profile. With it off, the profile says so and
    # shows no summary. An empty OLLAMA_URL turns the summary off entirely.
    ollama_url: str | None = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # Sessions: a signed token in an HttpOnly cookie. See app/security.py.
    jwt_secret: str = DEVELOPMENT_JWT_SECRET
    session_hours: int = 8
    # Send the cookie over HTTPS only. Unset means "everywhere except development", because
    # the local stack runs on plain http://localhost.
    cookie_secure: bool | None = None

    @property
    def session_cookie_secure(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.environment != "development"

    @model_validator(mode="after")
    def _refuse_the_development_secret(self) -> "Settings":
        """Outside development, a missing or weak signing key stops the API from starting.

        Anyone holding the key can mint a session for any account, including an admin, and
        the development key is published in this file. Failing at startup is louder than a
        warning nobody reads.
        """
        if self.environment != "development" and (
            self.jwt_secret == DEVELOPMENT_JWT_SECRET or len(self.jwt_secret) < 32
        ):
            raise ValueError(
                "JWT_SECRET must be set to a random value of at least 32 characters outside "
                "development. Generate one with: python -c \"import secrets; "
                "print(secrets.token_urlsafe(48))\""
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance so we parse the environment only once."""
    return Settings()
