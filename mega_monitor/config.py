# config.py
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import AnyUrl, Field, Extra

class Settings(BaseSettings):
    discord_webhook_url: AnyUrl
    check_interval_seconds: int = 3600  # 10 minutes
    log_level: str = "INFO"

    # Load the raw ENV string if present; .env might not include this
    raw_mention_user_ids: str = Field("", env="MENTION_USER_IDS")

    timezone: str = "UTC"
    # Ensure state lives under /app/data (the mounted folder)
    state_dir: Path = Path.cwd() / "data"

    class Config:
        env_file = ".env"
        env_prefix = ""
        extra = Extra.ignore

    @property
    def mention_user_ids(self) -> list[str]:
        # First try the raw field (from .env or OS env), then fallback to os.getenv
        raw = self.raw_mention_user_ids or os.getenv("MENTION_USER_IDS", "")
        return [
            uid.strip()
            for uid in raw.split(",")
            if uid.strip()
        ]

settings = Settings()
