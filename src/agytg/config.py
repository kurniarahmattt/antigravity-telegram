"""Settings loaded from environment / .env file."""

from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    telegram_bot_username: str = Field("", alias="TELEGRAM_BOT_USERNAME")

    # Workspace
    approved_directory: Path = Field(..., alias="APPROVED_DIRECTORY")
    allowed_users_raw: str = Field("", alias="ALLOWED_USERS")

    @computed_field  # type: ignore[misc]
    @property
    def allowed_users(self) -> List[int]:
        raw = self.allowed_users_raw or ""
        return [int(x.strip()) for x in raw.split(",") if x.strip()]

    # agy
    agy_bin: str = Field("agy", alias="AGY_BIN")
    agy_timeout_seconds: int = Field(300, alias="AGY_TIMEOUT_SECONDS")
    agy_skip_permissions: bool = Field(True, alias="AGY_SKIP_PERMISSIONS")
    agy_conversations_dir: Path = Field(
        Path.home() / ".gemini" / "antigravity-cli" / "conversations",
        alias="AGY_CONVERSATIONS_DIR",
    )
    # Directory used as cwd for `agy` in chat mode. Must contain no
    # antigravity project markers so agy does not auto-attach a project.
    agy_chat_scratch_dir: Path = Field(
        Path.home() / ".cache" / "agytg" / "scratch",
        alias="AGY_CHAT_SCRATCH_DIR",
    )
    # Optional system-style instruction prepended to user prompts in chat
    # mode. Helps keep agy in a conversational register instead of slipping
    # into agentic planning. Set to empty string to disable.
    chat_prompt_prefix: str = Field(
        (
            "[System note for agy: Kamu sedang chat ringan via Telegram. "
            "Jawab natural dan singkat mengikuti bahasa user. JANGAN buat "
            "implementation plan, JANGAN narasi rencana tool, JANGAN buat "
            "file kecuali user eksplisit minta. Kalau user nanya teknis, "
            "jawab langsung tanpa proses formal.]\n\n[User]: "
        ),
        alias="CHAT_PROMPT_PREFIX",
    )

    # Storage
    database_path: Path = Field(Path("./data/agytg.sqlite"), alias="DATABASE_PATH")

    # Logging
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    debug: bool = Field(False, alias="DEBUG")

    @field_validator("approved_directory")
    @classmethod
    def must_exist(cls, v: Path) -> Path:
        v = v.expanduser().resolve()
        if not v.exists() or not v.is_dir():
            raise ValueError(f"APPROVED_DIRECTORY does not exist: {v}")
        return v
