import asyncio
import json
import os
from datetime import datetime
from aiogram import Bot, Router, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.enums import ChatMemberStatus
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from database.database import (
    cursor, conn, get_group_ids_where_user_has_construct_rights,
    get_group_buff_settings, set_group_buffs_enabled, set_group_unique_buffs_only, toggle_group_buff_disabled,
    get_role_backups, get_role_backup_snapshot, create_role_backup, delete_role_backup,
    update_role_backup_name, MAX_ROLE_BACKUPS_PER_GROUP,
    run_db_call_async,
)
from commands.buy import ShopManager
from commands.buff_shop import ITEMS
from game.role_system import Role, Ability, AbilityType, AbilityPhase, TargetType, UsageLimit, RoleAlignment, create_default_roles
from game.role_manager import RoleManager
from game.chat_role_registry import ChatRoleRegistry
from game.ability_resolver import validate_ability_configuration
from premium_emoji import emoji_to_premium, custom_emoji_id_for_symbol
from typing import Optional, List, Dict, Any, Callable, Awaitable
import html

# Активний інстанс конструктора (використовується командою /settings для прямого відкриття).
ACTIVE_CONSTRUCT_EVENT = None


def get_active_construct_event():
    return ACTIVE_CONSTRUCT_EVENT


def user_awaits_construct_private_text_input(user_id: int) -> bool:
    """
    True, якщо користувач зараз вводить текст у /construct_event (ЛС).
    Потрібно, щоб router_last_word (play) не перехоплював ці повідомлення.
    """
    ce = get_active_construct_event()
    if ce is None:
        return False
    uid = int(user_id)
    try:
        if getattr(ce, "is_input_chat_id", False) and getattr(ce, "awaiting_chat_id_user_id", None) == uid:
            return True
        if getattr(ce, "is_input_add_chat_id", False) and getattr(ce, "awaiting_add_chat_id_user_id", None) == uid:
            return True
        if getattr(ce, "is_input_new_role_description", False) and getattr(ce, "awaiting_role_description_user_id", None) == uid:
            return True
        if getattr(ce, "is_input_min_players", False) and getattr(ce, "awaiting_min_players_user_id", None) == uid:
            return True
        if getattr(ce, "awaiting_night_message_user_id", None) == uid:
            return True
        if getattr(ce, "awaiting_role_card_user_id", None) == uid:
            return True
        if uid in getattr(ce, "_mafia_scale_pending", {}):
            return True
        if uid in getattr(ce, "_backup_rename_pending", {}):
            return True
        if uid in getattr(ce, "_role_name_pending", {}):
            return True
        if uid in getattr(ce, "_role_description_pending", {}):
            return True
        if getattr(ce, "is_input_new_role_description", False):
            return False
        if (getattr(ce, "is_input_new_role_name", False) or getattr(ce, "is_creating_new_role", False)) and (
            getattr(ce, "awaiting_role_name_user_id", None) is None
            or getattr(ce, "awaiting_role_name_user_id", None) == uid
        ):
            return True
    except Exception:
        return False
    return False


# #region agent log
_log_path = r"c:\Users\flime\OneDrive\Desktop\MafiaAllCaponeBot\.cursor\debug.log"
def _log_debug(session_id, run_id, hypothesis_id, location, message, data):
    try:
        os.makedirs(os.path.dirname(_log_path), exist_ok=True)
        with open(_log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                "sessionId": session_id,
                "runId": run_id,
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(datetime.now().timestamp() * 1000)
            }) + "\n")
            f.flush()
    except:
        pass
# #endregion


# ID головного власника бота (завжди має права власника)
BOT_OWNER_ID = 1859870653


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


def _icon_button(text: str, callback_data: str, symbol: str) -> InlineKeyboardButton:
    """Кнопка з premium-іконкою (якщо є custom_emoji_id), інакше звичайний емодзі в тексті."""
    cid = custom_emoji_id_for_symbol(symbol)
    if cid:
        return InlineKeyboardButton(text=text, callback_data=callback_data, icon_custom_emoji_id=cid)
    return InlineKeyboardButton(text=f"{symbol} {text}", callback_data=callback_data)


class ConstructUserContextMiddleware(BaseMiddleware):
    """Відновлює пер-користувацький контекст групи перед кожним хендлером конструктора."""

    def __init__(self, construct: "ConstructEvent"):
        super().__init__()
        self.construct = construct

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        try:
            from_user = getattr(event, "from_user", None)
            if from_user and getattr(from_user, "id", None):
                self.construct._apply_user_group_context(int(from_user.id))
        except Exception:
            pass
        return await handler(event, data)

class ConstructEvent():
    def __init__(self):
        global ACTIVE_CONSTRUCT_EVENT
        ACTIVE_CONSTRUCT_EVENT = self
        self.router_construct_event = Router()
        self.router_construct_event.message.middleware(ConstructUserContextMiddleware(self))
        self.router_construct_event.callback_query.middleware(ConstructUserContextMiddleware(self))

        # Register message handlers - тільки в приватному чаті, щоб конструктор не спрацьовував у групі
        self.router_construct_event.message.register(self.construct_event_handler, Command("construct_event"))
        # Автоприв'язка /construct_event: коли бота додають у групу, одразу фіксуємо group_id -> creator_id в admin_panel.
        self.router_construct_event.message.register(
            self.auto_bind_group_on_bot_added,
            F.chat.type.in_(("group", "supergroup")),
            F.new_chat_members,
            F.func(self._is_bot_added_event),
        )
        self.router_construct_event.message.register(
            self.is_input_chat_id_handler,
            lambda message: self.is_input_chat_id and getattr(message.chat, "type", None) == "private"
            and getattr(message.from_user, "id", None) == self.awaiting_chat_id_user_id
            and not (message.text or "").strip().startswith("/")
        )
        self.router_construct_event.message.register(
            self.IsInputAddChatId,
            lambda message: self.is_input_add_chat_id and getattr(message.chat, "type", None) == "private"
            and getattr(message.from_user, "id", None) == self.awaiting_add_chat_id_user_id
            and not (message.text or "").strip().startswith("/")
        )
        self.router_construct_event.message.register(
            self.is_input_new_role_name_handler,
            lambda message: (
                getattr(message.chat, "type", None) == "private"
                and getattr(message.from_user, "id", None) not in self._mafia_scale_pending
                and not self.is_input_new_role_description
                and (self.is_input_new_role_name or self.is_creating_new_role)
                and not (message.text or "").strip().startswith("/")
                and (
                    self.awaiting_role_name_user_id is None
                    or getattr(message.from_user, "id", None) == self.awaiting_role_name_user_id
                )
            )
        )
        self.router_construct_event.message.register(
            self.is_input_new_role_description_handler,
            lambda message: self.is_input_new_role_description and getattr(message.chat, "type", None) == "private"
            and getattr(message.from_user, "id", None) not in self._mafia_scale_pending
            and getattr(message.from_user, "id", None) == self.awaiting_role_description_user_id
            and not (message.text or "").strip().startswith("/")
        )
        self.router_construct_event.message.register(
            self.is_input_min_players_handler,
            lambda message: self.is_input_min_players and getattr(message.chat, "type", None) == "private"
            and getattr(message.from_user, "id", None) not in self._mafia_scale_pending
            and getattr(message.from_user, "id", None) == self.awaiting_min_players_user_id
            and not (message.text or "").strip().startswith("/")
        )
        self.router_construct_event.message.register(
            self.is_input_mafia_scale_handler,
            lambda message: (
                getattr(message.chat, "type", None) == "private"
                and getattr(message.from_user, "id", None) in self._mafia_scale_pending
                and bool((message.text or "").strip())
                and not (message.text or "").strip().startswith("/")
            )
        )
        self.router_construct_event.message.register(
            self.role_card_photo_handler,
            lambda message: getattr(message.chat, "type", None) == "private"
            and getattr(message.from_user, "id", None) == self.awaiting_role_card_user_id
            and bool(message.photo)
        )
        self.router_construct_event.message.register(
            self.is_input_night_message_handler,
            lambda message: getattr(message.chat, "type", None) == "private"
            and getattr(message.from_user, "id", None) == self.awaiting_night_message_user_id
            and not (message.text or "").strip().startswith("/")
        )
        self.router_construct_event.message.register(
            self.backup_rename_message_handler,
            lambda message: getattr(message.chat, "type", None) == "private"
            and getattr(message.from_user, "id", None) in self._backup_rename_pending
            and message.text and not (message.text or "").strip().startswith("/")
        )

        # Register callback handlers for default roles
        self.router_construct_event.callback_query.register(self.doctor_callback_query, F.data == "doctor")
        self.router_construct_event.callback_query.register(self.all_capone_callback_query, F.data == "all_capone")
        self.router_construct_event.callback_query.register(self.civilian_callback_query, F.data == "civilian")
        self.router_construct_event.callback_query.register(self.sheriff_callback_query, F.data == "sheriff")
        self.router_construct_event.callback_query.register(self.prostitute_callback_query, F.data == "prostitute")
        self.router_construct_event.callback_query.register(self.maniac_callback_query, F.data == "maniac")
        self.router_construct_event.callback_query.register(self.default_role_callback("Мафія"), F.data == "mafia")
        self.router_construct_event.callback_query.register(self.default_role_callback("Самогубець"), F.data == "suicide")
        self.router_construct_event.callback_query.register(self.default_role_callback("Волоцюга"), F.data == "homeless")
        self.router_construct_event.callback_query.register(self.default_role_callback("Камікадзе"), F.data == "kamikaze")
        self.router_construct_event.callback_query.register(self.default_role_callback("Сержант"), F.data == "sergeant")
        self.router_construct_event.callback_query.register(self.default_role_callback("Щасливчик"), F.data == "lucky")
        self.router_construct_event.callback_query.register(self.default_role_callback("Мед. сестра"), F.data == "nurse")
        self.router_construct_event.callback_query.register(self.default_role_callback("Журналіст"), F.data == "journalist")
        self.router_construct_event.callback_query.register(self.default_role_callback("Адвокат"), F.data == "lawyer")
        self.router_construct_event.callback_query.register(self.default_role_callback("Клоун"), F.data == "clown")
        self.router_construct_event.callback_query.register(self.default_role_callback("Брехун"), F.data == "trickster")
        self.router_construct_event.callback_query.register(self.default_role_callback("Диявол"), F.data == "devil")
        self.router_construct_event.callback_query.register(self.create_new_role_callback, F.data == "create_new_role")
        self.router_construct_event.callback_query.register(self.go_to_main_menu_callback(), F.data == "go_to_main_menu")
        self.router_construct_event.callback_query.register(self.add_group_handler, F.data == "add_group")
        self.router_construct_event.callback_query.register(self.delete_group_handler(), F.data == "delete_group")
        self.router_construct_event.callback_query.register(self.default_settings, F.data == "default")
        
        # Register tab selection handlers
        self.router_construct_event.callback_query.register(self.menu_roles_callback, F.data == "menu_roles")
        self.router_construct_event.callback_query.register(self.menu_basic_settings_callback, F.data == "menu_basic_settings")
        self.router_construct_event.callback_query.register(self.menu_premium_subscription_callback, F.data == "menu_premium_subscription")
        self.router_construct_event.callback_query.register(self.menu_premium_choose_callback, F.data == "menu_premium_choose")
        self.router_construct_event.callback_query.register(self.tab_standard_callback, F.data == "tab_standard")
        self.router_construct_event.callback_query.register(self.tab_custom_callback, F.data == "tab_custom")
        self.router_construct_event.callback_query.register(self.close_menu_callback, F.data == "close_menu")
        self.router_construct_event.callback_query.register(self.back_to_categories_callback, F.data == "back_to_categories")
        self.router_construct_event.callback_query.register(self.group_settings_callback, F.data == "group_settings")
        self.router_construct_event.callback_query.register(self.group_settings_buffs_toggle_callback, F.data == "group_settings_buffs_toggle")
        self.router_construct_event.callback_query.register(self.group_settings_buffs_list_callback, F.data == "group_settings_buffs_list")
        self.router_construct_event.callback_query.register(self.group_settings_themes_callback, F.data == "group_settings_themes")
        self.router_construct_event.callback_query.register(self.group_settings_back_callback, F.data == "group_settings_back")
        self.router_construct_event.callback_query.register(
            self.group_settings_buff_toggle_callback,
            F.data.startswith("group_settings_buff_toggle:"),
        )
        self.router_construct_event.callback_query.register(
            self.group_settings_theme_toggle_callback,
            F.data.startswith("group_settings_theme:"),
        )
        self.router_construct_event.callback_query.register(self.backup_menu_callback, F.data == "backup_menu")
        self.router_construct_event.callback_query.register(self.backup_save_callback, F.data == "backup_save")
        self.router_construct_event.callback_query.register(self.backup_back_callback, F.data == "backup_back")
        self.router_construct_event.callback_query.register(
            self.backup_restore_callback,
            F.data.startswith("backup_restore:"),
        )
        self.router_construct_event.callback_query.register(
            self.backup_delete_callback,
            F.data.startswith("backup_delete:"),
        )
        self.router_construct_event.callback_query.register(
            self.backup_rename_callback,
            F.data.startswith("backup_rename:"),
        )
        self.router_construct_event.callback_query.register(self.admin_logs_callback, F.data == "admin_logs")
        # Відкриття налаштувань конкретної групи з ЛС (кнопка з /settings у групі)
        self.router_construct_event.callback_query.register(
            self.open_group_settings_callback,
            F.data.startswith("open_group_settings:"),
        )

        # State flags
        self.is_input_chat_id = False
        self.is_input_add_chat_id = False
        self.is_input_new_role_name = False
        self.is_input_new_role_description = False
        self.is_input_role_alignment = False
        self.is_input_min_players = False
        self.is_input_mafia_scale = False
        # Тільки повідомлення від цих user_id обробляються як введення (щоб інший користувач не "перехопив" потік)
        self.awaiting_chat_id_user_id: Optional[int] = None
        self.awaiting_add_chat_id_user_id: Optional[int] = None
        self.awaiting_role_name_user_id: Optional[int] = None
        self.awaiting_role_description_user_id: Optional[int] = None
        self.awaiting_min_players_user_id: Optional[int] = None
        self.awaiting_mafia_scale_user_id: Optional[int] = None
        self.is_creating_new_role = False
        # Контекст очікування по user_id (щоб двоє людей редагували різні ролі - зміни не плутались)
        self._min_players_pending: Dict[int, Dict[str, Any]] = {}
        self._mafia_scale_pending: Dict[int, Dict[str, Any]] = {}
        self._role_name_pending: Dict[int, Dict[str, Any]] = {}
        self._role_description_pending: Dict[int, Dict[str, Any]] = {}
        self._backup_rename_pending: Dict[int, Dict[str, Any]] = {}
        self.awaiting_role_card_user_id: Optional[int] = None
        # Очікуємо текст нічного повідомлення для кастомної ролі (сповіщення цілі)
        self.awaiting_night_message_user_id: Optional[int] = None

        # Current state
        self.chat_id = 0
        self.current_role: Optional[Role] = None
        self.name_of_chats = []
        self.role_in_db = ""
        self.name_of_role = ""
        self.current_tab = "standard"  # "standard", "custom"
        # The owner (creator_id) of the selected group from admin_panel.
        # We use this as the single source-of-truth key for role configs,
        # so settings don't "flip back" when different admins open /construct_event.
        self.group_creator_id: int = 0
        # Per-user selected group context (щоб /settings у різних адмінів не перетирав один одного).
        self._user_group_ctx: Dict[int, Dict[str, int]] = {}

        # Короткий лог дій адмінів (по чатах): chat_id -> deque останніх записів
        from collections import defaultdict, deque
        self.admin_logs = defaultdict(lambda: deque(maxlen=40))

    async def _user_is_telegram_group_creator(self, bot: Bot, chat_id: int, user_id: int) -> bool:
        """Чи є користувач власником (creator) групи/супергрупи в Telegram."""
        try:
            m = await bot.get_chat_member(chat_id, user_id)
            return m.status == ChatMemberStatus.CREATOR
        except Exception:
            return False

    def _log_admin_action(self, chat_id: int, user_id: int, action: str):
        """
        Додає короткий запис у внутрішній лог конструктора.
        Не пишемо в БД, щоб не засмічувати її; тільки для перегляду в /construct_event.
        """
        name = str(user_id)
        ts = datetime.now().strftime("%H:%M")
        safe_name = html.escape(str(name).strip() or str(user_id))
        entry = f"{ts} - {safe_name}: {action}"
        self.admin_logs[int(chat_id)].appendleft(entry)

    def _set_user_group_context(self, user_id: int, chat_id: int, creator_id: int) -> None:
        """Persist selected group context for конкретного користувача."""
        try:
            self._user_group_ctx[int(user_id)] = {
                "chat_id": int(chat_id),
                "creator_id": int(creator_id),
            }
        except Exception:
            pass

    def _apply_user_group_context(self, user_id: int) -> None:
        """Restore user's selected group into legacy shared fields."""
        ctx = self._user_group_ctx.get(int(user_id))
        if not ctx:
            return
        try:
            self.chat_id = int(ctx.get("chat_id", 0) or 0)
        except Exception:
            pass
        try:
            self.group_creator_id = int(ctx.get("creator_id", 0) or 0)
        except Exception:
            pass

    def _can_edit_roles(self, user_id: int) -> bool:
        """Чи може користувач створювати/редагувати ролі (назва, опис, здатності). Потрібна підписка творця групи."""
        if user_id == BOT_OWNER_ID:
            return True
        creator_id = self.group_creator_id or user_id
        return ShopManager.is_subscription_active(creator_id)

    def _ability_type_ua(self, ability_type: AbilityType) -> str:
        mapping = {
            AbilityType.KILL: "Убити",
            AbilityType.HEAL: "Лікувати",
            AbilityType.CHECK_ROLE: "Перевірити роль",
            AbilityType.BLOCK_ACTION: "Заблокувати дію",
            AbilityType.PROTECT: "Захистити",
            AbilityType.INSPECT: "Розслідувати",
            AbilityType.CUSTOM_EFFECT: "Спецефект",
        }
        return mapping.get(ability_type, "Невідома дія")

    def _ability_phase_ua(self, phase: AbilityPhase) -> str:
        mapping = {
            AbilityPhase.DAY: "День",
            AbilityPhase.NIGHT: "Ніч",
            AbilityPhase.BOTH: "День/Ніч",
            AbilityPhase.VOTING: "Голосування",
        }
        return mapping.get(phase, "Невідома фаза")

    def _ability_target_type_ua(self, target_type: TargetType) -> str:
        mapping = {
            TargetType.ONE_PLAYER: "Один гравець",
            TargetType.TWO_PLAYERS: "Два гравці",
            TargetType.SELF: "На себе",
            TargetType.ANY_ALIVE: "Будь-хто з живих",
            TargetType.ANY_DEAD: "Будь-хто з мертвих",
            TargetType.MULTIPLE_PLAYERS: "Кілька гравців",
            TargetType.NO_TARGET: "Без цілі",
        }
        return mapping.get(target_type, "Невідомо")

    def _ability_usage_limit_ua(self, usage_limit: UsageLimit) -> str:
        mapping = {
            UsageLimit.UNLIMITED: "Без обмежень",
            UsageLimit.ONCE_PER_GAME: "1 раз за гру",
            UsageLimit.ONCE_PER_NIGHT: "1 раз за ніч",
            UsageLimit.ONCE_PER_DAY: "1 раз за день",
        }
        return mapping.get(usage_limit, "Невідомо")

    def _ensure_current_role(self, callback_or_message=None) -> bool:
        """
        Відновлює current_role з БД, якщо він None але є name_of_role і chat_id.
        Повертає True якщо роль є (або вже була), False якщо не вдалося завантажити.
        Приймає CallbackQuery або Message для отримання user_id.
        """
        if self.current_role is not None:
            return True
        if not self.name_of_role or not self.chat_id:
            return False
        user_id = 0
        if callback_or_message and hasattr(callback_or_message, "from_user") and callback_or_message.from_user:
            user_id = callback_or_message.from_user.id
        group_id = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
        # Спробувати кілька варіантів creator_id (роль могла бути створена з іншим ключем)
        for creator_key in (self.group_creator_id, user_id):
            if not creator_key:
                continue
            role = ChatRoleRegistry.get_role_for_chat(creator_key, group_id, self.name_of_role)
            if role:
                self.current_role = role
                self.role_in_db = "custom_role" if not getattr(role, "is_default", False) else self.role_in_db
                return True
        return False

    def _is_bot_added_event(self, message: Message) -> bool:
        """Швидкий pre-filter: у події додано принаймні одного бота."""
        members = getattr(message, "new_chat_members", None) or []
        if not members:
            return False
        for u in members:
            if u and getattr(u, "is_bot", False):
                return True
        return False

    async def auto_bind_group_on_bot_added(self, message: Message, bot: Bot):
        """
        Автоматично прив'язує /construct_event до групи, коли бота додають у чат:
        - визначає creator_id групи;
        - створює рядок admin_panel (creator_id, group_id), якщо для group_id ще немає запису.
        """
        try:
            chat_id = int(message.chat.id)
        except Exception:
            return
        if chat_id >= 0:
            return
        # Важливо: реагуємо тільки коли додали саме цього бота, а не будь-якого іншого.
        try:
            me = await bot.get_me()
            my_id = int(me.id)
            member_ids = {int(u.id) for u in (getattr(message, "new_chat_members", None) or []) if u}
            if my_id not in member_ids:
                return
        except Exception:
            return

        # Якщо група вже має прив'язку - нічого не робимо.
        try:
            existing = await _db_fetchone_async(
                "SELECT creator_id FROM admin_panel WHERE group_id = %s LIMIT 1",
                (chat_id,),
            )
            if existing:
                return
        except Exception:
            return

        creator_id = None
        try:
            admins = await bot.get_chat_administrators(chat_id)
            for adm in admins or []:
                if getattr(adm, "status", None) == ChatMemberStatus.CREATOR and getattr(adm, "user", None):
                    creator_id = int(adm.user.id)
                    break
        except Exception:
            creator_id = None

        if creator_id is None:
            try:
                inviter = getattr(message, "from_user", None)
                if inviter:
                    m = await bot.get_chat_member(chat_id, inviter.id)
                    if getattr(m, "status", None) == ChatMemberStatus.CREATOR:
                        creator_id = int(inviter.id)
            except Exception:
                creator_id = None

        if creator_id is None:
            return

        try:
            await _db_execute_commit_async(
                "INSERT INTO admin_panel (creator_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (creator_id, chat_id),
            )
        except Exception:
            pass

    async def _auto_register_owned_known_groups(self, user_id: int, bot: Bot) -> int:
        """
        One-shot self-heal for /construct_event:
        if bot already knows groups (bot_known_groups), auto-add groups where user is CREATOR.
        """
        added = 0
        try:
            rows = await _db_fetchall_async(
                """
                SELECT group_id
                FROM bot_known_groups
                ORDER BY last_seen_at DESC
                LIMIT 300
                """
            )
            known_ids = [int(r[0]) for r in (rows or []) if r and r[0] is not None]
        except Exception:
            return 0

        for gid in known_ids:
            try:
                existing = await _db_fetchone_async(
                    "SELECT creator_id FROM admin_panel WHERE group_id = %s LIMIT 1",
                    (gid,),
                )
                if existing:
                    continue
                m = await bot.get_chat_member(gid, user_id)
                if getattr(m, "status", None) != ChatMemberStatus.CREATOR:
                    continue
                await _db_execute_commit_async(
                    "INSERT INTO admin_panel (creator_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (int(user_id), int(gid)),
                )
                added += 1
            except Exception:
                continue
        return added


    async def construct_event_handler(self, message: Message, bot: Bot):
        """Main handler for /construct_event command"""
        # Proper try/except structure and fixed indentation
        #region agent log
        _log_debug('debug-session', 'run1', 'C1', 'construct_event.py:construct_event_handler', '/construct_event received', {
            'chat_type': message.chat.type,
            'user_id': message.from_user.id
        })
        #endregion
        try:
            # Only work in private chat
            if message.chat.type != "private":
                await message.answer(
                    "⚠️ <b>Приватний чат</b>\n\n"
                    "Будь ласка, надішли це повідомлення у <b>приватний чат</b> з ботом! 🔒",
                    parse_mode="html"
                )
                return
            # Reset flags
            self.is_input_chat_id = False
            self.is_input_add_chat_id = False
            self.is_input_new_role_name = False
            self.is_input_new_role_description = False
            self.awaiting_chat_id_user_id = None
            self.awaiting_add_chat_id_user_id = None
            self.awaiting_role_name_user_id = None
            self.awaiting_role_description_user_id = None
            self.awaiting_min_players_user_id = None
            self.awaiting_mafia_scale_user_id = None
            self.awaiting_role_card_user_id = None
            self.awaiting_night_message_user_id = None
            self.awaiting_night_message_user_id = None
            self.is_creating_new_role = False
            self.name_of_chats = []
            self._min_players_pending.clear()
            self._mafia_scale_pending.clear()
            self._role_name_pending.clear()
            self._role_description_pending.clear()
            self._backup_rename_pending.clear()

            # Самовідновлення: якщо групу додали раніше (до авто-бінду), пробуємо
            # автоматично підв'язати відомі боту групи, де user є CREATOR.
            try:
                await self._auto_register_owned_known_groups(message.from_user.id, bot)
            except Exception:
                pass
            
            # Check if user can access: BOT_OWNER, creator of any group, or admin level 3+ in any group
            creator_rows = await _db_fetchall_async("SELECT creator_id FROM admin_panel")
            creator_ids = [row[0] for row in (creator_rows or [])]
            if BOT_OWNER_ID not in creator_ids:
                creator_ids.append(BOT_OWNER_ID)
            group_ids_with_rights = get_group_ids_where_user_has_construct_rights(message.from_user.id)
            can_access = (
                message.from_user.id == BOT_OWNER_ID
                or message.from_user.id in creator_ids
                or len(group_ids_with_rights) > 0
            )
            #region agent log
            _log_debug('debug-session', 'run1', 'C2', 'construct_event.py:construct_event_handler', 'Access check', {
                'creator_ids_len': len(creator_ids),
                'group_ids_with_rights_len': len(group_ids_with_rights),
                'can_access': can_access
            })
            #endregion
        except Exception as e:
            print(f"Error in construct_event_handler: {e}")
            await message.answer(
                " Виникла помилка під час обробки запиту. Спробуйте ще раз.",
                parse_mode="html"
            )
            return

        if not can_access:
            await message.answer(
                "🎭 <b>Налаштування ролей</b> 🎭\n\n"
                "📋 <b>У тебе немає доступу.</b>\n\n"
                "Налаштовувати ролі можуть: <b>власник групи</b> або <b>адмін 3+ рівня</b> (команда <code>+адмін 3</code> в групі). 👑\n\n"
                "💡 Якщо ти власник - надішли <b>ID групи</b>. Якщо тобі видали права адміна 3 - обери групу зі списку після доступу.",
                parse_mode="html"
            )
            self.is_input_chat_id = True
            self.awaiting_chat_id_user_id = message.from_user.id
            return

        # Get user's groups: власник (creator_id) або адмін рівня 3+
        group_ids_with_rights = get_group_ids_where_user_has_construct_rights(message.from_user.id)
        group_ids = [(gid,) for gid in group_ids_with_rights]
        # #region agent log
        _log_debug('debug-session', 'run1', 'C2', 'construct_event.py:construct_event_handler', 'Loaded group_ids', {
            'group_ids_len': len(group_ids)
        })
        # #endregion

        if not group_ids:
            await message.answer(
                "📂 <b>Немає зареєстрованих груп</b> 📂\n\n"
                "У тебе ще немає жодної зареєстрованої групи.\n\n"
                "Надішли мені <b>ID групи</b>, яку <u><b>ти створив</b></u> для першої реєстрації.\n\n"
                "💡 <i>Щоб дізнатися ID групи, надішли команду <code>/id</code> у тій групі, яку <b>ти створив</b></i>\n\n"
                "⏳ Очікую ID групи...",
                parse_mode="html"
            )
            self.is_input_chat_id = True
            self.awaiting_chat_id_user_id = message.from_user.id
            return

        # Build group selection menu
        builder = InlineKeyboardBuilder()
        for chat_id_tuple in group_ids:
            chat_id = int(chat_id_tuple[0])
            try:
                chat = await bot.get_chat(chat_id=chat_id)
                builder.button(text=f"📁 {chat.title}", callback_data=f"group_{chat_id}")
                self.name_of_chats.append((chat_id, chat.title))
            except Exception as e:
                print(f"Error getting chat {chat_id}: {e}")
                continue
        
        builder.adjust(1)

        if self.name_of_chats:
            # Register group callbacks
            for chat_id, title in self.name_of_chats:
                self.router_construct_event.callback_query.register(
                    self.group_selected_callback(chat_id), 
                    F.data == f"group_{chat_id}"
                )
            await message.answer(
                "🎯 <b>Вибір групи</b> 🎯\n\n"
                "⬇️ Вибери чат для налаштування ролей: ⬇️",
                reply_markup=builder.as_markup(),
                parse_mode="html"
            )
        else:
            await message.answer(
                " <b>Помилка завантаження</b> \n\n"
                "Не вдалося завантажити групи з бази даних.\n\n"
                "Надішли мені <b>ID групи</b>, яку <u><b>ти створив</b></u> для реєстрації.\n\n"
                "💡 <i>Щоб дізнатися ID групи, надішли команду <code>/id</code> у тій групі, яку <b>ти створив</b></i>",
                parse_mode="html"
            )
            self.is_input_chat_id = True
            self.awaiting_chat_id_user_id = message.from_user.id

    def group_selected_callback(self, chat_id: int):
        """Handler when a group is selected. Усі подальші зміни ролей застосовуються лише до цієї групи."""
        async def handler(callback: CallbackQuery):
            self.chat_id = int(chat_id)
            # Власник групи з БД - усі ролі читаються/зберігаються тільки для (creator_id, group_id).
            # Зміни для інших груп не чіпаються.
            try:
                r = await _db_fetchone_async(
                    "SELECT creator_id FROM admin_panel WHERE group_id = %s",
                    (self.chat_id,),
                )
                self.group_creator_id = int(r[0]) if r and r[0] is not None else callback.from_user.id
            except Exception:
                self.group_creator_id = callback.from_user.id
            if callback.from_user:
                self._set_user_group_context(callback.from_user.id, int(self.chat_id), int(self.group_creator_id))
            
            # Check if group is blocked
            result = await _db_fetchone_async(
                "SELECT is_blocked FROM admin_panel WHERE group_id = %s",
                (chat_id,),
            )
            if result and result[0]:
                await callback.answer("🚫Лавочку прикрили. Доступу немає.", show_alert=True)
                await callback.message.answer("🚫Лавочку прикрили. Доступу немає.")
                return
            
            try:
                await callback.answer(" Завантажую меню...")
            except Exception:
                pass
            try:
                await self.show_main_menu(callback, tab=None)
            except Exception as e:
                _log_debug('debug-session', 'run1', 'C3', 'construct_event.py:group_selected_callback', 'Failed to show main menu', {
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                    'chat_id': self.chat_id
                })
                try:
                    await callback.message.answer(" Помилка відкриття меню. Спробуй ще раз.")
                except Exception:
                    pass
        return handler


    async def open_group_settings_callback(self, callback: CallbackQuery):
        """
        Відкрити конструктор одразу для конкретної групи по callback'у з ЛС.
        Використовується разом із командою /settings у групі.
        """
        if not callback.from_user:
            await callback.answer()
            return

        data = callback.data or ""
        parts = data.split(":", 1)
        if len(parts) != 2:
            await callback.answer("Помилка даних.", show_alert=True)
            return

        raw_chat_id = parts[1]
        chat_id = _parse_group_id(raw_chat_id)
        if chat_id is None:
            await callback.answer("Невірний ID групи.", show_alert=True)
            return

        user_id = callback.from_user.id
        self._apply_user_group_context(user_id)

        try:
            # Перевірка прав доступу до цієї групи
            group_ids_with_rights = get_group_ids_where_user_has_construct_rights(user_id)
            if user_id != BOT_OWNER_ID and chat_id not in group_ids_with_rights:
                await callback.answer(
                    "❌ У тебе немає прав налаштовувати цю групу.\n"
                    "Потрібно бути власником групи або адміном 3+ рівня.",
                    show_alert=True,
                )
                return

            # Встановлюємо поточну групу й creator_id
            self.chat_id = int(chat_id)
            try:
                r = await _db_fetchone_async(
                    "SELECT creator_id FROM admin_panel WHERE group_id = %s",
                    (self.chat_id,),
                )
                self.group_creator_id = int(r[0]) if r and r[0] is not None else user_id
            except Exception:
                self.group_creator_id = user_id
            self._set_user_group_context(user_id, int(self.chat_id), int(self.group_creator_id))

            try:
                await callback.answer("Завантажую налаштування групи...")
            except Exception:
                pass

            await self.show_main_menu(callback, tab=None)
        except Exception as e:
            try:
                await callback.answer("Помилка відкриття налаштувань.", show_alert=True)
            except Exception:
                pass

    async def open_group_settings_direct(self, bot: Bot, user_id: int, chat_id: int) -> bool:
        """Відкрити налаштування конкретної групи в ЛС без проміжної кнопки."""
        try:
            self._apply_user_group_context(user_id)
            self.chat_id = int(chat_id)
            try:
                r = await _db_fetchone_async(
                    "SELECT creator_id FROM admin_panel WHERE group_id = %s",
                    (self.chat_id,),
                )
                self.group_creator_id = int(r[0]) if r and r[0] is not None else int(user_id)
            except Exception:
                self.group_creator_id = int(user_id)
            self._set_user_group_context(int(user_id), int(self.chat_id), int(self.group_creator_id))

            # Одразу відправляємо головне меню конструктора без проміжного повідомлення.
            rows = [
                [_icon_button("Ролі", "menu_roles", "👥")],
                [_icon_button("Основні налаштування", "menu_basic_settings", "🛠️")],
                [_icon_button("Скинути налаштування", "default", "🔄")],
                [_icon_button("Преміум підписка", "menu_premium_subscription", "💎")],
                [_icon_button("Повернутися", "close_menu", "⬅️")],
            ]
            text = (
                "<b>Що змінюємо сьогодні?</b>"
            )
            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                parse_mode="html",
            )
            return True
        except Exception:
            return False


    async def show_main_menu(self, callback_or_message, tab=None):
        """Show main role selection menu with tabs.
        Усі ролі завантажуються та зберігаються тільки для обраної групи (creator_id + group_id).
        Зміни для однієї групи ніколи не застосовуються до інших груп.
        """
        user_id = 0
        if isinstance(callback_or_message, CallbackQuery):
            if callback_or_message.from_user:
                user_id = callback_or_message.from_user.id
        elif getattr(callback_or_message, "from_user", None):
            user_id = callback_or_message.from_user.id
        if user_id:
            self._apply_user_group_context(user_id)

        if not self.chat_id or self.chat_id == 0:
            msg = callback_or_message.message if isinstance(callback_or_message, CallbackQuery) else callback_or_message
            try:
                await msg.answer("⚠️ Спочатку оберіть групу зі списку.", parse_mode="html")
            except Exception:
                pass
            return
        # Get message object
        if isinstance(callback_or_message, CallbackQuery):
            message = callback_or_message.message
            user_id = callback_or_message.from_user.id
        else:
            message = callback_or_message
            user_id = callback_or_message.from_user.id

        # Ensure group_id is int
        group_id_for_query = self.chat_id
        if isinstance(group_id_for_query, tuple):
            group_id_for_query = int(group_id_for_query[0])

        # Load all roles for this chat using the group's creator_id as the key.
        # This prevents "enabled/min_players resets" when different admins open the menu.
        creator_key = self.group_creator_id or user_id
        all_roles = ChatRoleRegistry.get_all_roles_for_chat(creator_key, group_id_for_query)
        default_roles = ChatRoleRegistry.get_default_roles_for_chat(creator_key, group_id_for_query)
        custom_roles = ChatRoleRegistry.get_custom_roles_for_chat(creator_key, group_id_for_query)
        
        # Стандартні = всі дефолтні ролі гри; кастомні = створені вручну
        STANDARD_ROLE_NAMES = {
            "Адвокат", "Аль Капоне", "Брехун", "Диявол", "Комісар Каттані", "Лікар", "Мирний житель",
            "Волоцюга", "Журналіст", "Камікадзе", "Коханка", "Маніяк", "Мафія",
            "Мед. сестра", "Самогубець", "Сержант", "Щасливчик", "Клоун",
        }
        
        standard_roles = [r for r in all_roles if r.name in STANDARD_ROLE_NAMES]
        custom_roles_filtered = [r for r in custom_roles if r.name not in STANDARD_ROLE_NAMES]
        
        # #region agent log
        _log_debug('debug-session', 'run1', 'C3', 'construct_event.py:show_main_menu', 'Loaded roles for menu', {
            'user_id': user_id,
            'creator_key': creator_key,
            'group_id': group_id_for_query,
            'all_roles_len': len(all_roles),
            'standard_roles_len': len(standard_roles),
            'custom_roles_len': len(custom_roles_filtered),
            'current_tab': tab
        })
        # #endregion

        # Build buttons
        builder = InlineKeyboardBuilder()
        if tab:
            tab_standard_emoji = "" if tab == "standard" else "📋"
            tab_custom_emoji = "" if tab == "custom" else "🎭"
            builder.button(text=f"{tab_standard_emoji} Стандартні", callback_data="tab_standard")
            builder.button(text=f"{tab_custom_emoji} Кастомні", callback_data="tab_custom")
            builder.button(text="Закрити", callback_data="close_menu")
            builder.adjust(2, 2)
        
        # Default roles - map role names to callback_data with emojis
        default_role_callbacks = {
            "Лікар": ("doctor", "💊"),
            "Аль Капоне": ("all_capone", "🎩"),
            "Мирний житель": ("civilian", "🧍"),
            "Комісар Каттані": ("sheriff", "🕵️"),
            "Коханка": ("prostitute", "💋"),
            "Маніяк": ("maniac", "🔪"),
            "Мафія": ("mafia", "🤵"),
            "Самогубець": ("suicide", "🤦‍♂️"),
            "Волоцюга": ("homeless", "🧥"),
            "Камікадзе": ("kamikaze", "💣"),
            "Сержант": ("sergeant", "👮‍♂️"),
            "Щасливчик": ("lucky", "🍀"),
            "Мед. сестра": ("nurse", "👩‍⚕️"),
            "Журналіст": ("journalist", "👨‍💼"),
            "Адвокат": ("lawyer", "👨‍💼"),
            "Клоун": ("clown", "🤡"),
            "Брехун": ("trickster", "🎭"),
            "Диявол": ("devil", "👹")
        }
        
        # Show roles only if a tab is selected
        roles_to_show = []
        tab_name = ""
        if tab == "standard":
            roles_to_show = standard_roles
            tab_name = "Стандартні"
            for standard_role in standard_roles:
                callback_data, emoji = default_role_callbacks.get(standard_role.name, (None, ""))
                if callback_data:
                    state = "✅" if getattr(standard_role, "enabled", True) else "⬜"
                    builder.button(text=f"{state} {emoji} {standard_role.name}", callback_data=callback_data)
        elif tab == "custom":
            roles_to_show = custom_roles_filtered
            tab_name = "Кастомні"
            # Add custom roles as buttons
            for custom_role in custom_roles_filtered:
                state = "✅" if getattr(custom_role, "enabled", True) else "⬜"
                builder.button(text=f"{state} 🎭 {custom_role.name}", callback_data=f"custom_role_{custom_role.name}")
        
        if tab:
            # Екран списку ролей конкретної вкладки: тільки ролі + повернення в меню «Ролі».
            builder.add(_icon_button("Повернутися", "menu_roles", "⬅️"))
        else:
            # Головне меню налаштувань (оновлена структура).
            builder.row(_icon_button("Ролі", "menu_roles", "👥"))
            builder.row(_icon_button("Основні налаштування", "menu_basic_settings", "🛠️"))
            builder.row(_icon_button("Скинути налаштування", "default", "🔄"))
            builder.row(_icon_button("Преміум підписка", "menu_premium_subscription", "💎"))
            builder.row(_icon_button("Повернутися", "close_menu", "⬅️"))
        
        builder.adjust(1)

        # Register handlers for custom roles
        for custom_role in custom_roles:
            self.router_construct_event.callback_query.register(
                self.custom_role_callback(custom_role.name),
                F.data == f"custom_role_{custom_role.name}"
            )

        # Build text based on whether tab is selected
        if tab:
            roles_count = len(roles_to_show)
            enabled_count = sum(1 for r in roles_to_show if getattr(r, "enabled", True))
            text = (
                f"🎭 <b>Налаштування ролей</b> 🎭\n\n"
                f"📂 <b>Вкладка: {tab_name}</b>\n\n"
                f"📊 Ролей у вкладці: <b>{roles_count}</b> · увімкнено: <b>{enabled_count}</b>\n"
                f"<i>✅ — у грі, ⬜ — вимкнена</i>\n\n"
                "⬇️ <b>Тисни роль, щоб налаштувати:</b> ⬇️"
            )
        else:
            text = (
                "<b>Що змінюємо сьогодні?</b>"
            )

        text = emoji_to_premium(text)
        
        if isinstance(callback_or_message, CallbackQuery):
            try:
                await callback_or_message.message.edit_text(
                    text, 
                    reply_markup=builder.as_markup(), 
                    parse_mode="html"
                )
            except Exception as e:
                _log_debug('debug-session', 'run1', 'C4', 'construct_event.py:show_main_menu', 'Edit message failed, sending new', {
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                })
                await callback_or_message.message.answer(
                    text, 
                    reply_markup=builder.as_markup(), 
                    parse_mode="html"
                )
        else:
            await callback_or_message.answer(text, reply_markup=builder.as_markup(), parse_mode="html")
        
        # Update current tab
        if tab:
            self.current_tab = tab

    async def tab_standard_callback(self, callback: CallbackQuery):
        """Handler for Standard tab"""
        try:
            await callback.answer()
            await self.show_main_menu(callback, tab="standard")
        except Exception as e:
            print(f"Error in tab_standard_callback: {e}")

    async def tab_custom_callback(self, callback: CallbackQuery):
        """Handler for Custom tab"""
        try:
            await callback.answer()
            await self.show_main_menu(callback, tab="custom")
        except Exception as e:
            print(f"Error in tab_custom_callback: {e}")

    async def close_menu_callback(self, callback: CallbackQuery):
        """Handler for closing menu"""
        try:
            await callback.answer("Меню закрито")
            await callback.message.delete()
        except Exception as e:
            print(f"Error in close_menu_callback: {e}")
            try:
                await callback.answer(" Помилка закриття меню")
            except:
                pass

    async def menu_roles_callback(self, callback: CallbackQuery):
        """Підменю «Ролі»."""
        if callback.from_user:
            self._apply_user_group_context(callback.from_user.id)
        await callback.answer()
        rows = [
            [_icon_button("Стандартні", "tab_standard", "👤")],
            [_icon_button("Власні", "tab_custom", "🎨")],
            [_icon_button("Створити роль", "create_new_role", "➕")],
            [_icon_button("Повернутися", "go_to_main_menu", "⬅️")],
        ]
        text = (
            "👥 <b>Ролі</b>\n\n"
            "Оберіть розділ:"
        )
        text = emoji_to_premium(text)
        try:
            await callback.message.edit_text(
                text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="html"
            )
        except Exception:
            await callback.message.answer(
                text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="html"
            )

    async def menu_basic_settings_callback(self, callback: CallbackQuery):
        """Підменю «Основні налаштування»."""
        if callback.from_user:
            self._apply_user_group_context(callback.from_user.id)
        await callback.answer()
        rows = [
            [_icon_button("Налаштування чату", "group_settings", "📝")],
            [_icon_button("Бекапи налаштувань", "backup_menu", "📋")],
            [_icon_button("Логи дій", "admin_logs", "📑")],
            [_icon_button("Повернутися", "go_to_main_menu", "⬅️")],
        ]
        text = emoji_to_premium("🛠️ <b>Основні налаштування</b>")
        try:
            await callback.message.edit_text(
                text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="html"
            )
        except Exception:
            await callback.message.answer(
                text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="html"
            )

    async def menu_premium_subscription_callback(self, callback: CallbackQuery):
        """Відкрити екран підписки для чату (групові тарифи)."""
        await callback.answer()
        if not callback.message or not callback.from_user:
            return
        try:
            creator_id = int(self.group_creator_id or callback.from_user.id)
            if self.chat_id:
                try:
                    group_id = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
                    creator_row = await _db_fetchone_async(
                        "SELECT creator_id FROM admin_panel WHERE group_id = %s LIMIT 1",
                        (group_id,),
                    )
                    if creator_row and creator_row[0]:
                        creator_id = int(creator_row[0])
                except Exception:
                    pass

            sub = await ShopManager.get_user_subscription_async(creator_id)
            is_active = await ShopManager.is_subscription_active_async(creator_id)
            if is_active:
                end_dt = sub.get("subscription_end") if sub else None
                if end_dt:
                    sub_status = f"<b>Статус чату:</b> підписка активна до <code>{end_dt.strftime('%d.%m.%Y %H:%M')}</code>."
                else:
                    sub_status = "<b>Статус чату:</b> підписка активна."
            else:
                sub_status = "<b>Статус чату:</b> підписка не активна."

            text = (
                "💬 <b>Підписка для чату</b>\n\n"
                f"{sub_status}\n\n"
                "💎 <b>Переваги Преміум-підписок:</b>\n\n"
                "1. Розширені налаштування чату без обмежень.\n"
                "2. Кастомні ролі та гнучкі сценарії керування.\n"
                "3. Бекапи конфігурацій та швидке відновлення.\n"
                "4. Логи дій адмінів для повного контролю.\n"
                "5. Пріоритет по залізу: швидкість та оновлення.\n"
                "6. Повна свобода налаштувань під ваш стиль."
            )
            rows = [
                [_icon_button("Обрати свою", "menu_premium_choose", "💎")],
                [_icon_button("Повернутися", "go_to_main_menu", "⬅️")],
            ]
            await callback.message.edit_text(
                emoji_to_premium(text),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                parse_mode="html",
            )
        except Exception:
            await callback.answer("Не вдалося відкрити меню підписки.", show_alert=True)

    async def menu_premium_choose_callback(self, callback: CallbackQuery):
        """Список тарифів підписки для чату (без дублювання переваг)."""
        await callback.answer()
        if not callback.message or not callback.from_user:
            return
        try:
            from commands.buy import ShopManager, CHAT_SUBSCRIPTION_IDS
            from commands import vip as vip_mod

            uid = callback.from_user.id
            text = (
                "💎 <b>Магазин підписок</b> 💎\n\n"
                "⭐ <b>Оберіть підписку:</b>"
            )
            builder = InlineKeyboardBuilder()
            for item_id in CHAT_SUBSCRIPTION_IDS:
                item = ShopManager.get_item(item_id)
                if not item:
                    continue
                star_price = vip_mod.effective_star_price(item, uid)
                text += (
                    f"\n\n• <b>{item.name}</b>\n"
                    f"💰 Ціна: {star_price} ⭐\n"
                    f"⏱️ Тривалість: {item.duration_days} днів"
                )
                builder.button(text=f"{item.name} - {star_price} ⭐", callback_data=f"buy_{item_id}")
            builder.add(_icon_button("Назад", "menu_premium_subscription", "⬅️"))
            builder.adjust(1)
            await callback.message.edit_text(
                emoji_to_premium(text),
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
        except Exception:
            await callback.answer("Не вдалося відкрити тарифи.", show_alert=True)

    async def back_to_categories_callback(self, callback: CallbackQuery):
        """Handler for going back to category selection"""
        try:
            await callback.answer()
            await self.menu_roles_callback(callback)
        except Exception as e:
            print(f"Error in back_to_categories_callback: {e}")

    def go_to_main_menu_callback(self):
        """Callback to return to main menu"""
        async def handler(callback: CallbackQuery):
            await self.show_main_menu(callback, tab=None)
        return handler

    async def group_settings_callback(self, callback: CallbackQuery):
        """Меню налаштувань групи: бафи в грі та конкретні бафи."""
        if callback.from_user:
            self._apply_user_group_context(callback.from_user.id)
        await callback.answer()
        if not self.chat_id:
            await callback.message.edit_text("⚠️ Спочатку оберіть групу.", parse_mode="html")
            return
        group_id = int(self.chat_id) if isinstance(self.chat_id, tuple) else self.chat_id
        await self._ensure_admin_panel_group_row_async(
            int(group_id),
            int(self.group_creator_id or (callback.from_user.id if callback.from_user else BOT_OWNER_ID)),
        )
        enabled, disabled, _ = get_group_buff_settings(group_id)
        text = (
            "⚙️ <b>Налаштування групи</b>\n\n"
            f"📂 Група: <code>{group_id}</code>\n\n"
            "<b>Бафи в грі:</b> " + (" Ввімкнено" if enabled else " Вимкнено") + "\n"
            "Якщо вимкнено - жоден баф не працює в цій групі.\n\n"
            "Нижче можна вимкнути окремі бафи."
        )
        text = emoji_to_premium(text)
        builder = InlineKeyboardBuilder()
        builder.button(
            text=(" Вимкнути всі бафи" if enabled else " Ввімкнути бафи"),
            callback_data="group_settings_buffs_toggle",
        )
        builder.button(text="📦 Конкретні бафи", callback_data="group_settings_buffs_list")
        builder.button(text="🎭 Тематичні налаштування", callback_data="group_settings_themes")
        builder.add(_icon_button("Назад", "go_to_main_menu", "⬅️"))
        builder.adjust(1)
        try:
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
        except Exception:
            await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="html")

    async def group_settings_buffs_toggle_callback(self, callback: CallbackQuery):
        """Перемикання: бафи в групі ввімкнені / вимкнені."""
        if callback.from_user:
            self._apply_user_group_context(callback.from_user.id)
        await callback.answer()
        if not self.chat_id:
            return
        group_id = int(self.chat_id) if isinstance(self.chat_id, tuple) else self.chat_id
        enabled, _, _ = get_group_buff_settings(group_id)
        set_group_buffs_enabled(group_id, not enabled)
        await self.group_settings_callback(callback)

    async def group_settings_themes_callback(self, callback: CallbackQuery):
        """Окреме меню для тематичних налаштувань (ролі, голосування, нічні цілі, мовчанка)."""
        if callback.from_user:
            self._apply_user_group_context(callback.from_user.id)
        await callback.answer()
        if not self.chat_id:
            await callback.message.edit_text("⚠️ Спочатку оберіть групу.", parse_mode="html")
            return
        group_id = int(self.chat_id) if isinstance(self.chat_id, tuple) else self.chat_id
        await self._ensure_admin_panel_group_row_async(
            int(group_id),
            int(self.group_creator_id or (callback.from_user.id if callback.from_user else BOT_OWNER_ID)),
        )
        row = await _db_fetchone_async(
            "SELECT hide_dead_roles, hide_killer_roles, secret_voting, show_night_targets, allow_friendly_fire, "
            "silence_dead_players_enabled, silence_non_players_enabled, allow_skip_night_action, afk_auto_choice_enabled, "
            "duels_enabled "
            "FROM admin_panel WHERE group_id = %s LIMIT 1",
            (group_id,),
        )
        row = row or (False, False, False, False, False, True, True, False, False, False)
        hide_dead_roles = bool(row[0]) if row[0] is not None else False
        hide_killer_roles = bool(row[1]) if row[1] is not None else False
        secret_voting = bool(row[2]) if row[2] is not None else False
        show_night_targets = bool(row[3]) if row[3] is not None else False
        allow_friendly_fire = bool(row[4]) if len(row) > 4 and row[4] is not None else False
        silence_dead_players_enabled = bool(row[5]) if len(row) > 5 and row[5] is not None else True
        silence_non_players_enabled = bool(row[6]) if len(row) > 6 and row[6] is not None else True
        allow_skip_night_action = bool(row[7]) if len(row) > 7 and row[7] is not None else False
        afk_auto_choice_enabled = bool(row[8]) if len(row) > 8 and row[8] is not None else False
        duels_enabled = bool(row[9]) if len(row) > 9 and row[9] is not None else False
        text = (
            "🎭 <b>Тематичні налаштування</b>\n\n"
            f"📂 Група: <code>{group_id}</code>\n\n"
            f"• Ролі померлих: {' приховані' if hide_dead_roles else ' видимі'}\n"
            f"• Ролі виконавців вбивства: {' приховані' if hide_killer_roles else ' видимі'}\n"
            f"• Таємне голосування: {' увімкнено' if secret_voting else ' вимкнено'}\n"
            f"• Видно нічні цілі (хто до кого ходить): {' увімкнено' if show_night_targets else ' вимкнено'}\n"
            f"• Вбивство союзників: {' увімкнено' if allow_friendly_fire else ' вимкнено'}\n"
            f"• Пропуск нічної дії: {' дозволено ' if allow_skip_night_action else ' вимкнено '}\n"
            f"• AFK-автовибір: {' увімкнено' if afk_auto_choice_enabled else ' вимкнено'}\n"
            f"• Дуелі (Мирний з 2 патронами): {' увімкнено' if duels_enabled else ' вимкнено'}\n\n"
            f"🔇 <b>Мовчанка</b>\n"
            f"• Для мертвих: {' увімкнено' if silence_dead_players_enabled else ' вимкнено'}\n"
            f"• Для не-гравців: {' увімкнено' if silence_non_players_enabled else ' вимкнено'}"
        )
        text = emoji_to_premium(text)
        builder = InlineKeyboardBuilder()
        builder.button(
            text="💀 Ролі померлих",
            callback_data="group_settings_theme:hide_dead_roles",
        )
        builder.button(
            text="🔫 Ролі вбивць",
            callback_data="group_settings_theme:hide_killer_roles",
        )
        builder.button(
            text="🗳 Таємне голосування",
            callback_data="group_settings_theme:secret_voting",
        )
        builder.button(
            text="🌙 Нічні цілі",
            callback_data="group_settings_theme:show_night_targets",
        )
        builder.button(
            text="🔁 Вбивство союзників",
            callback_data="group_settings_theme:allow_friendly_fire",
        )
        builder.button(
            text="⏭ Пропуск нічної дії",
            callback_data="group_settings_theme:allow_skip_night_action",
        )
        builder.button(
            text="🤖 AFK-автовибір",
            callback_data="group_settings_theme:afk_auto_choice_enabled",
        )
        builder.button(
            text="⚔️ Дуелі",
            callback_data="group_settings_theme:duels_enabled",
        )
        builder.button(
            text="☠️ Мовчанка: мертві",
            callback_data="group_settings_theme:silence_dead_players_enabled",
        )
        builder.button(
            text="🚫 Мовчанка: не-гравці",
            callback_data="group_settings_theme:silence_non_players_enabled",
        )
        builder.add(_icon_button("Назад", "group_settings", "⬅️"))
        builder.adjust(1)
        try:
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
        except TelegramBadRequest as e:
            # Не створюємо дубль-повідомлення, якщо Telegram каже "нічого не змінилось"
            if "message is not modified" in str(e).lower():
                return
            await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="html")
        except Exception:
            await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="html")

    async def group_settings_buffs_list_callback(self, callback: CallbackQuery):
        """Список бафів: увімкнено/вимкнено в групі (конкретні)."""
        if callback.from_user:
            self._apply_user_group_context(callback.from_user.id)
        await callback.answer()
        if not self.chat_id:
            return
        group_id = int(self.chat_id) if isinstance(self.chat_id, tuple) else self.chat_id
        enabled, disabled, _ = get_group_buff_settings(group_id)
        text = (
            "📦 <b>Конкретні бафи</b>\n\n"
            + ("Бафи в грі зараз ввімкнені. Нижче можна вимкнути окремі предмети." if enabled else "⚠️ Усі бафи вимкнені для групи - спочатку увімкніть їх у «Налаштування групи».")
        )
        text = emoji_to_premium(text)
        builder = InlineKeyboardBuilder()
        for buff_id, item in (ITEMS or {}).items():
            name = getattr(item, "name", buff_id)
            emoji = getattr(item, "emoji", "📦")
            is_disabled = buff_id in disabled
            label = f"{'🚫' if is_disabled else ''} {emoji} {name}"
            builder.button(text=label, callback_data=f"group_settings_buff_toggle:{buff_id}")
        builder.add(_icon_button("Назад", "group_settings", "⬅️"))
        builder.adjust(1)
        try:
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
        except Exception:
            await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="html")

    async def group_settings_buff_toggle_callback(self, callback: CallbackQuery):
        """Вмикає/вимикає один баф у групі."""
        if callback.from_user:
            self._apply_user_group_context(callback.from_user.id)
        data = (callback.data or "").strip()
        if not data.startswith("group_settings_buff_toggle:"):
            await callback.answer()
            return
        buff_id = data.split(":", 1)[1].strip()
        if not self.chat_id or not buff_id:
            await callback.answer("Помилка.", show_alert=True)
            return
        group_id = int(self.chat_id) if isinstance(self.chat_id, tuple) else self.chat_id
        now_disabled = toggle_group_buff_disabled(group_id, buff_id)
        item = (ITEMS or {}).get(buff_id)
        name = getattr(item, "name", buff_id) if item else buff_id
        await callback.answer(f"{'Вимкнено' if now_disabled else 'Ввімкнено'}: {name}", show_alert=True)
        await self.group_settings_buffs_list_callback(callback)

    async def group_settings_back_callback(self, callback: CallbackQuery):
        """Повернутися з налаштувань групи до головного меню."""
        if callback.from_user:
            self._apply_user_group_context(callback.from_user.id)
        await callback.answer()
        await self.show_main_menu(callback, tab=None)

    async def group_settings_theme_toggle_callback(self, callback: CallbackQuery):
        """Перемикає одне з тематичних налаштувань (ролі померлих / вбивць / таємне голосування / нічні цілі)."""
        if callback.from_user:
            self._apply_user_group_context(callback.from_user.id)
        if not self.chat_id:
            await callback.answer("⚠️ Спочатку оберіть групу.", show_alert=True)
            return
        data = (callback.data or "").strip()
        if not data.startswith("group_settings_theme:"):
            await callback.answer()
            return
        key = data.split(":", 1)[1]
        group_id = int(self.chat_id) if isinstance(self.chat_id, tuple) else self.chat_id
        await self._ensure_admin_panel_group_row_async(
            int(group_id),
            int(self.group_creator_id or (callback.from_user.id if callback.from_user else BOT_OWNER_ID)),
        )
        column_map = {
            "hide_dead_roles": "hide_dead_roles",
            "hide_killer_roles": "hide_killer_roles",
            "secret_voting": "secret_voting",
            "show_night_targets": "show_night_targets",
            "allow_friendly_fire": "allow_friendly_fire",
            "silence_dead_players_enabled": "silence_dead_players_enabled",
            "silence_non_players_enabled": "silence_non_players_enabled",
            "allow_skip_night_action": "allow_skip_night_action",
            "afk_auto_choice_enabled": "afk_auto_choice_enabled",
            "duels_enabled": "duels_enabled",
        }
        column = column_map.get(key)
        if not column:
            await callback.answer("Невідомий параметр.", show_alert=True)
            return
        # Інвертуємо поточне значення у всіх записах admin_panel для цієї групи
        row = await _db_fetchone_async(
            f"SELECT {column} FROM admin_panel WHERE group_id = %s LIMIT 1",
            (group_id,),
        )
        current = bool(row[0]) if row and row[0] is not None else False
        new_value = not current
        await _db_execute_commit_async(
            f"UPDATE admin_panel SET {column} = %s WHERE group_id = %s",
            (new_value, group_id),
        )
        await callback.answer(" Увімкнено" if new_value else "⛔ Вимкнено")
        # Після перемикання лишаємось у меню тематичних налаштувань
        await self.group_settings_themes_callback(callback)

    def _backup_group_id(self):
        """Повертає int group_id для поточної групи."""
        if not self.chat_id or self.chat_id == 0:
            return None
        return int(self.chat_id[0]) if isinstance(self.chat_id, tuple) else int(self.chat_id)

    def _backup_creator_id(self, callback: CallbackQuery):
        return self.group_creator_id or (callback.from_user.id if callback and callback.from_user else 0)

    async def _ensure_admin_panel_group_row_async(self, group_id: int, fallback_creator_id: int) -> None:
        """
        Гарантує наявність рядка admin_panel для group_id.
        Без цього тумблери тематичних налаштувань можуть не зберігатися.
        """
        try:
            existing = await _db_fetchone_async(
                "SELECT 1 FROM admin_panel WHERE group_id = %s LIMIT 1",
                (group_id,),
            )
            if existing:
                return
            creator_id = int(fallback_creator_id) if fallback_creator_id else int(BOT_OWNER_ID)
            await _db_execute_commit_async(
                "INSERT INTO admin_panel (creator_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (creator_id, group_id),
            )
        except Exception:
            pass

    def _build_backup_menu(self, creator_id: int, group_id: int):
        """Повертає (text, builder) для меню бекапів."""
        backups = get_role_backups(creator_id, group_id)
        can_save = len(backups) < MAX_ROLE_BACKUPS_PER_GROUP
        builder = InlineKeyboardBuilder()
        if can_save:
            builder.row(_icon_button("Зберегти поточний бекап", "backup_save", "➕"))
        for row in backups:
            bid = row[0]
            created_at = row[1]
            name = row[2] if len(row) > 2 else None
            dt = created_at.strftime("%d.%m.%Y %H:%M") if hasattr(created_at, "strftime") else str(created_at)[:16]
            label = (name or dt).strip() or dt
            builder.row(
                _icon_button(f"{label[:30]} → Відновити", f"backup_restore:{bid}", "🔄"),
                _icon_button("Назву", f"backup_rename:{bid}", "📝"),
                _icon_button("Видалити", f"backup_delete:{bid}", "❌"),
            )
        builder.add(_icon_button("Назад", "backup_back", "⬅️"))
        text = (
            "📋 <b>Бекапи налаштувань ролей</b>\n\n"
            f"Збережено бекапів: <b>{len(backups)}</b> / {MAX_ROLE_BACKUPS_PER_GROUP}\n\n"
            "• <b>➕ Зберегти бекап</b> - зберегти поточний стан усіх ролей групи.\n"
            "• <b>🔄 Відновити</b> - замінити поточні ролі на збережений стан.\n"
            "• <b>📝 Назву</b> - змінити назву бекапу.\n"
            "• <b>❌ Видалити</b> - видалити бекап."
        )
        return text, builder

    async def admin_logs_callback(self, callback: CallbackQuery):
        """Показати короткий лог дій адмінів (доступно тільки для тих, хто має права на конструктор)."""
        await callback.answer()
        if not self.chat_id or self.chat_id == 0:
            await callback.message.answer(" Спочатку обери групу в конструкторі івентів.", parse_mode="html")
            return
        chat_id = int(self.chat_id[0]) if isinstance(self.chat_id, tuple) else int(self.chat_id)
        user_id = callback.from_user.id if callback.from_user else 0
        # Використовуємо той самий чек, що й для редагування ролей (потрібна активна підписка творця)
        if not self._can_edit_roles(user_id):
            await callback.answer("Недостатньо прав для перегляду логів.", show_alert=True)
            return
        entries = list(self.admin_logs.get(chat_id, []))
        if not entries:
            text = "📜 <b>Логи дій</b>\n\nПоки що немає записів."
        else:
            joined = "\n".join(entries[:30])
            text = "📜 <b>Логи дій адмінів</b> (останні до 40):\n\n" + joined
        try:
            await callback.message.answer(emoji_to_premium(text), parse_mode="html")
        except Exception:
            pass

    async def backup_menu_callback(self, callback: CallbackQuery):
        """Меню бекапів: зберегти, список бекапів (відновити/назву/видалити), назад."""
        await callback.answer()
        group_id = self._backup_group_id()
        if not group_id:
            await callback.message.edit_text(
                " Спочатку обери групу в конструкторі івентів.",
                parse_mode="html",
            )
            return
        creator_id = self._backup_creator_id(callback)
        text, builder = self._build_backup_menu(creator_id, group_id)
        try:
            await callback.message.edit_text(
                emoji_to_premium(text), reply_markup=builder.as_markup(), parse_mode="html"
            )
        except Exception:
            await callback.message.answer(
                emoji_to_premium(text), reply_markup=builder.as_markup(), parse_mode="html"
            )

    async def backup_save_callback(self, callback: CallbackQuery):
        """Зберегти поточний стан ролей групи в бекап."""
        await callback.answer()
        group_id = self._backup_group_id()
        if not group_id:
            await callback.answer(" Обери групу.", show_alert=True)
            return
        creator_id = self._backup_creator_id(callback)
        all_roles = ChatRoleRegistry.get_all_roles_for_chat(creator_id, group_id)
        snapshot = {"roles": [r.to_dict() for r in all_roles]}
        backup_id = create_role_backup(creator_id, group_id, snapshot)
        self._log_admin_action(group_id, callback.from_user.id if callback.from_user else 0, f"backup_save id={backup_id}, roles={len(all_roles)}")
        await callback.message.edit_text(
            emoji_to_premium(
                "✨ <b>Бекап збережено!</b>\n\n"
                f"ID бекапу: <code>{backup_id}</code>\n"
                f"Ролей у бекапі: <b>{len(all_roles)}</b>"
            ),
            parse_mode="html",
        )
        await asyncio.sleep(2)
        await self.backup_menu_callback(callback)

    async def backup_back_callback(self, callback: CallbackQuery):
        """Повернутися з меню бекапів до головного меню."""
        await callback.answer()
        current_tab = getattr(self, "current_tab", "standard")
        await self.show_main_menu(callback, tab=current_tab)

    async def backup_restore_callback(self, callback: CallbackQuery):
        """Відновити ролі групи з обраного бекапу."""
        data = (callback.data or "").strip()
        if not data.startswith("backup_restore:"):
            await callback.answer()
            return
        try:
            backup_id = int(data.split(":", 1)[1].strip())
        except (ValueError, IndexError):
            await callback.answer(" Помилка ID бекапу.", show_alert=True)
            return
        group_id = self._backup_group_id()
        if not group_id:
            await callback.answer(" Обери групу.", show_alert=True)
            return
        creator_id = self._backup_creator_id(callback)
        snapshot = get_role_backup_snapshot(backup_id, creator_id, group_id)
        if not snapshot or "roles" not in snapshot:
            await callback.answer(" Бекап не знайдено.", show_alert=True)
            return
        roles_data = snapshot["roles"]

        # ВАЖЛИВО: бекап НЕ має стирати кастомні ролі.
        # Тому видаляємо/оновлюємо тільки стандартні (is_default=True), а кастомні лишаємо як є.
        try:
            existing = RoleManager.get_all_roles(creator_id, group_id)
            for r in existing:
                if getattr(r, "is_default", False):
                    RoleManager.delete_role(creator_id, group_id, r.name)
        except Exception as e:
            print(f"backup restore delete default roles error: {e}")

        ChatRoleRegistry.clear_chat_cache(group_id)
        restored_defaults = 0
        for rd in roles_data:
            try:
                role = Role.from_dict(rd)
                # Пропускаємо кастомні ролі з бекапу - вони не повинні перезаписувати/стирати поточні
                if not getattr(role, "is_default", False):
                    continue
                role.creator_id = creator_id
                role.group_id = group_id
                RoleManager.save_role(role)
                restored_defaults += 1
            except Exception as e:
                print(f"backup restore role error: {e}")
        ChatRoleRegistry.clear_chat_cache(group_id)
        self._log_admin_action(group_id, callback.from_user.id if callback.from_user else 0, f"backup_restore id={backup_id}, defaults_restored={restored_defaults}, custom_kept=1")
        await callback.answer(" Ролі відновлено з бекапу!", show_alert=True)
        await self.backup_menu_callback(callback)

    async def backup_delete_callback(self, callback: CallbackQuery):
        """Видалити обраний бекап."""
        data = (callback.data or "").strip()
        if not data.startswith("backup_delete:"):
            await callback.answer()
            return
        try:
            backup_id = int(data.split(":", 1)[1].strip())
        except (ValueError, IndexError):
            await callback.answer(" Помилка ID бекапу.", show_alert=True)
            return
        group_id = self._backup_group_id()
        if not group_id:
            await callback.answer(" Обери групу.", show_alert=True)
            return
        creator_id = self._backup_creator_id(callback)
        deleted = delete_role_backup(backup_id, creator_id, group_id)
        if deleted:
            self._log_admin_action(group_id, callback.from_user.id if callback.from_user else 0, f"backup_delete id={backup_id}")
            await callback.answer(" Бекап видалено.", show_alert=True)
        else:
            await callback.answer(" Бекап не знайдено.", show_alert=True)
        await self.backup_menu_callback(callback)

    async def backup_rename_callback(self, callback: CallbackQuery):
        """Запитати нову назву бекапу та зберегти контекст."""
        data = (callback.data or "").strip()
        if not data.startswith("backup_rename:"):
            await callback.answer()
            return
        try:
            backup_id = int(data.split(":", 1)[1].strip())
        except (ValueError, IndexError):
            await callback.answer(" Помилка ID бекапу.", show_alert=True)
            return
        group_id = self._backup_group_id()
        if not group_id:
            await callback.answer(" Обери групу.", show_alert=True)
            return
        creator_id = self._backup_creator_id(callback)
        user_id = callback.from_user.id if callback.from_user else 0
        self._backup_rename_pending[user_id] = {
            "backup_id": backup_id,
            "creator_id": creator_id,
            "group_id": group_id,
        }
        await callback.answer()
        await callback.message.edit_text(
            emoji_to_premium(
                "📝 <b>Зміна назви бекапу</b>\n\nНапиши нову назву для цього бекапу:"
            ),
            parse_mode="html",
        )

    async def backup_rename_message_handler(self, message: Message):
        """Обробити введену назву бекапу."""
        user_id = message.from_user.id if message.from_user else 0
        ctx = self._backup_rename_pending.pop(user_id, None)
        if not ctx:
            return
        new_name = (message.text or "").strip()
        if not new_name:
            self._backup_rename_pending[user_id] = ctx
            await message.answer(" Назва не може бути порожньою. Напиши назву ще раз.")
            return
        ok = update_role_backup_name(
            ctx["backup_id"], ctx["creator_id"], ctx["group_id"], new_name[:255]
        )
        if ok:
            self._log_admin_action(ctx["group_id"], message.from_user.id if message.from_user else 0, f"backup_rename id={ctx['backup_id']} name='{new_name[:30]}'")
            await message.answer(f" Назву бекапу змінено на: <b>{new_name[:100]}</b>", parse_mode="html")
        else:
            await message.answer(" Бекап не знайдено або помилка оновлення.")
        text, builder = self._build_backup_menu(ctx["creator_id"], ctx["group_id"])
        await message.answer(
            emoji_to_premium(text), reply_markup=builder.as_markup(), parse_mode="html"
        )

    async def is_input_chat_id_handler(self, message: Message, bot: Bot):
        """Handler for initial group ID input"""
        if message.chat.type != "private":
            return

        parsed = _parse_group_id(message.text or "")
        if parsed is None:
            await message.answer(
                " <b>Невірний формат ID</b> \n\n"
                "ID групи - це число з мінусом (наприклад: <code>-1234567890</code>).\n\n"
                "💡 Скопіюй ID командою <code>/id</code> у групі або переконайся, що вставив число з мінусом.",
                parse_mode="html"
            )
            return

        try:
            self.chat_id = parsed

            if self.chat_id >= 0:
                await message.answer(
                    " <b>Невірний формат ID</b> \n\n"
                    "ID групи <b>завжди</b> з мінусом (наприклад: <code>-1234567890</code>).\n\n"
                    "💡 Скопіюй ID командою <code>/id</code> у групі - там буде мінус.",
                    parse_mode="html"
                )
                return

            # Verify user is creator
            chat_member = await bot.get_chat_member(self.chat_id, message.from_user.id)
            status = chat_member.status

            if status == ChatMemberStatus.CREATOR:
                await _db_execute_commit_async(
                    "INSERT INTO admin_panel (creator_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (message.from_user.id, self.chat_id),
                )

                chat = await bot.get_chat(chat_id=self.chat_id)
                await message.answer(
                    " <b>Реєстрація успішна!</b> \n\n"
                    f"🎉 Ти зареєстрований як власник групи:\n"
                    f"📁 <b>{chat.title}</b>\n\n"
                    f"Тепер ти можеш налаштовувати ролі для цієї групи!\n\n"
                    f"👉 Надішли <code>/construct_event</code> ще раз, щоб продовжити.",
                    parse_mode="html"
                )
                self.is_input_chat_id = False
                self.awaiting_chat_id_user_id = None
            else:
                await message.answer(
                    " <b>Доступ заборонено</b> \n\n"
                    "Ти не є <b>власником</b> цієї групи.\n\n"
                    "💡 <i>Налаштовувати ролі може тільки той, хто створив групу.</i>",
                    parse_mode="html"
                )
                self.chat_id = 0
                self.is_input_chat_id = False
                self.awaiting_chat_id_user_id = None

        except TelegramBadRequest as e:
            await message.answer(
                " <b>Помилка доступу</b> \n\n"
                f"Такої групи не існує або бот не має до неї доступу.\n\n"
                f"<code>{str(e)}</code>\n\n"
                f"💡 <i>Переконайся, що:\n"
                f"• Бот додано до групи\n"
                f"• ID правильний\n"
                f"• Група активна</i>",
                parse_mode="html"
            )
        except (ValueError, TypeError):
            await message.answer(
                " <b>Невірний формат</b> \n\n"
                "Надішли ID групи - число з мінусом, наприклад: <code>-1234567890</code>\n\n"
                "💡 Команда <code>/id</code> у групі покаже правильний ID.",
                parse_mode="html"
            )


    async def doctor_callback_query(self, callback: CallbackQuery):
        """Handler for doctor role"""
        await self.edit_role_menu(callback, "Лікар", "doctor")

    async def all_capone_callback_query(self, callback: CallbackQuery):
        """Handler for all_capone role"""
        await self.edit_role_menu(callback, "Аль Капоне", "all_capone")

    async def civilian_callback_query(self, callback: CallbackQuery):
        """Handler for civilian role"""
        await self.edit_role_menu(callback, "Мирний житель", "civilian")

    async def sheriff_callback_query(self, callback: CallbackQuery):
        """Handler for sheriff role"""
        await self.edit_role_menu(callback, "Комісар Каттані", "sheriff")

    async def prostitute_callback_query(self, callback: CallbackQuery):
        """Handler for prostitute role"""
        await self.edit_role_menu(callback, "Коханка", "prostitute")

    async def guardian_angel_callback_query(self, callback: CallbackQuery):
        """Handler for guardian angel role"""
        await self.edit_role_menu(callback, "Тілоохоронець", "guardian_angel")

    async def maniac_callback_query(self, callback: CallbackQuery):
        """Handler for maniac role"""
        await self.edit_role_menu(callback, "Маніяк", "maniac")

    async def sadistic_doctor_callback_query(self, callback: CallbackQuery):
        """Handler for sadistic doctor role"""
        await self.edit_role_menu(callback, "Доктор-садист", "sadistic_doctor")

    def custom_role_callback(self, role_name: str):
        """Handler for custom role selection"""
        async def handler(callback: CallbackQuery):
            # Get role using ChatRoleRegistry (ensures chat scoping)
            creator_key = self.group_creator_id or callback.from_user.id
            role = ChatRoleRegistry.get_role_for_chat(creator_key, self.chat_id, role_name)
            if not role:
                await callback.answer("Роль не знайдена!", show_alert=True)
                return
            
            self.current_role = role
            self.name_of_role = role_name
            self.role_in_db = "custom_role"
            await self.show_role_edit_menu(callback, role)
        return handler


    async def edit_role_menu(self, callback: CallbackQuery, display_name: str, role_db_name: str):
        """Show edit menu for a role"""
        self.name_of_role = display_name
        self.role_in_db = role_db_name
        
        # Map role_db_name to default role names for backward compatibility
        role_db_to_name_map = {
            "doctor": "Лікар",
            "all_capone": "Аль Капоне",
            "civilian": "Мирний житель",
            "sheriff": "Шериф",
            "prostitute": "Повія",
            "guardian_angel": "Ангел-охоронець",
            "maniac": "Маніяк",
            "sadistic_doctor": "Доктор-садист"
        }
        
        # Ensure default roles are initialized for this chat
        creator_key = self.group_creator_id or callback.from_user.id
        ChatRoleRegistry.ensure_default_roles_for_chat(creator_key, self.chat_id)
        
        # Try to get role from ChatRoleRegistry (should work for all default roles)
        role = ChatRoleRegistry.get_role_for_chat(creator_key, self.chat_id, display_name)
        
        if not role:
            # Fallback: Get from admin_panel only for old 3 roles (backward compatibility)
            if role_db_name in ["doctor", "all_capone", "civilian"]:
                try:
                        result = await _db_fetchone_async(
                            f"SELECT {role_db_name}, {role_db_name}_text FROM admin_panel WHERE creator_id = %s AND group_id = %s",
                            (callback.from_user.id, self.chat_id),
                        )
                    
                        if result:
                            default_roles = create_default_roles()
                            role_name = role_db_to_name_map.get(role_db_name)
                            if role_name and role_name in default_roles:
                                role = default_roles[role_name]
                                role.name = result[0] or role.name
                                role.description = result[1] or role.description
                                role.creator_id = callback.from_user.id
                                role.group_id = self.chat_id
                                # Save updated role to new system
                                RoleManager.save_role(role)
                except Exception as e:
                        print(f"Error loading role from admin_panel: {e}")
            
            # If still not found, try ChatRoleRegistry again
            if not role:
                role = ChatRoleRegistry.get_role_for_chat(creator_key, self.chat_id, display_name)
        
        # If still not found, show error
        if not role:
            await callback.answer(f" Роль «{display_name}» не знайдена!", show_alert=True)
            return
        
        self.current_role = role
        await self.show_role_edit_menu(callback, role)


    async def show_role_edit_menu(self, callback: CallbackQuery, role: Optional[Role]):
        """Show role editing menu. Завжди перезавантажуємо роль з БД, щоб показати актуальні min_players та enabled."""
        # Перезавантажити роль з БД, щоб відобразити збережені зміни (мін. гравців тощо)
        if self.chat_id and self.name_of_role and role:
            creator_key = self.group_creator_id or (callback.from_user.id if callback and callback.from_user else 0)
            if creator_key:
                group_id = int(self.chat_id) if isinstance(self.chat_id, tuple) else self.chat_id
                fresh_role = ChatRoleRegistry.get_role_for_chat(creator_key, group_id, self.name_of_role)
                if fresh_role:
                    role = fresh_role
                    self.current_role = role
        role_name = role.name if role else "N/A"
        # Клоун та Диявол вимкнені для груп без активної підписки (купленої або виданої) - при відкритті примусово вимикаємо і зберігаємо
        if role and role.name in ("Клоун", "Диявол"):
            creator_id = self.group_creator_id or (callback.from_user.id if callback.from_user else 0)
            if creator_id and not ShopManager.is_subscription_active(creator_id):
                if getattr(role, "enabled", True):
                    role.enabled = False
                    if self.group_creator_id:
                        role.creator_id = self.group_creator_id
                    role.group_id = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
                    RoleManager.save_role(role)
                    ChatRoleRegistry.clear_chat_cache(self.chat_id)
        role_desc = role.description if role else "N/A"
        role_min_players = role.min_players if role and hasattr(role, "min_players") else 1
        role_enabled = role.enabled if role and hasattr(role, "enabled") else True
        alignment = getattr(role, "alignment", RoleAlignment.GOOD)
        alignment_text = {"good": "🟢 Мирна", "evil": "🔴 Зла", "neutral": "🟡 Нейтральна"}.get(
            alignment.value if hasattr(alignment, "value") else str(alignment), "🟢 Мирна"
        )
        abilities_text = ""
        
        custom_night_msg = ""
        if role and getattr(role, "custom_data", None):
            custom_night_msg = role.custom_data.get("night_target_message", "")

        if role and role.abilities:
            abilities_text = f"\n\n⚔️ Поточні здатності ({len(role.abilities)}):\n"
            for i, ab in enumerate(role.abilities, 1):
                abilities_text += f"{i}. {ab.name} ({self._ability_type_ua(ab.ability_type)})\n"

        builder = InlineKeyboardBuilder()
        builder.button(text="✏️ Змінити назву ролі", callback_data="name_of_role")
        builder.add(_icon_button("Змінити опис ролі", "description_of_role", "📝"))
        if self.role_in_db == "custom_role":
            builder.button(text=f"🏷️ Тип ролі: {alignment_text}", callback_data="change_role_alignment")
            builder.button(text="🖼 Картка ролі (завантажити/оновити)", callback_data="upload_role_card_custom")
            builder.button(text="✉️ Текст нічного візиту", callback_data="edit_night_message")
        builder.add(_icon_button("Мін. гравців для ролі", "min_players", "👥"))
        if role and role.name == "Мафія":
            builder.button(text="⚖️ Кількість мафії за гравцями", callback_data="mafia_scale")
        builder.button(
            text=(" Роль увімкнена" if role_enabled else "🚫 Роль вимкнена"),
            callback_data="toggle_role_enabled"
        )
        builder.button(text="⚔️ Керувати здатностями", callback_data="abilities")
        
        if self.role_in_db == "custom_role":
            builder.button(text="🗑️ Видалити роль", callback_data=f"delete_role_{self.name_of_role}")
        
        builder.add(_icon_button("Повернутися до ролей", "tab_standard", "⬅️"))
        builder.adjust(1)

        # Register handlers
        self.router_construct_event.callback_query.register(self.name_of_role_callback(), F.data == "name_of_role")
        self.router_construct_event.callback_query.register(self.description_of_role_callback(), F.data == "description_of_role")
        self.router_construct_event.callback_query.register(self.min_players_callback(), F.data == "min_players")
        self.router_construct_event.callback_query.register(self.mafia_scale_callback(), F.data == "mafia_scale")
        self.router_construct_event.callback_query.register(self.toggle_role_enabled_callback(), F.data == "toggle_role_enabled")
        self.router_construct_event.callback_query.register(self.abilities_callback(), F.data == "abilities")
        if self.role_in_db == "custom_role":
            self.router_construct_event.callback_query.register(
                self.change_role_alignment_callback(),
                F.data == "change_role_alignment"
            )
            self.router_construct_event.callback_query.register(
                self.upload_role_card_custom_callback(),
                F.data == "upload_role_card_custom"
            )
            self.router_construct_event.callback_query.register(
                self.delete_role_handler(self.name_of_role),
                F.data == f"delete_role_{self.name_of_role}"
            )
            self.router_construct_event.callback_query.register(
                self.edit_night_message_callback(),
                F.data == "edit_night_message"
            )

        # Determine role icon
        role_icons = {
            "Лікар": "💊",
            "Аль Капоне": "🎩",
            "Мирний житель": "🧍",
            "Шериф": "👮",
            "Повія": "💋",
            "Ангел-охоронець": "😇",
            "Маніяк": "🔪",
            "Доктор-садист": "⚕️"
        }
        role_icon = role_icons.get(self.name_of_role, "🎭")
        
        role_type = "🌟 Стандартна роль" if self.role_in_db != "custom_role" else "🎨 Кастомна роль"
        
        mafia_scale_text = ""
        if role and role.name == "Мафія":
            mafia_scale = self._extract_mafia_scale_from_role(role)
            mafia_scale_text = (
                "\n📈 <b>Масштаб мафії:</b> "
                f"<code>1-10→{mafia_scale['up_to_10']}, 11-15→{mafia_scale['from_11']}, "
                f"16-22→{mafia_scale['from_16']}, 23+→{mafia_scale['from_23']}</code>"
            )

        text = (
            f"{role_icon} <b>Редагування ролі</b> {role_icon}\n\n"
            f"📋 <b>Роль:</b> «{self.name_of_role}»\n"
            f"🏷️ <b>Тип ролі:</b> {alignment_text}\n"
            f"📂 <b>Категорія:</b> {role_type}\n\n"
            f"📝 <b>Поточна назва:</b> <code>{role_name}</code>\n"
            f"📄 <b>Поточний опис:</b> <i>{role_desc[:100]}{'...' if len(role_desc) > 100 else ''}</i>\n"
            f"👥 <b>Мін. гравців:</b> <code>{role_min_players}</code>\n"
            f" <b>Увімкнена:</b> <code>{'так' if role_enabled else 'ні'}</code>"
            f"{mafia_scale_text}{abilities_text}"
        )
        if self.role_in_db == "custom_role":
            preview = custom_night_msg[:80] + ("..." if len(custom_night_msg) > 80 else "")
            text += f"\n✉️ <b>Нічне повідомлення цілі:</b> <i>{preview or '- не задано -'}</i>"
        text += "\n\n⬇️ <b>Виберіть, що хочете змінити:</b> ⬇️"

        await callback.message.edit_text(emoji_to_premium(text), reply_markup=builder.as_markup(), parse_mode="html")


    # Role creation flow
    async def create_new_role_callback(self, callback: CallbackQuery):
        """Start creating a new role"""
        # #region agent log
        _log_debug('debug-session', 'run1', 'CR0', 'construct_event.py:create_new_role_callback', 'Create new role clicked', {
            'user_id': callback.from_user.id,
            'chat_id': self.chat_id,
            'is_creating_new_role': self.is_creating_new_role
        })
        # #endregion
        if not self.chat_id or self.chat_id == 0:
            await callback.answer("Помилка: група не обрана! Спочатку обери групу.", show_alert=True)
            return
        if not self._can_edit_roles(callback.from_user.id):
            await callback.answer(
                " Створення нових ролей доступне лише з підпискою.\n\n"
                "Купити підписку: /buy_subscription",
                show_alert=True
            )
            return
        
        builder = InlineKeyboardBuilder()
        builder.add(_icon_button("Назад", "go_to_main_menu", "⬅️"))
        
        await callback.message.edit_text(
            emoji_to_premium(
                "✨ <b>Створення нової ролі</b> ✨\n\n"
                "🎭 Придумай унікальну назву для своєї ролі!\n\n"
                "💡 <b>Приклади назв:</b>\n"
                "• Детектив 🕵️\n"
                "• Снайпер 🎯\n"
                "• Мер 🏛️\n"
                "• Вбивця-Доктор ⚔️⚕️\n"
                "• Інші креативні варіанти...\n\n"
                "⏳ <i>Очікую назву ролі...</i>"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        # Скидаємо потенційно конфліктні "очікування", щоб ввід назви гарантовано обробився.
        self.is_input_new_role_description = False
        self.awaiting_role_description_user_id = None
        self.is_input_min_players = False
        self.awaiting_min_players_user_id = None
        self.is_input_mafia_scale = False
        self.awaiting_mafia_scale_user_id = None
        self._min_players_pending.pop(callback.from_user.id, None)
        self._mafia_scale_pending.pop(callback.from_user.id, None)

        self.is_input_new_role_name = True
        self.awaiting_role_name_user_id = callback.from_user.id
        self.is_creating_new_role = True
        self.current_role = None

    def edit_night_message_callback(self):
        """Почати редагування тексту нічного повідомлення для кастомної ролі."""
        async def handler(callback: CallbackQuery):
            if not self._ensure_current_role(callback):
                await callback.answer("Роль не знайдена!", show_alert=True)
                return
            if self.role_in_db != "custom_role":
                await callback.answer("Нічне повідомлення доступне лише для кастомних ролей.", show_alert=True)
                return

            self.awaiting_night_message_user_id = callback.from_user.id

            current_msg = ""
            if getattr(self.current_role, "custom_data", None):
                current_msg = self.current_role.custom_data.get("night_target_message", "")

            preview = current_msg[:120] + ("..." if len(current_msg) > 120 else "")
            text = (
                f"✉️ <b>Текст нічного візиту</b>\n\n"
                f"🎭 <b>Роль:</b> «{self.current_role.name}»\n\n"
                f"Поточний текст для гравця, до якого приходить роль:\n"
                f"<i>{preview or '- не задано -'}</i>\n\n"
                f"✏️ Надішли новий текст у наступному повідомленні.\n"
                f"Можна використовувати HTML-розмітку (жирний, курсив тощо).\n\n"
                f"Щоб очистити текст і не надсилати повідомлення цілі - надішли один дефіс (-)."
            )
            try:
                await callback.message.edit_text(emoji_to_premium(text), parse_mode="html")
            except Exception:
                try:
                    await callback.message.answer(emoji_to_premium(text), parse_mode="html")
                except Exception:
                    pass
            await callback.answer()

        return handler

    def default_role_callback(self, role_name: str):
        """Open edit menu for default role"""
        async def handler(callback: CallbackQuery):
            await self.edit_role_menu(callback, role_name, role_name)
        return handler

    async def is_input_night_message_handler(self, message: Message):
        """Обробка введення тексту нічного повідомлення для кастомної ролі."""
        if getattr(message.chat, "type", None) != "private":
            self.awaiting_night_message_user_id = None
            return
        user_id = getattr(message.from_user, "id", None) if message.from_user else None
        if not user_id or user_id != self.awaiting_night_message_user_id:
            return
        self.awaiting_night_message_user_id = None

        if not self._ensure_current_role(message):
            await message.answer("Роль не знайдена.", parse_mode="html")
            return
        if self.role_in_db != "custom_role":
            await message.answer("Нічне повідомлення доступне лише для кастомних ролей.", parse_mode="html")
            return

        text = (message.text or "").strip()
        if text == "-":
            new_msg = ""
        else:
            new_msg = text

        if not getattr(self.current_role, "custom_data", None):
            self.current_role.custom_data = {}
        self.current_role.custom_data["night_target_message"] = new_msg

        try:
            RoleManager.save_role(self.current_role)
            ChatRoleRegistry.clear_chat_cache(self.chat_id)
        except Exception as e:
            await message.answer(f"Помилка збереження тексту: {e}", parse_mode="html")
            return

        if new_msg:
            await message.answer("✉️ Текст нічного візиту оновлено.", parse_mode="html")
        else:
            await message.answer("✉️ Нічне повідомлення очищено - тепер цілі нічого не отримуватимуть.", parse_mode="html")


    async def is_input_new_role_name_handler(self, message: Message):
        """Handle new role name input (тільки в приватному чаті)."""
        if getattr(message.chat, "type", None) != "private":
            self.is_input_new_role_name = False
            self.awaiting_role_name_user_id = None
            return
        # #region agent log
        _log_debug('debug-session', 'run1', 'CR0', 'construct_event.py:is_input_new_role_name_handler', 'Role name input received', {
            'is_creating_new_role': self.is_creating_new_role,
            'chat_id': self.chat_id,
            'text_len': len(message.text.strip()) if message.text else 0
        })
        # #endregion
        if not self.is_creating_new_role:
            user_id = getattr(message.from_user, "id", None) if message.from_user else None
            ctx = self._role_name_pending.pop(user_id, None) if user_id is not None else None
            self.is_input_new_role_name = False
            self.awaiting_role_name_user_id = None
            if not ctx:
                await message.answer(
                    "⚠️ Сесію зміни назви ролі перервано або вона вже неактивна.\n\n"
                    "Відкрий <code>/construct_event</code> і знову обери «Змінити назву» в меню ролі.",
                    parse_mode="html",
                )
                return
            if not self._can_edit_roles(message.from_user.id):
                await message.answer(" Зміна назви ролі доступна лише з підпискою.", parse_mode="html")
                return
            new_name = (message.text or "").strip()
            if not new_name:
                self._role_name_pending[user_id] = ctx
                self.is_input_new_role_name = True
                self.awaiting_role_name_user_id = user_id
                await message.answer(" Назва не може бути порожньою!")
                return
            role_name = ctx["role_name"]
            role_in_db = ctx["role_in_db"]
            chat_id = ctx["chat_id"]
            group_creator_id = ctx["group_creator_id"]
            role = ChatRoleRegistry.get_role_for_chat(group_creator_id, chat_id, role_name)
            if not role:
                await message.answer(f" Роль «{role_name}» не знайдена. Відкрий налаштування ролі знову.", parse_mode="html")
                return
            role.name = new_name
            if role_in_db != "custom_role":
                await _db_execute_commit_async(
                    f"UPDATE admin_panel SET {role_in_db} = %s WHERE creator_id = %s AND group_id = %s",
                    (new_name, group_creator_id, chat_id),
                )
            if role_in_db == "custom_role":
                try:
                    role.creator_id = group_creator_id
                    role.group_id = chat_id
                    ChatRoleRegistry.update_role_for_chat(group_creator_id, chat_id, role)
                    ChatRoleRegistry.clear_chat_cache(chat_id)
                except ValueError as e:
                    await message.answer(f" Помилка: {str(e)}", parse_mode="html")
                    return
            else:
                role.creator_id = group_creator_id
                role.group_id = chat_id
                RoleManager.save_role(role)
                ChatRoleRegistry.clear_chat_cache(chat_id)
            await message.answer(
                f" <b>Назву змінено!</b> \n\n"
                f"🎭 <b>Стара назва:</b> «{role_name}»\n"
                f"🎭 <b>Нова назва:</b> «{new_name}»\n\n"
                f"💡 <i>Зміни збережено в базі даних.</i>",
                parse_mode="html"
            )
            await asyncio.sleep(2)
            try:
                await message.delete()
            except Exception:
                pass
            return
        
        if not self.chat_id or self.chat_id == 0:
            await message.answer(" Помилка: група не обрана!")
            self.is_input_new_role_name = False
            self.awaiting_role_name_user_id = None
            self.is_creating_new_role = False
            return
        
        role_name = (message.text or "").strip()
        if not role_name:
            await message.answer(" Назва ролі не може бути порожньою!")
            return
        
        # Check if role already exists in this chat (using ChatRoleRegistry ensures proper scoping)
        group_id_for_query = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
        creator_key = self.group_creator_id or message.from_user.id
        existing_role = ChatRoleRegistry.get_role_for_chat(creator_key, group_id_for_query, role_name)
        if existing_role:
            await message.answer(
                f" Роль з назвою <b>«{role_name}»</b> вже існує!\nОберіть іншу назву.",
                parse_mode="html"
            )
            return
        
        self.name_of_role = role_name
        
        builder = InlineKeyboardBuilder()
        builder.add(_icon_button("Назад", "cancel_role_creation", "⬅️"))
        
        await message.answer(
            emoji_to_premium(
                f" <b>Назву збережено!</b> \n\n"
                f"🎭 <b>Роль:</b> <code>{role_name}</code>\n\n"
                f"📝 Тепер напиши <b>опис</b> для цієї ролі.\n\n"
                f"💡 <i>Цей опис буде показано гравцеві під час гри, коли йому призначать цю роль.\n"
                f"Зроби його цікавим та описовим!</i>\n\n"
                f"⏳ <i>Очікую опис ролі...</i>"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        
        self.is_input_new_role_name = False
        self.awaiting_role_name_user_id = None
        self.is_input_new_role_description = True
        self.awaiting_role_description_user_id = message.from_user.id

        # Register cancel handler
        self.router_construct_event.callback_query.register(
            self.cancel_role_creation_handler(),
            F.data == "cancel_role_creation"
        )


    async def is_input_new_role_description_handler(self, message: Message):
        """Handle new role description input (тільки в приватному чаті)."""
        if getattr(message.chat, "type", None) != "private":
            self.is_input_new_role_description = False
            self.awaiting_role_description_user_id = None
            return
        # #region agent log
        _log_debug('debug-session', 'run1', 'CR0', 'construct_event.py:is_input_new_role_description_handler', 'Role description input received', {
            'is_creating_new_role': self.is_creating_new_role,
            'chat_id': self.chat_id,
            'text_len': len(message.text.strip()) if message.text else 0
        })
        # #endregion
        if not self.is_creating_new_role:
            user_id = getattr(message.from_user, "id", None) if message.from_user else None
            ctx = self._role_description_pending.pop(user_id, None) if user_id is not None else None
            self.is_input_new_role_description = False
            self.awaiting_role_description_user_id = None
            if not ctx:
                await message.answer(
                    "⚠️ Сесію створення/редагування ролі перервано або вона вже неактивна.\n\n"
                    "Відкрий <code>/construct_event</code> і почни з кнопки «Створити ролю» або меню ролі.",
                    parse_mode="html",
                )
                return
            if not self._can_edit_roles(message.from_user.id):
                await message.answer(" Зміна опису ролі доступна лише з підпискою.", parse_mode="html")
                return
            new_description = (message.text or "").strip()
            if not new_description:
                self._role_description_pending[user_id] = ctx
                self.is_input_new_role_description = True
                self.awaiting_role_description_user_id = user_id
                await message.answer(" Опис не може бути порожнім!")
                return
            role_name = ctx["role_name"]
            role_in_db = ctx["role_in_db"]
            chat_id = ctx["chat_id"]
            group_creator_id = ctx["group_creator_id"]
            role = ChatRoleRegistry.get_role_for_chat(group_creator_id, chat_id, role_name)
            if not role:
                await message.answer(f" Роль «{role_name}» не знайдена. Відкрий налаштування ролі знову.", parse_mode="html")
                return
            role.description = new_description
            if role_in_db != "custom_role":
                await _db_execute_commit_async(
                    f"UPDATE admin_panel SET {role_in_db}_text = %s WHERE creator_id = %s AND group_id = %s",
                    (new_description, group_creator_id, chat_id),
                )
            if role_in_db == "custom_role":
                try:
                    role.creator_id = group_creator_id
                    role.group_id = chat_id
                    ChatRoleRegistry.update_role_for_chat(group_creator_id, chat_id, role)
                    ChatRoleRegistry.clear_chat_cache(chat_id)
                except ValueError as e:
                    await message.answer(f" Помилка: {str(e)}", parse_mode="html")
                    return
            else:
                role.creator_id = group_creator_id
                role.group_id = chat_id
                RoleManager.save_role(role)
                ChatRoleRegistry.clear_chat_cache(chat_id)
            await message.answer(
                f" <b>Опис змінено!</b> \n\n"
                f"🎭 <b>Роль:</b> «{role_name}»\n"
                f"📝 <b>Новий опис:</b> <i>{new_description[:100]}{'...' if len(new_description) > 100 else ''}</i>\n\n"
                f"💡 <i>Зміни збережено в базі даних.</i>",
                parse_mode="html"
            )
            await asyncio.sleep(2)
            try:
                await message.delete()
            except Exception:
                pass
            return
        
        if not self.chat_id:
            await message.answer(" Помилка: група не вибрана!")
            self.is_input_new_role_description = False
            self.awaiting_role_description_user_id = None
            self.is_creating_new_role = False
            return
        
        if not (message.text or "").strip():
            await message.answer(
                "Надішли <b>опис ролі</b> одним текстовим повідомленням (не фото/стікером).",
                parse_mode="html",
            )
            return

        role_description = (message.text or "").strip()
        if not role_description:
            await message.answer(" Опис ролі не може бути порожнім!")
            return
        
        # Зберігаємо опис у тимчасовому стані (роль створимо після вибору alignment)
        self._pending_role_description = role_description
        self.is_input_new_role_description = False
        self.awaiting_role_description_user_id = None
        
        # Крок вибору: мирна / зла / нейтральна
        builder = InlineKeyboardBuilder()
        builder.button(text="🟢 Мирна (на стороні мирних)", callback_data="role_align_good")
        builder.button(text="🔴 Зла (мафія / зло)", callback_data="role_align_evil")
        builder.button(text="🟡 Нейтральна (грає за себе)", callback_data="role_align_neutral")
        builder.add(_icon_button("Назад", "cancel_role_creation", "⬅️"))
        builder.adjust(1)
        
        await message.answer(
            emoji_to_premium(
                f" <b>Опис збережено!</b> \n\n"
                f"🎭 <b>Роль:</b> «{self.name_of_role}»\n"
                f"📝 <b>Опис:</b> <i>{role_description[:150]}{'...' if len(role_description) > 150 else ''}</i>\n\n"
                f"🏷️ <b>Оберіть тип ролі:</b>\n\n"
                f"• <b>Мирна</b> - грає на стороні мирних жителів (Лікар, Комісар тощо)\n"
                f"• <b>Зла</b> - мафія, маніяк, або інше зло\n"
                f"• <b>Нейтральна</b> - сам за себе (Коханка, Самогубець тощо)\n\n"
                f"⬇️ <b>Оберіть тип:</b> ⬇️"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        
        # Register alignment handlers
        self.router_construct_event.callback_query.register(
            self.role_alignment_selected_handler(),
            F.data.startswith("role_align_")
        )


    def role_alignment_selected_handler(self):
        """Handler when role alignment (мирна/зла/нейтральна) is selected"""
        async def handler(callback: CallbackQuery):
            if not getattr(self, "_pending_role_description", None):
                await callback.answer("Помилка: опис ролі втрачено. Почни з початку.", show_alert=True)
                self.is_creating_new_role = False
                await self.show_main_menu(callback)
                return
            
            data = callback.data or ""
            if "evil" in data:
                alignment = RoleAlignment.EVIL
                faction = "mafia"
                align_name = "Зла"
            elif "neutral" in data:
                alignment = RoleAlignment.NEUTRAL
                faction = "civilians"
                align_name = "Нейтральна"
            else:
                alignment = RoleAlignment.GOOD
                faction = "civilians"
                align_name = "Мирна"
            
            role_description = self._pending_role_description
            group_id_for_db = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
            
            temp_role = Role(
                name=self.name_of_role,
                description=role_description,
                abilities=[],
                creator_id=(self.group_creator_id or callback.from_user.id),
                group_id=group_id_for_db,
                is_default=False,
                enabled=True,
                min_players=1,
                alignment=alignment,
                faction=faction
            )
            
            delattr(self, "_pending_role_description")
            self.current_role = temp_role
            self.role_in_db = "custom_role"
            
            await callback.answer(f" Тип ролі: {align_name}", show_alert=False)
            
            # Show abilities setup menu
            builder = InlineKeyboardBuilder()
            builder.button(text="➕ Додати здатність", callback_data="add_ability_new_role")
            builder.button(text="⏭️ Пропустити (без здатностей)", callback_data="finish_role_creation")
            builder.button(text=" Скасувати", callback_data="cancel_role_creation")
            builder.adjust(1)
            
            try:
                await callback.message.edit_text(
                    f" <b>Тип ролі: {align_name}</b> \n\n"
                    f"🎭 <b>Роль:</b> «{self.name_of_role}»\n"
                    f"📝 <b>Опис:</b> <i>{role_description[:100]}{'...' if len(role_description) > 100 else ''}</i>\n\n"
                    f"⚔️ <b>Тепер додай здатності!</b> ⚔️\n\n"
                    f"Здатності - це те, що роль може робити під час гри:\n"
                    f"• Вбити гравця 🔪\n• Вилікувати 💊\n• Перевірити роль 🕵️\n"
                    f"• Заблокувати дію 🚫\n• Спеціальні ефекти ⚡\n\n"
                    f"⬇️ <b>Оберіть дію:</b> ⬇️",
                    reply_markup=builder.as_markup(),
                    parse_mode="html"
                )
            except Exception:
                await callback.message.answer(
                    f"⚔️ <b>Додавання здатностей</b> ⚔️\n\n"
                    f"🎭 Роль: «{self.name_of_role}»\n⬇️ Оберіть дію:",
                    reply_markup=builder.as_markup(),
                    parse_mode="html"
                )
            
            self.router_construct_event.callback_query.register(
                self.add_ability_new_role_handler(),
                F.data == "add_ability_new_role"
            )
            self.router_construct_event.callback_query.register(
                self.finish_role_creation_handler(),
                F.data == "finish_role_creation"
            )
        return handler


    def add_ability_new_role_handler(self):
        """Handler for adding ability during role creation"""
        async def handler(callback: CallbackQuery):
            if not self.current_role:
                await callback.answer("Роль не знайдена!", show_alert=True)
                return
            
            builder = InlineKeyboardBuilder()
            ability_types = [
                ("Убити", "new_ability_kill"),
                ("Лікувати", "new_ability_heal"),
                ("Перевірити роль", "new_ability_check_role"),
                ("Заблокувати дію", "new_ability_block"),
                ("Захистити", "new_ability_protect"),
                ("Перевірити гравця", "new_ability_inspect"),
                ("Спеціальний ефект", "new_ability_custom"),
            ]
            
            for name, data in ability_types:
                builder.button(text=name, callback_data=data)
            
            builder.button(text=" Завершити створення ролі", callback_data="finish_role_creation")
            builder.add(_icon_button("Назад", "back_to_abilities_new", "⬅️"))
            builder.adjust(2)
            
            # Register handlers
            for _, data in ability_types:
                self.router_construct_event.callback_query.register(
                    self.new_ability_type_selected(data),
                    F.data == data
                )
            self.router_construct_event.callback_query.register(
                self.finish_role_creation_handler(),
                F.data == "finish_role_creation"
            )
            
            abilities_list = "\n".join([
                f"{i+1}. <b>{ab.name}</b> ({self._ability_type_ua(ab.ability_type)})"
                for i, ab in enumerate(self.current_role.abilities)
            ]) if self.current_role.abilities else "Здатності відсутні"
            
            await callback.message.edit_text(
                emoji_to_premium(
                    f"⚔️ <b>Додавання здатностей</b> ⚔️\n\n"
                    f"🎭 <b>Роль:</b> «{self.current_role.name}»\n\n"
                    f"📋 <b>Поточні здатності:</b>\n{abilities_list if abilities_list != 'Здатності відсутні' else ' Здатності відсутні'}\n\n"
                    f"⬇️ <b>Оберіть тип здатності для додавання:</b> ⬇️"
                ),
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
        return handler


    def new_ability_type_selected(self, ability_data: str):
        """Handler when ability type is selected during role creation"""
        async def handler(callback: CallbackQuery):
            # Спеціальний ефект - показуємо підменю з варіантами
            if ability_data == "new_ability_custom":
                builder = InlineKeyboardBuilder()
                builder.button(text="🤹 Обмін ролями", callback_data="spec_effect_swap_roles")
                builder.button(text="🎭 Фальсифікація", callback_data="spec_effect_falsify")
                builder.button(text="⚡ Інший спеціальний ефект", callback_data="spec_effect_other")
                builder.add(_icon_button("Назад", "add_ability_new_role", "⬅️"))
                builder.adjust(1)
                
                for data in ("spec_effect_swap_roles", "spec_effect_falsify", "spec_effect_other"):
                    self.router_construct_event.callback_query.register(
                        self.special_effect_selected_handler(data),
                        F.data == data
                    )
                
                try:
                    await callback.message.edit_text(
                        emoji_to_premium(
                            f"⚔️ <b>Спеціальний ефект</b> ⚔️\n\n"
                            f"🎭 <b>Роль:</b> «{self.current_role.name}»\n\n"
                            f"Оберіть тип спеціального ефекту:\n\n"
                            f"• <b>Обмін ролями</b> - поміняти ролі двох гравців місцями (як Клоун)\n"
                            f"• <b>Фальсифікація</b> - інвертувати результат перевірки Комісара (як Брехун)\n"
                            f"• <b>Інший</b> - довільний спеціальний ефект\n\n"
                            f"⬇️ <b>Оберіть:</b> ⬇️"
                        ),
                        reply_markup=builder.as_markup(),
                        parse_mode="html",
                    )
                except Exception:
                    await callback.message.answer(
                        emoji_to_premium("⚔️ Спеціальний ефект - оберіть тип:"),
                        reply_markup=builder.as_markup(),
                        parse_mode="html",
                    )
                await callback.answer()
                return
            
            ability_type_map = {
                "new_ability_kill": AbilityType.KILL,
                "new_ability_heal": AbilityType.HEAL,
                "new_ability_check_role": AbilityType.CHECK_ROLE,
                "new_ability_block": AbilityType.BLOCK_ACTION,
                "new_ability_protect": AbilityType.PROTECT,
                "new_ability_inspect": AbilityType.INSPECT,
            }
            
            ability_type = ability_type_map.get(ability_data)
            if not ability_type or not self.current_role:
                await callback.answer("Помилка!", show_alert=True)
                return
            
            new_ability = Ability(
                ability_type=ability_type,
                name=self._ability_type_ua(ability_type),
                description="",
                phase=AbilityPhase.NIGHT if ability_type in [AbilityType.KILL, AbilityType.HEAL] else AbilityPhase.BOTH,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.UNLIMITED
            )
            
            self.current_role.abilities.append(new_ability)
            abilities_data = [ab.to_dict() for ab in self.current_role.abilities]
            is_valid, error = validate_ability_configuration(abilities_data)
            
            if not is_valid and error:
                self.current_role.abilities.remove(new_ability)
                await callback.answer(f"Помилка: {error}", show_alert=True)
                return
            
            await callback.answer("Здатність додано! ")
            await self.add_ability_new_role_handler()(callback)
        return handler

    def special_effect_selected_handler(self, effect_data: str):
        """Handler for special effect submenu (swap_roles, falsify, other)"""
        async def handler(callback: CallbackQuery):
            if not self.current_role:
                await callback.answer("Роль не знайдена!", show_alert=True)
                return
            
            if effect_data == "spec_effect_swap_roles":
                new_ability = Ability(
                    ability_type=AbilityType.CUSTOM_EFFECT,
                    name="Обмін ролями",
                    description="Обери двох гравців для обміну ролями",
                    phase=AbilityPhase.NIGHT,
                    target_type=TargetType.TWO_PLAYERS,
                    usage_limit=UsageLimit.ONCE_PER_GAME,
                    custom_data={"effect_id": "swap_roles"}
                )
            elif effect_data == "spec_effect_falsify":
                new_ability = Ability(
                    ability_type=AbilityType.CUSTOM_EFFECT,
                    name="Фальсифікація",
                    description="Обери гравця для фальсифікації досьє",
                    phase=AbilityPhase.NIGHT,
                    target_type=TargetType.ONE_PLAYER,
                    usage_limit=UsageLimit.ONCE_PER_NIGHT,
                    custom_data={"effect_id": "falsify"}
                )
            else:  # spec_effect_other
                new_ability = Ability(
                    ability_type=AbilityType.CUSTOM_EFFECT,
                    name="Спеціальний ефект",
                    description="",
                    phase=AbilityPhase.NIGHT,
                    target_type=TargetType.ONE_PLAYER,
                    usage_limit=UsageLimit.UNLIMITED,
                    custom_data={"effect_id": "custom"}
                )
            
            self.current_role.abilities.append(new_ability)
            abilities_data = [ab.to_dict() for ab in self.current_role.abilities]
            is_valid, error = validate_ability_configuration(abilities_data)
            
            if not is_valid and error:
                self.current_role.abilities.remove(new_ability)
                await callback.answer(f"Помилка: {error}", show_alert=True)
                return
            
            await callback.answer("Здатність додано! ")
            await self.add_ability_new_role_handler()(callback)
        return handler


    def finish_role_creation_handler(self):
        """Handler to finish role creation and save it"""
        async def handler(callback: CallbackQuery):
            if not self.current_role:
                await callback.answer("Роль не знайдена!", show_alert=True)
                return
            
            try:
                # #region agent log
                _log_debug('debug-session', 'run1', 'CR2', 'construct_event.py:finish_role_creation_handler', 'Saving role', {
                    'role_name': self.current_role.name,
                    'creator_id': self.current_role.creator_id,
                    'group_id': self.current_role.group_id,
                    'is_default': self.current_role.is_default,
                    'abilities_len': len(self.current_role.abilities)
                })
                # #endregion
                # Save role to database using ChatRoleRegistry (ensures proper chat scoping)
                role_id = RoleManager.save_role(self.current_role)
                self.current_role.role_id = role_id
                
                # Очищаємо кеш для цього чату, щоб зміни застосувалися негайно
                ChatRoleRegistry.clear_chat_cache(self.current_role.group_id)
                
                # Verify save - використовуємо creator_id та group_id поточної групи
                verify_role = ChatRoleRegistry.get_role_for_chat(
                    self.current_role.creator_id,
                    self.current_role.group_id,
                    self.current_role.name
                )
                # #region agent log
                _log_debug('debug-session', 'run1', 'CR3', 'construct_event.py:finish_role_creation_handler', 'Role saved and verified', {
                    'role_id': role_id,
                    'verify_found': bool(verify_role),
                    'verify_role_name': verify_role.name if verify_role else None
                })
                # #endregion
                
                if not verify_role:
                    await callback.answer(" Помилка при збереженні ролі!", show_alert=True)
                    return
                
                # Show success message
                abilities_text = ""
                if self.current_role.abilities:
                    abilities_text = f"\n\n⚔️ <b>Здатності ({len(self.current_role.abilities)}):</b>\n"
                    for i, ab in enumerate(self.current_role.abilities, 1):
                        abilities_text += f"{i}. {ab.name} ({self._ability_type_ua(ab.ability_type)})\n"
                
                builder = InlineKeyboardBuilder()
                builder.button(text=" Готово", callback_data="go_to_main_menu")
                
                await callback.message.edit_text(
                    emoji_to_premium(
                        f"🎉 <b>Роль успішно створена!</b> 🎉\n\n"
                        f"🎭 <b>Назва:</b> «{self.current_role.name}»\n"
                        f"📝 <b>Опис:</b> <i>{self.current_role.description[:150]}{'...' if len(self.current_role.description) > 150 else ''}</i>{abilities_text}\n\n"
                        f" Роль збережена та готова до використання в грі!\n\n"
                        f"💡 <i>Тепер ти можеш призначати цю роль гравцям під час гри.</i>"
                    ),
                    reply_markup=builder.as_markup(),
                    parse_mode="html",
                )
                
                # Reset flags
                self.is_creating_new_role = False
                self.is_input_new_role_name = False
                self.is_input_new_role_description = False
                self.awaiting_role_name_user_id = None
                self.awaiting_role_description_user_id = None
                
                # Return to main menu will refresh the list automatically
                await asyncio.sleep(2)
                await self.show_main_menu(callback)
                
            except Exception as e:
                print(f"ERROR saving role: {e}")
                await callback.answer(f" Помилка при збереженні: {str(e)}", show_alert=True)
        return handler


    def cancel_role_creation_handler(self):
        """Handler to cancel role creation"""
        async def handler(callback: CallbackQuery):
            self.is_creating_new_role = False
            self.is_input_new_role_name = False
            self.is_input_new_role_description = False
            self.awaiting_role_name_user_id = None
            self.awaiting_role_description_user_id = None
            if hasattr(self, "_pending_role_description"):
                delattr(self, "_pending_role_description")
            self.current_role = None
            self.name_of_role = ""
            await self.show_main_menu(callback)
        return handler


    # Edit existing role handlers
    def name_of_role_callback(self):
        """Handler for editing role name"""
        async def handler(callback: CallbackQuery):
            if not self._can_edit_roles(callback.from_user.id):
                await callback.answer(
                    " Зміна назви ролі доступна лише з підпискою.\n\nКупити підписку: /buy_subscription",
                    show_alert=True
                )
                return
            builder = InlineKeyboardBuilder()
            builder.add(_icon_button("Назад", "go_to_previuos_menu", "⬅️"))
            
            await callback.message.edit_text(
                emoji_to_premium(
                    f"✏️ <b>Зміна назви ролі</b> ✏️\n\n"
                    f"🎭 <b>Поточна роль:</b> «{self.name_of_role}»\n\n"
                    f"Напиши мені <b>нову назву</b> для цієї ролі:\n\n"
                    f"⏳ <i>Очікую нову назву...</i>"
                ),
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
            self.is_input_new_role_name = True
            self.awaiting_role_name_user_id = callback.from_user.id
            group_id = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
            self._role_name_pending[callback.from_user.id] = {
                "role_name": self.name_of_role,
                "role_in_db": self.role_in_db,
                "chat_id": group_id,
                "group_creator_id": self.group_creator_id or callback.from_user.id,
            }
            self.router_construct_event.callback_query.register(
                self.go_to_previuos_menu_callback(),
                F.data == "go_to_previuos_menu"
            )
        return handler


    def update_role_name_handler(self):
        """Handler to update role name"""
        async def handler(message: Message):
            if not self._can_edit_roles(message.from_user.id):
                await message.answer(
                    " Зміна назви ролі доступна лише з підпискою.\n\nКупити підписку: /buy_subscription",
                    parse_mode="html"
                )
                return
            if not self.current_role:
                return
            
            new_name = message.text.strip()
            if not new_name:
                await message.answer(" Назва не може бути порожньою!")
                return
            
            # Update role
            self.current_role.name = new_name
            if self.role_in_db != "custom_role":
                await _db_execute_commit_async(
                    f"UPDATE admin_panel SET {self.role_in_db} = %s WHERE creator_id = %s AND group_id = %s",
                    (new_name, message.from_user.id, self.chat_id),
                )
            
            # Save using ChatRoleRegistry for custom roles (ensures proper scoping and validation)
            if self.role_in_db == "custom_role":
                try:
                    creator_key = self.group_creator_id or message.from_user.id
                    # Ensure consistent key for saving
                    self.current_role.creator_id = creator_key
                    self.current_role.group_id = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
                    ChatRoleRegistry.update_role_for_chat(creator_key, self.chat_id, self.current_role)
                    # Очищаємо кеш для цього чату, щоб зміни застосувалися негайно
                    ChatRoleRegistry.clear_chat_cache(self.chat_id)
                except ValueError as e:
                    await message.answer(f" Помилка: {str(e)}", parse_mode="html")
                    return
            else:
                # Ensure consistent key for saving default roles too
                if self.group_creator_id:
                    self.current_role.creator_id = self.group_creator_id
                self.current_role.group_id = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
                RoleManager.save_role(self.current_role)
                # Очищаємо кеш для цього чату, щоб зміни застосувалися негайно
                ChatRoleRegistry.clear_chat_cache(self.chat_id)
            
            await message.answer(
                f" <b>Назву змінено!</b> \n\n"
                f"🎭 <b>Стара назва:</b> «{self.name_of_role}»\n"
                f"🎭 <b>Нова назва:</b> «{new_name}»\n\n"
                f"💡 <i>Зміни збережено в базі даних.</i>",
                parse_mode="html"
            )
            self.name_of_role = new_name
            
            await asyncio.sleep(2)
            await message.delete()
        return handler


    def description_of_role_callback(self):
        """Handler for editing role description"""
        async def handler(callback: CallbackQuery):
            if not self._can_edit_roles(callback.from_user.id):
                await callback.answer(
                    " Зміна опису ролі доступна лише з підпискою.\n\nКупити підписку: /buy_subscription",
                    show_alert=True
                )
                return
            builder = InlineKeyboardBuilder()
            builder.add(_icon_button("Назад", "go_to_previuos_menu", "⬅️"))
            
            await callback.message.edit_text(
                emoji_to_premium(
                    f"📝 <b>Зміна опису ролі</b> 📝\n\n"
                    f"🎭 <b>Роль:</b> «{self.name_of_role}»\n\n"
                    f"Напиши мені <b>новий опис</b> для цієї ролі:\n\n"
                    f"💡 <i>Цей опис буде показано гравцеві під час гри.</i>\n\n"
                    f"⏳ <i>Очікую новий опис...</i>"
                ),
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
            self.is_input_new_role_description = True
            self.awaiting_role_description_user_id = callback.from_user.id
            group_id = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
            self._role_description_pending[callback.from_user.id] = {
                "role_name": self.name_of_role,
                "role_in_db": self.role_in_db,
                "chat_id": group_id,
                "group_creator_id": self.group_creator_id or callback.from_user.id,
            }
            self.router_construct_event.callback_query.register(
                self.go_to_previuos_menu_callback(),
                F.data == "go_to_previuos_menu"
            )
        return handler

    def change_role_alignment_callback(self):
        """Handler for changing role alignment (мирна/зла/нейтральна) for custom roles"""
        async def handler(callback: CallbackQuery):
            if not self._ensure_current_role(callback) or self.role_in_db != "custom_role":
                await callback.answer("Роль не знайдена!", show_alert=True)
                return
            
            builder = InlineKeyboardBuilder()
            builder.button(text="🟢 Мирна", callback_data="set_align_good")
            builder.button(text="🔴 Зла", callback_data="set_align_evil")
            builder.button(text="🟡 Нейтральна", callback_data="set_align_neutral")
            builder.add(_icon_button("Назад", "go_to_previuos_menu", "⬅️"))
            builder.adjust(2, 1)
            
            await callback.message.edit_text(
                emoji_to_premium(
                    f"🏷️ <b>Зміна типу ролі</b> 🏷️\n\n"
                    f"🎭 <b>Роль:</b> «{self.name_of_role}»\n\n"
                    f"Оберіть новий тип ролі:\n"
                    f"• <b>Мирна</b> - на стороні мирних\n"
                    f"• <b>Зла</b> - мафія, зло\n"
                    f"• <b>Нейтральна</b> - сам за себе\n\n"
                    f"⬇️ <b>Оберіть:</b> ⬇️"
                ),
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
            
            for data in ("set_align_good", "set_align_evil", "set_align_neutral"):
                self.router_construct_event.callback_query.register(
                    self.apply_alignment_change(data),
                    F.data == data
                )
        return handler
    
    def apply_alignment_change(self, data: str):
        """Apply alignment change and save"""
        async def handler(callback: CallbackQuery):
            if not self.current_role:
                return
            if "evil" in data:
                self.current_role.alignment = RoleAlignment.EVIL
                self.current_role.faction = "mafia"
                align_name = "Зла"
            elif "neutral" in data:
                self.current_role.alignment = RoleAlignment.NEUTRAL
                self.current_role.faction = "civilians"
                align_name = "Нейтральна"
            else:
                self.current_role.alignment = RoleAlignment.GOOD
                self.current_role.faction = "civilians"
                align_name = "Мирна"
            
            creator_key = self.group_creator_id or callback.from_user.id
            self.current_role.creator_id = creator_key
            self.current_role.group_id = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
            ChatRoleRegistry.update_role_for_chat(creator_key, self.chat_id, self.current_role)
            ChatRoleRegistry.clear_chat_cache(self.chat_id)
            
            await callback.answer(f" Тип ролі змінено на: {align_name}", show_alert=True)
            await self.show_role_edit_menu(callback, self.current_role)
        return handler

    def min_players_callback(self):
        """Handler for editing min players for role"""
        async def handler(callback: CallbackQuery):
            builder = InlineKeyboardBuilder()
            for quick_value in (4, 5, 6, 7, 8, 9, 10):
                builder.button(text=str(quick_value), callback_data=f"set_min_players:{quick_value}")
            builder.add(_icon_button("Назад", "go_to_previuos_menu", "⬅️"))
            builder.adjust(4, 3, 1)
            
            await callback.message.edit_text(
                emoji_to_premium(
                    f"👥 <b>Мінімум гравців для ролі</b> 👥\n\n"
                    f"🎭 <b>Роль:</b> «{self.name_of_role}»\n\n"
                    f"Напиши число, від скількох гравців ця роль може випадати.\n\n"
                    f"💡 <i>Або обери швидко кнопкою нижче (наприклад: 6)</i>\n\n"
                    f"⏳ <i>Очікую число...</i>"
                ),
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
            self.is_input_min_players = True
            self.awaiting_min_players_user_id = callback.from_user.id
            # Зберігаємо контекст ролі для цього користувача (щоб інший не перезаписав)
            group_id = int(self.chat_id[0]) if isinstance(self.chat_id, tuple) else int(self.chat_id)
            self._min_players_pending[callback.from_user.id] = {
                "role_name": self.name_of_role,
                "role_in_db": self.role_in_db,
                "chat_id": group_id,
                "group_creator_id": self.group_creator_id or callback.from_user.id,
            }
            self.router_construct_event.callback_query.register(
                self.go_to_previuos_menu_callback(),
                F.data == "go_to_previuos_menu"
            )
            self.router_construct_event.callback_query.register(
                self.quick_set_min_players_callback(),
                F.data.startswith("set_min_players:")
            )
        return handler

    def _extract_mafia_scale_from_role(self, role: Optional[Role]) -> Dict[str, int]:
        defaults = {
            "up_to_10": 1,
            "from_11": 2,
            "from_16": 3,
            "from_23": 5,
        }
        if not role or role.name != "Мафія":
            return defaults
        data = getattr(role, "custom_data", None) or {}
        raw = data.get("mafia_scale", {})
        result = dict(defaults)
        if isinstance(raw, dict):
            for key in defaults:
                try:
                    value = int(raw.get(key, defaults[key]))
                except Exception:
                    value = defaults[key]
                result[key] = max(0, min(10, value))
        return result

    def mafia_scale_callback(self):
        """Налаштування кількості ролі Мафія за діапазонами гравців."""
        async def handler(callback: CallbackQuery):
            if not self._ensure_current_role(callback):
                await callback.answer("Роль не знайдена!", show_alert=True)
                return
            if not self.current_role or self.current_role.name != "Мафія":
                await callback.answer("Це налаштування доступне лише для ролі «Мафія».", show_alert=True)
                return

            # При вході в екран масштабу мафії знімаємо інші режими вводу,
            # інакше текст може перехопити інший хендлер.
            user_id = callback.from_user.id
            self.is_input_new_role_name = False
            self.awaiting_role_name_user_id = None
            self.is_input_new_role_description = False
            self.awaiting_role_description_user_id = None
            self.is_input_min_players = False
            self.awaiting_min_players_user_id = None
            self._role_name_pending.pop(user_id, None)
            self._role_description_pending.pop(user_id, None)
            self._min_players_pending.pop(user_id, None)
            self.is_creating_new_role = False

            scale = self._extract_mafia_scale_from_role(self.current_role)
            builder = InlineKeyboardBuilder()
            builder.add(_icon_button("Назад", "go_to_previuos_menu", "⬅️"))
            builder.adjust(1)

            await callback.message.edit_text(
                emoji_to_premium(
                    "⚖️ <b>Кількість мафії за гравцями</b>\n\n"
                    f"Поточна схема:\n"
                    f"• 1-10: <code>{scale['up_to_10']}</code>\n"
                    f"• 11-15: <code>{scale['from_11']}</code>\n"
                    f"• 16-22: <code>{scale['from_16']}</code>\n"
                    f"• 23+: <code>{scale['from_23']}</code>\n\n"
                    "Надішли вручну скільки гравців -> скільки мафії у форматі:\n"
                    "<code>10:1,15:2,22:3,23:5</code>\n\n"
                    "де:\n"
                    "• <code>10:1</code> = для 1-10 гравців\n"
                    "• <code>15:2</code> = для 11-15\n"
                    "• <code>22:3</code> = для 16-22\n"
                    "• <code>23:5</code> = для 23+\n\n"
                ),
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )

            self.is_input_mafia_scale = True
            self.awaiting_mafia_scale_user_id = user_id
            group_id = int(self.chat_id[0]) if isinstance(self.chat_id, tuple) else int(self.chat_id)
            self._mafia_scale_pending[user_id] = {
                "role_name": "Мафія",
                "chat_id": group_id,
                "group_creator_id": self.group_creator_id or user_id,
            }
            # Для цього екрана також потрібен явний callback-хендлер "Назад".
            self.router_construct_event.callback_query.register(
                self.go_to_previuos_menu_callback(),
                F.data == "go_to_previuos_menu"
            )
        return handler

    def quick_set_mafia_scale_callback(self):
        async def handler(callback: CallbackQuery):
            data = (callback.data or "").strip()
            payload = data.split(":", 1)[1] if ":" in data else ""
            user_id = callback.from_user.id if callback.from_user else 0
            await self._apply_mafia_scale_values(callback.message, callback, user_id, payload)
        return handler

    async def is_input_mafia_scale_handler(self, message: Message):
        if getattr(message.chat, "type", None) != "private":
            self.is_input_mafia_scale = False
            self.awaiting_mafia_scale_user_id = None
            return
        user_id = message.from_user.id if message.from_user else 0
        await self._apply_mafia_scale_values(message, None, user_id, (message.text or "").strip())

    async def _apply_mafia_scale_values(
        self,
        source_message: Message,
        callback: Optional[CallbackQuery],
        user_id: int,
        payload: str,
    ):
        ctx = self._mafia_scale_pending.get(user_id)
        if not ctx:
            if callback:
                await callback.answer("Сесію оновлено. Відкрий «Мафія» ще раз.", show_alert=True)
            else:
                await source_message.answer("⏳ Сесію скинуто. Відкрий налаштування «Мафія» ще раз.")
            return

        parts = [p.strip() for p in (payload or "").split(",")]
        a = b = c = d = None
        if len(parts) == 4 and all(":" not in p for p in parts):
            # legacy format: a,b,c,d
            try:
                a, b, c, d = [int(x) for x in parts]
            except Exception:
                a = b = c = d = None
        else:
            # new format: 10:1,15:2,22:3,23:5
            mapping = {}
            for chunk in parts:
                if ":" not in chunk:
                    continue
                left, right = chunk.split(":", 1)
                try:
                    players_n = int(left.strip())
                    mafia_n = int(right.strip())
                except Exception:
                    continue
                mapping[players_n] = mafia_n
            a = mapping.get(10)
            b = mapping.get(15)
            c = mapping.get(22)
            d = mapping.get(23)
        if any(v is None for v in (a, b, c, d)):
            text = "Формат невірний. Приклад: 10:1,15:2,22:3,23:5"
            if callback:
                await callback.answer(text, show_alert=True)
            else:
                await source_message.answer(text)
            return

        values = [a, b, c, d]
        if any(v < 0 or v > 10 for v in values):
            text = "Кожне значення має бути від 0 до 10."
            if callback:
                await callback.answer(text, show_alert=True)
            else:
                await source_message.answer(text)
            return

        role = ChatRoleRegistry.get_role_for_chat(ctx["group_creator_id"], ctx["chat_id"], ctx["role_name"])
        if not role:
            if callback:
                await callback.answer("Роль «Мафія» не знайдена.", show_alert=True)
            else:
                await source_message.answer("Роль «Мафія» не знайдена.")
            return

        role.custom_data = (getattr(role, "custom_data", None) or {})
        role.custom_data["mafia_scale"] = {
            "up_to_10": a,
            "from_11": b,
            "from_16": c,
            "from_23": d,
        }
        role.creator_id = ctx["group_creator_id"]
        role.group_id = ctx["chat_id"]
        RoleManager.save_role(role)
        ChatRoleRegistry.clear_chat_cache(ctx["chat_id"])

        self.current_role = role
        self._mafia_scale_pending.pop(user_id, None)
        self.is_input_mafia_scale = False
        if self.awaiting_mafia_scale_user_id == user_id:
            self.awaiting_mafia_scale_user_id = None

        if callback:
            await callback.answer("Схему мафії збережено", show_alert=False)
            await self.show_role_edit_menu(callback, role)
            return

        await source_message.answer(
            " <b>Схему мафії оновлено</b>\n\n"
            f"• 1-10: <code>{a}</code>\n"
            f"• 11-15: <code>{b}</code>\n"
            f"• 16-22: <code>{c}</code>\n"
            f"• 23+: <code>{d}</code>",
            parse_mode="html",
        )

    def quick_set_min_players_callback(self):
        """Швидке встановлення мін. гравців кнопкою (без текстового вводу)."""
        async def handler(callback: CallbackQuery):
            user_id = callback.from_user.id if callback.from_user else 0
            data = (callback.data or "").strip()
            try:
                value = int(data.split(":", 1)[1])
            except Exception:
                await callback.answer("Невірне значення.", show_alert=True)
                return

            if value < 1:
                await callback.answer("Мінімум має бути >= 1", show_alert=True)
                return

            ctx = self._min_players_pending.get(user_id)
            if not ctx:
                await callback.answer("Сесію оновлено. Відкрий меню ролі ще раз.", show_alert=True)
                return

            role_name = ctx["role_name"]
            role_in_db = ctx["role_in_db"]
            chat_id = ctx["chat_id"]
            group_creator_id = ctx["group_creator_id"]

            role = ChatRoleRegistry.get_role_for_chat(group_creator_id, chat_id, role_name)
            if not role:
                await callback.answer("Роль не знайдена. Відкрий меню ролі ще раз.", show_alert=True)
                return

            role.min_players = value
            if role_in_db == "custom_role":
                try:
                    role.creator_id = group_creator_id
                    role.group_id = chat_id
                    ChatRoleRegistry.update_role_for_chat(group_creator_id, chat_id, role)
                    ChatRoleRegistry.clear_chat_cache(chat_id)
                except ValueError as e:
                    await callback.answer(f"Помилка: {str(e)}", show_alert=True)
                    return
            else:
                role.creator_id = group_creator_id
                role.group_id = chat_id
                RoleManager.save_role(role)
                ChatRoleRegistry.clear_chat_cache(chat_id)

            self._min_players_pending.pop(user_id, None)
            if self.awaiting_min_players_user_id == user_id:
                self.is_input_min_players = False
                self.awaiting_min_players_user_id = None

            await callback.answer(f"Мін. гравців: {value}", show_alert=False)
            await self.show_role_edit_menu(callback, role)
        return handler

    async def is_input_min_players_handler(self, message: Message):
        """Pass-through handler for min players input when flag is set (тільки в приватному чаті)."""
        if not self.is_input_min_players:
            return
        if getattr(message.chat, "type", None) != "private":
            self.is_input_min_players = False
            self.awaiting_min_players_user_id = None
            return
        await self.update_min_players_handler()(message)

    def update_min_players_handler(self):
        """Handler to update min players for role. Використовує контекст, збережений для цього user_id."""
        async def handler(message: Message):
            user_id = message.from_user.id if message.from_user else 0
            ctx = self._min_players_pending.pop(user_id, None)
            self.is_input_min_players = False
            self.awaiting_min_players_user_id = None
            if not ctx:
                await message.answer(
                    "⏳ Сесію скинуто (хтось інший відкрив конструктор). Відкрий налаштування ролі знову і введи число.",
                    parse_mode="html",
                )
                return
            role_name = ctx["role_name"]
            role_in_db = ctx["role_in_db"]
            chat_id = ctx["chat_id"]
            group_creator_id = ctx["group_creator_id"]
            try:
                value = int(message.text.strip())
                if value < 1:
                    self._min_players_pending[user_id] = ctx
                    self.is_input_min_players = True
                    self.awaiting_min_players_user_id = user_id
                    await message.answer(" Мінімум гравців має бути >= 1")
                    return
            except ValueError:
                self._min_players_pending[user_id] = ctx
                self.is_input_min_players = True
                self.awaiting_min_players_user_id = user_id
                await message.answer(" Невірний формат. Введи число.")
                return

            role = ChatRoleRegistry.get_role_for_chat(group_creator_id, chat_id, role_name)
            if not role:
                await message.answer(
                    f" Роль «{role_name}» не знайдена. Відкрий налаштування ролі знову.",
                    parse_mode="html",
                )
                return
            role.min_players = value
            if role_in_db == "custom_role":
                try:
                    role.creator_id = group_creator_id
                    role.group_id = chat_id
                    ChatRoleRegistry.update_role_for_chat(group_creator_id, chat_id, role)
                    ChatRoleRegistry.clear_chat_cache(chat_id)
                except ValueError as e:
                    await message.answer(f" Помилка: {str(e)}", parse_mode="html")
                    return
            else:
                role.creator_id = group_creator_id
                role.group_id = chat_id
                RoleManager.save_role(role)
                ChatRoleRegistry.clear_chat_cache(chat_id)

            await message.answer(
                f" <b>Мін. гравців оновлено!</b> \n\n"
                f"🎭 <b>Роль:</b> «{role_name}»\n"
                f"👥 <b>Мін. гравців:</b> <code>{value}</code>\n\n"
                f"💡 <i>Зміни збережено в базі даних.</i>",
                parse_mode="html",
            )
            await asyncio.sleep(2)
            await message.delete()
        return handler

    def toggle_role_enabled_callback(self):
        """Toggle role enabled/disabled"""
        async def handler(callback: CallbackQuery):
            if not self._ensure_current_role(callback):
                await callback.answer("Роль не знайдена!", show_alert=True)
                return
            current = getattr(self.current_role, "enabled", True)
            # Клоун та Диявол - тільки для груп з активною підпискою (купленою або виданою засновником)
            if not current and self.current_role.name in ("Клоун", "Диявол"):
                creator_id = self.group_creator_id or callback.from_user.id
                if not ShopManager.is_subscription_active(creator_id):
                    await callback.answer(
                        "Ролі Клоун та Диявол доступні лише для груп з активною підпискою. "
                        "Купити підписку: /buy_subscription",
                        show_alert=True,
                    )
                    return
            self.current_role.enabled = not current
            # Ensure we always save under the group's creator_id key
            if self.group_creator_id:
                self.current_role.creator_id = self.group_creator_id
            self.current_role.group_id = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
            
            # Диявол і Клоун взаємовиключні: при вмиканні одного вимикаємо іншого
            if self.current_role.enabled and self.current_role.name in ("Диявол", "Клоун"):
                other_name = "Клоун" if self.current_role.name == "Диявол" else "Диявол"
                creator_key = self.group_creator_id or callback.from_user.id
                group_id = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
                try:
                    role_other = ChatRoleRegistry.get_role_for_chat(creator_key, group_id, other_name)
                    if role_other and getattr(role_other, "enabled", True):
                        role_other.enabled = False
                        RoleManager.save_role(role_other)
                        ChatRoleRegistry.clear_chat_cache(self.chat_id)
                except Exception:
                    pass
            
            # Save updated role
            if self.role_in_db == "custom_role":
                try:
                    creator_key = self.group_creator_id or callback.from_user.id
                    ChatRoleRegistry.update_role_for_chat(creator_key, self.chat_id, self.current_role)
                    # Кеш автоматично очищається в update_role_for_chat
                except ValueError as e:
                    await callback.answer(f" Помилка: {str(e)}", show_alert=True)
                    return
            else:
                RoleManager.save_role(self.current_role)
                # Очищаємо кеш для цього чату, щоб зміни застосувалися негайно
                ChatRoleRegistry.clear_chat_cache(self.chat_id)
            
            await callback.answer(" Зміни збережено!", show_alert=True)
            await self.show_role_edit_menu(callback, self.current_role)
        return handler

    def upload_role_card_custom_callback(self):
        """Start flow: next photo from this user will be saved as role card for current custom role."""
        async def handler(callback: CallbackQuery):
            if not self._ensure_current_role(callback) or self.role_in_db != "custom_role":
                await callback.answer("Роль не знайдена або не є кастомною.", show_alert=True)
                return
            self.awaiting_role_card_user_id = callback.from_user.id
            try:
                await callback.message.answer(
                    "🖼 <b>Картка ролі</b>\n\n"
                    "Надішли фото, яке буде карткою для цієї ролі.\n"
                    "Вимоги:\n"
                    "• Формат: JPG/PNG\n"
                    "• Розмір файлу: до 5 МБ\n\n"
                    "Назва файлу буде відповідати назві ролі; вона має збігатися з тим, як роль показується гравцям.",
                    parse_mode="html",
                )
            except Exception:
                pass
            await callback.answer()
        return handler

    async def role_card_photo_handler(self, message: Message, bot: Bot):
        """Handle incoming photo for custom role card upload."""
        if not self.awaiting_role_card_user_id or not message.from_user or message.from_user.id != self.awaiting_role_card_user_id:
            return
        if not self.current_role or self.role_in_db != "custom_role":
            await message.answer("❌ Немає вибраної кастомної ролі.", parse_mode="html")
            self.awaiting_role_card_user_id = None
            return
        photo = message.photo[-1]
        max_bytes = 5 * 1024 * 1024
        if getattr(photo, "file_size", 0) and photo.file_size > max_bytes:
            await message.answer("❌ Фото надто велике. Використай зображення до 5 МБ.", parse_mode="html")
            return
        safe_name = self.current_role.name.strip()
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
        self.awaiting_role_card_user_id = None
        await message.answer(
            f" Картку ролі для <b>{html.escape(self.current_role.name)}</b> збережено.\n"
            "Вона буде показуватись гравцям при видачі цієї ролі (якщо назва ролі збігається).",
            parse_mode="html",
        )


    def update_role_description_handler(self):
        """Handler to update role description"""
        async def handler(message: Message):
            if not self._can_edit_roles(message.from_user.id):
                await message.answer(
                    " Зміна опису ролі доступна лише з підпискою.\n\nКупити підписку: /buy_subscription",
                    parse_mode="html"
                )
                return
            if not self.current_role:
                return
            
            new_description = message.text.strip()
            if not new_description:
                await message.answer(" Опис не може бути порожнім!")
                return
            
            # Update role
            self.current_role.description = new_description
            if self.role_in_db != "custom_role":
                await _db_execute_commit_async(
                    f"UPDATE admin_panel SET {self.role_in_db}_text = %s WHERE creator_id = %s AND group_id = %s",
                    (new_description, message.from_user.id, self.chat_id),
                )
            
            # Save using ChatRoleRegistry for custom roles (ensures proper scoping and validation)
            if self.role_in_db == "custom_role":
                try:
                    creator_key = self.group_creator_id or message.from_user.id
                    self.current_role.creator_id = creator_key
                    self.current_role.group_id = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
                    ChatRoleRegistry.update_role_for_chat(creator_key, self.chat_id, self.current_role)
                    # Очищаємо кеш для цього чату, щоб зміни застосувалися негайно
                    ChatRoleRegistry.clear_chat_cache(self.chat_id)
                except ValueError as e:
                    await message.answer(f" Помилка: {str(e)}", parse_mode="html")
                    return
            else:
                if self.group_creator_id:
                    self.current_role.creator_id = self.group_creator_id
                self.current_role.group_id = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
                RoleManager.save_role(self.current_role)
                # Очищаємо кеш для цього чату, щоб зміни застосувалися негайно
                ChatRoleRegistry.clear_chat_cache(self.chat_id)
            
            await message.answer(
                f" <b>Опис змінено!</b> \n\n"
                f"🎭 <b>Роль:</b> «{self.name_of_role}»\n"
                f"📝 <b>Новий опис:</b> <i>{new_description[:100]}{'...' if len(new_description) > 100 else ''}</i>\n\n"
                f"💡 <i>Зміни збережено в базі даних.</i>",
                parse_mode="html"
            )
            
            await asyncio.sleep(2)
            await message.delete()
        return handler


    def abilities_callback(self):
        """Handler for abilities menu"""
        async def handler(callback: CallbackQuery):
            if not self._ensure_current_role(callback):
                await callback.answer("Роль не знайдена!", show_alert=True)
                return
            if not self._can_edit_roles(callback.from_user.id):
                await callback.answer(
                    " Керування здатностями доступне лише з підпискою.\n\nКупити підписку: /buy_subscription",
                    show_alert=True
                )
                return
            
            builder = InlineKeyboardBuilder()
            builder.add(_icon_button("Додати здатність", "add_ability", "➕"))
            
            if self.current_role.abilities:
                builder.add(_icon_button("Список здатностей", "list_abilities", "📋"))
                builder.button(text="🗑️ Видалити здатність", callback_data="remove_ability")
            
            builder.add(_icon_button("Назад", "go_to_previuos_menu", "⬅️"))
            builder.adjust(1)
            
            abilities_list = "\n".join([
                f"{i+1}. <b>{ab.name}</b> ({self._ability_type_ua(ab.ability_type)})"
                for i, ab in enumerate(self.current_role.abilities)
            ]) if self.current_role.abilities else "Здатності відсутні"
            
            # Register handlers
            self.router_construct_event.callback_query.register(
                self.add_ability_handler(),
                F.data == "add_ability"
            )
            if self.current_role.abilities:
                self.router_construct_event.callback_query.register(
                    self.list_abilities_handler(),
                    F.data == "list_abilities"
                )
                self.router_construct_event.callback_query.register(
                    self.remove_ability_handler(),
                    F.data == "remove_ability"
                )
            self.router_construct_event.callback_query.register(
                self.go_to_previuos_menu_callback(),
                F.data == "go_to_previuos_menu"
            )
            
            await callback.message.edit_text(
                emoji_to_premium(
                    f"⚔️ <b>Керування здатностями</b> ⚔️\n\n"
                    f"🎭 <b>Роль:</b> «{self.current_role.name}»\n\n"
                    f"📋 <b>Поточні здатності:</b>\n"
                    f"{abilities_list if abilities_list != 'Здатності відсутні' else ' Здатності відсутні - додай першу!'}\n\n"
                    f"⬇️ <b>Оберіть дію:</b> ⬇️"
                ),
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
        return handler


    def add_ability_handler(self):
        """Handler for adding ability to existing role"""
        async def handler(callback: CallbackQuery):
            if not self._ensure_current_role(callback):
                await callback.answer("Роль не знайдена!", show_alert=True)
                return
            
            builder = InlineKeyboardBuilder()
            ability_types = [
                ("Убити", "ability_kill"),
                ("Лікувати", "ability_heal"),
                ("Перевірити роль", "ability_check_role"),
                ("Заблокувати дію", "ability_block"),
                ("Захистити", "ability_protect"),
                ("Перевірити гравця", "ability_inspect"),
                ("Спеціальний ефект", "ability_custom"),
            ]
            
            for name, data in ability_types:
                builder.button(text=name, callback_data=data)
            
            builder.add(_icon_button("Назад", "abilities", "⬅️"))
            builder.adjust(2)
            
            # Register handlers
            self.router_construct_event.callback_query.register(
                self.abilities_callback(),
                F.data == "abilities"
            )
            for _, data in ability_types:
                self.router_construct_event.callback_query.register(
                    self.ability_type_selected(data),
                    F.data == data
                )
            
            role_name = self.current_role.name if self.current_role else "N/A"
            await callback.message.edit_text(
                emoji_to_premium(
                    f"⚔️ <b>Додавання здатності</b> ⚔️\n\n"
                    f"🎭 <b>Роль:</b> «{role_name}»\n\n"
                    f"⬇️ <b>Оберіть тип здатності:</b> ⬇️\n\n"
                    f"💡 <i>Кожен тип має свої особливості та правила використання.</i>"
                ),
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
        return handler


    def ability_type_selected(self, ability_data: str):
        """Handler when ability type is selected (for existing role editing)"""
        async def handler(callback: CallbackQuery):
            if not self._ensure_current_role(callback):
                await callback.answer("Роль не знайдена!", show_alert=True)
                return
            
            # Спеціальний ефект - підменю
            if ability_data == "ability_custom":
                builder = InlineKeyboardBuilder()
                builder.button(text="🤹 Обмін ролями", callback_data="spec_edit_swap_roles")
                builder.button(text="🎭 Фальсифікація", callback_data="spec_edit_falsify")
                builder.button(text="⚡ Інший спеціальний ефект", callback_data="spec_edit_other")
                builder.add(_icon_button("Назад", "abilities", "⬅️"))
                builder.adjust(1)
                
                for data in ("spec_edit_swap_roles", "spec_edit_falsify", "spec_edit_other"):
                    self.router_construct_event.callback_query.register(
                        self.special_effect_edit_selected_handler(data),
                        F.data == data
                    )
                
                try:
                    await callback.message.edit_text(
                        emoji_to_premium(
                            f"⚔️ <b>Спеціальний ефект</b> ⚔️\n\n"
                            f"🎭 <b>Роль:</b> «{self.current_role.name}»\n\n"
                            f"Оберіть тип:\n"
                            f"• <b>Обмін ролями</b> - поміняти ролі двох гравців\n"
                            f"• <b>Фальсифікація</b> - інвертувати результат перевірки\n"
                            f"• <b>Інший</b> - довільний спеціальний ефект"
                        ),
                        reply_markup=builder.as_markup(),
                        parse_mode="html",
                    )
                except Exception:
                    await callback.message.answer(
                        emoji_to_premium("⚔️ Спеціальний ефект - оберіть тип:"),
                        reply_markup=builder.as_markup(),
                        parse_mode="html",
                    )
                await callback.answer()
                return
            
            ability_type_map = {
                "ability_kill": AbilityType.KILL,
                "ability_heal": AbilityType.HEAL,
                "ability_check_role": AbilityType.CHECK_ROLE,
                "ability_block": AbilityType.BLOCK_ACTION,
                "ability_protect": AbilityType.PROTECT,
                "ability_inspect": AbilityType.INSPECT,
            }
            
            ability_type = ability_type_map.get(ability_data)
            if not ability_type:
                await callback.answer("Невідомий тип!", show_alert=True)
                return
            
            new_ability = Ability(
                ability_type=ability_type,
                name=self._ability_type_ua(ability_type),
                description="",
                phase=AbilityPhase.NIGHT if ability_type in [AbilityType.KILL, AbilityType.HEAL] else AbilityPhase.BOTH,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.UNLIMITED
            )
            
            self.current_role.abilities.append(new_ability)
            abilities_data = [ab.to_dict() for ab in self.current_role.abilities]
            is_valid, error = validate_ability_configuration(abilities_data)
            
            if not is_valid and error:
                self.current_role.abilities.remove(new_ability)
                await callback.answer(f"Помилка: {error}", show_alert=True)
                return
            
            RoleManager.save_role(self.current_role)
            ChatRoleRegistry.clear_chat_cache(self.chat_id)
            await callback.answer("Здатність додано! ")
            await self.abilities_callback()(callback)
        return handler

    def special_effect_edit_selected_handler(self, effect_data: str):
        """Handler for special effect submenu when editing existing role"""
        async def handler(callback: CallbackQuery):
            if not self._ensure_current_role(callback):
                await callback.answer("Роль не знайдена!", show_alert=True)
                return
            
            if "swap" in effect_data:
                new_ability = Ability(
                    ability_type=AbilityType.CUSTOM_EFFECT,
                    name="Обмін ролями",
                    description="Обери двох гравців для обміну ролями",
                    phase=AbilityPhase.NIGHT,
                    target_type=TargetType.TWO_PLAYERS,
                    usage_limit=UsageLimit.ONCE_PER_GAME,
                    custom_data={"effect_id": "swap_roles"}
                )
            elif "falsify" in effect_data:
                new_ability = Ability(
                    ability_type=AbilityType.CUSTOM_EFFECT,
                    name="Фальсифікація",
                    description="Обери гравця для фальсифікації досьє",
                    phase=AbilityPhase.NIGHT,
                    target_type=TargetType.ONE_PLAYER,
                    usage_limit=UsageLimit.ONCE_PER_NIGHT,
                    custom_data={"effect_id": "falsify"}
                )
            else:
                new_ability = Ability(
                    ability_type=AbilityType.CUSTOM_EFFECT,
                    name="Спеціальний ефект",
                    description="",
                    phase=AbilityPhase.NIGHT,
                    target_type=TargetType.ONE_PLAYER,
                    usage_limit=UsageLimit.UNLIMITED,
                    custom_data={"effect_id": "custom"}
                )
            
            self.current_role.abilities.append(new_ability)
            abilities_data = [ab.to_dict() for ab in self.current_role.abilities]
            is_valid, error = validate_ability_configuration(abilities_data)
            
            if not is_valid and error:
                self.current_role.abilities.remove(new_ability)
                await callback.answer(f"Помилка: {error}", show_alert=True)
                return
            
            RoleManager.save_role(self.current_role)
            ChatRoleRegistry.clear_chat_cache(self.chat_id)
            await callback.answer("Здатність додано! ")
            await self.abilities_callback()(callback)
        return handler


    def list_abilities_handler(self):
        """Handler for listing abilities"""
        async def handler(callback: CallbackQuery):
            if not self._ensure_current_role(callback) or not self.current_role.abilities:
                await callback.answer("Немає здатностей!", show_alert=True)
                return
            
            abilities_text = ""
            for i, ab in enumerate(self.current_role.abilities, 1):
                abilities_text += (
                    f"{i}. <b>{ab.name}</b>\n"
                    f"   Тип: {self._ability_type_ua(ab.ability_type)}\n"
                    f"   Фаза: {self._ability_phase_ua(ab.phase)}\n"
                    f"   Мета: {self._ability_target_type_ua(ab.target_type)}\n"
                    f"   Обмеження: {self._ability_usage_limit_ua(ab.usage_limit)}\n\n"
                )
            
            builder = InlineKeyboardBuilder()
            builder.add(_icon_button("Назад", "abilities", "⬅️"))
            
            self.router_construct_event.callback_query.register(
                self.abilities_callback(),
                F.data == "abilities"
            )
            
            await callback.message.edit_text(
                emoji_to_premium(
                    f"📋 <b>Детальний список здатностей</b> 📋\n\n"
                    f"🎭 <b>Роль:</b> «{self.current_role.name}»\n\n"
                    f"{abilities_text}\n"
                ),
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
        return handler


    def remove_ability_handler(self):
        """Handler for removing ability"""
        async def handler(callback: CallbackQuery):
            if not self._ensure_current_role(callback) or not self.current_role.abilities:
                await callback.answer("Немає здатностей!", show_alert=True)
                return
            
            builder = InlineKeyboardBuilder()
            for i, ab in enumerate(self.current_role.abilities):
                builder.button(text=f"{i+1}. {ab.name}", callback_data=f"remove_ability_{i}")
            builder.add(_icon_button("Назад", "abilities", "⬅️"))
            builder.adjust(1)
            
            self.router_construct_event.callback_query.register(
                self.abilities_callback(),
                F.data == "abilities"
            )
            
            for i in range(len(self.current_role.abilities)):
                self.router_construct_event.callback_query.register(
                    self.confirm_remove_ability(i),
                    F.data == f"remove_ability_{i}"
                )
            
            await callback.message.edit_text(
                emoji_to_premium(
                    "🗑️ <b>Видалення здатності</b> 🗑️\n\n"
                    f"🎭 <b>Роль:</b> «{self.current_role.name}»\n\n"
                    "⚠️ <i>Увага! Цю дію неможливо скасувати.</i>\n\n"
                    "⬇️ <b>Оберіть здатність для видалення:</b> ⬇️"
                ),
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
        return handler


    def confirm_remove_ability(self, ability_index: int):
        """Handler for confirming ability removal"""
        async def handler(callback: CallbackQuery):
            if not self.current_role or ability_index >= len(self.current_role.abilities):
                await callback.answer("Помилка!", show_alert=True)
                return
            
            removed = self.current_role.abilities.pop(ability_index)
            RoleManager.save_role(self.current_role)
            # Очищаємо кеш для цього чату, щоб зміни застосувалися негайно
            ChatRoleRegistry.clear_chat_cache(self.chat_id)
            await callback.answer(f"Здатність «{removed.name}» видалено! ")
            await self.abilities_callback()(callback)
        return handler


    def go_to_previuos_menu_callback(self):
        """Return to role edit menu"""
        async def handler(callback: CallbackQuery):
            self.is_input_min_players = False
            self.is_input_mafia_scale = False
            self.is_input_new_role_name = False
            self.is_input_new_role_description = False
            uid = callback.from_user.id if callback.from_user else None
            if uid is not None:
                self._min_players_pending.pop(uid, None)
                self._mafia_scale_pending.pop(uid, None)
                self._role_name_pending.pop(uid, None)
                self._role_description_pending.pop(uid, None)
            self.awaiting_min_players_user_id = None
            self.awaiting_mafia_scale_user_id = None
            self.awaiting_role_name_user_id = None
            self.awaiting_role_description_user_id = None
            if self._ensure_current_role(callback):
                await self.show_role_edit_menu(callback, self.current_role)
        return handler


    def delete_role_handler(self, role_name: str):
        """Handler for deleting a custom role"""
        async def handler(callback: CallbackQuery):
            try:
                chat_id_int = int(self.chat_id) if not isinstance(self.chat_id, tuple) else int(self.chat_id[0])
                user_id = callback.from_user.id
                deleted = ChatRoleRegistry.delete_role_from_chat(self.group_creator_id or user_id, chat_id_int, role_name)
                if not deleted and self.group_creator_id and self.group_creator_id != user_id:
                    deleted = ChatRoleRegistry.delete_role_from_chat(user_id, chat_id_int, role_name)
                if deleted:
                    self.current_role = None
                    self.name_of_role = ""
                    await callback.answer(f"Роль «{role_name}» видалено! ", show_alert=True)
                    await self.show_main_menu(callback)
                else:
                    await callback.answer("Роль не знайдена! Можливо, роль створена під іншим ключем.", show_alert=True)
            except ValueError as e:
                await callback.answer(f" {str(e)}", show_alert=True)
            except Exception as e:
                await callback.answer(f" Помилка видалення: {str(e)}", show_alert=True)
        return handler


    # Group management
    async def add_group_handler(self, callback: CallbackQuery, bot: Bot):
        """Handler for adding a new group"""
        builder = InlineKeyboardBuilder()
        builder.add(_icon_button("Назад до меню", "go_to_main_menu", "⬅️"))
        
        await callback.message.edit_text(
            emoji_to_premium(
                "➕ <b>Додавання нової групи</b> ➕\n\n"
                "📁 Ти можеш додати іншу групу до свого списку для налаштування ролей.\n\n"
                "⬇️ <b>Надішли мені ID нової групи:</b> ⬇️\n\n"
                "💡 <i>Щоб дізнатися ID групи:\n"
                "1. Надішли команду <code>/id</code> у ту групу\n"
                "2. Скопіюй ID (завжди з мінусом)\n"
                "3. Надішли його сюди</i>\n\n"
                "⚠️ <i>Важливо: ти маєш бути власником групи!</i>"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="html",
        )
        
        self.is_input_add_chat_id = True
        self.awaiting_add_chat_id_user_id = callback.from_user.id


    async def IsInputAddChatId(self, message: Message, bot: Bot):
        """Handler for adding group ID (тільки в приватному чаті)."""
        if not self.is_input_add_chat_id:
            return
        if getattr(message.chat, "type", None) != "private":
            self.is_input_add_chat_id = False
            self.awaiting_add_chat_id_user_id = None
            return
        
        try:
            chat_id = int(message.text)
            
            # Check if user already has this group
            rows = await _db_fetchall_async(
                "SELECT group_id FROM admin_panel WHERE creator_id = %s",
                (message.from_user.id,),
            )
            user_group_ids = [row[0] for row in (rows or [])]
            
            if chat_id in user_group_ids:
                await message.answer(" Це id групи вже є у твоєму списку груп!")
                self.is_input_add_chat_id = False
                self.awaiting_add_chat_id_user_id = None
                return
            
            # Check if group exists with different creator
            existing = await _db_fetchone_async(
                "SELECT creator_id FROM admin_panel WHERE group_id = %s",
                (chat_id,),
            )
            if existing and existing[0] != message.from_user.id:
                await message.answer(" Ця група вже зареєстрована іншим користувачем!")
                self.is_input_add_chat_id = False
                self.awaiting_add_chat_id_user_id = None
                return
            
            # Verify user is creator
            chat_member = await bot.get_chat_member(chat_id, message.from_user.id)
            if chat_member.status == ChatMemberStatus.CREATOR:
                await _db_execute_commit_async(
                    "INSERT INTO admin_panel (creator_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (message.from_user.id, chat_id),
                )
                
                chat = await bot.get_chat(chat_id=chat_id)
                await message.answer(
                    f" <b>Групу додано!</b> \n\n"
                    f"📁 <b>Група:</b> {chat.title}\n"
                    f"🆔 <b>ID:</b> <code>{chat_id}</code>\n\n"
                    f"🎉 Тепер ти можеш налаштовувати ролі для цієї групи!\n\n"
                    f"👉 Використай <code>/construct_event</code> щоб продовжити.",
                    parse_mode="html"
                )
            else:
                await message.answer(" Ти не є власником цієї групи!")
            
            self.is_input_add_chat_id = False
            self.awaiting_add_chat_id_user_id = None
        except TelegramBadRequest:
            await message.answer(" Помилка доступу до групи!")
            self.is_input_add_chat_id = False
            self.awaiting_add_chat_id_user_id = None
        except ValueError:
            await message.answer(" Неправильний формат! Напиши тільки цифри.")


    def delete_group_handler(self):
        """Handler for deleting a group"""
        async def handler(callback: CallbackQuery, bot: Bot):
            builder = InlineKeyboardBuilder()
            builder.button(text="Так", callback_data="yes_delete_group")
            builder.button(text="Ні", callback_data="no_delete_group")
            
            await callback.message.edit_text(
                "⚠️ <b>Підтвердження видалення</b> ⚠️\n\n"
                "Ти точно хочеш видалити групу зі списку?\n\n"
                "💡 <i>Це не видалить групу в Telegram, лише прибере прив’язку в боті.</i>\n\n"
                "👑 <i>Видалити може лише <b>власник групи</b> (хто створив чат у Telegram), не просто адмін.</i>",
                reply_markup=builder.as_markup(),
                parse_mode="html"
            )
            
            self.router_construct_event.callback_query.register(
                self.yes_delete_group_handler(bot),
                F.data == "yes_delete_group"
            )
            self.router_construct_event.callback_query.register(
                self.no_delete_group_handler(),
                F.data == "no_delete_group"
            )
        return handler


    def yes_delete_group_handler(self, bot: Bot):
        """Handler for confirming group deletion"""
        async def handler(callback: CallbackQuery):
            builder = InlineKeyboardBuilder()
            group_ids = await _db_fetchall_async(
                "SELECT DISTINCT group_id FROM admin_panel WHERE creator_id = %s",
                (callback.from_user.id,),
            ) or []
            eligible: list[int] = []

            for chat_id_tuple in group_ids:
                chat_id = int(chat_id_tuple[0])
                if not await self._user_is_telegram_group_creator(bot, chat_id, callback.from_user.id):
                    continue
                try:
                    chat = await bot.get_chat(chat_id=chat_id)
                    builder.button(text=chat.title, callback_data=f"delete_group_{chat_id}")
                    eligible.append(chat_id)
                except Exception:
                    continue

            builder.add(_icon_button("Назад", "go_to_main_menu", "⬅️"))
            builder.adjust(1)

            for chat_id in eligible:
                self.router_construct_event.callback_query.register(
                    self.confirm_delete_group(chat_id),
                    F.data == f"delete_group_{chat_id}",
                )

            if not eligible:
                await callback.message.edit_text(
                    "🗑️ <b>Видалення групи</b> 🗑️\n\n"
                    "Немає груп, які ти можеш видалити з бота.\n\n"
                    "👑 Видалення доступне лише <b>власнику групи в Telegram</b> "
                    "(той, хто створив чат). Якщо ти лише адмін - попроси власника.\n\n"
                    "💡 Якщо власник змінився, спочатку оновіть власника в налаштуваннях Telegram.",
                    reply_markup=builder.as_markup(),
                    parse_mode="html",
                )
                return

            await callback.message.edit_text(
                "🗑️ <b>Видалення групи</b> 🗑️\n\n"
                "⬇️ <b>Оберіть групу для видалення з бота:</b> ⬇️\n\n"
                "👑 Показані лише чати, де ти - <b>власник</b> у Telegram.\n\n"
                "⚠️ <i>Після видалення можна знову додати групу через конструктор.</i>",
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
        return handler


    def confirm_delete_group(self, chat_id: int):
        """Handler for confirming specific group deletion (лише власник Telegram-чату)."""
        async def handler(callback: CallbackQuery):
            bot = callback.bot
            uid = callback.from_user.id if callback.from_user else 0
            if not await self._user_is_telegram_group_creator(bot, chat_id, uid):
                await callback.answer(
                    "Видаляти може лише власник групи в Telegram.",
                    show_alert=True,
                )
                return
            # Прибираємо всі прив’язки цієї групи в боті (на випадок кількох creator_id у admin_panel)
            await _db_execute_commit_async(
                "DELETE FROM admin_panel WHERE group_id = %s",
                (chat_id,),
            )
            await callback.answer("Групу видалено з бота!", show_alert=True)
            await self.show_main_menu(callback)
        return handler


    def no_delete_group_handler(self):
        """Handler for canceling group deletion"""
        async def handler(callback: CallbackQuery):
            await self.show_main_menu(callback)
        return handler


    async def default_settings(self, callback: CallbackQuery):
        """Reset all settings to default"""
        defaults = [
            ("Лікар", "doctor"),
            ("Цієї гри ти - Лікар! Роби все, щоб врятувати якомога більше мирних людей.", "doctor_text"),
            ("Аль Капоне", "all_capone"),
            ("Цієї гри ти - Аль Капоне! Роби все, щоб твоя сім`я отримала перемогу, над цими нікчемними мирними жителями.", "all_capone_text"),
            ("Цієї гри ти - Мирний житель! Роби все, щоб знищити підступне угрупування Аль Капоне.", "civilian_text"),
            ("Мирний Житель", "civilian")
        ]
        
        for text, column in defaults:
            await _db_execute_commit_async(
                f"UPDATE admin_panel SET {column} = %s WHERE creator_id = %s AND group_id = %s",
                (text, callback.from_user.id, self.chat_id),
            )
        
        # Очищаємо кеш для цього чату, щоб зміни застосувалися негайно
        ChatRoleRegistry.clear_chat_cache(self.chat_id)
        
        await callback.message.edit_text(
            "🔄 <b>Налаштування скинуто!</b> 🔄\n\n"
            " Всі ролі повернуто до початкових значень.\n\n"
            "💡 <i>Кастомні ролі залишаються без змін.</i>",
            parse_mode="html"
        )
