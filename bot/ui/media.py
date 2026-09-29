"""Медіа для сцен гри (фото / GIF / відео), які власник завантажує через бота."""

from __future__ import annotations

from bot.engine.roles import ROLES

SCENES: dict[str, str] = {
    "start": "Привітання /start",
    "lobby": "Збір гравців",
    "game_start": "Початок гри",
    "night": "Ніч",
    "morning": "Ранок",
    "vote": "Голосування",
    "lynch": "Страта",
    "win_village": "Перемога Громади",
    "win_evil": "Перемога Нечисті",
    "win_wolf": "Перемога Вовкулаки",
    "draw": "Нічия",
    **{f"role_{k}": f"Картка ролі: {r.name}" for k, r in ROLES.items()},
}

# Ефекти повідомлень (працюють лише в особистих чатах).
EFFECT_PARTY = "5046509860389126442"   # 🎉
EFFECT_FIRE = "5104841245755180586"    # 🔥

_media: dict[str, tuple[str, str]] = {}


def load(data: dict[str, tuple[str, str]]) -> None:
    _media.clear()
    _media.update({k: v for k, v in data.items() if k in SCENES})


def get(slot: str) -> tuple[str, str] | None:
    return _media.get(slot)


def put(slot: str, kind: str | None, file_id: str | None) -> None:
    if kind and file_id:
        _media[slot] = (kind, file_id)
    else:
        _media.pop(slot, None)
