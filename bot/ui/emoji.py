"""Анімовані (Premium) емодзі.

Бот може показувати custom emoji у своїх повідомленнях і на кнопках, якщо власник бота має
Telegram Premium. Кожен емодзі має семантичний ключ, звичайний символ (fallback - видно, якщо
анімація недоступна) і ID custom emoji. Власник може замінити будь-який ID командою
/emoji_set (збережено в БД, перекриває значення за замовчуванням).

Джерела ID за замовчуванням:
  * офіційний пак анімованих емодзі Telegram «RestrictedEmoji» та іконки TgAndroidIcons -
    з відкритого каталогу github.com/abbosahmad/telegram-premium-emojis;
  * ID зі старої версії бота (валюти, корона, вогонь) - перевірені з акаунтом власника.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Emo:
    char: str
    id: str | None = None


DEFAULTS: dict[str, Emo] = {
    # ---- ролі ----
    "selianyn": Emo("🙂", "5371073319107827779"),
    "znaharka": Emo("👨‍⚕️", "5429363657471434941"),
    "harakternyk": Emo("🕵️"),
    "kum": Emo("🍀", "5395325195542078574"),
    "storozh": Emo("🚶"),
    "kobzar": Emo("📰", "5433982607035474385"),
    "otaman": Emo("🎖", "5332547853304734597"),
    "vidma": Emo("🎩", "5287455550009809073"),
    "upyr": Emo("🔫", "5287638494141781389"),
    "mavka": Emo("💋", "5420273668427096000"),
    "vovkulaka": Emo("🔪", "5287353815119465955"),
    "duren": Emo("🤡", "5371074117971745503"),
    # ---- предмети ----
    "obereg": Emo("🧿", "5426900601101374618"),
    "garlic": Emo("🧄"),
    "horseshoe": Emo("🐴", "5339237329292764502"),
    "candle": Emo("🕯", "5350571717922167592"),
    "mask": Emo("🎭", "5359441070201513074"),
    "pitchfork": Emo("🔱"),
    "honey": Emo("🍯", "5402418909557053333"),
    # ---- сторони ----
    "village": Emo("🏠", "5465226866321268133"),
    "evil": Emo("🌑", "5188497854242495901"),
    "moon": Emo("🌕", "5188608638628929611"),
    # ---- фази ----
    "night": Emo("🌙", "5377377257356537351"),
    "morning": Emo("☀️", "5469947168523558652"),
    "sunrise": Emo("🌞", "5467597172872584200"),
    "discuss": Emo("🗣", "5370765563226236970"),
    "vote": Emo("🗳", "5359741159566484212"),
    "rope": Emo("🪢"),
    "coffin": Emo("⚰️", "5433769525117983603"),
    "skull": Emo("💀", "5370971163310693562"),
    "dove": Emo("🕊", "5434121252874756456"),
    "blood": Emo("🩸", "5287628044486350080"),
    # ---- валюти й статус ----
    "shagy": Emo("🪙", "5287645065441745227"),
    "cherv": Emo("💎", "5323694594267845824"),
    "vip": Emo("👑", "5339272251671879128"),
    "star": Emo("⭐", "5435957248314579621"),
    "moneybag": Emo("💰", "5375296873982604963"),
    # ---- нагороди ----
    "trophy": Emo("🏆", "5409008750893734809"),
    "gold": Emo("🥇", "5280735858926822987"),
    "silver": Emo("🥈", "5283195573812340110"),
    "bronze": Emo("🥉", "5282750778409233531"),
    "party": Emo("🎉", "5436040291507247633"),
    "fire": Emo("🔥", "5339218723494468495"),
    "sparkle": Emo("✨", "5472164874886846699"),
    "gift": Emo("🎁", "5199749070830197566"),
    # ---- інтерфейс ----
    "sunflower": Emo("🌻", "5211226911367257670"),
    "house": Emo("🏠", "5465226866321268133"),
    "profile": Emo("👤", "5373012449597335010"),
    "people": Emo("👥", "5372926953978341366"),
    "shop": Emo("🛒", "5431499171045581032"),
    "bag": Emo("👜", "5380056101473492248"),
    "rules": Emo("📖", "5226512880362332956"),
    "settings": Emo("⚙️", "5258096772776991776"),
    "timer": Emo("⏳", "5451732530048802485"),
    "hourglass": Emo("⌛", "5451646226975955576"),
    "dice": Emo("🎲", "5235588635885054955"),
    "ok": Emo("✅", "5427009714745517609"),
    "no": Emo("❌", "5465665476971471368"),
    "back": Emo("⬅️", "5258236805890710909"),
    "refresh": Emo("🔄", "5264727218734524899"),
    "skip": Emo("🚫", "5219805369806629055"),
    "eye": Emo("👁", "5424892643760937442"),
    "secret": Emo("🤫", "5370930189322688800"),
    "megaphone": Emo("📣", "5469903029144657419"),
    "stats": Emo("📊", "5431577498364158238"),
    "chart": Emo("📈", "5373001317042101552"),
    "bell": Emo("🔔", "5242628160297641831"),
    "hand": Emo("🙋", "5906995262378741881"),
    "wave": Emo("👋", "5472055112702629499"),
    "chat": Emo("💬", "5465300082628763143"),
    "check": Emo("🔍", "5188217332748527444"),
    "heal": Emo("💚", "5449380056201697322"),
    "shield": Emo("🛡", "5251203410396458957"),
    "lock": Emo("🔒", "5258476306152038031"),
    "tools": Emo("🛠", "5988023995125993550"),
    "like": Emo("👍"),
    "dislike": Emo("👎"),
}

_overrides: dict[str, str] = {}
_enabled = True

TAG_RE = re.compile(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', re.S)


def configure(enabled: bool, overrides: dict[str, str] | None = None) -> None:
    global _enabled
    _enabled = enabled
    _overrides.clear()
    _overrides.update({k: v for k, v in (overrides or {}).items() if k in DEFAULTS})


def set_override(key: str, custom_id: str | None) -> None:
    if custom_id:
        _overrides[key] = custom_id
    else:
        _overrides.pop(key, None)


def custom_id(key: str) -> str | None:
    if not _enabled or key not in DEFAULTS:
        return None
    return _overrides.get(key) or DEFAULTS[key].id


def plain(key: str) -> str:
    return DEFAULTS[key].char


def e(key: str) -> str:
    """HTML: анімований емодзі (або звичайний, якщо ID немає / вимкнено)."""
    emo = DEFAULTS[key]
    cid = custom_id(key)
    if cid:
        return f'<tg-emoji emoji-id="{cid}">{emo.char}</tg-emoji>'
    return emo.char


def icon(key: str | None) -> str | None:
    """ID для icon_custom_emoji_id на кнопці."""
    return custom_id(key) if key else None


def strip(html: str) -> str:
    """Прибрати анімовані емодзі, лишивши звичайні символи."""
    return TAG_RE.sub(r"\1", html)


TOKEN_RE = re.compile(r":([a-z][a-z0-9_]*):")


def render(text: str, html: bool = True) -> str:
    """Замінює мітки :ключ: на емодзі (анімовані в HTML, звичайні - у простому тексті)."""
    if ":" not in text:
        return text

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in DEFAULTS:
            return m.group(0)
        return e(key) if html else plain(key)

    return TOKEN_RE.sub(sub, text)
