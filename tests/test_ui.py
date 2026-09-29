"""Анімовані емодзі, кнопки, запасний варіант і коректність HTML у текстах."""

from __future__ import annotations

from html.parser import HTMLParser

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import InlineKeyboardMarkup

from bot import texts
from bot.engine.items import ITEMS
from bot.engine.roles import ROLES, Team
from bot.ui import emoji
from bot.ui.buttons import DANGER, btn
from bot.ui.safe import CustomEmojiFallback, has_custom_emoji, rendered


@pytest.fixture(autouse=True)
def fresh_emoji():
    emoji.configure(True)
    yield
    emoji.configure(True)


def test_every_role_and_item_has_emoji_key():
    for key in [k for k, r in ROLES.items() if not r.custom] + list(ITEMS):
        assert key in emoji.DEFAULTS, key


def test_e_icon_render():
    cid = emoji.DEFAULTS["vovkulaka"].id
    assert emoji.e("vovkulaka") == f'<tg-emoji emoji-id="{cid}">🐺</tg-emoji>'
    assert emoji.e("selianyn") == "👨‍🌾"  # без ID - звичайний символ
    assert emoji.icon("vovkulaka") == cid
    assert emoji.render(":vovkulaka: вийшов") == f'<tg-emoji emoji-id="{cid}">🐺</tg-emoji> вийшов'
    assert emoji.render(":vovkulaka: вийшов", html=False) == "🐺 вийшов"
    assert emoji.render("о 12:30 :unknown: https://t.me/x") == "о 12:30 :unknown: https://t.me/x"
    assert emoji.strip(emoji.render(":fire::fire:")) == "🔥🔥"


def test_override_and_disable():
    emoji.set_override("selianyn", "123")
    assert emoji.e("selianyn") == '<tg-emoji emoji-id="123">👨‍🌾</tg-emoji>'
    emoji.configure(False, {"selianyn": "123"})
    assert emoji.e("selianyn") == "👨‍🌾"
    assert emoji.icon("fire") is None
    assert btn("Вогонь", "x", emo="fire").text == "🔥Вогонь"


def test_button_icon_and_style():
    b = btn("Убити", "cb", emo="evil", style=DANGER)
    assert b.icon_custom_emoji_id == emoji.DEFAULTS["evil"].id
    assert b.style == DANGER and b.text == "Убити"


def test_rendered_method_fields():
    m = rendered(SendMessage(chat_id=1, text=":fire: гаряче"))
    assert "<tg-emoji" in m.text
    a = rendered(AnswerCallbackQuery(callback_query_id="1", text=":fire: гаряче"))
    assert a.text == "🔥 гаряче"


async def test_fallback_resends_plain():
    calls = []

    async def make_request(bot, method):
        calls.append(method)
        if has_custom_emoji(method):
            raise TelegramBadRequest(method=method, message="Bad Request: DOCUMENT_INVALID")
        return "ok"

    markup = InlineKeyboardMarkup(inline_keyboard=[[btn("Так", "y", emo="ok")]])
    result = await CustomEmojiFallback()(make_request, None, SendMessage(chat_id=1, text=":ok: так", reply_markup=markup))
    assert result == "ok"
    assert len(calls) == 2
    assert calls[1].text == "✅ так"
    assert calls[1].reply_markup.inline_keyboard[0][0].icon_custom_emoji_id is None


async def test_fallback_does_not_retry_unrelated_errors():
    async def make_request(bot, method):
        raise TelegramBadRequest(method=method, message="Bad Request: message is not modified")

    with pytest.raises(TelegramBadRequest):
        await CustomEmojiFallback()(make_request, None, SendMessage(chat_id=1, text=":ok:"))


# ---------- HTML у всіх текстах ----------

ALLOWED = {"b", "i", "u", "s", "code", "pre", "a", "blockquote", "tg-spoiler", "tg-emoji"}


class Checker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        assert tag in ALLOWED, tag
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack and self.stack[-1] == tag, (tag, self.stack)
        self.stack.pop()


def samples() -> list[str]:
    p = [(1, "Оксана <3"), (2, "Тарас")]
    out = [
        texts.start('Оксана <b>'), texts.rules(), texts.SECTION_HOWTO, texts.SECTION_GAME, texts.section_roles(),
        texts.section_items(), texts.section_profile('картка'), texts.section_daily('ok'), texts.SECTION_VIP,
        texts.settings_home('Хутір <3'), texts.SETTINGS_TIMERS_HEAD, texts.SETTINGS_VOTE_HEAD, texts.SETTINGS_ITEMS_HEAD, texts.lobby(p, 75, 4), texts.lobby([], 90, 4),
        texts.game_started(5, ["a", "b"]), texts.night_start(2, p),
        texts.morning(2, [(1, "Оксана", "evil", "vidma"), (2, "Тарас", "wolf", None)], 1), texts.morning(1, [], 0),
        texts.vote_results([("x", 3), (":skip: Нікого", 1)]), texts.vote_results([]),
        texts.CONFIRM_ASK.format(name="X", yes=1, no=2),
        texts.game_over(Team.VILLAGE, ["a"], ["b"], 3), texts.game_over("draw", [], ["b"], 3),
        texts.profile("Ім'я <b>", 10, 2, "01.01.2027", 5, 3, ["x"]), texts.profile("N", 0, 0, None, 0, 0, []),
        texts.shop(100, {"obereg": 2}, 3), texts.vip_menu(3, None, 60, 50), texts.promo_ok(1, 2, 3),
        texts.SETTINGS_ROLES_HEAD, texts.TOP_HEAD,
    ]
    out += [texts.role_card(k, ["honey"], ["ally"]) for k in ROLES]
    out += list(texts.NIGHT_PROMPTS.values()) + list(texts.YOU_SAVED.values())
    out += [v for k, v in vars(texts).items() if k.isupper() and isinstance(v, str)]
    return out


@pytest.mark.parametrize("enabled", [True, False])
def test_all_texts_are_valid_html(enabled):
    emoji.configure(enabled)
    for raw in samples():
        html = emoji.render(raw.replace("{", "").replace("}", ""))
        c = Checker()
        c.feed(html)
        c.close()
        assert not c.stack, (raw[:60], c.stack)
        assert not [t for t in emoji.TOKEN_RE.findall(html) if t in emoji.DEFAULTS], raw[:60]


def test_no_separator_lines_or_command_lists_in_menu():
    for raw in samples():
        assert "┈" not in raw, raw[:60]
    sections = [texts.SECTION_HOWTO, texts.SECTION_GAME, texts.SECTION_VIP, texts.section_roles(),
                texts.section_items(), texts.section_profile(texts.profile("N", 1, 0, None, 0, 0, [])),
                texts.section_daily("ok")]
    for text in sections:
        assert "<code>/" not in text and "/vip" not in text and "/shop" not in text, text[:60]
