"""
Founder/Admin Panel - Secret command for bot owner to manage subscriptions and bot administration.

Secret command: /capone_admin — повна панель (лише засновники).
/support_panel — лише тікети для користувачів з таблиці support_staff.
"""

import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.filters import Command, BaseFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from database.database import (
    cursor, conn, get_open_support_tickets, get_support_ticket, close_support_ticket,
    reset_advent_for_user, reset_advent_for_all, reset_advent_day_for_all, reset_all_user_data_except_founders,
    get_active_founder_ids, set_group_admin, get_all_broadcast_user_ids,
    block_user_async, unblock_user_async, is_user_blocked_async,
    run_db_call_async,
    add_support_staff_user, remove_support_staff_user, get_support_staff_ids, is_support_staff_user,
)
from commands.buy import ShopManager, ShopItem
from commands import vip as vip_mod
from commands.buff_shop import grant_infinite_buffs_to_user, admin_grant_buff_to_user, UNIQUE_BUFFS
from commands import seasonal_events as seasonal_mod
from commands import bot_commands as bot_commands_mod
from game.role_system import create_default_roles
from game.role_manager import RoleManager
from premium_emoji import emoji_to_premium, custom_emoji_id_for_symbol
from typing import Optional, List, Dict, Any
import html


# FOUNDER_ID - Set this to your Telegram user ID
# This is the only person who can initially access /capone_admin and add other founders
# You can set it via environment variable FOUNDER_ID or hardcode here
import os
_founder_id_str = os.getenv("FOUNDER_ID")
FOUNDER_ID = int(_founder_id_str) if _founder_id_str and _founder_id_str.isdigit() and int(_founder_id_str) != 0 else None

# ID головного власника бота (для відправки посилань на чати)
BOT_OWNER_ID = 1859870653

# Панель лише для ролі «лінія підтримки» (тікети), тільки ПП
SUPPORT_PANEL_COMMAND = "support_panel"

_NON_PRIVATE_CAPONE_CHATS = frozenset({ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL})


def _db_fetchone_sync(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_fetchall_sync(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchall()


def _db_execute_commit_sync(query: str, params: tuple = ()) -> None:
    cursor.execute(query, params)
    conn.commit()


def _db_execute_sync(query: str, params: tuple = ()) -> int:
    cursor.execute(query, params)
    return cursor.rowcount if cursor.rowcount is not None else 0


async def _db_fetchone_async(query: str, params: tuple = ()):
    def _run():
        cursor.execute(query, params)
        return cursor.fetchone()
    return await run_db_call_async(_run)


async def _db_fetchall_async(query: str, params: tuple = ()):
    def _run():
        cursor.execute(query, params)
        return cursor.fetchall()
    return await run_db_call_async(_run)


async def _db_execute_commit_async(query: str, params: tuple = ()) -> None:
    def _run():
        cursor.execute(query, params)
        conn.commit()
    await run_db_call_async(_run)


def _chat_is_private(chat) -> bool:
    """У різних версіях aiogram type може бути ChatType або рядок."""
    if not chat:
        return False
    t = chat.type
    return t == ChatType.PRIVATE or t == "private"


class FounderPanelCallbackSecurityMiddleware(BaseMiddleware):
    """
    Callback-и панелі засновника лише з ПП і лише для is_founder (повна панель)
    або is_support_staff лише для гілки «Тікети».
    Інакше після пересилання повідомлення з кнопками з ПП у групу панель «оживала» в групі.
    """

    def __init__(self, panel: "FounderPanel"):
        self.panel = panel

    async def __call__(self, handler, event, data):
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)
        uid = event.from_user.id if event.from_user else None
        if uid is None:
            return None
        data_cb = event.data or ""
        allowed = self.panel.is_founder(uid) or (
            self.panel.is_support_staff_uid(uid) and FounderPanel.callback_allows_support_staff(data_cb)
        )
        if not allowed:
            try:
                await event.answer("Доступ заборонено.", show_alert=True)
            except Exception:
                pass
            return None
        msg = event.message
        if not msg or not msg.chat or not _chat_is_private(msg.chat):
            try:
                await event.answer(
                    "Панель лише в особистих повідомленнях з ботом. "
                    "Відкрий ПП: засновники — /capone_admin, підтримка — /support_panel.",
                    show_alert=True,
                )
            except Exception:
                pass
            return None
        return await handler(event, data)


class ReplyingToTicketFilter(BaseFilter):
    """Фільтр: повідомлення від засновника або лінії підтримки в режимі відповіді на тікет."""
    def __init__(self, panel: "FounderPanel"):
        self.panel = panel
    async def __call__(self, message: Message) -> bool:
        text = (getattr(message, "text", None) or "").strip()
        uid = getattr(message.from_user, "id", None) if getattr(message, "from_user", None) else None
        return bool(
            uid
            and self.panel.is_ticket_staff(uid)
            and uid in self.panel.admin_replying_ticket
            and not text.startswith("/")
        )


class PromoInputFilter(BaseFilter):
    """Фільтр: засновник вводить дані для створення промокоду."""
    def __init__(self, panel: "FounderPanel"):
        self.panel = panel
    async def __call__(self, message: Message) -> bool:
        text = (getattr(message, "text", None) or "").strip()
        if not getattr(message, "from_user", None):
            return False
        if not self.panel.is_founder(message.from_user.id):
            return False
        if getattr(self.panel, "waiting_promo_user_id", None) is not None and message.from_user.id != self.panel.waiting_promo_user_id:
            return False
        if text.startswith("/"):
            return False
        return (
            self.panel.is_inputting_promo_name
            or self.panel.is_inputting_promo_code
            or self.panel.is_inputting_promo_max
            or self.panel.is_inputting_promo_rewards
        )


class SendToMessageFilter(BaseFilter):
    """Фільтр: засновник вводить текст повідомлення для відправки користувачу (/send_to)."""
    def __init__(self, panel: "FounderPanel"):
        self.panel = panel
    async def __call__(self, message: Message) -> bool:
        text = (getattr(message, "text", None) or "").strip()
        if not getattr(message, "from_user", None):
            return False
        if not self.panel.is_founder(message.from_user.id):
            return False
        if getattr(self.panel, "waiting_send_to_user_id", None) is not None and message.from_user.id != self.panel.waiting_send_to_user_id:
            return False
        return bool(
            self.panel.is_inputting_send_to_message
            and self.panel.temp_send_to_target_id
            and not text.startswith("/")
        )


class BroadcastMessageFilter(BaseFilter):
    """Фільтр: засновник вводить повідомлення для розсилки (/broadcast)."""
    def __init__(self, panel: "FounderPanel"):
        self.panel = panel
    async def __call__(self, message: Message) -> bool:
        text = (getattr(message, "text", None) or "").strip()
        if not getattr(message, "from_user", None):
            return False
        if not self.panel.is_founder(message.from_user.id):
            return False
        if getattr(self.panel, "waiting_broadcast_user_id", None) is not None and message.from_user.id != self.panel.waiting_broadcast_user_id:
            return False
        if text.startswith("/"):
            return False
        return bool(self.panel.is_inputting_broadcast_message)


class HasCustomEmojiFilter(BaseFilter):
    """Фільтр: у повідомленні є хоча б один преміум-емодзі (custom_emoji entity)."""
    def __init__(self, panel: Optional["FounderPanel"] = None):
        self.panel = panel

    async def __call__(self, message: Message) -> bool:
        # Не спрацьовувати, якщо зараз активний режим введення для /broadcast або /send_to.
        if self.panel and getattr(message, "from_user", None):
            uid = message.from_user.id
            waiting_broadcast = getattr(self.panel, "waiting_broadcast_user_id", None)
            if getattr(self.panel, "is_inputting_broadcast_message", False) and (
                waiting_broadcast is None or waiting_broadcast == uid
            ):
                return False
            waiting_send_to = getattr(self.panel, "waiting_send_to_user_id", None)
            if getattr(self.panel, "is_inputting_send_to_message", False) and (
                waiting_send_to is None or waiting_send_to == uid
            ):
                return False
        entities = getattr(message, "entities", None) or []
        return any(getattr(e, "custom_emoji_id", None) for e in entities)


def _parse_group_id(text: str) -> Optional[int]:
    """Парсить ID групи з тексту. Приймає мінус (включно з Unicode −), пробіли. Повертає int або None."""
    if not text or not isinstance(text, str):
        return None
    s = text.strip().replace("\u2212", "-").replace("−", "-").replace(" ", "")
    if not s or s == "-":
        return None
    try:
        return int(s)
    except ValueError:
        return None


async def resolve_group_open_link(bot: Bot, chat_id: int, chat) -> str:
    """
    HTTPS-посилання, яке Telegram нормально відкриває по тапу.
    Чистий tg://openmessage у багатьох клієнтах не підкреслює і не відкриває чат.
    """
    if getattr(chat, "invite_link", None):
        return chat.invite_link
    un = getattr(chat, "username", None)
    if un:
        return f"https://t.me/{un}"
    sid = str(chat.id)
    # Супергрупа / канал: -100xxxxxxxxxx → https://t.me/c/xxxxxxxxxx/
    if sid.startswith("-100") and len(sid) > 4 and sid[4:].isdigit():
        return f"https://t.me/c/{sid[4:]}/"
    # Звичайна група або немає публічного slug - пробуємо запрошення (бот має бути адміном)
    try:
        inv = await bot.export_chat_invite_link(chat_id)
        if inv:
            return inv
    except Exception:
        pass
    return f"tg://openmessage?chat_id={chat_id}"


class FounderPanel:
    """Administrative panel for bot founders"""
    
    def __init__(self):
        self.router_founder = Router()
        
        # /capone_admin: у групі/каналі - лише відмова; у ПП - панель (фільтр ChatType, не рядок "private")
        self.router_founder.message.register(
            self.capone_admin_reject_in_group_handler,
            Command("capone_admin"),
            F.chat.type.in_(_NON_PRIVATE_CAPONE_CHATS),
        )
        self.router_founder.message.register(
            self.founder_panel_handler,
            Command("capone_admin"),
            F.chat.type == ChatType.PRIVATE,
        )
        self.router_founder.message.register(
            self.support_panel_reject_in_group_handler,
            Command(SUPPORT_PANEL_COMMAND),
            F.chat.type.in_(_NON_PRIVATE_CAPONE_CHATS),
        )
        self.router_founder.message.register(
            self.support_panel_handler,
            Command(SUPPORT_PANEL_COMMAND),
            F.chat.type == ChatType.PRIVATE,
        )
        self.router_founder.callback_query.middleware(FounderPanelCallbackSecurityMiddleware(self))
        self.router_founder.message.register(self.founder_commands_handler, Command("founder_commands"))
        self.router_founder.message.register(
            self.bot_leave_chat_cmd_handler,
            Command("bot_leave"),
            F.chat.type == ChatType.PRIVATE,
        )
        # Register initialization command for first founder
        self.router_founder.message.register(self.init_founder_handler, Command("capone_init"))
        # Register command to update roles DB from code
        self.router_founder.message.register(self.update_roles_db_handler, Command("update_roles_db"))
        # Update only one default role from code
        self.router_founder.message.register(self.update_role_db_handler, Command("update_role_db"))
        self.router_founder.message.register(self.verify_buffs_handler, Command("verify_buffs"))
        self.router_founder.message.register(self.remove_achievements_handler, Command("remove_achievements"))
        self.router_founder.message.register(self.grant_achievements_handler, Command("grant_achievements"))
        self.router_founder.message.register(self.group_members_handler, Command("group_members"))
        self.router_founder.message.register(self.give_coins_cmd_handler, Command("give_coins"))
        self.router_founder.message.register(self.give_gold_cmd_handler, Command("give_gold"))
        self.router_founder.message.register(self.april_gold_cmd_handler, Command("april_gold"))
        self.router_founder.message.register(self.give_vip_cmd_handler, Command("give_vip"))
        self.router_founder.message.register(self.vip_paid_list_cmd_handler, Command("vip_paid_list"))
        self.router_founder.message.register(
            self.vip_paid_list_cmd_handler,
            F.chat.type == ChatType.PRIVATE,
            F.text.regexp(r"^/vip_paid_list(?:@\w+)?(?:\s|$)"),
        )
        self.router_founder.message.register(self.give_marigolds_cmd_handler, Command("give_marigolds"))
        self.router_founder.message.register(self.vip_daily_all_cmd_handler, Command("vip_daily_all"))
        self.router_founder.message.register(self.vip_daily_reset_cmd_handler, Command("vip_daily_reset"))
        self.router_founder.message.register(self.send_to_user_cmd_handler, Command("send_to"))
        self.router_founder.message.register(self.broadcast_cmd_handler, Command("broadcast"))
        self.router_founder.message.register(self.broadcast_delete_last_cmd_handler, Command("broadcast_delete_last"))
        self.router_founder.message.register(self.broadcast_delete_cmd_handler, Command("broadcast_delete"))
        self.router_founder.message.register(self.advent_reset_cmd_handler, Command("advent_reset"))
        self.router_founder.message.register(self.advent_reset_all_cmd_handler, Command("advent_reset_all"))
        self.router_founder.message.register(self.advent_reset_day_all_cmd_handler, Command("advent_reset_day_all"))
        self.router_founder.message.register(self.reset_stats_all_cmd_handler, Command("reset_stats_all"))
        self.router_founder.message.register(self.give_infinite_buffs_cmd_handler, Command("give_infinite_buffs"))
        self.router_founder.message.register(self.grant_buff_self_cmd_handler, Command("grant_buff_self"))
        self.router_founder.message.register(self.clear_user_buffs_cmd_handler, Command("clear_user_buffs"))
        self.router_founder.message.register(self.edit_user_cmd_handler, Command("edit_user"))
        self.router_founder.message.register(self.get_emoji_id_cmd_handler, Command("get_emoji_id"))
        self.router_founder.message.register(self.upload_role_card_cmd_handler, Command("upload_role_card"))
        self.router_founder.message.register(self.construct_access_cmd_handler, Command("construct_access"))
        self.router_founder.message.register(
            self.ticket_reply_message_handler,
            F.chat.type == ChatType.PRIVATE,
            F.text,
            ReplyingToTicketFilter(self),
        )
        self.router_founder.message.register(
            self.promo_input_message_handler,
            F.chat.type == ChatType.PRIVATE,
            F.text,
            PromoInputFilter(self),
        )
        self.router_founder.message.register(
            self.send_to_message_handler,
            F.chat.type == ChatType.PRIVATE,
            F.text,
            SendToMessageFilter(self),
        )
        self.router_founder.message.register(
            self.broadcast_message_handler,
            F.chat.type == ChatType.PRIVATE,
            (F.text | F.photo),
            BroadcastMessageFilter(self),
        )
        self.router_founder.message.register(
            self.edit_user_input_handler,
            F.chat.type == ChatType.PRIVATE,
            F.text,
            lambda msg: (
                getattr(msg, "from_user", None)
                and msg.from_user.id in self.user_edit_waiting_input
                and not (msg.text or "").strip().startswith("/")
            ),
        )
        # ВАЖЛИВО: реєструємо після /broadcast handler, інакше custom_emoji-підказка
        # може перехопити повідомлення для розсилки раніше за BroadcastMessageFilter.
        self.router_founder.message.register(
            self.premium_emoji_entities_handler,
            F.chat.type == ChatType.PRIVATE,
            F.text,
            HasCustomEmojiFilter(self),
        )
        
        # State flags
        self.is_inputting_user_id = False
        self.is_inputting_subscription_type = False
        self.is_inputting_duration = False
        self.is_inputting_balance_user_id = False
        self.is_inputting_balance_amount = False
        self.is_inputting_block_group_id = False
        self.is_inputting_unblock_group_id = False
        self.is_inputting_promo_name = False
        self.is_inputting_promo_code = False
        self.is_inputting_promo_max = False
        self.is_inputting_promo_rewards = False
        self.is_inputting_send_to_message = False
        self.is_inputting_broadcast_message = False
        
        # Temporary data
        self.temp_user_id = None
        self.temp_subscription_type = None
        self.temp_balance_user_id = None
        self.temp_balance_amount = None
        self.balance_mode = "give"  # "give" | "take" - видати чи забрати монети
        self.temp_promo_name = None
        self.temp_promo_code = None
        self.temp_promo_max = None
        self.temp_promo_rewards = None
        self.temp_promo_bot_chat_id = None
        self.temp_promo_bot_message_id = None
        self.temp_send_to_target_id = None
        # Хто зараз вводить (тільки цей user_id отримає обробку - синхронізація між засновниками)
        self.add_founder_waiting_user_id: Optional[int] = None
        self.add_founder_revoke_waiting_user_id: Optional[int] = None
        self.waiting_subscription_user_id: Optional[int] = None
        self.waiting_check_subscription_user_id: Optional[int] = None
        self.waiting_revoke_subscription_user_id: Optional[int] = None
        self.waiting_balance_user_id: Optional[int] = None
        self.waiting_block_group_user_id: Optional[int] = None
        self.waiting_unblock_group_user_id: Optional[int] = None
        self.waiting_promo_user_id: Optional[int] = None
        self.waiting_send_to_user_id: Optional[int] = None
        self.waiting_broadcast_user_id: Optional[int] = None
        # Чернетки редагування користувача: admin_id -> session
        self.user_edit_sessions: Dict[int, Dict[str, Any]] = {}
        # Очікуємо текстове значення поля: admin_id -> field ("balance"/"gold"/"vip")
        self.user_edit_waiting_input: Dict[int, str] = {}

        # Адмін відповідає на тікет: admin_id -> ticket_id
        self.admin_replying_ticket: Dict[int, int] = {}
        # Роль підтримки (тільки тікети): хто натиснув «дати/забрати» — очікуємо ID в ПП
        self.support_staff_add_waiting_user_id: Optional[int] = None
        self.support_staff_remove_waiting_user_id: Optional[int] = None

        # Реєструємо callback-обробники один раз (не в show_main_menu, щоб не дублювати)
        self._register_handlers()

    @staticmethod
    def callback_allows_support_staff(data_cb: str) -> bool:
        """Callback-и, доступні користувачу лише з роллю підтримки (без повної панелі засновника)."""
        if not data_cb:
            return False
        if data_cb in ("founder_tickets", "founder_back_main"):
            return True
        if data_cb.startswith("founder_ticket_close_"):
            return True
        if data_cb.startswith("founder_ticket_"):
            return True
        return False

    def is_founder(self, user_id: int) -> bool:
        """Check if user is a founder/admin"""
        # Бот-власник має доступ завжди, незалежно від таблиці founders/FOUNDER_ID
        if user_id == BOT_OWNER_ID:
            return True

        # Check founders table
        result = _db_fetchone_sync(
            "SELECT founder_id FROM founders WHERE founder_id = %s AND is_active = TRUE",
            (user_id,),
        )
        if result:
            return True
        
        # First founder check - if FOUNDER_ID is set, check it
        global FOUNDER_ID
        if FOUNDER_ID and user_id == FOUNDER_ID:
            # Auto-add to founders table if not exists
            row = _db_fetchone_sync("SELECT founder_id FROM founders WHERE founder_id = %s", (user_id,))
            if not row:
                _db_execute_commit_sync(
                    """
                    INSERT INTO founders (founder_id, added_by, is_active, notes)
                    VALUES (%s, %s, TRUE, 'Auto-added initial founder')
                    """,
                    (user_id, user_id),
                )
            return True
        
        # ЗАХИСТ: НЕ робимо засновником «першого користувача» при порожній таблиці.
        # Раніше тут було авто-додавання, через яке будь-хто, хто першим звернувся
        # до бота при порожній таблиці founders, ставав засновником із повним
        # доступом (/give_coins, /give_vip тощо). Засновники тепер призначаються
        # ЛИШЕ явно: власником (BOT_OWNER_ID), через FOUNDER_ID або вже наявним
        # засновником у панелі. Жодного автоматичного підвищення.
        return False

    def is_support_staff_uid(self, user_id: int) -> bool:
        """Роль лінії підтримки (не засновник): тікети в ПП."""
        return is_support_staff_user(int(user_id))

    def is_ticket_staff(self, user_id: int) -> bool:
        """Хто може відкривати/закривати тікети та писати відповідь користувачу."""
        return self.is_founder(user_id) or self.is_support_staff_uid(user_id)
    
    async def init_founder_handler(self, message: Message):
        """Initialize first founder - /capone_init"""
        user_id = message.from_user.id
        
        # Check if already founder
        if self.is_founder(user_id):
            await message.answer(
                f"✅ Ти вже є засновником!\n\n"
                f"Використай команду /capone_admin для доступу до панелі.",
                parse_mode="html"
            )
            return
        
        # Check if table is empty or has no active founders
        row = await _db_fetchone_async("SELECT COUNT(*) FROM founders WHERE is_active = TRUE")
        count = row[0] if row else 0
        
        if count == 0:
            # ЗАХИСТ: бутстрап «першого засновника» дозволено ЛИШЕ власнику бота.
            # Інакше будь-хто міг би зробити себе засновником, якщо активних
            # засновників тимчасово немає.
            if user_id != BOT_OWNER_ID:
                await message.answer(
                    "❌ Команда недоступна.\n\n"
                    "Засновника може призначити лише власник бота або вже наявний засновник.",
                    parse_mode="html",
                )
                return
            # Add as first founder
            try:
                await _db_execute_commit_async(
                    """
                    INSERT INTO founders (founder_id, added_by, is_active, notes)
                    VALUES (%s, %s, TRUE, 'Initialized via /capone_init command')
                    """,
                    (user_id, user_id),
                )
                
                await message.answer(
                    f"✅ <b>Ти тепер засновник!</b> ✅\n\n"
                    f"Твій Telegram ID: <b>{user_id}</b>\n\n"
                    f"Використай команду <code>/capone_admin</code> для доступу до адмін-панелі.",
                    parse_mode="html"
                )
            except Exception as e:
                await message.answer(
                    f"❌ Помилка при додаванні: {str(e)}\n\n"
                    f"Твій ID: {user_id}\n\n"
                    f"Можна додати вручну через SQL:\n"
                    f"<code>INSERT INTO founders (founder_id, added_by, is_active) VALUES ({user_id}, {user_id}, TRUE);</code>",
                    parse_mode="html"
                )
        else:
            await message.answer(
                f"❌ Засновники вже існують!\n\n"
                f"Твій ID: <b>{user_id}</b>\n\n"
                f"Попроси існуючого засновника додати тебе через панель /capone_admin",
                parse_mode="html"
            )
    
    async def capone_admin_reject_in_group_handler(self, message: Message):
        """/capone_admin у групі або каналі - не відкривати панель."""
        await message.answer(
            "❌ Команда /capone_admin доступна тільки в особистих повідомленнях боту (ПП).\n\n"
            "Напиши боту в ПП і введи команду там.",
            parse_mode="html",
        )

    async def support_panel_reject_in_group_handler(self, message: Message):
        """/support_panel у групі — тільки для ПП."""
        await message.answer(
            f"❌ Команда <code>/{SUPPORT_PANEL_COMMAND}</code> доступна лише в <b>особистих повідомленнях</b> з ботом.\n\n"
            "Напиши боту в ПП і введи команду там.",
            parse_mode="html",
        )

    async def support_panel_handler(self, message: Message):
        """Панель тікетів для лінії підтримки — /support_panel (тільки ПП)."""
        if not _chat_is_private(message.chat):
            await self.support_panel_reject_in_group_handler(message)
            return
        if not message.from_user:
            return
        uid = message.from_user.id
        if not self.is_support_staff_uid(uid):
            await message.answer(
                "❌ Команда <code>/support_panel</code> доступна лише для <b>лінії підтримки</b>.\n"
                "Засновники відкривають повну панель: <code>/capone_admin</code>.",
                parse_mode="html",
            )
            return
        await self.show_support_only_menu(message)

    async def founder_panel_handler(self, message: Message):
        """Панель засновника — /capone_admin, тільки ПП."""
        if not _chat_is_private(message.chat):
            await self.capone_admin_reject_in_group_handler(message)
            return
        if not message.from_user:
            return
        if not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        await self.show_main_menu(message)

    async def founder_commands_handler(self, message: Message):
        """Показати список команд для засновників. Доступно тільки засновникам, тільки в ПП."""
        if not _chat_is_private(message.chat):
            await message.answer(
                "❌ Команда /founder_commands доступна тільки в особистих повідомленнях з ботом.",
                parse_mode="html",
            )
            return
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Ця команда доступна тільки засновникам бота.")
            return
        text = emoji_to_premium(
            "👑 <b>Команди для засновників</b> 👑\n\n"
            "🔐 <b>Панель та доступ</b>\n"
            "<code>/capone_admin</code> - адмін-панель\n"
            "<code>/capone_init</code> - ініціалізація першого засновника\n"
            "У панелі: <b>«Лінія підтримки (роль)»</b> — видати/забрати доступ до тікетів за Telegram ID "
            "(такі люди відкривають тікети командою <code>/support_panel</code> у ПП і отримують нові звернення).\n\n"
            "💰 <b>Гроші</b>\n"
            "<code>/give_coins &lt;user_id&gt; &lt;кількість&gt;</code> - нарахувати ліри\n"
            "<code>/give_gold &lt;user_id&gt; &lt;кількість&gt;</code> - нарахувати золоті\n"
            "<code>/april_gold &lt;user_id|all&gt; [кількість]</code> - 1 квітня: фейкова «видача» (без запису в БД)\n"
            "<code>/give_marigolds &lt;user_id&gt; &lt;кількість&gt;</code> - видати лимони\n\n"
            "⚒️ <b>VIP</b>\n"
            "<code>/give_vip &lt;user_id&gt; [vip|vip+] [місяці]</code> - VIP / VIP+ (за замовч. 1 міс. × 30 дн.; до 120 міс.)\n"
            "Приклади: <code>/give_vip 123 vip+ 7</code>, <code>/give_vip 123 7 vip</code>\n"
            "<code>/vip_paid_list</code> - хто купив VIP/VIP+ і хто має активний VIP з покупки (без тест/адвент/адмін-видачі)\n"
            "<code>/vip_daily_all</code> - щоденні ліри всім активним VIP/VIP+ (хто ще не отримав сьогодні)\n"
            "<code>/vip_daily_all force</code> - нарахувати ще раз усім (компенсація)\n"
            "<code>/vip_daily_reset</code> - скинути «вже отримав сьогодні» собі (тест повідомлення VIP)\n"
            "<code>/vip_daily_reset &lt;user_id&gt;</code> - те саме для іншого користувача\n\n"
            "🏆 <b>Досягнення та картки</b>\n"
            "<code>/remove_achievements &lt;user_id&gt;</code> - видалити прогрес і картки\n"
            "<code>/grant_achievements &lt;user_id&gt;</code> - видати всі досягнення\n\n"
            "🌸 <b>Адвент</b>\n"
            "<code>/advent_reset &lt;user_id&gt;</code> - скинути адвент одному\n"
            "<code>/advent_reset_all</code> - скинути адвент усім\n\n"
            "📩 <b>Повідомлення</b>\n"
            "<code>/send_to &lt;user_id&gt;</code> - надіслати текст користувачу (потім ввести текст)\n"
            "<code>/broadcast</code> - розсилка повідомлення всім (потім ввести текст або фото з підписом)\n"
            "<code>/broadcast_delete_last</code> - видалити останню розсилку (v2), якщо можливо\n"
            "<code>/broadcast_delete &lt;id&gt;</code> - видалити розсилку за ID (v2)\n\n"
            "🔄 <b>Повне скидання</b>\n"
            "<code>/reset_stats_all</code> - обнулити все у всіх (гроші, бафи, досягнення, картки, адвент, підписки тощо), окрім засновників\n\n"
            "📋 <b>Інше</b>\n"
            "<code>/bot_leave &lt;chat_id&gt;</code> - бот виходить із групи/супергрупи (лише в ПП, <b>лише головний власник бота</b>)\n"
            "<code>/group_members</code> або <code>/group_members &lt;chat_id&gt;</code> - ID адмінів групи\n"
            "<code>/construct_access &lt;group_id&gt;</code> - дати собі доступ до /construct_event для групи (редагувати ролі)\n"
            "<code>/update_roles_db</code> - оновити таблицю ролей\n"
            "<code>/update_role_db &lt;role_name&gt;</code> - оновити лише одну default-роль (наприклад: <code>/update_role_db Щасливчик</code>)\n"
            "<code>/verify_buffs</code> - перевірка бафів на роботоспроможність (каталог + smoke test)\n"
            "<code>/test_endgame</code> - тест кінця гри\n"
            "<code>/test_start [N]</code> - тест гри з N гравцями\n\n"
            "📦 <b>Бафи</b>\n"
            "<code>/grant_buff_self [buff_id]</code> - видати <b>собі</b> один баф (за замовчуванням <code>devil_covenant</code>); id з каталогу ринку або унікальних\n"
            "<code>/give_infinite_buffs &lt;user_id&gt;</code> - видати безкінечні бафи (всі з каталогу) за ID\n"
            "<code>/clear_user_buffs &lt;user_id&gt;</code> - видалити бафи у користувача\n"
            "<code>/clear_all_buffs</code> - видалити всі бафи у всіх (з підтвердженням)\n\n"
            "🎨 <b>Преміум-емодзі</b>\n"
            "<code>/get_emoji_id</code> - підказка; надішли повідомлення з преміум-емодзі - отримаєш їхні ID для <code>premium_emoji.py</code>\n\n"
            "Панель <code>/capone_admin</code>: підписки, блокування груп, промокоди, тікети, додати засновника."
        )
        await message.answer(text, parse_mode="html")

    async def bot_leave_chat_cmd_handler(self, message: Message, bot: Bot):
        """
        Вийти з групи/каналу за numeric chat_id.
        Тільки головний власник бота (BOT_OWNER_ID), тільки в особистих повідомленнях.
        """
        if not message.from_user:
            return
        if message.from_user.id != BOT_OWNER_ID:
            await message.answer("❌ Ця команда доступна лише <b>головному власнику бота</b>.", parse_mode="html")
            return
        parts = (message.text or "").strip().split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.answer(
                "🚪 <b>Вийти з чату</b>\n\n"
                "Напиши в ПП:\n"
                "<code>/bot_leave &lt;chat_id&gt;</code>\n\n"
                "Приклад: <code>/bot_leave -1001234567890</code>\n\n"
                "<i>chat_id</i> - числовий ID групи або супергрупи (можна взяти з повідомлення про групу, "
                "з адмін-панелі або з пересланого посту).",
                parse_mode="html",
            )
            return
        chat_id = _parse_group_id(parts[1])
        if chat_id is None:
            await message.answer(
                "❌ Некоректний <code>chat_id</code>. Вкажи ціле число, наприклад <code>-1001234567890</code>.",
                parse_mode="html",
            )
            return
        try:
            await bot.leave_chat(chat_id)
            await message.answer(
                f"✅ Бот вийшов із чату <code>{chat_id}</code>.",
                parse_mode="html",
            )
        except TelegramBadRequest as e:
            await message.answer(
                f"❌ Telegram: <code>{html.escape(str(e))}</code>",
                parse_mode="html",
            )
        except Exception as e:
            await message.answer(
                f"❌ Помилка: <code>{html.escape(str(e))}</code>",
                parse_mode="html",
            )

    async def give_infinite_buffs_cmd_handler(self, message: Message):
        """Видати безкінечні бафи користувачу за ID. Тільки для засновника. Використання: /give_infinite_buffs <user_id>"""
        if not _chat_is_private(message.chat):
            return
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        text = (message.text or "").strip().split(maxsplit=1)
        if len(text) < 2:
            await message.answer(
                "♾ <b>Видати безкінечні бафи</b> ♾\n\n"
                "Використання: <code>/give_infinite_buffs &lt;user_id&gt;</code>\n\n"
                "Приклад: <code>/give_infinite_buffs 123456789</code>\n\n"
                "Користувач отримає всі бафи з каталогу з позначкою «безкінечно» (∞) - заряди не зменшуються при використанні.",
                parse_mode="html",
            )
            return
        try:
            target_user_id = int(text[1].strip())
        except ValueError:
            await message.answer("❌ Невірний ID. Вкажи число, наприклад: <code>/give_infinite_buffs 123456789</code>", parse_mode="html")
            return
        count = grant_infinite_buffs_to_user(target_user_id)
        await message.answer(
            f"✅ Користувачу <code>{target_user_id}</code> видано безкінечні бафи: <b>{count}</b> предметів.\n\n"
            "У профілі (/profile → Мої бафи) вони відображатимуться зі значком ∞.",
            parse_mode="html",
        )

    async def grant_buff_self_cmd_handler(self, message: Message):
        """Видати собі один баф за id. Лише засновник, лише ПП. /grant_buff_self [buff_id], за замовчуванням devil_covenant."""
        if not _chat_is_private(message.chat):
            return
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        parts = (message.text or "").strip().split(maxsplit=1)
        buff_id = parts[1].strip() if len(parts) >= 2 else "devil_covenant"
        uid = message.from_user.id
        ok, info = admin_grant_buff_to_user(uid, buff_id)
        if ok:
            hint = (
                "Увімкни баф: <code>/profile</code> → <b>Мої бафи</b> → <b>Унікальні бафи</b>."
                if buff_id in UNIQUE_BUFFS
                else "Увімкни баф: <code>/profile</code> → <b>Мої бафи</b>."
            )
            await message.answer(
                f"✅ Видано: <b>{html.escape(info)}</b> (<code>{html.escape(buff_id)}</code>)\n"
                f"Користувач: <code>{uid}</code>\n\n"
                f"{hint}",
                parse_mode="html",
            )
        else:
            await message.answer(
                f"❌ {html.escape(info)}\n\n"
                "Приклади: <code>/grant_buff_self devil_covenant</code>, <code>/grant_buff_self smoke_grenade</code>",
                parse_mode="html",
            )

    async def clear_user_buffs_cmd_handler(self, message: Message):
        """Забрати всі бафи у користувача за ID. Тільки для засновника."""
        if not _chat_is_private(message.chat):
            return
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return

        parts = (message.text or "").strip().split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "🧹 <b>Очистити бафи користувача</b>\n\n"
                "Використання: <code>/clear_user_buffs &lt;user_id&gt;</code>\n"
                "Приклад: <code>/clear_user_buffs 123456789</code>",
                parse_mode="html",
            )
            return

        try:
            target_user_id = int(parts[1].strip())
        except ValueError:
            await message.answer(
                "❌ Невірний ID. Вкажи число, наприклад: <code>/clear_user_buffs 123456789</code>",
                parse_mode="html",
            )
            return

        try:
            row = await _db_fetchone_async("SELECT COALESCE(COUNT(*), 0) FROM user_buffs WHERE user_id = %s", (target_user_id,))
            before_count = int(row[0]) if row and row[0] is not None else 0

            def _delete_buffs():
                try:
                    deleted_local = _db_execute_sync("DELETE FROM user_buffs WHERE user_id = %s", (target_user_id,))
                    conn.commit()
                    return deleted_local
                except Exception:
                    conn.rollback()
                    raise

            deleted = await run_db_call_async(_delete_buffs)

            await message.answer(
                f"✅ Бафи користувача <code>{target_user_id}</code> очищено.\n"
                f"Було записів: <b>{before_count}</b>, видалено: <b>{deleted}</b>.",
                parse_mode="html",
            )
        except Exception as e:
            await message.answer(
                f"❌ Помилка очищення бафів: <code>{html.escape(str(e))}</code>",
                parse_mode="html",
            )

    async def get_emoji_id_cmd_handler(self, message: Message):
        """Підказка: як отримати ID преміум-емодзі для premium_emoji.py."""
        if not _chat_is_private(message.chat) or not message.from_user or not self.is_founder(message.from_user.id):
            return
        await message.answer(
            "♾ <b>ID преміум-емодзі</b>\n\n"
            "Надішли сюди <b>одне повідомлення</b>, в якому вставлені преміум-емодзі з клавіатури Telegram "
            "(додаток → емодзі → преміум/анімовані). Я відповім їхніми <code>custom_emoji_id</code> - "
            "їх можна вставити в <code>premium_emoji.py</code> в словник <code>CUSTOM_EMOJI_MAP</code>.",
            parse_mode="html",
        )

    async def premium_emoji_entities_handler(self, message: Message):
        """Якщо засновник надіслав текст з преміум-емодзі - виводимо їхні custom_emoji_id для копіювання в premium_emoji.py."""
        if not message.from_user or not self.is_founder(message.from_user.id):
            return
        # Під час активної /broadcast або /send_to не перехоплюємо повідомлення:
        # воно має піти в відповідний handler, а не в сервісну підказку custom_emoji_id.
        if self.is_inputting_broadcast_message:
            waiting_uid = getattr(self, "waiting_broadcast_user_id", None)
            if waiting_uid is None or waiting_uid == message.from_user.id:
                return
        if self.is_inputting_send_to_message:
            waiting_uid = getattr(self, "waiting_send_to_user_id", None)
            if waiting_uid is None or waiting_uid == message.from_user.id:
                return
        if not message.entities:
            return
        custom = []
        for e in message.entities:
            cid = getattr(e, "custom_emoji_id", None)
            if cid is not None:
                custom.append(str(cid))
        if not custom:
            return
        lines = ["<b>Преміум-емодзі (custom_emoji_id):</b>\n"]
        for cid in custom:
            lines.append(f'  <code>"{cid}"</code>')
        lines.append("\nДодай у <code>premium_emoji.py</code> в <code>CUSTOM_EMOJI_MAP</code>: ключ - символ емодзі (наприклад 🔫), значення - рядок ID вище.")
        await message.answer("\n".join(lines), parse_mode="html")

    async def remove_achievements_handler(self, message: Message):
        """Видалити досягнення та сюжетний прогрес користувача по ID. Тільки для засновника. Використання: /remove_achievements <user_id>"""
        if not message.from_user:
            return
        if not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "📋 <b>Видалити досягнення користувачу</b>\n\n"
                "Використання: <code>/remove_achievements &lt;user_id&gt;</code>\n\n"
                "Приклад: <code>/remove_achievements 123456789</code>\n\n"
                "Буде видалено: прогрес досягнень, відкладену доставку сюжетки, відкриті сюжетні карточки та вибір у сюжеті для цього користувача.",
                parse_mode="html",
            )
            return
        try:
            target_user_id = int(parts[1].strip())
        except ValueError:
            await message.answer("❌ Невірний ID. Вкажи число, наприклад: <code>/remove_achievements 123456789</code>", parse_mode="html")
            return
        try:
            def _delete_achievements():
                try:
                    deleted_ach_local = _db_execute_sync(
                        "DELETE FROM user_achievement_progress WHERE user_id = %s",
                        (target_user_id,),
                    )
                    deleted_delivery_local = _db_execute_sync(
                        "DELETE FROM achievement_story_delivery WHERE user_id = %s",
                        (target_user_id,),
                    )
                    deleted_choices_local = _db_execute_sync(
                        "DELETE FROM user_story_choices WHERE user_id = %s",
                        (target_user_id,),
                    )
                    deleted_cards_local = _db_execute_sync(
                        "DELETE FROM user_story_cards WHERE user_id = %s",
                        (target_user_id,),
                    )
                    conn.commit()
                    return (
                        deleted_ach_local,
                        deleted_delivery_local,
                        deleted_choices_local,
                        deleted_cards_local,
                    )
                except Exception:
                    conn.rollback()
                    raise

            deleted_ach, deleted_delivery, deleted_choices, deleted_cards = await run_db_call_async(_delete_achievements)
            await message.answer(
                f"✅ Для користувача <code>{target_user_id}</code> видалено:\n"
                f"• досягнення: {deleted_ach}\n"
                f"• записів доставки сюжетки: {deleted_delivery}\n"
                f"• вибір у сюжеті: {deleted_choices}\n"
                f"• сюжетних карточок: {deleted_cards}",
                parse_mode="html",
            )
        except Exception as e:
            await message.answer(f"❌ Помилка: {e}", parse_mode="html")

    async def grant_achievements_handler(self, message: Message):
        """Видати всі досягнення користувачу. Використання: /grant_achievements <user_id>"""
        if not message.from_user:
            return
        if not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "🏆 <b>Видати всі досягнення</b>\n\n"
                "Використання: <code>/grant_achievements &lt;user_id&gt;</code>\n\n"
                "Приклад: <code>/grant_achievements 123456789</code>\n\n"
                "Користувач отримає всі досягнення та відповідні сюжетні картки.",
                parse_mode="html",
            )
            return
        try:
            target_user_id = int(parts[1].strip())
        except ValueError:
            await message.answer("❌ Невірний ID. Вкажи число, наприклад: <code>/grant_achievements 123456789</code>", parse_mode="html")
            return
        from commands.story_achievements import grant_all_achievements_to_user
        ach_count, card_count = grant_all_achievements_to_user(target_user_id)
        await message.answer(
            f"✅ Користувачу <code>{target_user_id}</code> видано:\n"
            f"• досягнень: {ach_count}\n"
            f"• нових сюжетних карток: {card_count}",
            parse_mode="html",
        )

    async def grant_cards_handler(self, message: Message):
        """Видати всі сюжетні картки користувачу. Використання: /grant_cards <user_id>"""
        if not message.from_user:
            return
        if not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "🃏 <b>Видати всі картки</b>\n\n"
                "Використання: <code>/grant_cards &lt;user_id&gt;</code>\n\n"
                "Приклад: <code>/grant_cards 123456789</code>\n\n"
                "Користувач отримає всі сюжетні картки (без досягнень).",
                parse_mode="html",
            )
            return
        try:
            target_user_id = int(parts[1].strip())
        except ValueError:
            await message.answer("❌ Невірний ID. Вкажи число, наприклад: <code>/grant_cards 123456789</code>", parse_mode="html")
            return
        from commands.story_achievements import grant_all_cards_to_user
        added = grant_all_cards_to_user(target_user_id)
        await message.answer(
            f"✅ Користувачу <code>{target_user_id}</code> додано нових карток: {added}\n\n"
            f"Всі сюжети доступні в /story та /cards.",
            parse_mode="html",
        )

    async def reset_story_choices_handler(self, message: Message):
        """Скинути збережені вибори в сюжетах (user_story_choices). /reset_story_choices <user_id> | all | всі"""
        if not message.from_user:
            return
        if not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "📖 <b>Скинути вибори в сюжетах</b>\n\n"
                "Видаляє збережені відповіді на розвилках у всіх сюжетних картках - користувачі зможуть обрати варіант знову "
                "(картки в колекції та досягнення не чіпаються).\n\n"
                "Використання:\n"
                "• <code>/reset_story_choices &lt;user_id&gt;</code> - для одного користувача\n"
                "• <code>/reset_story_choices all</code> або <code>/reset_story_choices всі</code> - для <b>усіх</b>\n\n"
                "Приклад: <code>/reset_story_choices 123456789</code>",
                parse_mode="html",
            )
            return
        arg = parts[1].strip()
        arg_lower = arg.lower()
        if arg_lower in ("all", "всі", "усі"):
            try:

                def _delete_all_choices():
                    try:
                        n = _db_execute_sync("DELETE FROM user_story_choices", ())
                        conn.commit()
                        return n
                    except Exception:
                        conn.rollback()
                        raise

                deleted = await run_db_call_async(_delete_all_choices)
            except Exception as e:
                await message.answer(f"❌ Помилка: {e}", parse_mode="html")
                return
            await message.answer(
                f"✅ Скинуто вибори в сюжетах для <b>усіх</b> користувачів.\n"
                f"Видалено записів: <b>{deleted}</b>.\n"
                "Відкриті сюжетні картки лишаються - гравці зможуть знову натиснути варіант на розвилці.",
                parse_mode="html",
            )
            return
        try:
            target_user_id = int(arg.strip())
        except ValueError:
            await message.answer(
                "❌ Невірний аргумент. Вкажи <code>user_id</code> (число) або <code>all</code> / <code>всі</code>.",
                parse_mode="html",
            )
            return
        try:

            def _delete_user_choices():
                try:
                    n = _db_execute_sync(
                        "DELETE FROM user_story_choices WHERE user_id = %s",
                        (target_user_id,),
                    )
                    conn.commit()
                    return n
                except Exception:
                    conn.rollback()
                    raise

            deleted = await run_db_call_async(_delete_user_choices)
        except Exception as e:
            await message.answer(f"❌ Помилка: {e}", parse_mode="html")
            return
        await message.answer(
            f"✅ Для користувача <code>{target_user_id}</code> скинуто вибори в сюжетах.\n"
            f"Видалено записів: <b>{deleted}</b>.\n"
            "Користувач зможе знову обрати варіант на кожній розвилці.",
            parse_mode="html",
        )

    async def test_story_handler(self, message: Message):
        """Запустити основний сюжет для тестування. Тільки для засновників.
        Використання: /test_story [user_id] [card_order]
        Без аргументів: card_order=0 (Аль Капоне) собі.
        Приклад: /test_story 123456789 5 - відправити card_order 5 користувачу 123456789."""
        if not message.from_user:
            return
        if not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        parts = (message.text or "").strip().split()
        target_user_id = message.from_user.id
        card_order = 0
        if len(parts) >= 2:
            try:
                target_user_id = int(parts[1])
            except ValueError:
                await message.answer(
                    "❌ Невірний формат. Використання:\n"
                    "<code>/test_story</code> - Аль Капоне собі\n"
                    "<code>/test_story 123456789</code> - Аль Капоне користувачу\n"
                    "<code>/test_story 123456789 5</code> - card_order 5 користувачу",
                    parse_mode="html",
                )
                return
        if len(parts) >= 3:
            try:
                card_order = int(parts[2])
            except ValueError:
                await message.answer("❌ card_order має бути числом (0-17).")
                return
        from commands.story_achievements import run_story_delivery_check, _get_story_card_by_order
        row = _get_story_card_by_order(card_order)
        if not row:
            await message.answer(f"❌ Картка з card_order={card_order} не знайдена.")
            return
        card_id = row[0]
        title = row[1] if len(row) > 1 else ""
        try:
            def _schedule_story():
                try:
                    _db_execute_sync(
                        "DELETE FROM achievement_story_delivery WHERE user_id = %s AND card_id = %s",
                        (target_user_id, card_id),
                    )
                    _db_execute_sync(
                        "INSERT INTO achievement_story_delivery (user_id, card_id, achievement_key, scheduled_send_at) "
                        "VALUES (%s, %s, 'test_story', NOW())",
                        (target_user_id, card_id),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

            await run_db_call_async(_schedule_story)
            await run_story_delivery_check(message.bot)
            await message.answer(
                f"✅ Заплановано та відправлено сюжет «{title}» (card_order={card_order}) користувачу <code>{target_user_id}</code>.",
                parse_mode="html",
            )
        except Exception as e:
            await message.answer(f"❌ Помилка: {e}")

    async def grant_achievements_info_handler(self, callback: CallbackQuery):
        """Показує інструкцію для /grant_achievements"""
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        await callback.message.edit_text(
            "🏆 <b>Видати всі досягнення</b>\n\n"
            "Введи команду:\n<code>/grant_achievements &lt;user_id&gt;</code>\n\n"
            "Приклад: <code>/grant_achievements 123456789</code>\n\n"
            "Користувач отримає всі досягнення та відповідні сюжетні картки.",
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        await callback.answer()

    async def grant_cards_info_handler(self, callback: CallbackQuery):
        """Показує інструкцію для /grant_cards"""
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        await callback.message.edit_text(
            "🃏 <b>Видати всі картки</b>\n\n"
            "Введи команду:\n<code>/grant_cards &lt;user_id&gt;</code>\n\n"
            "Приклад: <code>/grant_cards 123456789</code>\n\n"
            "Користувач отримає всі сюжетні картки. Досягнення не видаються.",
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        await callback.answer()

    async def group_members_handler(self, message: Message):
        """У групі: показати ID учасників (адміністратори + кількість). В ПП: /group_members <chat_id>. Тільки для засновника."""
        if not message.from_user:
            return
        if not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        bot = message.bot
        chat_id = message.chat.id
        chat_type = getattr(message.chat, "type", None)
        # У приватному чаті - очікуємо ID групи в аргументі
        if chat_type == "private":
            text = (message.text or "").strip().split(maxsplit=1)
            if len(text) < 2:
                await message.answer(
                    "👥 <b>ID учасників групи</b>\n\n"
                    "Використовуй команду <b>в групі</b> - тоді бот покаже дані цієї групи.\n\n"
                    "Або в ПП: <code>/group_members &lt;chat_id&gt;</code>\n"
                    "Приклад: <code>/group_members -1001234567890</code>",
                    parse_mode="html",
                )
                return
            try:
                chat_id = int(text[1].strip().replace("\u2212", "-").replace("−", "-"))
            except ValueError:
                await message.answer("❌ Невірний chat_id. Приклад: <code>/group_members -1001234567890</code>", parse_mode="html")
                return
        elif chat_type not in ("group", "supergroup"):
            await message.answer("❌ Ця команда тільки для груп або в ПП з указаним chat_id.")
            return
        try:
            count = await bot.get_chat_member_count(chat_id)
            admins = await bot.get_chat_administrators(chat_id)
        except Exception as e:
            await message.answer(f"❌ Не вдалося отримати дані чату: {e}", parse_mode="html")
            return
        from aiogram.enums import ChatMemberStatus
        lines = [
            f"👥 <b>Чат:</b> <code>{chat_id}</code>",
            f"📊 <b>Учасників усього:</b> {count}",
            "",
            "🛡️ <b>Адміністратори (ID та ім'я):</b>",
        ]
        for m in admins:
            uid = m.user.id
            name = (m.user.first_name or "").strip()
            if getattr(m.user, "last_name", None):
                name = f"{name} {m.user.last_name}".strip() or "-"
            if not name:
                name = "-"
            username = getattr(m.user, "username", None) or ""
            status = getattr(m, "status", None)
            if status == ChatMemberStatus.CREATOR:
                role = " (власник)"
            elif status == ChatMemberStatus.ADMINISTRATOR:
                role = " (адмін)"
            else:
                role = ""
            lines.append(f"• <code>{uid}</code> - {name}@{username}{role}" if username else f"• <code>{uid}</code> - {name}{role}")
        lines.append("")
        lines.append("<i>Примітка: Bot API не дає списку всіх учасників, тільки адмінів та загальну кількість.</i>")
        await message.answer("\n".join(lines), parse_mode="html")

    async def give_coins_cmd_handler(self, message: Message):
        """Видати ліри: /give_coins <user_id> <кількість>. Тільки засновник."""
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        parts = (message.text or "").strip().split()
        if len(parts) < 3:
            await message.answer(
                emoji_to_premium(
                    "💰 <b>Видати ліри</b>\n\n"
                    "Використання: <code>/give_coins &lt;user_id&gt; &lt;кількість&gt;</code>\n"
                    "Приклад: <code>/give_coins 123456789 100</code>"
                ),
                parse_mode="html",
            )
            return
        try:
            target_id = int(parts[1])
            amount = int(parts[2])
        except ValueError:
            await message.answer("❌ Вкажи число для user_id та кількості.")
            return
        if amount <= 0:
            await message.answer("❌ Кількість має бути більше 0.")
            return
        try:
            await _db_execute_commit_async(
                "INSERT INTO users (id, balance) VALUES (%s, 0) ON CONFLICT (id) DO NOTHING",
                (target_id,),
            )
            await _db_execute_commit_async(
                "UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s",
                (amount, target_id),
            )
            row = await _db_fetchone_async(
                "SELECT COALESCE(balance, 0) FROM users WHERE id = %s",
                (target_id,),
            )
            new_balance = row[0] if row else amount
            await message.answer(
                emoji_to_premium(
                    f"✅ Користувачу <code>{target_id}</code> видано <b>{amount}</b> лір.\n"
                    f"💵 Його баланс: <b>{new_balance}</b> лір"
                ),
                parse_mode="html",
            )
        except Exception as e:
            await message.answer(f"❌ Помилка: {e}", parse_mode="html")

    async def vip_daily_all_cmd_handler(self, message: Message):
        """
        Щоденні ліри VIP/VIP+ для всіх активних підписників.
        /vip_daily_all - як автоматика: лише ті, хто ще не отримав сьогодні.
        /vip_daily_all force - нарахувати суму ще раз усім (компенсація).
        """
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        if not _chat_is_private(message.chat):
            await message.answer(
                "❌ Команда <code>/vip_daily_all</code> доступна тільки в особистих повідомленнях з ботом.",
                parse_mode="html",
            )
            return
        parts = (message.text or "").strip().split()
        force = len(parts) > 1 and parts[1].lower() == "force"
        from commands import vip as vip_mod

        n_paid, total, n_vip, recipients = vip_mod.vip_admin_payout_daily_all(force=force)
        mode = "форсовано (усі отримали суму ще раз)" if force else "стандартно (лише хто не отримав сьогодні)"
        await message.answer(
            emoji_to_premium(
                f"✅ <b>VIP щоденні ліри</b> - {mode}\n\n"
                f"Активних VIP у базі: <b>{n_vip}</b>\n"
                f"Нараховано користувачів: <b>{n_paid}</b>\n"
                f"Сума нарахувань: <b>{total}</b> лір"
            ),
            parse_mode="html",
        )
        bot = message.bot
        notify_ok = 0
        notify_fail = 0
        for uid, amt, tier in recipients:
            try:
                user_txt = vip_mod.vip_daily_bonus_notification_html(amt, tier)
                await bot.send_message(
                    uid,
                    emoji_to_premium(user_txt),
                    parse_mode="html",
                )
                notify_ok += 1
            except Exception:
                notify_fail += 1
        if recipients:
            tail = f"Повідомлення в ПП: надіслано <b>{notify_ok}</b>"
            if notify_fail:
                tail += f", не вдалося <b>{notify_fail}</b> (нема чату з ботом / блок)"
            await message.answer(tail + ".", parse_mode="html")

    async def vip_daily_reset_cmd_handler(self, message: Message):
        """
        Скинути vip_daily_grant_day - щоб знову надійшло окреме повідомлення про щоденний VIP
        (при /profile, /start у ПП, відкритті рулетки тощо). Не забирає вже нараховані ліри.
        /vip_daily_reset - для себе; /vip_daily_reset <user_id> - для іншого (тільки засновник).
        """
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        if not _chat_is_private(message.chat):
            await message.answer(
                "❌ Команда <code>/vip_daily_reset</code> доступна тільки в особистих повідомленнях з ботом.",
                parse_mode="html",
            )
            return
        parts = (message.text or "").strip().split()
        if len(parts) >= 2:
            try:
                target_id = int(parts[1].strip())
            except ValueError:
                await message.answer(
                    "❌ Вкажи числовий <code>user_id</code> або використай <code>/vip_daily_reset</code> без аргументів (скинути собі).",
                    parse_mode="html",
                )
                return
        else:
            target_id = message.from_user.id
        from commands import vip as vip_mod

        ok = vip_mod.vip_reset_daily_grant_flag(target_id)
        if ok:
            await message.answer(
                emoji_to_premium(
                    f"✅ Скинуто позначку щоденного VIP-бонусу для <code>{target_id}</code>.\n\n"
                    f"Напиши <code>/profile</code> або <code>/start</code> (у ПП) - має знову прийти повідомлення з нарахуванням (якщо є VIP/VIP+)."
                ),
                parse_mode="html",
            )
        else:
            await message.answer(
                "❌ Не вдалося скинути (перевір БД або наявність рядка roulette_profiles).",
                parse_mode="html",
            )

    async def vip_paid_list_cmd_handler(self, message: Message):
        """
        /vip_paid_list - список тільки платних VIP/VIP+:
        без тестового VIP, адвенту і адмінської видачі.
        """
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        if not _chat_is_private(message.chat):
            await message.answer(
                "❌ Команда <code>/vip_paid_list</code> доступна тільки в особистих повідомленнях з ботом.",
                parse_mode="html",
            )
            return

        text = await self._build_vip_paid_list_text()
        try:
            await message.answer(emoji_to_premium(text), parse_mode="html")
        except Exception:
            await message.answer("❌ Не вдалося показати список. Спробуй ще раз.", parse_mode="html")

    async def vip_paid_list_callback_handler(self, callback: CallbackQuery):
        if not callback.from_user or not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        # Відповідаємо одразу, щоб не було «вічного завантаження» у клієнті.
        await callback.answer("Завантажую список…")
        try:
            text = await asyncio.wait_for(self._build_vip_paid_list_text(), timeout=12.0)
        except asyncio.TimeoutError:
            text = (
                "⚠️ <b>Список завантажується занадто довго.</b>\n\n"
                "Спробуй ще раз через кілька секунд або відкрий через команду "
                "<code>/vip_paid_list</code>."
            )
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        try:
            await callback.message.edit_text(
                emoji_to_premium(text),
                parse_mode="html",
                reply_markup=builder.as_markup(),
            )
        except Exception:
            try:
                await callback.message.answer(
                    emoji_to_premium(text),
                    parse_mode="html",
                    reply_markup=builder.as_markup(),
                )
            except Exception:
                pass

    async def _build_vip_paid_list_text(self) -> str:
        def _col(row, idx, default=None):
            if isinstance(row, (tuple, list)) and len(row) > idx:
                return row[idx]
            return default

        try:
            paid_rows = _db_fetchall_sync(
                """
                SELECT
                    sp.user_id,
                    COALESCE(NULLIF(TRIM(u.tg_name), ''), NULLIF(TRIM(u.link), ''), '-') AS user_name,
                    sp.item_type,
                    sp.amount_paid,
                    sp.currency,
                    sp.purchase_date
                FROM shop_purchases sp
                LEFT JOIN users u ON u.id = sp.user_id
                WHERE sp.item_type IN ('vip_30', 'vip_plus_30')
                  AND COALESCE(sp.refunded, FALSE) = FALSE
                  AND COALESCE(sp.telegram_payment_charge_id, '') NOT LIKE 'admin_grant_%%'
                ORDER BY sp.purchase_date DESC
                LIMIT 50
                """
            )

            active_rows = _db_fetchall_sync(
                """
                SELECT
                    s.user_id,
                    COALESCE(NULLIF(TRIM(u.tg_name), ''), NULLIF(TRIM(u.link), ''), '-') AS user_name,
                    s.subscription_type,
                    s.subscription_end
                FROM subscriptions s
                LEFT JOIN users u ON u.id = s.user_id
                WHERE s.is_active = TRUE
                  AND s.subscription_type IN ('vip_30', 'vip_plus_30')
                  AND COALESCE(s.is_purchased, FALSE) = TRUE
                  AND (s.subscription_end IS NULL OR s.subscription_end > CURRENT_TIMESTAMP)
                ORDER BY s.subscription_end DESC NULLS LAST
                LIMIT 100
                """
            )
        except Exception as e:
            return (
                "❌ <b>Помилка завантаження платного VIP списку</b>\n\n"
                f"<code>{html.escape(str(e))}</code>"
            )

        text = "💳 <b>Платний VIP/VIP+</b>\n<i>(без тестового VIP, адвенту та адмін-видачі)</i>\n\n"

        purchases_to_show = 12
        active_to_show = 25

        text += "<b>Останні покупки:</b>\n"
        if not paid_rows:
            text += "• Немає записів.\n"
        else:
            for idx, row in enumerate(paid_rows[:purchases_to_show], 1):
                uid = _col(row, 0, "-")
                uname = _col(row, 1, "-")
                item_type = _col(row, 2, "vip_30")
                amount_paid = _col(row, 3, 0)
                currency = _col(row, 4, "XTR")
                purchase_date = _col(row, 5, None)
                label = "VIP+" if item_type == "vip_plus_30" else "VIP"
                d = purchase_date.strftime("%d.%m.%Y %H:%M") if hasattr(purchase_date, "strftime") else str(purchase_date)
                text += (
                    f"{idx}. <code>{uid}</code> • {html.escape(str(uname or '-'))}\n"
                    f"   {label} • {amount_paid} {html.escape(str(currency or 'XTR'))} • {d}\n"
                )
            if len(paid_rows) > purchases_to_show:
                text += f"... та ще {len(paid_rows) - purchases_to_show}\n"

        text += "\n<b>Активний VIP з покупки:</b>\n"
        if not active_rows:
            text += "• Немає активних.\n"
        else:
            for idx, row in enumerate(active_rows[:active_to_show], 1):
                uid = _col(row, 0, "-")
                uname = _col(row, 1, "-")
                sub_type = _col(row, 2, "vip_30")
                sub_end = _col(row, 3, None)
                label = "VIP+" if sub_type == "vip_plus_30" else "VIP"
                end_str = sub_end.strftime("%d.%m.%Y %H:%M") if hasattr(sub_end, "strftime") else "Без обмежень"
                text += f"{idx}. <code>{uid}</code> • {html.escape(str(uname or '-'))} • {label} • до {end_str}\n"
            if len(active_rows) > active_to_show:
                text += f"... та ще {len(active_rows) - active_to_show}\n"

        return text

    async def give_gold_cmd_handler(self, message: Message):
        """Видати золоті монети (донат): /give_gold <user_id> <кількість>. Тільки засновник."""
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        parts = (message.text or "").strip().split()
        if len(parts) < 3:
            await message.answer(
                emoji_to_premium(
                    "🪙 <b>Видати золоті монети</b>\n\n"
                    "Використання: <code>/give_gold &lt;user_id&gt; &lt;кількість&gt;</code>\n"
                    "Приклад: <code>/give_gold 123456789 50</code>"
                ),
                parse_mode="html",
            )
            return
        try:
            target_id = int(parts[1])
            amount = int(parts[2])
        except ValueError:
            await message.answer("❌ Вкажи число для user_id та кількості.")
            return
        if amount <= 0:
            await message.answer("❌ Кількість має бути більше 0.")
            return
        try:
            await _db_execute_commit_async(
                "INSERT INTO users (id, balance, donate_coins) VALUES (%s, 0, 0) ON CONFLICT (id) DO NOTHING",
                (target_id,),
            )
            await _db_execute_commit_async(
                "UPDATE users SET donate_coins = COALESCE(donate_coins, 0) + %s WHERE id = %s",
                (amount, target_id),
            )
            row = await _db_fetchone_async(
                "SELECT COALESCE(donate_coins, 0) FROM users WHERE id = %s",
                (target_id,),
            )
            new_gold = row[0] if row else amount
            await message.answer(
                emoji_to_premium(
                    f"✅ Користувачу <code>{target_id}</code> видано <b>{amount}</b> золотих монет.\n"
                    f"🪙 Його донат-баланс: <b>{new_gold}</b> золотих монет"
                ),
                parse_mode="html",
            )
            try:
                await message.bot.send_message(
                    target_id,
                    emoji_to_premium(
                        f"🪙 <b>Вам нараховано золоті монети!</b>\n\n"
                        f"Нараховано: <b>{amount}</b> золотих монет\n"
                        f"💵 Ваш баланс золотих монет: <b>{new_gold}</b>"
                    ),
                    parse_mode="html",
                )
            except Exception:
                pass
        except Exception as e:
            await message.answer(f"❌ Помилка: {e}", parse_mode="html")

    async def april_gold_cmd_handler(self, message: Message):
        """
        1 квітня: фейкова «видача» золота без змін у БД.
        /april_gold <user_id|all> [amount]
        """
        if not _chat_is_private(message.chat):
            await message.answer(
                "❌ Команда <code>/april_gold</code> доступна тільки в особистих повідомленнях з ботом.",
                parse_mode="html",
            )
            return
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return

        parts = (message.text or "").strip().split()
        if len(parts) < 2:
            await message.answer(
                emoji_to_premium(
                    "🎭 <b>1 квітня: фейкова видача золота</b>\n\n"
                    "Використання:\n"
                    "<code>/april_gold &lt;user_id&gt; [кількість]</code>\n"
                    "<code>/april_gold all [кількість]</code>\n\n"
                    "За замовчуванням кількість: <b>1000000</b>.\n"
                    "<i>Команда лише надсилає повідомлення, БД не змінюється.</i>"
                ),
                parse_mode="html",
            )
            return

        target = (parts[1] or "").strip().lower()
        amount = 1_000_000
        if len(parts) >= 3:
            try:
                amount = int(parts[2])
            except ValueError:
                await message.answer("❌ Кількість має бути числом.", parse_mode="html")
                return
        if amount <= 0:
            await message.answer("❌ Кількість має бути більше 0.", parse_mode="html")
            return

        prank_text = emoji_to_premium(
            "🎉 <b>Вітаємо!</b>\n\n"
            f"На ваш акаунт нараховано <b>{amount:,}</b> золотих монет.\n"
        ).replace(",", " ")

        recipients: list[int] = []
        if target == "all":
            recipients = [int(uid) for uid in (get_all_broadcast_user_ids() or [])]
        else:
            try:
                recipients = [int(parts[1])]
            except ValueError:
                await message.answer("❌ Вкажи <code>user_id</code> числом або <code>all</code>.", parse_mode="html")
                return

        if not recipients:
            await message.answer("❌ Немає користувачів для відправки.", parse_mode="html")
            return

        status = await message.answer(f"📤 Відправляю фейкову видачу для {len(recipients)} користувачів…")
        ok = 0
        fail = 0
        for uid in recipients:
            try:
                await message.bot.send_message(uid, prank_text, parse_mode="html")
                ok += 1
            except Exception:
                fail += 1

        await status.edit_text(
            emoji_to_premium(
                "✅ <b>Готово.</b>\n\n"
                f"Надіслано: <b>{ok}</b>\n"
                f"Помилки: <b>{fail}</b>\n\n"
                "<i>Це була фейкова видача: баланс у БД не змінювався.</i>"
            ),
            parse_mode="html",
        )

    async def give_vip_cmd_handler(self, message: Message):
        """
        Видати підписку VIP / VIP+ (подарунок адміна).
        /give_vip <user_id> [vip|vip+] [місяці] - аргументи після id в довільному порядку.
        1 місяць = 30 днів (як у магазині). Місяці: 1…120, за замовчуванням 1.
        Тільки засновники; тільки в ПП.
        """
        if not _chat_is_private(message.chat):
            await message.answer(
                "❌ Команда <code>/give_vip</code> доступна тільки в особистих повідомленнях з ботом.",
                parse_mode="html",
            )
            return
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        parts = (message.text or "").strip().split()
        if len(parts) < 2:
            await message.answer(
                emoji_to_premium(
                    "⚒️ <b>Видати VIP</b>\n\n"
                    "Використання: <code>/give_vip &lt;user_id&gt; [vip|vip+] [місяці]</code>\n\n"
                    "• <code>vip</code> - ⚒️ VIP, за замовчуванням\n"
                    "• <code>vip+</code> / <code>plus</code> - ⛏️ VIP+\n"
                    "• <b>місяці</b> - скільки разів по 30 дн. (1…120); можна перед або після типу\n\n"
                    "Приклади:\n"
                    "<code>/give_vip 123456789</code>\n"
                    "<code>/give_vip 123456789 vip+</code>\n"
                    "<code>/give_vip 123456789 vip+ 7</code>\n"
                    "<code>/give_vip 123456789 7 vip</code>"
                ),
                parse_mode="html",
            )
            return
        try:
            target_id = int(parts[1])
        except ValueError:
            await message.answer("❌ <code>user_id</code> має бути числом.", parse_mode="html")
            return

        _PLUS = frozenset({"vip+", "vip_plus", "plus", "плюс", "vipplus"})
        _BASE = frozenset({"vip", "base"})
        tier: str | None = None
        months: int | None = None
        for raw in parts[2:]:
            t = raw.lower().strip()
            if t.isdigit():
                m = int(t)
                if months is not None:
                    await message.answer(
                        "❌ Кількість місяців вкажи один раз (число 1…120).",
                        parse_mode="html",
                    )
                    return
                if m < 1 or m > 120:
                    await message.answer(
                        "❌ Місяців має бути від <b>1</b> до <b>120</b>.",
                        parse_mode="html",
                    )
                    return
                months = m
                continue
            if t in _PLUS:
                if tier == "vip":
                    await message.answer(
                        "❌ Вкажи один тип: <code>vip</code> або <code>vip+</code>, не обидва.",
                        parse_mode="html",
                    )
                    return
                tier = "vip_plus"
                continue
            if t in _BASE:
                if tier == "vip_plus":
                    await message.answer(
                        "❌ Вкажи один тип: <code>vip</code> або <code>vip+</code>, не обидва.",
                        parse_mode="html",
                    )
                    return
                tier = "vip"
                continue
            await message.answer(
                f"❌ Невідомий аргумент: <code>{html.escape(raw)}</code>. "
                "Очікується <code>vip</code>, <code>vip+</code> або число місяців.",
                parse_mode="html",
            )
            return

        if months is None:
            months = 1
        item_id = "vip_plus_30" if tier == "vip_plus" else "vip_30"
        item = ShopManager.get_item(item_id)
        if not item:
            await message.answer(
                "❌ Тип підписки не знайдено в магазині.",
                parse_mode="html",
            )
            return
        admin_id = message.from_user.id
        try:
            now = datetime.now()
            unit_days = int(item.duration_days) if item.duration_days and item.duration_days > 0 else 30
            duration_days = unit_days * months
            end_date = now + timedelta(days=duration_days)
            charge_id = f"admin_vip_{admin_id}_{months}m_{datetime.now().timestamp()}"
            gift_label = f"{item.name} (Адмін VIP, {months} міс.)"

            def _grant_vip():
                try:
                    _db_execute_sync(
                        "INSERT INTO users (id, balance) VALUES (%s, 0) ON CONFLICT (id) DO NOTHING",
                        (target_id,),
                    )
                    exists = _db_fetchone_sync("SELECT user_id FROM subscriptions WHERE user_id = %s", (target_id,))
                    if exists:
                        _db_execute_sync(
                            """
                            UPDATE subscriptions
                            SET subscription_type = %s, subscription_start = %s, subscription_end = %s,
                                is_active = TRUE, is_purchased = FALSE, updated_at = %s
                            WHERE user_id = %s
                            """,
                            (item.item_id, now, end_date, now, target_id),
                        )
                    else:
                        _db_execute_sync(
                            """
                            INSERT INTO subscriptions (user_id, subscription_type, subscription_start, subscription_end, is_active, is_purchased)
                            VALUES (%s, %s, %s, %s, TRUE, FALSE)
                            """,
                            (target_id, item.item_id, now, end_date),
                        )
                    _db_execute_sync(
                        """
                        INSERT INTO shop_purchases (user_id, item_name, item_type, amount_paid, currency, telegram_payment_charge_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (target_id, gift_label, item.item_id, 0, "ADMIN", charge_id),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

            await run_db_call_async(_grant_vip)
            vip_mod.clear_vip_farewell_flag(target_id)
            end_txt = end_date.strftime("%d.%m.%Y %H:%M") if end_date else " - "
            if months % 10 == 1 and months % 100 != 11:
                month_word = "місяць"
            elif months % 10 in (2, 3, 4) and months % 100 not in (12, 13, 14):
                month_word = "місяці"
            else:
                month_word = "місяців"
            await message.answer(
                emoji_to_premium(
                    f"✅ Користувачу <code>{target_id}</code> видано: <b>{item.name}</b>\n"
                    f"Термін: <b>{months}</b> {month_word} (<b>{duration_days}</b> дн.)\n"
                    f"Діє до: <b>{end_txt}</b>\n"
                    f"<i>Подарунок адміна (не покупка).</i>"
                ),
                parse_mode="html",
            )
            try:
                await message.bot.send_message(
                    target_id,
                    emoji_to_premium(
                        f"💎 <b>Вам видано підписку!</b>\n\n"
                        f"{item.name}\n"
                        f"📅 Термін: <b>{months}</b> {month_word} ({duration_days} дн.)\n"
                        f"До: <b>{end_txt}</b>\n\n"
                        "Приємної гри!"
                    ),
                    parse_mode="html",
                )
            except Exception:
                pass
        except Exception as e:
            await message.answer(f"❌ Помилка: {html.escape(str(e))}", parse_mode="html")

    async def give_marigolds_cmd_handler(self, message: Message):
        """Видати лимони: /give_marigolds <user_id> <кількість>. Тільки засновник."""
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        parts = (message.text or "").strip().split()
        if len(parts) < 3:
            await message.answer(
                emoji_to_premium(
                    "🍋 <b>Видати лимони</b>\n\n"
                    "Використання: <code>/give_marigolds &lt;user_id&gt; &lt;кількість&gt;</code>\n"
                    "Приклад: <code>/give_marigolds 123456789 10</code>",
                    skip_vip_badges=False,
                ),
                parse_mode="html",
            )
            return
        try:
            target_id = int(parts[1])
            amount = int(parts[2])
        except ValueError:
            await message.answer("❌ Вкажи число для user_id та кількості.")
            return
        if amount <= 0:
            await message.answer("❌ Кількість має бути більше 0.")
            return
        try:
            await _db_execute_commit_async(
                "INSERT INTO users (id, balance, donate_coins, marigolds) VALUES (%s, 0, 0, 0) ON CONFLICT (id) DO NOTHING",
                (target_id,),
            )
            await _db_execute_commit_async(
                "UPDATE users SET marigolds = COALESCE(marigolds, 0) + %s WHERE id = %s",
                (amount, target_id),
            )
            row = await _db_fetchone_async(
                "SELECT COALESCE(marigolds, 0) FROM users WHERE id = %s",
                (target_id,),
            )
            new_marigolds = row[0] if row else amount
            await message.answer(
                emoji_to_premium(
                    f"✅ Користувачу <code>{target_id}</code> видано <b>{amount}</b> лимонів 🍋.\n"
                    f"🍋 Його баланс лимонів: <b>{new_marigolds}</b>",
                    skip_vip_badges=False,
                ),
                parse_mode="html",
            )
        except Exception as e:
            await message.answer(f"❌ Помилка: {e}", parse_mode="html")

    async def send_to_user_cmd_handler(self, message: Message):
        """Написати комусь через бота. Тільки власники. Використання: /send_to <user_id>"""
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        text = (message.text or "").strip().split(maxsplit=1)
        if len(text) < 2:
            await message.answer(
                "📩 <b>Написати користувачу</b>\n\n"
                "Використання: <code>/send_to &lt;user_id&gt;</code>\n"
                "Приклад: <code>/send_to 123456789</code>\n\n"
                "Після цього надішли текст повідомлення (або <code>/cancel</code> щоб скасувати).",
                parse_mode="html",
            )
            return
        try:
            target_id = int(text[1].strip())
        except ValueError:
            await message.answer("❌ Вкажи числовий Telegram ID користувача. Приклад: <code>/send_to 123456789</code>", parse_mode="html")
            return
        self.temp_send_to_target_id = target_id
        self.is_inputting_send_to_message = True
        self.waiting_send_to_user_id = message.from_user.id
        await message.answer(
            f"📩 Надішли текст повідомлення для користувача <code>{target_id}</code>.\n"
            "Скасувати: <code>/cancel</code>",
            parse_mode="html",
        )

    async def send_to_message_handler(self, message: Message, bot: Bot):
        """Обробка тексту повідомлення для /send_to (відправка одержувачу)."""
        text = (message.text or "").strip()
        if not text:
            return
        if text.lower() == "/cancel":
            self.is_inputting_send_to_message = False
            self.temp_send_to_target_id = None
            self.waiting_send_to_user_id = None
            await message.answer("❌ Скасовано.")
            return
        target_id = self.temp_send_to_target_id
        if not target_id:
            self.is_inputting_send_to_message = False
            self.waiting_send_to_user_id = None
            return
        try:
            await bot.send_message(
                chat_id=target_id,
                text=text,
                parse_mode="html",
            )
            await message.answer(f"✅ Повідомлення надіслано користувачу <code>{target_id}</code>.", parse_mode="html")
        except Exception as e:
            await message.answer(f"❌ Не вдалося надіслати: {e}\n\nМожливо, користувач не писав боту або заблокував його.", parse_mode="html")
        self.is_inputting_send_to_message = False
        self.temp_send_to_target_id = None
        self.waiting_send_to_user_id = None

    async def broadcast_cmd_handler(self, message: Message):
        """Розсилка повідомлення всім користувачам. Тільки засновники. Після /broadcast - надіслати текст або фото з підписом."""
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Ця команда доступна тільки засновникам бота.")
            return
        self.is_inputting_broadcast_message = True
        self.waiting_broadcast_user_id = message.from_user.id
        await message.answer(
            "📢 <b>Розсилка</b>\n\n"
            "Надішли текст повідомлення або фото з підписом - воно буде надіслано всім користувачам бота.\n\n"
            "Скасувати: <code>/cancel</code>",
            parse_mode="html",
        )

    async def _ensure_broadcast_v2_tables(self) -> None:
        await _db_execute_commit_async(
            """
            CREATE TABLE IF NOT EXISTS broadcast_campaigns (
                id BIGSERIAL PRIMARY KEY,
                created_by BIGINT NOT NULL,
                content_text TEXT,
                has_photo BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await _db_execute_commit_async(
            """
            CREATE TABLE IF NOT EXISTS broadcast_deliveries (
                campaign_id BIGINT NOT NULL REFERENCES broadcast_campaigns(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL,
                message_id BIGINT NOT NULL,
                delivered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (campaign_id, user_id)
            )
            """
        )
        await _db_execute_commit_async(
            "CREATE INDEX IF NOT EXISTS idx_broadcast_deliveries_campaign ON broadcast_deliveries(campaign_id)"
        )

    async def broadcast_message_handler(self, message: Message, bot: Bot):
        """Обробка повідомлення для розсилки: текст або фото з підписом."""
        raw_text = (message.text or message.caption or "").strip()
        if raw_text.lower() == "/cancel":
            self.is_inputting_broadcast_message = False
            self.waiting_broadcast_user_id = None
            await message.answer("❌ Розсилку скасовано.")
            return
        has_photo = bool(getattr(message, "photo", None))
        content_text = emoji_to_premium(raw_text or "")
        if not has_photo and not content_text:
            await message.answer("❌ Надішли текст або фото з підписом. Скасувати: <code>/cancel</code>", parse_mode="html")
            return
        await self._ensure_broadcast_v2_tables()
        user_ids = get_all_broadcast_user_ids()
        if not user_ids:
            self.is_inputting_broadcast_message = False
            self.waiting_broadcast_user_id = None
            await message.answer("❌ Немає користувачів для розсилки.")
            return
        status = await message.answer(f"📤 Розсилаю повідомлення {len(user_ids)} користувачам…")
        campaign_row = await _db_fetchone_async(
            """
            INSERT INTO broadcast_campaigns (created_by, content_text, has_photo)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (message.from_user.id if message.from_user else 0, raw_text or "", bool(has_photo)),
        )
        campaign_id = int(campaign_row[0]) if campaign_row else 0
        ok = 0
        fail = 0
        for uid in user_ids:
            try:
                if has_photo:
                    photo = message.photo[-1]
                    sent = await bot.send_photo(
                        chat_id=uid,
                        photo=photo.file_id,
                        caption=content_text if content_text else None,
                        parse_mode="html",
                    )
                else:
                    sent = await bot.send_message(
                        chat_id=uid,
                        text=content_text,
                        parse_mode="html",
                    )
                if campaign_id:
                    await _db_execute_commit_async(
                        """
                        INSERT INTO broadcast_deliveries (campaign_id, user_id, message_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (campaign_id, user_id) DO UPDATE SET message_id = EXCLUDED.message_id, delivered_at = CURRENT_TIMESTAMP
                        """,
                        (campaign_id, int(uid), int(sent.message_id)),
                    )
                ok += 1
            except Exception:
                fail += 1
        self.is_inputting_broadcast_message = False
        self.waiting_broadcast_user_id = None
        await status.edit_text(
            f"✅ Розсилка завершена.\n\n"
            f"ID розсилки (v2): <b>{campaign_id}</b>\n"
            f"Доставлено: <b>{ok}</b>\n"
            f"Не вдалося (блокування/помилка): <b>{fail}</b>",
            parse_mode="html",
        )

    async def _delete_broadcast_by_id(self, bot: Bot, campaign_id: int) -> tuple[int, int]:
        rows = await _db_fetchall_async(
            "SELECT user_id, message_id FROM broadcast_deliveries WHERE campaign_id = %s",
            (campaign_id,),
        )
        ok = 0
        fail = 0
        for uid, mid in rows or []:
            try:
                await bot.delete_message(chat_id=int(uid), message_id=int(mid))
                ok += 1
            except Exception:
                fail += 1
        return ok, fail

    async def broadcast_delete_last_cmd_handler(self, message: Message, bot: Bot):
        """Видалити останню розсилку v2."""
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Ця команда доступна тільки засновникам бота.")
            return
        await self._ensure_broadcast_v2_tables()
        row = await _db_fetchone_async("SELECT id FROM broadcast_campaigns ORDER BY id DESC LIMIT 1")
        if not row:
            await message.answer("❌ Немає збережених розсилок v2.")
            return
        campaign_id = int(row[0])
        ok, fail = await self._delete_broadcast_by_id(bot, campaign_id)
        await message.answer(
            f"🧹 Видалення розсилки <b>#{campaign_id}</b> завершено.\n"
            f"Видалено: <b>{ok}</b>\n"
            f"Не вдалося: <b>{fail}</b>",
            parse_mode="html",
        )

    async def broadcast_delete_cmd_handler(self, message: Message, bot: Bot):
        """Видалити розсилку v2 за ID: /broadcast_delete <id>."""
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Ця команда доступна тільки засновникам бота.")
            return
        await self._ensure_broadcast_v2_tables()
        parts = (message.text or "").strip().split()
        if len(parts) < 2:
            await message.answer(
                "Використання: <code>/broadcast_delete &lt;id&gt;</code>\n"
                "Приклад: <code>/broadcast_delete 12</code>",
                parse_mode="html",
            )
            return
        try:
            campaign_id = int(parts[1])
        except Exception:
            await message.answer("❌ ID має бути числом.")
            return
        exists = await _db_fetchone_async("SELECT id FROM broadcast_campaigns WHERE id = %s", (campaign_id,))
        if not exists:
            await message.answer("❌ Розсилку з таким ID не знайдено.")
            return
        ok, fail = await self._delete_broadcast_by_id(bot, campaign_id)
        await message.answer(
            f"🧹 Видалення розсилки <b>#{campaign_id}</b> завершено.\n"
            f"Видалено: <b>{ok}</b>\n"
            f"Не вдалося: <b>{fail}</b>",
            parse_mode="html",
        )

    async def advent_reset_cmd_handler(self, message: Message):
        """Скинути адвент-календар для користувача по ID. Тільки засновник. Використання: /advent_reset <user_id>"""
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        parts = (message.text or "").strip().split()
        if len(parts) < 2:
            await message.answer(
                "🌸 <b>Скинути адвент для користувача</b>\n\n"
                "Використання: <code>/advent_reset &lt;user_id&gt;</code>\n"
                "Приклад: <code>/advent_reset 123456789</code>\n\n"
                "Після скидання у цього користувача календар знову буде з дня 1.",
                parse_mode="html",
            )
            return
        try:
            target_id = int(parts[1].strip())
        except ValueError:
            await message.answer("❌ Вкажи числовий Telegram ID. Приклад: <code>/advent_reset 123456789</code>", parse_mode="html")
            return
        deleted = reset_advent_for_user(target_id)
        await message.answer(
            f"✅ Адвент скинуто для користувача <code>{target_id}</code>. Видалено записів: <b>{deleted}</b>. Календар знову від дня 1.",
            parse_mode="html",
        )

    async def advent_reset_all_cmd_handler(self, message: Message):
        """Скинути адвент-календар для всіх користувачів. Тільки засновник. Команда: /advent_reset_all"""
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        deleted = reset_advent_for_all()
        await message.answer(
            f"✅ Адвент скинуто для <b>всіх</b>. Видалено записів: <b>{deleted}</b>. У всіх календар знову від дня 1.",
            parse_mode="html",
        )

    async def advent_reset_day_all_cmd_handler(self, message: Message):
        """
        Скинути один день адвенту для всіх користувачів.
        Тільки засновник. Команда: /advent_reset_day_all <day_number>, наприклад /advent_reset_day_all 9
        """
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        parts = (message.text or "").strip().split()
        if len(parts) < 2:
            await message.answer(
                "🌸 <b>Скинути один день адвенту для всіх</b>\n\n"
                "Використання: <code>/advent_reset_day_all &lt;day_number(1-31)&gt;</code>\n"
                "Приклад (день 9): <code>/advent_reset_day_all 9</code>\n\n"
                "Після скидання всі користувачі зможуть знову відкрити саме цей день і заново обрати баф (якщо день з вибором бафа).",
                parse_mode="html",
            )
            return
        try:
            day_num = int(parts[1].strip())
        except ValueError:
            await message.answer("❌ День має бути числом від 1 до 31.", parse_mode="html")
            return
        if day_num < 1 or day_num > 31:
            await message.answer("❌ День має бути в межах 1-31.", parse_mode="html")
            return
        deleted = reset_advent_day_for_all(day_num)
        await message.answer(
            f"✅ День <b>{day_num}</b> адвенту скинуто для всіх користувачів.\n"
            f"🗂 Видалено відкриттів цього дня: <b>{deleted}</b>.\n"
            "Користувачі зможуть знову відкрити саме цей день і, якщо потрібно, заново обрати баф.",
            parse_mode="html",
        )

    async def upload_role_card_cmd_handler(self, message: Message, bot: Bot):
        """
        Завантажити картку ролі (зображення) для стандартної або кастомної ролі.
        Тільки засновник. Використання:
        - надіслати фото з підписом: /upload_role_card НазваРолі
        - або написати /upload_role_card НазваРолі у відповіді на повідомлення з фото.
        Файл зберігається в Media/role_announce/role_images/<НазваРолі>.jpg
        """
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "🖼 <b>Завантажити картку ролі</b>\n\n"
                "Використання:\n"
                "1) Надіслати фото з підписом:\n"
                "<code>/upload_role_card НазваРолі</code>\n\n"
                "2) Або відповісти на повідомлення з фото командою:\n"
                "<code>/upload_role_card НазваРолі</code>\n\n"
                "Назва ролі має повністю збігатися з тим, як вона показується гравцям.",
                parse_mode="html",
            )
            return
        role_name = parts[1].strip()
        if not role_name:
            await message.answer("❌ Вкажи назву ролі після команди.", parse_mode="html")
            return
        photo_msg = message
        if not photo_msg.photo and message.reply_to_message:
            photo_msg = message.reply_to_message
        if not photo_msg.photo:
            await message.answer(
                "❌ Не знайдено фото.\n\n"
                "Надішли фото з підписом /upload_role_card НазваРолі або відповідай командою на повідомлення з фото.",
                parse_mode="html",
            )
            return
        photo = photo_msg.photo[-1]
        # Обмеження за розміром файлу (наприклад до 5 МБ)
        max_bytes = 5 * 1024 * 1024
        if getattr(photo, "file_size", 0) and photo.file_size > max_bytes:
            await message.answer("❌ Фото надто велике. Використай зображення до 5 МБ.", parse_mode="html")
            return
        safe_name = role_name.strip()
        # Проста нормалізація імені файлу
        for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
            safe_name = safe_name.replace(ch, "_")
        if not safe_name:
            await message.answer("❌ Некоректна назва ролі для імені файлу.", parse_mode="html")
            return
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Media", "role_announce", "role_images"))
        os.makedirs(base_dir, exist_ok=True)
        dest_path = os.path.join(base_dir, f"{safe_name}.jpg")
        try:
            file = await bot.get_file(photo.file_id)
            await bot.download_file(file.file_path, dest_path)
        except Exception as e:
            await message.answer(f"❌ Не вдалося зберегти картку ролі: {e}", parse_mode="html")
            return
        await message.answer(
            f"✅ Картку ролі для <b>{html.escape(role_name)}</b> збережено.\n"
            "Вона буде показуватись гравцям при видачі цієї ролі (якщо назва ролі збігається).",
            parse_mode="html",
        )

    async def reset_stats_all_cmd_handler(self, message: Message):
        """Скинути ВСЕ у всіх (гроші, бафи, досягнення, картки, адвент, підписки тощо), окрім засновників. /reset_stats_all"""
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        founder_ids = get_active_founder_ids()
        try:
            counts = reset_all_user_data_except_founders()
        except Exception as e:
            await message.answer(f"❌ Помилка: {e}", parse_mode="html")
            return
        founders_note = f" (засновники - {len(founder_ids)} осіб - не змінені)" if founder_ids else ""
        users_n = counts.get("users", 0)
        lines = [
            f"✅ <b>Повне скидання виконано</b>{founders_note}.",
            f"Оновлено користувачів: <b>{users_n}</b>.",
            "",
            "Що обнулено:",
            f"• Гроші (ліри, золоті), статистика (killed, cured, votes): <b>{counts.get('users', 0)}</b>",
            f"• Бафи: <b>{counts.get('user_buffs', 0)}</b> записів",
            f"• Досягнення: <b>{counts.get('user_achievement_progress', 0)}</b>",
            f"• Сюжетні картки: <b>{counts.get('user_story_cards', 0)}</b>",
            f"• Адвент: <b>{counts.get('advent_opens', 0)}</b> відкриттів, <b>{counts.get('advent_buff_choice', 0)}</b> виборів бафа",
            f"• Підписки: <b>{counts.get('subscriptions', 0)}</b>",
            f"• Активації промокодів: <b>{counts.get('promocode_activations', 0)}</b>",
            f"• Вибір у сюжеті та доставка: <b>{counts.get('user_story_choices', 0)}</b> / <b>{counts.get('achievement_story_delivery', 0)}</b>",
            f"• Історія покупок бафів: <b>{counts.get('buff_purchases', 0)}</b>",
            "• Стартовий подарунок позначку знято - можна отримати знову.",
        ]
        await message.answer("\n".join(lines), parse_mode="html")

    async def construct_access_cmd_handler(self, message: Message):
        """Дати собі доступ до /construct_event для групи. Тільки засновник. Використання: /construct_access <group_id>"""
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        parts = (message.text or "").strip().split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "🔧 <b>Доступ до конструктора подій</b>\n\n"
                "Використання: <code>/construct_access &lt;group_id&gt;</code>\n"
                "Приклад: <code>/construct_access -1001234567890</code>\n\n"
                "Додає тебе як адміна 3 рівня для цієї групи - з’явишся в <code>/construct_event</code> і зможеш редагувати ролі цієї групи.",
                parse_mode="html",
            )
            return
        raw = parts[1].strip().replace("\u2212", "-").replace("−", "-").replace(" ", "")
        try:
            group_id = int(raw)
        except ValueError:
            await message.answer("❌ Невірний ID групи. Приклад: <code>/construct_access -1001234567890</code>", parse_mode="html")
            return
        row = await _db_fetchone_async("SELECT 1 FROM admin_panel WHERE group_id = %s", (group_id,))
        if not row:
            await message.answer(
                f"❌ Група <code>{group_id}</code> не зареєстрована в боті (немає в admin_panel). "
                "Спочатку група має бути додана через бота (наприклад власником групи).",
                parse_mode="html",
            )
            return
        ok = set_group_admin(group_id, message.from_user.id, 3, message.from_user.id)
        if ok:
            await message.answer(
                f"✅ <b>Доступ надано.</b>\n\n"
                f"Ти доданий як адмін 3 рівня для групи <code>{group_id}</code>.\n\n"
                f"Тепер у <code>/construct_event</code> ця група з’явиться в списку - можеш редагувати ролі.",
                parse_mode="html",
            )
        else:
            await message.answer("❌ Не вдалося записати доступ. Спробуй ще раз.", parse_mode="html")

    async def show_main_menu(self, message_or_callback):
        """Show main founder panel menu"""
        if isinstance(message_or_callback, CallbackQuery):
            message = message_or_callback.message
            user_id = message_or_callback.from_user.id
        else:
            message = message_or_callback
            user_id = message.from_user.id

        if not message or not message.chat or not _chat_is_private(message.chat):
            if isinstance(message_or_callback, CallbackQuery):
                try:
                    await message_or_callback.answer(
                        "Панель лише в ПП з ботом. Надішли /capone_admin у особистих повідомленнях.",
                        show_alert=True,
                    )
                except Exception:
                    pass
            return

        if not self.is_founder(user_id):
            if isinstance(message_or_callback, CallbackQuery):
                try:
                    await message_or_callback.answer("Доступ заборонено.", show_alert=True)
                except Exception:
                    pass
            else:
                try:
                    await message.answer("❌ Доступ заборонено.", parse_mode="html")
                except Exception:
                    pass
            return

        builder = InlineKeyboardBuilder()
        # ── 💳 Підписки та валюта ──
        builder.button(text="🎫 Видати підписку", callback_data="founder_give_subscription")
        builder.button(text="❌ Скасувати підписку", callback_data="founder_revoke_subscription")
        builder.button(text="💰 Видати монети", callback_data="founder_give_balance")
        builder.button(text="💸 Забрати монети", callback_data="founder_take_balance")
        _mar_cid = custom_emoji_id_for_symbol("🍋")
        if _mar_cid:
            builder.button(
                text="Видати лимони",
                callback_data="founder_give_marigolds",
                icon_custom_emoji_id=_mar_cid,
            )
        else:
            builder.button(text="🍋 Видати лимони", callback_data="founder_give_marigolds")
        builder.button(text="🔍 Перевірити підписку", callback_data="founder_check_subscription")
        # ── 👥 Користувачі та засновники ──
        builder.button(text="👑 Додати засновника", callback_data="founder_add_founder")
        builder.button(text="👤 Забрати засновника", callback_data="founder_revoke_founder")
        builder.button(text="🛟 Лінія підтримки", callback_data="founder_support_staff_menu")
        builder.button(text="🏆 Усі досягнення", callback_data="founder_grant_achievements")
        # ── 📊 Аналітика ──
        builder.button(text="📈 Статистика бота", callback_data="founder_bot_stats")
        builder.button(text="📊 Статистика підписок", callback_data="founder_stats")
        builder.button(text="👥 Список підписок", callback_data="founder_list_subscriptions")
        builder.button(text="💳 Платний VIP", callback_data="founder_vip_paid_list")
        builder.button(text="🏅 Топ гравців", callback_data="founder_top_players")
        builder.button(text="🏙 Топ груп", callback_data="founder_top_groups_week")
        # ── 🛡 Модерація · 🎟 Промо · 📂 Підтримка ──
        builder.button(text="🚫 Блок групи", callback_data="founder_block_group")
        builder.button(text="✅ Розблок групи", callback_data="founder_unblock_group")
        builder.button(text="📂 Тікети", callback_data="founder_tickets")
        builder.button(text="🎟 Промокоди", callback_data="founder_promocodes")
        builder.button(text="🎉 Сезонні івенти", callback_data="founder_seasonal_events")
        # Рядки: підписки/валюта (2+2+2), засновники (2+2+1), аналітика (2+2+2),
        # модерація/промо (2+2+1) — компактна сітка 2-в-ряд.
        builder.adjust(2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 1)

        text = (
            "👑 <b>Панель засновника</b>\n"
            "<i>Sicilian Mafia · керування ботом</i>\n\n"
            "💳 <b>Підписки та валюта</b>\n"
            "👥 <b>Користувачі й засновники</b>\n"
            "📊 <b>Аналітика</b>\n"
            "🛡 <b>Модерація · 🎟 промо · 📂 тікети</b>\n\n"
            "Оберіть дію 👇"
        )

        if isinstance(message_or_callback, CallbackQuery):
            await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
            await message_or_callback.answer()
        else:
            await message.answer(text, reply_markup=builder.as_markup(), parse_mode="html")

    async def show_support_only_menu(self, message_or_callback):
        """Меню для користувачів лише з роллю підтримки: тільки тікети."""
        if isinstance(message_or_callback, CallbackQuery):
            message = message_or_callback.message
        else:
            message = message_or_callback
        if not message or not message.chat or not _chat_is_private(message.chat):
            if isinstance(message_or_callback, CallbackQuery):
                try:
                    await message_or_callback.answer(
                        "Панель лише в ПП з ботом. Надішли /support_panel у особистих повідомленнях.",
                        show_alert=True,
                    )
                except Exception:
                    pass
            return
        builder = InlineKeyboardBuilder()
        builder.button(text="📂 Тікети", callback_data="founder_tickets")
        builder.adjust(1)
        text = (
            "🛟 <b>Панель підтримки</b>\n\n"
            "Тут доступні лише звернення користувачів (тікети).\n"
            "Натисни «Тікети», обери номер — і можна відповісти текстом у ПП.\n\n"
        )
        if isinstance(message_or_callback, CallbackQuery):
            await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
            await message_or_callback.answer()
        else:
            await message.answer(text, reply_markup=builder.as_markup(), parse_mode="html")
    
    def _register_handlers(self):
        """Register all callback handlers"""
        self.router_founder.callback_query.register(
            self.give_subscription_handler, F.data == "founder_give_subscription"
        )
        self.router_founder.callback_query.register(
            self.show_stats_handler, F.data == "founder_stats"
        )
        self.router_founder.callback_query.register(
            self.list_subscriptions_handler, F.data == "founder_list_subscriptions"
        )
        self.router_founder.callback_query.register(
            self.vip_paid_list_callback_handler, F.data == "founder_vip_paid_list"
        )
        self.router_founder.callback_query.register(
            self.check_subscription_handler, F.data == "founder_check_subscription"
        )
        self.router_founder.callback_query.register(
            self.revoke_subscription_handler, F.data == "founder_revoke_subscription"
        )
        self.router_founder.callback_query.register(
            self.add_founder_handler, F.data == "founder_add_founder"
        )
        self.router_founder.callback_query.register(
            self.revoke_founder_handler, F.data == "founder_revoke_founder"
        )
        # Один раз реєструємо обробники введення ID - тільки для того, хто натиснув (перевірка всередині фільтра)
        self.router_founder.message.register(
            self.add_founder_input_handler(),
            lambda msg: (
                _chat_is_private(msg.chat)
                and self.add_founder_waiting_user_id is not None
                and getattr(msg.from_user, "id", None) == self.add_founder_waiting_user_id
                and msg.text and msg.text.strip().isdigit()
                and not msg.text.startswith("/")
            )
        )
        self.router_founder.message.register(
            self.revoke_founder_input_handler(),
            lambda msg: (
                _chat_is_private(msg.chat)
                and self.add_founder_revoke_waiting_user_id is not None
                and getattr(msg.from_user, "id", None) == self.add_founder_revoke_waiting_user_id
                and msg.text and msg.text.strip().isdigit()
                and not msg.text.startswith("/")
            )
        )
        self.router_founder.message.register(
            self.support_staff_add_input_handler(),
            lambda msg: (
                _chat_is_private(msg.chat)
                and self.support_staff_add_waiting_user_id is not None
                and getattr(msg.from_user, "id", None) == self.support_staff_add_waiting_user_id
                and msg.text and msg.text.strip().isdigit()
                and not msg.text.startswith("/")
            ),
        )
        self.router_founder.message.register(
            self.support_staff_remove_input_handler(),
            lambda msg: (
                _chat_is_private(msg.chat)
                and self.support_staff_remove_waiting_user_id is not None
                and getattr(msg.from_user, "id", None) == self.support_staff_remove_waiting_user_id
                and msg.text and msg.text.strip().isdigit()
                and not msg.text.startswith("/")
            ),
        )
        # Синхронізація: тільки той, хто натиснув кнопку, вводить дані та отримує відповідь
        self.router_founder.message.register(
            self.user_id_input_handler(),
            lambda msg: (
                _chat_is_private(msg.chat)
                and self.waiting_subscription_user_id is not None
                and getattr(msg.from_user, "id", None) == self.waiting_subscription_user_id
                and self.is_inputting_user_id and msg.text and not msg.text.startswith("/")
            )
        )
        self.router_founder.message.register(
            self.check_subscription_input_handler(),
            lambda msg: (
                _chat_is_private(msg.chat)
                and self.waiting_check_subscription_user_id is not None
                and getattr(msg.from_user, "id", None) == self.waiting_check_subscription_user_id
                and msg.text and msg.text.strip().isdigit() and not msg.text.startswith("/")
            )
        )
        self.router_founder.message.register(
            self.revoke_subscription_input_handler(),
            lambda msg: (
                _chat_is_private(msg.chat)
                and self.waiting_revoke_subscription_user_id is not None
                and getattr(msg.from_user, "id", None) == self.waiting_revoke_subscription_user_id
                and msg.text and msg.text.strip().isdigit() and not msg.text.startswith("/")
            )
        )
        self.router_founder.message.register(
            self.balance_user_id_input_handler(),
            lambda msg: (
                _chat_is_private(msg.chat)
                and self.waiting_balance_user_id is not None
                and getattr(msg.from_user, "id", None) == self.waiting_balance_user_id
                and self.is_inputting_balance_user_id and msg.text and not msg.text.startswith("/")
            )
        )
        self.router_founder.message.register(
            self.balance_amount_input_handler(),
            lambda msg: (
                _chat_is_private(msg.chat)
                and self.waiting_balance_user_id is not None
                and getattr(msg.from_user, "id", None) == self.waiting_balance_user_id
                and self.is_inputting_balance_amount and msg.text and not msg.text.startswith("/")
            )
        )
        self.router_founder.message.register(
            self.block_group_id_input_handler(),
            lambda msg: (
                _chat_is_private(msg.chat)
                and self.waiting_block_group_user_id is not None
                and getattr(msg.from_user, "id", None) == self.waiting_block_group_user_id
                and self.is_inputting_block_group_id and msg.text and not msg.text.startswith("/")
            )
        )
        self.router_founder.message.register(
            self.unblock_group_id_input_handler(),
            lambda msg: (
                _chat_is_private(msg.chat)
                and self.waiting_unblock_group_user_id is not None
                and getattr(msg.from_user, "id", None) == self.waiting_unblock_group_user_id
                and self.is_inputting_unblock_group_id and msg.text and not msg.text.startswith("/")
            )
        )
        self.router_founder.callback_query.register(
            self.grant_achievements_info_handler, F.data == "founder_grant_achievements"
        )
        self.router_founder.callback_query.register(
            self.bot_stats_handler, F.data == "founder_bot_stats"
        )
        self.router_founder.callback_query.register(
            self.clicker_stats_handler, F.data == "founder_clicker_stats"
        )
        self.router_founder.callback_query.register(
            self.top_players_menu_handler, F.data == "founder_top_players"
        )
        self.router_founder.callback_query.register(
            self.top_groups_week_handler, F.data == "founder_top_groups_week"
        )
        self.router_founder.callback_query.register(
            self.top_players_balance_handler, F.data == "founder_top_balance"
        )
        self.router_founder.callback_query.register(
            self.top_players_gold_handler, F.data == "founder_top_gold"
        )
        self.router_founder.callback_query.register(
            self.top_players_marigolds_handler, F.data == "founder_top_marigolds"
        )
        self.router_founder.callback_query.register(
            self.give_balance_handler, F.data == "founder_give_balance"
        )
        self.router_founder.callback_query.register(
            self.take_balance_handler, F.data == "founder_take_balance"
        )
        self.router_founder.callback_query.register(
            self.give_marigolds_menu_handler, F.data == "founder_give_marigolds"
        )
        self.router_founder.callback_query.register(
            self.refresh_balance_handler, F.data == "founder_refresh_balance"
        )
        self.router_founder.callback_query.register(
            self.block_group_handler, F.data == "founder_block_group"
        )
        self.router_founder.callback_query.register(
            self.unblock_group_handler, F.data == "founder_unblock_group"
        )
        self.router_founder.callback_query.register(
            self.back_to_main_handler, F.data == "founder_back_main"
        )
        self.router_founder.callback_query.register(
            self.founder_support_staff_menu_handler, F.data == "founder_support_staff_menu"
        )
        self.router_founder.callback_query.register(
            self.founder_support_add_handler, F.data == "founder_support_add"
        )
        self.router_founder.callback_query.register(
            self.founder_support_remove_handler, F.data == "founder_support_remove"
        )
        self.router_founder.callback_query.register(
            self.seasonal_events_menu_handler, F.data == "founder_seasonal_events"
        )
        self.router_founder.callback_query.register(
            self.seasonal_event_enable_handler, F.data.startswith("founder_season_enable:")
        )
        self.router_founder.callback_query.register(
            self.seasonal_event_disable_handler, F.data == "founder_season_disable"
        )
        self.router_founder.callback_query.register(
            self.tickets_list_handler, F.data == "founder_tickets"
        )
        self.router_founder.callback_query.register(
            self.ticket_view_handler, F.data.startswith("founder_ticket_") & ~F.data.startswith("founder_ticket_close_")
        )
        self.router_founder.callback_query.register(
            self.ticket_close_handler, F.data.startswith("founder_ticket_close_")
        )
        self.router_founder.callback_query.register(
            self.promocodes_menu_handler, F.data == "founder_promocodes"
        )
        self.router_founder.callback_query.register(
            self.promo_create_start_handler, F.data == "founder_promo_create"
        )
        self.router_founder.callback_query.register(
            self.promo_list_handler, F.data == "founder_promo_list"
        )
        self.router_founder.callback_query.register(
            self.promo_toggle_active_handler, F.data.startswith("founder_promo_toggle_")
        )
        self.router_founder.callback_query.register(
            self.promo_delete_handler, F.data.startswith("founder_promo_del_")
        )
        self.router_founder.callback_query.register(
            self.edit_user_callback_handler, F.data.startswith("founder_edit_user:")
        )
        
        # Subscription type selection
        for item_id in ShopManager.SHOP_ITEMS.keys():
            self.router_founder.callback_query.register(
                self.subscription_type_selected(item_id),
                F.data == f"founder_sub_type_{item_id}"
            )
    
    async def give_subscription_handler(self, callback: CallbackQuery):
        """Handler for giving subscription"""
        self.waiting_subscription_user_id = None
        self.is_inputting_user_id = False
        builder = InlineKeyboardBuilder()

        # Show subscription options
        for item_id, item in ShopManager.SHOP_ITEMS.items():
            builder.button(text=f"{item.name} ({item.duration_days} днів)", 
                          callback_data=f"founder_sub_type_{item_id}")
        
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        builder.adjust(1)
        
        await callback.message.edit_text(
            "🎫 <b>Видати підписку</b> 🎫\n\n"
            ""
            "⬇️ <b>Оберіть тип підписки для видачі:</b> ⬇️\n\n"
            "💡 <i>Після вибору введи Telegram ID користувача.</i>",
            reply_markup=builder.as_markup(),
            parse_mode="html"
        )
        await callback.answer()
    
    def subscription_type_selected(self, item_id: str):
        """Handler when subscription type is selected"""
        async def handler(callback: CallbackQuery):
            item = ShopManager.get_item(item_id)
            if not item:
                await callback.answer("Помилка!", show_alert=True)
                return
            
            self.temp_subscription_type = item_id
            self.waiting_subscription_user_id = callback.from_user.id

            builder = InlineKeyboardBuilder()
            builder.button(text="⬅️ Назад", callback_data="founder_give_subscription")
            
            await callback.message.edit_text(
                f"🎫 <b>Видати підписку</b> 🎫\n\n"
                f"📦 <b>Обрано підписку:</b> {item.name}\n"
                f"⏱️ <b>Тривалість:</b> <code>{item.duration_days} днів</code>\n\n"
                f"⬇️ <b>Надішли ID:</b> ⬇️\n\n"
                f"💡 <i>Можна ввести:\n"
                f"• <b>ID групи</b> (від’ємне число, напр. -1001234567890) - підписку отримає власник групи\n"
                f"• <b>ID користувача</b> (додатнє число) - підписку отримає цей користувач</i>\n\n"
                f"💡 ID групи: <code>/id</code> в чаті групи. ID користувача: <code>@userinfobot</code> або <code>/id</code> в ПП.\n\n"
                f"⏳ <i>Очікую ID...</i>",
                reply_markup=builder.as_markup(),
                parse_mode="html"
            )
            
            self.is_inputting_user_id = True
        return handler

    def user_id_input_handler(self):
        """Handler for user ID input (тільки для того, хто обрав тип підписки - фільтр по waiting_subscription_user_id)."""
        async def handler(message: Message, bot: Bot):
            if not self.is_inputting_user_id:
                return
            try:
                raw_id = int(message.text.strip())
                user_id = raw_id
                display_label = ""
                
                # Якщо від'ємне число - це ID групи, шукаємо власника (creator_id) в admin_panel
                if raw_id < 0:
                    row = await _db_fetchone_async(
                        "SELECT creator_id FROM admin_panel WHERE group_id = %s LIMIT 1",
                        (raw_id,),
                    )
                    if not row:
                        await message.answer(
                            "❌ Групу з таким ID не знайдено в боті.\n\n"
                            "Додай групу через /construct_event або введи ID власника групи (додатнє число).",
                            parse_mode="html"
                        )
                        return
                    user_id = int(row[0])
                    display_label = f"Група: <code>{raw_id}</code> → власник (ID: {user_id})"
                else:
                    display_label = f"Користувач ID: {user_id}"
                
                self.temp_user_id = user_id
                
                # Verify user exists
                try:
                    user_info = await bot.get_chat(user_id)
                    user_name = user_info.first_name or "N/A"
                except Exception:
                    user_name = "N/A"
                
                item = ShopManager.get_item(self.temp_subscription_type)
                
                builder = InlineKeyboardBuilder()
                builder.button(text="✅ Підтвердити", callback_data="founder_confirm_give")
                builder.button(text="❌ Скасувати", callback_data="founder_back_main")
                builder.adjust(1)
                
                await message.answer(
                    f"🎫 <b>Підтвердження</b> 🎫\n\n"
                    f"{display_label}\n"
                    f"Користувач: <b>{user_name}</b> (ID: {user_id})\n"
                    f"Підписка: <b>{item.name}</b>\n"
                    f"Тривалість: <b>{item.duration_days} днів</b>\n\n"
                    f"Підтвердити видачу підписки?",
                    reply_markup=builder.as_markup(),
                    parse_mode="html"
                )

                self.is_inputting_user_id = False
                self.waiting_subscription_user_id = None

                self.router_founder.callback_query.register(
                    self.confirm_give_subscription_handler(),
                    F.data == "founder_confirm_give"
                )
                
            except ValueError:
                await message.answer("❌ Неправильний формат! Надішли тільки цифри (ID групи або ID користувача).")
        
        return handler
    
    def confirm_give_subscription_handler(self):
        """Handler for confirming subscription gift"""
        async def handler(callback: CallbackQuery):
            try:
                user_id = self.temp_user_id
                item = ShopManager.get_item(self.temp_subscription_type)
                
                if not user_id or not item:
                    await callback.answer("Помилка! Спробуй ще раз.", show_alert=True)
                    return
                
                # Activate subscription
                now = datetime.now()
                end_date = now + timedelta(days=item.duration_days) if item.duration_days > 0 else None

                # Log as admin gift (with special charge_id)
                charge_id = f"admin_gift_{callback.from_user.id}_{datetime.now().timestamp()}"

                def _grant_subscription():
                    try:
                        exists = _db_fetchone_sync("SELECT user_id FROM subscriptions WHERE user_id = %s", (user_id,))
                        if exists:
                            _db_execute_sync(
                                """
                                UPDATE subscriptions 
                                SET subscription_type = %s, subscription_start = %s, subscription_end = %s,
                                    is_active = TRUE, is_purchased = FALSE, updated_at = %s
                                WHERE user_id = %s
                                """,
                                (item.item_id, now, end_date, now, user_id),
                            )
                        else:
                            _db_execute_sync(
                                """
                                INSERT INTO subscriptions (user_id, subscription_type, subscription_start, subscription_end, is_active, is_purchased)
                                VALUES (%s, %s, %s, %s, TRUE, FALSE)
                                """,
                                (user_id, item.item_id, now, end_date),
                            )
                        _db_execute_sync(
                            """
                            INSERT INTO shop_purchases (user_id, item_name, item_type, amount_paid, currency, telegram_payment_charge_id)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (user_id, f"{item.name} (Адмін)", item.item_id, 0, "ADMIN", charge_id),
                        )
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise

                await run_db_call_async(_grant_subscription)
                if (item.item_id or "").startswith("vip"):
                    vip_mod.clear_vip_farewell_flag(user_id)
                
                # Reset temp data
                self.temp_user_id = None
                self.temp_subscription_type = None
                
                await callback.message.edit_text(
                    f"✅ <b>Підписка видана!</b> ✅\n\n"
                    f"Користувачу з ID <b>{user_id}</b> видано підписку:\n"
                    f"<b>{item.name}</b> ({item.duration_days} днів)",
                    parse_mode="html"
                )
                
                # Return to main menu after delay
                await asyncio.sleep(3)
                await self.show_main_menu(callback)
                
            except Exception as e:
                await callback.answer(f"❌ Помилка: {str(e)}", show_alert=True)
        
        return handler
    
    async def show_stats_handler(self, callback: CallbackQuery):
        """Show subscription statistics"""
        # Count active subscriptions
        active_row = await _db_fetchone_async("SELECT COUNT(*) FROM subscriptions WHERE is_active = TRUE")
        active_count = active_row[0] if active_row else 0
        
        # Count total users with subscriptions
        total_row = await _db_fetchone_async("SELECT COUNT(DISTINCT user_id) FROM subscriptions")
        total_users = total_row[0] if total_row else 0
        
        # Count by subscription type
        by_type = await _db_fetchall_async(
            """
            SELECT subscription_type, COUNT(*) 
            FROM subscriptions 
            WHERE is_active = TRUE 
            GROUP BY subscription_type
            """
        )
        
        stats_text = "📊 <b>Статистика підписок</b> 📊\n\n"
        stats_text += f"Активних підписок: <b>{active_count}</b>\n"
        stats_text += f"Усього користувачів з підписками: <b>{total_users}</b>\n\n"
        stats_text += "<b>За типами:</b>\n"
        
        for sub_type, count in by_type:
            item = ShopManager.get_item(sub_type)
            name = item.name if item else sub_type
            stats_text += f"• {name}: <b>{count}</b>\n"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        
        await callback.message.edit_text(stats_text, reply_markup=builder.as_markup(), parse_mode="html")
        await callback.answer()
    
    async def list_subscriptions_handler(self, callback: CallbackQuery):
        """List active subscriptions"""
        subscriptions = await _db_fetchall_async(
            """
            SELECT user_id, subscription_type, subscription_start, subscription_end
            FROM subscriptions
            WHERE is_active = TRUE
            ORDER BY subscription_end DESC
            LIMIT 50
            """
        )
        
        if not subscriptions:
            await callback.answer("Немає активних підписок!", show_alert=True)
            return
        
        text = "👥 <b>Активні підписки</b> 👥\n\n"
        for idx, (user_id, sub_type, start_date, end_date) in enumerate(subscriptions[:20], 1):
            item = ShopManager.get_item(sub_type)
            name = item.name if item else sub_type
            end_str = end_date.strftime("%d.%m.%Y") if end_date else "Без обмежень"
            text += f"{idx}. ID: {user_id} - {name}\n   До: {end_str}\n"
        
        if len(subscriptions) > 20:
            text += f"\n... та ще {len(subscriptions) - 20} підписок"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
        await callback.answer()
    
    async def check_subscription_handler(self, callback: CallbackQuery):
        """Check specific user's subscription. Тільки той, хто натиснув, вводить ID."""
        self.waiting_check_subscription_user_id = callback.from_user.id
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        await callback.message.edit_text(
            emoji_to_premium("🔍 <b>Перевірити підписку</b> 🔍\n\nНадішли Telegram ID користувача:"),
            reply_markup=builder.as_markup(),
            parse_mode="html"
        )
        await callback.answer()

    def check_subscription_input_handler(self):
        """Handler for subscription check input (тільки для того, хто натиснув)."""
        async def handler(message: Message):
            self.waiting_check_subscription_user_id = None
            try:
                user_id = int(message.text.strip())
                subscription = ShopManager.get_user_subscription(user_id)
                
                if subscription and ShopManager.is_subscription_active(user_id):
                    item = ShopManager.get_item(subscription["subscription_type"])
                    name = item.name if item else subscription["subscription_type"]
                    end_str = subscription["subscription_end"].strftime("%d.%m.%Y %H:%M") if subscription["subscription_end"] else "Без обмежень"
                    
                    text = (
                        f"✅ <b>Активна підписка</b> ✅\n\n"
                        f"Користувач ID: <b>{user_id}</b>\n"
                        f"Тип: <b>{name}</b>\n"
                        f"Діє до: {end_str}"
                    )
                else:
                    text = f"❌ У користувача з ID <b>{user_id}</b> немає активної підписки."
                
                builder = InlineKeyboardBuilder()
                builder.button(text="⬅️ Назад", callback_data="founder_back_main")
                
                await message.answer(text, reply_markup=builder.as_markup(), parse_mode="html")
            except ValueError:
                await message.answer("❌ Неправильний формат!")
        return handler
    
    async def revoke_subscription_handler(self, callback: CallbackQuery):
        """Revoke user's subscription. Тільки той, хто натиснув, вводить ID."""
        self.waiting_revoke_subscription_user_id = callback.from_user.id
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        await callback.message.edit_text(
            "❌ <b>Скасувати підписку</b> ❌\n\n"
            "Надішли Telegram ID користувача:",
            reply_markup=builder.as_markup(),
            parse_mode="html"
        )
        await callback.answer()

    def revoke_subscription_input_handler(self):
        """Handler for revoke subscription input (тільки для того, хто натиснув)."""
        async def handler(message: Message):
            self.waiting_revoke_subscription_user_id = None
            try:
                user_id = int(message.text.strip())
                
                # Deactivate subscription
                def _deactivate_subscription():
                    try:
                        affected_local = _db_execute_sync(
                            """
                            UPDATE subscriptions 
                            SET is_active = FALSE, updated_at = %s
                            WHERE user_id = %s
                            """,
                            (datetime.now(), user_id),
                        )
                        conn.commit()
                        return affected_local
                    except Exception:
                        conn.rollback()
                        raise

                affected = await run_db_call_async(_deactivate_subscription)
                
                if affected > 0:
                    text = f"✅ Підписку користувача <b>{user_id}</b> скасовано."
                else:
                    text = f"❌ У користувача з ID <b>{user_id}</b> немає активної підписки."
                
                builder = InlineKeyboardBuilder()
                builder.button(text="⬅️ Назад", callback_data="founder_back_main")
                
                await message.answer(text, reply_markup=builder.as_markup(), parse_mode="html")
            except ValueError:
                await message.answer("❌ Неправильний формат!")
        return handler
    
    async def add_founder_handler(self, callback: CallbackQuery):
        """Add another founder/admin. Тільки той, хто натиснув, може ввести ID і отримає відповідь."""
        self.add_founder_waiting_user_id = callback.from_user.id
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        await callback.message.edit_text(
            "👑 <b>Додати засновника</b> 👑\n\n"
            "Надішли Telegram ID нового засновника (тільки ти побачиш підтвердження):",
            reply_markup=builder.as_markup(),
            parse_mode="html"
        )
        await callback.answer()

    def add_founder_input_handler(self):
        """Обробник введення ID для додавання засновника (викликається тільки для того, хто натиснув «Додати засновника»)."""
        async def handler(message: Message):
            self.add_founder_waiting_user_id = None  # одразу скидаємо, щоб інші повідомлення не оброблялись
            try:
                founder_id = int(message.text.strip())
                added_by = message.from_user.id

                row = await _db_fetchone_async(
                    "SELECT founder_id FROM founders WHERE founder_id = %s AND is_active = TRUE",
                    (founder_id,),
                )
                if row:
                    await message.answer(f"❌ Користувач з ID <b>{founder_id}</b> вже є засновником.", parse_mode="html")
                    return

                await _db_execute_commit_async(
                    """
                    INSERT INTO founders (founder_id, added_by, is_active, notes)
                    VALUES (%s, %s, TRUE, 'Added by founder')
                    """,
                    (founder_id, added_by),
                )

                builder = InlineKeyboardBuilder()
                builder.button(text="⬅️ Назад", callback_data="founder_back_main")
                await message.answer(
                    f"✅ Користувач з ID <b>{founder_id}</b> доданий як засновник!",
                    reply_markup=builder.as_markup(),
                    parse_mode="html"
                )
            except ValueError:
                await message.answer("❌ Неправильний формат!")
        return handler

    async def revoke_founder_handler(self, callback: CallbackQuery):
        """Забрати статус засновника. Тільки той, хто натиснув, вводить ID і отримує відповідь."""
        self.add_founder_revoke_waiting_user_id = callback.from_user.id
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        await callback.message.edit_text(
            "👤 <b>Забрати засновника</b> 👤\n\n"
            "Надішли Telegram ID засновника, якому хочеш забрати статус (тільки ти побачиш підтвердження):",
            reply_markup=builder.as_markup(),
            parse_mode="html"
        )
        await callback.answer()

    def revoke_founder_input_handler(self):
        """Обробник введення ID для забрання засновника (тільки для того, хто натиснув кнопку)."""
        async def handler(message: Message):
            self.add_founder_revoke_waiting_user_id = None
            try:
                founder_id = int(message.text.strip())
                revoker_id = message.from_user.id

                if founder_id == revoker_id:
                    await message.answer("❌ Не можна забрати статус собі.", parse_mode="html")
                    return

                row = await _db_fetchone_async(
                    "SELECT founder_id FROM founders WHERE founder_id = %s AND is_active = TRUE",
                    (founder_id,),
                )
                if not row:
                    await message.answer(f"❌ Користувач з ID <b>{founder_id}</b> не є активним засновником.", parse_mode="html")
                    return

                count_row = await _db_fetchone_async("SELECT COUNT(*) FROM founders WHERE is_active = TRUE")
                count = count_row[0] if count_row else 0
                if count <= 1:
                    await message.answer("❌ Не можна забрати останнього засновника.", parse_mode="html")
                    return

                await _db_execute_commit_async(
                    "UPDATE founders SET is_active = FALSE, notes = COALESCE(notes, '') || ' [Revoked]' WHERE founder_id = %s",
                    (founder_id,),
                )

                builder = InlineKeyboardBuilder()
                builder.button(text="⬅️ Назад", callback_data="founder_back_main")
                await message.answer(
                    f"✅ У користувача з ID <b>{founder_id}</b> забрано статус засновника.",
                    reply_markup=builder.as_markup(),
                    parse_mode="html"
                )
            except ValueError:
                await message.answer("❌ Неправильний формат!")
        return handler
    
    async def clicker_stats_handler(self, callback: CallbackQuery):
        """Статистика адмін-клікера (день / тиждень)."""
        if not callback.from_user or not self.is_founder(callback.from_user.id):
            await callback.answer("Доступ заборонено.", show_alert=True)
            return
        try:
            from commands.admin_clicker import render_clicker_stats
            text = await render_clicker_stats()
        except Exception as e:
            text = f"🕹 <b>Клікер — статистика</b>\n\n⚠️ Помилка: {e}"
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Оновити", callback_data="founder_clicker_stats")
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        builder.adjust(2)
        try:
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
        except Exception:
            await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="html")
        await callback.answer()

    async def bot_stats_handler(self, callback: CallbackQuery):
        """Show bot statistics"""
        # Count total users
        total_users_row = await _db_fetchone_async("SELECT COUNT(*) FROM users")
        total_users = total_users_row[0] if total_users_row else 0
        
        # Count active subscriptions
        active_subs_row = await _db_fetchone_async("SELECT COUNT(*) FROM subscriptions WHERE is_active = TRUE")
        active_subs = active_subs_row[0] if active_subs_row else 0
        
        # Зареєстровані в конструкторі (admin_panel): один рядок на group_id з агрегованим блоком
        admin_rows = await _db_fetchall_async(
            """
            SELECT group_id, BOOL_OR(COALESCE(is_blocked, FALSE))
            FROM admin_panel
            GROUP BY group_id
            ORDER BY group_id
            """
        )
        admin_rows = admin_rows or []
        registered: dict[int, bool] = {int(r[0]): bool(r[1]) for r in admin_rows}
        total_registered = len(registered)

        # Усі групи, де бот бачив активність (повідомлення / callback / історія в БД)
        try:
            known_rows = await _db_fetchall_async("SELECT group_id FROM bot_known_groups ORDER BY group_id")
            known_ids = {int(r[0]) for r in (known_rows or [])}
        except Exception:
            known_ids = set()

        all_group_ids = sorted(set(registered.keys()) | known_ids)
        only_activity = [g for g in all_group_ids if g not in registered]
        total_seen = len(all_group_ids)

        blocked_groups = [(gid, True) for gid, bl in registered.items() if bl]
        active_registered = [(gid, False) for gid, bl in registered.items() if not bl]
        
        # Count founders
        founders_row = await _db_fetchone_async("SELECT COUNT(*) FROM founders WHERE is_active = TRUE")
        founders_count = founders_row[0] if founders_row else 0
        
        text = (
            "📈 <b>Статистика бота</b> 📈\n\n"
            f"Усього користувачів: <b>{total_users}</b>\n"
            f"Активних підписок: <b>{active_subs}</b>\n"
            f"Груп з активністю у бота: <b>{total_seen}</b>\n"
            f"   • У конструкторі (admin_panel): <b>{total_registered}</b>\n"
            f"   • Лише чат (ще без admin_panel): <b>{len(only_activity)}</b>\n"
            f"   • Активних (зареєстр.): <b>{len(active_registered)}</b>\n"
            f"   • Заблокованих (зареєстр.): <b>{len(blocked_groups)}</b>\n"
        )
        
        # Get group names and send links to owner in private
        links_message = None
        if total_seen > 0:
            text += "\n📁 <b>Групи:</b>\n"
            
            # Prepare links message for owner (only if owner is viewing)
            if callback.from_user.id == BOT_OWNER_ID:
                links_message = "🔗 <b>Посилання на групи (статистика бота):</b>\n\n"
            
            async def _append_group_line(group_id: int, *, blocked: bool, in_constructor: bool) -> None:
                nonlocal text, links_message
                tag = "🚫 " if blocked else ""
                suffix = ""
                if not in_constructor:
                    suffix = " <i>(лише активність у чаті)</i>"
                try:
                    chat = await callback.bot.get_chat(group_id)
                    group_name = chat.title or f"Група {group_id}"
                    group_link = await resolve_group_open_link(callback.bot, group_id, chat)
                    esc_name = html.escape(group_name)
                    esc_href = html.escape(group_link, quote=True)
                    line = (
                        f"• {tag}<a href=\"{esc_href}\">{esc_name}</a> "
                        f"(<code>{group_id}</code>){suffix}\n"
                    )
                    text += line
                    if links_message:
                        links_message += line
                except Exception:
                    line = f"• {tag}<code>{group_id}</code> (недоступно){suffix}\n"
                    text += line
                    if links_message:
                        links_message += line

            # Зареєстровані активні
            if active_registered:
                text += "\n✅ <b>Конструктор - активні:</b>\n"
                if links_message:
                    links_message += "✅ <b>Конструктор - активні:</b>\n"
                for group_id, _ in active_registered[:50]:
                    await _append_group_line(group_id, blocked=False, in_constructor=True)
                if len(active_registered) > 50:
                    text += f"\n... та ще <b>{len(active_registered) - 50}</b>\n"
            
            # Заблоковані
            if blocked_groups:
                text += "\n🚫 <b>Конструктор - заблоковані:</b>\n"
                if links_message:
                    links_message += "\n🚫 <b>Конструктор - заблоковані:</b>\n"
                for group_id, _ in blocked_groups[:50]:
                    await _append_group_line(group_id, blocked=True, in_constructor=True)
                if len(blocked_groups) > 50:
                    text += f"\n... та ще <b>{len(blocked_groups) - 50}</b>\n"

            # Тільки активність у бота, без рядка в admin_panel
            if only_activity:
                text += "\n📡 <b>Були повідомлення, ще без конструктора:</b>\n"
                if links_message:
                    links_message += "\n📡 <b>Були повідомлення, ще без конструктора:</b>\n"
                for group_id in only_activity[:50]:
                    await _append_group_line(group_id, blocked=False, in_constructor=False)
                if len(only_activity) > 50:
                    text += f"\n... та ще <b>{len(only_activity) - 50}</b>\n"
        else:
            text += "\n📁 <b>Групи:</b> поки немає записів (надішли повідомлення в групу після оновлення бота)"
        
        text += f"\n\n👑 Засновників: <b>{founders_count}</b>"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
        await callback.answer()
        
        # Send links to owner in private message
        if links_message and callback.from_user.id == BOT_OWNER_ID:
            try:
                await callback.bot.send_message(
                    chat_id=BOT_OWNER_ID,
                    text=links_message,
                    parse_mode="html",
                    disable_web_page_preview=True
                )
            except Exception as e:
                print(f"Error sending links to owner: {e}")

    async def top_players_menu_handler(self, callback: CallbackQuery):
        """Меню топів: по лір, золотих, лимонах."""
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        builder = InlineKeyboardBuilder()
        builder.button(text="💰 Топ по лір", callback_data="founder_top_balance")
        builder.button(text="🪙 Топ по золотих монетах", callback_data="founder_top_gold")
        _mar_cid_top = custom_emoji_id_for_symbol("🍋")
        if _mar_cid_top:
            builder.button(
                text="Топ по лимонах",
                callback_data="founder_top_marigolds",
                icon_custom_emoji_id=_mar_cid_top,
            )
        else:
            builder.button(text="🍋 Топ по лимонах", callback_data="founder_top_marigolds")
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        builder.adjust(1)
        await callback.message.edit_text(
            "🏅 <b>Топ гравців</b> 🏅\n\n"
            "Оберіть рейтинг за яким показувати топ:",
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        await callback.answer()

    async def top_groups_week_handler(self, callback: CallbackQuery):
        """Топ груп за кількістю зіграних ігор з понеділка поточного тижня."""
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        try:
            await _db_execute_commit_async(
                """
                CREATE TABLE IF NOT EXISTS mafia_game_results (
                    game_key TEXT PRIMARY KEY,
                    group_id BIGINT NOT NULL,
                    winner TEXT,
                    ended_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        except Exception:
            pass
        # Backfill старих ігор: переносимо історичні раунди казино в нову таблицю ігор мафії.
        # Використовуємо детермінований game_key, щоб імпорт був ідемпотентним.
        try:
            await _db_execute_commit_async(
                """
                INSERT INTO mafia_game_results (game_key, group_id, winner, ended_at)
                SELECT
                    ('legacy_round:' || r.id::text) AS game_key,
                    r.chat_id AS group_id,
                    CASE
                        WHEN r.mafia_wins IS TRUE THEN 'mafia'
                        WHEN r.mafia_wins IS FALSE THEN 'civilians'
                        ELSE ''
                    END AS winner,
                    COALESCE(r.resolved_at, r.created_at) AS ended_at
                FROM casino_rounds r
                WHERE COALESCE(r.resolved_at, r.created_at) IS NOT NULL
                ON CONFLICT (game_key) DO NOTHING
                """
            )
        except Exception:
            pass
        rows = await _db_fetchall_async(
            """
            SELECT
                k.group_id,
                COALESCE(g.games_count, 0)::BIGINT AS games_count
            FROM bot_known_groups k
            LEFT JOIN (
                SELECT group_id, COUNT(*)::BIGINT AS games_count
                FROM mafia_game_results
                WHERE ended_at >= date_trunc('week', CURRENT_TIMESTAMP)
                GROUP BY group_id
            ) g ON g.group_id = k.group_id
            ORDER BY COALESCE(g.games_count, 0) DESC, k.group_id ASC
            LIMIT 20
            """
        )
        rows = rows or []
        lines = ["🏙 <b>Топ груп з понеділка</b>\n"]
        if not rows:
            lines.append("Немає відомих груп у базі.")
        else:
            for i, (group_id, games_count) in enumerate(rows, 1):
                chat_title = f"ID {group_id}"
                try:
                    chat = await callback.bot.get_chat(int(group_id))
                    title = getattr(chat, "title", None)
                    if title:
                        chat_title = html.escape(str(title))
                except Exception:
                    pass
                lines.append(f"{i}. <b>{chat_title}</b> - 🎮 <b>{int(games_count or 0)}</b>")
            if all(int(gc or 0) == 0 for _, gc in rows):
                lines.append("\n<i>З понеділка ще не зафіксовано завершених ігор.</i>")
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=builder.as_markup(),
            parse_mode="html",
            disable_web_page_preview=True,
        )
        await callback.answer()

    def _format_top_list(self, rows: list, value_name: str, emoji: str, limit: int = 20) -> str:
        """Формує текст списку топу. rows: [(id, tg_name, value), ...]"""
        lines = []
        vip_count = 0
        for i, (uid, name, value) in enumerate(rows[:limit], 1):
            if vip_mod.active_vip_tier(int(uid)):
                vip_count += 1
            plain = str(name or " - ").strip() or " - "
            link = vip_mod.html_user_link(int(uid), plain)
            lines.append(f"{i}. {link} - {emoji} <b>{value}</b>")
        body = "\n".join(lines) if lines else "Немає даних."
        if vip_count >= 3:
            body += "\n\n⚒️ <i>У топі сьогодні багато тих, хто грає з VIP.</i>"
        return body

    async def top_players_balance_handler(self, callback: CallbackQuery):
        """Топ гравців за лірами (balance)."""
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        rows = await _db_fetchall_async(
            "SELECT id, COALESCE(tg_name, ' - '), COALESCE(balance, 0) FROM users ORDER BY COALESCE(balance, 0) DESC LIMIT 25"
        )
        rows = rows or []
        text = emoji_to_premium(
            "💰 <b>Топ гравців по лір</b> 💰\n\n" + self._format_top_list(rows, "лір", "💰", 20),
            skip_vip_badges=True,
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_top_players")
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
        await callback.answer()

    async def top_players_gold_handler(self, callback: CallbackQuery):
        """Топ гравців за золотими монетами (donate_coins)."""
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        rows = await _db_fetchall_async(
            "SELECT id, COALESCE(tg_name, ' - '), COALESCE(donate_coins, 0) FROM users ORDER BY COALESCE(donate_coins, 0) DESC LIMIT 25"
        )
        rows = rows or []
        text = emoji_to_premium(
            "🪙 <b>Топ гравців по золотих монетах</b> 🪙\n\n" + self._format_top_list(rows, "золотих", "🪙", 20),
            skip_vip_badges=True,
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_top_players")
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
        await callback.answer()

    async def top_players_marigolds_handler(self, callback: CallbackQuery):
        """Топ гравців за лимонами (marigolds)."""
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        rows = await _db_fetchall_async(
            "SELECT id, COALESCE(tg_name, ' - '), COALESCE(marigolds, 0) FROM users ORDER BY COALESCE(marigolds, 0) DESC LIMIT 25"
        )
        rows = rows or []
        text = "🍋 <b>Топ гравців по лимонах</b> 🍋\n\n" + self._format_top_list(rows, "лимонів", "🍋", 20)
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_top_players")
        await callback.message.edit_text(
            emoji_to_premium(text, skip_vip_badges=False),
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        await callback.answer()

    async def give_balance_handler(self, callback: CallbackQuery):
        """Handler for giving balance (coins). Тільки той, хто натиснув, вводить ID та суму."""
        self.balance_mode = "give"
        self.is_inputting_balance_amount = False
        self.temp_balance_user_id = None
        self.temp_balance_amount = None
        self.waiting_balance_user_id = callback.from_user.id
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        text = emoji_to_premium(
            "💰 <b>Видати монети</b> 💰\n\n"
            "⬇️ <b>Надішли Telegram ID користувача:</b> ⬇️\n\n"
            "💡 <i>Щоб дізнатися ID користувача:\n"
            "• Надішли йому <code>@userinfobot</code>\n"
            "• Або використай <code>/id</code> в приватному чаті</i>\n\n"
            "⏳ <i>Очікую ID користувача...</i>"
        )
        try:
            await callback.message.edit_text(
                text,
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
        except TelegramBadRequest:
            # Якщо редагування неможливе - просто надішлемо нове повідомлення
            if callback.message:
                await callback.message.answer(
                    text,
                    reply_markup=builder.as_markup(),
                    parse_mode="html",
                )
        self.is_inputting_balance_user_id = True
        await callback.answer()

    async def give_marigolds_menu_handler(self, callback: CallbackQuery):
        """Показати підказку для команди /give_marigolds."""
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        await callback.message.edit_text(
            emoji_to_premium(
                "🍋 <b>Видати лимони</b> 🍋\n\n"
                "Введіть у чат команду:\n"
                "<code>/give_marigolds &lt;user_id&gt; &lt;кількість&gt;</code>\n\n"
                "Приклад: <code>/give_marigolds 123456789 10</code>\n\n"
                "Користувачу з указаним ID буде нараховано вказану кількість лимонів.",
                skip_vip_badges=False,
            ),
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        await callback.answer()

    async def take_balance_handler(self, callback: CallbackQuery):
        """Handler for taking away balance (coins). Тільки той, хто натиснув, вводить ID та суму."""
        self.balance_mode = "take"
        self.is_inputting_balance_amount = False
        self.temp_balance_user_id = None
        self.temp_balance_amount = None
        self.waiting_balance_user_id = callback.from_user.id
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        text = (
            "💸 <b>Забрати монети</b> 💸\n\n"
            "⬇️ <b>Надішли Telegram ID користувача (у якого забирати монети):</b> ⬇️\n\n"
            "💡 <i>Щоб дізнатися ID користувача:\n"
            "• Надішли йому <code>@userinfobot</code>\n"
            "• Або використай <code>/id</code> в приватному чаті</i>\n\n"
            "⏳ <i>Очікую ID користувача...</i>"
        )
        try:
            await callback.message.edit_text(
                text,
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
        except TelegramBadRequest:
            if callback.message:
                await callback.message.answer(
                    text,
                    reply_markup=builder.as_markup(),
                    parse_mode="html",
                )
        self.is_inputting_balance_user_id = True
        await callback.answer()
    
    def balance_user_id_input_handler(self):
        """Handler for balance user ID input"""
        async def handler(message: Message, bot: Bot):
            if not self.is_inputting_balance_user_id:
                return
            
            try:
                raw = (message.text or "").strip()
                user_id = int(raw)
                self.temp_balance_user_id = user_id
                
                # Verify user exists
                try:
                    user_info = await bot.get_chat(user_id)
                    user_name = user_info.first_name or "N/A"
                except:
                    user_name = "N/A"
                
                # Get current balance
                result = await _db_fetchone_async("SELECT COALESCE(balance, 0) FROM users WHERE id = %s", (user_id,))
                current_balance = result[0] if result else 0
                
                is_take = getattr(self, "balance_mode", "give") == "take"
                title = "💸 Забрати монети" if is_take else "💰 Видати монети"
                prompt = "суму монет для списання" if is_take else "суму монет для видачі"
                
                builder = InlineKeyboardBuilder()
                builder.button(text="🔄 Оновити", callback_data="founder_refresh_balance")
                builder.button(text="⬅️ Назад", callback_data="founder_give_balance" if not is_take else "founder_take_balance")
                builder.adjust(1)
                
                await message.answer(
                    emoji_to_premium(
                        f"{title} 💰\n\n"
                        f"Користувач: <b>{user_name}</b> (ID: {user_id})\n"
                        f"Поточний баланс: <b>{current_balance} лір</b>\n\n"
                        f"⬇️ <b>Надішли {prompt}:</b> ⬇️\n\n"
                        f"💡 <i>Введи тільки число (наприклад: 100)</i>"
                    ),
                    reply_markup=builder.as_markup(),
                    parse_mode="html"
                )
                
                self.is_inputting_balance_user_id = False
                self.is_inputting_balance_amount = True
            except ValueError:
                await message.answer("❌ Неправильний формат! Надішли тільки цифри (Telegram ID)")
            except Exception as e:
                # Не мовчимо при будь-якій помилці (БД/Telegram API тощо)
                try:
                    await message.answer(f"❌ Помилка при обробці ID: {e}", parse_mode="html")
                except Exception:
                    pass
        return handler

    def balance_amount_input_handler(self):
        """Handler for balance amount input"""
        async def handler(message: Message, bot: Bot):
            if not self.is_inputting_balance_amount:
                return
            
            try:
                raw = (message.text or "").strip()
                amount = int(raw)
                
                if amount <= 0:
                    await message.answer("❌ Сума повинна бути більше 0!")
                    return
                
                self.temp_balance_amount = amount
                
                # Get user info
                try:
                    user_info = await bot.get_chat(self.temp_balance_user_id)
                    user_name = user_info.first_name or "N/A"
                except:
                    user_name = "N/A"
                
                # Get current balance
                result = await _db_fetchone_async(
                    "SELECT COALESCE(balance, 0) FROM users WHERE id = %s",
                    (self.temp_balance_user_id,),
                )
                current_balance = result[0] if result else 0
                is_take = getattr(self, "balance_mode", "give") == "take"
                
                if is_take:
                    if amount > current_balance:
                        await message.answer(
                            f"❌ Недостатньо монет! У користувача лише <b>{current_balance} лір</b>.",
                            parse_mode="html"
                        )
                        return
                    new_balance = current_balance - amount
                    builder = InlineKeyboardBuilder()
                    builder.button(text="✅ Підтвердити", callback_data="founder_confirm_take_balance")
                    builder.button(text="❌ Скасувати", callback_data="founder_back_main")
                    builder.adjust(1)
                    await message.answer(
                        f"💸 <b>Підтвердження списання</b> 💸\n\n"
                        f"Користувач: <b>{user_name}</b> (ID: {self.temp_balance_user_id})\n"
                        f"Поточний баланс: <b>{current_balance} лір</b>\n"
                        f"Сума до списання: <b>-{amount} лір</b>\n"
                        f"Новий баланс: <b>{new_balance} лір</b>\n\n"
                        f"Підтвердити списання монет?",
                        reply_markup=builder.as_markup(),
                        parse_mode="html"
                    )
                    self.router_founder.callback_query.register(
                        self.confirm_take_balance_handler(),
                        F.data == "founder_confirm_take_balance"
                    )
                else:
                    new_balance = current_balance + amount
                    builder = InlineKeyboardBuilder()
                    builder.button(text="✅ Підтвердити", callback_data="founder_confirm_give_balance")
                    builder.button(text="❌ Скасувати", callback_data="founder_back_main")
                    builder.adjust(1)
                    await message.answer(
                        emoji_to_premium(
                            f"💰 <b>Підтвердження</b> 💰\n\n"
                            f"Користувач: <b>{user_name}</b> (ID: {self.temp_balance_user_id})\n"
                            f"Поточний баланс: <b>{current_balance} лір</b>\n"
                            f"Сума до видачі: <b>+{amount} лір</b>\n"
                            f"Новий баланс: <b>{new_balance} лір</b>\n\n"
                            f"Підтвердити видачу монет?"
                        ),
                        reply_markup=builder.as_markup(),
                        parse_mode="html"
                    )
                    self.router_founder.callback_query.register(
                        self.confirm_give_balance_handler(),
                        F.data == "founder_confirm_give_balance"
                    )
                
                self.is_inputting_balance_amount = False
                
            except ValueError:
                await message.answer("❌ Неправильний формат! Надішли тільки число (наприклад: 100)")
            except Exception as e:
                # Не мовчимо, якщо щось пішло не так на етапі суми
                self.is_inputting_balance_amount = False
                try:
                    await message.answer(f"❌ Помилка при обробці суми: {e}", parse_mode="html")
                except Exception:
                    pass
        
        return handler
    
    def confirm_give_balance_handler(self):
        """Handler for confirming balance gift"""
        async def handler(callback: CallbackQuery):
            try:
                user_id = self.temp_balance_user_id
                amount = self.temp_balance_amount
                
                if not user_id or not amount:
                    await callback.answer("Помилка! Спробуй ще раз.", show_alert=True)
                    return
                
                # Ensure user exists in database
                def _give_balance():
                    try:
                        row = _db_fetchone_sync("SELECT id FROM users WHERE id = %s", (user_id,))
                        if not row:
                            _db_execute_sync(
                                """
                                INSERT INTO users (id, balance)
                                VALUES (%s, %s)
                                """,
                                (user_id, amount),
                            )
                        else:
                            _db_execute_sync(
                                """
                                UPDATE users 
                                SET balance = COALESCE(balance, 0) + %s 
                                WHERE id = %s
                                """,
                                (amount, user_id),
                            )
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise

                await run_db_call_async(_give_balance)
                
                # Get new balance
                result = await _db_fetchone_async("SELECT COALESCE(balance, 0) FROM users WHERE id = %s", (user_id,))
                new_balance = result[0] if result else amount
                
                # Reset temp data
                self.temp_balance_user_id = None
                self.temp_balance_amount = None
                self.waiting_balance_user_id = None

                await callback.message.edit_text(
                    f"✅ <b>Монети видано!</b> ✅\n\n"
                    f"Користувачу з ID <b>{user_id}</b> видано <b>{amount} лір</b>\n\n"
                    f"💵 Новий баланс: <b>{new_balance} лір</b>",
                    parse_mode="html"
                )

                # Try to notify user
                try:
                    await callback.bot.send_message(
                        chat_id=user_id,
                        text=emoji_to_premium(
                            f"💰 <b>Вам нараховано монети!</b> 💰\n\n"
                            f"💵 Ви отримали: <b>{amount} лір</b>\n\n"
                            f"💵 Ваш баланс: <b>{new_balance} лір</b>"
                        ),
                        parse_mode="html"
                    )
                except Exception as e:
                    print(f"Could not notify user {user_id}: {e}")
                
                # Return to main menu after delay
                await asyncio.sleep(3)
                await self.show_main_menu(callback)
                
            except Exception as e:
                await callback.answer(f"❌ Помилка: {str(e)}", show_alert=True)
        
        return handler
    
    def confirm_take_balance_handler(self):
        """Handler for confirming balance deduction (забрати монети) - тільки власник"""
        async def handler(callback: CallbackQuery):
            try:
                user_id = self.temp_balance_user_id
                amount = self.temp_balance_amount
                
                if not user_id or not amount:
                    await callback.answer("Помилка! Спробуй ще раз.", show_alert=True)
                    return
                
                row = await _db_fetchone_async("SELECT COALESCE(balance, 0) FROM users WHERE id = %s", (user_id,))
                current_balance = row[0] if row else 0
                new_balance = max(0, current_balance - amount)
                
                await _db_execute_commit_async(
                    """
                    UPDATE users 
                    SET balance = %s 
                    WHERE id = %s
                    """,
                    (new_balance, user_id),
                )
                
                self.temp_balance_user_id = None
                self.temp_balance_amount = None
                self.waiting_balance_user_id = None

                await callback.message.edit_text(
                    f"✅ <b>Монети списано!</b> ✅\n\n"
                    f"У користувача з ID <b>{user_id}</b> списано <b>{amount} лір</b>\n\n"
                    f"💵 Новий баланс: <b>{new_balance} лір</b>",
                    parse_mode="html"
                )

                try:
                    await callback.bot.send_message(
                        chat_id=user_id,
                        text=f"💸 <b>Списання монет</b> 💸\n\n"
                             f"У вас списано: <b>{amount} лір</b>\n\n"
                             f"💵 Ваш баланс: <b>{new_balance} лір</b>",
                        parse_mode="html"
                    )
                except Exception as e:
                    print(f"Could not notify user {user_id}: {e}")
                
                await asyncio.sleep(3)
                await self.show_main_menu(callback)
                
            except Exception as e:
                await callback.answer(f"❌ Помилка: {str(e)}", show_alert=True)
        
        return handler
    
    async def refresh_balance_handler(self, callback: CallbackQuery):
        """Оновити відображення балансу (перечитати з БД) - тільки власник"""
        if not self.temp_balance_user_id:
            await callback.answer("Спочатку оберіть користувача.", show_alert=True)
            return
        try:
            user_id = self.temp_balance_user_id
            result = await _db_fetchone_async("SELECT COALESCE(balance, 0) FROM users WHERE id = %s", (user_id,))
            current_balance = result[0] if result else 0
            try:
                user_info = await callback.bot.get_chat(user_id)
                user_name = user_info.first_name or "N/A"
            except Exception:
                user_name = "N/A"
            
            is_take = getattr(self, "balance_mode", "give") == "take"
            title = "💸 Забрати монети" if is_take else "💰 Видати монети"
            prompt = "суму монет для списання" if is_take else "суму монет для видачі"
            
            builder = InlineKeyboardBuilder()
            builder.button(text="🔄 Оновити", callback_data="founder_refresh_balance")
            builder.button(text="⬅️ Назад", callback_data="founder_give_balance" if not is_take else "founder_take_balance")
            builder.adjust(1)
            
            await callback.message.edit_text(
                f"{title} 💰\n\n"
                f"Користувач: <b>{user_name}</b> (ID: {user_id})\n"
                f"Поточний баланс: <b>{current_balance} лір</b>\n\n"
                f"⬇️ <b>Надішли {prompt}:</b> ⬇️\n\n"
                f"💡 <i>Введи тільки число (наприклад: 100)</i>\n\n"
                f"🔄 <i>Баланс оновлено</i>",
                reply_markup=builder.as_markup(),
                parse_mode="html"
            )
            await callback.answer("Баланс оновлено ✅")
        except Exception as e:
            await callback.answer(f"❌ Помилка: {str(e)}", show_alert=True)
    
    async def block_group_handler(self, callback: CallbackQuery):
        """Handler for blocking a group. Тільки той, хто натиснув, вводить ID."""
        self.waiting_block_group_user_id = callback.from_user.id
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        await callback.message.edit_text(
            "🚫 <b>Заблокувати групу</b> 🚫\n\n"
            "⬇️ <b>Надішли ID групи для блокування:</b> ⬇️\n\n"
            "💡 <i>Щоб дізнатися ID групи:\n"
            "• Використай команду <code>/id</code> в групі\n"
            "• Або скопіюй зі статистики бота</i>\n\n"
            "⏳ <i>Очікую ID групи...</i>",
            reply_markup=builder.as_markup(),
            parse_mode="html"
        )
        self.is_inputting_block_group_id = True
        await callback.answer()
    
    def block_group_id_input_handler(self):
        """Handler for block group ID input"""
        async def handler(message: Message, bot: Bot):
            if not self.is_inputting_block_group_id:
                return
            
            group_id = _parse_group_id(message.text or "")
            if group_id is None:
                await message.answer(
                    "❌ <b>Невірний формат ID</b> ❌\n\n"
                    "ID групи - число з мінусом (наприклад: <code>-1234567890</code>).\n\n"
                    "💡 Команда <code>/id</code> у групі покаже правильний ID.",
                    parse_mode="html"
                )
                return
            
            try:
                self.is_inputting_block_group_id = False
                self.waiting_block_group_user_id = None

                # Check if group exists in admin_panel
                result = await _db_fetchone_async(
                    "SELECT creator_id, is_blocked FROM admin_panel WHERE group_id = %s",
                    (group_id,),
                )
                
                if not result:
                    await message.answer(
                        f"❌ Група з ID <b>{group_id}</b> не знайдена в базі даних.\n\n"
                        f"💡 <i>Група повинна бути зареєстрована через <code>/construct_event</code> (налаштування ролей)</i>",
                        parse_mode="html"
                    )
                    return
                
                creator_id, current_blocked = result
                
                if current_blocked:
                    await message.answer(
                        f"⚠️ Група з ID <b>{group_id}</b> вже заблокована.",
                        parse_mode="html"
                    )
                    return
                
                # Block the group
                await _db_execute_commit_async(
                    """
                    UPDATE admin_panel 
                    SET is_blocked = TRUE 
                    WHERE group_id = %s
                    """,
                    (group_id,),
                )
                
                builder = InlineKeyboardBuilder()
                builder.button(text="⬅️ Назад до меню", callback_data="founder_back_main")
                
                await message.answer(
                    f"✅ <b>Група заблокована!</b> ✅\n\n"
                    f"🚫 Група з ID <b>{group_id}</b> тепер заблокована.\n\n"
                    f"💡 <i>Бот не буде працювати в цій групі до розблокування.</i>",
                    reply_markup=builder.as_markup(),
                    parse_mode="html"
                )
                
            except Exception:
                await message.answer(
                    "❌ <b>Невірний формат ID</b> ❌\n\n"
                    "ID групи - число з мінусом (наприклад: <code>-1234567890</code>).",
                    parse_mode="html"
                )
        
        return handler
    
    async def unblock_group_handler(self, callback: CallbackQuery):
        """Handler for unblocking a group. Тільки той, хто натиснув, вводить ID."""
        self.waiting_unblock_group_user_id = callback.from_user.id
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        await callback.message.edit_text(
            "✅ <b>Розблокувати групу</b> ✅\n\n"
            "⬇️ <b>Надішли ID групи для розблокування:</b> ⬇️\n\n"
            "💡 <i>Щоб дізнатися ID групи:\n"
            "• Використай команду <code>/id</code> в групі\n"
            "• Або скопіюй зі статистики бота</i>\n\n"
            "⏳ <i>Очікую ID групи...</i>",
            reply_markup=builder.as_markup(),
            parse_mode="html"
        )
        self.is_inputting_unblock_group_id = True
        await callback.answer()
    
    def unblock_group_id_input_handler(self):
        """Handler for unblock group ID input"""
        async def handler(message: Message, bot: Bot):
            if not self.is_inputting_unblock_group_id:
                return
            
            group_id = _parse_group_id(message.text or "")
            if group_id is None:
                await message.answer(
                    "❌ <b>Невірний формат ID</b> ❌\n\n"
                    "ID групи - число з мінусом (наприклад: <code>-1234567890</code>).\n\n"
                    "💡 Команда <code>/id</code> у групі покаже правильний ID.",
                    parse_mode="html"
                )
                return
            
            try:
                self.is_inputting_unblock_group_id = False
                self.waiting_unblock_group_user_id = None

                # Check if group exists in admin_panel
                result = await _db_fetchone_async(
                    "SELECT creator_id, is_blocked FROM admin_panel WHERE group_id = %s",
                    (group_id,),
                )

                if not result:
                    await message.answer(
                        f"❌ Група з ID <b>{group_id}</b> не знайдена в базі даних.\n\n"
                        f"💡 <i>Група повинна бути зареєстрована через <code>/construct_event</code> (налаштування ролей)</i>",
                        parse_mode="html"
                    )
                    return
                
                creator_id, current_blocked = result
                
                if not current_blocked:
                    await message.answer(
                        f"⚠️ Група з ID <b>{group_id}</b> не заблокована.",
                        parse_mode="html"
                    )
                    return
                
                # Unblock the group
                await _db_execute_commit_async(
                    """
                    UPDATE admin_panel 
                    SET is_blocked = FALSE 
                    WHERE group_id = %s
                    """,
                    (group_id,),
                )
                
                builder = InlineKeyboardBuilder()
                builder.button(text="⬅️ Назад до меню", callback_data="founder_back_main")
                
                await message.answer(
                    f"✅ <b>Група розблокована!</b> ✅\n\n"
                    f"✅ Група з ID <b>{group_id}</b> тепер розблокована.\n\n"
                    f"💡 <i>Бот знову працюватиме в цій групі.</i>",
                    reply_markup=builder.as_markup(),
                    parse_mode="html"
                )
                
            except Exception:
                await message.answer(
                    "❌ <b>Невірний формат ID</b> ❌\n\n"
                    "ID групи - число з мінусом (наприклад: <code>-1234567890</code>).",
                    parse_mode="html"
                )
        
        return handler

    async def founder_support_staff_menu_handler(self, callback: CallbackQuery):
        """Меню керування роллю підтримки (тільки засновники)."""
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        staff = get_support_staff_ids()
        lines = "\n".join(f"• <code>{sid}</code>" for sid in staff) if staff else "<i>поки нікого</i>"
        builder = InlineKeyboardBuilder()
        builder.button(text="➕ Дати роль за ID", callback_data="founder_support_add")
        builder.button(text="➖ Забрати роль за ID", callback_data="founder_support_remove")
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        builder.adjust(1)
        text = (
            "🛟 <b>Лінія підтримки</b>\n\n"
            "Ці користувачі отримують нові тікети в ПП і відкривають відповіді через "
            "<code>/support_panel</code> (лише «Тікети»).\n\n"
            f"<b>Поточний склад:</b>\n{lines}\n\n"
            "Натисни дію й надішли числовий Telegram ID."
        )
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
        await callback.answer()

    async def founder_support_add_handler(self, callback: CallbackQuery):
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        self.support_staff_add_waiting_user_id = callback.from_user.id
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_support_staff_menu")
        await callback.message.edit_text(
            "➕ <b>Дати роль підтримки</b>\n\n"
            "Надішли <b>Telegram ID</b> користувача (лише цифри).",
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        await callback.answer()

    async def founder_support_remove_handler(self, callback: CallbackQuery):
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        self.support_staff_remove_waiting_user_id = callback.from_user.id
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="founder_support_staff_menu")
        await callback.message.edit_text(
            "➖ <b>Забрати роль підтримки</b>\n\n"
            "Надішли <b>Telegram ID</b> користувача, якому забрати роль (лише цифри).",
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        await callback.answer()

    async def seasonal_events_menu_handler(self, callback: CallbackQuery):
        """Меню сезонних івентів: увімкнути/вимкнути (активним може бути лише один)."""
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        active_id = await seasonal_mod.get_active_event_id()
        events = seasonal_mod.list_events()

        builder = InlineKeyboardBuilder()
        if events:
            for ev in events:
                eid = ev.get("id")
                is_on = (eid == active_id)
                mark = "🟢" if is_on else "⚪️"
                emoji = ev.get("emoji", "")
                name = ev.get("name", eid)
                builder.button(
                    text=f"{mark} {emoji} {name}".strip(),
                    callback_data=f"founder_season_enable:{eid}",
                )
        if active_id:
            builder.button(text="🛑 Вимкнути активний івент", callback_data="founder_season_disable")
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        builder.adjust(1)

        if active_id:
            status = f"🟢 Активний: <b>{seasonal_mod.event_label(active_id)}</b>"
        else:
            status = "⚪️ Зараз жоден івент не активний."

        if events:
            hint = "Тисни на івент, щоб увімкнути його для всіх (одночасно — лише один)."
        else:
            hint = "Поки що немає доступних івентів. Вони з'являться тут після додавання."

        text = (
            "🎉 <b>Сезонні івенти</b> 🎉\n\n"
            f"{status}\n\n"
            f"{hint}"
        )
        try:
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
        except TelegramBadRequest:
            pass
        try:
            await callback.answer()
        except Exception:
            pass

    async def seasonal_event_enable_handler(self, callback: CallbackQuery):
        """Увімкнути конкретний івент (для всіх). Single-active."""
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        event_id = (callback.data or "").split(":", 1)[1] if ":" in (callback.data or "") else ""
        ev = seasonal_mod.get_event(event_id)
        if not ev:
            await callback.answer("Невідомий івент.", show_alert=True)
            return
        active_id = await seasonal_mod.get_active_event_id()
        if active_id == event_id:
            # Повторний тап по активному — вимикаємо (toggle).
            await seasonal_mod.disable_active_event()
            await callback.answer("Івент вимкнено.")
        else:
            ok = await seasonal_mod.set_active_event(event_id)
            if not ok:
                await callback.answer("Не вдалося увімкнути івент.", show_alert=True)
                return
            await callback.answer(f"Увімкнено: {ev.get('name', event_id)}")
        # Оновлюємо меню «/» у ПП (додаємо/прибираємо команди івенту, напр. /kupala).
        try:
            await bot_commands_mod.apply_private_commands(callback.bot)
        except Exception:
            pass
        await self.seasonal_events_menu_handler(callback)

    async def seasonal_event_disable_handler(self, callback: CallbackQuery):
        """Вимкнути будь-який активний івент (для всіх)."""
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        await seasonal_mod.disable_active_event()
        await callback.answer("Активний івент вимкнено.")
        try:
            await bot_commands_mod.apply_private_commands(callback.bot)
        except Exception:
            pass
        await self.seasonal_events_menu_handler(callback)

    def support_staff_add_input_handler(self):
        async def handler(message: Message):
            self.support_staff_add_waiting_user_id = None
            if not message.from_user or not self.is_founder(message.from_user.id):
                return
            try:
                new_id = int((message.text or "").strip())
            except ValueError:
                await message.answer("❌ Неправильний формат ID.")
                return
            if new_id <= 0:
                await message.answer("❌ Некоректний ID.")
                return
            if self.is_founder(new_id):
                await message.answer(
                    "ℹ️ Цей користувач уже <b>засновник</b> — тікети й так отримує.",
                    parse_mode="html",
                )
                return
            if is_support_staff_user(new_id):
                await message.answer(
                    f"ℹ️ У користувача <code>{new_id}</code> вже є роль підтримки.",
                    parse_mode="html",
                )
                return
            if add_support_staff_user(new_id, message.from_user.id):
                try:
                    await message.bot.send_message(
                        new_id,
                        "🛟 Вам надано роль <b>лінії підтримки</b>.\n\n"
                        "Нові тікети будуть приходити сюди. Відповідати: "
                        "<code>/support_panel</code> → «Тікети».",
                        parse_mode="html",
                    )
                except Exception:
                    pass
                builder = InlineKeyboardBuilder()
                builder.button(text="⬅️ До меню підтримки", callback_data="founder_support_staff_menu")
                await message.answer(
                    f"✅ Користувачу <code>{new_id}</code> надано роль підтримки.",
                    reply_markup=builder.as_markup(),
                    parse_mode="html",
                )
            else:
                await message.answer("❌ Не вдалося зберегти (перевір логи БД).")
        return handler

    def support_staff_remove_input_handler(self):
        async def handler(message: Message):
            self.support_staff_remove_waiting_user_id = None
            if not message.from_user or not self.is_founder(message.from_user.id):
                return
            try:
                rid = int((message.text or "").strip())
            except ValueError:
                await message.answer("❌ Неправильний формат ID.")
                return
            if not is_support_staff_user(rid):
                await message.answer(
                    f"❌ Користувач <code>{rid}</code> не в списку підтримки.",
                    parse_mode="html",
                )
                return
            if remove_support_staff_user(rid):
                self.admin_replying_ticket.pop(rid, None)
                builder = InlineKeyboardBuilder()
                builder.button(text="⬅️ До меню підтримки", callback_data="founder_support_staff_menu")
                await message.answer(
                    f"✅ У користувача <code>{rid}</code> забрано роль підтримки.",
                    reply_markup=builder.as_markup(),
                    parse_mode="html",
                )
            else:
                await message.answer("❌ Не вдалося видалити запис.")
        return handler

    async def tickets_list_handler(self, callback: CallbackQuery):
        """Список відкритих тікетів."""
        if not self.is_ticket_staff(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        if callback.from_user:
            self.admin_replying_ticket.pop(callback.from_user.id, None)
        tickets = get_open_support_tickets()
        builder = InlineKeyboardBuilder()
        if not tickets:
            await callback.message.edit_text(
                "📂 <b>Тікети</b> 📂\n\nНемає відкритих тікетів.",
                reply_markup=builder.button(text="⬅️ Назад", callback_data="founder_back_main").as_markup(),
                parse_mode="html",
            )
            await callback.answer()
            return
        for row in tickets:
            ticket_id, user_id, username, category, msg_text, created_at = row
            created_str = created_at.strftime("%d.%m %H:%M") if hasattr(created_at, "strftime") else str(created_at)
            builder.button(
                text=f"#{ticket_id} | {category[:20]} | {created_str}",
                callback_data=f"founder_ticket_{ticket_id}",
            )
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        builder.adjust(1)
        text = "📂 <b>Відкриті тікети</b> 📂\n\nОберіть тікет:"
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
        await callback.answer()

    async def ticket_view_handler(self, callback: CallbackQuery):
        """Відкрити тікет: показати деталі, увімкнути режим відповіді."""
        if not self.is_ticket_staff(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        data = callback.data or ""
        if not data.startswith("founder_ticket_"):
            await callback.answer()
            return
        try:
            ticket_id = int(data.replace("founder_ticket_", ""))
        except ValueError:
            await callback.answer()
            return
        row = get_support_ticket(ticket_id)
        if not row:
            await callback.answer("Тікет не знайдено або вже закрито.", show_alert=True)
            return
        tid, user_id, username, category, message_text, status, created_at = row
        if status != "open":
            await callback.answer("Тікет вже закрито.", show_alert=True)
            return
        created_str = created_at.strftime("%d.%m.%Y %H:%M") if hasattr(created_at, "strftime") else str(created_at)
        self.admin_replying_ticket[callback.from_user.id] = ticket_id
        user_row = await _db_fetchone_async(
            "SELECT COALESCE(NULLIF(TRIM(tg_name), ''), ''), COALESCE(NULLIF(TRIM(link), ''), '') FROM users WHERE id = %s",
            (user_id,),
        )
        in_bot_status = "🟢 Активний у боті" if user_row else "🔴 Не знайдено в БД"
        vip_tier = vip_mod.active_vip_tier(user_id)
        if vip_tier == "vip_plus":
            vip_status = "👑 VIP+"
        elif vip_tier == "vip":
            vip_status = "💎 VIP"
        else:
            vip_status = "❌ Неактивний"
        vip_until = ""
        try:
            test_until = vip_mod.get_game_vip_test_until(user_id)
            if test_until:
                vip_until = f" (тест до {test_until.strftime('%d.%m.%Y %H:%M')})"
            elif ShopManager.is_subscription_active(user_id):
                sub = ShopManager.get_user_subscription(user_id)
                end_val = sub.get("subscription_end") if sub else None
                if end_val:
                    vip_until = f" (до {end_val.strftime('%d.%m.%Y %H:%M')})"
        except Exception:
            vip_until = ""
        text = (
            f"📂 <b>Тікет №{tid}</b>\n\n"
            f"🆔 <b>ID тікета:</b> {tid}\n"
            f"👤 <b>Telegram ID:</b> <code>{user_id}</code>\n"
            f"📛 <b>Username:</b> @{username or ' - '}\n"
            f"🧍 <b>Статус людини:</b> {in_bot_status}\n"
            f"💠 <b>VIP статус:</b> {vip_status}{vip_until}\n"
            f"📁 <b>Категорія:</b> {category}\n"
            f"📅 <b>Створено:</b> {created_str}\n\n"
            f"💬 <b>Повідомлення користувача:</b>\n{message_text}\n\n"
            f"✏️ Напишіть <b>одне</b> повідомлення - воно буде надіслано користувачу як відповідь підтримки, після чого режим відповіді вимкнеться. Щоб відповісти ще раз - відкрийте тікет знову. Кнопка «Закрити» - закрити тікет."
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Закрити", callback_data=f"founder_ticket_close_{ticket_id}")
        builder.button(text="⬅️ До списку тікетів", callback_data="founder_tickets")
        builder.adjust(1)
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
        await callback.answer()

    async def ticket_close_handler(self, callback: CallbackQuery):
        """Закрити тікет та повідомити користувача."""
        if not self.is_ticket_staff(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        data = callback.data or ""
        if not data.startswith("founder_ticket_close_"):
            await callback.answer()
            return
        try:
            ticket_id = int(data.replace("founder_ticket_close_", ""))
        except ValueError:
            await callback.answer()
            return
        row = get_support_ticket(ticket_id)
        if not row:
            await callback.answer("Тікет не знайдено.", show_alert=True)
            return
        tid, user_id, username, category, message_text, status, created_at = row
        if status != "open":
            await callback.answer("Тікет вже закрито.", show_alert=True)
            return
        closed = close_support_ticket(ticket_id)
        if not closed:
            await callback.answer("Не вдалося закрити тікет.", show_alert=True)
            return
        for admin_id, t_id in list(self.admin_replying_ticket.items()):
            if t_id == ticket_id:
                del self.admin_replying_ticket[admin_id]
        try:
            await callback.bot.send_message(
                user_id,
                f"🔒 Тікет №{tid} закрито. Дякуємо за звернення! Якщо питання залишилось - створіть новий тікет через «Тех. Підтримка».",
                parse_mode="html",
            )
        except Exception:
            pass
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ До списку тікетів", callback_data="founder_tickets")
        await callback.message.edit_text(
            f"✅ Тікет №{tid} закрито. Користувачу надіслано повідомлення.",
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        await callback.answer()

    async def ticket_reply_message_handler(self, message: Message):
        """Якщо засновник або підтримка у режимі відповіді на тікет - надіслати текст користувачу."""
        if not message.from_user or not message.text:
            return
        if not self.is_ticket_staff(message.from_user.id):
            return
        ticket_id = self.admin_replying_ticket.get(message.from_user.id)
        if ticket_id is None:
            return
        row = get_support_ticket(ticket_id)
        if not row:
            self.admin_replying_ticket.pop(message.from_user.id, None)
            return
        tid, user_id, username, category, message_text, status, created_at = row
        if status != "open":
            self.admin_replying_ticket.pop(message.from_user.id, None)
            await message.answer("Цей тікет вже закрито.")
            return
        reply_text = (message.text or "").strip()
        if not reply_text:
            return
        try:
            await message.bot.send_message(
                user_id,
                f"💬 Відповідь підтримки по тікету №{tid}:\n\n{reply_text}",
                parse_mode="html",
            )
            # Одноразова відповідь: вимикаємо режим, щоб подальші повідомлення сапорта НЕ пересилались користувачу.
            self.admin_replying_ticket.pop(message.from_user.id, None)
            builder = InlineKeyboardBuilder()
            builder.button(text="✏️ Відповісти ще", callback_data=f"founder_ticket_{tid}")
            builder.button(text="✅ Закрити тікет", callback_data=f"founder_ticket_close_{tid}")
            builder.adjust(1)
            await message.answer(
                "✅ Відповідь надіслано користувачу.\n"
                "Режим відповіді вимкнено - наступні повідомлення НЕ підуть користувачу. "
                "Натисніть «Відповісти ще», щоб написати знову.",
                reply_markup=builder.as_markup(),
            )
        except Exception as e:
            await message.answer(f"❌ Не вдалося надіслати: {e}")

    # ---------- Промокоди ----------
    async def promocodes_menu_handler(self, callback: CallbackQuery):
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        self.waiting_promo_user_id = None
        builder = InlineKeyboardBuilder()
        builder.button(text="➕ Створити промокод", callback_data="founder_promo_create")
        builder.button(text="📋 Список промокодів", callback_data="founder_promo_list")
        builder.button(text="⬅️ Назад", callback_data="founder_back_main")
        builder.adjust(1)
        await callback.message.edit_text(
            "🎟 <b>Промокоди</b> 🎟\n\n"
            "Створюй промокоди - користувачі активують їх командою <code>/promocode слова коду</code>.\n\n"
            "⬇️ Оберіть дію:",
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        await callback.answer()

    async def promo_create_start_handler(self, callback: CallbackQuery):
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        self.waiting_promo_user_id = callback.from_user.id
        self.temp_promo_name = None
        self.temp_promo_code = None
        self.temp_promo_max = None
        self.temp_promo_rewards = None
        self.is_inputting_promo_name = True
        self.is_inputting_promo_code = False
        self.is_inputting_promo_max = False
        self.is_inputting_promo_rewards = False
        builder = InlineKeyboardBuilder()
        builder.button(text="❌ Скасувати", callback_data="founder_promocodes")
        await callback.message.edit_text(
            "➕ <b>Створити промокод</b>\n\n"
            "Крок 1/4: Введи <b>назву</b> промокоду (внутрішня назва, для себе).\n"
            "Наприклад: <i>Весняний бонус</i>",
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        self.temp_promo_bot_chat_id = callback.message.chat.id
        self.temp_promo_bot_message_id = callback.message.message_id
        await callback.answer()

    async def promo_list_handler(self, callback: CallbackQuery):
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        rows = await _db_fetchall_async(
            """
            SELECT id, code, name, max_activations, current_activations, is_active, created_at
            FROM promocodes
            ORDER BY created_at DESC
            LIMIT 30
            """
        )
        if not rows:
            builder = InlineKeyboardBuilder()
            builder.button(text="⬅️ Назад", callback_data="founder_promocodes")
            await callback.message.edit_text(
                "📋 <b>Список промокодів</b>\n\nПромокодів поки немає.",
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
            await callback.answer()
            return
        lines = ["📋 <b>Список промокодів</b>\n"]
        builder = InlineKeyboardBuilder()
        for pid, code, name, max_act, cur_act, is_active, created_at in rows:
            status = "✅" if is_active else "⏸"
            label = name or code
            created_str = created_at.strftime("%d.%m") if hasattr(created_at, "strftime") else str(created_at)
            lines.append(f"{status} <b>{label}</b>\n   Код: <code>{code}</code> | {cur_act}/{max_act} активацій | {created_str}")
            builder.button(text=f"{status} {label[:18]}", callback_data=f"founder_promo_toggle_{pid}")
            builder.button(text="🗑 Видалити", callback_data=f"founder_promo_del_{pid}")
        builder.button(text="⬅️ Назад", callback_data="founder_promocodes")
        builder.adjust(2)  # по 2 кнопки в ряд: [увімк/вимк] [видалити]
        await callback.message.edit_text(
            "\n".join(lines) + "\n\n<i>Кнопка з назвою - увімкнути/вимкнути. 🗑 - видалити промокод назавжди.</i>",
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        await callback.answer()

    async def promo_toggle_active_handler(self, callback: CallbackQuery):
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        data = callback.data or ""
        if not data.startswith("founder_promo_toggle_"):
            await callback.answer()
            return
        try:
            pid = int(data.replace("founder_promo_toggle_", ""))
        except ValueError:
            await callback.answer()
            return
        row = await _db_fetchone_async("SELECT is_active FROM promocodes WHERE id = %s", (pid,))
        if not row:
            await callback.answer("Промокод не знайдено.", show_alert=True)
            return
        new_active = not row[0]
        await _db_execute_commit_async(
            "UPDATE promocodes SET is_active = %s WHERE id = %s",
            (new_active, pid),
        )
        await callback.answer("Промокод увімкнено" if new_active else "Промокод вимкнено", show_alert=True)
        await self.promo_list_handler(callback)

    async def promo_delete_handler(self, callback: CallbackQuery):
        """Видалити промокод назавжди (і всі його активації)."""
        if not self.is_founder(callback.from_user.id):
            await callback.answer("❌ Доступ заборонено.", show_alert=True)
            return
        data = callback.data or ""
        if not data.startswith("founder_promo_del_"):
            await callback.answer()
            return
        try:
            pid = int(data.replace("founder_promo_del_", ""))
        except ValueError:
            await callback.answer()
            return
        row = await _db_fetchone_async("SELECT code, name FROM promocodes WHERE id = %s", (pid,))
        if not row:
            await callback.answer("Промокод не знайдено.", show_alert=True)
            return
        code, name = row
        try:
            def _delete_promo():
                try:
                    _db_execute_sync("DELETE FROM promocode_activations WHERE promocode_id = %s", (pid,))
                    _db_execute_sync("DELETE FROM promocodes WHERE id = %s", (pid,))
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

            await run_db_call_async(_delete_promo)
        except Exception as e:
            await callback.answer(f"❌ Помилка: {e}", show_alert=True)
            return
        label = name or code
        await callback.answer(f"Промокод «{label}» видалено.", show_alert=True)
        await self.promo_list_handler(callback)

    async def promo_input_message_handler(self, message: Message, bot: Bot):
        """Обробка введення даних при створенні промокоду (назва → код → макс активацій → нагороди)."""
        import re
        import json
        from commands.buff_shop import ITEMS
        from commands.buy import ShopManager

        text = (message.text or "").strip()
        if not text:
            return

        builder = InlineKeyboardBuilder()
        builder.button(text="❌ Скасувати", callback_data="founder_promocodes")

        async def _delete_user_message():
            try:
                await message.delete()
            except Exception:
                pass

        async def _delete_bot_previous_message():
            if getattr(self, "temp_promo_bot_chat_id", None) and getattr(self, "temp_promo_bot_message_id", None):
                try:
                    await bot.delete_message(chat_id=self.temp_promo_bot_chat_id, message_id=self.temp_promo_bot_message_id)
                except Exception:
                    pass
                self.temp_promo_bot_chat_id = None
                self.temp_promo_bot_message_id = None

        if self.is_inputting_promo_name:
            self.temp_promo_name = text[:255]
            self.is_inputting_promo_name = False
            self.is_inputting_promo_code = True
            await _delete_user_message()
            await _delete_bot_previous_message()
            sent = await message.answer(
                "➕ <b>Створити промокод</b>\n\n"
                "Крок 2/4: Введи <b>код для активації</b> - слова, які користувач вводитиме в <code>/promocode ...</code>.\n"
                "Наприклад: <i>весняний бонус</i> або <i>ALCAPONE2025</i>",
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
            self.temp_promo_bot_chat_id = message.chat.id
            self.temp_promo_bot_message_id = sent.message_id
            return

        if self.is_inputting_promo_code:
            code_normalized = re.sub(r"\s+", " ", text.strip())
            if not code_normalized:
                await message.answer("❌ Код не може бути порожнім. Введи слова для активації.")
                return
            self.temp_promo_code = code_normalized[:255]
            self.is_inputting_promo_code = False
            self.is_inputting_promo_max = True
            await _delete_user_message()
            await _delete_bot_previous_message()
            sent = await message.answer(
                "➕ <b>Створити промокод</b>\n\n"
                "Крок 3/4: Введи <b>максимальну кількість активацій</b> (число).\n"
                "Наприклад: <code>100</code> або <code>1</code> для одноразового.",
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
            self.temp_promo_bot_chat_id = message.chat.id
            self.temp_promo_bot_message_id = sent.message_id
            return

        if self.is_inputting_promo_max:
            try:
                max_act = int(text)
                if max_act < 1:
                    raise ValueError("Мін. 1")
            except ValueError:
                await message.answer("❌ Введи ціле число більше 0 (наприклад: 100).")
                return
            self.temp_promo_max = max_act
            self.is_inputting_promo_max = False
            self.is_inputting_promo_rewards = True
            buffs_preview = ", ".join(list(ITEMS.keys())[:8]) + "…" if ITEMS else "cap, mask, pager…"
            await _delete_user_message()
            await _delete_bot_previous_message()
            sent = await message.answer(
                "➕ <b>Створити промокод</b>\n\n"
                "Крок 4/4: Введи <b>нагороди</b> в один рядок через пробіл:\n"
                "<code>ліри золоті бафи підписка_ід дні</code>\n\n"
                "Приклад: <code>100 50 cap mask subscription_1month 30</code>\n"
                "• ліри, золоті - числа (0 якщо не потрібно)\n"
                f"• бафи - id через кому з каталогу: {buffs_preview}\n"
                "• підписка_ід: subscription_1month, subscription_3months тощо\n"
                "• дні - кількість днів підписки (0 якщо не потрібно)\n\n"
                "Мінімум одне поле: можна лише <code>200 0 0 0 0</code> (тільки ліри).",
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
            self.temp_promo_bot_chat_id = message.chat.id
            self.temp_promo_bot_message_id = sent.message_id
            return

        if self.is_inputting_promo_rewards:
            self.is_inputting_promo_rewards = False
            parts = text.split()
            reward_balance = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
            reward_gold = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            buffs_str = (parts[2] if len(parts) > 2 else "").strip().lower()
            sub_item = (parts[3] if len(parts) > 3 else "").strip() or None
            sub_days = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
            reward_buffs = []
            if buffs_str:
                for bid in buffs_str.replace(",", " ").split():
                    bid = bid.strip()
                    if bid and bid in ITEMS:
                        item = ITEMS[bid]
                        reward_buffs.append({"buff_id": item.item_id, "buff_name": item.name, "quantity": 1})
            if sub_item and not ShopManager.get_item(sub_item):
                sub_item = None
            if sub_days < 1:
                sub_days = None

            code_for_db = re.sub(r"\s+", " ", self.temp_promo_code.strip()).lower()
            if not code_for_db:
                await message.answer("❌ Код промокоду не може бути порожнім.", reply_markup=builder.as_markup(), parse_mode="html")
                self.is_inputting_promo_rewards = True
                return
            try:
                await _db_execute_commit_async(
                    """
                    INSERT INTO promocodes (
                        code, name, max_activations, reward_balance, reward_gold,
                        reward_buffs, reward_subscription_item_id, reward_subscription_days,
                        created_by, is_active
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, TRUE)
                    """,
                    (
                        code_for_db,
                        self.temp_promo_name or code_for_db,
                        self.temp_promo_max,
                        reward_balance,
                        reward_gold,
                        json.dumps(reward_buffs),
                        sub_item,
                        sub_days,
                        message.from_user.id,
                    ),
                )
            except Exception as e:
                await message.answer(f"❌ Помилка збереження: {e}", reply_markup=builder.as_markup(), parse_mode="html")
                self.temp_promo_name = None
                self.temp_promo_code = None
                self.temp_promo_max = None
                return

            display_name = self.temp_promo_name or code_for_db
            max_act = self.temp_promo_max
            self.temp_promo_name = None
            self.temp_promo_code = None
            self.temp_promo_max = None
            self.waiting_promo_user_id = None
            summary = []
            if reward_balance:
                summary.append(f"💰 {reward_balance} лір")
            if reward_gold:
                summary.append(f"🪙 {reward_gold} золотих")
            if reward_buffs:
                summary.append(f"📦 {len(reward_buffs)} бафів")
            if sub_item and sub_days:
                summary.append(f"🎫 {sub_days} дн. підписки")
            summary_str = ", ".join(summary) if summary else "без нагород"
            try:
                await message.delete()
            except Exception:
                pass
            await _delete_bot_previous_message()
            self.temp_promo_bot_chat_id = None
            self.temp_promo_bot_message_id = None
            await message.answer(
                emoji_to_premium(
                    f"✅ <b>Промокод створено!</b>\n\n"
                    f"Назва: <b>{display_name}</b>\n"
                    f"Код: <code>{code_for_db}</code>\n"
                    f"Активацій: {max_act}\n"
                    f"Нагороди: {summary_str}\n\n"
                    f"Користувачі активують: <code>/promocode {code_for_db}</code>"
                ),
                parse_mode="html",
            )
            return

    async def back_to_main_handler(self, callback: CallbackQuery):
        """Return to main menu - скидаємо всі прапорці очікування введення, щоб не просити ID/суму після Назад"""
        self.is_inputting_user_id = False
        self.is_inputting_subscription_type = False
        self.is_inputting_duration = False
        self.is_inputting_balance_user_id = False
        self.is_inputting_balance_amount = False
        self.is_inputting_block_group_id = False
        self.is_inputting_unblock_group_id = False
        self.is_inputting_promo_name = False
        self.is_inputting_promo_code = False
        self.is_inputting_promo_max = False
        self.is_inputting_promo_rewards = False
        self.temp_user_id = None
        self.temp_subscription_type = None
        self.temp_balance_user_id = None
        self.temp_balance_amount = None
        self.temp_promo_name = None
        self.temp_promo_code = None
        self.temp_promo_max = None
        self.temp_promo_rewards = None
        self.temp_promo_bot_chat_id = None
        self.temp_promo_bot_message_id = None
        self.is_inputting_send_to_message = False
        self.temp_send_to_target_id = None
        self.is_inputting_broadcast_message = False
        self.waiting_broadcast_user_id = None
        self.add_founder_waiting_user_id = None
        self.add_founder_revoke_waiting_user_id = None
        self.support_staff_add_waiting_user_id = None
        self.support_staff_remove_waiting_user_id = None
        self.waiting_subscription_user_id = None
        self.waiting_check_subscription_user_id = None
        self.waiting_revoke_subscription_user_id = None
        self.waiting_balance_user_id = None
        self.waiting_block_group_user_id = None
        self.waiting_unblock_group_user_id = None
        self.waiting_promo_user_id = None
        self.waiting_send_to_user_id = None
        if callback.from_user:
            self.admin_replying_ticket.pop(callback.from_user.id, None)
        uid = callback.from_user.id if callback.from_user else 0
        if self.is_founder(uid):
            await self.show_main_menu(callback)
        elif self.is_support_staff_uid(uid):
            await self.show_support_only_menu(callback)
        else:
            try:
                await callback.answer("Доступ заборонено.", show_alert=True)
            except Exception:
                pass
    
    async def update_roles_db_handler(self, message: Message):
        """Update default roles in database from code - only for founders"""
        if not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        
        await message.answer("⏳ Оновлюю ролі в базі даних з коду...")
        
        try:
            # Get all default roles from code
            default_roles = create_default_roles()
            
            # Get all chats that have default roles
            chats = _db_fetchall_sync(
                """
                SELECT DISTINCT creator_id, group_id 
                FROM custom_roles 
                WHERE is_default = TRUE
                """
            )
            
            updated_count = 0
            renamed_count = 0
            
            # Map old names to new names (for renaming)
            name_mapping = {
                "Бомж": "Волоцюга",
                "Любовниця": "Коханка",
                "Обманщик": "Брехун",
                "Оборотень": "Перевертень",
                "Телохранитель": "Тілоохоронець"
            }
            
            # For each chat, update default roles
            for creator_id, group_id in chats:
                # STEP 1: First, rename all old roles to avoid conflicts
                for old_name_key, new_name in name_mapping.items():
                    # Check if old role exists
                    old_role = _db_fetchone_sync(
                        """
                        SELECT role_id FROM custom_roles
                        WHERE creator_id = %s AND group_id = %s 
                        AND is_default = TRUE AND role_name = %s
                        """,
                        (creator_id, group_id, old_name_key),
                    )
                    
                    if old_role:
                        # Check if new name already exists
                        new_role_exists = _db_fetchone_sync(
                            """
                            SELECT role_id FROM custom_roles
                            WHERE creator_id = %s AND group_id = %s 
                            AND is_default = TRUE AND role_name = %s
                            """,
                            (creator_id, group_id, new_name),
                        )
                        
                        if new_role_exists:
                            # If new name already exists, delete old role (duplicate)
                            _db_execute_commit_sync(
                                """
                                DELETE FROM custom_roles
                                WHERE role_id = %s
                                """,
                                (old_role[0],),
                            )
                            renamed_count += 1
                        else:
                            # Rename role only if new name doesn't exist
                            try:
                                _db_execute_commit_sync(
                                    """
                                    UPDATE custom_roles
                                    SET role_name = %s
                                    WHERE role_id = %s
                                    """,
                                    (new_name, old_role[0]),
                                )
                                renamed_count += 1
                            except Exception as rename_error:
                                # If rename fails (e.g., constraint violation), delete old role
                                print(f"Warning: Could not rename {old_name_key} to {new_name}: {rename_error}")
                                _db_execute_commit_sync(
                                    """
                                    DELETE FROM custom_roles
                                    WHERE role_id = %s
                                    """,
                                    (old_role[0],),
                                )
                                renamed_count += 1
                
                # STEP 2: Now update/create roles with new names
                for role_key, role_template in default_roles.items():
                    # Check if role exists with current name
                    existing = _db_fetchone_sync(
                        """
                        SELECT role_id FROM custom_roles
                        WHERE creator_id = %s AND group_id = %s 
                        AND is_default = TRUE AND role_name = %s
                        """,
                        (creator_id, group_id, role_template.name),
                    )
                    
                    if existing:
                        # Update existing role
                        role_id = existing[0]
                        role_data = role_template.to_dict()
                        import json
                        role_json = json.dumps(role_data, ensure_ascii=False)
                        
                        # Update only role_description and role_data (enabled and min_players are in role_data JSON)
                        _db_execute_commit_sync(
                            """
                            UPDATE custom_roles
                            SET role_description = %s, role_data = %s
                            WHERE role_id = %s
                            """,
                            (role_template.description, role_json, role_id),
                        )
                        updated_count += 1
                    else:
                        # Create new role if it doesn't exist
                        # Double-check that role doesn't exist (might have been created in step 1)
                        check_again = _db_fetchone_sync(
                            """
                            SELECT role_id FROM custom_roles
                            WHERE creator_id = %s AND group_id = %s 
                            AND role_name = %s
                            """,
                            (creator_id, group_id, role_template.name),
                        )
                        
                        if check_again:
                            # Role exists, update it
                            role_id = check_again[0]
                            role_data = role_template.to_dict()
                            role_json = json.dumps(role_data, ensure_ascii=False)
                            _db_execute_commit_sync(
                                """
                                UPDATE custom_roles
                                SET role_description = %s, role_data = %s, is_default = %s
                                WHERE role_id = %s
                                """,
                                (role_template.description, role_json, True, role_id),
                            )
                            updated_count += 1
                        else:
                            # Role doesn't exist, create it
                            role_template.creator_id = creator_id
                            role_template.group_id = group_id
                            try:
                                RoleManager.save_role(role_template)
                                updated_count += 1
                            except Exception as save_error:
                                # If save fails (e.g., duplicate), try to update instead
                                print(f"Warning: Could not save role {role_template.name}, trying update: {save_error}")
                                # Try to find and update
                                found = _db_fetchone_sync(
                                    """
                                    SELECT role_id FROM custom_roles
                                    WHERE creator_id = %s AND group_id = %s 
                                    AND role_name = %s
                                    """,
                                    (creator_id, group_id, role_template.name),
                                )
                                if found:
                                    role_data = role_template.to_dict()
                                    role_json = json.dumps(role_data, ensure_ascii=False)
                                    _db_execute_commit_sync(
                                        """
                                        UPDATE custom_roles
                                        SET role_description = %s, role_data = %s, is_default = %s
                                        WHERE role_id = %s
                                        """,
                                        (role_template.description, role_json, True, found[0]),
                                    )
                                    updated_count += 1
            
            await message.answer(
                f"✅ <b>Оновлення завершено!</b> ✅\n\n"
                f"📊 Статистика:\n"
                f"• Оновлено ролей: <b>{updated_count}</b>\n"
                f"• Перейменовано ролей: <b>{renamed_count}</b>\n"
                f"• Оброблено чатів: <b>{len(chats)}</b>\n\n"
                f"💡 <i>Всі default ролі тепер синхронізовані з кодом.</i>",
                parse_mode="html"
            )
        except Exception as e:
            await message.answer(
                f"❌ <b>Помилка при оновленні!</b> ❌\n\n"
                f"<code>{str(e)}</code>",
                parse_mode="html"
            )
            print(f"Error updating roles DB: {e}")

    async def update_role_db_handler(self, message: Message):
        """Оновити тільки одну default-роль (по її назві/ключу з create_default_roles)."""
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return

        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(
                "🎨 <b>Оновити одну роль</b>\n\n"
                "Використання: <code>/update_role_db &lt;role_name&gt;</code>\n"
                "Приклад: <code>/update_role_db Щасливчик</code>",
                parse_mode="html",
            )
            return

        role_arg = parts[1].strip()
        if not role_arg:
            await message.answer("❌ Вкажи назву ролі. Наприклад: <code>/update_role_db Щасливчик</code>", parse_mode="html")
            return

        # Мапінг на старі назви (як у update_roles_db_handler)
        name_mapping = {
            "Бомж": "Волоцюга",
            "Любовниця": "Коханка",
            "Обманщик": "Брехун",
            "Оборотень": "Перевертень",
            "Телохранитель": "Тілоохоронець",
        }
        role_arg_mapped = name_mapping.get(role_arg, role_arg)

        try:
            default_roles = create_default_roles()

            template = None
            role_arg_cf = role_arg_mapped.casefold()
            for key, role_template in default_roles.items():
                # key інколи дорівнює role.name, але в будь-якому разі перевіряємо обидва
                if key.casefold() == role_arg_cf or role_template.name.casefold() == role_arg_cf:
                    template = role_template
                    break

            if not template:
                available = ", ".join(list(default_roles.keys())[:15]) + ("…" if len(default_roles) > 15 else "")
                await message.answer(
                    "❌ Роль не знайдено в create_default_roles.\n\n"
                    f"Твоя: <code>{role_arg}</code>\n"
                    f"Приклади: <code>{available}</code>",
                    parse_mode="html",
                )
                return

            await message.answer(f"⏳ Оновлюю роль <b>{template.name}</b> у default-записах...")

            import json

            # всі чати/групи де є default-роль з потрібною назвою
            chats = await _db_fetchall_async(
                """
                SELECT DISTINCT creator_id, group_id
                FROM custom_roles
                WHERE is_default = TRUE AND role_name = %s
                """,
                (template.name,),
            )
            chats = chats or []

            if not chats:
                await message.answer("ℹ️ Немає default-записів цієї ролі у БД.")
                return

            updated_groups = 0
            updated_rows = 0

            for creator_id, group_id in chats:
                # Забираємо існуючий role_data, щоб зберегти enabled/min_players/custom_data з /construct_event
                row = await _db_fetchone_async(
                    """
                    SELECT role_data
                    FROM custom_roles
                    WHERE creator_id = %s AND group_id = %s AND role_name = %s AND is_default = TRUE
                    """,
                    (creator_id, group_id, template.name),
                )
                if not row:
                    continue

                role_data_raw = row[0]
                if isinstance(role_data_raw, str):
                    role_data = json.loads(role_data_raw)
                elif isinstance(role_data_raw, dict):
                    role_data = role_data_raw
                else:
                    role_data = {}

                # створюємо новий шаблон і патчимо тільки "міняється в коді" (description/abilities)
                new_data = template.to_dict()
                new_data["description"] = template.description
                new_data["abilities"] = new_data.get("abilities", [])
                # зберігаємо налаштування конкретної групи
                if "enabled" in role_data:
                    new_data["enabled"] = role_data["enabled"]
                if "min_players" in role_data:
                    new_data["min_players"] = role_data["min_players"]
                if "custom_data" in role_data:
                    new_data["custom_data"] = role_data["custom_data"] or {}
                if "faction" in role_data:
                    new_data["faction"] = role_data["faction"]

                # прив'язуємо до chat scope (щоб Role.from_dict не перехапив wrong fields)
                new_data["creator_id"] = creator_id
                new_data["group_id"] = group_id
                new_data["is_default"] = True

                role_json = json.dumps(new_data, ensure_ascii=False)

                def _update_role_row():
                    try:
                        affected_local = _db_execute_sync(
                            """
                            UPDATE custom_roles
                            SET role_description = %s, role_data = %s
                            WHERE creator_id = %s AND group_id = %s AND role_name = %s AND is_default = TRUE
                            """,
                            (template.description, role_json, creator_id, group_id, template.name),
                        )
                        conn.commit()
                        return affected_local
                    except Exception:
                        conn.rollback()
                        raise

                affected = await run_db_call_async(_update_role_row)
                if affected > 0:
                    updated_groups += 1
                    updated_rows += affected

            await message.answer(
                "✅ <b>Оновлення завершено!</b>\n\n"
                f"📌 Роль: <b>{template.name}</b>\n"
                f"🗂️ Оновлено груп: <b>{updated_groups}</b>\n"
                f"🧾 Оновлено рядків: <b>{updated_rows}</b>",
                parse_mode="html",
            )

        except Exception as e:
            await message.answer(f"❌ Помилка: <code>{e}</code>", parse_mode="html")
            print(f"Error update_role_db_handler: {e}")

    async def verify_buffs_handler(self, message: Message):
        """Перевірка бафів: узгодженість каталогу з обробниками + smoke test ItemEffectProcessor. Тільки для засновника."""
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        await message.answer("⏳ Перевіряю бафи...")
        try:
            from game.buff_verification import run_full_verification
            chat_id = message.chat.id if message.chat else 0
            report = run_full_verification(chat_id=chat_id)
            await message.answer(report, parse_mode="html")
        except Exception as e:
            await message.answer(f"❌ Помилка: <code>{str(e)}</code>", parse_mode="html")

    async def edit_user_cmd_handler(self, message: Message):
        """/edit_user <user_id> - чернетка редагування профілю + підтвердження застосування."""
        if not message.from_user or not self.is_founder(message.from_user.id):
            await message.answer("❌ Доступ заборонено.")
            return
        if not _chat_is_private(message.chat):
            await message.answer("❌ Команда доступна тільки в ПП з ботом.")
            return
        parts = (message.text or "").strip().split()
        if len(parts) < 2:
            await message.answer(
                "Використання: <code>/edit_user &lt;user_id&gt;</code>\n"
                "Приклад: <code>/edit_user 123456789</code>",
                parse_mode="html",
            )
            return
        try:
            target_id = int(parts[1])
        except ValueError:
            await message.answer("❌ user_id має бути числом.")
            return
        await self._open_user_edit_menu(message, message.from_user.id, target_id)

    async def _load_user_edit_snapshot(self, target_id: int) -> Optional[Dict[str, Any]]:
        user_row = await _db_fetchone_async(
            """
            SELECT id, COALESCE(tg_name,''), COALESCE(link,''), COALESCE(balance,0), COALESCE(donate_coins,0), COALESCE(marigolds,0)
            FROM users WHERE id = %s
            """,
            (target_id,),
        )
        if not user_row:
            return None
        sub_row = await _db_fetchone_async(
            """
            SELECT subscription_type, subscription_end
            FROM subscriptions
            WHERE user_id = %s AND is_active = TRUE
            ORDER BY subscription_end DESC NULLS LAST
            LIMIT 1
            """,
            (target_id,),
        )
        blocked = await is_user_blocked_async(target_id)
        egg_row = await _db_fetchone_async(
            """
            SELECT COALESCE(progress, 0)
            FROM egg_event_state
            WHERE user_id = %s
            """,
            (target_id,),
        )
        egg_progress = int(egg_row[0] or 0) if egg_row else 0
        return {
            "user_id": int(user_row[0]),
            "tg_name": str(user_row[1] or ""),
            "link": str(user_row[2] or ""),
            "balance": int(user_row[3] or 0),
            "gold": int(user_row[4] or 0),
            "marigolds": int(user_row[5] or 0),
            "blocked": bool(blocked),
            "vip_type": (str(sub_row[0]) if sub_row and sub_row[0] else None),
            "vip_end": (sub_row[1] if sub_row else None),
            "egg_progress": egg_progress,
        }

    def _render_user_edit_text(self, session: Dict[str, Any]) -> str:
        o = session["original"]
        d = session["draft"]
        def _vip_label(raw: Optional[str]) -> str:
            if not raw:
                return "немає"
            r = str(raw).lower()
            if r in {"vip_plus", "vip_plus_30"}:
                return "vip_plus_30"
            if r in {"vip", "vip_30"}:
                return "vip_30"
            return str(raw)
        vip_orig = _vip_label(o["vip_type"])
        vip_new = _vip_label(d["vip_type"])
        vip_days = d.get("vip_days")
        vip_days_text = f", {vip_days} дн." if vip_days else ""
        return (
            "🛠 <b>Редагування профілю користувача</b>\n\n"
            f"👤 <b>ID:</b> <code>{o['user_id']}</code>\n"
            f"🙍 <b>Ім'я:</b> {html.escape(o['tg_name'] or '—')}\n"
            f"🔗 <b>Username:</b> @{html.escape(o['link']) if o['link'] else '—'}\n\n"
            "<b>Чернетка змін (ще не застосовано):</b>\n"
            f"💰 Баланс: <code>{o['balance']}</code> → <code>{d['balance']}</code>\n"
            f"🪙 Золото: <code>{o['gold']}</code> → <code>{d['gold']}</code>\n"
            f"🍋 Лимони: <code>{o['marigolds']}</code> → <code>{d['marigolds']}</code>\n"
            f"🚫 Блок: <code>{'YES' if o['blocked'] else 'NO'}</code> → <code>{'YES' if d['blocked'] else 'NO'}</code>\n"
            f"💎 VIP: <code>{vip_orig}</code> → <code>{vip_new}{vip_days_text}</code>\n"
            f"🥚 Прогрес яйця: <code>{o['egg_progress']}</code> → <code>{d['egg_progress']}</code>\n\n"
            "Натисни <b>Підтвердити</b>, щоб застосувати все одразу."
        )

    def _build_user_edit_kb(self, target_id: int) -> InlineKeyboardMarkup:
        b = InlineKeyboardBuilder()
        b.button(text="💰 Змінити баланс", callback_data=f"founder_edit_user:set_balance:{target_id}")
        b.button(text="🪙 Змінити золото", callback_data=f"founder_edit_user:set_gold:{target_id}")
        b.button(text="🍋 Змінити лимони", callback_data=f"founder_edit_user:set_egg:{target_id}")
        b.button(text="🚫 Перемкнути блок", callback_data=f"founder_edit_user:toggle_block:{target_id}")
        b.button(text="💎 Задати VIP", callback_data=f"founder_edit_user:set_vip:{target_id}")
        b.button(text="🥚 Змінити прогрес яйця", callback_data=f"founder_edit_user:set_egg_progress:{target_id}")
        b.button(text="♻️ Оновити з БД", callback_data=f"founder_edit_user:refresh:{target_id}")
        b.button(text="✅ Підтвердити", callback_data=f"founder_edit_user:apply:{target_id}")
        b.button(text="❌ Скасувати", callback_data=f"founder_edit_user:cancel:{target_id}")
        b.adjust(1)
        return b.as_markup()

    async def _open_user_edit_menu(self, message_or_callback, admin_id: int, target_id: int, note: str = ""):
        snap = await self._load_user_edit_snapshot(target_id)
        if not snap:
            txt = "❌ Користувача не знайдено."
            if isinstance(message_or_callback, CallbackQuery):
                await message_or_callback.answer(txt, show_alert=True)
            else:
                await message_or_callback.answer(txt)
            return
        self.user_edit_sessions[admin_id] = {
            "target_id": target_id,
            "original": dict(snap),
            "draft": {
                "balance": int(snap["balance"]),
                "gold": int(snap["gold"]),
                "marigolds": int(snap["marigolds"]),
                "blocked": bool(snap["blocked"]),
                "vip_type": snap["vip_type"],
                "vip_days": None,
                "egg_progress": int(snap["egg_progress"]),
            },
        }
        text = self._render_user_edit_text(self.user_edit_sessions[admin_id])
        if note:
            text = f"{note}\n\n{text}"
        kb = self._build_user_edit_kb(target_id)
        if isinstance(message_or_callback, CallbackQuery):
            try:
                await message_or_callback.message.edit_text(text, reply_markup=kb, parse_mode="html")
            except Exception:
                await message_or_callback.message.answer(text, reply_markup=kb, parse_mode="html")
            await message_or_callback.answer()
        else:
            await message_or_callback.answer(text, reply_markup=kb, parse_mode="html")

    async def edit_user_callback_handler(self, callback: CallbackQuery):
        if not callback.from_user:
            await callback.answer()
            return
        admin_id = callback.from_user.id
        if not self.is_founder(admin_id):
            await callback.answer("Доступ заборонено.", show_alert=True)
            return
        parts = (callback.data or "").split(":")
        if len(parts) < 3:
            await callback.answer()
            return
        action = parts[1]
        try:
            target_id = int(parts[2])
        except ValueError:
            await callback.answer("Некоректний user_id.", show_alert=True)
            return
        sess = self.user_edit_sessions.get(admin_id)
        if not sess or int(sess.get("target_id", 0)) != target_id:
            await self._open_user_edit_menu(callback, admin_id, target_id)
            return

        if action == "set_balance":
            self.user_edit_waiting_input[admin_id] = "balance"
            await callback.answer("Введи новий баланс одним числом у наступному повідомленні.")
            return
        if action == "set_gold":
            self.user_edit_waiting_input[admin_id] = "gold"
            await callback.answer("Введи нову кількість золота одним числом.")
            return
        if action == "set_egg":
            self.user_edit_waiting_input[admin_id] = "marigolds"
            await callback.answer("Введи нову кількість лимонів одним числом.")
            return
        if action == "set_vip":
            self.user_edit_waiting_input[admin_id] = "vip"
            try:
                await callback.message.answer(
                    "💎 Введи VIP у повідомленні:\n"
                    "• <code>vip 30</code>\n"
                    "• <code>vip_plus 30</code>\n"
                    "• <code>vip_plus_30</code>\n"
                    "• <code>none</code>",
                    parse_mode="html",
                )
            except Exception:
                pass
            await callback.answer("Очікую значення VIP…")
            return
        if action == "set_egg_progress":
            self.user_edit_waiting_input[admin_id] = "egg_progress"
            await callback.answer("Введи progress: 0..100")
            return
        if action == "toggle_block":
            sess["draft"]["blocked"] = not bool(sess["draft"]["blocked"])
            await self._open_user_edit_menu(callback, admin_id, target_id, "✅ Чернетку оновлено")
            return
        if action == "refresh":
            await self._open_user_edit_menu(callback, admin_id, target_id, "♻️ Перезавантажено з БД")
            return
        if action == "cancel":
            self.user_edit_waiting_input.pop(admin_id, None)
            self.user_edit_sessions.pop(admin_id, None)
            await callback.message.edit_text("❌ Редагування скасовано.")
            await callback.answer()
            return
        if action == "apply":
            d = sess["draft"]
            await _db_execute_commit_async(
                """
                UPDATE users
                SET balance = %s, donate_coins = %s, marigolds = %s
                WHERE id = %s
                """,
                (int(d["balance"]), int(d["gold"]), int(d["marigolds"]), target_id),
            )
            if bool(d["blocked"]):
                await block_user_async(target_id)
            else:
                await unblock_user_async(target_id)
            egg_progress = int(d["egg_progress"])
            egg_stage = 1
            if egg_progress >= 85:
                egg_stage = 5
            elif egg_progress >= 60:
                egg_stage = 4
            elif egg_progress >= 40:
                egg_stage = 3
            elif egg_progress >= 20:
                egg_stage = 2
            await _db_execute_commit_async(
                """
                INSERT INTO egg_event_state (
                    user_id, has_egg, stage, progress, growth, stability, quality, risk, overcare_percent, opened, result_type, last_action_at
                )
                VALUES (%s, FALSE, %s, %s, 0, 0, 0, 0, 0, FALSE, NULL, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET
                    stage = EXCLUDED.stage,
                    progress = EXCLUDED.progress,
                    last_action_at = CURRENT_TIMESTAMP
                """,
                (
                    target_id,
                    egg_stage,
                    egg_progress,
                ),
            )
            vip_type = d.get("vip_type")
            if not vip_type:
                await _db_execute_commit_async(
                    "UPDATE subscriptions SET is_active = FALSE WHERE user_id = %s",
                    (target_id,),
                )
            else:
                days = int(d.get("vip_days") or 30)
                await _db_execute_commit_async(
                    """
                    INSERT INTO subscriptions (user_id, subscription_type, subscription_start, subscription_end, is_active, auto_renew, updated_at)
                    VALUES (%s, %s, NOW(), NOW() + (%s || ' days')::interval, TRUE, FALSE, NOW())
                    ON CONFLICT (user_id) DO UPDATE SET
                      subscription_type = EXCLUDED.subscription_type,
                      subscription_start = EXCLUDED.subscription_start,
                      subscription_end = EXCLUDED.subscription_end,
                      is_active = TRUE,
                      auto_renew = FALSE,
                      updated_at = NOW()
                    """,
                    (target_id, vip_type, days),
                )
            self.user_edit_waiting_input.pop(admin_id, None)
            await self._open_user_edit_menu(callback, admin_id, target_id, "✅ Зміни застосовано")
            return
        await callback.answer()

    async def edit_user_input_handler(self, message: Message):
        if not message.from_user:
            return
        admin_id = message.from_user.id
        field = self.user_edit_waiting_input.get(admin_id)
        sess = self.user_edit_sessions.get(admin_id)
        if not field or not sess:
            return
        txt = (message.text or "").strip()
        try:
            if field == "balance":
                sess["draft"]["balance"] = int(txt)
            elif field == "gold":
                sess["draft"]["gold"] = int(txt)
            elif field == "marigolds":
                sess["draft"]["marigolds"] = int(txt)
            elif field == "vip":
                norm = txt.strip().lower()
                if norm in {"none", "off", "0"}:
                    sess["draft"]["vip_type"] = None
                    sess["draft"]["vip_days"] = None
                else:
                    norm = norm.replace("-", "_")
                    if "_" in norm and " " not in norm:
                        # Підтримка формату vip_plus_30 / vip_30
                        last_us = norm.rfind("_")
                        if last_us > 0 and last_us < len(norm) - 1:
                            norm = f"{norm[:last_us]} {norm[last_us+1:]}"
                    parts = norm.split()
                    if len(parts) != 2:
                        raise ValueError("VIP format")
                    tier = parts[0].strip().lower()
                    days = int(parts[1])
                    if tier not in {"vip", "vip_plus", "vip_30", "vip_plus_30"}:
                        raise ValueError("VIP tier")
                    if days <= 0:
                        raise ValueError("VIP days")
                    # В БД і логіці бота типи зберігаються як vip_30 / vip_plus_30
                    if tier in {"vip_plus", "vip_plus_30"}:
                        sess["draft"]["vip_type"] = "vip_plus_30"
                    else:
                        sess["draft"]["vip_type"] = "vip_30"
                    sess["draft"]["vip_days"] = days
            elif field == "egg_progress":
                val = int(txt)
                if val < 0 or val > 100:
                    raise ValueError("egg progress")
                sess["draft"]["egg_progress"] = val
            else:
                return
        except Exception:
            await message.answer("❌ Некоректне значення. Спробуй ще раз.")
            return
        self.user_edit_waiting_input.pop(admin_id, None)
        target_id = int(sess["target_id"])
        await message.answer(
            self._render_user_edit_text(sess),
            reply_markup=self._build_user_edit_kb(target_id),
            parse_mode="html",
        )


# Initialize founder panel
founder_panel = FounderPanel()
router_founder = founder_panel.router_founder
