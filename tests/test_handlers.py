"""Тести обробників через справжній Dispatcher aiogram з фейковою сесією Telegram."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from itertools import count

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetChatMember, GetMe, TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberMember,
    ChatMemberOwner,
    Message,
    MessageEntity,
    MessageId,
    PhotoSize,
    PreCheckoutQuery,
    SuccessfulPayment,
    Update,
    User,
)

from bot.__main__ import build_dispatcher, setup_bot
from bot.config import Settings
from bot.db import shop as shop_db
from bot.db import users as users_db
from bot.engine.models import Phase
from bot.game.callbacks import NightCb
from bot.game.manager import GameManager
from bot.game.messenger import Messenger
from bot.handlers.payments import StarsCb
from bot.handlers.settings import SetCb
from bot.handlers.shop import BuyCb
from bot.ui import emoji

OWNER = 1
ADMIN = 2
GROUP = -1001
ids = count(1)


class MockSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []

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
        if name in ("SendMessage", "SendInvoice", "SendPhoto", "SendAnimation", "SendVideo"):
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
    bot = setup_bot(Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode="HTML")))
    emoji.configure(True)
    manager = GameManager(Messenger(bot), pool, "test_bot")
    config = Settings(bot_token="42:TEST", owner_ids=frozenset({OWNER}))
    # Роутери модульні: від'єднуємо їх від диспетчера попереднього тесту.
    from bot import handlers

    for mod in vars(handlers).values():
        if hasattr(mod, "router"):
            mod.router._parent_router = None
    dp = build_dispatcher(pool, manager, config)

    async def feed(update: Update):
        await dp.feed_update(bot, update)

    yield feed, session, manager, pool
    await manager.shutdown()


async def test_private_commands(env):
    feed, s, _, pool = env
    await feed(msg(10, "/start"))
    assert "Консильєре" in s.last_text(10) and "Гравець10" in s.last_text(10)
    await feed(msg(10, "/profile"))
    assert "Ліри: <b>100</b>" in s.last_text(10)
    await feed(msg(10, "/daily"))
    assert "+50" in s.last_text(10)
    await feed(msg(10, "/daily"))
    assert "уже отримано" in s.last_text(10)
    await feed(msg(10, "/rules"))
    assert "Комісар" in s.last_text(10)

    await feed(msg(10, "/shop"))
    assert "ЧОРНИЙ РИНОК" in s.last_text(10)
    await feed(cb(10, BuyCb(item="obereg").pack()))
    assert await shop_db.inventory(pool, 10) == {"obereg": 1}
    assert (await users_db.get(pool, 10)).shagy == 150 - 120
    await feed(cb(10, BuyCb(item="obereg").pack()))  # не вистачає
    assert await shop_db.inventory(pool, 10) == {"obereg": 1}


async def test_owner_and_promo(env):
    feed, s, _, pool = env
    await feed(msg(11, "/start"))
    await feed(msg(11, "/owner"))  # не власник - тиша
    assert not any("КАБІНЕТ ДОНА" in t for t in s.texts_to(11))
    await feed(msg(OWNER, "/owner"))
    assert "КАБІНЕТ ДОНА" in s.last_text(OWNER)
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


async def test_owner_panel(env):
    feed, s, manager, pool = env
    from bot.keyboards import OwnCb

    def last_edit():
        return [c for c in s.calls if type(c).__name__ == "EditMessageText"][-1].text

    await feed(msg(21, "/start"))
    await feed(msg(22, "/start"))
    await feed(msg(OWNER, "/owner"))
    home = [c for c in s.calls if type(c).__name__ == "SendMessage" and c.chat_id == OWNER][-1].reply_markup
    assert [len(r) for r in home.inline_keyboard] == [2, 2, 2, 1]

    # Не власник не може тиснути кнопки кабінету
    await feed(cb(21, OwnCb(action="give", value="21.shagy.1000").pack()))
    assert (await users_db.get(pool, 21)).shagy == 100

    # Гравець: пошук за ID і кнопки
    await feed(cb(OWNER, OwnCb(action="player").pack()))
    await feed(msg(OWNER, "abc"))
    assert "лише цифри" in s.last_text(OWNER)
    await feed(msg(OWNER, "21"))
    assert "ID <code>21</code>" in s.last_text(OWNER)
    await feed(cb(OWNER, OwnCb(action="give", value="21.shagy.1000").pack()))
    await feed(cb(OWNER, OwnCb(action="give", value="21.cherv.10").pack()))
    await feed(cb(OWNER, OwnCb(action="give", value="21.cherv.-100").pack()))  # у мінус не йдемо
    await feed(cb(OWNER, OwnCb(action="vip", value="21.30").pack()))
    await feed(cb(OWNER, OwnCb(action="block", value="21").pack()))
    u = await users_db.get(pool, 21)
    assert u.shagy == 1100 and u.chervintsi == 10 and u.is_vip and u.blocked
    assert "Заблокований" in last_edit()
    await feed(cb(OWNER, OwnCb(action="block", value="21").pack()))
    assert not (await users_db.get(pool, 21)).blocked

    # Промокоди
    await feed(cb(OWNER, OwnCb(action="promo_new").pack()))
    await feed(msg(OWNER, "погано"))
    assert "Не розібрав" in s.last_text(OWNER)
    await feed(msg(OWNER, "CIAO 10 0 0 5"))
    assert "CIAO" in s.last_text(OWNER)
    await feed(cb(OWNER, OwnCb(action="promos").pack()))
    assert "CIAO" in last_edit()
    await feed(cb(OWNER, OwnCb(action="promo_del", value="CIAO").pack()))
    assert "ще немає" in last_edit()

    # Розсилка: превʼю, потім підтвердження
    await feed(cb(OWNER, OwnCb(action="bc").pack()))
    await feed(msg(OWNER, "Бонджорно, сім'я!"))
    assert "Розіслати" in s.last_text(OWNER)
    await feed(cb(OWNER, OwnCb(action="bc_go").pack()))
    copies = [c for c in s.calls if type(c).__name__ == "CopyMessage"]
    assert {c.chat_id for c in copies} >= {21, 22}
    assert "Доставлено" in s.last_text(OWNER)

    # Покупки, ігри, оформлення, назад
    for action, word in (("buys", "покупки"), ("games", "Ігри"), ("design", "ОФОРМЛЕННЯ"), ("home", "КАБІНЕТ")):
        await feed(cb(OWNER, OwnCb(action=action).pack()))
        assert word in last_edit(), action

    # Зупинка гри з кабінету
    await feed(msg(21, "/game", GROUP))
    await asyncio.sleep(0.05)
    await feed(cb(OWNER, OwnCb(action="stop", value=str(GROUP)).pack()))
    assert "Зупинити гру" in last_edit()
    await feed(cb(OWNER, OwnCb(action="stop_go", value=str(GROUP)).pack()))
    assert manager.get(GROUP) is None


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
    await feed(msg(ADMIN, "/settings", GROUP))
    # Панель іде в особисті адміна, у групі - коротка відповідь з кнопкою
    assert "Налаштування сім'ї" in s.last_text(ADMIN)
    assert "в особистих" in s.last_text(GROUP)
    home = [c for c in s.calls if type(c).__name__ == "SendMessage" and c.chat_id == ADMIN][-1].reply_markup
    assert [len(r) for r in home.inline_keyboard] == [2, 2, 1, 1]
    labels = [b.text for r in home.inline_keyboard for b in r]
    assert "Кастомні налаштування" in labels and "Омерта" not in labels
    # Кастомні налаштування: реєстрація, розмір сім'ї, омерта, власні ролі, скидання
    await feed(cb(ADMIN, SetCb(action="custom", chat=GROUP).pack()))
    custom = [c for c in s.calls if type(c).__name__ == "EditMessageText"][-1]
    assert "Кастомні налаштування" in custom.text
    labels = [b.text for r in custom.reply_markup.inline_keyboard for b in r]
    for label in ("Реєстрація", "Розмір сім'ї", "Омерта", "Створити роль", "Мої ролі", "Скинути все"):
        assert label in labels, label
    back = custom.reply_markup.inline_keyboard[-1][0].callback_data
    assert back == SetCb(action="home", chat=GROUP).pack()
    # Натискання в особистих: chat у callback - це група
    await feed(cb(ADMIN, SetCb(action="toggle", key="secret_vote", chat=GROUP).pack()))
    await feed(cb(ADMIN, SetCb(action="timer", key="night_time", delta=15, chat=GROUP).pack()))
    await feed(cb(ADMIN, SetCb(action="role", key="mavka", chat=GROUP).pack()))
    await feed(cb(ADMIN, SetCb(action="item", key="honey", chat=GROUP).pack()))
    await feed(cb(ADMIN, SetCb(action="ratio", key="many", chat=GROUP).pack()))
    await feed(cb(ADMIN, SetCb(action="players", key="min_players", delta=2, chat=GROUP).pack()))
    await feed(cb(ADMIN, SetCb(action="toggle", key="omerta_dead", chat=GROUP).pack()))
    await feed(cb(13, SetCb(action="toggle", key="items_enabled", chat=GROUP).pack(), 13))  # не адмін
    row = await pool.fetchrow("SELECT * FROM group_settings WHERE chat_id = $1", GROUP)
    assert row["secret_vote"] and row["night_time"] == 75 and list(row["disabled_roles"]) == ["mavka"]
    assert row["items_enabled"] and list(row["disabled_items"]) == ["honey"]
    assert row["mafia_ratio"] == "many" and row["min_players"] == 6 and row["omerta_dead"]

    # /settings в особистих - список чатів, де він адмін
    await feed(msg(ADMIN, "/settings"))
    assert "Обери чат" in s.last_text(ADMIN)

    # Скинути все
    await feed(cb(ADMIN, SetCb(action="reset_ok", chat=GROUP).pack()))
    row = await pool.fetchrow("SELECT * FROM group_settings WHERE chat_id = $1", GROUP)
    assert not row["secret_vote"] and row["mafia_ratio"] == "normal" and row["title"] == "Хутір"


async def test_settings_pm_fallback(env):
    feed, s, _, pool = env
    from aiogram.exceptions import TelegramForbiddenError

    original = s.make_request

    async def blocked(bot, method, timeout=None):
        if type(method).__name__ == "SendMessage" and method.chat_id == ADMIN:
            raise TelegramForbiddenError(method=method, message="Forbidden: bot can't initiate conversation")
        return await original(bot, method, timeout)

    s.make_request = blocked
    await feed(msg(ADMIN, "/settings", GROUP))
    last = [c for c in s.calls if type(c).__name__ == "SendMessage" and c.chat_id == GROUP][-1]
    assert f"start=settings{GROUP}" in last.reply_markup.inline_keyboard[0][0].url
    s.make_request = original
    await feed(msg(ADMIN, f"/start settings{GROUP}"))
    assert "Налаштування сім'ї" in s.last_text(ADMIN)
    await feed(msg(13, f"/start settings{GROUP}"))
    assert "лише адміністратор" in s.last_text(13)


async def test_omerta(env):
    feed, s, manager, pool = env
    await feed(msg(ADMIN, "/settings", GROUP))
    await feed(cb(ADMIN, SetCb(action="toggle", key="omerta_dead", chat=GROUP).pack()))
    await feed(cb(ADMIN, SetCb(action="toggle", key="omerta_night", chat=GROUP).pack()))
    players = [51, 52, 53, 54]
    await feed(msg(51, "/game", GROUP))
    runner = manager.get(GROUP)
    await asyncio.sleep(0.05)
    for uid in players:
        await feed(msg(uid, f"/start join{GROUP}"))
    await feed(msg(51, "/start_now", GROUP))
    for _ in range(100):
        if runner.game.phase == Phase.NIGHT:
            break
        await asyncio.sleep(0.02)

    def deleted() -> int:
        return sum(type(c).__name__ == "DeleteMessage" for c in s.calls)

    await feed(msg(52, "я мирний!", GROUP))  # уночі гравці мовчать
    assert deleted() == 1
    await feed(msg(99, "глядач", GROUP))  # не гравець - не чіпаємо
    await feed(msg(52, "/leave", GROUP))  # команди проходять
    assert deleted() == 1
    runner.game.phase = Phase.DAY
    await feed(msg(52, "вдень можна", GROUP))
    assert deleted() == 1
    runner.game.players[53].alive = False
    await feed(msg(53, "мене вбили", GROUP))  # мертві мовчать
    assert deleted() == 2
    await feed(msg(ADMIN, "/stop", GROUP))


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
    await feed(msg(21, "/start_now", GROUP))  # хто почав збір - може
    for _ in range(100):
        if runner.game.phase == Phase.NIGHT and runner._pending:
            break
        await asyncio.sleep(0.02)
    game = runner.game
    assert all("ТВОЯ РОЛЬ" in "".join(s.texts_to(uid)) for uid in game.players)

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


async def test_design_tools(env):
    feed, s, _, pool = env
    # /emoji_set з premium-емодзі в самому повідомленні
    text = "/emoji_set storozh 🌾"
    ent = MessageEntity(type="custom_emoji", offset=len("/emoji_set storozh "), length=2, custom_emoji_id="777")
    await feed(msg(OWNER, text, entities=[ent]))
    assert emoji.custom_id("storozh") == "777"
    assert await pool.fetchval("SELECT custom_id FROM emoji_overrides WHERE key = 'storozh'") == "777"
    await feed(msg(OWNER, "/emoji"))
    assert any('emoji-id="777"' in t for t in s.texts_to(OWNER))
    await feed(msg(OWNER, "/emoji_reset storozh"))
    assert emoji.custom_id("storozh") is None

    # /media відповіддю на фото → /start надсилає фото з підписом
    photo_msg = Message(message_id=next(ids), date=datetime.now(UTC), chat=Chat(id=OWNER, type="private"),
                        from_user=tg_user(OWNER), photo=[PhotoSize(file_id="PHOTO1", file_unique_id="u",
                                                                   width=10, height=10)])
    await feed(msg(OWNER, "/media start", reply_to_message=photo_msg))
    assert await pool.fetchval("SELECT file_id FROM media WHERE slot = 'start'") == "PHOTO1"
    await feed(msg(30, "/start"))
    photo = [c for c in s.calls if type(c).__name__ == "SendPhoto"][-1]
    assert photo.photo == "PHOTO1" and "Консильєре" in photo.caption and "<tg-emoji" in photo.caption
    assert photo.reply_markup.inline_keyboard[0][0].icon_custom_emoji_id
    await feed(msg(OWNER, "/media_clear start"))
    await feed(msg(30, "/start"))
    assert "Консильєре" in s.last_text(30)

    # звичайний гравець не має доступу
    await feed(msg(30, "/emoji_set fire"))
    assert emoji.custom_id("fire") == emoji.DEFAULTS["fire"].id


async def test_menu_and_sections(env):
    feed, s, _, pool = env

    def edits():
        return [c for c in s.calls if type(c).__name__ == "EditMessageText"]

    await feed(msg(31, "/start"))
    menu = [c for c in s.calls if type(c).__name__ == "SendMessage" and c.chat_id == 31][-1].reply_markup
    assert [len(r) for r in menu.inline_keyboard] == [1, 2, 2, 2, 1]
    assert all(b.icon_custom_emoji_id for row in menu.inline_keyboard for b in row)
    assert menu.inline_keyboard[0][0].callback_data == "sec:howto"

    for name, marker in [("howto", "в групу"), ("game", "Правила сім'ї"), ("roles", "Комісар"),
                         ("items", "Талісман"), ("profile", "Ліри"), ("daily", "+50"), ("vip", "VIP")]:
        await feed(cb(31, f"sec:{name}"))
        last = edits()[-1]
        assert marker in last.text, name
        assert last.reply_markup.inline_keyboard[0][0].callback_data == "menu:main"
    await feed(cb(31, "menu:main"))
    assert "Обирай, з чого почнемо" in edits()[-1].text


async def test_settings_modules(env):
    feed, s, _, pool = env

    def last_edit():
        return [c for c in s.calls if type(c).__name__ == "EditMessageText"][-1]

    for module, word in (("timers", "Таймери"), ("lobby", "Реєстрація"), ("family", "Розмір сім'ї"),
                         ("omerta", "Омерта"), ("items", "Арсенал"), ("roles", "Хто є хто"), ("reset", "Скинути"),
                         ("custom", "Кастомні")):
        await feed(cb(ADMIN, SetCb(action=module, chat=GROUP).pack()))
        assert word in last_edit().text, module
        # Із кастомних модулів «Назад» веде в кастомні налаштування
        back = last_edit().reply_markup.inline_keyboard[-1][-1].callback_data
        if module in ("lobby", "family", "omerta", "reset"):
            assert back == SetCb(action="custom", chat=GROUP).pack(), module
    await feed(cb(ADMIN, SetCb(action="vote", chat=GROUP).pack()))
    assert len(last_edit().reply_markup.inline_keyboard) == 3  # 2 перемикачі + Назад
    await feed(cb(ADMIN, SetCb(action="refresh", chat=GROUP).pack()))
    assert "Налаштування сім'ї" in last_edit().text
    # Старі панелі в групі (без chat) теж працюють
    await feed(cb(ADMIN, SetCb(action="timers").pack(), GROUP))
    assert "Таймери" in last_edit().text


async def test_custom_role_wizard_and_game(env):
    feed, s, manager, pool = env
    from bot.engine.roles import ROLES
    from bot.keyboards import RoleCb

    # Не адмін групи - відмова
    await feed(msg(13, f"/start newrole{GROUP}"))
    assert "лише адміністратори" in s.last_text(13)

    # Адмін проходить майстер
    await feed(msg(ADMIN, f"/start newrole{GROUP}"))
    assert "Нова роль" in s.last_text(ADMIN)
    await feed(msg(ADMIN, "x" * 30))
    assert "від 1 до 24" in s.last_text(ADMIN)
    await feed(msg(ADMIN, "Мисливець"))
    await feed(msg(ADMIN, "abc"))
    assert "емодзі" in s.last_text(ADMIN)
    await feed(msg(ADMIN, "🏹"))
    await feed(msg(ADMIN, "Полює на нечисть <вночі>"))
    await feed(cb(ADMIN, RoleCb(action="team", value="village").pack()))
    await feed(cb(ADMIN, RoleCb(action="ability", value="kill").pack()))
    await feed(cb(ADMIN, RoleCb(action="min", value="4").pack()))
    preview = [c for c in s.calls if type(c).__name__ == "EditMessageText"][-1].text
    assert "Мисливець" in preview and "&lt;вночі&gt;" in preview and "Вбивати" in preview
    await feed(cb(ADMIN, RoleCb(action="save").pack()))
    row = await pool.fetchrow("SELECT * FROM custom_roles WHERE chat_id = $1", GROUP)
    assert row["name"] == "Мисливець" and row["team"] == "village" and row["ability"] == "kill"
    key = f"c{row['id']}"

    # Роль видно в /settings → Хто є хто; вимкнути й знову увімкнути
    await feed(cb(ADMIN, SetCb(action="roles", chat=GROUP).pack()))
    kb = [c for c in s.calls if type(c).__name__ == "EditMessageText"][-1].reply_markup
    labels = [b.text for r in kb.inline_keyboard for b in r]
    assert any("Мисливець" in t for t in labels)
    assert RoleCb(action="new", value=str(GROUP)).pack() in [b.callback_data for r in kb.inline_keyboard for b in r]
    await feed(cb(ADMIN, SetCb(action="crole", key=str(row["id"]), chat=GROUP).pack()))
    assert await pool.fetchval("SELECT enabled FROM custom_roles WHERE id = $1", row["id"]) is False
    await feed(cb(ADMIN, SetCb(action="crole", key=str(row["id"]), chat=GROUP).pack()))

    # Кнопка «Створити роль» з панелі запускає майстер
    await feed(cb(ADMIN, RoleCb(action="new", value=str(GROUP)).pack()))
    assert "Нова роль" in s.last_text(ADMIN)
    await feed(msg(ADMIN, "/cancel"))
    await feed(cb(13, RoleCb(action="new", value=str(GROUP)).pack()))  # не адмін - нічого

    # Гра: власна роль роздається й отримує свою нічну підказку
    players = [ADMIN, 41, 42, 43, 44]
    await feed(msg(41, "/game", GROUP))
    runner = manager.get(GROUP)
    await asyncio.sleep(0.05)
    for uid in players:
        await feed(msg(uid, f"/start join{GROUP}"))
    await feed(msg(41, "/start_now", GROUP))
    for _ in range(100):
        if runner.game.phase == Phase.NIGHT and runner._pending:
            break
        await asyncio.sleep(0.02)
    hunter = next(p for p in runner.game.players.values() if p.role == key)
    assert ROLES[key].name == "Мисливець"
    assert any("Мисливець" in t for t in s.texts_to(hunter.user_id))
    assert any("Кого приберемо" in t for t in s.texts_to(hunter.user_id))
    target = next(p for p in runner.game.alive() if p.user_id != hunter.user_id)
    await feed(cb(hunter.user_id, NightCb(chat=GROUP, kind="ckill", target=target.user_id).pack()))
    assert runner.game.actions[f"{hunter.user_id}:role"].target == target.user_id
    await feed(msg(ADMIN, "/stop", GROUP))

    # Мої ролі → видалити
    await feed(msg(ADMIN, f"/start myroles{GROUP}"))
    assert "Власні ролі" in s.last_text(ADMIN)
    await feed(cb(ADMIN, RoleCb(action="delete", value=str(row["id"])).pack()))
    assert await pool.fetchval("SELECT count(*) FROM custom_roles") == 0
