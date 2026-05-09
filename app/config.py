from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field


load_dotenv()


class Settings(BaseModel):
    openai_api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_base_url: str = Field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    openai_model: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    sqlite_path: str = Field(default_factory=lambda: os.getenv("SQLITE_PATH", "data/agent_chat.db"))

    @property
    def sqlite_file(self) -> Path:
        return Path(self.sqlite_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
