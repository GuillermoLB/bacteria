from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PostgresSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POSTGRES__", env_file=".env", extra="ignore")

    host: str = "localhost"
    port: int = 5432
    user: str = "bacteria"
    password: str = "bacteria"
    db: str = "bacteria"

    @property
    def url(self) -> str:
        return f"postgresql+psycopg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WORKER__", env_file=".env", extra="ignore")

    concurrency: int = 5
    poll_interval: int = 5      # seconds between polls when queue is empty
    stuck_threshold: int = 600  # seconds before a CLAIMED job is considered stuck


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT__", env_file=".env", extra="ignore")

    model: str = "claude-sonnet-4-6"
    max_turns: int = 20
    max_budget_usd: float = 1.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
