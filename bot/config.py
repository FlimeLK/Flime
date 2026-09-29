"""Налаштування бота зі змінних середовища (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "mafia"
    db_user: str = "postgres"
    db_password: str = ""
    owner_ids: frozenset[int] = field(default_factory=frozenset)
    # Анімовані емодзі (потрібен Telegram Premium у власника бота)
    premium_emoji: bool = True

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


def _parse_ids(raw: str) -> frozenset[int]:
    ids = set()
    for part in raw.replace(" ", "").split(","):
        if part.lstrip("-").isdigit():
            ids.add(int(part))
    return frozenset(ids)


def load_settings() -> Settings:
    load_dotenv()
    token = (os.getenv("BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не вказаний. Скопіюй .env.example у .env і впиши токен.")
    return Settings(
        bot_token=token,
        db_host=os.getenv("DB_HOST", "localhost"),
        db_port=int(os.getenv("DB_PORT", "5432")),
        db_name=os.getenv("DB_NAME", "mafia"),
        db_user=os.getenv("DB_USER", "postgres"),
        db_password=os.getenv("DB_PASSWORD", ""),
        owner_ids=_parse_ids(os.getenv("OWNER_IDS", "")),
        premium_emoji=os.getenv("PREMIUM_EMOJI", "1").strip().lower() not in ("0", "false", "no", "off"),
    )
