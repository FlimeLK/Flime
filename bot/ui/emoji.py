"""Анімовані (Premium) емодзі.

Бот може показувати custom emoji у своїх повідомленнях і на кнопках, якщо власник бота має
Telegram Premium. Кожен емодзі має семантичний ключ, звичайний символ (fallback - видно, якщо
анімація недоступна) і ID custom emoji. Власник може замінити будь-який ID командою
/emoji_set (збережено в БД, перекриває значення за замовчуванням).

Джерела ID за замовчуванням:
  * службові іконки інтерфейсу (UI_KEYS) - пак t.me/addemoji/TgAndroidIcons;
  * ролі, предмети, фази й нагороди - офіційний пак анімованих емодзі Telegram «RestrictedEmoji»;
    обидва - з відкритого каталогу github.com/abbosahmad/telegram-premium-emojis;
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
    "obereg": Emo("📿", "5287475306859369799"),
    "garlic": Emo("🧴", "5287390996651348173"),
    "horseshoe": Emo("🚗", "5287452805525707781"),
    "candle": Emo("🔦", "5287497507545325240"),
    "mask": Emo("📜", "5343901079660697964"),
    "pitchfork": Emo("🔪", "5287353815119465955"),
    "honey": Emo("🚬", "5287288712005196892"),
    # ---- сторони ----
    "village": Emo("🏠", "5465226866321268133"),
    "evil": Emo("🌑", "5188497854242495901"),
    "moon": Emo("🌕", "5188608638628929611"),
    # ---- фази ----
    "night": Emo("🌙", "5377377257356537351"),
    "morning": Emo("☀️", "5469947168523558652"),
    "sunrise": Emo("🌞", "5467597172872584200"),
    "discuss": Emo("🗣", "5908864771448376860"),
    "vote": Emo("🗳", "5359741159566484212"),
    "rope": Emo("🪢"),
    "coffin": Emo("⚰️", "5433769525117983603"),
    "skull": Emo("💀", "5370971163310693562"),
    "dove": Emo("🕊", "5434121252874756456"),
    "blood": Emo("🩸", "5287628044486350080"),
    # ---- валюти й статус ----
    "shagy": Emo("💰", "5287647058306571051"),
    "cherv": Emo("🪙", "5287645065441745227"),
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
    "theater": Emo("🎭", "5891093751555694829"),
    "house": Emo("🏠", "5967822972931542886"),
    "profile": Emo("👤", "5771887475421090729"),
    "people": Emo("👥", "5915556996215476302"),
    "shop": Emo("🏪", "5983399041197675256"),
    "bag": Emo("👛", "5769403330761593044"),
    "rules": Emo("📖", "5897850551156084824"),
    "settings": Emo("⚙️", "5877260593903177342"),
    "timer": Emo("⏲️", "5877613700344450910"),
    "hourglass": Emo("🕓", "5776213190387961618"),
    "dice": Emo("🎲", "5960608239623082921"),
    "ok": Emo("✅", "5776375003280838798"),
    "no": Emo("❌", "5778527486270770928"),
    "back": Emo("⬅️", "5875082500023258804"),
    "refresh": Emo("🔄", "5839200986022812209"),
    "skip": Emo("🚫", "5872829476143894491"),
    "eye": Emo("👁", "5960714428394507968"),
    "secret": Emo("🔇", "5890838600433536921"),
    "megaphone": Emo("📢", "5771695636411847302"),
    "stats": Emo("📊", "5877485980901971030"),
    "chart": Emo("📈", "5776219138917668486"),
    "bell": Emo("🔔", "5909201569898827582"),
    "hand": Emo("🙋", "5906995262378741881"),
    "wave": Emo("👋", "5994750571041525522"),
    "chat": Emo("💬", "5886666250158870040"),
    "check": Emo("🔎", "5874960879434338403"),
    "heal": Emo("💚", "5449380056201697322"),
    "shield": Emo("🛡", "5926783847453692661"),
    "lock": Emo("🔒", "5832546462478635761"),
    "tools": Emo("🛠", "5988023995125993550"),
    "like": Emo("👍", "5992199545151295755"),
    "dislike": Emo("👎", "5994368422031397063"),
    "trash": Emo("🗑", "5879896690210639947"),
    "plus": Emo("➕", "5877219383691972108"),
    "pin": Emo("📌", "5908961403917570106"),
    "edit": Emo("✏️", "5879841310902324730"),
    "info": Emo("ℹ️", "5879785854284599288"),
    "warn": Emo("⚠️", "5881702736843511327"),
}

# Службові іконки інтерфейсу (меню, налаштування, кабінет Дона, кнопки) - з паку TgAndroidIcons.
# /emoji_pack НАЗВА ui застосовує пак лише до них. Ролі, предмети, валюти, фази й нагороди - тематичні.
UI_KEYS = frozenset({
    "settings", "timer", "hourglass", "profile", "people", "house", "shop", "bag", "rules", "dice", "ok", "no",
    "back", "refresh", "skip", "eye", "secret", "megaphone", "stats", "chart", "bell", "hand", "wave", "chat",
    "check", "shield", "lock", "tools", "like", "dislike", "theater", "discuss", "trash", "plus", "pin", "edit",
    "info", "warn",
})

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
