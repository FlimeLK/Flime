"""Числа економіки в одному місці, щоб легко балансувати."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

# Нагороди за гру (шаги)
REWARD_PLAY = 10
REWARD_WIN = 40
VIP_MULTIPLIER = 1.5

# Щоденний гостинець
DAILY = 50
DAILY_VIP = 120
DAILY_COOLDOWN = timedelta(hours=20)

# Обмін: 1 червінець = N шагів
EXCHANGE_RATE = 50

# VIP
VIP_DAYS = 30
VIP_PRICE_CHERV = 60


@dataclass(frozen=True)
class Product:
    key: str
    title: str
    stars: int
    chervintsi: int = 0
    vip_days: int = 0


PRODUCTS: dict[str, Product] = {
    p.key: p
    for p in (
        Product("cherv_10", "10 червінців", 50, chervintsi=10),
        Product("cherv_30", "30 червінців", 140, chervintsi=30),
        Product("cherv_75", "75 червінців", 325, chervintsi=75),
        Product("vip_30", "VIP на 30 днів", 150, vip_days=VIP_DAYS),
    )
}


def game_reward(won: bool, vip: bool) -> int:
    amount = REWARD_PLAY + (REWARD_WIN if won else 0)
    return round(amount * VIP_MULTIPLIER) if vip else amount
