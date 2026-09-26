import asyncio
import os
from datetime import datetime
from logging import INFO, basicConfig
from aiogram import Bot, Dispatcher
from aiogram.types import (
    Message,
    CallbackQuery,
    BotCommandScopeDefault,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllChatAdministrators,
)
from aiogram import Router
from aiogram.types.bot_command import BotCommand
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.enums import ChatType

# Токен бота береться з env (рекомендовано через systemd EnvironmentFile або .env)
TOKEN = (os.getenv("BOT_TOKEN") or "").strip()

# Перевірка наявності токена
if not TOKEN:
    raise ValueError("Помилка: BOT_TOKEN не вказаний у змінних середовища.")

# Імпортуємо модулі
from commands.start import router_start, grant_welcome_bonus_if_needed
from commands.support import router_support
from commands.buy import router_pay
from commands.play import PlayCommand
from commands.construct_event import ConstructEvent
from commands.founder import router_founder
from commands.buff_shop import router_buff_shop
from commands.marigolds import router_marigolds
from commands.promocode import router_promocode
from commands.group_admin import router_group_admin
from commands.contraband import router_contraband
from commands.casino import router_casino
from commands.kupala import router_kupala
from commands.roulette import router_roulette
from commands.story_achievements import router_story
from database.database import initialize_db, conn, cursor, is_user_blocked, touch_known_group, is_bot_command_disabled
from commands.group_admin import BOT_OWNER_IDS
from commands.command_switch import router_command_switch

# Ініціалізація бази даних (if not already initialized at module import)
# Note: initialize_db() is also called at module import time in database.py
# This call ensures initialization if module was imported elsewhere first
if conn is None or cursor is None:
    try:
        initialize_db()
    except Exception as e:
        print("\n" + "=" * 70)
        print("FATAL ERROR: Cannot start bot without database connection")
        print("=" * 70)
        print(f"Error: {e}")
        print("\nPlease ensure PostgreSQL is running and try again.")
        print("=" * 70 + "\n")
        raise

# Видаляємо з інвентаря всіх гравців бафи, яких немає в каталозі (тільки дешеві)
try:
    from commands import buff_shop
    buff_shop._cleanup_removed_buffs()
except Exception:
    pass

# Видаляємо колекції (story_cards), яких немає у жодного користувача
try:
    from commands.start import _cleanup_unused_story_cards
    _cleanup_unused_story_cards()
except Exception:
    pass


class BlockedUserMiddleware(BaseMiddleware):
    """Блокує заблокованих користувачів - вони не обробляються ботом."""

    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            print(f"[BlockedUserMiddleware] Повідомлення від user_id={event.from_user.id if event.from_user else None}, текст: '{event.text}', chat_id={event.chat.id if event.chat else None}")
        user = getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)
        is_blocked = is_user_blocked(user.id)
        print(f"[BlockedUserMiddleware] user_id={user.id}, is_blocked={is_blocked}")
        if not is_blocked:
            return await handler(event, data)
        bot = data.get("bot")
        if isinstance(event, Message):
            if event.chat and event.chat.type == "private" and bot:
                await event.answer("Ви заблоковані і не можете користуватися ботом.")
            return
        if isinstance(event, CallbackQuery) and event.message and bot:
            await event.answer("Ви заблоковані.", show_alert=True)
        return


class InteractionLoggingMiddleware(BaseMiddleware):
    """Логує в консоль усі взаємодії з ботом: хто (user_id, username), де (chat_id), що (текст/callback)."""

    async def __call__(self, handler, event, data):
        ts = datetime.now().strftime("%H:%M:%S")
        user = getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)
        uid = user.id
        username = getattr(user, "username", None) or "-"
        name = (getattr(user, "first_name", "") or "").strip()
        if getattr(user, "last_name", None):
            name = f"{name} {user.last_name}".strip()
        if not name:
            name = "-"
        chat = getattr(event, "chat", None) or (getattr(event, "message", None) and getattr(event.message, "chat", None))
        chat_id = getattr(chat, "id", "-") if chat else "-"
        chat_type = getattr(chat, "type", "-") if chat else "-"
        if isinstance(event, Message):
            text = (event.text or event.caption or "[медіа]").strip()
            if len(text) > 60:
                text = text[:57] + "..."
            print(f"[{ts}] 💬 msg | user_id={uid} @{username} ({name}) | chat_id={chat_id} ({chat_type}) | {text!r}")
            # Додаткове логування для команд +адмін
            if text and ("+адмін" in text.lower() or "-адмін" in text.lower()):
                print(f"[{ts}] 🔍 [MIDDLEWARE] Знайдено команду +адмін/-адмін! Текст: {text!r}")
        elif isinstance(event, CallbackQuery):
            cb = (event.data or "")[:70]
            print(f"[{ts}] 🔘 cb  | user_id={uid} @{username} ({name}) | chat_id={chat_id} | data={cb!r}")
        # Усі групи з повідомленнями/callback - у bot_known_groups (статистика /capone_admin)
        try:
            if isinstance(event, Message) and event.chat and event.chat.type in ("group", "supergroup"):
                touch_known_group(event.chat.id)
            elif isinstance(event, CallbackQuery) and event.message and event.message.chat:
                ch = event.message.chat
                if ch.type in ("group", "supergroup"):
                    touch_known_group(ch.id)
        except Exception:
            pass
        return await handler(event, data)


class DisabledCommandMiddleware(BaseMiddleware):
    """Блокує slash-команди з БД; /cmd_off|on|list у ЛС проходять лише для BOT_OWNER_IDS."""

    _admin_cmds = frozenset({"cmd_off", "cmd_on", "cmd_list"})

    @staticmethod
    def _parse_command(text: str | None) -> str | None:
        t = (text or "").strip()
        if not t.startswith("/"):
            return None
        token = t.split()[0].split("@", 1)[0]
        if len(token) < 2:
            return None
        return token[1:].lower()

    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            cmd = self._parse_command(event.text)
            if cmd:
                uid = event.from_user.id if event.from_user else 0
                private = event.chat.type == ChatType.PRIVATE
                if cmd in self._admin_cmds and private and uid in BOT_OWNER_IDS:
                    return await handler(event, data)
                if is_bot_command_disabled(cmd):
                    await event.answer("🚫 Ця команда тимчасово вимкнена.")
                    return
        return await handler(event, data)


class WelcomeBonusCommandMiddleware(BaseMiddleware):
    """Видає одноразовий привітальний бонус при першій slash-команді користувача."""

    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            text = (event.text or "").strip()
            if text.startswith("/") and event.from_user:
                await grant_welcome_bonus_if_needed(event, only_new_user=True)
        return await handler(event, data)


class TelegramBot:
    def __init__(self):
        self.bot = Bot(token=TOKEN)
        self.dp = Dispatcher()
        self.play_command = PlayCommand()

        # Спершу перевірка заблокованих, потім лог
        block_mw = BlockedUserMiddleware()
        self.dp.message.middleware(block_mw)
        self.dp.callback_query.middleware(block_mw)
        log_mw = InteractionLoggingMiddleware()
        self.dp.message.middleware(log_mw)
        self.dp.callback_query.middleware(log_mw)
        self.dp.message.middleware(WelcomeBonusCommandMiddleware())
        self.dp.message.middleware(DisabledCommandMiddleware())
        
        self.construct_event = ConstructEvent()
        # router_last_word першим: «останнє слово» в ЛС не має перехоплюватись promocode/founder/roulette/support.
        # router_marigolds одразу після нього: щоб етапи дарування (ввід @username/id) не перехоплювались іншими роутерами.
        # router_pay після цього: подарунок VIP (ввід @username у ЛС), рефанд, інвойси - інакше
        # router_founder / router_play / router_start перехоплюють текст раніше й оновлення «handled» без відповіді.
        # router_group_admin далі: команди /хто_адмін, /мут, /бан, +адмін, текст «ХтоАдмін» та одне слово «Мафія»
        # router_founder перед router_support, щоб /capone_admin в ЛС оброблявся панеллю засновника
        self.dp.include_routers(
            self.play_command.router_last_word,
            router_marigolds,
            router_pay,
            router_command_switch,
            router_group_admin,
            router_promocode,  # перед play/start, щоб /promocode завжди оброблявся
            # ВАЖЛИВО: founder роутер має йти РАНІШЕ за roulette, бо рулетка перехоплює числові повідомлення,
            # а в /capone_admin є ввід ID/суми числами.
            router_founder,
            router_roulette,
            self.play_command.router_play, router_start, router_support,
            self.construct_event.router_construct_event,
            router_buff_shop, router_contraband, router_casino, router_story,
        )
        # Окремим викликом, щоб гарантовано приєднати (у складі великого include_routers
        # останній роутер інколи не чіплявся в цьому середовищі).
        self.dp.include_router(router_kupala)

        # Команди тільки в ЛС - не показувати play/start_game/carry_on (leave — для заглушених у групі)
        self.command_list_private = [
            BotCommand(command="start", description="Запуск бота 🤖"),
            BotCommand(command="help", description="Допомога 🆘"),
            BotCommand(command="profile", description="👤 Мій профіль"),
            BotCommand(command="promocode", description="🎟 Ввести промокод"),
            BotCommand(command="contraband", description="📦 Контрабанда"),
            BotCommand(command="leave", description="🚪 Покинути гру"),
        ]
        # Групи: у меню для всіх — вихід першим (як у інших ботів); для адмінів — додатково решта (Telegram об’єднує списки).
        self.command_list_group_members = [
            BotCommand(command="leave", description="🚪 Покинути гру"),
            BotCommand(command="roulette", description="🎰 Рулетка"),
            BotCommand(command="duel", description="⚔️ Дуель"),
        ]
        self.command_list_group_admins = [
            BotCommand(command="play", description="Почати гру 🎮"),
            BotCommand(command="start_game", description="Запустити гру одразу ⚡"),
            BotCommand(command="stop_game", description="Зупинити гру (адміни)"),
            BotCommand(command="carry_on", description="Продовжити реєстрацію ⏱️"),
            BotCommand(command="unreg", description="🔕 Вимкнути пінги при /play"),
            BotCommand(command="transfer_gold", description="🪙 Перевести золоті засновнику групи"),
            BotCommand(command="construct_event", description="🎨 Налаштування ролей (тільки для адмінів)"),
            BotCommand(command="settings", description="⚙️ Налаштування групи"),
            BotCommand(command="set_registration_time", description="⏱️ Встановити час реєстрації (тільки для власників)"),
        ]

    async def setup_bot_commands(self) -> None:
        """Меню «/» у групах: короткий список для всіх + додаткові для адмінів чату.
        Спочатку прибираємо глобальний default — інакше Telegram може показувати старий повний список
        (BotFather або setMyCommands без scope) поверх вузьких scope.
        Ті самі списки для uk/ru: якщо для мови інтерфейсу задано окремий порожній список, /leave не з’являвся б."""
        try:
            await self.bot.delete_my_commands(scope=BotCommandScopeDefault())
        except Exception:
            pass
        for lang in (None, "uk", "ru"):
            kw = {"language_code": lang} if lang else {}
            await self.bot.set_my_commands(
                self.command_list_private, scope=BotCommandScopeAllPrivateChats(), **kw
            )
            await self.bot.set_my_commands(
                self.command_list_group_members, scope=BotCommandScopeAllGroupChats(), **kw
            )
            await self.bot.set_my_commands(
                self.command_list_group_admins,
                scope=BotCommandScopeAllChatAdministrators(),
                **kw,
            )

    async def run(self):
        await self.setup_bot_commands()
        await self.dp.start_polling(self.bot)

if __name__ == "__main__":
    basicConfig(level=INFO)
    bot = TelegramBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        print("Close connection!")
