# -*- coding: utf-8 -*-
"""
Преміум (анімовані) емодзі в повідомленнях бота.

У Telegram преміум-емодзі відображаються як анімація для підписників Premium.
Щоб бот міг їх відправляти, використовуй HTML-тег:
  <tg-emoji emoji-id="CUSTOM_EMOJI_ID">🔫</tg-emoji>
Символ у тезі — fallback для клієнтів без підтримки.

Як отримати custom_emoji_id:
  1. Надішли потрібний преміум-емодзі боту в ЛС (або збережи в повідомленні).
  2. У коді засновника можна тимчасово вивести message.entities — там буде
     entity.type == "custom_emoji" та entity.custom_emoji_id.
  3. Або переглянь повідомлення в Telegram Web (DevTools) / @RawDataBot.

Підставляй ID нижче в CUSTOM_EMOJI_MAP і викликай emoji_to_premium(text)
перед відправкою повідомлення з parse_mode="html".
"""

import unicodedata
from typing import Any, Dict, Iterable, Optional, FrozenSet

# У масових текстах з skip_vip_badges=True не чіпаємо лише ⚒️ та 🐈‍⬛ (часто в описах магазину / апселах).
# ⛏️ і 🔥 — преміум-значки VIP+ у CUSTOM_EMOJI_MAP; їх конвертуємо разом з іншими емодзі.
VIP_BADGE_SYMBOLS_NFC: FrozenSet[str] = frozenset(
    unicodedata.normalize("NFC", c) for c in ("⚒️", "🐈‍⬛")
)

# Маппінг: звичайний емодзі (один символ) -> custom_emoji_id (рядок з Telegram).
# Заповни ID з Telegram (наприклад, /get_emoji_id та надішли преміум-емодзі боту).
# У маппінгу: 🔫 🔪 🧴 🎩 🩸 🚬 ☠️ 🐈‍⬛ 🌀 — підставляються в текстах повідомлень (buff_shop, play тощо).
# 🐈‍⬛ — Чорний кіт; 🌀 — Портал, унікальні бафи.
CUSTOM_EMOJI_MAP: Dict[str, str] = {
    "🔫": "5287638494141781389",
    "🔪": "5287353815119465955",
    "🧴": "5961017438337242519",
    "🎩": "5287455550009809073",
    "🩸": "5287628044486350080",
    "🚬": "5287288712005196892",
    "☠️": "5287427787341206470",
    "🧴": "5287390996651348173",
    "📿": "5287475306859369799", 
    "🔦": "5287497507545325240",
    "🚗": "5287452805525707781",
    "💰": "5287647058306571051",
    "💴": "5287335020342578666",
    "💵": "5287335020342578666",
    "🪙": "5287645065441745227",
    "🔍": "5287517784085927248",
    "🌀": "5305729235694951877",
    "🎯": "5323499435248881682",
    "🔴": "5323550352086178137",
    "🎲": "5323462438400596535",
    "💎": "5323694594267845824",
    "🧩": "5323295402827487241",
    "🎰": "5323293027710572231",
    "🚔": "5323280868658159270",
    "🚨": "5323618066540567552",
    "📈": "5323716056219424693",
    "❌": "5325562896451670272",
    "👑": "5339272251671879128",
    "🔥": "5339218723494468495",
    "🥚": "5343930500186674098",
    "🐣": "5341496280227028271",
    "💡": "5341465468131646647",
    "🧪": "5341644898980370960",
    "🧼": "5341597302152796852",
    "🔄": "5344017262821021543",
    "🔁": "5344017262821021543",
    "⬅️": "5346242575571393384",
    "🛡️": "5346277837252891810",
    "✨": "5343870048521986401",
    "📋": "5345820470480508677",
    "⚙️": "5345867663581156727",
    "🛠️": "5346301738745894496",
    "❓": "5345926066546448898",
    "👥": "5346040428640640384",
    "👤": "5345926663546900578",
    "📝": "5344003553285415043",
    "🎨": "5345774849337890224",
    "➕": "5343743926807337896",
    "📜": "5343901079660697964",
    "📑": "5346068625100937726",
    "⛏️": "5346271746989263986",
    "⚒️": "5343621803707242651",
    "🐈‍⬛": "5372835192002093123",
    "💍": "5285254980566030981",
    "🌼": "5372931519528620806", 
    "💥": "5372857517242094562",
    "🤠": "5287455550009809073",
    # Кіт /cat: клубок; чорний кіт; стейк; рукостискання; кусок м'яса; погладити (☝️); налаштування
    "🧶": "5384093357846860325",
    "🐱": "5381808357935979022",
    "🥩": "5382357886116598601",
    "👋": "5384054724616033529",
    "🐔": "5381998655051961580",
    "☝️": "5381841553738208311",
    "📳": "5384053676644015097",
}

def emoji_to_premium(
    text: str,
    mapping: Optional[Dict[str, str]] = None,
    *,
    skip_vip_badges: bool = False,
    skip_chars: Optional[Iterable[str]] = None,
) -> str:
    """
    Заміняє в тексті звичайні емодзі на HTML-теги преміум-емодзі.

    Використовуй з parse_mode="html" при відправці:
      from premium_emoji import emoji_to_premium
      text = emoji_to_premium("Куплено: 🔫 Tommy Gun")
      await message.answer(text, parse_mode="html")

    Якщо mapping не передано, використовується CUSTOM_EMOJI_MAP з цього модуля.
    Якщо для емодзі немає ID — символ залишається як є.

    skip_vip_badges=True — не конвертувати лише ⚒️ та 🐈‍⬛ (щоб не засмічувати преміумом
    кожен рядок магазину). ⛏️ і 🔥 завжди йдуть через мапу, якщо є в тексті.

    skip_chars — не замінювати ці емодзі (NFC), наприклад якщо Telegram відхиляє id.
    """
    if text is None or not text:
        return text or ""
    base = mapping if mapping is not None else CUSTOM_EMOJI_MAP
    if skip_vip_badges and base:
        use = {
            char: cid
            for char, cid in base.items()
            if unicodedata.normalize("NFC", char) not in VIP_BADGE_SYMBOLS_NFC
        }
    else:
        use = dict(base) if base else {}
    if skip_chars and use:
        banned = frozenset(unicodedata.normalize("NFC", c) for c in skip_chars)
        use = {
            char: cid
            for char, cid in use.items()
            if unicodedata.normalize("NFC", char) not in banned
        }
    if not use:
        return unicodedata.normalize("NFC", text or "")
    def _expand_variants(sym: str) -> list[str]:
        """Повернути можливі варіанти символу з/без variation selector-16."""
        n = unicodedata.normalize("NFC", sym or "")
        if not n:
            return []
        out = [n]
        if "\ufe0f" in n:
            base = n.replace("\ufe0f", "")
            if base and base not in out:
                out.append(base)
        else:
            with_vs16 = f"{n}\ufe0f"
            if with_vs16 not in out:
                out.append(with_vs16)
        return out

    # Нормалізація NFC, щоб однакові символи (різні форми) збігались
    result = unicodedata.normalize("NFC", text)
    # Спершу замінюємо довші послідовності (наприклад ☠️), потім коротші
    for char, custom_id in sorted(use.items(), key=lambda x: -len(x[0])):
        if not custom_id:
            continue
        for char_n in _expand_variants(char):
            if char_n in result:
                result = result.replace(char_n, f'<tg-emoji emoji-id="{custom_id}">{char_n}</tg-emoji>')
    return result


def custom_emoji_id_for_symbol(symbol: str) -> Optional[str]:
    """Повертає custom_emoji_id для одного емодзі з CUSTOM_EMOJI_MAP (NFC) або None."""
    if not symbol:
        return None
    n = unicodedata.normalize("NFC", symbol)
    return CUSTOM_EMOJI_MAP.get(n)


def build_emoji_callback_button(
    callback_data: str,
    *,
    text: str,
    is_selected: bool = False,
    icon_custom_emoji_id: Optional[str] = None,
) -> Any:
    """
    Inline-кнопка (Bot API 9.4+): преміум — лише icon_custom_emoji_id, text = пробіл (без дубля емодзі);
    звичайний випадок — text як підпис. Обрана опція: style success.
    """
    from aiogram.types import InlineKeyboardButton

    kwargs: dict = {
        "text": " " if icon_custom_emoji_id else text,
        "callback_data": callback_data,
    }
    if icon_custom_emoji_id:
        kwargs["icon_custom_emoji_id"] = icon_custom_emoji_id
    if is_selected:
        kwargs["style"] = "success"
    return InlineKeyboardButton(**kwargs)
