"""Димовий прогін: усі команди від власника, адміна й гравця в особистих і в групі,
плюс натискання кожної кнопки, яку бот показав (обхід у ширину). Жодна дія не має падати."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from tests.test_handlers import ADMIN, GROUP, OWNER, cb, env, msg  # noqa: F401

COMMANDS = [
    "/start", "/help", "/rules", "/profile", "/me", "/shop", "/daily", "/vip", "/promo", "/promo NOPE",
    "/top", "/settings", "/game", "/leave", "/start_now", "/stop", "/cancel",
    "/owner", "/design", "/emoji", "/emoji_id", "/emoji_set", "/emoji_set fire", "/emoji_set nokey 🔥",
    "/emoji_reset", "/emoji_reset fire", "/emoji_pack", "/media", "/media nope", "/media_clear",
    "/media_clear night", "/give", "/give abc", "/give 5 10", "/vip_give", "/vip_give 5 3", "/block",
    "/block 5", "/unblock 5", "/broadcast", "/promo_new", "/promo_new X 10", "/promo_list", "/promo_del X",
    "/purchases", "/refund", "/refund 1", "/games", "/start newrole-1001", "/start myroles-1001",
    "/start join-1001", "/start newrole123", "hello",
]
PLAYER = 7

def _buttons(session, seen: set[str]) -> list[tuple[int, str]]:
    found = []
    for call in session.calls:
        markup = getattr(call, "reply_markup", None)
        chat_id = getattr(call, "chat_id", None)
        if not isinstance(markup, InlineKeyboardMarkup) or not isinstance(chat_id, int):
            continue
        for row in markup.inline_keyboard:
            for b in row:
                if b.callback_data and (chat_id, b.callback_data) not in seen:
                    seen.add((chat_id, b.callback_data))
                    found.append((chat_id, b.callback_data))
    return found


async def test_crawl_everything(env):  # noqa: F811
    feed, s, manager, pool = env
    for uid in (OWNER, ADMIN, PLAYER):
        for chat in (uid, GROUP):
            for text in COMMANDS:
                await feed(msg(uid, text, chat))
    seen: set = set()
    pressed = 0
    for _ in range(6):
        queue = _buttons(s, seen)
        if not queue:
            break
        for chat_id, data in queue:
            for uid in (OWNER, PLAYER):
                await feed(cb(uid, data, chat_id))
                pressed += 1
    assert pressed > 50
