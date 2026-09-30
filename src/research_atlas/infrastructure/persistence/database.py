"""Explicit PostgreSQL engine configuration."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RESEARCH_ATLAS_", extra="ignore")

    database_url: SecretStr | None = None


def configured_database_url() -> str:
    value = DatabaseSettings().database_url
    if value is None:
        raise ValueError("RESEARCH_ATLAS_DATABASE_URL is required")
    return value.get_secret_value()


def database_url(value: str) -> str:
    if make_url(value).drivername != "postgresql+psycopg":
        raise ValueError("database URL must use postgresql+psycopg")
    return value


def create_database_engine(url: str | None = None) -> AsyncEngine:
    """Caller must await engine.dispose(); importing this module opens no connections."""
    value = url if url is not None else configured_database_url()
    return create_async_engine(
        database_url(value), pool_pre_ping=True, isolation_level="READ COMMITTED"
    )
