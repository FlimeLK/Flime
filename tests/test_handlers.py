"""Тести обробників через справжній Dispatcher aiogram з фейковою сесією Telegram."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from itertools import count

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import GetChatMember, GetMe, TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberMember,
    ChatMemberOwner,
    Message,
    MessageId,
    PreCheckoutQuery,
    SuccessfulPayment,
    Update,
    User,
)

from bot import texts
from bot.__main__ import build_dispatcher
from bot.config import Settings
from bot.db import shop as shop_db
from bot.db import users as users_db
from bot.engine.models import Phase
from bot.game.callbacks import NightCb
from bot.game.manager import GameManager
from bot.game.messenger import Messenger
from bot.handlers.common import MenuCb
from bot.handlers.payments import StarsCb
from bot.handlers.roles_builder import RoleCb
from bot.handlers.settings import SetCb
from bot.handlers.shop import BuyCb

OWNER = 1
ADMIN = 2
GROUP = -1001
ids = count(1)


class MockSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []
        # Кому бот не може писати (людина не натискала «Почати»).
        self.unreachable: set[int] = set()

    async def close(self):
        pass

    async def stream_content(self, *a, **kw):  # pragma: no cover
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        name = type(method).__name__
        if isinstance(method, GetMe):
            return User(id=42, is_bot=True, first_name="Хутір", username="test_bot")
        if isinstance(method, GetChatMember):
            user = User(id=method.user_id, is_bot=False, first_name="X")
            if method.user_id in (OWNER, ADMIN):
                return ChatMemberOwner(user=user, is_anonymous=False)
            return ChatMemberMember(user=user)
        if name == "SendMessage" and method.chat_id in self.unreachable:
            raise TelegramForbiddenError(method=method, message="bot can't initiate conversation with a user")
        if name in ("SendMessage", "SendInvoice"):
            chat_type = "private" if method.chat_id > 0 else "supergroup"
            return Message(message_id=next(ids), date=datetime.now(UTC),
                           chat=Chat(id=method.chat_id, type=chat_type), text=getattr(method, "text", None))
        if name == "CopyMessage":
            return MessageId(message_id=next(ids))
        return True

    def texts_to(self, chat_id: int) -> list[str]:
        return [c.text for c in self.calls if type(c).__name__ == "SendMessage" and c.chat_id == chat_id]

    def last_text(self, chat_id: int) -> str:
        return self.texts_to(chat_id)[-1]


def tg_user(uid: int) -> User:
    return User(id=uid, is_bot=False, first_name=f"Гравець{uid}")


def msg(uid: int, text: str, chat_id: int | None = None, **extra) -> Update:
    chat_id = uid if chat_id is None else chat_id
    chat = Chat(id=chat_id, type="private" if chat_id > 0 else "supergroup", title=None if chat_id > 0 else "Хутір")
    return Update(update_id=next(ids), message=Message(
        message_id=next(ids), date=datetime.now(UTC), chat=chat, from_user=tg_user(uid), text=text, **extra))


def cb(uid: int, data: str, chat_id: int | None = None) -> Update:
    chat_id = uid if chat_id is None else chat_id
    chat = Chat(id=chat_id, type="private" if chat_id > 0 else "supergroup")
    m = Message(message_id=next(ids), date=datetime.now(UTC), chat=chat, text="…")
    return Update(update_id=next(ids), callback_query=CallbackQuery(
        id=str(next(ids)), from_user=tg_user(uid), chat_instance="x", data=data, message=m))


@pytest.fixture
async def env(pool):
    session = MockSession()
    bot = Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode="HTML"))
    manager = GameManager(Messenger(bot), pool, "test_bot")
    config = Settings(bot_token="42:TEST", owner_ids=frozenset({OWNER}))
    # Роутери модульні: від'єднуємо їх від диспетчера попереднього тесту.
    from bot import handlers

    for mod in (handlers.lobby, handlers.roles_builder, handlers.start, handlers.profile, handlers.shop, handlers.payments,
                handlers.settings, handlers.owner, handlers.play):
        mod.router._parent_router = None
    dp = build_dispatcher(pool, manager, config)

    async def feed(update: Update):
        await dp.feed_update(bot, update)

    yield feed, session, manager, pool
    await manager.shutdown()


async def test_private_commands(env):
    feed, s, _, pool = env
    await feed(msg(10, "/start"))
    assert "Мафія: Хутір" in s.last_text(10)
    await feed(msg(10, "/profile"))
    assert "Шаги: <b>100</b>" in s.last_text(10)
    await feed(msg(10, "/daily"))
    assert "+50" in s.last_text(10)
    await feed(msg(10, "/daily"))
    assert "уже отримано" in s.last_text(10)
    await feed(msg(10, "/rules"))
    assert "Характерник" in s.last_text(10)

    await feed(msg(10, "/shop"))
    assert "Ярмарок" in s.last_text(10)
    await feed(cb(10, BuyCb(item="obereg").pack()))
    assert await shop_db.inventory(pool, 10) == {"obereg": 1}
    assert (await users_db.get(pool, 10)).shagy == 150 - 120
    await feed(cb(10, BuyCb(item="obereg").pack()))  # не вистачає
    assert await shop_db.inventory(pool, 10) == {"obereg": 1}


async def test_main_menu(env):
    feed, s, _, pool = env
    await feed(msg(12, "/start"))
    start = next(c for c in reversed(s.calls) if type(c).__name__ == "SendMessage" and c.chat_id == 12)
    buttons = [b for row in start.reply_markup.inline_keyboard for b in row]
    assert buttons[0].url == "https://t.me/test_bot?startgroup=true"

    def last_edit() -> str:
        return next(c for c in reversed(s.calls) if type(c).__name__ == "EditMessageText").text

    await feed(cb(12, MenuCb(action="profile").pack()))
    assert "Шаги: <b>100</b>" in last_edit()
    await feed(cb(12, MenuCb(action="shop").pack()))
    assert "Ярмарок" in last_edit()
    await feed(cb(12, MenuCb(action="vip").pack()))
    assert "<b>VIP</b>" in last_edit()
    await feed(cb(12, MenuCb(action="rules").pack()))
    assert "Характерник" in last_edit()
    await feed(cb(12, MenuCb(action="home").pack()))
    assert "Як почати" in last_edit()
    await feed(cb(12, MenuCb(action="daily").pack()))
    alert = next(c for c in reversed(s.calls) if type(c).__name__ == "AnswerCallbackQuery")
    assert "+50" in alert.text and alert.show_alert
    assert (await users_db.get(pool, 12)).shagy == 150

    await feed(msg(12, "/start rules"))
    assert "Правила" in s.last_text(12)


async def test_owner_and_promo(env):
    feed, s, _, pool = env
    await feed(msg(11, "/start"))
    await feed(msg(11, "/owner"))  # не власник — тиша
    assert not any("Панель власника" in t for t in s.texts_to(11))
    await feed(msg(OWNER, "/owner"))
    assert "Панель власника" in s.last_text(OWNER)
    await feed(msg(OWNER, "/give 11 cherv 70"))
    assert (await users_db.get(pool, 11)).chervintsi == 70
    await feed(msg(OWNER, "/promo_new HUTIR 25 0 3 10"))
    await feed(msg(11, "/promo hutir"))
    u = await users_db.get(pool, 11)
    assert u.shagy == 125 and u.is_vip
    await feed(msg(11, "/promo hutir"))
    assert "вже активував" in s.last_text(11)
    await feed(msg(OWNER, "/block 11"))
    before = len(s.calls)
    await feed(msg(11, "/profile"))
    assert len(s.calls) == before  # заблокованим не відповідаємо


async def test_payments(env):
    feed, s, _, pool = env
    await feed(msg(12, "/vip"))
    await feed(cb(12, StarsCb(product="cherv_30").pack()))
    invoice = next(c for c in s.calls if type(c).__name__ == "SendInvoice")
    assert invoice.currency == "XTR" and invoice.prices[0].amount == 140

    bad = PreCheckoutQuery(id="q1", from_user=tg_user(12), currency="XTR", total_amount=1, invoice_payload="cherv_30")
    await feed(Update(update_id=next(ids), pre_checkout_query=bad))
    good = bad.model_copy(update={"id": "q2", "total_amount": 140})
    await feed(Update(update_id=next(ids), pre_checkout_query=good))
    answers = [c for c in s.calls if type(c).__name__ == "AnswerPreCheckoutQuery"]
    assert [a.ok for a in answers] == [False, True]

    paid = SuccessfulPayment(currency="XTR", total_amount=140, invoice_payload="cherv_30",
                             telegram_payment_charge_id="ch_1", provider_payment_charge_id="p1")
    await feed(msg(12, None, successful_payment=paid))
    await feed(msg(12, None, successful_payment=paid))  # повтор не нараховує вдруге
    assert (await users_db.get(pool, 12)).chervintsi == 30

    await feed(cb(12, "exch:20"))
    u = await users_db.get(pool, 12)
    assert u.chervintsi == 10 and u.shagy == 100 + 20 * 50

    await feed(msg(OWNER, "/refund ch_1"))
    assert any(type(c).__name__ == "RefundStarPayment" for c in s.calls)
    assert (await users_db.get(pool, 12)).chervintsi == 0


async def test_settings_admin_only(env):
    feed, s, _, pool = env
    await feed(msg(13, "/settings", GROUP))
    assert "лише адміністратор" in s.last_text(GROUP)
    # Панель приходить адміну в особисті, у групі — лише підтвердження.
    await feed(msg(ADMIN, "/settings", GROUP))
    assert "в особисті" in s.last_text(GROUP)
    assert "Налаштування гри" in s.last_text(ADMIN)
    panel = next(c for c in reversed(s.calls) if type(c).__name__ == "SendMessage" and c.chat_id == ADMIN)
    labels = [b.text for row in panel.reply_markup.inline_keyboard for b in row]
    assert texts.RB_OPEN_BUTTON in labels

    await feed(cb(ADMIN, SetCb(action="toggle", chat=GROUP, key="secret_vote").pack()))
    await feed(cb(ADMIN, SetCb(action="timer", chat=GROUP, key="night_time", delta=15).pack()))
    await feed(cb(ADMIN, SetCb(action="role", chat=GROUP, key="mavka").pack()))
    await feed(cb(13, SetCb(action="toggle", chat=GROUP, key="items_enabled").pack()))  # не адмін
    row = await pool.fetchrow("SELECT * FROM group_settings WHERE chat_id = $1", GROUP)
    assert row["secret_vote"] and row["night_time"] == 75 and list(row["disabled_roles"]) == ["mavka"]
    assert row["items_enabled"]


async def test_game_via_handlers(env):
    feed, s, manager, pool = env
    players = [ADMIN, 21, 22, 23, 24, 25]
    await feed(msg(21, "/game", GROUP))
    runner = manager.get(GROUP)
    assert runner is not None
    await asyncio.sleep(0.05)
    await feed(msg(21, "/game", GROUP))
    assert "вже йде" in s.last_text(GROUP)
    for uid in players:
        await feed(msg(uid, f"/start join{GROUP}"))
        assert "записано" in s.last_text(uid)
    await feed(msg(25, "/leave", GROUP))
    assert 25 not in runner.game.players
    await feed(msg(22, "/start_now", GROUP))
    assert "лише адміністратор" in s.last_text(GROUP)
    await feed(msg(21, "/start_now", GROUP))  # хто почав збір — може
    for _ in range(100):
        if runner.game.phase == Phase.NIGHT and runner._pending:
            break
        await asyncio.sleep(0.02)
    game = runner.game
    assert all("Твоя роль" in "".join(s.texts_to(uid)) for uid in game.players)

    # Рада нечисті: повідомлення відьми доходить до інших з нечисті (якщо вони є).
    witch = game.by_role("vidma")[0]
    await feed(msg(witch.user_id, "кого беремо?"))
    for ally in game.team_alive(witch.team):
        if ally is not witch:
            assert "кого беремо?" in s.last_text(ally.user_id)

    victim = next(p for p in game.alive() if p.team != witch.team)
    await feed(cb(witch.user_id, NightCb(chat=GROUP, kind="kill", target=victim.user_id).pack()))
    assert game.evil_votes[witch.user_id] == victim.user_id
    await feed(cb(victim.user_id, NightCb(chat=GROUP, kind="kill", target=witch.user_id).pack()))
    assert victim.user_id not in game.evil_votes

    await feed(msg(22, "/stop", GROUP))
    assert manager.get(GROUP) is not None
    await feed(msg(ADMIN, "/stop", GROUP))
    assert manager.get(GROUP) is None
    assert "зупинено" in s.last_text(GROUP)


async def test_custom_roles_builder(env):
    feed, s, manager, pool = env
    from bot.db import custom_roles as roles_db

    await feed(msg(ADMIN, "/role", GROUP))
    assert "в особисті" in s.last_text(GROUP)
    assert "Своїх ролей ще немає" in s.last_text(ADMIN)
    await feed(msg(40, "/start roles-1001"))
    assert "лише адміністратори" in s.last_text(40)
    await feed(msg(ADMIN, "/start roles-1001"))
    assert "Своїх ролей ще немає" in s.last_text(ADMIN)

    await feed(cb(ADMIN, RoleCb(action="new", chat=GROUP).pack()))
    await feed(msg(ADMIN, "Відьма"))  # назва стандартної ролі
    assert "не підходить" in s.last_text(ADMIN)
    await feed(msg(ADMIN, "Мольфар"))
    assert "Мольфар" in s.last_text(ADMIN)
    [role] = await roles_db.list_for_chat(pool, GROUP)

    async def press(action: str, val: str = "") -> None:
        await feed(cb(ADMIN, RoleCb(action=action, chat=GROUP, role=role.id, val=val).pack()))

    await press("team")
    assert (await roles_db.get(pool, role.id)).team == "evil"
    await press("team")
    await press("setab", "kill")
    await press("plus")
    await press("minus")
    await press("desc")
    await feed(msg(ADMIN, "Карпатський чаклун."))
    r = await roles_db.get(pool, role.id)
    assert (r.team, r.ability, r.min_players, r.description) == ("village", "kill", 4, "Карпатський чаклун.")
    await feed(cb(40, RoleCb(action="toggle", chat=GROUP, role=role.id).pack()))  # не адмін
    assert (await roles_db.get(pool, role.id)).enabled

    # Роль роздається в грі.
    await feed(msg(ADMIN, "/game", GROUP))
    for uid in (41, 42, 43, 44):
        await feed(msg(uid, "/start join-1001"))
    await feed(msg(ADMIN, "/start_now", GROUP))
    runner = manager.get(GROUP)
    for _ in range(100):
        if runner.game.phase == Phase.NIGHT and runner._pending:
            break
        await asyncio.sleep(0.02)
    holder = next(p for p in runner.game.players.values() if p.role == r.key)
    assert any("Мольфар" in t for t in s.texts_to(holder.user_id))
    assert any("раз за гру" in t for t in s.texts_to(holder.user_id))
    await feed(msg(ADMIN, "/stop", GROUP))

    await press("del")
    await press("delok")
    assert await roles_db.list_for_chat(pool, GROUP) == []


async def test_settings_fallback_link_when_pm_closed(env):
    feed, s, _, _ = env
    s.unreachable.add(ADMIN)
    await feed(msg(ADMIN, "/settings", GROUP))
    reply = next(c for c in reversed(s.calls) if type(c).__name__ == "SendMessage" and c.chat_id == GROUP)
    assert reply.reply_markup.inline_keyboard[0][0].url == "https://t.me/test_bot?start=settings-1001"
    s.unreachable.clear()
    await feed(msg(ADMIN, "/start settings-1001"))
    assert "Налаштування гри" in s.last_text(ADMIN)
    await feed(msg(13, "/start settings-1001"))
    assert "лише адміністратори" in s.last_text(13)


async def test_testgame_command(env):
    feed, s, manager, _ = env
    await feed(msg(13, "/testgame", GROUP))
    assert "лише адміністратор" in s.last_text(GROUP)
    await feed(msg(ADMIN, "/testgame 3", GROUP))
    assert "Тестова гра" in s.last_text(GROUP)
    runner = manager.get(GROUP)
    assert runner.is_test and sorted(runner.game.players) == [-3, -2, -1]
    await feed(msg(ADMIN, "/testgame", GROUP))
    assert "вже йде" in s.last_text(GROUP)
    await feed(msg(ADMIN, "/stop", GROUP))
