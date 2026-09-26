from __future__ import annotations
import sys
import os
import io
import inspect
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import asyncio, random, html, re
import json
import shutil
import tempfile
from datetime import datetime, timedelta
try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore
from aiogram import Bot, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery,
    FSInputFile, BufferedInputFile, InputMediaPhoto, ChatPermissions,
)
from aiogram.utils.deep_linking import create_start_link
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError
from database.database import (
    cursor,
    conn,
    get_group_creator_id_async,
    get_group_admin_level_async,
    get_active_founder_ids,
    ping_members_add_async,
    ping_members_get_recent_async,
    ping_opt_out_add_async,
    ping_opt_out_remove_async,
    ping_opt_out_ids_for_chat_async,
    ping_opt_out_ids_for_chat,
    casino_create_round_async,
    casino_get_open_round_async,
    casino_close_bets_for_round_async,
    add_balance_to_user_async,
    run_db_call_async,
)
from commands.start import add_user_to_db
from game.chat_role_registry import ChatRoleRegistry
from game.role_system import RoleAlignment, AbilityType, AbilityPhase
from game.game_state_manager import game_state_manager, GameState
from typing import Optional
from game.item_effects import ItemEffectProcessor
from commands.buff_shop import (
    ActivationTime, ITEMS, ItemType, UNIQUE_BUFFS, can_use_item, try_consume_buff,
    get_active_items_for_player, grant_portal_reward, admin_grant_buff_to_user,
)
from commands.buy import ShopManager
from commands import vip as vip_mod
from commands import seasonal_events as seasonal_mod
from premium_emoji import emoji_to_premium, custom_emoji_id_for_symbol


def _devil_contract_choice_markup(chat_id: int) -> InlineKeyboardMarkup:
    """Кнопки прийняття угоди з Дияволом - преміум 📜 / ❓ на кнопках."""
    b = InlineKeyboardBuilder()
    doc = custom_emoji_id_for_symbol("📜")
    qm = custom_emoji_id_for_symbol("❓")
    if doc:
        b.button(
            text="Погодитися",
            callback_data=f"devil_accept_{chat_id}",
            icon_custom_emoji_id=doc,
        )
    else:
        b.button(text="Погодитися", callback_data=f"devil_accept_{chat_id}")
    if qm:
        b.button(
            text="Відмовитися",
            callback_data=f"devil_refuse_{chat_id}",
            icon_custom_emoji_id=qm,
        )
    else:
        b.button(text="Відмовитися", callback_data=f"devil_refuse_{chat_id}")
    b.adjust(2)
    return b.as_markup()


def _devil_covenant_activate_kb(chat_id: int) -> InlineKeyboardMarkup:
    """Кнопка активації бафа «Контракт з дияволом» з преміум 💥."""
    cid = custom_emoji_id_for_symbol("💥")
    if cid:
        btn = InlineKeyboardButton(
            text="Активувати контракт",
            callback_data=f"item_use:devil_covenant:{chat_id}",
            icon_custom_emoji_id=cid,
        )
    else:
        btn = InlineKeyboardButton(
            text="💥 Активувати контракт",
            callback_data=f"item_use:devil_covenant:{chat_id}",
        )
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])


# Алерти обговорення / голосування (callback.answer + show_alert — лише plain text, без HTML tg-emoji).
PLAY_ALERT_GAME_INACTIVE = (
    "⚠️Стіл порожній. Гра вже закінчилася, ці кнопки більше нічого не вирішують."
)
PLAY_ALERT_DISCUSSION_COUNTDOWN_STARTED = (
    "⏱️Час розмов вийшов. Ми вже почали зворотний відлік до вироку."
)
PLAY_ALERT_DISCUSSION_ALREADY_CLOSED = (
    "⏱️ Сказано достатньо. Обговорення вже закрите, переходимо до дій."
)
PLAY_ALERT_NOT_IN_THIS_PARTY = (
    "⛔️Не лізь не в свою справу.  Ти не береш участі в цій партії."
)
PLAY_ALERT_SKIP_DISCUSSION_ALREADY = (
    "👋Ми тебе почули. Ти вже натиснув пропуск, чекай на інших."
)
PLAY_ALERT_NOT_ENOUGH_ALIVE_FOR_VOTE = (
    "👥Немає кому вирішувати. Для голосування потрібно більше живих гравців."
)
PLAY_ALERT_NO_VOTE_CANDIDATES = (
    "🚨Пустий стіл. Жодного кандидата на виліт не знайдено."
)
PLAY_ALERT_NO_ACTIVE_GAME_JOIN = (
    "⚠️Стіл порожній. Не знайдено активної гри, до якої можна було б приєднатися."
)
PLAY_ALERT_PARTY_OVER = "⚠️Партія завершена. Твій час у цій грі вийшов."
PLAY_ALERT_VERDICT_WRONG_TIME = (
    "⏱️Не твій час. Зараз не час для вироку - або ще занадто рано, або вже пізно."
)
PLAY_ALERT_DAY_VOTE_45_EXPIRED = (
    "⏱️45 секунд минуло. Ти занадто довго вагався. Твій голос більше не приймається."
)
AFK_AUTO_CHOICE_TOTAL_SECONDS = 45
AFK_AUTO_CHOICE_BOT_PICK_AT_SECONDS = 40
PLAY_ALERT_STRANGER_NOT_ON_LIST = (
    "⛔️ Ти тут сторонній. Твого імені немає в списку учасників цієї партії."
)
PLAY_ALERT_DEAD_SILENT = (
    "☠️Мертві мовчать. Твій час у цій грі вичерпано. Просто спостерігай за фіналом."
)
PLAY_ALERT_DO_NOT_VOTE_DEAD = (
    "⛔️Мертвим вирок не потрібен. Обери когось із тих, хто ще дихає."
)
PLAY_ALERT_CANNOT_VOTE_SELF = (
    "⛔️Самогубство не вихід.  Ти не можеш винести вирок самому собі."
)
PLAY_ALERT_VOTE_STALE_OR_INVALID = (
    "🚨Голос не зараховано.  Дані застаріли. Спробуй оновити меню і повторити дію."
)
PLAY_ALERT_GAME_INACTIVE_OR_NOT_MEMBER = (
    "⚠️Стіл порожній. Або гра вже не йде, або ти не в списку учасників цієї партії."
)
PLAY_ALERT_HANGING_VOTE_EXPIRED = (
    "⏱️ Час на голосування за повішення вичерпано. Твій голос більше не приймається."
)
PLAY_ALERT_SILENCED_CANNOT_VOTE = (
    "🤐 Сьогодні твій голос недоступний — діє мовчанка."
)
PLAY_ALERT_ALREADY_VOTED_THIS_ROUND = (
    "👋Твій голос уже зараховано в цьому раунді."
)


class _ChatMessageProxy:
    """Мінімальний Message-like об'єкт для відновлення таймерів після рестарту."""

    class _ProxyChat:
        def __init__(self, chat_id: int):
            self.id = chat_id

    def __init__(self, bot: Bot, chat_id: int):
        self.bot = bot
        self.chat = self._ProxyChat(chat_id)

    async def answer(self, text: str, **kwargs):
        return await self.bot.send_message(chat_id=self.chat.id, text=text, **kwargs)

# ПП між парними ролями (лікар/сестра, комісар/сержант) — відповіді в ЛС з parse_mode=html + emoji_to_premium
PLAY_PM_ALLY_DEAD = (
    "☠️Ти залишився сам. Твого союзника вже прибрали, допомоги чекати нізвідки."
)
PLAY_PM_ALLY_LINK_LOST = (
    "☠️Зв'язок розірвано. Твого союзника не знайдено серед живих або його прізвище викреслене."
)
PLAY_PM_NO_CHAT_RIGHTS = (
    "🔇Ти не маєш права голосу. Або партія вже закінчена, або твоє прізвище викреслене зі списку живих."
)
PLAY_PM_PARTNER_NONE = (
    "🚨Ти одинак. У цій грі в тебе немає напарників. Розраховуй тільки на свої сили."
)
PLAY_PM_PARTNER_DEAD = (
    "💀Ти залишився сам. Твого напарника вже прибрали. Тепер вся відповідальність на тобі."
)
PLAY_PM_SEND_FAILED = (
    "🚨Зв'язок обірвано. Твоє повідомлення не дійшло до адресата. Спробуй ще раз."
)

# Останнє слово (ПП / смерть при вже завершеній партії)
PLAY_LAST_WORD_ALIVE_ONLY = (
    "☠️Твій час ще не настав.  Право на останню заяву мають лише ті, кого вже немає з нами. Ти поки що дихаєш."
)
PLAY_LAST_WORD_GAME_OVER = (
    "⌛️Запізно для сповіді. Партія завершена. Твоє останнє слово так і залишиться несказаним."
)
PLAY_LAST_WORD_PRIVATE_ONLY = (
    "📄Дотримуйся конфіденційності. Твоє останнє слово має бути почуте лише через приватний канал зв'язку з ботом."
)


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


# Короткі репліки під час реєстрації в гру (атмосферні жарти з емодзі)
REGISTRATION_JOKES = [
    "В цьому місті навіть мовчання може бути роллю.",
    "Аль Капоне боявся не кулі - а податкової. Тут - ще й нічного чату.",
    "Коханка знає більше, ніж детектив. Просто говорить менше.",
    "У сицилійській мафії “рандом” - це коли ти вижив.",
    "Коза Ностра має кодекс честі. У вас - ще й бафи.",
    "Якщо тобі дали 🎩 - ти або геній, або дуже пощастило.",
    "Маніяк у грі - це як лаг: з’являється раптово і псує всім життя.",
    "Лакі Лучано створив структуру мафії. Ви створили структуру хаосу.",
    "Найнебезпечніша роль - та, яку всі недооцінюють.",
    "У сицилійській мафії навіть волоцюга може пережити всіх.",
    "Якщо тебе не вбили вночі - значить, ти ще потрібен.",
    "Джон Готті любив увагу. У вас це смертельно.",
    "Бафи не роблять тебе безсмертним. Вони роблять тебе цікавішою ціллю.",
    "Тут “довіра” - це тимчасовий дебафф.",
    "Сицилійський адвокат може врятувати тебе… або просто красиво пояснити, чому ні.",
    "Якщо в грі тихо - значить, хтось уже щось вирішив.",
    "Сухий закон у США створив мафію. Наш бот - нові причини сваритись.",
    "Тут навіть щасливчик іноді не такий вже й щасливий.",
    "Найкраща стратегія - виглядати безкорисним.",
    "Сицилійська мафія не поспішає. Вона чекає, поки ти сам зробиш помилку.",
    "Якщо ти впевнений, що виграєш - ти або новий, або вже програв.",
    "У мафії є ієрархія. Тут - ще й нічні сюрпризи.",
    "Парфум - єдина зброя, яка пахне проблемами.",
    "Якщо в чаті всі згодні - шукай брехуна.",
    "У сицилійській мафії є правило: якщо перейшов дорогу 🐈‍⬛ - значить, гра тільки починається.",
]

# Пінгачок при /play: згадки в чаті (HTML-посилання tg://user?id=…)
# Пачки надсилаються у фоні - не блокують таймер реєстрації.
REGISTRATION_PING_ENABLED = False  # тимчасово вимкнено
REGISTRATION_PING_MAX_USERS = 1000
REGISTRATION_PING_CHUNK_SIZE = 6  # тегів у одному повідомленні
REGISTRATION_PING_CHUNK_DELAY_SEC = 1.0  # одна пачка пінгів раз на секунду (не швидко)
REGISTRATION_PING_DELETE_AFTER_SEC = 60  # через скільки секунд видалити кожне пінг-повідомлення (1 хв)
# Обмеження викликів get_chat_member (інакше сотні API-запитів «вішають» подію)
REGISTRATION_PING_MAX_API_LOOKUPS = 120
# Емодзі перед кожною згадкою (циклічно)
PING_MENTION_EMOJIS = ("🎭", "🃏", "🎩", "🌙", "🔫", "🎲")

# ID власників бота (завжди мають права власника)
BOT_OWNER_IDS = [1859870653]


def _is_bot_owner_id(user_id: int) -> bool:
    return user_id in BOT_OWNER_IDS


def _chat_is_private_msg(chat) -> bool:
    """У різних версіях aiogram type може бути ChatType або рядок (як у founder._chat_is_private)."""
    if not chat:
        return False
    t = chat.type
    return t == ChatType.PRIVATE or t == "private"


def _user_awaiting_vip_gift_or_refund_dm(user_id: int | None) -> bool:
    """
    ПП з вводом @username для подарунку VIP або текстом для рефанду.
    router_play реєструється раніше за router_pay — інакше ці повідомлення «з'їдають»
    мафія/лікар/комісар під час активної гри.
    """
    if user_id is None:
        return False
    try:
        from commands.buy import refund_awaiting_user_ids, vip_gift_awaiting

        if user_id in vip_gift_awaiting or user_id in refund_awaiting_user_ids:
            return True
    except Exception:
        pass
    return False


def _format_game_duration_uk(start: Optional[datetime]) -> Optional[str]:
    """Людськочитабельна тривалість для фінального повідомлення (наївний локальний час)."""
    if start is None:
        return None
    try:
        end = datetime.now()
        st = start.replace(tzinfo=None) if getattr(start, "tzinfo", None) else start
        sec = int(max(0, (end - st).total_seconds()))
    except Exception:
        return None
    if sec < 60:
        return f"{sec} с" if sec > 0 else "менше хвилини"
    total_m = sec // 60
    h, m = total_m // 60, total_m % 60
    if h:
        return f"{h} год {m} хв" if m else f"{h} год"
    return f"{m} хв"


class PlayCommand:
    def __init__(self):
        self.router_play = Router()
        # Окремий роутер з найвищим пріоритетом у dp - щоб «останнє слово» не перехопили founder/roulette/support тощо.
        self.router_last_word = Router(name="last_word")
        self.router_last_word.message.register(
            self.last_message,
            lambda message: self._is_last_message(message),
        )
        # Пінгачок: активні користувачі по чатах (user_id -> last_seen_ts).
        # Тримаємо окремо від GameState, щоб не створювати "фантомні" стани для чатів без ігор.
        self._ping_recent_users: dict[int, dict[int, float]] = {}
        # Пінгачок: opt-out по чатах (хто написав «Анрег»).
        self._ping_opt_out_ids: dict[int, set[int]] = {}
        # Серійний доступ до «останнього слова» по групі - інакше два швидкі ПП дають подвійний пост у групі.
        self._last_word_locks: dict[int, asyncio.Lock] = {}
        # Вибір Лікаря: два швидкі натискання могли обидва пройти doctor_action_taken до встановлення → дубль «Карета» в групі.
        self._doctor_heal_locks: dict[int, asyncio.Lock] = {}
        # AFK-автовибір під час денного голосування: серіалізуємо бот-вибір, щоб не дублювати голоси.
        self._afk_vote_pick_locks: dict[int, asyncio.Lock] = {}
        # Події «збір дропа» у каналах/групах: message_key -> state.
        self._loot_drop_events: dict[str, dict] = {}

        self.router_play.message.register(self.play_cmd, Command("play"))
        self.router_play.message.register(self.force_start_game, Command("start_game", "startgame"))
        self.router_play.message.register(self.start_cmd_link, CommandStart(deep_link=True))
        self.router_play.message.register(
            self.join_game_cmd,
            F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]),
            Command("join"),
        )
        self.router_play.message.register(
            self.players_cmd,
            F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]),
            Command("players"),
        )
        self.router_play.message.register(
            self.end_discussion_cmd,
            F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]),
            Command("end_discussion"),
        )
        self.router_play.message.register(self.leave_game_cmd, Command("leave_game", "leave"))
        self.router_play.message.register(self.carry_on_cmd, Command("carry_on"))
        self.router_play.message.register(self.set_registration_time_cmd, Command("set_registration_time"))
        self.router_play.message.register(self.stop_game_cmd, Command("stop_game", "cancelgame", "cancel_game"))
        self.router_play.message.register(self.test_endgame_cmd, Command("test_endgame"))
        # Тестові команди для різних екранів
        self.router_play.message.register(self.test_day_ui_cmd, Command("test_day_ui"))
        self.router_play.message.register(self.test_night_ui_cmd, Command("test_night_ui"))
        self.router_play.message.register(self.top_mafia_cmd, Command("top_mafia", "mafia_top"))
        self.router_play.message.register(self.top_mafia_week_cmd, Command("top_mafia_week", "mafia_top_week"))

        # Відписка через «Анрег» / /unreg вимкнена.
        self.router_play.message.register(
            self._track_chat_activity,
            F.chat.type.in_(["supergroup", "group"]),
            F.text,
            F.func(self._should_track_chat_activity),
        )
        # Пінгачок: збір нових учасників (service message "joined") - дозволяє тегати навіть тих, хто не писав.
        self.router_play.message.register(
            self._track_new_chat_members,
            F.chat.type.in_(["supergroup", "group"]),
            F.new_chat_members,
        )
        self.router_play.message.register(
            self.left_chat_member_game_handler,
            F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]),
            F.left_chat_member,
        )
        # Дозволяє гравцю додати себе в пінг-список (для тегів у /play)
        self.router_play.message.register(self.ping_collect_me_cmd, Command("ping_collect"))
        self.router_play.message.register(self.ping_collect_me_cmd, Command("ping_collect_me"))
        # /ping_add_to_chat: у ПП - chat_id + user_id; у групі - лише user_id або reply (тільки адміни)
        self.router_play.message.register(
            self.ping_add_to_chat_cmd,
            Command("ping_add_to_chat"),
        )
        self.router_play.message.register(self.test_day_cmd, Command("test_day"))
        self.router_play.message.register(self.test_night_cmd, Command("test_night"))
        self.router_play.message.register(self.test_voting_ui_cmd, Command("test_voting_ui"))
        self.router_play.message.register(
            self.loot_drop_cmd,
            F.chat.type.in_([ChatType.PRIVATE, ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]),
            Command("loot_drop", "drop_loot"),
        )
        self.router_play.message.register(
            self.test_premium_emoji_cmd,
            F.chat.type.in_([ChatType.PRIVATE, ChatType.GROUP, ChatType.SUPERGROUP]),
            Command("test_premium_emoji"),
        )
        # Fallback для клієнтів, де Command-фільтр інколи не матчить або коли пишуть без пробілу: /loot_drop-100... 1
        self.router_play.message.register(
            self.loot_drop_cmd,
            F.chat.type.in_([ChatType.PRIVATE, ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL]),
            F.text.regexp(r"^/(?:loot_drop|drop_loot)(?:@\w+)?(?:\s+.*|-\d.*)?$"),
        )
        # Робимо фільтр більш "м'яким", щоб матчило і "/test_start", і "/test_start 5"
        # (деякі клієнти/форматування можуть давати аргументи інакше, ніж очікує Command()).
        self.router_play.message.register(
            self.test_start_cmd,
            F.text.regexp(r"^/test_start(?:@\w+)?(?:\s+\d+)?\s*$"),
        )

        self.router_play.callback_query.register(self.yes_btn, F.data == "answer_1")
        self.router_play.callback_query.register(self.no_btn, F.data == "answer_2")

        # Register mafia private message handler
        self.router_play.message.register(self.mafia_private_message, lambda message: self._is_mafia_private_message(message))
        
        # Register doctor-nurse private message handler
        self.router_play.message.register(self.doctor_nurse_private_message, lambda message: self._is_doctor_nurse_private_message(message))
        # Register commissioner-sergeant private message handler
        self.router_play.message.register(self.commissioner_sergeant_private_message, lambda message: self._is_commissioner_sergeant_private_message(message))
        
        # Register silenced player message handler (blocks messages from silenced players in group chat)
        self.router_play.message.register(self.silenced_message_handler, lambda message: self._is_silenced_message(message))
        # Повідомлення від мертвих гравців (опційно: видаляти під час гри)
        self.router_play.message.register(self.dead_player_message_handler, lambda message: self._is_dead_player_message_during_game(message))
        # Повідомлення від тих, хто не грає - видалити, мут на 1 хв, повідомлення в ПП
        self.router_play.message.register(self.non_player_message_handler, lambda message: self._is_non_player_message_during_game(message))

        self.router_play.callback_query.register(self.like_def, F.data == "like")
        self.router_play.callback_query.register(self.dislike_def, F.data == "dislike")
        
        # Register vote handler once in __init__
        self.router_play.callback_query.register(self.chosen_candidate_handler, F.data.startswith("vote_"))
        # Skip discussion button
        self.router_play.callback_query.register(self.skip_discussion, F.data == "skip_discussion")
        
        # Register doctor patient selection handler once in __init__
        self.router_play.callback_query.register(self.chosen_patient_handler, F.data.endswith("_cured"))
        self.router_play.callback_query.register(
            self.journalist_target_pick_handler,
            F.data.regexp(r"^-?\d+_\d+_journal$"),
        )
        self.router_play.callback_query.register(
            self.night_standard_target_callback,
            F.data.regexp(
                r"^(-?\d+)_(\d+)_(protect|check|maniac|homeless|lawyer|clown|infect|deceiver|sadistic_heal|sadistic_kill|maf_killed|killed)$"
            ),
        )
        self.router_play.callback_query.register(
            self.portal_night_target_callback,
            F.data.startswith("portal_night:"),
        )
        self.router_play.callback_query.register(
            self.commissioner_mode_pick_callback,
            F.data.regexp(r"^comm_mode_(check|kill)_(-?\d+)$"),
        )
        self.router_play.callback_query.register(
            self.commissioner_check_target_callback,
            F.data.regexp(r"^comm_check_(-?\d+)_(\d+)$"),
        )
        self.router_play.callback_query.register(
            self.commissioner_kill_target_callback,
            F.data.regexp(r"^comm_kill_(-?\d+)_(\d+)$"),
        )
        self.router_play.callback_query.register(
            self.commissioner_back_callback,
            F.data.regexp(r"^comm_back_(-?\d+)$"),
        )
        self.router_play.callback_query.register(
            self.custom_ability_choose_callback,
            F.data.regexp(r"^custom_ability_choose_(-?\d+)_(\d+)_(.+)$"),
        )
        self.router_play.callback_query.register(
            self.custom_ability_target_callback,
            F.data.regexp(r"^custom_ability_(-?\d+)_(\d+)_(\d+)_(.+)$"),
        )
        self.router_play.callback_query.register(
            self.sadistic_mode_entry_callback,
            F.data.regexp(r"^sadistic_(heal|kill)_(-?\d+)_(\d+)$"),
        )
        # ── Купальська ніч: нічні дії Русалки та Мисливця ──
        self.router_play.callback_query.register(
            self.kupala_mermaid_ability_callback, F.data.regexp(r"^kr_mab:(-?\d+):(\d+):(flow|protect)$")
        )
        self.router_play.callback_query.register(
            self.kupala_flow_a_callback, F.data.regexp(r"^kr_flowa:(-?\d+):(\d+):(\d+)$")
        )
        self.router_play.callback_query.register(
            self.kupala_flow_b_callback, F.data.regexp(r"^kr_flowb:(-?\d+):(\d+):(\d+):(\d+)$")
        )
        self.router_play.callback_query.register(
            self.kupala_protect_callback, F.data.regexp(r"^kr_protect:(-?\d+):(\d+):(\d+)$")
        )
        self.router_play.callback_query.register(
            self.kupala_hunter_ability_callback, F.data.regexp(r"^kr_hab:(-?\d+):(\d+):(silence|harpoon)$")
        )
        self.router_play.callback_query.register(
            self.kupala_silence_callback, F.data.regexp(r"^kr_silence:(-?\d+):(\d+):(\d+)$")
        )
        self.router_play.callback_query.register(
            self.kupala_harpoon_callback, F.data.regexp(r"^kr_harpoon:(-?\d+):(\d+):(\d+)$")
        )

        # Register kamikaze choice handler once in __init__
        self.router_play.callback_query.register(self.chosen_kamikaze_handler, F.data.startswith("kamikaze_"))
        
        # Register item use handler for active items during night
        self.router_play.callback_query.register(self.item_use_handler, F.data.startswith("item_use:"))
        # Ліхтарик - вибір гравця для перевірки відвідувачів
        self.router_play.callback_query.register(self.flashlight_handler, F.data.startswith("flashlight:"))
        # Заточка - спочатку кнопка, потім вибір цілі
        self.router_play.callback_query.register(self.knife_menu_handler, F.data.startswith("knife_menu:"))
        # Заточка - миттєве вбивство вибраного гравця
        self.router_play.callback_query.register(self.knife_kill_handler, F.data.startswith("knife_kill:"))
        # Дуель (налаштування) - кнопка виклику та вибір опонента
        self.router_play.callback_query.register(self.duel_menu_handler, F.data.startswith("duelcall_menu:"))
        self.router_play.callback_query.register(self.duel_call_handler, F.data.startswith("duelcall_pick:"))
        # Диявол: пропозиція контракту, прийняття/відмова, вибір двох жертв контрактником
        self.router_play.callback_query.register(self.devil_callback_handler, F.data.startswith("devil_"))
        # Коханка: вибір цілі для блоку (стабільний хендлер, без реєстрації на кожну кнопку)
        self.router_play.callback_query.register(
            self.prostitute_block_choice_handler,
            F.data.regexp(r"^-?\d+_\d+_block$"),
        )
        # Чорний кіт Коханки - лише один хендлер на префікс (інакше кожен виклик prostitute_block додає копії → подвійні «нюхи»)
        self.router_play.callback_query.register(
            self.prostitute_bc_learn_callback,
            F.data.startswith("prostitute_bc_learn:"),
        )
        self.router_play.callback_query.register(
            self.prostitute_bc_close_callback,
            F.data.startswith("prostitute_bc_close:"),
        )
        self.router_play.callback_query.register(
            self.clown_shuffle_all_callback,
            F.data.startswith("clown_shuffle_all:"),
        )
        self.router_play.callback_query.register(
            self.loot_drop_collect_callback,
            F.data == "loot_drop_collect",
        )
        # Night action skip handlers
        self.router_play.callback_query.register(
            self.skip_night_action_handler,
            F.data.startswith("skip_night_"),
        )

    @staticmethod
    def _loot_drop_key(chat_id: int, message_id: int) -> str:
        return f"{chat_id}:{message_id}"

    def _loot_drop_button_text(self, remaining: int, limit: int) -> str:
        return f"Зібрати • {remaining}/{limit}"

    def _loot_drop_markup(self, remaining: int, limit: int) -> InlineKeyboardMarkup:
        dice_cid = custom_emoji_id_for_symbol("🎲")
        btn_kwargs: dict = {
            "text": self._loot_drop_button_text(remaining, limit),
            "callback_data": "loot_drop_collect",
        }
        if dice_cid:
            btn_kwargs["icon_custom_emoji_id"] = dice_cid
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(**btn_kwargs)]])

    def _get_random_regular_buff_id(self) -> str | None:
        candidates = [
            item_id
            for item_id, item in ITEMS.items()
            if getattr(item.category, "value", "") == "cheap" and not item_id.startswith("portal_")
        ]
        if not candidates:
            return None
        return random.choice(candidates)

    @staticmethod
    def _premium_symbol(symbol: str) -> str:
        # Беремо emoji-id тільки з premium_emoji.py (CUSTOM_EMOJI_MAP).
        cid = custom_emoji_id_for_symbol(symbol)
        if cid:
            return f'<tg-emoji emoji-id="{cid}">{symbol}</tg-emoji>'
        return symbol

    async def loot_drop_cmd(self, message: Message, bot: Bot):
        if not message.chat:
            return
        if not message.from_user:
            try:
                await message.answer("Не можу визначити, хто запускає команду.")
            except Exception:
                pass
            return
        source_chat_id = message.chat.id
        if not _is_bot_owner_id(message.from_user.id):
            await message.answer(
                "Цю команду можуть запускати лише засновники бота.",
                protect_content=True,
            )
            return

        target_chat_id = source_chat_id
        limit = 100
        is_private = _chat_is_private_msg(message.chat)
        text_raw = (message.text or "").strip()
        parts = text_raw.split()
        self.print_log(
            f"🎲 loot_drop_cmd: uid={message.from_user.id}, src_chat={source_chat_id}, "
            f"is_private={is_private}, text={message.text!r}"
        )
        compact_match = re.match(
            r"^/(?:loot_drop|drop_loot)(?:@\w+)?(?P<chat>-\d+)(?:\s+(?P<limit>\d+))?\s*$",
            text_raw,
        )
        if compact_match and is_private:
            try:
                target_chat_id = int(compact_match.group("chat"))
                if compact_match.group("limit"):
                    limit = int(compact_match.group("limit"))
                parts = ["/loot_drop", str(target_chat_id), str(limit)]
            except Exception:
                pass
        if is_private:
            if len(parts) < 2:
                await message.answer(
                    "Формат у ПП: <code>/loot_drop &lt;channel_id&gt; [кількість]</code>\n"
                    "Приклад: <code>/loot_drop -1001234567890 100</code>",
                    parse_mode="html",
                    protect_content=True,
                )
                return
            try:
                target_chat_id = int(parts[1])
            except Exception:
                await message.answer(
                    "Невірний channel_id. Приклад: <code>-1001234567890</code>",
                    parse_mode="html",
                    protect_content=True,
                )
                return
            if len(parts) > 2:
                try:
                    limit = int(parts[2])
                except Exception:
                    await message.answer(
                        "Невірна кількість. Формат: <code>/loot_drop -1001234567890 100</code>",
                        parse_mode="html",
                        protect_content=True,
                    )
                    return
        elif len(parts) > 1:
            try:
                limit = int(parts[1])
            except Exception:
                await message.answer(
                    "Формат: <code>/loot_drop [кількість]</code>\nПриклад: <code>/loot_drop 100</code>",
                    parse_mode="html",
                    protect_content=True,
                )
                return
        if limit < 1 or limit > 1000:
            await message.answer("Кількість має бути від 1 до 1000.", protect_content=True)
            return
        self.print_log(
            f"🎲 loot_drop_cmd parsed: target_chat_id={target_chat_id}, limit={limit}, parts={parts}"
        )

        active_text = (
            f"{self._premium_symbol('🚗')}Під час втечі один із злодіїв проронив декілька цінних речей\n\n"
        )
        try:
            sent = await bot.send_message(
                chat_id=target_chat_id,
                text=active_text,
                parse_mode="html",
                reply_markup=self._loot_drop_markup(limit, limit),
                protect_content=True,
            )
        except Exception as e:
            self.print_log(
                f"❌ loot_drop_cmd send_message failed: target_chat_id={target_chat_id}, "
                f"limit={limit}, error={e!r}"
            )
            await message.answer(
                "Не вдалося опублікувати в канал/чат.\n"
                "Перевір, що bot є адміном і channel_id правильний.\n\n"
                f"Помилка: <code>{html.escape(str(e))}</code>",
                parse_mode="html",
                protect_content=True,
            )
            return

        if is_private:
            try:
                await message.answer(
                    f"Опубліковано розіграш у чат: <code>{target_chat_id}</code>\n"
                    f"Ліміт: <b>{limit}</b>",
                    parse_mode="html",
                    protect_content=True,
                )
            except Exception:
                pass
        key = self._loot_drop_key(sent.chat.id, sent.message_id)
        self._loot_drop_events[key] = {
            "limit": limit,
            "claimed_user_ids": set(),
            "closed": False,
            "lock": asyncio.Lock(),
        }

    async def test_premium_emoji_cmd(self, message: Message, bot: Bot):
        if not message.from_user:
            return
        if not _is_bot_owner_id(message.from_user.id):
            await message.answer("Команда лише для засновників.")
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(
                "Формат: <code>/test_premium_emoji &lt;chat_id&gt;</code>\n"
                "Приклад: <code>/test_premium_emoji -1001991387701</code>",
                parse_mode="html",
            )
            return
        try:
            target_chat_id = int(parts[1])
        except Exception:
            await message.answer("Невірний chat_id.")
            return

        # Тестуємо саме ті emoji-id, що зараз лежать у premium_emoji.py.
        sample = (
            "Тест premium emoji у каналі:\n"
            f"{self._premium_symbol('🚗')} {self._premium_symbol('🎲')} {self._premium_symbol('💰')}"
        )
        try:
            await bot.send_message(
                chat_id=target_chat_id,
                text=sample,
                parse_mode="html",
                protect_content=True,
            )
            await message.answer("Тест відправлено.")
        except Exception as e:
            await message.answer(
                f"Помилка відправки: <code>{html.escape(str(e))}</code>",
                parse_mode="html",
            )

    async def loot_drop_collect_callback(self, callback: CallbackQuery, bot: Bot):
        if not callback.message or not callback.from_user:
            await callback.answer()
            return
        chat_id = callback.message.chat.id
        message_id = callback.message.message_id
        key = self._loot_drop_key(chat_id, message_id)
        event = self._loot_drop_events.get(key)
        if not event:
            await callback.answer("Розіграш вже неактивний.", show_alert=True)
            return

        lock = event.get("lock")
        if not isinstance(lock, asyncio.Lock):
            lock = asyncio.Lock()
            event["lock"] = lock

        async with lock:
            if event.get("closed"):
                await callback.answer("Вже завершено.", show_alert=False)
                return

            claimed_user_ids = event.get("claimed_user_ids")
            if not isinstance(claimed_user_ids, set):
                claimed_user_ids = set()
                event["claimed_user_ids"] = claimed_user_ids

            user_id = callback.from_user.id
            if user_id in claimed_user_ids:
                await callback.answer("Цю здобич можна зібрати лише 1 раз.", show_alert=True)
                return

            limit = int(event.get("limit", 0) or 0)
            if limit <= 0:
                event["closed"] = True
                await callback.answer("Розіграш завершено.", show_alert=False)
                return
            if len(claimed_user_ids) >= limit:
                event["closed"] = True
                await callback.answer("Все вже зібрали.", show_alert=False)
                return

            claimed_user_ids.add(user_id)
            reward_text = ""
            if random.choice([True, False]):
                krb = random.randint(60, 220)
                await add_balance_to_user_async(user_id, krb)
                reward_text = f"Ти забрав {krb} лір."
            else:
                buff_id = self._get_random_regular_buff_id()
                if not buff_id:
                    krb = random.randint(60, 220)
                    await add_balance_to_user_async(user_id, krb)
                    reward_text = f"Ти забрав {krb} лір."
                else:
                    ok, buff_name = await run_db_call_async(admin_grant_buff_to_user, user_id, buff_id)
                    if ok:
                        item = ITEMS.get(buff_id)
                        buff_emoji = item.emoji if item else "🎁"
                        reward_text = f"Ти забрав баф: {buff_emoji} {buff_name}."
                    else:
                        krb = random.randint(60, 220)
                        await add_balance_to_user_async(user_id, krb)
                        reward_text = f"Ти забрав {krb} лір."

            taken = len(claimed_user_ids)
            remaining = max(0, limit - taken)

            if remaining <= 0:
                event["closed"] = True
                finished_text = (
                    f"{self._premium_symbol('🤠')} Сім'я вже прибрала зайвого, стежте за новинами, можливо хтось буде ще на стільки ж необачним."
                )
                try:
                    await callback.message.edit_text(
                        finished_text,
                        parse_mode="html",
                        reply_markup=None,
                    )
                except Exception:
                    pass
                await callback.answer(reward_text, show_alert=True)
                return

            try:
                await callback.message.edit_reply_markup(
                    reply_markup=self._loot_drop_markup(remaining, limit)
                )
            except Exception:
                pass
            await callback.answer(reward_text, show_alert=True)

    @staticmethod
    def _sync_devil_contract_on_player_elimination(state: GameState, player_id: int) -> None:
        """Скидає незавершений контракт і дозволяє нову пропозицію, якщо з гри вибуває контрактник, адресат ПП-пропозиції або Диявол."""
        holders = getattr(state, "devil_contract_holders", None)
        if holders is None:
            return
        offered = int(getattr(state, "devil_contract_offered_id", 0) or 0)
        pending = int(getattr(state, "devil_contract_pending", 0) or 0)
        souls = int(getattr(state, "devil_souls_brought", 0) or 0)
        devil_id_now = int(getattr(state, "devil_id", 0) or 0)

        def wipe_active_incomplete() -> None:
            state.devil_contract_pending = 0
            state.devil_kill_targets = []
            state.devil_souls_brought = 0
            state.devil_contract_action_taken = False
            state.devil_contract_start_night = 0
            if getattr(state, "devil_first_kill_id", 0):
                state.devil_first_kill_id = 0

        if offered == player_id and player_id not in holders:
            state.devil_contract_offered_id = 0
            state.devil_offered_this_game = False
            return

        if devil_id_now == player_id:
            reset_offer = False
            if offered and offered not in holders:
                state.devil_contract_offered_id = 0
                reset_offer = True
            if pending and souls < 2:
                nh = set(holders)
                nh.discard(pending)
                state.devil_contract_holders = nh
                wipe_active_incomplete()
                reset_offer = True
            if reset_offer:
                state.devil_offered_this_game = False
            return

        if pending == player_id and souls < 2:
            nh = set(holders)
            nh.discard(player_id)
            state.devil_contract_holders = nh
            wipe_active_incomplete()
            state.devil_offered_this_game = False
            return

        if player_id in holders:
            nh = set(holders)
            nh.discard(player_id)
            state.devil_contract_holders = nh
    
    def _get_state(self, chat_id: int) -> GameState:
        """Get game state for a specific chat"""
        return game_state_manager.get_state(chat_id)
    
    @staticmethod
    def _group_chat_link(chat_id: int, message_id: int | None = None) -> str:
        """
        Посилання на групу для кнопки «Перейти в групу».
        
        Якщо чат - супергрупа (chat_id починається з -100) і відомий message_id,
        повертаємо web‑посилання формату https://t.me/c/<internal>/<message_id>  - 
        воно стабільно працює і на Desktop, і на Mobile.

        Інакше використовуємо deep‑link `tg://openmessage?chat_id=...`.
        """
        try:
            cid = int(chat_id)
            if message_id and cid < 0 and str(cid).startswith("-100"):
                internal = str(cid)[4:]  # прибираємо "-100"
                return f"https://t.me/c/{internal}/{int(message_id)}"
            return f"tg://openmessage?chat_id={cid}"
        except Exception:
            return "https://t.me/sicilian_mafia_bot"
    
    def _is_group_blocked(self, chat_id: int) -> bool:
        """Legacy sync helper (kept for compatibility)."""
        if not game_state_manager.has_state(chat_id):
            return False
        state = self._get_state(chat_id)
        return bool(getattr(state, "group_blocked", False))

    async def _is_group_blocked_async(self, chat_id: int) -> bool:
        row = await self._db_fetchone(
            "SELECT is_blocked FROM admin_panel WHERE group_id = %s",
            (chat_id,),
        )
        if row:
            return row[0] if row[0] is not None else False
        return False

    def _is_group_registered_via_construct(self, chat_id: int) -> bool:
        """Legacy sync helper (kept for compatibility)."""
        return game_state_manager.has_state(chat_id)
    
    def _is_last_message(self, message: Message) -> bool:
        """Check if message is last message for any active game"""
        if not message.from_user or not message.chat:
            return False
        # Команди (наприклад /profile, /help, /construct_event) не перехоплюємо - даємо доступ до бота після гри
        if message.text and message.text.strip().startswith("/"):
            return False
        # Якщо повідомлення з приватного чату, шукаємо групу, де очікується останнє повідомлення від цього гравця
        if _chat_is_private_msg(message.chat):
            user_id = message.from_user.id
            # Не перехоплювати ПП, коли користувач вводить @username для подарунку VIP, ID рефанду чи текст тікета —
            # router_last_word іде першим у dp, інакше ці сценарії «німіють» під час гри.
            try:
                from commands.buy import refund_awaiting_user_ids, vip_gift_awaiting

                if user_id in vip_gift_awaiting or user_id in refund_awaiting_user_ids:
                    return False
            except Exception:
                pass
            try:
                from commands.support import support_awaiting_description

                if user_id in support_awaiting_description:
                    return False
            except Exception:
                pass
            try:
                from commands.construct_event import user_awaits_construct_private_text_input

                if user_awaits_construct_private_text_input(user_id):
                    return False
            except Exception:
                pass
            # Спершу по всіх станах де is_last_message (навіть якщо game_active вже False), щоб не втратити повідомлення
            if game_state_manager.get_chat_awaiting_last_message_from(user_id) is not None:
                return True
            active_chats = game_state_manager.get_all_active_chats()
            for chat_id in active_chats:
                state = self._get_state(chat_id)
                allowed = set(getattr(state, "last_word_allowed_ids", set()) or set())
                if (state.is_last_message and state.victim_id == user_id) or (user_id in allowed):
                    return True
            return False
        else:
            # Якщо повідомлення з групи, перевіряємо стан цієї групи
            # Але останнє повідомлення має бути тільки в приватних повідомленнях
            return False
    
    def _is_mafia_private_message(self, message: Message) -> bool:
        """Check if message is from mafia or Don in private chat during active game"""
        if not _chat_is_private_msg(message.chat):
            return False
        # Skip commands
        if message.text and message.text.startswith("/"):
            return False
        # Skip if it's last message
        if self._is_last_message(message):
            return False
        if _user_awaiting_vip_gift_or_refund_dm(getattr(message.from_user, "id", None)):
            return False

        user_id = message.from_user.id
        active_chats = game_state_manager.get_all_active_chats()

        for chat_id in active_chats:
            state = self._get_state(chat_id)
            if not state.game_active:
                continue

            # Check if user is Don (Аль Капоне) or Mafia
            if user_id == state.all_capone_id or user_id in state.mafia_ids:
                if user_id in state.membersList:
                    return True

        return False

    def _is_founder_like(self, user_id: int) -> bool:
        """Базова перевірка доступу для тестових/адмінських команд.
        Дозволяємо власників бота або будь-кого, хто є активним засновником у БД (таблиця founders).
        """
        if _is_bot_owner_id(user_id):
            return True
        return self._is_founder(user_id)
    
    def _is_doctor_nurse_private_message(self, message: Message) -> bool:
        """Check if message is from doctor or nurse in private chat during active game"""
        if not _chat_is_private_msg(message.chat):
            return False
        
        # Skip commands
        if message.text and message.text.startswith("/"):
            return False
        
        # Skip if it's last message
        if self._is_last_message(message):
            return False
        if _user_awaiting_vip_gift_or_refund_dm(getattr(message.from_user, "id", None)):
            return False
        
        user_id = message.from_user.id
        active_chats = game_state_manager.get_all_active_chats()
        
        for chat_id in active_chats:
            state = self._get_state(chat_id)
            if not state.game_active:
                continue
            
            # Check if user is Doctor or Nurse
            is_doctor = (user_id == state.doctor_id)
            is_nurse = (user_id == state.nurse_id and state.nurse_id != state.doctor_id)
            
            if is_doctor or is_nurse:
                if user_id in state.membersList:
                    return True
        
        return False
    
    def _is_commissioner_sergeant_private_message(self, message: Message) -> bool:
        """Check if message is from Commissioner or Sergeant in private chat during active game"""
        if not _chat_is_private_msg(message.chat):
            return False
        if message.text and message.text.startswith("/"):
            return False
        if self._is_last_message(message):
            return False
        if _user_awaiting_vip_gift_or_refund_dm(getattr(message.from_user, "id", None)):
            return False
        user_id = message.from_user.id
        active_chats = game_state_manager.get_all_active_chats()
        for chat_id in active_chats:
            state = self._get_state(chat_id)
            if not state.game_active:
                continue
            is_commissioner = (user_id == state.commissioner_id)
            is_sergeant = (user_id == state.sheriff_id)
            if is_commissioner or is_sergeant:
                if user_id in state.membersList:
                    return True
        return False

    @staticmethod
    def _is_group_chat_service_update(message: Message) -> bool:
        """Service-оновлення чату (вхід/вихід учасника тощо) — не мовчанка і не «повідомлення гравця»."""
        if getattr(message, "new_chat_members", None):
            return True
        if getattr(message, "left_chat_member", None):
            return True
        return False
    
    def _is_silenced_message(self, message: Message) -> bool:
        """Check if message is from a silenced player in group chat during active game"""
        # Only check group/supergroup messages
        if message.chat.type not in ["group", "supergroup"]:
            return False
        if self._is_group_chat_service_update(message):
            return False
        if not message.from_user:
            return False
        
        # Skip bot commands
        if message.text and message.text.startswith("/"):
            return False
        
        # Skip admin commands (+адмін, -адмін) - вони мають оброблятися окремо
        if message.text:
            text_lower = message.text.strip().lower()
            if text_lower.startswith("+адмін") or text_lower.startswith("-адмін"):
                print(f"[play]  _is_silenced_message: пропускаємо команду '+адмін' для chat_id={message.chat.id}")
                return False
        
        # Skip if message is from bot
        if message.from_user.is_bot:
            return False
        
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Check if there's an active game in this chat
        if not game_state_manager.has_state(chat_id):
            return False
        
        state = self._get_state(chat_id)
        if not state.game_active:
            return False
        
        # Check if user is silenced
        return user_id in state.silenced_ids

    async def _get_silence_settings_async(self, chat_id: int, state: Optional[GameState] = None) -> tuple[bool, bool]:
        """
        Повертає налаштування мовчанки:
        (silence_dead_players_enabled, silence_non_players_enabled)
        """
        state = state or self._get_state(chat_id)
        row = await self._db_fetchone(
            "SELECT silence_dead_players_enabled, silence_non_players_enabled "
            "FROM admin_panel WHERE group_id = %s LIMIT 1",
            (chat_id,),
        )
        dead_players = bool(row[0]) if row and row[0] is not None else True
        non_players = bool(row[1]) if row and row[1] is not None else True
        state.silence_dead_players_enabled = dead_players
        state.silence_non_players_enabled = non_players
        return dead_players, non_players

    def _is_dead_player_message_during_game(self, message: Message) -> bool:
        """Повідомлення від мертвого гравця під час активної гри (опційна мовчанка для мертвих)."""
        if message.chat.type not in ["group", "supergroup"]:
            return False
        if not message.from_user or message.from_user.is_bot:
            return False
        if self._is_group_chat_service_update(message):
            return False
        if message.text and (message.text.strip().startswith("/") or
                            message.text.strip().lower().startswith("+адмін") or
                            message.text.strip().lower().startswith("-адмін")):
            return False
        chat_id = message.chat.id
        if not game_state_manager.has_state(chat_id):
            return False
        state = self._get_state(chat_id)
        if not state.game_active:
            return False
        user_id = message.from_user.id
        roster_ids = {pid for pid, _ in (state.all_membersNames or [])}
        return user_id in roster_ids and user_id not in state.membersList

    def _is_non_player_message_during_game(self, message: Message) -> bool:
        """Повідомлення в групі від користувача, який не бере участі в поточній грі (гра вже почалась)."""
        if message.chat.type not in ["group", "supergroup"]:
            return False
        if not message.from_user or message.from_user.is_bot:
            return False
        if self._is_group_chat_service_update(message):
            return False
        if message.text and (message.text.strip().startswith("/") or
                            message.text.strip().lower().startswith("+адмін") or
                            message.text.strip().lower().startswith("-адмін")):
            return False
        chat_id = message.chat.id
        if not game_state_manager.has_state(chat_id):
            return False
        state = self._get_state(chat_id)
        if not state.game_active:
            return False
        user_id = message.from_user.id
        return user_id not in state.membersList

    def _is_unreg_trigger(self, message: Message) -> bool:
        # Команда/тригер відписки вимкнені.
        return False

    def _blocked_ping_user_ids(self, chat_id: int) -> set[int]:
        """Хто відписався від пінгів: пам'ять процесу + БД (після рестарту бота лишається в БД)."""
        blocked = set(self._ping_opt_out_ids.get(chat_id) or set())
        try:
            blocked |= ping_opt_out_ids_for_chat(int(chat_id))
        except Exception:
            pass
        return blocked

    def _should_track_chat_activity(self, message: Message) -> bool:
        """
        Трекінг пінгачка тільки для звичайних повідомлень, які не є командами.
        ВАЖЛИВО: під час активної гри не трекаємо тут взагалі, щоб не перехоплювати
        non_player_message_handler/silenced_message_handler.
        """
        if not message.text:
            return False
        text = message.text.strip()
        if not text or text.startswith("/"):
            return False
        chat_id = message.chat.id
        if game_state_manager.has_state(chat_id):
            state = self._get_state(chat_id)
            if state.game_active:
                return False
        return True

    
    def print_log(self, text):
        color = "\033[32m"
        RESET = "\033[0m"
        frame = inspect.currentframe().f_back  # Отримуємо попередній кадр
        print(f"{color} {text} {RESET} File: '{frame.f_code.co_filename}', line {frame.f_lineno} ")

    async def _db_execute_commit(self, query: str, params: tuple = ()) -> None:
        def _run():
            import database.database as _db  # «живі» посилання після можливого переконекту
            _db.cursor.execute(query, params)
            _db.conn.commit()
        await run_db_call_async(_run)

    async def _db_fetchone(self, query: str, params: tuple = ()):
        def _run():
            import database.database as _db
            _db.cursor.execute(query, params)
            return _db.cursor.fetchone()
        return await run_db_call_async(_run)

    async def _db_fetchall(self, query: str, params: tuple = ()):
        def _run():
            import database.database as _db
            _db.cursor.execute(query, params)
            return _db.cursor.fetchall()
        return await run_db_call_async(_run)

    async def _ensure_mafia_top_tables(self) -> None:
        await self._db_execute_commit(
            """
            CREATE TABLE IF NOT EXISTS mafia_game_results (
                game_key TEXT PRIMARY KEY,
                group_id BIGINT NOT NULL,
                winner TEXT,
                ended_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self._db_execute_commit(
            """
            CREATE TABLE IF NOT EXISTS mafia_player_results (
                id BIGSERIAL PRIMARY KEY,
                game_key TEXT NOT NULL,
                group_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                is_winner BOOLEAN NOT NULL DEFAULT FALSE,
                recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(game_key, user_id)
            )
            """
        )
        await self._db_execute_commit(
            "CREATE INDEX IF NOT EXISTS idx_mafia_game_results_group_time ON mafia_game_results(group_id, ended_at DESC)"
        )
        await self._db_execute_commit(
            "CREATE INDEX IF NOT EXISTS idx_mafia_player_results_group_user ON mafia_player_results(group_id, user_id)"
        )

    async def _backfill_mafia_games_from_legacy(self) -> None:
        # Історичні ігри зберігалися у casino_rounds. Переносимо їх у новий реєстр ігор мафії.
        # game_key детермінований, тому вставка безпечна при повторному запуску.
        await self._db_execute_commit(
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

    async def _record_mafia_game_stats(self, chat_id: int, winner: str, roster_data: list[dict]) -> None:
        if not roster_data:
            return
        await self._ensure_mafia_top_tables()
        game_key = f"{chat_id}:{int(datetime.utcnow().timestamp() * 1000)}:{random.randint(1000, 9999)}"
        await self._db_execute_commit(
            "INSERT INTO mafia_game_results (game_key, group_id, winner) VALUES (%s, %s, %s) ON CONFLICT (game_key) DO NOTHING",
            (game_key, int(chat_id), str(winner or "")),
        )
        for rec in roster_data:
            uid = int(rec.get("player_id") or 0)
            if not uid:
                continue
            is_winner = bool(rec.get("is_winner"))
            await self._db_execute_commit(
                """
                INSERT INTO mafia_player_results (game_key, group_id, user_id, is_winner)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (game_key, user_id) DO NOTHING
                """,
                (game_key, int(chat_id), uid, is_winner),
            )

    async def _render_group_top_text(self, chat_id: int, weekly: bool = False) -> str:
        await self._ensure_mafia_top_tables()
        try:
            await self._backfill_mafia_games_from_legacy()
        except Exception:
            pass
        period_sql = "AND g.ended_at >= date_trunc('week', CURRENT_TIMESTAMP)" if weekly else ""
        total_games_row = await self._db_fetchone(
            """
            SELECT COUNT(*)::BIGINT
            FROM mafia_game_results
            WHERE group_id = %s
            """
            + (" AND ended_at >= date_trunc('week', CURRENT_TIMESTAMP)" if weekly else ""),
            (int(chat_id),),
        )
        total_games = int(total_games_row[0] or 0) if total_games_row else 0
        rows = await self._db_fetchall(
            f"""
            SELECT
                r.user_id,
                COALESCE(u.tg_name, 'Гравець') AS tg_name,
                COUNT(*)::BIGINT AS games_count,
                COALESCE(SUM(CASE WHEN r.is_winner THEN 1 ELSE 0 END), 0)::BIGINT AS wins_count
            FROM mafia_player_results r
            JOIN mafia_game_results g ON g.game_key = r.game_key
            LEFT JOIN users u ON u.id = r.user_id
            WHERE r.group_id = %s {period_sql}
            GROUP BY r.user_id, u.tg_name
            """,
            (int(chat_id),),
        ) or []
        if not rows:
            if total_games > 0:
                period_text = "з понеділка" if weekly else "загалом"
                return (
                    "🏁 <b>Топ гравців у мафію</b>\n\n"
                    f"🎮 <b>Ігор {period_text}:</b> <b>{total_games}</b>\n\n"
                    f"Знайдено історичні ігри {period_text}, "
                    "але для старого періоду немає персонального складу гравців.\n"
                    "Топ по гравцях почне наповнюватись після нових завершених ігор."
                )
            if weekly:
                return "🏁 <b>Топ з понеділка</b>\n\nПоки немає зіграних ігор у цій групі."
            return "🏁 <b>Топ гравців у мафію</b>\n\nПоки немає завершених ігор у цій групі."

        min_games_for_top = 15
        eligible_rows = [r for r in rows if int(r[2] or 0) >= min_games_for_top]
        unified_sorted = sorted(
            eligible_rows,
            key=lambda x: (
                int(x[3] or 0),  # перемоги
                int(x[2] or 0),  # ігри
                (float(int(x[3] or 0)) / float(int(x[2] or 1))) if int(x[2] or 0) > 0 else 0.0,  # winrate
            ),
            reverse=True,
        )[:15]
        title = "🏁 <b>Топ з понеділка</b>" if weekly else "🏁 <b>Топ гравців у мафію</b>"
        lines = [
            title,
            f"🎮 <b>Ігор за період:</b> <b>{total_games}</b>",
            "",
            "📊 <b>Єдиний топ</b>",
        ]
        if not unified_sorted:
            lines.append("Немає даних.")
            return "\n".join(lines)
        for i, (uid, name, games_cnt, wins_cnt) in enumerate(unified_sorted, 1):
            link = vip_mod.html_user_link(int(uid), str(name or "Гравець"))
            games_n = int(games_cnt or 0)
            wins_n = int(wins_cnt or 0)
            winrate = (wins_n / games_n * 100.0) if games_n > 0 else 0.0
            lines.append(
                f"{i}. {link} - 🎮 <b>{games_n}</b> | 🏆 <b>{wins_n}</b> | 📈 <b>{winrate:.1f}%</b>"
            )
        return "\n".join(lines)

    async def top_mafia_cmd(self, message: Message, bot: Bot):
        if message.chat.type not in ("group", "supergroup"):
            await message.answer("Ця команда працює лише в груповому чаті.")
            return
        text = await self._render_group_top_text(message.chat.id, weekly=False)
        await message.answer(emoji_to_premium(text, skip_vip_badges=False), parse_mode="html")

    async def top_mafia_week_cmd(self, message: Message, bot: Bot):
        if message.chat.type not in ("group", "supergroup"):
            await message.answer("Ця команда працює лише в груповому чаті.")
            return
        text = await self._render_group_top_text(message.chat.id, weekly=True)
        await message.answer(emoji_to_premium(text, skip_vip_badges=False), parse_mode="html")

    async def _track_chat_activity(self, message: Message, bot: Bot):
        """
        Трекінг активності користувачів у чаті для пінгачка.
        - Додає user_id до recent_chat_users.
        - Якщо юзер був в opt-out і написав щось (крім «Анрег») - знову дозволяємо тегати.
        """
        if message.chat.type not in ["supergroup", "group"]:
            return
        if not message.from_user:
            return
        # Не трекаємо повідомлення ботів, інакше пінгачок починає тегати лише бота.
        if getattr(message.from_user, "is_bot", False):
            return
        chat_id = message.chat.id
        user_id = message.from_user.id
        now_ts = datetime.now().timestamp()
        by_chat = self._ping_recent_users.get(chat_id)
        if by_chat is None:
            by_chat = {}
            self._ping_recent_users[chat_id] = by_chat
        by_chat[user_id] = now_ts
        # Ліміт, щоб не рости безкінечно (залишаємо найсвіжіших)
        if len(by_chat) > 1500:
            try:
                self._ping_recent_users[chat_id] = dict(
                    sorted(by_chat.items(), key=lambda kv: kv[1], reverse=True)[:1000]
                )
            except Exception:
                pass
        if message.text and not self._is_unreg_trigger(message):
            opt = self._ping_opt_out_ids.get(chat_id)
            if opt and user_id in opt:
                opt.discard(user_id)
            try:
                await ping_opt_out_remove_async(chat_id, user_id)
            except Exception:
                pass

    async def _track_new_chat_members(self, message: Message, bot: Bot):
        """
        Трекінг користувачів, які щойно зайшли в чат.
        Telegram надсилає service message з new_chat_members - це працює навіть тоді,
        коли звичайні повідомлення можуть не доходити (Privacy Mode).
        """
        if message.chat.type not in ["supergroup", "group"]:
            return
        chat_id = message.chat.id
        members = getattr(message, "new_chat_members", None) or []
        if not members:
            return
        # Автоприв'язка /construct_event при додаванні саме цього бота в групу.
        # Робимо тут (а не в construct_event), бо цей handler гарантовано отримує service-подію.
        try:
            me = await bot.get_me()
            my_id = int(me.id)
            added_ids = {int(u.id) for u in members if u and getattr(u, "id", None) is not None}
            if my_id in added_ids:
                existing = await self._db_fetchone(
                    "SELECT 1 FROM admin_panel WHERE group_id = %s LIMIT 1",
                    (chat_id,),
                )
                exists = existing is not None
                if not exists:
                    creator_id = None
                    try:
                        admins = await bot.get_chat_administrators(chat_id)
                        for adm in admins or []:
                            if getattr(adm, "status", None) == ChatMemberStatus.CREATOR and getattr(adm, "user", None):
                                creator_id = int(adm.user.id)
                                break
                    except Exception:
                        creator_id = None
                    # Fallback для нових/малих чатів: перевіряємо того, хто додав бота.
                    if creator_id is None:
                        try:
                            inviter = getattr(message, "from_user", None)
                            if inviter and getattr(inviter, "id", None):
                                try:
                                    inv_member = await bot.get_chat_member(chat_id, int(inviter.id))
                                    if getattr(inv_member, "status", None) == ChatMemberStatus.CREATOR:
                                        creator_id = int(inviter.id)
                                except Exception:
                                    # Останній fallback: у service-події додавання бота вважаємо,
                                    # що додав власник (типовий сценарій для особистих груп на 2 учасники).
                                    creator_id = int(inviter.id)
                        except Exception:
                            creator_id = None
                    if creator_id is not None:
                        await self._db_execute_commit(
                            "INSERT INTO admin_panel (creator_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                            (creator_id, chat_id),
                        )
        except Exception:
            pass
        now_ts = datetime.now().timestamp()
        by_chat = self._ping_recent_users.get(chat_id)
        if by_chat is None:
            by_chat = {}
            self._ping_recent_users[chat_id] = by_chat
        for u in members:
            try:
                if not u or getattr(u, "is_bot", False):
                    continue
                by_chat[int(u.id)] = now_ts
                # Пінгачок: фіксуємо в БД, щоб тегати навіть тих, хто не писав саме зараз
                try:
                    await ping_members_add_async(chat_id, int(u.id))
                except Exception:
                    pass
            except Exception:
                continue
        # Ліміт, щоб не рости безкінечно (залишаємо найсвіжіших)
        if len(by_chat) > 1500:
            try:
                self._ping_recent_users[chat_id] = dict(
                    sorted(by_chat.items(), key=lambda kv: kv[1], reverse=True)[:1000]
                )
            except Exception:
                pass


    async def _answer_with_retry(self, message: Message, *args, max_retries: int = 5, **kwargs):
        """Відправити повідомлення в чат з повторними спробами при flood control і коротких мережевих збоях."""
        max_retries = kwargs.pop("max_retries", max_retries)
        # За замовчуванням захищаємо контент від пересилання, якщо явно не вимкнуто
        kwargs.setdefault("protect_content", True)
        flood_left = max(1, int(max_retries))
        net_left = 4
        last_exc = None
        while flood_left > 0 or net_left > 0:
            try:
                return await message.answer(*args, **kwargs)
            except asyncio.CancelledError:
                raise
            except TelegramRetryAfter as e:
                last_exc = e
                flood_left -= 1
                if flood_left <= 0:
                    raise
                self.print_log(
                    f"⚠️ Flood control (SendMessage): чекаємо {e.retry_after} с (залишилось спроб flood: {flood_left})"
                )
                await asyncio.sleep(e.retry_after)
            except TelegramNetworkError as e:
                last_exc = e
                net_left -= 1
                if net_left <= 0:
                    raise
                delay = min(3.0, 0.5 * (5 - net_left))
                self.print_log(
                    f"⚠️ Мережа Telegram (SendMessage), повтор через {delay:.1f}s (залишилось {net_left}): {e}"
                )
                await asyncio.sleep(delay)
        if last_exc:
            raise last_exc

    async def unreg_ping_cmd(self, message: Message, bot: Bot):
        """
        Команда-відписка від пінгачка.
        Якщо користувач напише «Анрег» у групі - ми більше не тегатимемо його при /play,
        поки він знову щось не напише в чат.
        """
        if not message.text or not self._is_unreg_trigger(message):
            return
        if not message.from_user:
            return
        chat_id = message.chat.id
        user_id = message.from_user.id
        opt = self._ping_opt_out_ids.get(chat_id)
        if opt is None:
            opt = set()
            self._ping_opt_out_ids[chat_id] = opt
        opt.add(user_id)
        try:
            await ping_opt_out_add_async(chat_id, user_id)
        except Exception:
            pass
        reply = None
        try:
            reply = await message.reply(
                "🔕 <b>Виклики вимкнено</b>\n"
                "Тебе більше не кличуть у гру.\n\n",
                parse_mode="html",
                protect_content=True,
            )
        except Exception:
            pass

        # Через хвилину видаляємо і команду, і відповідь бота (якщо вони ще є)
        async def _cleanup_unreg(chat_id: int, user_msg_id: int, reply_msg_id: int | None):
            await asyncio.sleep(60)
            try:
                await bot.delete_message(chat_id=chat_id, message_id=user_msg_id)
            except Exception:
                pass
            if reply_msg_id:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=reply_msg_id)
                except Exception:
                    pass

        try:
            asyncio.create_task(_cleanup_unreg(chat_id, message.message_id, reply.message_id if reply else None))
        except Exception:
            pass

    async def ping_collect_me_cmd(self, message: Message):
        """
        Дозволяє гравцю додати себе в persistent ping-список для цього чату.
        Ідея: коли в БД є список користувачів, /play може тегати навіть тих,
        хто не писав у чат.
        """
        if not message.from_user or not message.chat:
            return
        if message.chat.type not in ["supergroup", "group"]:
            try:
                await message.answer(
                    "Цю команду треба запускати в групі / супергрупі під час гри.",
                    parse_mode="html",
                    protect_content=True,
                )
            except Exception:
                pass
            return
        chat_id = message.chat.id
        user_id = message.from_user.id
        try:
            await ping_members_add_async(chat_id, user_id)
        except Exception as e:
            self.print_log(f"⚠️ ping_members_add error: {e}")

        # Якщо людина раніше відмовилась від пінгів («Анрег»), дозволимо знову
        try:
            opt = self._ping_opt_out_ids.get(chat_id)
            if opt and user_id in opt:
                opt.discard(user_id)
        except Exception:
            pass
        try:
            await ping_opt_out_remove_async(chat_id, user_id)
        except Exception:
            pass

        try:
            await message.answer(
                "📌 <b>Внесено в пінг-список</b>.\n"
                "Тепер пінгачок може тегати тебе під час <code>/play</code>.\n\n"
                "Команди: <code>/ping_collect_me</code> або <code>/ping_collect</code>.",
                parse_mode="html",
                protect_content=True,
            )
        except Exception as e:
            self.print_log(f"⚠️ ping_collect_me_cmd message.answer error: {e}")

    async def ping_add_to_chat_cmd(self, message: Message, bot: Bot):
        """
        ПП: /ping_add_to_chat <chat_id> <user_id> [user_id...] - для вказаної групи.
        Група: тільки адміни - reply на повідомлення або /ping_add_to_chat <user_id> [user_id...]
        для поточного чату.
        """
        try:
            if not message.text or not message.from_user or not message.chat:
                return
            caller_id = message.from_user.id
            chat = message.chat
            parts = message.text.strip().split()

            user_id_values: list[int] = []
            chat_id: int | None = None

            if _chat_is_private_msg(chat):
                if len(parts) < 3:
                    await message.answer(
                        "<b>У приватному чаті з ботом:</b>\n"
                        "<code>/ping_add_to_chat &lt;chat_id&gt; &lt;user_id&gt;</code>\n\n"
                        "Приклад:\n"
                        "<code>/ping_add_to_chat -1001991387701 1859870653</code>\n\n"
                        "<b>У групі</b> (як адмін): відповідай на повідомлення і надішли "
                        "<code>/ping_add_to_chat</code> або вкажи id: "
                        "<code>/ping_add_to_chat 1859870653</code>",
                        parse_mode="html",
                        protect_content=True,
                    )
                    return
                try:
                    chat_id = int(parts[1])
                except Exception:
                    await message.answer(
                        "Невірний <code>chat_id</code>. Має бути число (наприклад <code>-1001234567890</code>).",
                        parse_mode="html",
                        protect_content=True,
                    )
                    return
                for raw in parts[2:]:
                    raw = (raw or "").strip()
                    if not raw:
                        continue
                    try:
                        user_id_values.append(int(raw))
                    except Exception:
                        continue
                if not user_id_values:
                    await message.answer(
                        "Не знайшов user_id. Формат:\n"
                        "<code>/ping_add_to_chat &lt;chat_id&gt; &lt;user_id&gt; [&lt;user_id&gt;...]</code>",
                        parse_mode="html",
                        protect_content=True,
                    )
                    return
                if not _is_bot_owner_id(caller_id):
                    if not await self._is_chat_admin(bot, chat_id, caller_id):
                        await message.answer(
                            "⚠️ Додавати в пінг-список може тільки власник бота або адміністратор <b>того</b> чату (chat_id).",
                            parse_mode="html",
                            protect_content=True,
                        )
                        return

            elif chat.type in ("group", "supergroup"):
                chat_id = chat.id
                if not _is_bot_owner_id(caller_id):
                    if not await self._is_chat_admin(bot, chat_id, caller_id):
                        await message.answer(
                            "⚠️ У групі додавати інших у пінг-список можуть лише адміністратори.\n\n"
                            "Щоб додати <b>себе</b>, використай <code>/ping_collect_me</code> "
                            "або <code>/ping_collect</code> - це може будь-хто.",
                            parse_mode="html",
                            protect_content=True,
                        )
                        return
                if message.reply_to_message and message.reply_to_message.from_user:
                    ru = message.reply_to_message.from_user
                    if not getattr(ru, "is_bot", False):
                        user_id_values.append(ru.id)
                for raw in parts[1:]:
                    raw = (raw or "").strip()
                    if not raw:
                        continue
                    try:
                        user_id_values.append(int(raw))
                    except Exception:
                        continue
                if not user_id_values:
                    await message.answer(
                        "<b>Додати людей у пінг-список цієї групи</b>\n\n"
                        "1) Відповідай на повідомлення людини і надішли <code>/ping_add_to_chat</code>\n"
                        "2) Або вкажи Telegram id: <code>/ping_add_to_chat 123456789</code>\n"
                        "3) Кілька id: <code>/ping_add_to_chat 111 222</code>\n\n"
                        "Щоб додати себе (без адмін): <code>/ping_collect_me</code>",
                        parse_mode="html",
                        protect_content=True,
                    )
                    return
            else:
                return

            # Щоб не валити БД довжелезними списками, обмежимо розмір.
            user_id_values = list(dict.fromkeys(user_id_values))
            MAX_IDS = 200
            if len(user_id_values) > MAX_IDS:
                user_id_values = user_id_values[:MAX_IDS]

            added_count = 0
            for user_id in user_id_values:
                await ping_members_add_async(chat_id, user_id)
                added_count += 1
                try:
                    opt = self._ping_opt_out_ids.get(chat_id)
                    if opt and user_id in opt:
                        opt.discard(user_id)
                except Exception:
                    pass
                try:
                    await ping_opt_out_remove_async(chat_id, user_id)
                except Exception:
                    pass

            await message.answer(
                f"Додано в пінг-список: <b>{added_count}</b> гравців.\n"
                f"chat_id: <code>{chat_id}</code>\n"
                f"user_ids: <code>{', '.join(map(str, user_id_values))}</code>",
                parse_mode="html",
                protect_content=True,
            )
        except Exception as e:
            self.print_log(f"⚠️ ping_add_to_chat_cmd error: {e}")
            try:
                await message.answer(
                    "Помилка при додаванні в пінг-список.",
                    protect_content=True,
                )
            except Exception:
                pass

    async def _send_registration_ping_messages(self, bot: Bot, chat_id: int) -> None:
        """
        Пінги після /play у фоні - не блокує старт і оновлення таймера реєстрації.
        У тексті лише емодзі-посилання (tg://user) - імена Telegram у повідомленні не показуються;
        пачки по REGISTRATION_PING_CHUNK_SIZE (зараз 6).
        """
        if not REGISTRATION_PING_ENABLED:
            return
        try:
            state = self._get_state(chat_id)
            recent_map = self._ping_recent_users.get(chat_id) or {}
            candidate_ids = set(recent_map.keys())
            try:
                candidate_ids |= set(await ping_members_get_recent_async(chat_id, limit=400))
            except Exception:
                pass
            try:
                candidate_ids |= set(getattr(state, "membersList", []) or [])
            except Exception:
                pass
            members_map: dict[int, str] = {}

            if not candidate_ids:
                last_roster = getattr(state, "last_game_membersNames", None) or getattr(state, "all_membersNames", []) or []
                members_map = {uid: name for uid, name in last_roster}
                candidate_ids = set(members_map.keys())
                try:
                    candidate_ids |= set(getattr(state, "last_game_membersList", []) or [])
                except Exception:
                    pass
            blocked = self._blocked_ping_user_ids(chat_id)
            ping_ids = [uid for uid in candidate_ids if uid not in blocked]
            try:
                ping_ids = [uid for uid in ping_ids if uid != bot.id]
            except Exception:
                pass
            ping_ids = sorted(ping_ids)[:REGISTRATION_PING_MAX_USERS]

            mentions: list[str] = []
            api_lookups = 0
            emojis = PING_MENTION_EMOJIS
            ne = len(emojis) if emojis else 1

            for mention_idx, uid in enumerate(ping_ids):
                # Ім'я добираємо лише щоб при потребі відсікти ботів через get_chat_member
                name = members_map.get(uid)
                if not name:
                    try:
                        row = await self._db_fetchone(
                            "SELECT tg_name FROM users WHERE id = %s",
                            (uid,),
                        )
                        if row and row[0]:
                            name = row[0]
                    except Exception:
                        pass
                if not name and api_lookups < REGISTRATION_PING_MAX_API_LOOKUPS:
                    try:
                        m = await bot.get_chat_member(chat_id, uid)
                        api_lookups += 1
                        if m and getattr(m, "user", None):
                            if getattr(m.user, "is_bot", False):
                                continue
                    except Exception:
                        pass
                emoji = emojis[mention_idx % ne] if emojis else "👤"
                # Тільки емодзі в посиланні - пінг є, ім'я в чаті не світиться
                mentions.append(f"<a href='tg://user?id={uid}'>{emoji}</a>")

            if not mentions:
                return

            chunk_size = REGISTRATION_PING_CHUNK_SIZE
            mention_chunks = [mentions[i:i + chunk_size] for i in range(0, len(mentions), chunk_size)]

            async def _delete_ping_later(cid: int, message_id: int):
                await asyncio.sleep(REGISTRATION_PING_DELETE_AFTER_SEC)
                try:
                    await bot.delete_message(chat_id=cid, message_id=message_id)
                except Exception:
                    pass

            for idx, chunk in enumerate(mention_chunks):
                header = (
                    "Запускається нова гра в мафію. Хто в ділі?\n\n"
                    if idx == 0
                    else "Ще трошки гравців у ділі:\n\n"
                )
                text = emoji_to_premium(header + ", ".join(chunk))
                sent = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="html",
                    protect_content=True,
                )
                try:
                    asyncio.create_task(_delete_ping_later(chat_id, sent.message_id))
                except Exception:
                    pass
                if idx < len(mention_chunks) - 1 and REGISTRATION_PING_CHUNK_DELAY_SEC > 0:
                    await asyncio.sleep(REGISTRATION_PING_CHUNK_DELAY_SEC)
        except Exception as e:
            self.print_log(f"Помилка пінгачка при /play: {e}")

    def _collect_players_acted_this_night(self, state) -> set:
        """Збирає множину user_id гравців, які зробили хоч одну нічну дію в боті (для перевірки неактивності)."""
        acted = set()
        if state.mafia_action_taken:
            # Командний хід мафії (вибір цілі) вважаємо дією лише Аль Капоне.
            # Інакше підручні мафії помилково блокуються для особистих нічних дій (напр. заточки).
            if state.all_capone_id:
                acted.add(state.all_capone_id)
        for pid in getattr(state, "mafia_member_personal_night_done", set()) or []:
            acted.add(pid)
        if state.doctor_action_taken and state.doctor_id:
            acted.add(state.doctor_id)
        if state.guardian_action_taken and state.guardian_id:
            acted.add(state.guardian_id)
        if state.commissioner_action_taken and state.commissioner_id:
            acted.add(state.commissioner_id)
        if state.sheriff_action_taken and state.sheriff_id:
            acted.add(state.sheriff_id)
        if (state.block_action_taken or getattr(state, "prostitute_no_target_this_night", False)) and state.prostitute_id:
            acted.add(state.prostitute_id)
        if state.maniac_action_taken and state.maniac_id:
            acted.add(state.maniac_id)
        if state.sadistic_action_taken and getattr(state, "sadistic_doctor_id", 0):
            acted.add(state.sadistic_doctor_id)
        if state.clown_action_taken and state.clown_id:
            acted.add(state.clown_id)
        if state.infected_action_taken:
            for pid in getattr(state, "infected_ids", []) or []:
                acted.add(pid)
        if state.deceiver_action_taken and state.deceiver_id:
            acted.add(state.deceiver_id)
        if getattr(state, "devil_contract_action_taken", False) and getattr(state, "devil_contract_pending", 0):
            acted.add(state.devil_contract_pending)
        if getattr(state, "devil_contract_offered_id", 0) and state.devil_id:
            acted.add(state.devil_id)
        if getattr(state, "journalist_targets", None) and state.journalist_id:
            acted.add(state.journalist_id)
        if state.lawyer_client_id and state.lawyer_id:
            acted.add(state.lawyer_id)
        if getattr(state, "homeless_target_id", 0) and state.homeless_id:
            acted.add(state.homeless_id)
        # ── Купальська ніч: Русалка / Мисливець на русалку ──
        _mermaid = getattr(state, "mermaid_id", 0)
        if _mermaid and (
            getattr(state, "mermaid_redirect_a", 0)
            or getattr(state, "mermaid_protect_id", 0)
            or getattr(state, "mermaid_weakened", False)  # виснажена — не діє цю ніч, але не AFK
        ):
            acted.add(_mermaid)
        _hunter = getattr(state, "hunter_id", 0)
        if _hunter and (
            getattr(state, "hunter_silence_id", 0)
            or getattr(state, "hunter_harpoon_id", 0)
        ):
            acted.add(_hunter)
        return acted

    def _lock_night_role_action_for_user(self, state, user_id: int) -> None:
        """Блокує рольову нічну дію для гравця на поточну ніч (режим «або роль, або заточка»)."""
        if not user_id:
            return
        don_id = getattr(state, "all_capone_id", 0)
        if user_id == don_id:
            # Дон обрав заточку замість нічного вбивства - командний вибір «закрито»
            state.mafia_action_taken = True
        elif user_id in (getattr(state, "mafia_ids", []) or []):
            # Підручний мафії (заточка тощо) - лише особиста дія; Аль Капоне все ще обирає жертву
            personal = set(getattr(state, "mafia_member_personal_night_done", set()))
            personal.add(int(user_id))
            state.mafia_member_personal_night_done = personal
        if user_id == getattr(state, "doctor_id", 0):
            state.doctor_action_taken = True
        if user_id == getattr(state, "guardian_id", 0):
            state.guardian_action_taken = True
        if user_id == getattr(state, "commissioner_id", 0):
            state.commissioner_action_taken = True
        if user_id == getattr(state, "sheriff_id", 0):
            state.sheriff_action_taken = True
        if user_id == getattr(state, "prostitute_id", 0):
            state.block_action_taken = True
        if user_id == getattr(state, "maniac_id", 0):
            state.maniac_action_taken = True
        if user_id == getattr(state, "sadistic_doctor_id", 0):
            state.sadistic_action_taken = True
        if user_id == getattr(state, "clown_id", 0):
            state.clown_action_taken = True
        if user_id == getattr(state, "deceiver_id", 0):
            state.deceiver_action_taken = True
        if user_id in (getattr(state, "infected_ids", []) or []):
            state.infected_action_taken = True
        if user_id == getattr(state, "devil_contract_pending", 0):
            state.devil_contract_action_taken = True

    def _ensure_knife_role_locked_users(self, state) -> None:
        """Сумісність зі старими станами: користувачі, що обрали заточку цієї ночі."""
        if not hasattr(state, "knife_role_locked_users"):
            state.knife_role_locked_users = set()

    async def _night_timer_task(self, message: Message, bot: Bot):
        """Separate task to handle night timer and transition to day"""
        chat_id = message.chat.id
        state = self._get_state(chat_id)
        try:
            # #region agent log
            _log_debug('debug-session', 'run1', 'N1', 'play.py:_night_timer_task:start', 'Night timer task started', {
                'chat_id': chat_id,
                'night_number': state.night_number,
                'game_active': state.game_active
            })
            # #endregion
            afk_auto_choice_enabled = await self._is_afk_auto_choice_enabled_async(chat_id, state)
            now = datetime.now()
            started_at = getattr(state, "night_started_at", None) or now
            if not getattr(state, "night_started_at", None):
                state.night_started_at = started_at
            elapsed = max(0, (now - started_at).total_seconds())
            if afk_auto_choice_enabled:
                self.print_log(
                    f"⏳ Таск ночі запущено: {AFK_AUTO_CHOICE_TOTAL_SECONDS}с, "
                    f"автовибір на {AFK_AUTO_CHOICE_BOT_PICK_AT_SECONDS}с..."
                )
                if (
                    elapsed >= AFK_AUTO_CHOICE_BOT_PICK_AT_SECONDS
                    and not getattr(state, "afk_night_auto_choice_applied", False)
                ):
                    state = self._get_state(chat_id)
                    if state.game_active and not getattr(state, "day_active", False):
                        await self._auto_pick_night_actions_for_afk(chat_id, bot)
                        state.afk_night_auto_choice_applied = True
                elif not getattr(state, "afk_night_auto_choice_applied", False):
                    await asyncio.sleep(max(0, AFK_AUTO_CHOICE_BOT_PICK_AT_SECONDS - elapsed))
                    state = self._get_state(chat_id)
                    if state.game_active and not getattr(state, "day_active", False):
                        await self._auto_pick_night_actions_for_afk(chat_id, bot)
                        state.afk_night_auto_choice_applied = True
                state = self._get_state(chat_id)
                now = datetime.now()
                elapsed = max(0, (now - (getattr(state, "night_started_at", None) or now)).total_seconds())
                await asyncio.sleep(max(0, AFK_AUTO_CHOICE_TOTAL_SECONDS - elapsed))
            else:
                self.print_log("⏳ Таск ночі запущено, очікую 60 секунд...")
                await asyncio.sleep(max(0, 60 - elapsed))
            # #region agent log
            _log_debug('debug-session', 'run1', 'N1', 'play.py:_night_timer_task:after_sleep', 'Night timer woke up', {
                'chat_id': chat_id,
                'game_active': state.game_active
            })
            # #endregion
            self.print_log("⏰ Час ночі вийшов! Перевіряю умови...")
            
            # Check if game is still active (re-get state in case it changed)
            state = self._get_state(chat_id)
            if not state.game_active:
                self.print_log(f"⚠️ Гра неактивна, зупиняю таск ночі")
                return
            
            self.print_log(f" Гра активна, перевіряю умови перемоги...")
                
            # Check win conditions before day
            winner = await self.check_win_conditions_async(chat_id)
            if winner:
                self.print_log(f"🏆 Знайдено переможця: {winner}")
                bot = message.bot
                try:
                    await message.answer(
                        emoji_to_premium(
                            "🌅 <b>Світанок настав.</b>\n\n"
                            "Після нічних подій баланс сил остаточно змінився.\n"
                            "<b>Денна фаза пропускається, бо переможець уже визначений.</b>"
                        ),
                        parse_mode="html",
                    )
                except Exception:
                    pass
                await self._handle_game_end(message, bot, chat_id, winner)
                return
            
            # Announce transition to day phase in logs (без додаткового повідомлення в чат)
            self.print_log(f"🌙 Ніч завершується, оголошую результати...")
            
            state = self._get_state(chat_id)  # Re-get state
            # Виключення за 3 ночі поспіль без жодного вибору в боті. Не кікаємо ролі, у яких у боті немає нічних дій:
            # Мирний житель, Щасливчик, Камікадзе, Сержант, Мед. сестра, Самогубець, Мафія (вибір робить Дон).
            # Тематичне налаштування «Пропуск нічної дії»: не рахуємо AFK і не виключаємо (дія в ніч все одно скидає лічильник).
            allow_skip_night = await self._is_skip_night_action_allowed_async(chat_id, state)
            acted = self._collect_players_acted_this_night(state)
            day_voted = getattr(state, "day_voting_participants", set()) or set()
            acted_with_day_vote = acted | day_voted
            inactive_count = getattr(state, "inactive_nights_count", None) or {}
            kicked_list = getattr(state, "kicked_for_inactivity", None) or []
            state.inactive_nights_count = inactive_count
            state.kicked_for_inactivity = kicked_list
            _no_afk_kick_roles = (
                getattr(state, "name_of_civilian", "Мирний житель"), "Мирний житель", "Щасливчик",
                "Камікадзе", "Сержант", "Мед. сестра", "Самогубець", "Мафія"
            )
            for player_id in list(state.membersList):
                try:
                    row = await self._db_fetchone(
                        "SELECT role, tg_name, COALESCE(killed, 0) FROM users WHERE id = %s",
                        (player_id,),
                    )
                    if not row:
                        continue
                    role = (row[0] if row[0] else "").strip()
                    tg_name = (row[1] if len(row) > 1 else "Гравець") or "Гравець"
                    killed = int(row[2]) if len(row) > 2 else 0
                    if killed == 1:
                        continue  # Вже мертвий (повішений/вбитий) - не рахуємо неактивність і не викидаємо за AFK
                except Exception:
                    continue
                # Не кікаємо за AFK гравців зі стандартними ролями без дій +
                # взагалі ніколи не кікаємо за AFK кастомні ролі (які створені через /construct_event)
                if role in _no_afk_kick_roles:
                    continue
                # Перевірка: чи є роль кастомною для цього чату
                try:
                    custom_role_row = await self._db_fetchone(
                        "SELECT 1 FROM custom_roles WHERE group_id = %s AND role_name = %s AND is_default = FALSE",
                        (chat_id, role),
                    )
                    if custom_role_row:
                        # Кастомна роль - пропускаємо AFK-кік
                        continue
                except Exception:
                    # У випадку помилки не ризикуємо зайвими киками - теж пропускаємо
                    continue
                if player_id in acted_with_day_vote:
                    inactive_count[player_id] = 0
                else:
                    if allow_skip_night:
                        continue
                    prev = inactive_count.get(player_id, 0)
                    inactive_count[player_id] = prev + 1
                    if inactive_count[player_id] >= 3:
                        state.membersList = [p for p in state.membersList if p != player_id]
                        state.membersNames = [(p, n) for p, n in state.membersNames if p != player_id]
                        self._sync_devil_contract_on_player_elimination(state, player_id)
                        try:
                            await self._db_execute_commit(
                                "UPDATE users SET killed = 1 WHERE id = %s",
                                (player_id,),
                            )
                        except Exception as e:
                            self.print_log(f"⚠️ Помилка оновлення killed для {player_id}: {e}")
                        state.kicked_for_inactivity.append((player_id, tg_name, role))
                        inactive_count.pop(player_id, None)
                        self.print_log(f"🚪 Виключено за неактивність: {tg_name} (id={player_id})")
                        # Як при _kill_player: спадкування Дона / Комісара (інакше state і БД розходяться)
                        try:
                            if player_id in (state.mafia_ids or []):
                                state.mafia_ids.remove(player_id)
                            don_aliases = {
                                x for x in (getattr(state, "name_of_all_capone", None), "Аль Капоне") if x
                            }
                            if role in don_aliases or player_id == getattr(state, "all_capone_id", 0):
                                await self._elect_new_don_from_alive_mafia_async(
                                    state, bot, chat_id, dead_don_id=player_id, dm_old_don=False
                                )
                            if role == "Комісар Каттані" or player_id == getattr(
                                state, "commissioner_id", 0
                            ):
                                await self._promote_sergeant_to_commissioner_after_comm_death_async(
                                    state, bot, chat_id
                                )
                            if role in [getattr(state, "name_of_doctor", "Лікар"), "Лікар"] or player_id == getattr(
                                state, "doctor_id", 0
                            ):
                                await self._promote_nurse_to_doctor_after_doctor_death_async(state)
                            await self._refresh_state_role_ids_async(state)
                        except Exception as e:
                            self.print_log(f"⚠️ AFK: спадкування ролей після кіку: {e}")
            state.inactive_nights_count = inactive_count

            self.print_log(f"📊 Стан гри перед переходом до дня: game_active={state.game_active}, membersList={len(state.membersList)}")
            if state.game_active:
                self.print_log(f" Переходжу до day_function...")
                try:
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'N2', 'play.py:_night_timer_task:to_day', 'Transitioning to day_function', {
                        'chat_id': chat_id,
                        'game_active': state.game_active
                    })
                    # #endregion
                    await self.day_function(message, bot)
                except Exception as e:
                    self.print_log(f" ПОМИЛКА в day_function: {e}")
                    import traceback
                    self.print_log(traceback.format_exc())
            else:
                self.print_log(f"⚠️ Гра неактивна, не переходжу до дня")
        except Exception as e:
            self.print_log(f" КРИТИЧНА ПОМИЛКА в _night_timer_task: {e}")
            import traceback
            self.print_log(traceback.format_exc())


    async def night_function(self, message: Message, bot: Bot):
        chat_id = message.chat.id
        
        # Check if group is blocked
        if await self._is_group_blocked_async(chat_id):
            state = self._get_state(chat_id)
            await self._unmute_users_muted_during_game(bot, chat_id)
            state.game_active = False
            return
        
        state = self._get_state(chat_id)
        # Скидаємо флаг дня (день закінчився, почалася ніч)
        state.day_active = False

        # Розмутити всіх, кого замутили під час гри (щоб мут був лише на 1 хв, а не назавжди)
        await self._unmute_users_muted_during_game(bot, chat_id)

        url_button = InlineKeyboardButton(text="Перейти до бота", url="https://t.me/sicilian_mafia_bot")

        self.url_buttons = InlineKeyboardMarkup(inline_keyboard=[[url_button]])

        # Reset action tracking for this night
        state.reset_for_new_night()
        # Денний щит контракту діяв до кінця минулого дня - на старті нової ночі скидаємо
        state.devil_covenant_day_shield.clear()
        
        # Ініціалізуємо обробник ефектів предметів для ночі
        item_processor = ItemEffectProcessor(chat_id)

        # Капелюх КаПоне: застосувати до циклу по гравцях. Інакше portal_seeds_skip дає continue
        # на початку ітерації - гравець ніколи не потрапляє в smoke_grenade_activated_this_night.
        try:
            hat_scheduled = set(getattr(state, "capone_hat_scheduled_for_night", set()) or set())
            self.print_log(f"🎩 DEBUG: hat_scheduled at night start = {hat_scheduled}")
            if hat_scheduled:
                smoke_now = set(getattr(state, "smoke_grenade_activated_this_night", set()) or set())
                self.print_log(f"🎩 DEBUG: smoke_now before processing = {smoke_now}")
                members_set = {int(x) for x in (state.membersList or [])}
                self.print_log(f"🎩 DEBUG: members_set = {members_set}")
                for uid_hat in list(hat_scheduled):
                    try:
                        uid_hat = int(uid_hat)
                    except (TypeError, ValueError):
                        self.print_log(f"🎩 DEBUG: Failed to convert uid_hat to int: {uid_hat}")
                        hat_scheduled.discard(uid_hat)
                        continue
                    if uid_hat not in members_set:
                        self.print_log(f"🎩 DEBUG: uid_hat {uid_hat} not in members_set")
                        hat_scheduled.discard(uid_hat)
                        continue
                    try:
                        row = await self._db_fetchone(
                            "SELECT COALESCE(killed, 0) FROM users WHERE id = %s",
                            (uid_hat,),
                        )
                        if row and int(row[0]) == 1:
                            self.print_log(f"🎩 DEBUG: uid_hat {uid_hat} is already killed")
                            hat_scheduled.discard(uid_hat)
                            continue
                    except Exception as ex:
                        self.print_log(f"🎩 DEBUG: Exception checking killed status for {uid_hat}: {ex}")
                        pass
                    self.print_log(f"🎩 DEBUG: Adding {uid_hat} to smoke_now")
                    smoke_now.add(uid_hat)
                    hat_scheduled.discard(uid_hat)
                    try:
                        await bot.send_message(
                            chat_id=uid_hat,
                            text=emoji_to_premium(
                                "🎩 <b>Капелюх КаПоне</b> активовано!\n\n"
                                "Ти невидимий для всіх нічних дій цієї ночі."
                            ),
                            parse_mode="html",
                        )
                        self.print_log(f"🎩 DEBUG: Sent activation message to {uid_hat}")
                    except Exception as ex:
                        self.print_log(f"🎩 DEBUG: Failed to send message to {uid_hat}: {ex}")
                        pass
                self.print_log(f"🎩 DEBUG: Final smoke_now = {smoke_now}")
                self.print_log(f"🎩 DEBUG: Final hat_scheduled = {hat_scheduled}")
                state.capone_hat_scheduled_for_night = hat_scheduled
                state.smoke_grenade_activated_this_night = smoke_now
            else:
                self.print_log(f"🎩 DEBUG: No hats scheduled for this night")
        except Exception as e:
            self.print_log(f"⚠️ capone_hat (старт ночі): {e}")
            import traceback
            self.print_log(f"⚠️ capone_hat traceback: {traceback.format_exc()}")
        
        # #region agent log
        _log_debug('debug-session', 'run1', 'N0', 'play.py:night_function:entry', 'night_function called', {
            'chat_id': chat_id,
            'night_number': state.night_number,
            'game_active': state.game_active
        })
        # #endregion
        
        # Одне повідомлення: відео ночі (night.mp4) з текстом у підписі, або лише текст
        night_announcement = (
            f"🌃 <b>НІЧ {state.night_number}</b> 🌃\n\n"
            "<blockquote>Місто засинає. У провулках Палермо гасне світло, "
            "а десь у темряві тихо клацає затвор.\n"
            "Замкни двері й молись, щоб світанок застав тебе живим.</blockquote>\n\n"
            "<i>Що ж принесе цей світанок?</i> 🤔"
        )
        # Пріоритет — піксельарт-анімація ночі (Media/night.gif) через send_animation.
        night_sent_media = await self._send_phase_media(
            bot, chat_id, 'night', night_announcement, reply_markup=self.url_buttons
        )
        media_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Media'))
        night_video = os.path.join(media_dir, 'night.mp4')
        path_to_send = None
        if not night_sent_media and os.path.isfile(night_video):
            path_to_send = await self._prepare_video_9_16(night_video) or night_video
        for attempt in range(3):
            if night_sent_media:
                break
            try:
                if path_to_send and os.path.isfile(path_to_send):
                    await bot.send_video(
                        chat_id=chat_id,
                        video=FSInputFile(path_to_send),
                        caption=night_announcement,
                        parse_mode="html",
                        reply_markup=self.url_buttons,
                    )
                else:
                    await message.answer(
                        night_announcement,
                        reply_markup=self.url_buttons,
                        parse_mode="html"
                    )
                break
            except TelegramRetryAfter as e:
                self.print_log(f"⚠️ Flood control при нічному анонсі: чекаємо {e.retry_after} с (спроба {attempt + 1}/3)")
                await asyncio.sleep(e.retry_after)
            except Exception as e:
                self.print_log(f"⚠️ Не вдалося надіслати night.mp4: {e}")
                try:
                    await message.answer(night_announcement, reply_markup=self.url_buttons, parse_mode="html")
                except Exception:
                    pass
                break
            finally:
                if path_to_send and path_to_send != night_video:
                    try:
                        os.unlink(path_to_send)
                    except OSError:
                        pass

        # Завантаження налаштувань ролей з БД
        # ВАЖЛИВО: Ініціалізуємо значення за замовчуванням ПЕРЕД запитом до БД
        state.name_of_doctor = "Лікар"
        state.description_of_doctor = "Ти - лікар! Рятуй гравців вночі."
        state.name_of_all_capone = "Аль Капоне"
        state.description_of_all_capone = "Ти - Аль Капоне! Вбивай гравців вночі."
        state.name_of_civilian = "Мирний житель"
        state.description_of_civilian = "Ти - мирний житель! Знайди мафію."
        
        creator_result = await self._db_fetchone(
            "SELECT creator_id FROM admin_panel WHERE group_id = %s",
            (chat_id,),
        )
        creator_id = creator_result[0] if creator_result else None

        if creator_id:
            result = await self._db_fetchone(
                "SELECT doctor, doctor_text, all_capone, all_capone_text, civilian, civilian_text FROM admin_panel WHERE creator_id = %s AND group_id = %s",
                (creator_id, chat_id),
            )
            if result:
                if result[0]:
                    state.name_of_doctor = result[0]
                if result[1]:
                    state.description_of_doctor = result[1]
                if result[2]:
                    state.name_of_all_capone = result[2]
                if result[3]:
                    state.description_of_all_capone = result[3]
                if result[4]:
                    state.name_of_civilian = result[4]
                if result[5]:
                    state.description_of_civilian = result[5]
        
        # Обробка предметів: невидимість (ціль недоступна для нічних дій)
        # ВАЖЛИВО: "невидимість" має блокувати дії ПО ЦІЛІ, але не позбавляти гравця його власного ходу.
        
        # Синхронізуємо усі role-id з БД до циклу (портал/«насіння» роблять continue до оновлення стану —
        # інакше all_capone_id / mafia_ids лишаються «вчорашніми»: мафія без кнопки вбивства, Сержант без перевірки).
        await self._refresh_state_role_ids_async(state)

        # ВАЖЛИВА ПЕРЕВІРКА: Переконуємось, що всі гравці в membersList мають ролі в БД
        self.print_log(f"🌙 Ніч {state.night_number}: перевірка цілісності membersList ({len(state.membersList)} гравців)")
        for check_id in state.membersList:
            check_result = await self._db_fetchone(
                "SELECT role, killed FROM users WHERE id = %s",
                (check_id,),
            )
            if not check_result:
                self.print_log(f"⚠️ КРИТИЧНА ПОМИЛКА: гравець {check_id} в membersList, але не знайдений в БД!")
            elif not check_result[0]:
                self.print_log(f"⚠️ КРИТИЧНА ПОМИЛКА: гравець {check_id} в membersList, але не має ролі в БД!")
            elif check_result[1] == 1:
                self.print_log(f"⚠️ ПОМИЛКА: гравець {check_id} в membersList, але позначений як мертвий (killed=1)!")

        # ── Дуель: на першій ночі обираємо рівно одного живого Мирного жителя, якому даємо 2 патрони ──
        try:
            if await self._is_duels_enabled_async(chat_id, state) and not int(getattr(state, "duel_shooter_id", 0) or 0):
                civ_candidates = []
                for pid in state.membersList:
                    rr = await self._db_fetchone(
                        "SELECT role, COALESCE(killed, 0) FROM users WHERE id = %s", (pid,)
                    )
                    if rr and rr[1] == 0 and rr[0] and ("мирний" in str(rr[0]).lower() and "житель" in str(rr[0]).lower()):
                        civ_candidates.append(int(pid))
                if civ_candidates:
                    import random as _rnd_duel
                    state.duel_shooter_id = _rnd_duel.choice(civ_candidates)
                    self.print_log(f"⚔️ Дуель увімкнено: 2 патрони видано Мирному {state.duel_shooter_id}")
        except Exception as _e_duel:
            self.print_log(f"⚠️ Помилка вибору дуелянта: {_e_duel}")

        # Розсилка повідомлень ролям та нічні дії
        for id in state.membersList:
            role_result = await self._db_fetchone(
                "SELECT role FROM users WHERE id = %s",
                (id,),
            )
            if not role_result:
                self.print_log(f"Warning: Player {id} not found in database, skipping")
                continue
            
            role = role_result[0]
            if not role:
                self.print_log(f"⚠️ Warning: Player {id} has no role assigned, skipping")
                continue

            # Логування для діагностики (особливо після обміну ролей Клоуном)
            self.print_log(f"🌙 Обробка гравця {id}, роль: {role}")

            # Портал: «Заговорити зуби» - гравець пропускає нічну дію (лускав насіння)
            if id in getattr(state, "portal_seeds_skip", set()):
                self.print_log(f"🌙 Гравець {id} пропускає ніч (portal_seeds_skip)")
                continue
            # #region agent log
            _log_debug('debug-session', 'run1', 'R1', 'play.py:night_function:role_from_db', 'Player role from DB', {'player_id': id, 'role': role, 'doctor_id_before': state.doctor_id, 'commissioner_id_before': state.commissioner_id})
            # #endregion
            
            # Перевірка невидимості (Дим / ультра-пасивні). Капелюх КаПоне - на старті night_function.
            ultra_effects = item_processor.process_ultra_passive_effects(id, state)
            smoke_activated = set(getattr(state, "smoke_grenade_activated_this_night", set()) or set())
            has_smoke_item = any(
                ni.get("item_id") == "smoke_grenade"
                for ni in item_processor.get_player_items(id, ActivationTime.NIGHT)
            )

            made_invisible_by_ultra = False

            # Ультра-пасивна невидимість (наприклад Чорна діра): якщо спрацьовує - також додаємо в загальний список невидимих
            if ultra_effects.get("invisible") and not has_smoke_item:
                items = item_processor.get_player_items(id, ActivationTime.NIGHT)
                for item in items:
                    if item.get("item_id") == "black_hole" and item.get("effect_data", {}).get("effect") == "redirect_all_actions_to_random":
                        if not try_consume_buff(chat_id, id, "black_hole"):
                            self.print_log(f"⚠️ Чорна діра для {id}: немає зарядів, невидимість не активується")
                            break
                        made_invisible_by_ultra = True
                        smoke_activated.add(id)
                        self.print_log(f"🕳 Чорна діра активує невидимість для {id} (списано заряд)")
                        break

            # Зберігаємо оновлену множину невидимих на цю ніч у стан (використовується при резолві вбивств/перевірок/блоків)
            state.smoke_grenade_activated_this_night = smoke_activated

            # Глушилка сигналу - активний предмет: кнопка для активації цієї ночі
            night_items = item_processor.get_player_items(int(id), ActivationTime.NIGHT)
            for ni in night_items:
                if ni.get("item_id") == "signal_jammer" and ni.get("is_active"):
                    try:
                        jammer_kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="📵 Заглушити", callback_data=f"item_use:signal_jammer:{chat_id}")]
                        ])
                        await bot.send_message(
                            chat_id=id,
                            text="📵 <b>Глушилка сигналу</b>\n\nБлокує всі підслуховування цієї ночі. Натисни, щоб активувати.",
                            reply_markup=jammer_kb,
                            parse_mode="html"
                        )
                    except Exception:
                        pass
                    break

            # Димова шашка - активний предмет: кнопка 1 раз за гру, стаєш невидимим
            smoke_used = getattr(state, "smoke_grenade_used_this_game", set())
            if int(id) not in smoke_used:
                for ni in item_processor.get_player_items(int(id), ActivationTime.NIGHT):
                    if ni.get("item_id") == "smoke_grenade" and ni.get("is_active"):
                        try:
                            btn_text = "🕳 Активувати дим"
                            body_text = "🕳 <b>Димова шашка</b>\n\nСтаєш невидимим для нічних дій. Натисни, щоб активувати. Один раз за гру."
                            smoke_kb = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text=btn_text, callback_data=f"item_use:{ni.get('item_id')}:{chat_id}")]
                            ])
                            await bot.send_message(
                                chat_id=id,
                                text=body_text,
                                reply_markup=smoke_kb,
                                parse_mode="html"
                            )
                        except Exception:
                            pass
                        break
            # Вогнегасник - активний предмет: кнопка 1 раз за гру, скасовує одну нічну дію на гравця
            if int(id) not in state.fire_extinguisher_used_this_game:
                night_items_fe = item_processor.get_player_items(int(id), ActivationTime.NIGHT)
                for ni in night_items_fe:
                    if ni.get("item_id") == "fire_extinguisher" and ni.get("is_active"):
                        try:
                            fe_kb = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🧯 Скасувати дію", callback_data=f"item_use:fire_extinguisher:{chat_id}")]
                            ])
                            await bot.send_message(
                                chat_id=id,
                                text="🧯 <b>Вогнегасник</b>\n\nСкасовує 1 нічну дію на тобі (блок повії, вбивство тощо). Натисни, щоб використати цієї ночі. Один раз за гру.",
                                reply_markup=fe_kb,
                                parse_mode="html"
                            )
                        except Exception:
                            pass
                        break

            # Заточка - запрошення з кнопкою лише 1 раз за гру (не щоночі)
            knife_used = getattr(state, "knife_used_this_game", set())
            knife_offer_sent = getattr(state, "knife_offer_sent_this_game", set())
            if int(id) not in knife_used and int(id) not in knife_offer_sent:
                night_items_knife = item_processor.get_player_items(int(id), ActivationTime.NIGHT)
                for ni in night_items_knife:
                    if ni.get("item_id") == "knife" and ni.get("is_active"):
                        try:
                            knife_kb = InlineKeyboardMarkup(inline_keyboard=[
                                [
                                    InlineKeyboardButton(
                                        text="🔪 Обрати ціль для заточки",
                                        callback_data=f"knife_menu:{chat_id}"
                                    )
                                ]
                            ])
                            await bot.send_message(
                                chat_id=id,
                                text=emoji_to_premium(
                                    "🔪 <b>Заточка</b>\n\n"
                                    "Натисни кнопку нижче, щоб обрати жертву. "
                                    "Усі бафи можна використати лише один раз за гру."
                                ),
                                reply_markup=knife_kb,
                                parse_mode="html"
                            )
                            knife_offer_sent = getattr(state, "knife_offer_sent_this_game", set())
                            knife_offer_sent.add(int(id))
                            state.knife_offer_sent_this_game = knife_offer_sent
                        except Exception:
                            pass
                        break

            # Дуель - запрошення обраному Мирному жителю (1 раз за гру)
            if (int(id) == int(getattr(state, "duel_shooter_id", 0) or 0)
                    and not getattr(state, "duel_used", False)
                    and not getattr(state, "duel_offer_sent", False)):
                try:
                    duel_kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text="⚔️ Викликати на дуель",
                            callback_data=f"duelcall_menu:{chat_id}"
                        )
                    ]])
                    await bot.send_message(
                        chat_id=id,
                        text=emoji_to_premium(
                            "⚔️ <b>Дуель</b>\n\n"
                            "У тебе 2 патрони - один тобі, один опоненту.\n"
                            "Можеш викликати будь-кого на дуель цієї ночі: постріл вб'є одного з вас (шанс 50/50).\n"
                            "Тільки один раз за гру."
                        ),
                        reply_markup=duel_kb,
                        parse_mode="html"
                    )
                    state.duel_offer_sent = True
                except Exception:
                    pass

            if int(id) not in getattr(state, "portal_seeds_skip", set()):
                night_items_dc = item_processor.get_player_items(int(id), ActivationTime.NIGHT)
                for ni in night_items_dc:
                    if ni.get("item_id") == "devil_covenant" and ni.get("is_active"):
                        try:
                            dc_kb = _devil_covenant_activate_kb(chat_id)
                            await bot.send_message(
                                chat_id=id,
                                text=emoji_to_premium(
                                    "💥 <b>Контракт з дияволом</b>\n\n"
                                    "Один раз за гру: після активації до кінця цієї ночі та наступного дня "
                                    "жодна ворожа дія проти тебе не спрацює."
                                ),
                                reply_markup=dc_kb,
                                parse_mode="html",
                            )
                        except Exception:
                            pass
                        break
            # Повторна підстраховка для невидимості (дим) - якщо з якихось причин не надіслалось вище
            if int(id) not in getattr(state, "smoke_grenade_used_this_game", set()):
                night_items_smoke = item_processor.get_player_items(int(id), ActivationTime.NIGHT)
                for ni in night_items_smoke:
                    if ni.get("item_id") == "smoke_grenade" and ni.get("is_active"):
                        try:
                            btn_text = "🕳 Активувати дим"
                            body_text = "🕳 <b>Димова шашка</b>\n\nСтанеш невидимим для нічних дій (вбивство, перевірка, блок). Один раз за гру."
                            smoke_kb = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text=btn_text, callback_data=f"item_use:{ni.get('item_id')}:{chat_id}")]
                            ])
                            await bot.send_message(
                                chat_id=id,
                                text=body_text,
                                reply_markup=smoke_kb,
                                parse_mode="html"
                            )
                        except Exception:
                            pass
                        break
            # Старий Ліхтарик (якщо ще є в базі) - активний предмет: обрати гравця, дізнатися чи хтось приходив до нього (1 раз за гру)
            if int(id) not in getattr(state, "flashlight_used_this_game", set()):
                night_items_flash = item_processor.get_player_items(int(id), ActivationTime.NIGHT)
                for ni in night_items_flash:
                    if ni.get("item_id") == "flashlight" and ni.get("is_active"):
                        try:
                            flash_builder = InlineKeyboardBuilder()
                            for pid in state.membersList:
                                if pid != id:
                                    r = await self._db_fetchone(
                                        "SELECT tg_name, killed FROM users WHERE id = %s",
                                        (pid,),
                                    )
                                    if r and r[1] == 0:
                                        flash_builder.button(text=r[0], callback_data=f"flashlight:{chat_id}:{pid}")
                            flash_builder.adjust(1)
                            await bot.send_message(
                                chat_id=id,
                                text="🔦 <b>Ліхтарик</b>\n\nОбери гравця - дізнаєшся, чи хтось приходив до нього вночі. Один раз за гру.",
                                reply_markup=flash_builder.as_markup(),
                                parse_mode="html"
                            )
                        except Exception:
                            pass
                        break
            
            # Логування для діагностики Лікаря
            if role in ["Лікар"] or (hasattr(state, 'name_of_doctor') and role == state.name_of_doctor):
                self.print_log(f"💊 night_function: знайдено Лікаря! id={id}, role={role}, doctor_id={state.doctor_id}, name_of_doctor={getattr(state, 'name_of_doctor', 'N/A')}")

            role_obj = ChatRoleRegistry.get_role_for_chat(creator_id, chat_id, role) if creator_id else None
            role_desc = role_obj.description if role_obj and role_obj.description else f"Твоя роль: {role}"
            ability_types = [ab.ability_type for ab in role_obj.abilities] if role_obj else []
            # #region agent log
            _log_debug('debug-session', 'run1', 'A1', 'play.py:night_function:role_abilities', 'Role abilities resolved', {
                'player_id': id,
                'role_name': role,
                'abilities': [a.value for a in ability_types]
            })
            # #endregion

            # #region agent log
            _log_debug('debug-session', 'run1', 'R2', 'play.py:night_function:state_after_assign', 'State IDs after role assign', {
                'player_id': id, 'role': role,
                'all_capone_id': state.all_capone_id, 'mafia_ids': list(state.mafia_ids),
                'doctor_id': state.doctor_id, 'commissioner_id': state.commissioner_id,
                'prostitute_id': state.prostitute_id, 'maniac_id': state.maniac_id,
                'homeless_id': state.homeless_id, 'journalist_id': state.journalist_id,
                'lawyer_id': state.lawyer_id, 'clown_id': state.clown_id, 'deceiver_id': state.deceiver_id,
                'devil_id': state.devil_id,
                'nurse_id': state.nurse_id, 'sheriff_id': state.sheriff_id
            })
            # #endregion

            # Send role message
            emoji_map = {
                "Аль Капоне": "🎩",
                "Мафія": "🤵",
                "Мирний житель": "🧍",
                "Лікар": "💊",
                "Комісар Каттані": "🕵️",
                "Самогубець": "🤦‍♂️",
                "Волоцюга": "🧥",
                "Коханка": "💃",
                "Тілоохоронець": "🛡️",
                "Камікадзе": "😈",
                "Сержант": "👮‍♂️",
                "Щасливчик": "🍀",
                "Маніяк": "🔪",
                "Доктор-садист": "⚕️",
                "Мед. сестра": "👩‍⚕️",
                "Журналіст": "📰",
                "Адвокат": "👨‍💼",
                "Перевертень": "🐺",
                "Клоун": "🤡",
                "Заражений": "🧟",
                "Брехун": "🎭",
                "Диявол": "👹"
            }
            emoji = emoji_map.get(role, "🎭")
            
            # Не надсилаємо повідомлення про роль для МЖ в нову ніч (тільки питання)
            is_civilian = (role in [state.name_of_civilian, "Мирний житель"] or 
                          ("мирний" in role.lower() and "житель" in role.lower()))
            
            # ПОВІДОМЛЕННЯ ПРО РОЛЬ ВЖЕ НАДСИЛАЄТЬСЯ В start_game, тому не надсилаємо тут знову
            # Це запобігає дублюванню повідомлень про роль

            # Після зміни ролей Клоуном нова роль активується лише з наступної ночі.
            if await self._is_clown_role_temporarily_blocked(state, id):
                await self._notify_clown_role_block_once(bot, state, id)
                continue
            
            # Night actions (wrapped to handle fake test IDs that cause "chat not found")
            try:
                if role in [state.name_of_all_capone, "Аль Капоне"]:
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R3', 'play.py:night_function:action_branch', 'Action branch', {'player_id': id, 'role': role, 'handler': 'all_capone'})
                    # #endregion
                    await self.all_capone(message, bot, chat_id)
                elif role == "Мафія" and state.all_capone_id == 0:
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R3', 'play.py:night_function:action_branch', 'Action branch', {'player_id': id, 'role': role, 'handler': 'mafia_kill'})
                    # #endregion
                    # Дон мертвий - Мафія бере на себе роль помсти
                    await self.mafia_kill(message, bot, chat_id, id)
                elif role == "Мафія" and state.all_capone_id != 0:
                    # Дон живий - нічна нотація від Великого Ела
                    if not getattr(state, "big_el_wisdom_sent", False):
                        try:
                            await bot.send_message(
                                chat_id=id,
                                text=(
                                    "🕴🏻Цієї ночі вибір робить Великий Ел, "
                                    "та ділиться з тобою мудрістю, запам'ятовуй."
                                )
                            )
                            state.big_el_wisdom_sent = True
                        except Exception as e:
                            self.print_log(f" Помилка надсилання нічного повідомлення Мафії {id}: {e}")
                elif role in [state.name_of_doctor, "Лікар"] and id == state.doctor_id:
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R3', 'play.py:night_function:action_branch', 'Action branch', {'player_id': id, 'role': role, 'handler': 'doctor', 'doctor_id_match': True})
                    # #endregion
                    self.print_log(f"💊 Викликаю doctor для гравця {id}, роль: {role}, doctor_id: {state.doctor_id}")
                    await self.doctor(message, bot, chat_id)
                elif role in [state.name_of_doctor, "Лікар"]:
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R4', 'play.py:night_function:doctor_mismatch', 'Doctor ID mismatch', {'player_id': id, 'role': role, 'doctor_id': state.doctor_id, 'name_of_doctor': getattr(state, 'name_of_doctor', None)})
                    # #endregion
                    self.print_log(f"⚠️ Лікар не викликається! role={role}, id={id}, doctor_id={state.doctor_id}, name_of_doctor={state.name_of_doctor}")
                elif role == "Мед. сестра":
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R3', 'play.py:night_function:action_branch', 'Action branch', {'player_id': id, 'role': role, 'handler': 'nurse_or_doctor', 'doctor_id_eq': state.doctor_id == id})
                    # #endregion
                    if state.doctor_id == id:
                        # Мед. сестра вже стала Лікарем
                        await self.doctor(message, bot, chat_id)
                    else:
                        # Мед. сестра ще не стала Лікарем - показуємо відповідне повідомлення
                        await self.nurse_action(message, bot, chat_id, id)
                elif role == "Комісар Каттані":
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R3', 'play.py:night_function:action_branch', 'Action branch', {'player_id': id, 'role': role, 'handler': 'commissioner_action'})
                    # #endregion
                    await self.commissioner_action(message, bot, chat_id, id)
                elif role == "Сержант":
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R3', 'play.py:night_function:action_branch', 'Action branch', {'player_id': id, 'role': role, 'handler': 'sergeant', 'commissioner_dead': state.commissioner_id == 0})
                    # #endregion
                    # Сержант може діяти тільки якщо Комісар мертвий
                    if state.commissioner_id == 0:
                        # Сержант став Комісаром - викликаємо дію Комісара
                        await self.commissioner_action(message, bot, chat_id, id)
                    else:
                        # Комісар живий - Сержант спостерігає; повідомлення лише 1 раз за гру
                        if not getattr(state, "sergeant_passive_night_sent", False):
                            try:
                                await bot.send_message(
                                    chat_id=id,
                                    text="🎖️ <b>Сержант</b> не виконує нічних дій.\n\n"
                                         "Він спостерігає і запам'ятовує.",
                                    parse_mode="html"
                                )
                                state.sergeant_passive_night_sent = True
                            except Exception:
                                pass
                elif role == "Коханка":
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R3', 'play.py:night_function:action_branch', 'Action branch', {'player_id': id, 'role': role, 'handler': 'prostitute_block'})
                    # #endregion
                    await self.prostitute_block(message, bot, chat_id, id)
                elif role == "Тілоохоронець":
                    await self.guardian_angel(message, bot, chat_id, id)
                elif role == "Маніяк":
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R3', 'play.py:night_function:action_branch', 'Action branch', {'player_id': id, 'role': role, 'handler': 'maniac_kill'})
                    # #endregion
                    await self.maniac_kill(message, bot, chat_id, id)
                elif role == "Доктор-садист":
                    await self.sadistic_doctor(message, bot, chat_id, id)
                elif role == "Волоцюга":
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R3', 'play.py:night_function:action_branch', 'Action branch', {'player_id': id, 'role': role, 'handler': 'homeless_watch'})
                    # #endregion
                    await self.homeless_watch(message, bot, chat_id, id)
                elif role == "Журналіст":
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R3', 'play.py:night_function:action_branch', 'Action branch', {'player_id': id, 'role': role, 'handler': 'journalist_action'})
                    # #endregion
                    await self.journalist_action(message, bot, chat_id, id)
                elif role == "Адвокат":
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R3', 'play.py:night_function:action_branch', 'Action branch', {'player_id': id, 'role': role, 'handler': 'lawyer_protect'})
                    # #endregion
                    await self.lawyer_protect(message, bot, chat_id, id)
                elif role == "Клоун":
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R3', 'play.py:night_function:action_branch', 'Action branch', {'player_id': id, 'role': role, 'handler': 'clown_swap'})
                    # #endregion
                    await self.clown_swap(message, bot, chat_id, id)
                elif role == "Заражений":
                    await self.infected_action(message, bot, chat_id, id)
                elif role == "Брехун":
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R3', 'play.py:night_function:action_branch', 'Action branch', {'player_id': id, 'role': role, 'handler': 'deceiver_fake'})
                    # #endregion
                    await self.deceiver_fake(message, bot, chat_id, id)
                # Контрактник: показуємо «Принести душу» тільки якщо він НЕ Дон (Дон вбиває як звичайно - це й рахується як душа)
                elif id == getattr(state, 'devil_contract_pending', 0) and id in getattr(state, 'devil_contract_holders', set()) and getattr(state, 'devil_souls_brought', 0) < 2 and id != getattr(state, 'all_capone_id', 0):
                    await self.devil_contract_holder_choose(message, bot, chat_id, id)
                elif role == "Диявол":
                    await self.devil_offer_contract(message, bot, chat_id, id)
                elif role == "Русалка":
                    await self.mermaid_action(message, bot, chat_id, id)
                elif role == "Мисливець на русалку":
                    await self.hunter_action(message, bot, chat_id, id)
                else:
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'R5', 'play.py:night_function:fallback_branch', 'Role fell to else (no explicit handler)', {'player_id': id, 'role': role, 'has_abilities': bool(creator_id and role_obj and getattr(role_obj, 'abilities', None))})
                    # #endregion
                    # Кастомні ролі з реєстру (наприклад Танос): показуємо нічні дії за їхніми здібностями
                    if creator_id and role_obj and getattr(role_obj, 'abilities', None):
                        phase_ok = lambda a: (
                            getattr(a, 'phase', None) in (AbilityPhase.NIGHT, AbilityPhase.BOTH)
                            or (hasattr(a, 'phase') and getattr(a.phase, 'value', '') in ('night', 'both'))
                            or (hasattr(a, 'can_use_in_phase') and a.can_use_in_phase("night"))
                        )
                        night_abilities = [a for a in role_obj.abilities if phase_ok(a)]
                        if night_abilities:
                            await self._custom_role_night_action(message, bot, chat_id, id, role, role_obj, state)
            except TelegramForbiddenError as e:
                # Користувач заблокував бота — нічні кнопки в ПП недоступні; гра не має падати.
                self.print_log(f"⚠️ Гравець {id} ({role}) заблокував бота або бот не може писати в ПП: {e}")
            except TelegramBadRequest as e:
                err = str(e).lower()
                if "chat not found" in err:
                    self.print_log(f"⚠️ ПП невідкрито для гравця {id} ({role}), пропускаємо")
                elif "blocked" in err or "forbidden" in err or "deactivated" in err or "user is deactivated" in err:
                    self.print_log(f"⚠️ Не вдалося надіслати нічну дію гравцю {id} ({role}): {e}")
                else:
                    raise
        
        # Портал: унікальні активні бафи - вибір цілі вночі (стрічка, насіння, Дух 2021, Запах фрі, Київський смак)
        portal_active_buff_ids = ("portal_ribbon", "portal_seeds", "portal_spirit_2021", "portal_smell_fry", "portal_kyiv_taste")
        for player_id in state.membersList:
            row = await self._db_fetchone(
                "SELECT killed FROM users WHERE id = %s",
                (player_id,),
            )
            if row and (row[0] or 0) == 1:
                continue
            items = get_active_items_for_player(player_id, chat_id)
            for item in items:
                bid = item.get("item_id")
                if bid not in portal_active_buff_ids:
                    continue
                def_item = UNIQUE_BUFFS.get(bid)
                if not def_item:
                    continue
                alive_others = []
                for pid in state.membersList:
                    if pid == player_id:
                        continue
                    r = await self._db_fetchone(
                        "SELECT killed FROM users WHERE id = %s",
                        (pid,),
                    )
                    if r and (r[0] or 0) == 0:
                        alive_others.append(pid)
                if not alive_others:
                    continue
                builder = InlineKeyboardBuilder()
                for tid in alive_others:
                    tn = await self._db_fetchone(
                        "SELECT tg_name FROM users WHERE id = %s",
                        (tid,),
                    )
                    name = (tn[0] or "Гравець") if tn else "Гравець"
                    builder.button(text=name, callback_data=f"portal_night:{chat_id}:{bid}:{tid}")
                builder.adjust(1)
                try:
                    await bot.send_message(
                        chat_id=player_id,
                        text=f"🌙 <b>Нічний баф</b>\n\n{def_item.emoji} <b>{def_item.name}</b>\n{def_item.description}\n\nОбери гравця:",
                        parse_mode="html",
                        reply_markup=builder.as_markup(),
                    )
                except Exception as e:
                    self.print_log(f"⚠️ Не вдалося надіслати меню портального бафа гравцю {player_id}: {e}")
                break  # один баф на гравця за ітерацію (перший знайдений)
        
        # На початку першої ночі гарантовано надсилаємо Дону та Мафії список союзників (після того як state вже з БД)
        if state.night_number == 1 and not getattr(state, "mafia_allies_sent", False):
            try:
                if state.all_capone_id:
                    mafia_allies = []
                    for mafia_id in state.mafia_ids:
                        r = await self._db_fetchone(
                            "SELECT tg_name FROM users WHERE id = %s",
                            (mafia_id,),
                        )
                        if r:
                            mafia_allies.append(r[0])
                    if mafia_allies:
                        allies_list_text = "\n".join([f"• 🤵 {name}" for name in mafia_allies])
                        msg_don = (
                            f"🤝 <b>Твої союзники (Мафія):</b>\n\n{allies_list_text}\n\n"
                        )
                        await bot.send_message(chat_id=state.all_capone_id, text=msg_don, parse_mode="html")
                for mafia_id in state.mafia_ids:
                    allies_for_mafia = []
                    if state.all_capone_id:
                        r = await self._db_fetchone(
                            "SELECT tg_name FROM users WHERE id = %s",
                            (state.all_capone_id,),
                        )
                        if r:
                            allies_for_mafia.append(f"• 🎩 {r[0]}")
                    for other_id in state.mafia_ids:
                        if other_id != mafia_id:
                            r = await self._db_fetchone(
                                "SELECT tg_name FROM users WHERE id = %s",
                                (other_id,),
                            )
                            if r:
                                allies_for_mafia.append(f"• 🤵 {r[0]}")
                    if allies_for_mafia:
                        text_mafia = (
                            f"🤝 <b>Твої союзники:</b>\n\n" + "\n".join(allies_for_mafia) + "\n\n"
                        )
                        await bot.send_message(chat_id=mafia_id, text=text_mafia, parse_mode="html")
                state.mafia_allies_sent = True
                self.print_log(" Надіслано союзників Дону та Мафії (перша ніч)")
            except Exception as e:
                self.print_log(f" Помилка надсилання союзників Дон/Мафія: {e}")
        
        # Надсилаємо питання МЖ один раз після обробки всіх ролей (не в циклі)
        if state.civilian_ids:
            await self.civilian(message=message, bot=bot, chat_id=chat_id)
        
        # CRITICAL: Create a task to handle night ending separately
        # This ensures the function doesn't block and can properly complete
        afk_auto_choice_enabled = await self._is_afk_auto_choice_enabled_async(chat_id, state)
        night_duration = AFK_AUTO_CHOICE_TOTAL_SECONDS if afk_auto_choice_enabled else 60
        self.print_log(f"🌙 Ніч {state.night_number} почалася, запускаю таймер на {night_duration} секунд...")
        self.print_log(f"📊 Стан: game_active={state.game_active}, membersList={len(state.membersList) if state.membersList else 0}")
        
        # Create task for night timer - this will ensure completion
        asyncio.create_task(self._night_timer_task(message, bot))
        # #region agent log
        _log_debug('debug-session', 'run1', 'N0', 'play.py:night_function:task_created', 'Night timer task scheduled', {
            'chat_id': chat_id,
            'night_number': state.night_number
        })
        # #endregion


    async def check_win_conditions_async(self, chat_id: int):
        """Check win conditions based on role alignment (evil/good/neutral)"""
        state = self._get_state(chat_id)
        evil_count = 0  # Тільки мафія (Дон + Мафія) - Маніяк перемагає окремо
        good_count = 0  # Добрі ролі (мирні, лікар, шериф)
        neutral_count = 0  # Нейтральні ролі (повія, доктор-садист)
        don_alive = False
        alive_roles = []
        
        # Отримуємо creator_id для доступу до ролей
        creator_result = await self._db_fetchone(
            "SELECT creator_id FROM admin_panel WHERE group_id = %s",
            (chat_id,),
        )
        creator_id = creator_result[0] if creator_result else 0
        
        for player_id in state.membersList:
            result = await self._db_fetchone(
                "SELECT role, killed FROM users WHERE id = %s",
                (player_id,),
            )
            if result:
                role_name, killed = result
                # Only count alive players
                if killed == 0:
                    alive_roles.append(role_name)
                    # Маніяк - самостійна роль, не рахується ні за мафію, ні за мирних
                    if role_name == "Маніяк":
                        continue
                    # Helper to classify by name if alignment is missing/invalid (тільки Дон + Мафія = evil для перемоги)
                    def _classify_by_name(name: str):
                        nonlocal evil_count, good_count, don_alive
                        mafia_names = {state.name_of_all_capone, "Аль Капоне", "Мафія"}
                        if name in mafia_names:
                            evil_count += 1
                            if name == state.name_of_all_capone or name == "Аль Капоне":
                                don_alive = True
                        elif name == "Мирний житель" or name == state.name_of_civilian:
                            good_count += 1
                        else:
                            good_count += 1

                    # Отримуємо роль об'єкт для визначення alignment
                    role_obj = ChatRoleRegistry.get_role_for_chat(creator_id, chat_id, role_name)
                    
                    if role_obj and hasattr(role_obj, 'alignment') and role_obj.alignment is not None:
                        alignment = role_obj.alignment
                        if role_name == state.name_of_all_capone or role_name == "Аль Капоне":
                            don_alive = True
                        if isinstance(alignment, str):
                            if alignment == "evil":
                                evil_count += 1
                            elif alignment == "good":
                                good_count += 1
                            elif alignment == "neutral":
                                neutral_count += 1
                            else:
                                _classify_by_name(role_name)
                        elif alignment == RoleAlignment.EVIL:
                            evil_count += 1
                        elif alignment == RoleAlignment.GOOD:
                            good_count += 1
                        elif alignment == RoleAlignment.NEUTRAL:
                            neutral_count += 1
                    else:
                        _classify_by_name(role_name)
        
        # Спочатку визначаємо переможця за стандартними умовами
        winner = None

        # Диявол виграє, якщо вклав хоча б один вдалий контракт (навіть якщо його повішали)
        devil_successful_contracts = getattr(state, "devil_successful_contracts", 0)
        if devil_successful_contracts >= 1:
            winner = "devil"
        
        # Якщо залишився тільки Маніяк - він виграв
        if winner is None and len(alive_roles) == 1 and alive_roles[0] == "Маніяк":
            winner = "maniac"
        # 2 мирних + 2 мафії + 1 Маніяк - перемагає Маніяк
        elif winner is None and "Маніяк" in alive_roles and good_count == 2 and evil_count == 2 and len(alive_roles) == 5:
            winner = "maniac"
        # Якщо залишився Маніяк + мирні (без мафії) - Маніяк перемагає
        elif winner is None and "Маніяк" in alive_roles and evil_count == 0 and good_count > 0:
            winner = "maniac"
        
        # Якщо всі живі - заражені
        elif winner is None and alive_roles and all(role == "Заражений" for role in alive_roles):
            winner = "infected"
        
        elif winner is None:
            # Нейтральні ролі (Коханка, Самогубець тощо) вважаються союзниками мирних жителів
            # Вони перемагають разом з мирними, тому додаємо їх до good_count для перевірки перемоги
            total_good_allies = good_count + neutral_count
            
            # Якщо немає мафії (Дон+Мафія мертві) і мирних є - добрі виграли. Якщо при цьому живий Маніяк - гра продовжується
            if evil_count == 0 and total_good_allies > 0 and "Маніяк" not in alive_roles:
                # #region agent log
                _log_debug('debug-session', 'run1', 'W1', 'play.py:check_win_conditions', 'Win condition met: civilians (no evil)', {
                    'chat_id': chat_id,
                    'evil_count': evil_count,
                    'good_count': good_count,
                    'neutral_count': neutral_count,
                    'total_good_allies': total_good_allies,
                    'don_alive': don_alive
                })
                # #endregion
                winner = "civilians"
            
            # Якщо немає добрих ролей (всі мирні мертві) - злі виграли
            # Нейтральні ролі перемагають разом з мирними, але якщо мирних немає,
            # то нейтральні не можуть перемогти самостійно - мафія перемагає
            elif good_count == 0 and evil_count > 0:
                winner = "mafia"
            
            # Класичні умови перемоги Mafia
            # Мафія перемагає тільки якщо їх більше або дорівнює мирним + нейтральним разом
            # Або якщо всі мирні мертві і немає нейтральних
            elif evil_count > 0:
                # Мафія перемагає, якщо зліх не менше, ніж «команда міста» (мирні + нейтральні, уже в total_good_allies).
                # Нейтральні (наприклад Коханка) вже входять у total_good_allies — рівність 3 злих vs 2 добрих + 1 нейтральна
                # має завершувати гру перемогою мафії, інакше гра може «висіти» без переможця.
                if evil_count >= total_good_allies:
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'W1', 'play.py:check_win_conditions', 'Win condition met: mafia (evil >= good+neutral)', {
                        'chat_id': chat_id,
                        'evil_count': evil_count,
                        'good_count': good_count,
                        'neutral_count': neutral_count,
                        'total_good_allies': total_good_allies,
                        'don_alive': don_alive
                    })
                    # #endregion
                    winner = "mafia"
        
        # Самогубець: якщо його повісили, гра не закінчується окремо - повертаємо звичайного переможця (мафія/мирні).
        # Самогубець потрапляє в список переможців у _build_endgame_summary, якщо winner in ("mafia", "civilians").
        # #region agent log
        _log_debug('debug-session', 'run1', 'W1', 'play.py:check_win_conditions', 'No win condition or game continues', {
            'chat_id': chat_id,
            'evil_count': evil_count,
            'good_count': good_count,
            'neutral_count': neutral_count,
            'don_alive': don_alive,
            'winner': winner,
            'suicide_was_lynched': state.suicide_was_lynched
        })
        # #endregion
        return winner

    def check_win_conditions(self, chat_id: int):
        """Legacy sync shim. Prefer await check_win_conditions_async()."""
        self.print_log("⚠️ check_win_conditions(sync) is deprecated; use check_win_conditions_async")
        return None

    def _classify_alignment(self, creator_id: int, chat_id: int, role_name: str, state: GameState) -> str:
        """Return alignment label: 'evil', 'good', or 'neutral'"""
        role_obj = ChatRoleRegistry.get_role_for_chat(creator_id, chat_id, role_name)
        if role_obj and hasattr(role_obj, 'alignment') and role_obj.alignment is not None:
            alignment = role_obj.alignment
            if isinstance(alignment, str):
                if alignment in ["evil", "good", "neutral"]:
                    return alignment
            elif alignment == RoleAlignment.EVIL:
                return "evil"
            elif alignment == RoleAlignment.GOOD:
                return "good"
            elif alignment == RoleAlignment.NEUTRAL:
                return "neutral"
        # Fallback by name
        if role_name == state.name_of_all_capone or role_name == "Аль Капоне" or role_name == "Маніяк":
            return "evil"
        if role_name == "Мирний житель" or role_name == state.name_of_civilian:
            return "good"
        return "good"

    async def test_endgame_cmd(self, message: Message, bot: Bot):
        """Тестова команда для засновника - показує кінець гри з тестовими даними"""
        # Перевірка, чи користувач є засновником
        if not self._is_founder(message.from_user.id):
            await message.answer(" Ця команда доступна тільки засновнику бота.")
            return
        
        chat_id = message.chat.id
        state = self._get_state(chat_id)
        
        # Якщо немає гравців, створюємо тестові дані
        if not state.all_membersNames and not state.membersNames:
            # Створюємо тестові дані
            test_players = [
                (123456789, "Тестовий Гравець 1"),
                (987654321, "Тестовий Гравець 2"),
                (111222333, "Тестовий Гравець 3"),
            ]
            state.all_membersNames = test_players
            
            # Додаємо тестові ролі в БД
            for player_id, player_name in test_players:
                await self._db_execute_commit(
                    """
                    INSERT INTO users (id, tg_name, role, killed)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET tg_name = EXCLUDED.tg_name, role = EXCLUDED.role, killed = EXCLUDED.killed
                    """,
                    (player_id, player_name, "Аль Капоне" if player_id == 123456789 else "Мирний житель", 0),
                )
        
        # Тестуємо різні варіанти перемоги (з відео, де воно є)
        winners_to_test = ["mafia", "civilians", "maniac", "infected", "suicide"]
        bot = message.bot
        for winner in winners_to_test:
            winner_name = {
                "mafia": "Аль Капоне",
                "civilians": "Мирні жителі",
                "maniac": "Маніяк",
                "infected": "Заражені",
                "suicide": "Самогубець"
            }.get(winner, winner)
            await message.answer(f"🧪 <b>ТЕСТ: Перемога {winner_name}</b> 🧪", parse_mode="html")
            await self._send_endgame_summary(message, bot, chat_id, winner)
            await asyncio.sleep(1)  # Невелика затримка між повідомленнями
        
        await message.answer(" Тест завершено! Всі варіанти перемоги показано.")

    async def _ensure_test_players(self, chat_id: int):
        """Допоміжна функція: створює тестових гравців і ролі, якщо їх ще немає"""
        state = self._get_state(chat_id)
        if state.all_membersNames and state.membersNames and state.membersList:
            return state
        
        test_players = [
            (123456789, "Тестовий Гравець 1"),
            (987654321, "Тестовий Гравець 2"),
            (111222333, "Тестовий Гравець 3"),
            (444555666, "Тестовий Гравець 4"),
        ]
        state.all_membersNames = test_players
        state.membersNames = test_players
        state.membersList = [p[0] for p in test_players]
        
        # Додаємо тестові ролі в БД
        for idx, (player_id, player_name) in enumerate(test_players):
            if idx == 0:
                role = "Аль Капоне"
            elif idx == 1:
                role = "Лікар"
            else:
                role = "Мирний житель"
            await self._db_execute_commit(
                """
                INSERT INTO users (id, tg_name, role, killed) 
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE 
                SET tg_name = EXCLUDED.tg_name, role = EXCLUDED.role, killed = EXCLUDED.killed
                """,
                (player_id, player_name, role, 0),
            )
        return state

    async def test_day_ui_cmd(self, message: Message, bot: Bot):
        """Тестовий екран початку дня (список гравців + ролі + таймер)"""
        if not self._is_founder(message.from_user.id):
            await message.answer(" Ця команда доступна тільки засновнику бота.")
            return
        
        chat_id = message.chat.id
        state = await self._ensure_test_players(chat_id)

        players_text = self._format_players_list_numbered_html(state.membersNames)
        alive_roles_info = await self._get_alive_roles_info_async(chat_id, state)

        await message.answer(
            f"Список гравців:\n\n"
            f"{players_text}\n\n"
            f"{alive_roles_info}\n\n",
            parse_mode="html",
        )

    async def test_night_ui_cmd(self, message: Message, bot: Bot):
        """Тестовий екран початку ночі"""
        if not self._is_founder(message.from_user.id):
            await message.answer(" Ця команда доступна тільки засновнику бота.")
            return
        
        chat_id = message.chat.id
        await self._ensure_test_players(chat_id)

        await message.answer(
            "🌃 <b>Ніч знову опускається на місто…</b> 🌃\n\n",
            parse_mode="html",
        )

    def _is_founder(self, user_id: int) -> bool:
        """Чи є користувач засновником бота (таблиця founders або owner ID)."""
        if _is_bot_owner_id(user_id):
            return True
        try:
            founder_ids = get_active_founder_ids()
            return user_id in (founder_ids or [])
        except Exception:
            return False

    async def test_day_cmd(self, message: Message, bot: Bot):
        """Тест дня для засновників: відео дня (day.mp4) + текст «День настав».
        /test_day - без жертв; /test_day 1 - одна жертва; /test_day 2 - дві жертви (тестові дані)."""
        if not message.from_user or not self._is_founder(message.from_user.id):
            await message.answer(" Ця команда доступна тільки засновникам бота.")
            return
        chat_id = message.chat.id
        parts = (message.text or "").strip().split()
        victims_count = 0  # 0 = без жертв
        if len(parts) >= 2:
            try:
                victims_count = int(parts[1])
                victims_count = max(0, min(2, victims_count))
            except ValueError:
                pass
        media_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Media'))
        day_video = os.path.join(media_dir, 'day.mp4')

        if victims_count == 0:
            day_text = (
                "🌄 <b>День настав</b> 🌄\n\n"
                "Місто прокинулося з поганою новиною. Цієї ночі без жертв.\n\n"
                "Але мафія нікуди не зникла…"
            )
        else:
            # Тестові жертви: 1 = одна, 2 = дві (ролі та вбивці як у реальному повідомленні)
            uid = message.from_user.id
            fn = message.from_user.first_name or "Гравець"
            ln = (message.from_user.last_name or "").strip()
            name1 = f"{fn} {ln}".strip() if ln else fn
            victim1_link = vip_mod.html_user_link(uid, name1)
            if victims_count == 1:
                killed_block = f"Цієї ночі <b>Лікар</b> {victim1_link} був убитий.\n"
                killer_text = "<b>Аль Капоне</b>"
                day_text = (
                    "🌄 День настав 🌄\n\n"
                    "Місто прокинулося з поганою новиною.\n"
                    f"{killed_block}"
                    f"Кажуть, що за цим стоїть {killer_text}.\n"
                )
            else:
                victim2_link = f"<a href='tg://user?id=999999999'>Тест Другий</a>"
                victim_entries = [f"<b>Лікар</b> {victim1_link}", f"<b>Камікадзе</b> {victim2_link}"]
                killers_str = "<b>Аль Капоне</b>, <b>Маніяк</b>"
                killed_block = "Цієї ночі були вбиті:\n" + ", ".join(victim_entries) + "\n"
                killed_block += f"Кажуть, що за цим стоять {killers_str}.\n"
                day_text = (
                    "🌄 День настав 🌄\n\n"
                    "Місто прокинулося з поганою новиною.\n"
                    f"{killed_block}"
                )

        day_caption_test = emoji_to_premium(day_text, skip_vip_badges=False)
        day_sent_media = await self._send_phase_media(bot, chat_id, 'day', day_caption_test)
        path_day_send = None
        if not day_sent_media and os.path.isfile(day_video):
            path_day_send = await self._prepare_video_9_16(day_video) or day_video
        try:
            if day_sent_media:
                pass
            elif path_day_send and os.path.isfile(path_day_send):
                await bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(path_day_send),
                    caption=day_caption_test,
                    parse_mode="html",
                )
            else:
                await message.answer(day_caption_test, parse_mode="html")
            await message.answer(" Тест дня надіслано." + (" (з жертвами)" if victims_count else ""))
        except Exception as e:
            self.print_log(f"⚠️ test_day: {e}")
            try:
                await message.answer(day_caption_test, parse_mode="html")
                await message.answer("Тест дня надіслано (без відео).")
            except Exception:
                await message.answer("Не вдалося надіслати тест дня.")
        finally:
            if path_day_send and path_day_send != day_video:
                try:
                    os.unlink(path_day_send)
                except OSError:
                    pass

    async def test_night_cmd(self, message: Message, bot: Bot):
        """Тест ночі для засновників: відео ночі (night.mp4) + текст «Ніч 1»."""
        if not message.from_user or not self._is_founder(message.from_user.id):
            await message.answer(" Ця команда доступна тільки засновникам бота.")
            return
        chat_id = message.chat.id
        media_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Media'))
        night_video = os.path.join(media_dir, 'night.mp4')
        night_announcement = (
            "🌃 <b>Ніч 1</b> 🌃\n\n"
            "Під покровом ночі за рогом почулися постріли і виє сирена швидкої.\n"
            "Сержант наказав усім тісно зачинити двері.\n\n"
            "Залишаємось на сторожі...\n"
            "Що ж нам може принести цей світанок? 🤔"
        )
        url_button = InlineKeyboardButton(text="Перейти до бота", url="https://t.me/sicilian_mafia_bot")
        url_buttons = InlineKeyboardMarkup(inline_keyboard=[[url_button]])
        night_sent_media = await self._send_phase_media(bot, chat_id, 'night', night_announcement, reply_markup=url_buttons)
        path_to_send = None
        if not night_sent_media and os.path.isfile(night_video):
            path_to_send = await self._prepare_video_9_16(night_video) or night_video
        try:
            if night_sent_media:
                pass
            elif path_to_send and os.path.isfile(path_to_send):
                await bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(path_to_send),
                    caption=night_announcement,
                    parse_mode="html",
                    reply_markup=url_buttons,
                )
            else:
                await message.answer(night_announcement, reply_markup=url_buttons, parse_mode="html")
            await message.answer(" Тест ночі надіслано.")
        except Exception as e:
            self.print_log(f"⚠️ test_night: {e}")
            try:
                await message.answer(night_announcement, reply_markup=url_buttons, parse_mode="html")
                await message.answer(" Тест ночі надіслано (без відео).")
            except Exception:
                await message.answer(" Не вдалося надіслати тест ночі.")
        finally:
            if path_to_send and path_to_send != night_video:
                try:
                    os.unlink(path_to_send)
                except OSError:
                    pass

    async def test_start_cmd(self, message: Message, bot: Bot):
        """Тест гри з N гравцями (тільки для засновника). /test_start [число]
        Наприклад: /test_start 10 або /test_start 7. За замовчуванням - 10."""
        if message.from_user is None or not self._is_founder(message.from_user.id):
            await message.answer(" Ця команда доступна тільки засновнику бота.")
            return
        chat_id = message.chat.id
        if chat_id > 0:
            await message.answer(" Команду потрібно викликати в групі, де буде гра.", parse_mode="html")
            return
        # Фіксуємо, чи гра вже активна. Це потрібно лише для логіки повідомлень
        # (але сам restart в тесті виконується нижче).
        state = self._get_state(chat_id)
        was_active_before_test_start = bool(getattr(state, "game_active", False))
        # Парсимо число гравців з аргументу
        parts = (message.text or "").strip().split()
        n = 10
        if len(parts) >= 2:
            try:
                n = int(parts[1])
                n = max(2, min(20, n))
            except ValueError:
                await message.answer(" Введи число: /test_start 10 або /test_start 7", parse_mode="html")
                return
        _log_debug(
            "debug-session",
            "run1",
            "TS0",
            "play.py:test_start_cmd:entry",
            "test_start_cmd called",
            {
                "chat_id": chat_id,
                "from_user_id": message.from_user.id if message.from_user else None,
                "n": n,
                "was_active_before_test_start": was_active_before_test_start,
            },
        )

        # Швидка відповідь, щоб було видно що хендлер спрацював
        try:
            await message.answer(f"🧪 Запускаю тест гри з {n} гравцями...", parse_mode="html")
        except Exception:
            pass

        try:
            # Скидаємо активну гру
            await self._unmute_users_muted_during_game(message.bot, chat_id)
            state.game_active = False

            # N тестових гравців: засновник + (N-1) фейкових ID
            owner_id = BOT_OWNER_IDS[0]
            test_players = [
                (owner_id, message.from_user.first_name or "Гравець 1"),
            ]
            for i in range(2, n + 1):
                fake_id = 1000000000 + i
                test_players.append((fake_id, f"Тест {i}"))

            state.all_membersNames = test_players
            state.membersNames = test_players
            state.membersList = [p[0] for p in test_players]
            state.MN = 2

            # Додаємо/оновлюємо користувачів у БД
            for player_id, player_name in test_players:
                await self._db_execute_commit(
                    """
                    INSERT INTO users (id, tg_name, role, killed) VALUES (%s, %s, NULL, 0)
                    ON CONFLICT (id) DO UPDATE SET tg_name = EXCLUDED.tg_name, role = NULL, killed = 0
                    """,
                    (player_id, player_name),
                )

            _log_debug(
                "debug-session",
                "run1",
                "TS1",
                "play.py:test_start_cmd:before_start_game",
                "before start_game",
                {"chat_id": chat_id, "membersList_len": len(state.membersList) if state.membersList else 0},
            )

            # Запускаємо гру
            await self.start_game(message, bot)
        except Exception as e:
            _log_debug(
                "debug-session",
                "run1",
                "TSX",
                "play.py:test_start_cmd:exception",
                "Exception in test_start_cmd",
                {"chat_id": chat_id, "error": str(e)},
            )
            try:
                await message.answer(
                    f"❌ Помилка при запуску тесту: <b>{html.escape(str(e))}</b>",
                    parse_mode="html",
                )
            except Exception:
                pass

    async def test_voting_ui_cmd(self, message: Message, bot: Bot):
        """Тестовий екран початку голосування (без реальної логіки)"""
        if not _is_bot_owner_id(message.from_user.id):
            await message.answer(" Ця команда доступна тільки засновнику бота.")
            return
        
        chat_id = message.chat.id
        state = await self._ensure_test_players(chat_id)

        players_text = self._format_players_list_numbered_html(state.membersNames)
        alive_roles_info = await self._get_alive_roles_info_async(chat_id, state)

        await message.answer(
            f"Список гравців (тест голосування):\n\n"
            f"{players_text}\n\n"
            f"{alive_roles_info}\n\n",
            parse_mode="html",
        )

    def _get_voting_prep_time(self, chat_id: int) -> int:
        """Legacy sync helper (kept for compatibility)."""
        return 30

    async def _get_voting_prep_time_async(self, chat_id: int) -> int:
        """Асинхронно отримати час до старту голосування (мін 20 сек, макс 180 сек)."""
        result = await self._db_fetchone(
            "SELECT voting_prep_time FROM admin_panel WHERE group_id = %s",
            (chat_id,),
        )
        if result and result[0] is not None:
            prep_time = result[0]
            return max(20, min(180, prep_time))
        return 30
    
    def _get_thematic_settings(self, chat_id: int, state: Optional[GameState] = None) -> tuple[bool, bool, bool, bool]:
        """Legacy sync helper (kept for compatibility)."""
        state = state or self._get_state(chat_id)
        state.hide_dead_roles = bool(getattr(state, "hide_dead_roles", False))
        state.hide_killer_roles = bool(getattr(state, "hide_killer_roles", False))
        state.secret_voting = bool(getattr(state, "secret_voting", False))
        state.show_night_targets = bool(getattr(state, "show_night_targets", False))
        return state.hide_dead_roles, state.hide_killer_roles, state.secret_voting, state.show_night_targets

    async def _get_thematic_settings_async(self, chat_id: int, state: Optional[GameState] = None) -> tuple[bool, bool, bool, bool]:
        """
        Асинхронно повертає (hide_dead_roles, hide_killer_roles, secret_voting, show_night_targets)
        та оновлює значення в стані гри.
        """
        state = state or self._get_state(chat_id)
        row = await self._db_fetchone(
            "SELECT hide_dead_roles, hide_killer_roles, secret_voting, show_night_targets "
            "FROM admin_panel WHERE group_id = %s LIMIT 1",
            (chat_id,),
        )
        row = row or (False, False, False, False)
        state.hide_dead_roles = bool(row[0]) if row[0] is not None else False
        state.hide_killer_roles = bool(row[1]) if row[1] is not None else False
        state.secret_voting = bool(row[2]) if row[2] is not None else False
        state.show_night_targets = bool(row[3]) if row[3] is not None else False
        return state.hide_dead_roles, state.hide_killer_roles, state.secret_voting, state.show_night_targets
    
    async def _is_friendly_fire_allowed_async(self, chat_id: int, state: Optional[GameState] = None) -> bool:
        """
        Тематичне налаштування: чи дозволено вбивати союзників (дружній вогонь).
        Повертає True/False, читаючи значення з admin_panel.
        """
        state = state or self._get_state(chat_id)
        row = await self._db_fetchone(
            "SELECT allow_friendly_fire FROM admin_panel WHERE group_id = %s LIMIT 1",
            (chat_id,),
        )
        value = bool(row[0]) if row and row[0] is not None else False
        state.allow_friendly_fire = value
        return value
    
    async def _is_skip_night_action_allowed_async(self, chat_id: int, state: Optional[GameState] = None) -> bool:
        """
        Тематичне налаштування «Пропуск нічної дії»: якщо True - не збільшуємо лічильник нічної неактивності
        і не виключаємо гравців за 3 ночі без дії в боті.
        """
        state = state or self._get_state(chat_id)
        row = await self._db_fetchone(
            "SELECT allow_skip_night_action FROM admin_panel WHERE group_id = %s LIMIT 1",
            (chat_id,),
        )
        value = bool(row[0]) if row and row[0] is not None else False
        state.allow_skip_night_action = value
        self.print_log(f"🔍 _is_skip_night_action_allowed_async: chat_id={chat_id}, row={row}, value={value}")
        return value

    async def _is_duels_enabled_async(self, chat_id: int, state: Optional[GameState] = None) -> bool:
        """
        Налаштування «Дуелі»: рівно один Мирний житель отримує 2 патрони й може викликати
        когось уночі (постріл 50/50, 1 раз за гру).
        """
        state = state or self._get_state(chat_id)
        row = await self._db_fetchone(
            "SELECT duels_enabled FROM admin_panel WHERE group_id = %s LIMIT 1",
            (chat_id,),
        )
        value = bool(row[0]) if row and row[0] is not None else False
        state.duels_enabled = value
        return value

    async def _is_afk_auto_choice_enabled_async(self, chat_id: int, state: Optional[GameState] = None) -> bool:
        """
        Тематичне налаштування «AFK-автовибір»:
        - ніч триває 45 секунд;
        - на 40-й секунді бот робить вибір за неактивних;
        - аналогічно для денного голосування.
        """
        state = state or self._get_state(chat_id)
        row = await self._db_fetchone(
            "SELECT afk_auto_choice_enabled FROM admin_panel WHERE group_id = %s LIMIT 1",
            (chat_id,),
        )
        value = bool(row[0]) if row and row[0] is not None else False
        state.afk_auto_choice_enabled = value
        return value

    async def _resume_day_vote_after_restart(self, bot: Bot, chat_id: int, remaining_seconds: float) -> None:
        if remaining_seconds > 0:
            await asyncio.sleep(remaining_seconds)
        state = self._get_state(chat_id)
        if not state.game_active or not getattr(state, "day_active", False):
            return
        if not getattr(state, "voting_start_time", None):
            return
        proxy = _ChatMessageProxy(bot, chat_id)
        await self.results_def(message=proxy, bot=bot, chat_id=chat_id)

    async def recover_active_games_after_restart(self, bot: Bot) -> None:
        """
        Відновлює активні ігри після рестарту процесу:
        - піднімає таймер ночі;
        - піднімає таймер денного голосування;
        - піднімає таймер фінального голосування 👍/👎.
        """
        active_chats = game_state_manager.get_all_active_chats()
        if not active_chats:
            return

        for chat_id in active_chats:
            state = self._get_state(chat_id)
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=emoji_to_premium(
                        "♻️ Бот перезапущено. Активну гру відновлено, партія продовжується."
                    ),
                    parse_mode="html",
                )
            except Exception:
                pass

            if getattr(state, "hanging_vote_start_time", None) and getattr(state, "lynched_candidate_id", 0):
                proxy = _ChatMessageProxy(bot, chat_id)
                # Таймер фінального голосування запускаємо заново (безпечніше, ніж втратити фазу повністю).
                state.hanging_vote_start_time = datetime.now()
                asyncio.create_task(
                    self._hanging_vote_timer(
                        message=proxy,
                        bot=bot,
                        chat_id=chat_id,
                        lynched_id=state.lynched_candidate_id,
                    )
                )
                continue

            if getattr(state, "day_active", False) and getattr(state, "voting_start_time", None):
                elapsed = max(0, (datetime.now() - state.voting_start_time).total_seconds())
                remaining = max(0, AFK_AUTO_CHOICE_TOTAL_SECONDS - elapsed)
                afk_auto_choice_enabled = await self._is_afk_auto_choice_enabled_async(chat_id, state)
                if afk_auto_choice_enabled and not getattr(state, "afk_day_auto_choice_applied", False):
                    afk_delay = max(0, AFK_AUTO_CHOICE_BOT_PICK_AT_SECONDS - elapsed)
                    asyncio.create_task(self._auto_pick_day_votes_for_afk(bot, chat_id, delay_seconds=afk_delay))
                asyncio.create_task(self._resume_day_vote_after_restart(bot, chat_id, remaining))
                continue

            if getattr(state, "day_active", False):
                # Денна фаза до голосування (обговорення / підготовка голосування).
                # Голосування й фінальне голосування оброблені вище, тож тут — лише
                # обговорення або відлік підготовки. Без відновлення гра зависає без таймера.
                proxy = _ChatMessageProxy(bot, chat_id)
                started = getattr(state, "discussion_started_at", None)
                if started:
                    elapsed = (datetime.now() - started).total_seconds()
                    remaining = int(max(0, 30 - elapsed))
                    if remaining > 0:
                        # Ще триває обговорення — відновлюємо із залишком часу.
                        state.discussion_task = asyncio.create_task(
                            self._run_discussion_countdown(proxy, bot, chat_id, remaining)
                        )
                        continue
                # Обговорення завершилось або були у фазі підготовки голосування —
                # стартуємо відлік підготовки заново (скидаємо застаріле повідомлення).
                state.discussion_started_at = None
                state.voting_prep_message = None
                asyncio.create_task(self._start_voting_prep_timer(proxy, bot, chat_id))
                continue

            if not getattr(state, "day_active", False):
                proxy = _ChatMessageProxy(bot, chat_id)
                asyncio.create_task(self._night_timer_task(message=proxy, bot=bot))

    async def _get_alive_target_ids(self, chat_id: int, excluded_ids: set[int]) -> list[int]:
        state = self._get_state(chat_id)
        alive_ids: list[int] = []
        for pid in list(state.membersList):
            if pid in excluded_ids:
                continue
            row = await self._db_fetchone(
                "SELECT killed FROM users WHERE id = %s",
                (pid,),
            )
            if row and int(row[0]) == 0:
                alive_ids.append(pid)
        return alive_ids

    async def _is_clown_role_temporarily_blocked(self, state: GameState, user_id: int) -> bool:
        """Після зміни ролі Клоуном: гравець не може ходити новою роллю до наступної ночі."""
        blocked = set(getattr(state, "clown_role_blocked_this_night", set()) or set())
        return int(user_id) in blocked

    async def _notify_clown_role_block_once(self, bot: Bot, state: GameState, user_id: int) -> None:
        sent = set(getattr(state, "clown_role_block_notice_sent_this_night", set()) or set())
        uid = int(user_id)
        if uid in sent:
            return
        sent.add(uid)
        state.clown_role_block_notice_sent_this_night = sent
        try:
            await bot.send_message(
                chat_id=uid,
                text=(
                    "🤡 Клоун змінив твою роль цієї ночі.\n\n"
                    "Нові кнопки дій стануть доступні з наступної ночі."
                ),
                parse_mode="html",
            )
        except Exception:
            pass

    async def _build_check_action_group_text(
        self,
        actor_id: int,
        target_name: str | None,
        show_target: bool,
    ) -> str:
        """Формує тематичний текст перевірки за реальною роллю виконавця з БД."""
        role_row = await self._db_fetchone("SELECT role FROM users WHERE id = %s", (int(actor_id),))
        role_name = role_row[0] if role_row else ""
        if self._is_commissioner_role_name(role_name) or role_name == "Сержант":
            if show_target and target_name:
                return f"🕵️ <b>Комісар Каттані</b> виходить на перевірку: <code>{target_name}</code>."
            return "🕵️ <b>Комісар Каттані</b> виходить на перевірку"
        title = role_name or "Слідчий"
        if show_target and target_name:
            return f"🔎 <b>{title}</b> перевіряв <code>{target_name}</code>."
        return f"🔎 <b>{title}</b> перевіряв"

    async def _auto_pick_night_actions_for_afk(self, chat_id: int, bot: Bot) -> None:
        state = self._get_state(chat_id)
        if not state.game_active or getattr(state, "day_active", False):
            return

        try:
            await self._refresh_state_role_ids_async(state)
        except Exception:
            pass

        devil_id = getattr(state, "devil_id", 0)
        devil_contract_holders = set(getattr(state, "devil_contract_holders", set()) or set())
        allow_friendly_fire = await self._is_friendly_fire_allowed_async(chat_id, state)
        _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)

        async def _pick_one(excluded: set[int]) -> int:
            options = await self._get_alive_target_ids(chat_id, excluded)
            return random.choice(options) if options else 0

        async def _notify_group(text: str) -> None:
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="html")
            except Exception:
                pass

        async def _target_name(target_id: int) -> str:
            row = await self._db_fetchone("SELECT tg_name FROM users WHERE id = %s", (target_id,))
            return html.escape((row[0] if row and row[0] else "Гравець"))

        # Аль Капоне / Мафія
        if not getattr(state, "mafia_action_taken", False):
            don_id = int(getattr(state, "all_capone_id", 0) or 0)
            mafia_actor_id = don_id
            if not mafia_actor_id:
                alive_mafia = [mid for mid in (state.mafia_ids or []) if mid in state.membersList]
                mafia_actor_id = alive_mafia[0] if alive_mafia else 0
            if mafia_actor_id:
                excluded = {mafia_actor_id, devil_id} | devil_contract_holders
                mafia_targets = await self._get_alive_target_ids(chat_id, excluded)
                forced_colleague_target = False
                # Спец-правило AFK: якщо Аль Капоне не зробив вибір - спочатку цілиться в колегу з «Мафії».
                if don_id and mafia_actor_id == don_id:
                    colleague_ids: list[int] = []
                    for mid in (state.mafia_ids or []):
                        if mid in excluded:
                            continue
                        row = await self._db_fetchone(
                            "SELECT killed FROM users WHERE id = %s",
                            (mid,),
                        )
                        if row and int(row[0]) == 0:
                            colleague_ids.append(mid)
                    if colleague_ids:
                        mafia_targets = colleague_ids
                        forced_colleague_target = True
                if not allow_friendly_fire and mafia_targets and not forced_colleague_target:
                    filtered_targets: list[int] = []
                    for pid in mafia_targets:
                        role_row = await self._db_fetchone(
                            "SELECT role FROM users WHERE id = %s",
                            (pid,),
                        )
                        if not role_row or role_row[0] != "Мафія":
                            filtered_targets.append(pid)
                    mafia_targets = filtered_targets
                target_id = random.choice(mafia_targets) if mafia_targets else 0
                if target_id:
                    state.victim_id = target_id
                    self._record_visit(state, mafia_actor_id, target_id, "kill_don" if don_id else "kill_mafia")
                    if show_night_targets:
                        await _notify_group(f"🎩 <b>Сім'я Аль Капоне</b> зробила свій вибір: <code>{await _target_name(target_id)}</code>.")
                    else:
                        await _notify_group("🎩 <b>Сім'я Аль Капоне</b> зробила свій вибір")
                state.mafia_action_taken = True

        # Лікар
        if getattr(state, "doctor_id", 0) and not getattr(state, "doctor_action_taken", False):
            excluded = {devil_id}
            if getattr(state, "doctor_self_heal_used", False):
                excluded.add(state.doctor_id)
            patient_id = await _pick_one(excluded)
            if patient_id:
                state.patient_id = patient_id
                self._record_visit(state, state.doctor_id, patient_id, "heal")
                if patient_id == state.doctor_id:
                    state.doctor_self_heal_used = True
                if show_night_targets:
                    await _notify_group(f"🚑 <b>Карета швидкої допомоги</b> мчить до <code>{await _target_name(patient_id)}</code>.")
                else:
                    await _notify_group("🚑 <b>Карета швидкої допомоги</b> помчала містом.")
            state.doctor_action_taken = True

        # Тілоохоронець
        if getattr(state, "guardian_id", 0) and not getattr(state, "guardian_action_taken", False):
            target_id = await _pick_one({state.guardian_id, devil_id})
            if target_id:
                state.guardian_protect_id = target_id
                self._record_visit(state, state.guardian_id, target_id, "protect")
                if show_night_targets:
                    await _notify_group(f"🛡️ <b>Тілоохоронець</b> захищає <code>{await _target_name(target_id)}</code>.")
                else:
                    await _notify_group("🛡️ <b>Тілоохоронець</b> зробив свій вибір")
            state.guardian_action_taken = True

        # Шериф
        if getattr(state, "sheriff_id", 0) and not getattr(state, "sheriff_action_taken", False):
            target_id = await _pick_one({state.sheriff_id, devil_id} | devil_contract_holders)
            if target_id:
                state.sheriff_check_id = target_id
                self._record_visit(state, state.sheriff_id, target_id, "check")
                target_name = await _target_name(target_id) if show_night_targets else None
                text = await self._build_check_action_group_text(
                    actor_id=state.sheriff_id,
                    target_name=target_name,
                    show_target=show_night_targets,
                )
                await _notify_group(text)
            state.sheriff_action_taken = True

        # Коханка
        if getattr(state, "prostitute_id", 0) and not getattr(state, "block_action_taken", False):
            target_id = await _pick_one({state.prostitute_id, devil_id, getattr(state, "prostitute_last_target_id", 0)})
            if target_id:
                state.block_action_target_id = target_id
                state.prostitute_last_target_id = target_id
                self._record_visit(state, state.prostitute_id, target_id, "block")
                if show_night_targets:
                    await _notify_group(f"💋 <b>Коханка</b> провела ніч з <code>{await _target_name(target_id)}</code>.")
                else:
                    await _notify_group("💋 <b>Коханка</b> зробила свій вибір")
            state.block_action_taken = True

        # Маніяк
        if getattr(state, "maniac_id", 0) and not getattr(state, "maniac_action_taken", False):
            target_id = await _pick_one({state.maniac_id, devil_id} | devil_contract_holders)
            if target_id:
                state.maniac_victim_id = target_id
                self._record_visit(state, state.maniac_id, target_id, "kill_maniac")
                if show_night_targets:
                    await _notify_group(f"🪓 <b>Маніяк</b> заносить сокиру над: <code>{await _target_name(target_id)}</code>.")
                else:
                    await _notify_group("🪓 <b>Маніяк</b> виходить на полювання")
            state.maniac_action_taken = True

        # Доктор-садист
        if getattr(state, "sadistic_doctor_id", 0) and not getattr(state, "sadistic_action_taken", False):
            target_id = await _pick_one({state.sadistic_doctor_id, devil_id})
            if target_id:
                if random.choice([True, False]):
                    state.sadistic_heal_id = target_id
                    self._record_visit(state, state.sadistic_doctor_id, target_id, "heal_sadistic")
                    if show_night_targets:
                        await _notify_group(f"⚕️ <b>Доктор-садист</b> обрав для експерименту <code>{await _target_name(target_id)}</code>.")
                    else:
                        await _notify_group("⚕️ <b>Доктор-садист</b> зробив свій вибір")
                else:
                    state.sadistic_kill_id = target_id
                    self._record_visit(state, state.sadistic_doctor_id, target_id, "kill_sadistic")
                    if show_night_targets:
                        await _notify_group(f"⚕️ <b>Доктор-садист</b> вибрав жертву: <code>{await _target_name(target_id)}</code>.")
                    else:
                        await _notify_group("⚕️ <b>Доктор-садист</b> вибрав жертву")
            state.sadistic_action_taken = True

        # Комісар
        if getattr(state, "commissioner_id", 0) and not getattr(state, "commissioner_action_taken", False):
            excluded = {state.commissioner_id, devil_id, getattr(state, "sheriff_id", 0)} | devil_contract_holders
            target_id = await _pick_one(excluded)
            if target_id:
                if random.choice([True, False]):
                    state.commissioner_check_id = target_id
                    self._record_visit(state, state.commissioner_id, target_id, "check_comm")
                    if show_night_targets:
                        await _notify_group(f"🕵️ <b>Комісар Каттані</b> виходить на перевірку: <code>{await _target_name(target_id)}</code>.")
                    else:
                        await _notify_group("🕵️ <b>Комісар Каттані</b> виходить на перевірку")
                else:
                    state.commissioner_kill_id = target_id
                    self._record_visit(state, state.commissioner_id, target_id, "kill_comm")
                    if show_night_targets:
                        await _notify_group(f"🕵️ <b>Комісар Каттані</b> виходить на усунення: <code>{await _target_name(target_id)}</code>.")
                    else:
                        await _notify_group("🕵️ <b>Комісар Каттані</b> витягнув зброю з кобури")
            state.commissioner_action_taken = True

        # Волоцюга
        if getattr(state, "homeless_id", 0) and not getattr(state, "homeless_target_id", 0):
            target_id = await _pick_one({state.homeless_id, devil_id})
            if target_id:
                state.homeless_target_id = target_id
                self._record_visit(state, state.homeless_id, target_id, "homeless")
                if show_night_targets:
                    await _notify_group(f"🧥 Волоцюга спостерігає за <code>{await _target_name(target_id)}</code>.")
                else:
                    await _notify_group("🧥 Волоцюга спостерігає з темряви.")

        # Адвокат
        if getattr(state, "lawyer_id", 0) and not getattr(state, "lawyer_client_id", 0):
            target_id = await _pick_one({state.lawyer_id, devil_id})
            if target_id:
                state.lawyer_client_id = target_id
                self._record_visit(state, state.lawyer_id, target_id, "lawyer")
                await _notify_group("⚖️ <b>Адвокат</b> пішов по слідах Комісара.")

        # Журналіст
        if getattr(state, "journalist_id", 0) and len(getattr(state, "journalist_targets", [])) < 2:
            excluded = {state.journalist_id, devil_id}
            options = await self._get_alive_target_ids(chat_id, excluded)
            if options:
                random.shuffle(options)
                need = 2 - len(state.journalist_targets)
                state.journalist_targets.extend(options[:need])
                await _notify_group("✍🏻 Журналіст бере диктофон та блокнот")

        # Заражений
        if getattr(state, "infected_ids", None) and not getattr(state, "infected_action_taken", False):
            excluded = set(getattr(state, "infected_ids", []) or []) | {devil_id}
            target_id = await _pick_one(excluded)
            if target_id:
                state.infected_target_id = target_id
            state.infected_action_taken = True
            if target_id:
                await _notify_group("🧟 <b>Заражений</b> зробив свій вибір")

        # Брехун
        if getattr(state, "deceiver_id", 0) and not getattr(state, "deceiver_action_taken", False):
            target_id = await _pick_one({state.deceiver_id, devil_id})
            if target_id:
                state.deceiver_target_id = target_id
                self._record_visit(state, state.deceiver_id, target_id, "deceiver")
                await _notify_group("🎭 <b>Брехун</b> зробив свій вибір")
            state.deceiver_action_taken = True
    
    def _get_hanging_vote_time(self, chat_id: int) -> int:
        """Legacy sync helper (kept for compatibility)."""
        return 30

    async def _get_hanging_vote_time_async(self, chat_id: int) -> int:
        """Асинхронно отримати час фінального голосування (мін 20 сек, макс 180 сек)."""
        result = await self._db_fetchone(
            "SELECT hanging_vote_time FROM admin_panel WHERE group_id = %s",
            (chat_id,),
        )
        if result and result[0] is not None:
            vote_time = result[0]
            return max(20, min(180, vote_time))
        return 30
    
    async def _run_discussion_countdown(self, message: Message, bot: Bot, chat_id: int, remaining: int = 30):
        """Відлік фази обговорення для ВІДНОВЛЕННЯ після рестарту.

        Повторює логіку вкладеного discussion_timer() з day_function, але приймає
        залишок часу (remaining), порахований із збереженого discussion_started_at.
        Викликається лише з recover_active_games_after_restart, щоб гра не зависала
        у фазі обговорення після перезапуску бота.
        """
        try:
            self.print_log(f"♻️⏰ Відновлюю обговорення для chat_id={chat_id}, залишок {remaining}с...")
            update_interval = 5
            while remaining > 0:
                await asyncio.sleep(1)
                remaining -= 1
                state = self._get_state(chat_id)
                if not state.game_active or state.discussion_skipped:
                    return
                if remaining > 0 and (remaining % update_interval == 0 or remaining < update_interval):
                    if state.discussion_message:
                        try:
                            current_players_text = self._format_players_list_numbered_html(state.membersNames)
                            current_alive_roles_info = await self._get_alive_roles_info_async(chat_id, state)
                            votes_count = len(state.skip_discussion_votes)
                            total_players = len(state.membersList)
                            current_discussion_keyboard = InlineKeyboardMarkup(
                                inline_keyboard=[[InlineKeyboardButton(text=f"Пропустити обговорення ({votes_count}/{total_players})", callback_data="skip_discussion")]]
                            )
                            _disc_body = (
                                f"Список гравців:\n\n"
                                f"{current_players_text}\n\n"
                                f"{current_alive_roles_info}\n\n"
                            )
                            await state.discussion_message.edit_text(
                                emoji_to_premium(_disc_body, skip_vip_badges=False),
                                reply_markup=current_discussion_keyboard,
                                parse_mode="html",
                            )
                        except TelegramRetryAfter as e:
                            await asyncio.sleep(e.retry_after)
                        except Exception:
                            pass
            state = self._get_state(chat_id)
            state.discussion_started_at = None
            if state.game_active and not state.discussion_skipped:
                await self._start_voting_prep_timer(message, bot, chat_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.print_log(f" Помилка у відновленому обговоренні для chat_id={chat_id}: {e}")

    async def _start_voting_prep_timer(self, message: Message, bot: Bot, chat_id: int, *, skip_prep: bool = False):
        """Запустити відлік до голосування після обговорення. Якщо skip_prep=True (пропуск обговорення), одразу стартує голосування без другого відліку."""
        self.print_log(f"⏰ _start_voting_prep_timer викликано для chat_id={chat_id}, skip_prep={skip_prep}")
        state = self._get_state(chat_id)
        
        # Перевіряємо, чи гра ще активна
        if not state.game_active:
            self.print_log(f"⚠️ Гра неактивна для chat_id={chat_id}, не запускаю відлік")
            return
        
        prep_msg = None
        if not skip_prep:
            # Перевіряємо, чи відлік вже запущений
            if state.voting_prep_message:
                self.print_log(f"⚠️ Відлік вже запущений для chat_id={chat_id}")
                return
            
            # Отримуємо час до голосування
            prep_time = await self._get_voting_prep_time_async(chat_id)
            self.print_log(f"⏰ Час до голосування для chat_id={chat_id}: {prep_time} секунд")
            
            # Відправляємо повідомлення про відлік до голосування з обробкою flood control
            max_retries = 3
            for retry in range(max_retries):
                try:
                    prep_msg = await message.answer(
                        f"⏳ <b>Голосування через {prep_time} СЕКУНД</b>",
                        parse_mode="html"
                    )
                    state.voting_prep_message = prep_msg
                    self.print_log(f" Повідомлення про відлік відправлено для chat_id={chat_id}")
                    break  # Успішно відправлено
                except TelegramRetryAfter as e:
                    self.print_log(f"⚠️ Flood control при відправці повідомлення про відлік: чекаємо {e.retry_after} секунд (спроба {retry + 1}/{max_retries})")
                    await asyncio.sleep(e.retry_after)
                    if retry == max_retries - 1:
                        self.print_log(f" Не вдалося відправити повідомлення про відлік після {max_retries} спроб")
                        return
                except Exception as e:
                    self.print_log(f" Помилка відправки повідомлення про відлік для chat_id={chat_id}: {e}")
                    return
            
            if not prep_msg:
                self.print_log(f" Не вдалося отримати повідомлення про відлік для chat_id={chat_id}")
                return
            
            # Відлік з оновленням повідомлення кожні 5 секунд (щоб уникнути flood control)
            update_interval = 5  # Оновлюємо кожні 5 секунд
            remaining = prep_time
            
            while remaining > 0:
                # Чекаємо 1 секунду перед перевіркою
                await asyncio.sleep(1)
                remaining -= 1
                
                # Перевіряємо, чи гра ще активна
                state = self._get_state(chat_id)
                if not state.game_active:
                    return
                
                # Оновлюємо повідомлення тільки кожні 5 секунд або коли залишилося менше 5 секунд
                if remaining % update_interval == 0 or remaining < update_interval:
                    if remaining > 0:
                        try:
                            await prep_msg.edit_text(
                                f"⏳ <b>Голосування через {remaining} СЕКУНД</b>",
                                parse_mode="html"
                            )
                        except TelegramRetryAfter as e:
                            self.print_log(f"⚠️ Flood control при оновленні повідомлення про відлік: чекаємо {e.retry_after} секунд")
                            await asyncio.sleep(e.retry_after)
                            # Продовжуємо відлік
                        except Exception:
                            # Інші помилки (наприклад, повідомлення видалено) - просто продовжуємо
                            pass
        
        # Після закінчення відліку (або при skip_prep) запускаємо голосування
        state = self._get_state(chat_id)
        self.print_log(f"⏰ Відлік завершено для chat_id={chat_id}, game_active={state.game_active}")
        if state.game_active:
            # Захист від подвійного «Голосування розпочато!» (наприклад таймер + skip обговорення одночасно)
            if getattr(state, "voting_start_message_sent", False):
                voting_started_at = getattr(state, "voting_start_time", None)
                # Якщо прапор "залип" (немає часу старту або він старий) - скидаємо і дозволяємо запуск.
                is_stale = (
                    voting_started_at is None
                    or (datetime.now() - voting_started_at).total_seconds() > 120
                )
                if is_stale:
                    self.print_log(
                        f"⚠️ Застарілий voting_start_message_sent для chat_id={chat_id}; скидаю прапор і перезапускаю голосування"
                    )
                    state.voting_start_message_sent = False
                else:
                    self.print_log(f"⚠️ Голосування вже запущено для chat_id={chat_id}, пропускаю дубль")
                    return
            state.voting_start_message_sent = True
            # Видаляємо повідомлення про відлік (якщо було) та очищаємо посилання
            if prep_msg:
                try:
                    await prep_msg.delete()
                except Exception as e:
                    self.print_log(f"⚠️ Помилка видалення повідомлення про відлік: {e}")
            state.voting_prep_message = None
            
            # Reset votes before voting
            await self._db_execute_commit(
                "UPDATE users SET votes = %s WHERE id IN %s",
                (0, tuple(state.membersList) if state.membersList else (None,)),
            )
            state.voted_users.clear()
            state.list_of_all_votes.clear()
            state.expected_voter_ids.clear()

            # Кнопка в групі має відкривати ПП з ботом (а не перекидати назад у групу)
            bot_url = "https://t.me/sicilian_mafia_bot"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Проголосувати!", url=bot_url)]
            ])

            try:
                self.print_log(f"🗳️ Запускаю голосування для chat_id={chat_id}")
                afk_auto_choice_enabled = await self._is_afk_auto_choice_enabled_async(chat_id, state)
                # Відправляємо повідомлення про початок голосування з обробкою flood control
                voting_start_msg = None
                max_retries = 3
                for retry in range(max_retries):
                    try:
                        voting_text = (
                            "⚖️ <b>СУД ПАЛЕРМО</b> ⚖️\n\n"
                            "<blockquote>Місто прокинулось і вимагає крові. "
                            "Хтось сьогодні гойдатиметься на мотузці — і вирішувати вам.</blockquote>\n\n"
                            "🗳 Тисни «Проголосувати!» — вибір робиться в особистих.\n"
                            f"⏳ Час: <b>{AFK_AUTO_CHOICE_TOTAL_SECONDS} сек</b>"
                        )
                        if afk_auto_choice_enabled:
                            voting_text += (
                                f"\n<i>Через {AFK_AUTO_CHOICE_BOT_PICK_AT_SECONDS} с вибір за мовчунів зробить Сім'я.</i>"
                            )
                        voting_start_msg = await message.answer(
                            voting_text,
                            reply_markup=keyboard,
                            parse_mode="html"
                        )
                        break  # Успішно відправлено
                    except TelegramRetryAfter as e:
                        self.print_log(f"⚠️ Flood control при відправці повідомлення про голосування: чекаємо {e.retry_after} секунд (спроба {retry + 1}/{max_retries})")
                        await asyncio.sleep(e.retry_after)
                        if retry == max_retries - 1:
                            self.print_log(f" Не вдалося відправити повідомлення про голосування після {max_retries} спроб")
                            raise
                    except Exception as e:
                        self.print_log(f" Помилка відправки повідомлення про голосування: {e}")
                        raise
                
                state.voting_start_time = datetime.now()
                # Явно відкриваємо вікно денного голосування; пізні callback-и після закриття блокуємо цим прапорцем.
                state.day_vote_window_open = True
                state.afk_day_auto_choice_applied = False
                await self.voiting_function(message=message, bot=bot, membersList=state.membersList, chat_id=chat_id)
                if afk_auto_choice_enabled:
                    asyncio.create_task(self._auto_pick_day_votes_for_afk(bot, chat_id))
                # Чекаємо до 45 с, але якщо всі вже проголосували або вже є незворотна більшість - одразу переходимо до результатів
                deadline = asyncio.get_event_loop().time() + AFK_AUTO_CHOICE_TOTAL_SECONDS
                while asyncio.get_event_loop().time() < deadline:
                    state = self._get_state(chat_id)
                    expected = getattr(state, "expected_voter_ids", set())
                    # Всі, хто мав голосувати, вже проголосували
                    if expected and state.voted_users.issuperset(expected):
                        self.print_log(f"🗳️ Всі проголосували, завершую голосування для chat_id={chat_id}")
                        break
                    # Або вже є більшість голосів, яку неможливо перебити
                    if await self._has_irreversible_voting_majority_async(chat_id):
                        self.print_log(f"🗳️ Досягнуто незворотної більшості голосів для chat_id={chat_id}")
                        break
                    # Або вже достатньо голосів за пропуск - нікого не вішаємо, можна завершити
                    if await self._has_irreversible_skip_majority_async(chat_id):
                        self.print_log(f"🗳️ Більшість за пропуск, завершую голосування для chat_id={chat_id}")
                        break
                    await asyncio.sleep(2)
                
                # CRITICAL: Always call results_def if game is still active
                state = self._get_state(chat_id)  # Re-get state
                if state.game_active:
                    self.print_log(f"📊 Переходжу до результатів голосування для chat_id={chat_id}")
                    await self.results_def(message=message, bot=bot, chat_id=chat_id)
                else:
                    self.print_log(f"⚠️ Гра неактивна, не переходжу до результатів голосування для chat_id={chat_id}")
            except TelegramRetryAfter as e:
                self.print_log(f"⚠️ Flood control при запуску голосування для chat_id={chat_id}: чекаємо {e.retry_after} секунд")
                await asyncio.sleep(e.retry_after)
                # Повідомлення «Голосування розпочато» вже могло бути відправлено - не дублюємо. Тільки продовжуємо голосування/результати.
                state = self._get_state(chat_id)
                if state.game_active:
                    try:
                        afk_auto_choice_enabled = await self._is_afk_auto_choice_enabled_async(chat_id, state)
                        state.voting_start_time = getattr(state, "voting_start_time", None) or datetime.now()
                        state.day_vote_window_open = True
                        state.afk_day_auto_choice_applied = False
                        await self.voiting_function(message=message, bot=bot, membersList=state.membersList, chat_id=chat_id)
                        if afk_auto_choice_enabled:
                            asyncio.create_task(self._auto_pick_day_votes_for_afk(bot, chat_id))
                        deadline = asyncio.get_event_loop().time() + AFK_AUTO_CHOICE_TOTAL_SECONDS
                        while asyncio.get_event_loop().time() < deadline:
                            state = self._get_state(chat_id)
                            expected = getattr(state, "expected_voter_ids", set())
                            if expected and state.voted_users.issuperset(expected):
                                break
                            if await self._has_irreversible_voting_majority_async(chat_id):
                                self.print_log(f"🗳️ Досягнуто незворотної більшості голосів для chat_id={chat_id}")
                                break
                            if await self._has_irreversible_skip_majority_async(chat_id):
                                self.print_log(f"🗳️ Більшість за пропуск, завершую голосування для chat_id={chat_id}")
                                break
                            await asyncio.sleep(2)
                        state = self._get_state(chat_id)
                        if state.game_active:
                            await self.results_def(message=message, bot=bot, chat_id=chat_id)
                    except Exception as retry_error:
                        self.print_log(f" Помилка при повторній спробі запуску голосування: {retry_error}")
            except Exception as e:
                self.print_log(f" Помилка при запуску голосування для chat_id={chat_id}: {e}")
                import traceback
                self.print_log(f" Traceback: {traceback.format_exc()}")
                state = self._get_state(chat_id)
                state.voting_start_message_sent = False
        else:
            self.print_log(f"⚠️ Гра неактивна для chat_id={chat_id}, не запускаю голосування")

    async def _register_auto_day_vote_async(
        self,
        bot: Bot,
        chat_id: int,
        voter_id: int,
        candidate_id: Optional[int],
        *,
        secret_voting: bool,
    ) -> None:
        state = self._get_state(chat_id)
        if voter_id in state.voted_users:
            return

        state.voted_users.add(voter_id)
        state.day_voting_participants.add(voter_id)

        voter_name_row = await self._db_fetchone(
            "SELECT tg_name FROM users WHERE id = %s",
            (voter_id,),
        )
        voter_name = (voter_name_row[0] if voter_name_row else "Гравець") or "Гравець"
        voter_link = vip_mod.html_user_link(voter_id, voter_name)

        if candidate_id:
            await self._db_execute_commit(
                "UPDATE users SET votes = votes + 1 WHERE id = %s",
                (candidate_id,),
            )
            candidate_row = await self._db_fetchone(
                "SELECT tg_name FROM users WHERE id = %s",
                (candidate_id,),
            )
            candidate_name = (candidate_row[0] if candidate_row else "Гравець") or "Гравець"
            try:
                if secret_voting:
                    text = f"🗳 {voter_link} проголосував(ла) за…"
                else:
                    candidate_link = vip_mod.html_user_link(candidate_id, candidate_name)
                    text = f"🗳 {voter_link} проголосував(ла) за страту {candidate_link}."
                log_msg = await bot.send_message(
                    chat_id=chat_id,
                    text=emoji_to_premium(text, skip_vip_badges=False),
                    parse_mode="html",
                )
                state.voting_log_messages.append(log_msg)
            except Exception:
                pass
        else:
            try:
                log_msg = await bot.send_message(
                    chat_id=chat_id,
                    text=emoji_to_premium(
                        f"{voter_link} пропустив голосування",
                        skip_vip_badges=False,
                    ),
                    parse_mode="html",
                )
                state.voting_log_messages.append(log_msg)
            except Exception:
                pass

        if voter_id in state.message_list_of_candidates:
            try:
                await state.message_list_of_candidates[voter_id].delete()
            except Exception:
                pass
            state.message_list_of_candidates.pop(voter_id, None)

    async def _auto_pick_day_votes_for_afk(self, bot: Bot, chat_id: int, delay_seconds: float = AFK_AUTO_CHOICE_BOT_PICK_AT_SECONDS) -> None:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        state = self._get_state(chat_id)
        if not state.game_active or not getattr(state, "day_active", False):
            return
        if not getattr(state, "voting_start_time", None):
            return

        lock = self._afk_vote_pick_locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            state = self._get_state(chat_id)
            if not state.game_active or not getattr(state, "day_active", False):
                return
            if not getattr(state, "voting_start_time", None):
                return
            if getattr(state, "afk_day_auto_choice_applied", False):
                return

            _, _, secret_voting, _ = await self._get_thematic_settings_async(chat_id, state)

            expected_voters = set(getattr(state, "expected_voter_ids", set()) or set())
            pending_voters = [uid for uid in expected_voters if uid not in state.voted_users]
            if not pending_voters:
                state.afk_day_auto_choice_applied = True
                return

            for voter_id in pending_voters:
                state = self._get_state(chat_id)
                if voter_id in state.voted_users:
                    continue
                if not state.game_active or not getattr(state, "day_active", False):
                    return

                voter_alive_row = await self._db_fetchone(
                    "SELECT killed FROM users WHERE id = %s",
                    (voter_id,),
                )
                if not voter_alive_row or int(voter_alive_row[0]) == 1:
                    continue
                if voter_id in getattr(state, "silenced_ids", set()):
                    continue

                candidate_ids = await self._get_alive_target_ids(chat_id, {voter_id})
                candidate_id = random.choice(candidate_ids) if candidate_ids else None
                await self._register_auto_day_vote_async(
                    bot,
                    chat_id,
                    voter_id,
                    candidate_id,
                    secret_voting=secret_voting,
                )
            state.afk_day_auto_choice_applied = True
    
    async def skip_discussion(self, callback: CallbackQuery, bot: Bot):
        """Голосування за пропуск обговорення - якщо більшість проголосує, обговорення пропускається"""
        try:
            chat_id = callback.message.chat.id
            user_id = callback.from_user.id
            self.print_log(f"🔘 skip_discussion викликано для chat_id={chat_id}, user_id={user_id}")
            state = self._get_state(chat_id)
            
            # Перевіряємо, чи гра ще активна
            if not state.game_active:
                self.print_log(f"⚠️ Гра неактивна для chat_id={chat_id}")
                try:
                    await callback.answer(PLAY_ALERT_GAME_INACTIVE, show_alert=True)
                except TelegramBadRequest:
                    pass  # callback застарілий - Telegram не приймає answer
                return
            
            # Перевіряємо, чи відлік до голосування вже запущений
            if state.voting_prep_message:
                self.print_log(f"⚠️ Відлік до голосування вже запущено для chat_id={chat_id}")
                try:
                    await callback.answer(PLAY_ALERT_DISCUSSION_COUNTDOWN_STARTED, show_alert=True)
                except TelegramBadRequest:
                    pass
                return
            
            # Перевіряємо, чи обговорення вже пропущено
            if state.discussion_skipped:
                self.print_log(f"⚠️ Обговорення вже пропущено для chat_id={chat_id}")
                try:
                    await callback.answer(PLAY_ALERT_DISCUSSION_ALREADY_CLOSED, show_alert=True)
                except TelegramBadRequest:
                    pass
                return
            
            # Перевіряємо, чи гравець є учасником гри
            if user_id not in state.membersList:
                try:
                    await callback.answer(PLAY_ALERT_NOT_IN_THIS_PARTY, show_alert=True)
                except TelegramBadRequest:
                    pass
                return
            
            # Перевіряємо, чи гравець вже проголосував
            if user_id in state.skip_discussion_votes:
                try:
                    await callback.answer(PLAY_ALERT_SKIP_DISCUSSION_ALREADY, show_alert=True)
                except TelegramBadRequest:
                    pass
                return
            
            # Додаємо голос
            state.skip_discussion_votes.add(user_id)
            votes_count = len(state.skip_discussion_votes)
            total_players = len(state.membersList)
            majority_needed = (total_players // 2) + 1  # Більшість (50% + 1)
            
            self.print_log(f"📊 Голос за пропуск обговорення: {votes_count}/{total_players} (потрібно {majority_needed})")
            
            # Оновлюємо повідомлення з кількістю голосів
            if state.discussion_message:
                try:
                    # Отримуємо актуальні дані для повідомлення
                    players_text = self._format_players_list_numbered_html(state.membersNames)
                    alive_roles_info = await self._get_alive_roles_info_async(chat_id, state)
                    discussion_keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text=f"Пропустити обговорення ({votes_count}/{total_players})", callback_data="skip_discussion")]]
                    )
                    _skip_disc_body = (
                        f"Список гравців:\n\n"
                        f"{players_text}\n\n"
                        f"{alive_roles_info}\n\n"
                    )
                    await state.discussion_message.edit_text(
                        emoji_to_premium(_skip_disc_body, skip_vip_badges=False),
                        reply_markup=discussion_keyboard,
                        parse_mode="html",
                    )
                except Exception as e:
                    self.print_log(f"⚠️ Помилка оновлення повідомлення про обговорення: {e}")
            
            try:
                await callback.answer(f" Твій голос враховано! ({votes_count}/{total_players})")
            except TelegramBadRequest:
                pass
            
            # Перевіряємо, чи більшість проголосувала
            if votes_count >= majority_needed:
                self.print_log(f" Більшість проголосувала за пропуск обговорення ({votes_count}/{total_players})")
                
                # Позначаємо, що обговорення пропущено
                state.discussion_skipped = True
                # Скасовуємо завдання обговорення, якщо воно є
                if state.discussion_task and not state.discussion_task.done():
                    self.print_log(f"🛑 Скасовую discussion_task для chat_id={chat_id}")
                    state.discussion_task.cancel()
                    try:
                        await state.discussion_task
                    except asyncio.CancelledError:
                        self.print_log(f" discussion_task скасовано для chat_id={chat_id}")
                        pass

                # Оновлюємо повідомлення обговорення, але НЕ видаляємо список гравців
                if state.discussion_message:
                    try:
                        players_text = self._format_players_list_numbered_html(state.membersNames)
                        alive_roles_info = await self._get_alive_roles_info_async(chat_id, state)
                        _skipped_disc_body = (
                            f"Список гравців:\n\n"
                            f"{players_text}\n\n"
                            f"{alive_roles_info}\n\n"
                            "⏭️ Обговорення пропущено. Йде голосування."
                        )
                        await state.discussion_message.edit_text(
                            emoji_to_premium(_skipped_disc_body, skip_vip_badges=False),
                            reply_markup=None,
                            parse_mode="html",
                        )
                    except Exception as e:
                        self.print_log(f"⚠️ Не вдалося оновити повідомлення після пропуску обговорення: {e}")
                
                # Одразу запускаємо голосування без повторного відліку «обговорення»
                self.print_log(f"🚀 Запускаю голосування після пропуску обговорення для chat_id={chat_id}")
                await self._start_voting_prep_timer(callback.message, bot, chat_id, skip_prep=True)
        except TelegramBadRequest:
            # Застарілий callback (query is too old) - нічого не робимо
            pass
        except Exception as e:
            self.print_log(f" Помилка в skip_discussion: {e}")
            import traceback
            self.print_log(f" Traceback: {traceback.format_exc()}")
            try:
                await callback.answer(f" Помилка: {e}", show_alert=True)
            except (TelegramBadRequest, Exception):
                pass

    async def skip_night_action_handler(self, callback: CallbackQuery, bot: Bot):
        """Handler for skipping night actions when allow_skip_night_action is enabled"""
        try:
            # Parse callback data: skip_night_{role}_{chat_id}
            parts = callback.data.split("_")
            if len(parts) < 4:
                await callback.answer("⚠️ Некоректні дані", show_alert=True)
                return

            role = parts[2]  # doctor, mafia, etc.
            chat_id = int(parts[3])
            user_id = callback.from_user.id

            state = self._get_state(chat_id)

            # Verify game is active
            if not state.game_active:
                await callback.answer("⚠️ Гра неактивна", show_alert=True)
                return

            # Verify it's night time
            if getattr(state, "day_active", False):
                await callback.answer("🌅 Ніч уже закінчилась", show_alert=True)
                return

            # Verify skip is allowed
            allow_skip = await self._is_skip_night_action_allowed_async(chat_id, state)
            if not allow_skip:
                await callback.answer("⚠️ Пропуск нічної дії вимкнено", show_alert=True)
                return

            # Handle skip based on role
            if role == "doctor":
                if user_id != state.doctor_id:
                    await callback.answer("⚠️ Це меню тільки для Лікаря", show_alert=True)
                    return
                if state.doctor_action_taken:
                    await callback.answer("⚠️ Ти вже зробив свій вибір цієї ночі", show_alert=True)
                    return

                state.doctor_action_taken = True
                await callback.message.edit_text(
                    "💊 <b>Лікар</b>\n\n"
                    "Ти вирішив пропустити лікування цієї ночі.",
                    parse_mode="html"
                )
                await callback.answer("⏭️ Дію пропущено")

            elif role == "mafia":
                if user_id != state.all_capone_id:
                    await callback.answer("⚠️ Це меню тільки для Аль Капоне", show_alert=True)
                    return
                if state.mafia_action_taken:
                    await callback.answer("⚠️ Ти вже зробив свій вибір цієї ночі", show_alert=True)
                    return

                state.mafia_action_taken = True
                await callback.message.edit_text(
                    "🤵 <b>Аль Капоне</b>\n\n"
                    "Ти вирішив пропустити вбивство цієї ночі.",
                    parse_mode="html"
                )
                await callback.answer("⏭️ Дію пропущено")

            else:
                await callback.answer("⚠️ Невідома роль", show_alert=True)

        except Exception as e:
            self.print_log(f"⚠️ Помилка в skip_night_action_handler: {e}")
            try:
                await callback.answer(f"⚠️ Помилка: {e}", show_alert=True)
            except Exception:
                pass

    async def _build_endgame_summary_async(self, chat_id: int, winner: str) -> str:
        """Build end-of-game summary with winners/losers lists"""
        state = self._get_state(chat_id)
        creator_result = await self._db_fetchone(
            "SELECT creator_id FROM admin_panel WHERE group_id = %s",
            (chat_id,),
        )
        creator_id = creator_result[0] if creator_result else 0

        roster = state.all_membersNames if state.all_membersNames else state.membersNames
        winners = []
        losers = []

        for player_id, name_html in roster:
            result = await self._db_fetchone(
                "SELECT role, killed, tg_name FROM users WHERE id = %s",
                (player_id,),
            )
            if not result:
                continue
            role_name = result[0] if result[0] else "Невідома роль"
            killed = result[1] if len(result) > 1 else 0
            tg_name = result[2] if len(result) > 2 else "Гравець"
            
            # Формуємо тег гравця (завжди використовуємо тег)
            player_link = vip_mod.html_user_link(player_id, tg_name)
            
            # Визначаємо статус (живий/мертвий)
            status_emoji = "💀" if killed == 1 else "❤️"
            status_text = "Мертвий" if killed == 1 else "Живий"
            
            alignment = self._classify_alignment(creator_id, chat_id, role_name, state)
            
            # Визначаємо, чи гравець переміг чи програв
            is_winner = False
            devil_failed_holders = getattr(state, "devil_failed_contract_holder_ids", set())
            devil_contract_holders = getattr(state, "devil_contract_holders", set())
            if player_id in devil_failed_holders:
                is_winner = False  # Жертва не виконала контракт - не в списку переможців
            elif role_name == "Диявол" and winner == "devil":
                is_winner = True  # Диявол у списку переможців (навіть якщо повішений), якщо контракт виконано
            elif winner == "devil" and player_id in devil_contract_holders and player_id not in devil_failed_holders:
                is_winner = True  # Той, хто підписав контракт і приніс душі - теж переможець разом із Дияволом
            # Самогубець перемагає разом із переможцями: якщо його повісили - з мафією при перемозі мафії, з мирними при перемозі мирних
            elif role_name == "Самогубець":
                is_winner = bool(getattr(state, "suicide_was_lynched", False) and winner in ("mafia", "civilians"))
            elif killed == 1:
                # Мертвий гравець завжди програє (окрім самогубця, який вже оброблений вище)
                is_winner = False
            else:
                # Тільки живі гравці можуть перемогти
                if winner == "mafia":
                    is_winner = (alignment == "evil")
                elif winner == "maniac":
                    is_winner = (role_name == "Маніяк")
                elif winner == "infected":
                    is_winner = (role_name == "Заражений")
                elif winner == "devil":
                    is_winner = (role_name == "Диявол")
                else:  # civilians
                    # Нейтральні ролі (Коханка тощо) перемагають разом з мирними жителями
                    # Самогубець вже оброблений вище
                    is_winner = (alignment == "good" or alignment == "neutral")
            
            # Формуємо запис: роль під нахилом (курсив) - ім'я, без емодзі
            role_safe = html.escape(role_name)
            if is_winner:
                entry = f"<i>{role_safe}</i> - {player_link}"
                winners.append(entry)
            else:
                entry = f"<i>{role_safe}</i> - {player_link}"
                losers.append(entry)

        winners_text = "\n".join(winners) if winners else "<i>Немає переможців</i>"
        losers_text = "\n".join(losers) if losers else "<i>Немає програвших</i>"

        # Визначаємо повідомлення про перемогу (усе жирним у всіх кінцівках)
        victory_messages = {
            "mafia": "<blockquote>Темрява взяла місто під контроль - закон мовчить.\nCosa Nostra диктує свої правила.</blockquote>",
            "civilians": "<blockquote>Світанок приніс спокій - постріли стихли, вулиці знову дихають.\nМирні жителі вистояли.</blockquote>",
            "maniac": "<blockquote>Ні мафія, ні закон не змогли зупинити його.\nМісто спорожніло - тиша стала фінальним вироком.</blockquote>",
            "infected": "<blockquote>Епідемія поширилася на всіх. Ніхто не встояв.\nМісто захоплене заразою.</blockquote>",
            "devil": "<blockquote>Контракт виконано - борги сплачено.\nДвох душ виявилось достатньо.</blockquote>",
        }
        
        victory_text = victory_messages.get(winner, "")
        
        final_message = {
            "mafia": "Гру завершено. Перемогла мафія.",
            "civilians": "Гру завершено. Місто очищено від мафії.",
            "maniac": "Гру завершено. Хаос переміг.",
            "infected": "Гру завершено. Епідемія завершилась.",
            "devil": "Гру завершено. Пекло відкрило свої двері.",
        }.get(winner, "Гру завершено.")

        duration_line = ""
        dur = _format_game_duration_uk(getattr(state, "game_started_at", None))
        if dur:
            duration_line = f"\n\n<b>Гра тривала:</b> {html.escape(dur)}"

        return (
            f"<b>{final_message}</b>\n"
            f"{victory_text}\n\n"
            "🏆 <b>Переможці</b>\n"
            f"{winners_text}\n\n"
            "🕯 <b>Не дожили до світанку</b>\n"
            f"{losers_text}"
            f"{duration_line}"
        )

    def _get_endgame_video_path(self, winner: str):
        """Повертає шлях до відео за переможцем, або None якщо відео немає. Шукає відносно play.py і відносно cwd."""
        videos = {
            "mafia": "Перемогла мафія..mp4",
            "civilians": "Місто очищено від мафії..mp4",
            "maniac": "Хаос переміг..mp4",
            "devil": "Пекло відкрило свої двері..mp4",
        }
        name = videos.get(winner)
        if not name:
            return None
        # 1) Відносно розташування play.py (project/Media/)
        media_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Media'))
        path = os.path.join(media_dir, name)
        if os.path.isfile(path):
            return path
        # 2) Відносно поточної робочої директорії (Media/ або project/Media/)
        for base in (os.getcwd(), os.path.abspath(os.path.join(os.getcwd(), '..'))):
            p = os.path.join(base, "Media", name)
            if os.path.isfile(p):
                return p
        return None

    async def _send_endgame_summary(self, message: Message, bot: Bot, chat_id: int, winner: str):
        """Відправляє підсумок гри: відео з підписом (якщо є файл за переможцем) або лише текст."""
        summary = emoji_to_premium(await self._build_endgame_summary_async(chat_id, winner), skip_vip_badges=False)
        video_path = self._get_endgame_video_path(winner)
        if not video_path:
            self.print_log(f"⚠️ Відео для переможця {winner} не знайдено (перевір папку Media/).")
            await message.answer(summary, parse_mode="html")
            return
        path_to_send = video_path
        try:
            path_to_send = await self._prepare_video_9_16(video_path) or video_path
            if not path_to_send or not os.path.isfile(path_to_send):
                path_to_send = video_path
            await bot.send_video(
                chat_id=chat_id,
                video=FSInputFile(path_to_send),
                caption=summary,
                parse_mode="html",
            )
        except Exception as e:
            self.print_log(f"⚠️ Не вдалося надіслати відео підсумку: {e}")
            if path_to_send != video_path and os.path.isfile(video_path):
                try:
                    await bot.send_video(
                        chat_id=chat_id,
                        video=FSInputFile(video_path),
                        caption=summary,
                        parse_mode="html",
                    )
                except Exception as e2:
                    self.print_log(f"⚠️ Відправка оригіналу відео теж не вдалася: {e2}")
                    await message.answer(summary, parse_mode="html")
            else:
                try:
                    await message.answer(summary, parse_mode="html")
                except Exception:
                    pass
        finally:
            if path_to_send and path_to_send != video_path and os.path.isfile(path_to_send):
                try:
                    os.unlink(path_to_send)
                except OSError:
                    pass

    async def _handle_game_end(self, message: Message, bot: Bot, chat_id: int, winner: str):
        """Завершення гри після перемоги: підсумок (з відео), приватні повідомлення, винагороди, досягнення, розмут, game_active = False."""
        await self._send_endgame_summary(message, bot, chat_id, winner)
        await self._award_win_rewards(bot, chat_id, winner)
        roster_data, game_events = await self._build_roster_for_achievements_async(chat_id, winner)
        try:
            await self._record_mafia_game_stats(chat_id, winner, roster_data or [])
        except Exception as e:
            self.print_log(f"Статистика топу мафії: {e}")
        # Персональні повідомлення програвшим гравцям залежно від ролі
        try:
            await self._send_personal_endgame_messages(bot, winner, roster_data)
        except Exception as e:
            self.print_log(f"Помилка персональних фінальних повідомлень: {e}")
        if roster_data or game_events:
            try:
                from commands.story_achievements import process_achievements_after_game
                await process_achievements_after_game(bot, roster_data or [], winner, game_events=game_events)
            except Exception as e:
                self.print_log(f"Досягнення після гри: {e}")
        await self._unmute_users_muted_during_game(bot, chat_id)
        state = self._get_state(chat_id)
        try:
            # Важливо: імпорт модуля, а не з функціями - щоб не “ламалось” при циклах імпорту
            import commands.casino as casino_mod
            await casino_mod.resolve_casino_after_game(bot, chat_id, state, winner)
        except Exception as e:
            self.print_log(f"Казино «У Лева»: {e}")
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"🎲 <b>Казино «У Лева»:</b> помилка підбиття підсумків: <code>{html.escape(str(e))}</code>",
                    parse_mode="html",
                )
            except Exception:
                pass
        state.game_active = False
        self._reset_last_word_tracking(state)

    async def _has_irreversible_voting_majority_async(self, chat_id: int) -> bool:
        """
        Перевіряє, чи вже є така кількість голосів за когось, що її неможливо перебити
        навіть якщо всі, хто ще не проголосував, проголосують інакше.
        Логіка: якщо хтось набрав > половини голосів від усіх живих гравців,
        інші вже не можуть отримати більше.
        """
        state = self._get_state(chat_id)
        if not state.membersList:
            return False

        # Знаходимо всіх живих гравців у цій грі
        alive_ids: list[int] = []
        for pid in state.membersList:
            row = await self._db_fetchone(
                "SELECT killed FROM users WHERE id = %s",
                (pid,),
            )
            if row and row[0] == 0:
                alive_ids.append(pid)

        if not alive_ids:
            return False

        # Отримуємо поточні голоси по всіх живих
        try:
            rows = await self._db_fetchall(
                "SELECT id, COALESCE(votes, 0) FROM users WHERE id IN %s",
                (tuple(alive_ids),),
            )
            rows = rows or []
        except Exception:
            return False

        if not rows:
            return False

        total_alive = len(alive_ids)
        max_votes = max(int(v[1] or 0) for v in rows)

        # Незворотна більшість: більше половини живих
        return max_votes > total_alive / 2

    async def _has_irreversible_skip_majority_async(self, chat_id: int) -> bool:
        """
        Чи вже достатньо голосів за пропуск, щоб навіть якщо всі, хто ще не проголосував,
        проголосують за одного кандидата - пропуск все одно виграє (нікого не вішаємо).
        Тоді можна одразу завершити голосування.
        """
        state = self._get_state(chat_id)
        expected = getattr(state, "expected_voter_ids", set())
        if not expected or len(state.voted_users) < 1:
            return False
        # Поточні голоси з БД (тільки живі)
        alive_ids = []
        for pid in state.membersList:
            row = await self._db_fetchone(
                "SELECT killed FROM users WHERE id = %s",
                (pid,),
            )
            if row and row[0] == 0:
                alive_ids.append(pid)
        if not alive_ids:
            return False
        try:
            rows = await self._db_fetchall(
                "SELECT id, COALESCE(votes, 0) FROM users WHERE id IN %s",
                (tuple(alive_ids),),
            )
            rows = rows or []
        except Exception:
            return False
        if not rows:
            return False
        total_votes_cast = sum(int(v[1] or 0) for v in rows)
        max_votes = max(int(v[1] or 0) for v in rows)
        skip_count = len(state.voted_users) - total_votes_cast
        remaining = len(expected) - len(state.voted_users)
        # Пропуск вже незворотний: навіть якщо всі remaining проголосують за одного, skip_count >= новий max_votes
        return skip_count >= max_votes + remaining

    async def _award_win_rewards(self, bot, chat_id: int, winner: str):
        """Нарахувати винагороду переможцям (база 20 лір; VIP +25%, VIP+ +50%)."""
        state = self._get_state(chat_id)
        creator_result = await self._db_fetchone(
            "SELECT creator_id FROM admin_panel WHERE group_id = %s",
            (chat_id,),
        )
        creator_id = creator_result[0] if creator_result else 0

        roster = state.all_membersNames if state.all_membersNames else state.membersNames
        base_reward = 20

        winners_list = []
        
        for player_id, name_html in roster:
            result = await self._db_fetchone(
                "SELECT role, killed FROM users WHERE id = %s",
                (player_id,),
            )
            if not result:
                continue
            role_name = result[0] if result[0] else "Невідома роль"
            killed = result[1] if len(result) > 1 else 0
            
            alignment = self._classify_alignment(creator_id, chat_id, role_name, state)
            
            # Визначаємо, чи гравець переміг (використовуємо ту саму логіку, що й у _build_endgame_summary)
            is_winner = False
            devil_failed_holders = getattr(state, "devil_failed_contract_holder_ids", set())
            devil_contract_holders = getattr(state, "devil_contract_holders", set())
            if player_id in devil_failed_holders:
                is_winner = False
            elif role_name == "Диявол" and winner == "devil":
                is_winner = True  # Диявол у переможцях навіть якщо повішений
            elif winner == "devil" and player_id in devil_contract_holders and player_id not in devil_failed_holders:
                is_winner = True  # Виконавець контракту (приніс душі) теж отримує винагороду
            # Самогубець перемагає разом із переможцями (з мафією або з мирними), якщо його повісили
            elif role_name == "Самогубець":
                is_winner = bool(getattr(state, "suicide_was_lynched", False) and winner in ("mafia", "civilians"))
            elif killed == 1:
                # Мертвий гравець завжди програє (окрім самогубця, який вже оброблений вище)
                is_winner = False
            else:
                # Тільки живі гравці можуть перемогти
                if winner == "mafia":
                    is_winner = (alignment == "evil")
                elif winner == "maniac":
                    is_winner = (role_name == "Маніяк")
                elif winner == "infected":
                    is_winner = (role_name == "Заражений")
                elif winner == "devil":
                    is_winner = (role_name == "Диявол")
                else:  # civilians
                    # Нейтральні ролі (Коханка тощо) перемагають разом з мирними жителями
                    # Самогубець вже оброблений вище
                    is_winner = (alignment == "good" or alignment == "neutral")
            
            # Мертві гравці не отримують винагороду (окрім самогубця, який переміг)
            if not is_winner:
                continue
            # Гравці, які покинули гру до кінця, не отримують винагороду та повідомлення
            if player_id not in state.membersList:
                continue
            
            if is_winner:
                tier = vip_mod.active_vip_tier(player_id)
                mult = vip_mod.game_win_reward_multiplier(tier)
                reward_amount = int(round(base_reward * mult))
                # Нарахувати винагороду
                await self._db_execute_commit(
                    """
                    UPDATE users
                    SET balance = COALESCE(balance, 0) + %s
                    WHERE id = %s
                    """,
                    (reward_amount, player_id),
                )
                
                winners_list.append(player_id)
                
                # Відправити повідомлення гравцю про винагороду
                try:
                    new_balance = await self._get_user_balance_async(player_id)
                    bonus_line = ""
                    if tier == "vip":
                        bonus_line = "\n⚒️ <i>Бонус VIP: +25% до винагороди за перемогу.</i>\n"
                    elif tier == "vip_plus":
                        bonus_line = "\n⛏️ <i>Бонус VIP+: +50% до винагороди за перемогу.</i>\n"
                    await bot.send_message(
                        chat_id=player_id,
                        text=emoji_to_premium(
                            f"🎉 <b>Вітаємо з перемогою!</b> 🎉\n\n"
                            f"💰 Ви отримали <b>{reward_amount} лір</b> за перемогу в грі!"
                            f"{bonus_line}\n"
                            f"💵 Ваш баланс: <b>{new_balance} лір</b>"
                        ),
                        parse_mode="html"
                    )
                except Exception as e:
                    self.print_log(f"Помилка відправки повідомлення про винагороду {player_id}: {e}")
        
        if winner == "devil":
            devil_failed_holders = getattr(state, "devil_failed_contract_holder_ids", set())
            devil_contract_holders = getattr(state, "devil_contract_holders", set())
            covenant_reward_ids: set[int] = set()
            for pid, _name_html in roster:
                row = await self._db_fetchone(
                    "SELECT role, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if not row:
                    continue
                rname = row[0] or ""
                killed = row[1] if len(row) > 1 else 0
                if rname == "Диявол":
                    covenant_reward_ids.add(pid)
                elif pid in devil_contract_holders and pid not in devil_failed_holders and (killed or 0) == 0:
                    covenant_reward_ids.add(pid)
            for pid in covenant_reward_ids:
                rrow = await self._db_fetchone(
                    "SELECT role FROM users WHERE id = %s",
                    (pid,),
                )
                ronly = (rrow[0] if rrow else "") or ""
                if ronly != "Диявол" and pid not in state.membersList:
                    continue
                granted = grant_portal_reward(pid, "devil_covenant")
                if granted:
                    await self._db_execute_commit(
                        "UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s",
                        (100, pid),
                    )
                    try:
                        await bot.send_message(
                            chat_id=pid,
                            text=emoji_to_premium(
                                "💥 <b>Контракт з дияволом</b>\n\n"
                                "За перемогу Диявола ти отримуєш унікальний баф <b>«Контракт з дияволом»</b> "
                                "та <b>100 лір</b>.\n\n"
                                "<i>Кажуть, угоди такого рівня не укладають просто так.</i>\n\n"
                                "У грі: один раз за партію активуй кнопку вдень або вночі - "
                                "до кінця поточного дня й ночі жодна ворожа дія проти тебе не спрацює."
                            ),
                            parse_mode="html",
                        )
                    except Exception as e:
                        self.print_log(f"Помилка повідомлення про контракт з дияволом {pid}: {e}")
        
        if winners_list:
            self.print_log(
                f"💰 Нараховано винагороду за перемогу {len(winners_list)} переможцям "
                f"(база {base_reward} лір; VIP ×1.25, VIP+ ×1.5)"
            )

    async def _build_roster_for_achievements_async(self, chat_id: int, winner: str) -> tuple[list[dict], list[tuple]]:
        """Збирає для кожного гравця (player_id, role_name, killed, is_winner) для оновлення досягнень. Повертає (roster_data, game_achievement_events)."""
        state = self._get_state(chat_id)
        creator_result = await self._db_fetchone(
            "SELECT creator_id FROM admin_panel WHERE group_id = %s",
            (chat_id,),
        )
        creator_id = creator_result[0] if creator_result else 0
        roster = state.all_membersNames if state.all_membersNames else state.membersNames
        if not roster:
            return ([], list(getattr(state, "game_achievement_events", [])) if state else [])
        result = []
        for player_id, _name_html in roster:
            row = await self._db_fetchone(
                "SELECT role, killed FROM users WHERE id = %s",
                (player_id,),
            )
            if not row:
                continue
            role_name = row[0] if row[0] else "Мирний житель"
            killed = row[1] if len(row) > 1 else 0
            alignment = self._classify_alignment(creator_id, chat_id, role_name, state)
            is_winner = False
            devil_failed_holders = getattr(state, "devil_failed_contract_holder_ids", set())
            if player_id in devil_failed_holders:
                is_winner = False
            elif role_name == "Диявол" and winner == "devil":
                is_winner = True
            elif role_name == "Самогубець":
                is_winner = bool(getattr(state, "suicide_was_lynched", False) and winner in ("mafia", "civilians"))
            elif killed == 1:
                is_winner = False
            else:
                if winner == "mafia":
                    is_winner = (alignment == "evil")
                elif winner == "maniac":
                    is_winner = (role_name == "Маніяк")
                elif winner == "infected":
                    is_winner = (role_name == "Заражений")
                elif winner == "devil":
                    is_winner = (role_name == "Диявол")
                else:
                    is_winner = (alignment == "good" or alignment == "neutral")
            result.append({
                "player_id": player_id,
                "role_name": role_name,
                "killed": killed,
                "is_winner": is_winner,
            })
        game_events = list(getattr(state, "game_achievement_events", [])) if state else []
        return (result, game_events)

    async def _send_personal_endgame_messages(self, bot: Bot, winner: str, roster_data: list[dict]) -> None:
        """
        Надсилає в особисті повідомлення фінальний текст програшу залежно від ролі.
        Використовує emoji_to_premium для емодзі.
        """
        if not roster_data:
            return

        # Базові тексти програшу для конкретних ролей
        role_texts: dict[str, str] = {
            # Мафіозна команда (Мафія, Аль Капоне) програла
            "mafia_team": (
                "🔫 <b>Гру завершено.</b>\n"
                "План був майже ідеальний…\n"
                "але цього разу місто виявилось розумнішим."
            ),
            # Рольові тексти
            "Комісар Каттані": (
                "👮 <b>Гру завершено.</b>\n"
                "Ви були близькі до правди.\n"
                "Можливо навіть занадто.\n"
                "Але в цьому місті ті, хто знають забагато,\n"
                "рідко доживають до ранку."
            ),
            "Шериф": (
                "👮 <b>Гру завершено.</b>\n"
                "Ви були близькі до правди.\n"
                "Можливо навіть занадто.\n"
                "Але в цьому місті ті, хто знають забагато,\n"
                "рідко доживають до ранку."
            ),
            "Мирний житель": (
                "📄 <b>Гру завершено.</b>\n"
                "Ви намагались врятувати місто…\n"
                "але темрява цієї ночі виявилась сильнішою.\n"
                "Мафія знову сховалась у тінях."
            ),
            "Лікар": (
                "🩸 <b>Гру завершено.</b>\n"
                "Ви намагалися врятувати тих, кого ще можна було врятувати.\n"
                "Але цієї ночі навіть медицина була безсилою."
            ),
            "Коханка": (
                "⚱️ <b>Гру завершено.</b>\n"
                "Ваші чари працювали…\n"
                "але цього разу місто виявилось сильнішим за спокусу."
            ),
            "Маніяк": (
                "🔪 <b>Гру завершено.</b>\n"
                "Місто боялось вас…\n"
                "але цієї ночі мисливець сам став здобиччю."
            ),
            "Самогубець": (
                "🎯 <b>Гру завершено.</b>\n"
                "Ви чекали моменту…\n"
                "але місто вирішило все без вас."
            ),
            "Волоцюга": (
                "⚠️ <b>Гру завершено.</b>\n"
                "Вулиці знають багато історій.\n"
                "Сьогодні одна з них закінчилась для вас."
            ),
            "Щасливчик": (
                "☠️ <b>Гру завершено.</b>\n"
                "Удача довго була поруч.\n"
                "Але цієї ночі вона вирішила піти."
            ),
            "Адвокат": (
                "😎 <b>Гру завершено.</b>\n"
                "Ви намагалися захистити клієнта…\n"
                "але суд цієї ночі був безжальним."
            ),
            "Медсестра": (
                "🩸 <b>Гру завершено.</b>\n"
                "Ви допомагали тим, хто боровся за життя.\n"
                "Але ніч виявилась сильнішою."
            ),
            "Брехун": (
                "🃏 <b>Гру завершено.</b>\n"
                "Ваші слова майже переконали місто…\n"
                "але правда все ж вирвалась назовні."
            ),
            "Диявол": (
                "☠️ <b>Гру завершено.</b>\n"
                "Ви пропонували угоди темряви…\n"
                "але цієї ночі навіть диявол програв."
            ),
            "Клоун": (
                "🚬 <b>Гру завершено.</b>\n"
                "Місто сміялось разом із вами…\n"
                "але цього разу фінальний жарт був не ваш."
            ),
            "Камікадзе": (
                "🎯 <b>Гру завершено.</b>\n"
                "Ви були готові підірвати всю гру.\n"
                "Але план цієї ночі не спрацював."
            ),
            "Журналіст": (
                "🪪 <b>Гру завершено.</b>\n"
                "Ви шукали правду серед брехні.\n"
                "Але цієї ночі історію написали без вас."
            ),
        }

        for entry in roster_data:
            player_id = entry.get("player_id")
            role_name = (entry.get("role_name") or "").strip()
            is_winner = bool(entry.get("is_winner"))
            if not player_id or is_winner:
                continue

            text: str | None = None

            # Якщо програла мафія - окремий текст для мафіозних ролей
            if winner != "mafia" and role_name in ("Мафія", "Аль Капоне"):
                text = role_texts["mafia_team"]
            else:
                text = role_texts.get(role_name)

            if not text:
                continue

            try:
                await bot.send_message(
                    chat_id=player_id,
                    text=emoji_to_premium(text),
                    parse_mode="html",
                )
            except Exception:
                continue

    def _get_user_balance(self, user_id: int) -> int:
        """Legacy sync helper (kept for compatibility)."""
        return 0

    async def _get_user_balance_async(self, user_id: int) -> int:
        """Асинхронно отримати баланс користувача."""
        result = await self._db_fetchone(
            "SELECT COALESCE(balance, 0) FROM users WHERE id = %s",
            (user_id,),
        )
        return result[0] if result else 0

    async def portal_night_target_callback(self, callback: CallbackQuery, bot: Bot):
        """Єдиний обробник portal_night: (без повторної реєстрації щоночі)."""
        data = callback.data or ""
        if not data.startswith("portal_night:"):
            return
        parts = data.split(":", 3)
        if len(parts) != 4:
            await callback.answer("Некоректні дані.", show_alert=True)
            return
        _, chat_s, buff_id, target_s = parts
        try:
            chat_id = int(chat_s)
            target_id = int(target_s)
        except ValueError:
            await callback.answer("Некоректні дані.", show_alert=True)
            return
        state = self._get_state(chat_id)
        user_id = callback.from_user.id if callback.from_user else 0
        if user_id not in state.membersList:
            await callback.answer("Ти не в цій грі.", show_alert=True)
            return
        r = await self._db_fetchone(
            "SELECT killed FROM users WHERE id = %s",
            (user_id,),
        )
        if r and (r[0] or 0) == 1:
            await callback.answer("Мертві не діють.", show_alert=True)
            return
        if target_id not in state.membersList:
            await callback.answer("Невірна ціль.", show_alert=True)
            return
        if target_id in getattr(state, "devil_covenant_night_shield", set()):
            await callback.answer("💥 На цього гравця не діє - контракт з дияволом.", show_alert=True)
            return
        if buff_id == "portal_ribbon":
            state.portal_ribbon_protected[target_id] = user_id
        elif buff_id == "portal_seeds":
            state.portal_seeds_skip.add(target_id)
        elif buff_id == "portal_spirit_2021":
            state.portal_spirit_isolated.add(target_id)
        elif buff_id == "portal_smell_fry":
            state.portal_smell_fry_targets.add(target_id)
        elif buff_id == "portal_kyiv_taste":
            state.portal_kyiv_taste[target_id] = user_id
        if not try_consume_buff(chat_id, user_id, buff_id):
            await callback.answer("Баф уже використано або недоступний.", show_alert=True)
            return
        try:
            if callback.message:
                await callback.message.edit_text(" Баф використано.", reply_markup=None)
        except Exception:
            pass
        await callback.answer("Використано.", show_alert=False)

    def _record_visit(self, state: GameState, visitor_id: int, target_id: int, action: str):
        """Track nightly visits for roles like Бомж."""
        if visitor_id and target_id:
            state.visit_log.append((visitor_id, target_id, action))

    def _resolve_night_killer_for_target(self, state: GameState, target_id: int) -> Optional[int]:
        """
        Хто відповідає за нічну спробу вбити target_id (Tommy Gun, талісман нападника, міна).
        Не покладаємось на порядок visit_log: спочатку збіг з активним victim_id / maniac_victim_id тощо.
        """
        tid = int(target_id)
        log = list(getattr(state, "visit_log", []) or [])
        vid = int(getattr(state, "victim_id", 0) or 0)
        if vid == tid:
            for action in ("kill_don", "kill_mafia"):
                for visitor_id, visited_id, act in log:
                    if int(visited_id) == tid and act == action:
                        return int(visitor_id)
        mv = int(getattr(state, "maniac_victim_id", 0) or 0)
        if mv == tid:
            for visitor_id, visited_id, act in log:
                if int(visited_id) == tid and act == "kill_maniac":
                    return int(visitor_id)
        cki = int(getattr(state, "commissioner_kill_id", 0) or 0)
        if cki == tid:
            for visitor_id, visited_id, act in log:
                if int(visited_id) == tid and act == "kill_comm":
                    return int(visitor_id)
        ski = int(getattr(state, "sadistic_kill_id", 0) or 0)
        if ski == tid:
            for visitor_id, visited_id, act in log:
                if int(visited_id) == tid and act == "kill_sadistic":
                    return int(visitor_id)
        cxs = getattr(state, "custom_kill_ids", []) or []
        if tid in cxs:
            for visitor_id, visited_id, act in log:
                if int(visited_id) == tid and act == "kill_custom":
                    return int(visitor_id)
        for visitor_id, visited_id, action in log:
            if int(visited_id) == tid and action in (
                "kill_don",
                "kill_mafia",
                "kill_maniac",
                "kill_comm",
                "kill_yakuza",
                "kill_sadistic",
                "kill_custom",
            ):
                return int(visitor_id)
        # Якщо замах записаний у state, але рядка в visit_log немає — без killer_id не спрацьовує
        # Tommy Gun / талісман нападника / пост-ефекти; лікар усе одно захищає через protection_ids.
        if vid == tid:
            cap = int(getattr(state, "all_capone_id", 0) or 0)
            if cap:
                return cap
            for mid in getattr(state, "mafia_ids", []) or []:
                if mid:
                    return int(mid)
        if mv == tid:
            maniac_id = int(getattr(state, "maniac_id", 0) or 0)
            if maniac_id:
                return maniac_id
        if cki == tid:
            comm_id = int(getattr(state, "commissioner_id", 0) or 0)
            if comm_id:
                return comm_id
        if ski == tid:
            sad_id = int(getattr(state, "sadistic_doctor_id", 0) or 0)
            if sad_id:
                return sad_id
        return None

    def _flashlight_killer_is_genuine(self, state: GameState, target_id: int) -> bool:
        """True, лише якщо у visit_log є СПРАВЖНІЙ запис нічного вбивства саме на target_id.

        Потрібно для Ліхтарика (reveal_killer). При перенаправленні удару
        (Магніт/Чорна діра, «Водний потік» Русалки, купальська «Щаслива ніч»)
        victim_id переноситься на нову ціль, а запис «kill_*» у visit_log
        лишається на ПЕРВІСНІЙ цілі. Тоді _resolve_night_killer_for_target падає
        у фолбек і повертає Аль Капоне, хоча на цю жертву ніхто прямо не ходив.
        Така атрибуція коректна для Tommy Gun/талісмана/міни, але для ліхтарика
        вона хибна — тому показуємо вбивцю тільки за наявності прямого запису.
        """
        tid = int(target_id)
        for visitor_id, visited_id, action in (getattr(state, "visit_log", []) or []):
            if int(visited_id) == tid and action in (
                "kill_don",
                "kill_mafia",
                "kill_maniac",
                "kill_comm",
                "kill_yakuza",
                "kill_sadistic",
                "kill_custom",
            ):
                return True
        return False

    def _record_achievement_event(self, state: GameState, event_type: str, player_id: int):
        """Записати подію для досягнення (нараховується в кінці гри)."""
        if state and player_id:
            state.game_achievement_events.append((event_type, player_id))
    
    async def _get_action_description_async(self, visitor_id: int, action: str, state: GameState) -> str:
        """Get description of action for a role"""
        result = await self._db_fetchone(
            "SELECT role, tg_name FROM users WHERE id = %s",
            (visitor_id,),
        )
        if not result:
            return "невідомий"
        
        role, name = result[0], result[1]
        
        # Визначаємо опис дії залежно від ролі та типу дії
        don_name = getattr(state, "name_of_all_capone", "Аль Капоне") or "Аль Капоне"
        if action == "kill_don" or (action == "kill_mafia" and visitor_id == state.all_capone_id):
            return emoji_to_premium(f"🎩 <b>{don_name}</b> зробив свій вибір")
        elif action == "kill_maniac":
            return emoji_to_premium("🔪 <b>Маніяк</b> зробив свій вибір")
        elif action == "heal" or action == "heal_sadistic":
            if role == "Лікар" or role == state.name_of_doctor:
                return "🚑 <b>Карета швидкої допомоги</b> помчала містом"
            elif role == "Доктор-садист":
                return "⚕️ <b>Доктор-садист</b> зробив свій вибір"
            else:
                return f"<b>{role}</b> зробив свій вибір"
        elif action == "check" or action == "check_comm":
            if role == "Комісар Каттані" or role == "Сержант":
                return "🕵️ <b>Комісар Каттані</b> виходить на перевірку"
            else:
                return f"<b>{role}</b> перевіряв"
        elif action == "kill_comm":
            return "🕵️ <b>Комісар Каттані</b> вийшов на усунення"
        elif action == "protect":
            return "🛡️ <b>Тілоохоронець</b> зробив свій вибір"
        elif action == "block" or action == "block_thug":
            if role == "Коханка":
                return "💋 <b>Коханка</b> вже зачекалася тебе"
            elif role == "Головоріз":
                return "💪 <b>Головоріз</b> зробив свій вибір"
            else:
                return f"<b>{role}</b> зробив свій вибір"
        elif action == "kill_sadistic":
            return "⚕️ <b>Доктор-садист</b> зробив свій вибір"
        elif action == "kill_mafia":
            return "🎩 <b>Сім'я Аль Капоне</b> зробила свій вибір"
        elif action == "homeless":
            return None  # Не показуємо для Бомжа
        elif action == "lawyer":
            return "⚖️ <b>Адвокат</b> пішов по слідах Комісара"
        elif action == "infect":
            return "🧟 <b>Заражений</b> зробив свій вибір"
        elif action == "deceiver":
            return "🎭 <b>Брехун</b> плутає сліди"
        elif action == "kill_custom":
            # Кастомна роль з нічною здібністю Kill
            return emoji_to_premium(f"🗡 <b>{role}</b> зробив свій вибір")
        else:
            return None  # Не показуємо загальні повідомлення

    async def _end_of_night_mafia_group_text_async(self, chat_id: int, state: GameState) -> str | None:
        """
        Текст у групу на світанку, якщо мафія походила - той самий формат, що раніше
        відправлявся одразу після вибору (Дон / підлегла мафія + тематичний показ цілі).
        """
        if not getattr(state, "mafia_action_taken", False):
            return None
        victim_id = int(getattr(state, "victim_id", 0) or 0)
        kill_action = None
        target_for_name = victim_id
        log = list(getattr(state, "visit_log", []) or [])
        for _visitor_id, target_id, action in reversed(log):
            if action not in ("kill_don", "kill_mafia"):
                continue
            tid = int(target_id)
            if victim_id and tid != victim_id:
                continue
            kill_action = action
            target_for_name = tid
            break
        if kill_action is None:
            for _visitor_id, target_id, action in reversed(log):
                if action in ("kill_don", "kill_mafia"):
                    kill_action = action
                    target_for_name = int(target_id)
                    break
        member_name = ""
        if target_for_name:
            try:
                row = await self._db_fetchone(
                    "SELECT tg_name FROM users WHERE id = %s",
                    (target_for_name,),
                )
                if row and row[0]:
                    member_name = str(row[0])
            except Exception:
                pass
        try:
            _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
        except Exception:
            show_night_targets = False
        if kill_action == "kill_mafia":
            if show_night_targets and member_name:
                return f"🎩 <b>Сім'я Аль Капоне</b> зробила свій вибір: <code>{member_name}</code>."
            return "🎩 <b>Сім'я Аль Капоне</b> зробила свій вибір"
        # Як раніше: у чаті завжди «Аль Капоне», не кастомна назва ролі
        if show_night_targets and member_name:
            return emoji_to_premium(f"🎩 <b>Аль Капоне</b> знайшов зрадника - <code>{member_name}</code>.")
        return emoji_to_premium("🎩 <b>Аль Капоне</b> знайшов зрадника")
    
    def _get_killer_fallback_text(self, victim_id: int, state: GameState) -> str:
        """Повертає текст «гостював X» за реальним вбивцею з visit_log (не завжди Аль Капоне)."""
        kill_actions = ("kill_don", "kill_mafia", "kill_maniac", "kill_comm", "kill_sadistic", "kill_yakuza", "kill_custom")
        for _visitor_id, target_id, action in state.visit_log:
            if target_id == victim_id and action in kill_actions:
                if action == "kill_maniac":
                    return "Подейкують, що напередодні в нього гостював <b>Маніяк</b>…"
                if action == "kill_comm":
                    return "Подейкують, що напередодні в нього гостював <b>Комісар Каттані</b>…"
                if action == "kill_sadistic":
                    return "Подейкують, що напередодні в нього гостював <b>Доктор-садист</b>…"
                if action in ("kill_don", "kill_mafia"):
                    return "Подейкують, що напередодні в нього гостював <b>Аль Капоне</b>…"
                if action == "kill_yakuza":
                    return "Подейкують, що напередодні в нього гостював <b>Якудза</b>…"
                return "Подейкують, що напередодні в нього гостював <b>хтось</b>…"
        return "Подейкують, що напередодні в нього гостював <b>Аль Капоне</b>…"
    
    def _get_action_description_for_observer(self, action: str) -> str:
        """Get action description for Волоцюга (without role names, just action type)"""
        action_descriptions = {
            "kill_don": "вбивство",
            "kill_mafia": "вбивство",
            "kill_maniac": "вбивство",
            "kill_sadistic": "вбивство",
            "kill_comm": "вбивство",
            "heal": "лікування",
            "heal_sadistic": "лікування",
            "protect": "захист",
            "block": "блокування",
            "block_thug": "блокування",
            "check": "перевірка",
            "check_comm": "перевірка",
            "lawyer": "захист",
            "infect": "зараження",
            "deceiver": "обман",
            "homeless": "спостереження"
        }
        return action_descriptions.get(action, "відвідування")

    async def _set_player_role_async(self, player_id: int, role_name: str):
        """Persist role change to DB."""
        await self._db_execute_commit(
            "UPDATE users SET role = %s WHERE id = %s",
            (role_name, player_id),
        )

    async def _refresh_state_role_ids_async(self, state):
        """Оновити state.*_id та списки ролей з БД після обміну ролей Клоуном (щоб нічні дії йшли правильним гравцям)."""
        # Логування для діагностики
        self.print_log(f"🔄 _refresh_state_role_ids_async: початок оновлення ролей для {len(state.membersList)} гравців")

        state.doctor_id = 0
        state.all_capone_id = 0
        state.mafia_ids.clear()
        state.civilian_ids.clear()
        state.commissioner_id = 0
        state.sheriff_id = 0
        state.suicide_id = 0
        state.homeless_id = 0
        state.prostitute_id = 0
        state.guardian_id = 0
        state.kamikaze_id = 0
        state.lucky_ids.clear()
        state.maniac_id = 0
        state.sadistic_doctor_id = 0
        state.nurse_id = 0
        state.journalist_id = 0
        state.lawyer_id = 0
        state.werewolf_id = 0
        state.clown_id = 0
        state.infected_ids.clear()
        state.deceiver_id = 0
        state.devil_id = 0
        state.mermaid_id = 0
        state.hunter_id = 0

        # Лічильник оновлених ролей для діагностики
        roles_updated = 0

        # ВАЖЛИВО: Перевіряємо, що membersList не порожній
        if not state.membersList:
            self.print_log("⚠️ _refresh_state_role_ids_async: membersList порожній!")
            return

        for pid in state.membersList:
            r = await self._db_fetchone(
                "SELECT role, killed FROM users WHERE id = %s",
                (pid,),
            )
            if not r:
                self.print_log(f"⚠️ _refresh_state_role_ids_async: гравець {pid} не знайдений в БД")
                continue
            if r[1] == 1:
                self.print_log(f"⚠️ _refresh_state_role_ids_async: гравець {pid} мертвий (killed=1), пропускаємо")
                continue

            role = r[0] or ""
            if not role:
                self.print_log(f"⚠️ _refresh_state_role_ids_async: гравець {pid} не має ролі")
                continue

            roles_updated += 1

            if role in [getattr(state, "name_of_all_capone", "Аль Капоне"), "Аль Капоне"]:
                state.all_capone_id = int(pid)
                self.print_log(f"✅ Оновлено: Аль Капоне = {pid}")
            elif role == "Мафія":
                state.mafia_ids.append(pid)
                self.print_log(f"✅ Оновлено: Мафія додано {pid}")
            elif role in [getattr(state, "name_of_civilian", "Мирний житель"), "Мирний житель"] or ("мирний" in role.lower() and "житель" in role.lower()):
                state.civilian_ids.append(pid)
                self.print_log(f"✅ Оновлено: Мирний житель додано {pid}")
            elif role in [getattr(state, "name_of_doctor", "Лікар"), "Лікар"]:
                state.doctor_id = pid
                self.print_log(f"✅ Оновлено: Лікар = {pid}")
            elif self._is_commissioner_role_name(role):
                state.commissioner_id = pid
                self.print_log(f"✅ Оновлено: Комісар = {pid}")
            elif role == "Самогубець":
                state.suicide_id = pid
                self.print_log(f"✅ Оновлено: Самогубець = {pid}")
            elif role == "Волоцюга":
                state.homeless_id = pid
                self.print_log(f"✅ Оновлено: Волоцюга = {pid}")
            elif role == "Коханка":
                state.prostitute_id = pid
                self.print_log(f"✅ Оновлено: Коханка = {pid}")
            elif role == "Тілоохоронець":
                state.guardian_id = pid
                self.print_log(f"✅ Оновлено: Тілоохоронець = {pid}")
            elif role == "Камікадзе":
                state.kamikaze_id = pid
                self.print_log(f"✅ Оновлено: Камікадзе = {pid}")
            elif role == "Сержант":
                state.sheriff_id = pid
                self.print_log(f"✅ Оновлено: Сержант = {pid}")
            elif role == "Щасливчик":
                state.lucky_ids.append(pid)
                self.print_log(f"✅ Оновлено: Щасливчик додано {pid}")
            elif role == "Маніяк":
                state.maniac_id = pid
                self.print_log(f"✅ Оновлено: Маніяк = {pid}")
            elif role == "Доктор-садист":
                state.sadistic_doctor_id = pid
                self.print_log(f"✅ Оновлено: Доктор-садист = {pid}")
            elif role == "Мед. сестра":
                state.nurse_id = pid
                self.print_log(f"✅ Оновлено: Мед. сестра = {pid}")
            elif role == "Журналіст":
                state.journalist_id = pid
                self.print_log(f"✅ Оновлено: Журналіст = {pid}")
            elif role == "Адвокат":
                state.lawyer_id = pid
                self.print_log(f"✅ Оновлено: Адвокат = {pid}")
            elif role == "Перевертень":
                state.werewolf_id = pid
                self.print_log(f"✅ Оновлено: Перевертень = {pid}")
            elif role == "Клоун":
                state.clown_id = pid
                self.print_log(f"✅ Оновлено: Клоун = {pid}")
            elif role == "Заражений":
                state.infected_ids.append(pid)
                self.print_log(f"✅ Оновлено: Заражений додано {pid}")
            elif role == "Брехун":
                state.deceiver_id = pid
                self.print_log(f"✅ Оновлено: Брехун = {pid}")
            elif role == "Диявол":
                state.devil_id = pid
                self.print_log(f"✅ Оновлено: Диявол = {pid}")
            elif role == "Русалка":
                state.mermaid_id = pid
                self.print_log(f"✅ Оновлено: Русалка = {pid}")
            elif role == "Мисливець на русалку":
                state.hunter_id = pid
                self.print_log(f"✅ Оновлено: Мисливець на русалку = {pid}")
            else:
                self.print_log(f"⚠️ Невідома роль для гравця {pid}: {role}")

        self.print_log(f"🔄 _refresh_state_role_ids_async: завершено, оновлено {roles_updated} ролей")

    def _don_role_name_for_db(self, state) -> str:
        """Назва ролі Дона в БД (кастомна з адмінки або «Аль Капоне»)."""
        n = (getattr(state, "name_of_all_capone", None) or "").strip()
        return n if n else "Аль Капоне"

    async def _elect_new_don_from_alive_mafia_async(
        self, state, bot: Bot, chat_id: int, *, dead_don_id: int, dm_old_don: bool = True
    ) -> None:
        """Після смерті/виключення Дона: випадковий живий «Мафія» стає Доном (як у _kill_player)."""
        don_label = self._don_role_name_for_db(state)
        has_mafia = bool(state.mafia_ids)
        if not has_mafia:
            mafia_count_row = await self._db_fetchone(
                "SELECT COUNT(*) FROM users WHERE role = %s AND killed = %s AND id IN %s",
                ("Мафія", 0, tuple(state.membersList) if state.membersList else (None,)),
            )
            has_mafia = (mafia_count_row[0] if mafia_count_row else 0) > 0
        if dm_old_don:
            try:
                if has_mafia:
                    await bot.send_message(
                        chat_id=dead_don_id,
                        text=emoji_to_premium(
                            "🎩Зрадники виявилися хитрішими, Великий Ел, твої нащадки зможуть помститися за тебе."
                        ),
                        parse_mode="html",
                    )
                else:
                    await bot.send_message(
                        chat_id=dead_don_id,
                        text=emoji_to_premium(
                            "🎩Зрадники виявилися хитрішими, Великий Ел, для тебе вже готовий окремий котел в пеклі."
                        ),
                        parse_mode="html",
                    )
            except Exception:
                pass
        state.all_capone_id = 0
        alive_mafia_ids = [mid for mid in (state.mafia_ids or []) if mid in state.membersList]
        if not alive_mafia_ids:
            try:
                mafia_rows = await self._db_fetchall(
                    "SELECT id FROM users WHERE role = %s AND killed = 0 AND id IN %s",
                    ("Мафія", tuple(state.membersList) if state.membersList else (None,)),
                )
                alive_mafia_ids = [int(r[0]) for r in (mafia_rows or []) if r and r[0]]
                state.mafia_ids = list(alive_mafia_ids)
            except Exception as e:
                self.print_log(f"⚠️ Не вдалося оновити список живих мафій з БД: {e}")
        if not alive_mafia_ids:
            return
        new_don = random.choice(alive_mafia_ids)
        state.all_capone_id = new_don
        await self._set_player_role_async(new_don, don_label)
        if new_don in state.mafia_ids:
            state.mafia_ids.remove(new_don)
        try:
            await bot.send_message(
                chat_id=new_don,
                text=emoji_to_premium(
                    f"🎩 {don_label} загинув. Ти зайняв його місце!"
                ),
                parse_mode="html",
            )
        except Exception as e:
            self.print_log(f"Помилка надсилання повідомлення новому Дону {new_don}: {e}")

    async def _promote_sergeant_to_commissioner_after_comm_death_async(
        self, state, bot: Bot, chat_id: int
    ) -> None:
        """Після смерті/виключення Комісара: Сержант стає Комісаром (БД + state)."""
        state.commissioner_id = 0
        sgt = int(state.sheriff_id or 0)
        if not sgt or sgt not in state.membersList:
            sgt = 0
        if not sgt:
            try:
                row = await self._db_fetchone(
                    "SELECT id FROM users WHERE killed = 0 AND TRIM(role) = %s AND id IN %s",
                    ("Сержант", tuple(state.membersList) if state.membersList else (None,)),
                )
                if row and row[0]:
                    sgt = int(row[0])
            except Exception:
                sgt = 0
        if not sgt:
            return
        state.commissioner_id = sgt
        await self._set_player_role_async(sgt, "Комісар Каттані")
        state.sheriff_id = 0
        try:
            await bot.send_message(
                chat_id=state.commissioner_id,
                text="💀 <b>Комісар Каттані</b> загинув при виконанні\n\n⚖️ Закон не зникає.",
                parse_mode="html",
            )
        except Exception:
            pass

    async def _promote_nurse_to_doctor_after_doctor_death_async(self, state) -> int:
        """Після смерті/вибуття Лікаря: Мед. сестра отримує лікарські здібності (без зміни ролі в БД)."""
        state.doctor_id = 0
        promote_nurse_id = 0
        if state.nurse_id and state.nurse_id in state.membersList:
            promote_nurse_id = int(state.nurse_id)
        elif state.membersList:
            nurse_row = await self._db_fetchone(
                "SELECT id FROM users WHERE killed = 0 AND TRIM(role) = %s AND id IN %s",
                ("Мед. сестра", tuple(state.membersList)),
            )
            if nurse_row:
                promote_nurse_id = int(nurse_row[0])
        if not promote_nurse_id:
            return 0
        state.doctor_id = promote_nurse_id
        # ВАЖЛИВО: роль у БД НЕ змінюємо на "Лікар" - лишається "Мед. сестра".
        # Це лише передача лікарських здібностей через doctor_id.
        state.doctor_was_nurse = True
        # Після отримання здібності у медсестри має бути власний 1 self-heal.
        # Не переносимо/не наслідуємо ліміт самолікування попереднього Лікаря.
        state.doctor_self_heal_used = False
        state.nurse_promoted_day_notify_id = promote_nurse_id
        return promote_nurse_id

    async def _resolve_commissioner_check(self, state, bot: Bot, chat_id: int, item_processor):
        """Обчислити результат перевірки Комісара на світанку (після всіх нічних виборів), щоб захист Адвоката та Брехуна враховувався коректно."""
        target_id = getattr(state, "commissioner_check_id", 0) or 0
        if not target_id or not getattr(state, "choose_who_commissioner_will_check", None):
            return
        # Пальоні парфуми Gucci: Комісар «чхає» і перевіряє випадкового іншого гравця замість обраної цілі
        if item_processor.should_redirect_commissioner_check(target_id):
            alive_others = []
            for pid in state.membersList:
                if pid == target_id:
                    continue
                row = await self._db_fetchone(
                    "SELECT killed FROM users WHERE id = %s",
                    (pid,),
                )
                if row and (row[0] or 0) == 0:
                    alive_others.append(pid)
            if alive_others:
                target_id = random.choice(alive_others)
                state.commissioner_check_id = target_id
                try:
                    await bot.edit_message_text(
                        chat_id=state.commissioner_id,
                        message_id=state.choose_who_commissioner_will_check.message_id,
                        text="✨ <b>Пальоні парфуми Gucci</b>: сильний аромат - перевірка перенаправлена на іншого гравця.",
                        parse_mode="html"
                    )
                except Exception:
                    pass
        # Димова шашка: ціль невидима - перевірка не спрацьовує
        smoke_invisible = getattr(state, "smoke_grenade_activated_this_night", set())
        self.print_log(f"🎩 DEBUG Commissioner: smoke_invisible = {smoke_invisible}, target_id = {target_id}")
        if target_id in smoke_invisible:
            state.commissioner_check_id = 0
            self.print_log(f"🎩 DEBUG Commissioner: Target {target_id} is invisible, check blocked")
            try:
                await bot.edit_message_text(
                    chat_id=state.commissioner_id,
                    message_id=state.choose_who_commissioner_will_check.message_id,
                    text="🕳 <b>Димова шашка</b>: обрана ціль невидима. Перевірка не спрацювала.",
                    parse_mode="html"
                )
            except Exception:
                pass
            return
        if target_id in getattr(state, "devil_covenant_night_shield", set()):
            state.commissioner_check_id = 0
            try:
                await bot.edit_message_text(
                    chat_id=state.commissioner_id,
                    message_id=state.choose_who_commissioner_will_check.message_id,
                    text=emoji_to_premium(
                        "💥 <b>Контракт з дияволом</b>: перевірка не спрацювала."
                    ),
                    parse_mode="html",
                )
            except Exception:
                pass
            return
        # Портал: «Запах фрі» / «Дух 2021» - візитер нічого не робить, перевірка не спрацьовує
        if target_id in getattr(state, "portal_smell_fry_targets", set()) or target_id in getattr(state, "portal_spirit_isolated", set()):
            try:
                await bot.edit_message_text(
                    chat_id=state.commissioner_id,
                    message_id=state.choose_who_commissioner_will_check.message_id,
                    text="🍟 Перевірка не спрацювала: на цілі «запах фрі» або ізоляція.",
                    parse_mode="html",
                )
            except Exception:
                pass
            state.commissioner_check_id = 0
            return
        result = await self._db_fetchone(
            "SELECT role, killed, tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        if not result:
            return
        role, killed, member_name = result
        if killed == 1:
            return
        # Предмети: блокування / випадковізація перевірок
        blocking_effects = item_processor.process_blocking_effects(target_id, state)
        id_card_used = getattr(state, "id_card_used_this_game", set())
        if blocking_effects.get("block_role_check") and target_id not in id_card_used:
            used = False
            # Спочатку пробуємо новий баф «Паспорт Лиса», потім старе «Посвідчення особи»
            if try_consume_buff(chat_id, target_id, "fox_passport"):
                used = True
                role = "Невідомо"
                state.id_card_used_this_game.add(target_id)
                try:
                    await bot.send_message(
                        chat_id=target_id,
                        text=emoji_to_premium(
                            "📜 <b>Паспорт Лиса</b> спрацював!\n\n"
                            "Фальшивий документ збив перевірку."
                        ),
                        parse_mode="html",
                    )
                except Exception:
                    pass
            elif try_consume_buff(chat_id, target_id, "id_card"):
                used = True
                role = "Невідомо"
                state.id_card_used_this_game.add(target_id)
                try:
                    await bot.send_message(
                        chat_id=target_id,
                        text="🪪 <b>Посвідчення особи</b> спрацювало!\n\nПеревірка дала результат «Невідомо».",
                        parse_mode="html",
                    )
                except Exception:
                    pass
            if not used:
                # Немає зарядів жодного з бафів - переходимо до звичайної логіки
                pass
        else:
            ultra_effects = item_processor.process_ultra_passive_effects(target_id, state)
            mask_used = getattr(state, "mask_used_this_night", set())
            # Маска хаосу - списуємо заряд при використанні
            if ultra_effects.get("randomize_checks"):
                items = item_processor.get_player_items(target_id, ActivationTime.NIGHT)
                chaos_mask_used = False
                for item in items:
                    if item.get("item_id") == "chaos_mask" and item.get("effect_data", {}).get("effect") == "randomize_all_checks_and_buffs":
                        if not try_consume_buff(chat_id, target_id, "chaos_mask"):
                            self.print_log(f"⚠️ Маска хаосу для {target_id}: немає зарядів")
                            break
                        else:
                            chaos_mask_used = True
                            self.print_log(f"🎭 Маска хаосу активована для {target_id} (списано заряд)")
                            break
                if chaos_mask_used:
                    all_roles = ["Мирний житель", "Аль Капоне", "Мафія", "Лікар", "Комісар Каттані",
                                 "Брехун", "Адвокат", "Камікадзе", "Маніяк"]
                    role = random.choice(all_roles)
            elif item_processor.should_randomize_single_check(target_id) and target_id not in mask_used:
                if not try_consume_buff(chat_id, target_id, "mask"):
                    pass  # немає зарядів
                else:
                    all_roles = ["Мирний житель", "Аль Капоне", "Мафія", "Лікар", "Комісар Каттані",
                                 "Брехун", "Адвокат", "Камікадзе", "Маніяк"]
                    role = random.choice(all_roles)
                    state.mask_used_this_night.add(target_id)
        # Захист Адвоката - показуємо «Мирний житель» (пріоритет перед Брехуном за логікою гри)
        # Досягнення Адвокат: пішов до Мафії/Аль Капоне коли до них також прийшов Комісар
        lawyer_mafia_roles = ["Аль Капоне", "Мафія"]
        if state.name_of_all_capone:
            lawyer_mafia_roles.append(state.name_of_all_capone)
        if target_id == state.lawyer_client_id and role in lawyer_mafia_roles and state.lawyer_id:
            self._record_achievement_event(state, "lawyer_visit_with_commissioner", state.lawyer_id)
        if target_id == state.lawyer_client_id:
            role = "Мирний житель"
            try:
                await bot.send_message(
                    chat_id=target_id,
                    text="⚖️ <b>Адвокат</b> втрутився в перевірку.\n\n➡️ Комісар бачить тебе як мирного жителя.",
                    parse_mode="html"
                )
            except Exception:
                pass
        # Брехун інвертує результат (якщо Адвокат не захистив)
        elif target_id == state.deceiver_target_id:
            mafia_roles = ["Аль Капоне", "Мафія", "Адвокат", "Брехун"]
            if state.name_of_all_capone:
                mafia_roles.append(state.name_of_all_capone)
            is_mafia = role in mafia_roles
            if is_mafia:
                role = "Мирний житель"
            else:
                role = state.name_of_all_capone if state.name_of_all_capone else "Аль Капоне"
        # Перевертень стає Сержантом при перевірці
        if role == "Перевертень":
            await self._set_player_role_async(target_id, "Сержант")
            try:
                await bot.send_message(chat_id=target_id, text="🐺 Тебе перевірили - ти стаєш Сержантом!", parse_mode="html")
            except Exception:
                pass
            role = "Сержант"
        # Текст результату для Комісара
        mafia_roles_check = ["Аль Капоне", "Мафія", "Адвокат", "Брехун"]
        if state.name_of_all_capone:
            mafia_roles_check.append(state.name_of_all_capone)
        is_mafia = role in mafia_roles_check
        role_emoji_map = {
            "Аль Капоне": "🎩",
            "Мафія": "🤵",
            "Мирний житель": "🧍",
            "Лікар": "💊",
            "Комісар Каттані": "🕵️",
            "Самогубець": "🤦‍♂️",
            "Волоцюга": "🧥",
            "Коханка": "💃",
            "Тілоохоронець": "🛡️",
            "Камікадзе": "💥",
            "Сержант": "👮‍♂️",
            "Щасливчик": "🍀",
            "Маніяк": "🔪",
            "Доктор-садист": "⚕️",
            "Мед. сестра": "👩‍⚕️",
            "Журналіст": "📰",
            "Адвокат": "👨‍💼",
            "Перевертень": "🐺",
            "Клоун": "🤡",
            "Заражений": "🧟",
            "Брехун": "🎭",
            "Диявол": "👹",
        }
        role_emoji = role_emoji_map.get(role, "🎭")
        checked_line = f"<b>{html.escape(member_name)} - {role_emoji} {html.escape(role)}</b>"
        # Досягнення: Комісар/Сержант знайшов мафію
        if is_mafia and state.commissioner_id:
            comm_role_row = await self._db_fetchone(
                "SELECT role FROM users WHERE id = %s",
                (state.commissioner_id,),
            )
            comm_role = comm_role_row[0] if comm_role_row else ""
            if comm_role == "Сержант":
                self._record_achievement_event(state, "sergeant_find_mafia", state.commissioner_id)
            else:
                self._record_achievement_event(state, "commissioner_find_don_night", state.commissioner_id)
        if is_mafia:
            result_text = (
                f"Комісар затримує погляд довше, ніж треба:\n"
                "«Ти помилився містом»\n"
                f"{checked_line}"
            )
        else:
            result_text = (
                "Комісар прибирає посвідчення:\n"
                "«Поки що - чисто»\n"
                f"{checked_line}"
            )
        try:
            await bot.edit_message_text(
                chat_id=state.commissioner_id,
                message_id=state.choose_who_commissioner_will_check.message_id,
                text=result_text,
                parse_mode="html"
            )
        except Exception:
            pass
        # Сержанту теж надсилаємо повний результат перевірки (хто перевірений і яка роль)
        if state.sheriff_id and state.sheriff_id != state.commissioner_id:
            try:
                await bot.send_message(
                    chat_id=state.sheriff_id,
                    text=f"🔍 <b>Результат перевірки Комісара</b>\n\n{result_text}",
                    parse_mode="html"
                )
            except Exception:
                pass
        # Дзеркальце: перевірений дізнається, хто його перевіряв (1 раз за гру)
        mirror_used = getattr(state, "mirror_used_this_game", set())
        if item_processor.should_reveal_checker(target_id) and target_id not in mirror_used:
            if not try_consume_buff(chat_id, target_id, "mirror"):
                pass  # немає зарядів
            else:
                state.mirror_used_this_game.add(target_id)
                checker_name = "Комісар Каттані"  # або ім'я з БД
                if state.commissioner_id:
                    cn = await self._db_fetchone(
                        "SELECT tg_name FROM users WHERE id = %s",
                        (state.commissioner_id,),
                    )
                    checker_name = cn[0] if cn else "Комісар Каттані"
                try:
                    await bot.send_message(
                        chat_id=target_id,
                        text=f"🪞 <b>Дзеркальце</b> спрацювало!\n\nТебе перевіряв(ла): <b>{checker_name}</b>.",
                        parse_mode="html"
                    )
                except Exception:
                    pass

    # ──────────────────────────── Купальська ніч: ролі ────────────────────────────
    def _kupala_member_name(self, state, pid: int) -> str:
        for m in getattr(state, "membersNames", []):
            try:
                if m[0] == pid:
                    return str(m[1])
            except Exception:
                continue
        return str(pid)

    def _kupala_target_kb(self, prefix: str, chat_id: int, actor_id: int, state, excludes=None):
        excludes = set(excludes or [])
        excludes.add(actor_id)
        b = InlineKeyboardBuilder()
        count = 0
        for pid in state.membersList:
            if pid in excludes:
                continue
            b.button(text=self._kupala_member_name(state, pid), callback_data=f"{prefix}:{chat_id}:{actor_id}:{pid}")
            count += 1
        b.adjust(1)
        return (b.as_markup() if count else None)

    async def mermaid_action(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        """Нічне меню Русалки: «Водний потік» або «Оберіг глибин»."""
        state = self._get_state(chat_id)
        if getattr(state, "mermaid_weakened", False):
            try:
                await bot.send_message(chat_id=player_id, text="🧜 <b>Виснаження</b>\n\nЦієї ночі ти знесилена після оберегу й не дієш.", parse_mode="html")
            except Exception:
                pass
            return
        b = InlineKeyboardBuilder()
        b.button(text="🌊 Водний потік", callback_data=f"kr_mab:{chat_id}:{player_id}:flow")
        b.button(text="🧜 Оберіг глибин", callback_data=f"kr_mab:{chat_id}:{player_id}:protect")
        b.adjust(1)
        try:
            await bot.send_message(
                chat_id=player_id,
                text="🧜 <b>Русалка</b>\n\nОбери дію цієї ночі:",
                reply_markup=b.as_markup(), parse_mode="html",
            )
        except Exception:
            pass
        # Атмосферна репліка в груповий чат (як в інших ролей).
        try:
            await bot.send_message(chat_id=chat_id, text="🧜🏻‍♀️ З глибин лунає чаруюча пісня.")
        except Exception:
            pass

    async def kupala_mermaid_ability_callback(self, callback: CallbackQuery, bot: Bot):
        _, chat_s, actor_s, kind = callback.data.split(":")
        chat_id, actor_id = int(chat_s), int(actor_s)
        state = self._get_state(chat_id)
        if kind == "flow":
            kb = self._kupala_target_kb("kr_flowa", chat_id, actor_id, state)
            txt = "🌊 <b>Водний потік</b>\n\nОбери <b>Гравця А</b> (звідки перетече атака):"
        else:
            # «не захищати себе двічі поспіль»: якщо минулого разу захистила себе — заборонити себе
            ex = [actor_id] if getattr(state, "mermaid_last_protect_id", 0) == actor_id else []
            # дозволяємо захищати себе, якщо минулого разу був не сам
            kb = self._kupala_target_kb("kr_protect", chat_id, actor_id, state, excludes=ex) if ex else self._kupala_self_or_target_kb("kr_protect", chat_id, actor_id, state)
            txt = "🧜 <b>Оберіг глибин</b>\n\nКого захистити цієї ночі? (після цього ти будеш виснажена 1 ніч)"
        if not kb:
            await callback.answer("Немає доступних цілей.", show_alert=True)
            return
        try:
            await callback.message.edit_text(txt, reply_markup=kb, parse_mode="html")
        except Exception:
            await callback.message.answer(txt, reply_markup=kb, parse_mode="html")
        await callback.answer()

    def _kupala_self_or_target_kb(self, prefix: str, chat_id: int, actor_id: int, state):
        """Як _kupala_target_kb, але дозволяє ще й себе (для оберегу)."""
        b = InlineKeyboardBuilder()
        count = 0
        for pid in state.membersList:
            label = ("🪞 Себе" if pid == actor_id else self._kupala_member_name(state, pid))
            b.button(text=label, callback_data=f"{prefix}:{chat_id}:{actor_id}:{pid}")
            count += 1
        b.adjust(1)
        return (b.as_markup() if count else None)

    async def kupala_flow_a_callback(self, callback: CallbackQuery, bot: Bot):
        _, chat_s, actor_s, a_s = callback.data.split(":")
        chat_id, actor_id, a_id = int(chat_s), int(actor_s), int(a_s)
        state = self._get_state(chat_id)
        kb = self._kupala_target_kb("kr_flowb", chat_id, actor_id, state, excludes=[a_id])
        # Підставляємо A у префікс через окремий формат: kr_flowb:chat:actor:A — додамо B при кліку.
        # Тут кнопки вже мають target=B, тож вшиваємо A у callback вручну.
        b = InlineKeyboardBuilder()
        for pid in state.membersList:
            if pid in (actor_id, a_id):
                continue
            b.button(text=self._kupala_member_name(state, pid), callback_data=f"kr_flowb:{chat_id}:{actor_id}:{a_id}:{pid}")
        b.adjust(1)
        txt = f"🌊 <b>Водний потік</b>\n\nГравець А: <b>{self._kupala_member_name(state, a_id)}</b>\nОбери <b>Гравця Б</b> (куди перетече атака):"
        try:
            await callback.message.edit_text(txt, reply_markup=b.as_markup(), parse_mode="html")
        except Exception:
            await callback.message.answer(txt, reply_markup=b.as_markup(), parse_mode="html")
        await callback.answer()

    async def kupala_flow_b_callback(self, callback: CallbackQuery, bot: Bot):
        _, chat_s, actor_s, a_s, b_s = callback.data.split(":")
        chat_id, a_id, b_id = int(chat_s), int(a_s), int(b_s)
        state = self._get_state(chat_id)
        state.mermaid_redirect_a = a_id
        state.mermaid_redirect_b = b_id
        try:
            await callback.message.edit_text(
                f"🌊 Готово. Атаку злих з <b>{self._kupala_member_name(state, a_id)}</b> буде перенаправлено на <b>{self._kupala_member_name(state, b_id)}</b>.",
                parse_mode="html",
            )
        except Exception:
            pass
        await callback.answer("Водний потік налаштовано.")

    async def kupala_protect_callback(self, callback: CallbackQuery, bot: Bot):
        _, chat_s, actor_s, t_s = callback.data.split(":")
        chat_id, actor_id, t_id = int(chat_s), int(actor_s), int(t_s)
        state = self._get_state(chat_id)
        if getattr(state, "mermaid_last_protect_id", 0) == actor_id and t_id == actor_id:
            await callback.answer("Не можна захищати себе двічі поспіль.", show_alert=True)
            return
        state.mermaid_protect_id = t_id
        state.mermaid_last_protect_id = t_id
        # Після оберегу — виснаження наступної ночі.
        state.mermaid_weakened_pending = True
        try:
            if t_id not in state.list_of_patient:
                state.list_of_patient.append(t_id)
        except Exception:
            pass
        try:
            await callback.message.edit_text(
                f"🧜 Ти захистила <b>{self._kupala_member_name(state, t_id)}</b> цієї ночі. Наступної ночі ти будеш виснажена.",
                parse_mode="html",
            )
        except Exception:
            pass
        await callback.answer("Оберіг глибин активовано.")

    async def hunter_action(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        """Нічне меню Мисливця: «Засідка» та «Гарпун» (1/гру)."""
        state = self._get_state(chat_id)
        b = InlineKeyboardBuilder()
        b.button(text="🩸 Засідка (блок дії)", callback_data=f"kr_hab:{chat_id}:{player_id}:silence")
        if not getattr(state, "hunter_harpoon_used", False):
            b.button(text="🎯 Гарпун (1 раз за гру)", callback_data=f"kr_hab:{chat_id}:{player_id}:harpoon")
        b.adjust(1)
        try:
            await bot.send_message(
                chat_id=player_id,
                text="🩸 <b>Мисливець на русалку</b>\n\nОбери дію цієї ночі:",
                reply_markup=b.as_markup(), parse_mode="html",
            )
        except Exception:
            pass
        # Атмосферна репліка в груповий чат (як в інших ролей).
        try:
            await bot.send_message(chat_id=chat_id, text="🩸 Арбалет вже заряджений.")
        except Exception:
            pass

    async def kupala_hunter_ability_callback(self, callback: CallbackQuery, bot: Bot):
        _, chat_s, actor_s, kind = callback.data.split(":")
        chat_id, actor_id = int(chat_s), int(actor_s)
        state = self._get_state(chat_id)
        if kind == "harpoon" and getattr(state, "hunter_harpoon_used", False):
            await callback.answer("Гарпун уже використано.", show_alert=True)
            return
        prefix = "kr_silence" if kind == "silence" else "kr_harpoon"
        kb = self._kupala_target_kb(prefix, chat_id, actor_id, state)
        if not kb:
            await callback.answer("Немає доступних цілей.", show_alert=True)
            return
        txt = ("🩸 <b>Засідка</b>\n\nЧию нічну дію скасувати?" if kind == "silence"
               else "🎯 <b>Гарпун</b>\n\nКого вразити (ігнорує щити)?")
        try:
            await callback.message.edit_text(txt, reply_markup=kb, parse_mode="html")
        except Exception:
            await callback.message.answer(txt, reply_markup=kb, parse_mode="html")
        await callback.answer()

    async def kupala_silence_callback(self, callback: CallbackQuery, bot: Bot):
        _, chat_s, actor_s, t_s = callback.data.split(":")
        chat_id, t_id = int(chat_s), int(t_s)
        state = self._get_state(chat_id)
        state.hunter_silence_id = t_id
        try:
            blk = set(getattr(state, "custom_block_ids", set()) or set())
            blk.add(t_id)
            state.custom_block_ids = blk
        except Exception:
            pass
        try:
            await callback.message.edit_text(
                f"🩸 Засідка: <b>{self._kupala_member_name(state, t_id)}</b> цієї ночі не зможе діяти.",
                parse_mode="html",
            )
        except Exception:
            pass
        await callback.answer("Засідку влаштовано.")

    async def kupala_harpoon_callback(self, callback: CallbackQuery, bot: Bot):
        _, chat_s, actor_s, t_s = callback.data.split(":")
        chat_id, t_id = int(chat_s), int(t_s)
        state = self._get_state(chat_id)
        if getattr(state, "hunter_harpoon_used", False):
            await callback.answer("Гарпун уже використано.", show_alert=True)
            return
        state.hunter_harpoon_id = t_id
        state.hunter_harpoon_used = True
        try:
            await callback.message.edit_text(
                f"🎯 Гарпун націлено на <b>{self._kupala_member_name(state, t_id)}</b>. Щити не врятують.",
                parse_mode="html",
            )
        except Exception:
            pass
        await callback.answer("Гарпун кинуто.")

    async def _custom_role_night_action(self, message: Message, bot: Bot, chat_id: int, player_id: int, role_name: str, role_obj, state):
        """Нічна дія для кастомних ролей (наприклад Танос) - показує вибір за типом здібності."""
        from game.role_system import AbilityType, TargetType
        phase_ok = lambda a: (
            getattr(a, 'phase', None) == AbilityPhase.NIGHT
            or (hasattr(a, 'phase') and getattr(a.phase, 'value', '') in ('night', 'both'))
        )
        night_abilities = [a for a in role_obj.abilities if phase_ok(a)]
        if not night_abilities:
            return
        def target_ok(a):
            tt = getattr(a, 'target_type', None)
            if tt is None:
                return False
            v = getattr(tt, 'value', str(tt)) if hasattr(tt, 'value') else str(tt)
            return v in ('one_player', 'any_alive')
        usable_abilities = [a for a in night_abilities if target_ok(a)]
        if not usable_abilities:
            # Якщо немає дій з вибором гравця - повідомляємо гравця про наявні здібності
            try:
                names = [getattr(a, 'name', getattr(getattr(a, 'ability_type', None), 'value', '?')) for a in night_abilities]
                await bot.send_message(
                    chat_id=player_id,
                    text=f"🎭 <b>{role_name}</b>\n\n💡 Твої здібності цієї ночі: {', '.join(names)}.\n(Поки що немає дій, які потребують вибору цілі.)",
                    parse_mode="html"
                )
            except Exception:
                pass
            return
        # Якщо лише одна здібність з ціллю - одразу показуємо вибір гравця (як раніше)
        if len(usable_abilities) == 1:
            ability = usable_abilities[0]
            atype = getattr(ability, 'ability_type', None)
            atype_val = atype.value if atype and hasattr(atype, 'value') else str(atype) if atype else "check_role"
            await self._send_custom_ability_target_menu(bot, chat_id, player_id, role_name, atype_val, state)
            return
        # Якщо декілька здібностей - спочатку даємо обрати, яку саме використовувати
        ability_kb = InlineKeyboardBuilder()
        for ability in usable_abilities:
            atype = getattr(ability, 'ability_type', None)
            atype_val = atype.value if atype and hasattr(atype, 'value') else str(atype) if atype else "check_role"
            ability_name = getattr(ability, 'name', atype_val)
            ability_kb.button(
                text=ability_name,
                callback_data=f"custom_ability_choose_{chat_id}_{player_id}_{atype_val}"
            )
        ability_kb.adjust(1)
        try:
            await bot.send_message(
                chat_id=player_id,
                text=f"🎭 <b>{role_name}</b>\n\nОбери, яку здібність хочеш використати цієї ночі:",
                reply_markup=ability_kb.as_markup(),
                parse_mode="html"
            )
        except Exception:
            return

    async def _send_custom_ability_target_menu(self, bot: Bot, chat_id: int, player_id: int, role_name: str, ability_type_val: str, state):
        builder = InlineKeyboardBuilder()
        for pid in state.membersList:
            if pid != player_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if result and result[1] == 0:
                    builder.button(
                        text=result[0],
                        callback_data=f"custom_ability_{chat_id}_{player_id}_{pid}_{ability_type_val}"
                    )
        builder.adjust(1)
        try:
            await bot.send_message(
                chat_id=player_id,
                text=f"🎭 <b>{role_name}</b>\n\n🔹 Обери ціль для здібності:\n",
                reply_markup=builder.as_markup(),
                parse_mode="html"
            )
        except Exception:
            return

    async def custom_ability_choose_callback(self, callback: CallbackQuery, bot: Bot):
        m = re.match(r"^custom_ability_choose_(-?\d+)_(\d+)_(.+)$", callback.data or "")
        if not m:
            await callback.answer("Помилка даних.", show_alert=True)
            return
        chat_id = int(m.group(1))
        player_id = int(m.group(2))
        ability_type_val = m.group(3)
        if callback.from_user.id != player_id:
            await callback.answer("Ця дія тільки для тебе.", show_alert=True)
            return
        state = self._get_state(chat_id)
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась.", show_alert=True)
            return
        row = await self._db_fetchone(
            "SELECT role FROM users WHERE id = %s",
            (player_id,),
        )
        if not row:
            await callback.answer("Помилка: гравець не знайдений.", show_alert=True)
            return
        role_name = row[0]
        try:
            await self._send_custom_ability_target_menu(bot, chat_id, player_id, role_name, ability_type_val, state)
            try:
                if callback.message:
                    await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            await callback.answer("Здібність обрано, тепер обери ціль.")
        except Exception:
            await callback.answer("Помилка при виборі здібності.", show_alert=True)

    async def custom_ability_target_callback(self, callback: CallbackQuery, bot: Bot):
        m = re.match(r"^custom_ability_(-?\d+)_(\d+)_(\d+)_(.+)$", callback.data or "")
        if not m:
            await callback.answer("Помилка даних.", show_alert=True)
            return
        chat_id = int(m.group(1))
        player_id = int(m.group(2))
        target_id = int(m.group(3))
        ability_type_val = m.group(4)
        if callback.from_user.id != player_id:
            await callback.answer("Ця дія тільки для тебе.", show_alert=True)
            return
        state = self._get_state(chat_id)
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась.", show_alert=True)
            return
        prow = await self._db_fetchone(
            "SELECT role FROM users WHERE id = %s",
            (player_id,),
        )
        if not prow:
            await callback.answer("Помилка: гравець не знайдений.", show_alert=True)
            return
        role_name = prow[0]
        result = await self._db_fetchone(
            "SELECT role, tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        if not result:
            await callback.answer("Гравець не знайдений.", show_alert=True)
            return
        target_role, target_name = result
        if ability_type_val == "check_role":
            try:
                await bot.send_message(
                    chat_id=player_id,
                    text=f"🔍 <b>Результат перевірки</b>\n\n{target_name} - <b>{target_role}</b>",
                    parse_mode="html",
                )
            except Exception:
                pass
        elif ability_type_val == "kill":
            try:
                custom_kill_ids = getattr(state, "custom_kill_ids", []) or []
                if target_id not in custom_kill_ids:
                    custom_kill_ids.append(target_id)
                state.custom_kill_ids = custom_kill_ids
                self._record_visit(state, player_id, target_id, "kill_custom")
            except Exception:
                pass
        elif ability_type_val == "block_action":
            custom_block_ids = set(getattr(state, "custom_block_ids", set()) or set())
            custom_block_ids.add(int(target_id))
            state.custom_block_ids = custom_block_ids
            self._record_visit(state, player_id, target_id, "block_custom")
        elif ability_type_val in ("heal", "protect"):
            custom_protect_ids = set(getattr(state, "custom_protect_ids", set()) or set())
            custom_protect_ids.add(int(target_id))
            state.custom_protect_ids = custom_protect_ids
            self._record_visit(state, player_id, target_id, f"{ability_type_val}_custom")
        try:
            role_obj = ChatRoleRegistry.get_role_for_chat(
                state.chat_owner_id if hasattr(state, "chat_owner_id") else player_id, chat_id, role_name
            )
        except Exception:
            role_obj = None
        target_msg = ""
        if role_obj and getattr(role_obj, "custom_data", None):
            target_msg = role_obj.custom_data.get("night_target_message", "")
        if target_msg:
            try:
                await bot.send_message(chat_id=target_id, text=target_msg, parse_mode="html")
            except Exception:
                pass
        try:
            _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
            if show_night_targets:
                announce = f"🎭 <b>{role_name}</b> зробив свій вибір: <code>{target_name}</code>."
            else:
                announce = f"🎭 <b>{role_name}</b> зробив свій вибір"
            await bot.send_message(
                chat_id=chat_id,
                text=announce,
                parse_mode="html",
            )
        except Exception:
            pass
        try:
            if callback.message:
                await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.answer("Вибір зроблено! ")

    async def day_function(self, message: Message, bot: Bot):
        """Process night actions and transition to day phase"""
        chat_id = message.chat.id
        
        # Check if group is blocked
        if await self._is_group_blocked_async(chat_id):
            state = self._get_state(chat_id)
            await self._unmute_users_muted_during_game(bot, chat_id)
            state.game_active = False
            return
        
        state = self._get_state(chat_id)
        # Якщо вночі Мед. сестру підвищили до Лікаря, повідомляємо про це в ПП на старті дня.
        promoted_doctor_id = int(getattr(state, "nurse_promoted_day_notify_id", 0) or 0)
        if promoted_doctor_id and promoted_doctor_id not in state.membersList:
            # Підвищена медсестра вже не в грі (загинула цієї ж ночі) - повідомлення не надсилаємо.
            state.nurse_promoted_day_notify_id = 0
            promoted_doctor_id = 0
        if promoted_doctor_id:
            try:
                await bot.send_message(
                    chat_id=promoted_doctor_id,
                    text=(
                        "💉 Лікар загинув на чергуванні.\n"
                        "Карета швидкої не чекає - хтось повинен зайняти його місце.\n\n"
                    ),
                    parse_mode="html",
                )
            except Exception as e:
                self.print_log(f"⚠️ Не вдалося надіслати денне повідомлення новому Лікарю {promoted_doctor_id}: {e}")
            finally:
                state.nurse_promoted_day_notify_id = 0
        prostitute_day_notify_target_id = int(getattr(state, "prostitute_day_notify_target_id", 0) or 0)
        if prostitute_day_notify_target_id:
            try:
                await bot.send_message(
                    chat_id=prostitute_day_notify_target_id,
                    text="💋 <b>Коханка сьогодні вирішила навідатися сама</b>\n\n",
                    parse_mode="html",
                )
            except Exception as e:
                self.print_log(
                    f"⚠️ Не вдалося надіслати денне повідомлення цілі Коханки {prostitute_day_notify_target_id}: {e}"
                )
            finally:
                state.prostitute_day_notify_target_id = 0
        # Встановлюємо флаг, що день активний (для видалення повідомлень заблокованих гравців)
        state.day_active = True
        # Новий день - скидаємо облік денного голосування (попередній набір уже враховано в AFK наприкінці ночі)
        state.day_voting_participants.clear()
        # Рядок про мафію надсилаємо окремим повідомленням перед денним блоком.
        mafia_day_preface = await self._end_of_night_mafia_group_text_async(chat_id, state)

        # Якщо є "заблоковані" (silenced_ids) - під час дня реально мутимо їх у чаті,
        # щоб повідомлення не мигали (і щоб заблокований гравець не міг писати взагалі).
        # Розмут робиться на старті ночі через _unmute_users_muted_during_game.
        try:
            if not hasattr(state, "muted_during_game") or state.muted_during_game is None:
                state.muted_during_game = set()
            until_date = int((datetime.utcnow() + timedelta(hours=6)).timestamp())
            for sid in list(getattr(state, "silenced_ids", set()) or []):
                try:
                    await bot.restrict_chat_member(
                        chat_id,
                        sid,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=until_date,
                    )
                    state.muted_during_game.add(sid)
                except Exception:
                    pass
        except Exception:
            pass

        # Критичне: мертві гравці можуть блокуватись у чаті, але тільки якщо
        # увімкнена мовчанка для мертвих (silence_dead_players_enabled).
        try:
            if not hasattr(state, "silenced_ids") or state.silenced_ids is None:
                state.silenced_ids = set()
            dead_ids: set[int] = set()
            for pid in getattr(state, "membersList", []) or []:
                try:
                    row = await self._db_fetchone(
                        "SELECT COALESCE(killed, 0) FROM users WHERE id = %s",
                        (pid,),
                    )
                    if row and int(row[0]) == 1:
                        dead_ids.add(int(pid))
                except Exception:
                    continue

            silence_dead_players_enabled, _ = await self._get_silence_settings_async(chat_id, state)
            if dead_ids and silence_dead_players_enabled:
                for did in dead_ids:
                    state.silenced_ids.add(did)
                # Мутимо на "довго", щоб ігнорувати повідомлення навіть якщо бот не встигне видалити
                long_until = int((datetime.utcnow() + timedelta(days=365)).timestamp())
                for did in dead_ids:
                    try:
                        await bot.restrict_chat_member(
                            chat_id,
                            did,
                            permissions=ChatPermissions(can_send_messages=False),
                            until_date=long_until,
                        )
                    except Exception:
                        pass
            elif dead_ids and not silence_dead_players_enabled:
                # Якщо мовчанка вимкнена - прибираємо мертвих з "silenced_ids" і знімаємо старий мут.
                full_permissions = ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                )
                for did in dead_ids:
                    state.silenced_ids.discard(did)
                    try:
                        await bot.restrict_chat_member(chat_id, did, permissions=full_permissions)
                    except Exception:
                        pass
        except Exception:
            pass

        # Скидаємо стан денного обговорення/пропуску, щоб він не «переїжджав» у наступний день
        try:
            state.discussion_skipped = False
            if getattr(state, "skip_discussion_votes", None) is None:
                state.skip_discussion_votes = set()
            else:
                state.skip_discussion_votes.clear()
            # Також скидаємо «вже відправили старт голосування» на початок дня,
            # щоб не було ситуації коли голосування/переходи дублюються між днями.
            state.voting_start_message_sent = False
            state.voting_start_time = None
            state.voting_prep_message = None
        except Exception:
            pass

        # Ініціалізуємо обробник ефектів предметів
        item_processor = ItemEffectProcessor(chat_id)

        # Капелюх КаПоне - активується вдень, діє наступної ночі
        self.print_log(f"🎩 DEBUG day_function: Starting capone_hat button check")
        try:
            for pid in state.membersList:
                self.print_log(f"🎩 DEBUG day_function: Checking player {pid}")
                r = await self._db_fetchone(
                    "SELECT killed FROM users WHERE id = %s",
                    (pid,),
                )
                if not r or r[0] != 0:
                    self.print_log(f"🎩 DEBUG day_function: Player {pid} is dead or not found, skipping")
                    continue  # тільки живі гравці
                self.print_log(f"🎩 DEBUG day_function: Player {pid} is alive, getting day items")
                day_items = item_processor.get_player_items(int(pid), ActivationTime.DAY)
                self.print_log(f"🎩 DEBUG day_function: Player {pid} day_items = {day_items}")
                for di in day_items:
                    self.print_log(f"🎩 DEBUG day_function: Checking item {di.get('item_id')}, is_active={di.get('is_active')}")
                    if di.get("item_id") == "capone_hat" and di.get("is_active"):
                        self.print_log(f"🎩 DEBUG day_function: Found active capone_hat for player {pid}")
                        # Перевіряємо, чи Капелюх вже заплановано на наступну ніч
                        hat_scheduled = getattr(state, "capone_hat_scheduled_for_night", set())
                        self.print_log(f"🎩 DEBUG day_function: hat_scheduled = {hat_scheduled}")
                        if pid in hat_scheduled:
                            self.print_log(f"🎩 DEBUG day_function: Player {pid} already scheduled, breaking")
                            break  # Вже заплановано, не показуємо кнопку
                        # Перевіряємо, чи Капелюх вже використано цю гру
                        smoke_used = getattr(state, "smoke_grenade_used_this_game", set())
                        self.print_log(f"🎩 DEBUG day_function: smoke_used = {smoke_used}")
                        if pid in smoke_used:
                            self.print_log(f"🎩 DEBUG day_function: Player {pid} already used this game, breaking")
                            break  # Вже використано цю гру
                        self.print_log(f"🎩 DEBUG day_function: Sending capone_hat button to player {pid}")
                        capone_kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(
                                text="🎩 Активувати капелюх на наступну ніч",
                                callback_data=f"item_use:capone_hat:{chat_id}"
                            )]
                        ])
                        await bot.send_message(
                            chat_id=pid,
                            text=emoji_to_premium(
                                "🎩 <b>Капелюх КаПоне</b>\n\n"
                                "Активуй його зараз, вдень. Наступної ночі ти станеш невидимим для всіх нічних дій."
                            ),
                            reply_markup=capone_kb,
                            parse_mode="html"
                        )
                        self.print_log(f"🎩 DEBUG day_function: Button sent successfully to player {pid}")
                        break
                for di in day_items:
                    if di.get("item_id") == "devil_covenant" and di.get("is_active"):
                        try:
                            dc_kb = _devil_covenant_activate_kb(chat_id)
                            await bot.send_message(
                                chat_id=pid,
                                text=emoji_to_premium(
                                    "💥 <b>Контракт з дияволом</b>\n\n"
                                    "Один раз за гру: після активації до кінця цього дня та до кінця цієї ночі "
                                    "жодна ворожа дія проти тебе не спрацює."
                                ),
                                reply_markup=dc_kb,
                                parse_mode="html",
                            )
                        except Exception:
                            pass
                        break
        except Exception as e:
            self.print_log(f"🎩 DEBUG day_function: Exception in capone_hat block: {e}")
            import traceback
            self.print_log(f"🎩 DEBUG day_function: Traceback: {traceback.format_exc()}")

        # Повідомлення про виключених за неактивність (3 ночі поспіль без вибору в боті)
        kicked = getattr(state, "kicked_for_inactivity", None) or []
        if kicked:
            lines = []
            for entry in kicked:
                uid = entry[0]
                name = entry[1] if len(entry) > 1 else "Гравець"
                role_name = entry[2] if len(entry) > 2 and entry[2] else "невідома"
                link = vip_mod.html_user_link(uid, name)
                lines.append(
                    f"Твоя, <b>{html.escape(str(role_name))}</b> {link}, тиша коштувала тобі місця за столом.\n"
                    f"Ти вибув через відсутність дій.\n"
                )
            kick_msg = "\n\n".join(lines)
            try:
                await message.answer(kick_msg, parse_mode="html")
            except Exception as e:
                self.print_log(f"⚠️ Не вдалося надіслати повідомлення про виключення: {e}")
            state.kicked_for_inactivity.clear()

        # #region agent log
        _log_debug('debug-session', 'run1', 'N3', 'play.py:day_function:entry', 'day_function called', {
            'chat_id': chat_id,
            'night_number': state.night_number,
            'game_active': state.game_active,
            'victim_id': state.victim_id,
            'patient_id': state.patient_id
        })
        # #endregion
        
        self.print_log(f"🌅 day_function ВИКЛИКАНО!")
        self.print_log(f"📊 Стан: victim_id={state.victim_id}, patient_id={state.patient_id}")
        
        # Обробка нічних дій: перевірка чи були вбивство та/або лікування
        state.is_killed = 0
        
        # Ініціалізуємо обробник ефектів предметів
        item_processor = ItemEffectProcessor(chat_id)

        # ── Сезонний баф «Щаслива ніч» (Купальська ніч) ──
        # Якщо Аль Капоне володіє бафом, його вибір жертви ігнорується: ціль стає
        # випадковою серед живих (може випадково вбити союзника). Інертно, якщо бафа немає.
        try:
            _kupala = getattr(state, "kupala_buffs", None) or {}
            _don_id = getattr(state, "all_capone_id", 0)
            if _don_id and _kupala.get(_don_id) == "lucky_night" and state.victim_id:
                _alive_pool = [p for p in state.membersList if p != _don_id]
                if _alive_pool:
                    state.victim_id = random.choice(_alive_pool)
                    self.print_log(f"💮 Щаслива ніч: ціль Аль Капоне змінено на випадкову ({state.victim_id})")
        except Exception as _e:
            self.print_log(f"Щаслива ніч: помилка обробки: {_e}")

        # Вогнегасник - спочатку скасовуємо одну нічну дію на гравця (хто натиснув кнопку цієї ночі).
        # Має бути ДО редіректу: інакше редірект змінює victim_id, і перевірка "victim_id == pid" не спрацьовує.
        for pid in getattr(state, "fire_extinguisher_used_this_night", set()):
            cancelled = False
            # Скасовуємо лише одну дію на гравця (пріоритет: вбивство, потім блок)
            if state.victim_id == pid:
                state.victim_id = 0
                cancelled = True
                self.print_log(f"🧯 Вогнегасник скасував вбивство гравця {pid}")
            elif state.maniac_victim_id == pid:
                state.maniac_victim_id = 0
                cancelled = True
                self.print_log(f"🧯 Вогнегасник скасував дію маніяка на гравця {pid}")
            elif state.commissioner_kill_id == pid:
                state.commissioner_kill_id = 0
                cancelled = True
                self.print_log(f"🧯 Вогнегасник скасував вбивство комісара гравця {pid}")
            elif getattr(state, "sadistic_kill_id", 0) == pid:
                state.sadistic_kill_id = 0
                cancelled = True
                self.print_log(f"🧯 Вогнегасник скасував вбивство доктора-садиста гравця {pid}")
            elif pid in getattr(state, "custom_kill_ids", []):
                state.custom_kill_ids = [t for t in getattr(state, "custom_kill_ids", []) if t != pid]
                cancelled = True
                self.print_log(f"🧯 Вогнегасник скасував вбивство кастомної ролі гравця {pid}")
            elif pid in (set(getattr(state, "custom_block_ids", set()) or set())):
                custom_block_ids_now = set(getattr(state, "custom_block_ids", set()) or set())
                custom_block_ids_now.discard(pid)
                state.custom_block_ids = custom_block_ids_now
                cancelled = True
                self.print_log(f"🧯 Вогнегасник скасував блок кастомної ролі гравця {pid}")
            elif state.block_action_target_id == pid:
                state.block_action_target_id = 0
                cancelled = True
                self.print_log(f"🧯 Вогнегасник скасував блок (повія) гравця {pid}")
            if cancelled:
                try:
                    await bot.send_message(
                        chat_id=pid,
                        text="🧯 <b>Вогнегасник</b> спрацював!\n\nОдну нічну дію на тебе скасовано.",
                        parse_mode="html"
                    )
                except Exception:
                    pass

        # ── Сезонний баф «Магія Купала» (Купальська ніч) ──
        # 50% шанс розвіяти одну вхідну нічну дію (вбивство/блок) на власника бафа.
        try:
            _kupala_magic = getattr(state, "kupala_buffs", None) or {}
            for _pid, _bid in list(_kupala_magic.items()):
                if _bid != "kupala_magic" or _pid not in state.membersList:
                    continue
                if random.randint(1, 100) > 50:
                    continue  # 50% — не спрацювало
                _cancelled = False
                if state.victim_id == _pid:
                    state.victim_id = 0; _cancelled = True
                elif getattr(state, "maniac_victim_id", 0) == _pid:
                    state.maniac_victim_id = 0; _cancelled = True
                elif getattr(state, "commissioner_kill_id", 0) == _pid:
                    state.commissioner_kill_id = 0; _cancelled = True
                elif getattr(state, "sadistic_kill_id", 0) == _pid:
                    state.sadistic_kill_id = 0; _cancelled = True
                elif _pid in getattr(state, "custom_kill_ids", []):
                    state.custom_kill_ids = [t for t in getattr(state, "custom_kill_ids", []) if t != _pid]
                    _cancelled = True
                elif getattr(state, "block_action_target_id", 0) == _pid:
                    state.block_action_target_id = 0; _cancelled = True
                if _cancelled:
                    self.print_log(f"🔮 Магія Купала: розвіяно нічну дію проти {_pid}")
                    try:
                        await bot.send_message(
                            chat_id=_pid,
                            text="🔮 <b>Магія Купала</b> захистила тебе!\n\nОдну нічну дію проти тебе цієї ночі розвіяно.",
                            parse_mode="html",
                        )
                    except Exception:
                        pass
        except Exception as _e:
            self.print_log(f"Магія Купала: помилка обробки: {_e}")

        # ── Русалка «Водний потік» (Купальська ніч) ──
        # Якщо зла атака (вбивство Дона/мафії) спрямована на ціль А — перетікає на ціль Б.
        # Пріоритет: після блокувань (вогнегасник вище), перед застосуванням атаки.
        try:
            _ma = getattr(state, "mermaid_redirect_a", 0)
            _mb = getattr(state, "mermaid_redirect_b", 0)
            if _ma and _mb and getattr(state, "mermaid_id", 0):
                if state.victim_id == _ma:
                    state.victim_id = _mb
                    # Вода замела слід: для перенаправленої жертви ліхтарик не видає вбивцю
                    # (інакше він світив би Дона тому, кого Дон узагалі не обирав).
                    state.water_flow_redirected_to = int(_mb)
                    self.print_log(f"🧜 Водний потік: атаку Дона перенаправлено з {_ma} на {_mb}")
        except Exception as _e:
            self.print_log(f"Водний потік: помилка обробки: {_e}")

        # ── Мисливець «Гарпун» (Купальська ніч) ──
        # Атака, що ігнорує щити: ціль гине навіть під захистом/лікуванням і її
        # не можна перенаправити. Реалізуємо як окреме вбивство поверх захисту.
        try:
            _hh = getattr(state, "hunter_harpoon_id", 0)
            if _hh and getattr(state, "hunter_id", 0) and _hh in state.membersList:
                # Знімаємо будь-який захист/лікування саме з цієї цілі, щоб «пробити щит».
                if getattr(state, "patient_id", 0) == _hh:
                    state.patient_id = 0
                if getattr(state, "mermaid_protect_id", 0) == _hh:
                    state.mermaid_protect_id = 0
                if _hh in getattr(state, "list_of_patient", []):
                    try:
                        state.list_of_patient.remove(_hh)
                    except Exception:
                        pass
                # Незалежне вбивство (не чіпає ціль Дона): додаємо в окремий список убивств,
                # попередньо знявши захист (щит пробито).
                _ck = list(getattr(state, "custom_kill_ids", []) or [])
                if _hh not in _ck:
                    _ck.append(_hh)
                state.custom_kill_ids = _ck
                self.print_log(f"🩸 Гарпун: ціль {_hh} вражено в обхід щитів (custom_kill)")
        except Exception as _e:
            self.print_log(f"Гарпун: помилка обробки: {_e}")

        # ── Русалка «Оберіг глибин» (Купальська ніч): невразливість цілі на ніч ──
        # Скасовуємо будь-яке вбивство саме на захищеного гравця (гарпун уже зняв захист вище).
        try:
            _mp = getattr(state, "mermaid_protect_id", 0)
            if _mp and getattr(state, "mermaid_id", 0) and _mp in state.membersList:
                _saved = False
                if state.victim_id == _mp:
                    state.victim_id = 0; _saved = True
                if getattr(state, "maniac_victim_id", 0) == _mp:
                    state.maniac_victim_id = 0; _saved = True
                if getattr(state, "sadistic_kill_id", 0) == _mp:
                    state.sadistic_kill_id = 0; _saved = True
                if _mp in getattr(state, "custom_kill_ids", []):
                    state.custom_kill_ids = [t for t in getattr(state, "custom_kill_ids", []) if t != _mp]
                    _saved = True
                if _saved:
                    self.print_log(f"🧜 Оберіг глибин: захищено {_mp} від вбивства")
                    try:
                        await bot.send_message(
                            chat_id=_mp,
                            text="🧜 <b>Оберіг глибин</b> Русалки захистив тебе цієї ночі!",
                            parse_mode="html",
                        )
                    except Exception:
                        pass
        except Exception as _e:
            self.print_log(f"Оберіг глибин: помилка обробки: {_e}")

        # Обробка предметів: перенаправлення дій (після вогнегасника)
        redirected_actions = {}  # {original_target: new_target}
        for player_id in state.membersList:
            new_target = item_processor.should_redirect_action(player_id, state)
            if new_target:
                # Перевіряємо який предмет використовується і списуємо заряд
                items = item_processor.get_player_items(player_id, ActivationTime.NIGHT)
                redirected = False
                for item in items:
                    item_id = item.get("item_id")
                    effect = item.get("effect_data", {}).get("effect")
                    if effect in ("redirect_action", "redirect_all_actions_to_random"):
                        # Магніт або Чорна діра
                        if item_id == "magnet":
                            if try_consume_buff(chat_id, player_id, "magnet"):
                                redirected_actions[player_id] = new_target
                                self.print_log(f"🔄 Магніт перенаправив дію з {player_id} на {new_target} (списано заряд)")
                                redirected = True
                                break
                        elif item_id == "black_hole":
                            # Чорна діра вже списується при невидимості, але якщо спрацьовує тільки перенаправлення
                            if try_consume_buff(chat_id, player_id, "black_hole"):
                                redirected_actions[player_id] = new_target
                                self.print_log(f"🔄 Чорна діра перенаправила дію з {player_id} на {new_target} (списано заряд)")
                                redirected = True
                                break
                if not redirected:
                    self.print_log(f"⚠️ Перенаправлення для {player_id}: немає зарядів або предмет не знайдено")
        
        if redirected_actions:
            if state.victim_id in redirected_actions:
                old_victim = state.victim_id
                state.victim_id = redirected_actions[old_victim]
                self.print_log(f"🔄 Перенаправлено вбивство з {old_victim} на {state.victim_id}")
            if state.patient_id in redirected_actions:
                old_patient = state.patient_id
                state.patient_id = redirected_actions[old_patient]
                self.print_log(f"🔄 Перенаправлено лікування з {old_patient} на {state.patient_id}")

        # Apply block actions (lover)
        blocked_ids = {state.block_action_target_id} | set(getattr(state, "custom_block_ids", set()) or set())
        blocked_ids.discard(0)
        # Димова шашка: блок на невидимого гравця не спрацьовує
        smoke_invisible = getattr(state, "smoke_grenade_activated_this_night", set())
        covenant_night = getattr(state, "devil_covenant_night_shield", set())
        if state.block_action_target_id and state.block_action_target_id in smoke_invisible:
            old_block_target = state.block_action_target_id
            state.block_action_target_id = 0
            blocked_ids.discard(old_block_target)
        if state.block_action_target_id and state.block_action_target_id in covenant_night:
            old_block_target = state.block_action_target_id
            state.block_action_target_id = 0
            blocked_ids.discard(old_block_target)
        # Парфум / Чорний кіт:
        # - Якщо Коханка вже використала «Дізнатися» цієї ночі — нічого (баф/парфум уже в колбеку).
        # - «Нюх» (дзенькіт скла + спання кота) — щонайбільше 1 раз за всю гру (prostitute_black_cat_sniff_used_this_game).
        # - З активним котом і ще без нюху за гру: парфум не відлякує візит; нюх і списання кота — лише при валідному парфумі на цілі.
        # - Без кота (або нюх уже був): магазинний парфум відлякує як раніше.
        prostitute_black_cat_used_this_night = getattr(state, "prostitute_black_cat_used_this_night", False)
        if state.block_action_target_id and state.prostitute_id and not prostitute_black_cat_used_this_night:
            target_id = state.block_action_target_id
            has_black_cat = self._prostitute_has_black_cat(
                state.prostitute_id, chat_id
            ) and not getattr(state, "prostitute_black_cat_sniff_used_this_game", False)
            if has_black_cat:
                perfume_buff_id = None
                try:
                    items_t = get_active_items_for_player(target_id, chat_id)
                    item_ids_t = {it.get("item_id") for it in (items_t or [])}
                    if "parfum" in item_ids_t:
                        perfume_buff_id = "parfum"
                    elif "portal_perfume_gucci" in item_ids_t:
                        perfume_buff_id = "portal_perfume_gucci"
                except Exception:
                    perfume_buff_id = None
                can_sniff = bool(
                    perfume_buff_id
                    and (
                        perfume_buff_id != "parfum"
                        or target_id not in getattr(state, "parfum_shop_used_this_game", set())
                    )
                )
                if can_sniff:
                    cat_ok = try_consume_buff(chat_id, state.prostitute_id, "black_cat")
                    perf_ok = cat_ok and try_consume_buff(chat_id, target_id, perfume_buff_id)
                    if cat_ok and not perf_ok:
                        try:
                            await self._db_execute_commit(
                                """
                                UPDATE user_buffs SET quantity = quantity + 1
                                WHERE user_id = %s AND buff_id = 'black_cat'
                                  AND COALESCE(infinite, FALSE) = FALSE
                                  AND COALESCE(is_active, FALSE) = TRUE
                                """,
                                (state.prostitute_id,),
                            )
                        except Exception:
                            pass
                    if cat_ok and perf_ok:
                        if perfume_buff_id == "parfum":
                            used_p = set(getattr(state, "parfum_shop_used_this_game", set()))
                            used_p.add(int(target_id))
                            state.parfum_shop_used_this_game = used_p
                        state.prostitute_black_cat_used_this_night = True
                        state.prostitute_black_cat_sniff_used_this_game = True
                        self.print_log(
                            f"🐈‍⬛ Чорний кіт занюхав парфум у гравця {target_id} для Коханки {state.prostitute_id}"
                        )
                        trow = await self._db_fetchone(
                            "SELECT tg_name FROM users WHERE id = %s",
                            (target_id,),
                        )
                        member_name_parfum = trow[0] if trow else "Гравець"
                        try:
                            await bot.send_message(
                                chat_id=state.prostitute_id,
                                text=emoji_to_premium(
                                    "🐈‍⬛Кіт повернувся і тихо потерся об ноги.\n"
                                    "Тепер я знаю цей запах.\n\n"
                                    "🧴 Парфум використовує:\n"
                                    f"<b>{html.escape(member_name_parfum)}</b>\n\n"
                                    "Тепер його аромат не зможе завадити вашій ночі."
                                ),
                                parse_mode="html",
                            )
                        except Exception:
                            pass
                        try:
                            await bot.send_message(
                                chat_id=target_id,
                                text=emoji_to_premium(
                                    "🐈‍⬛Чорний кіт граційно вистрибнув на підвіконня.\n"
                                    "Він зачепив лапою ваш флакон парфуму.\n\n"
                                    "🧴 Флакон впав і розбився.\n\n"
                                    "Цієї ночі парфум більше не працює."
                                ),
                                parse_mode="html",
                            )
                        except Exception:
                            pass
                        try:
                            await bot.send_message(
                                chat_id=chat_id,
                                text=emoji_to_premium("🐈‍⬛У темному провулку чути дзенькіт скла…"),
                                parse_mode="html",
                            )
                        except Exception:
                            pass
                        await self._strip_message_reply_markup(
                            bot, state.prostitute_id, getattr(state, "choose_who_you_will_block", None)
                        )
            else:
                # Логіка парфуму без кота: спрацьовує як звичайний, так і портальний Gucci.
                perfume_no_cat_buff_id = None
                try:
                    items_t = get_active_items_for_player(target_id, chat_id)
                    item_ids_t = {it.get("item_id") for it in (items_t or [])}
                    if "parfum" in item_ids_t and target_id not in getattr(state, "parfum_shop_used_this_game", set()):
                        perfume_no_cat_buff_id = "parfum"
                    elif "portal_perfume_gucci" in item_ids_t:
                        perfume_no_cat_buff_id = "portal_perfume_gucci"
                except Exception:
                    perfume_no_cat_buff_id = None

                if perfume_no_cat_buff_id and try_consume_buff(chat_id, target_id, perfume_no_cat_buff_id):
                    if perfume_no_cat_buff_id == "parfum":
                        used_pf = set(getattr(state, "parfum_shop_used_this_game", set()))
                        used_pf.add(int(target_id))
                        state.parfum_shop_used_this_game = used_pf
                    state.block_action_target_id = 0
                    blocked_ids.discard(target_id)
                    self.print_log(
                        f"🧴 {perfume_no_cat_buff_id} відлякав Коханку від гравця {target_id}"
                    )
                    try:
                        await bot.send_message(
                            chat_id=target_id,
                            text=emoji_to_premium(
                                "🧴 <b>Парфум</b> спрацював!\n\nРізкий запах відлякав Коханку - цієї ночі вона не змогла провести час із вами."
                            ),
                            parse_mode="html",
                        )
                    except Exception:
                        pass
                    try:
                        await bot.send_message(
                            chat_id=state.prostitute_id,
                            text=emoji_to_premium(
                                "🧴 Ви підійшли до дверей - і вдихнули різкий аромат парфуму.\n"
                                "Цієї ночі візит зірвався."
                            ),
                            parse_mode="html",
                        )
                    except Exception:
                        pass

        # Обробка предметів: Капкан - перша нічна дія на тебе перенаправляється на випадкового гравця (1 раз за гру)
        trap_used = getattr(state, "trap_used_this_game", set())
        alive_members = [pid for pid in state.membersList if pid]
        for player_id in state.membersList:
            if player_id in trap_used:
                continue
            blocking_effects = item_processor.process_blocking_effects(player_id, state)
            if blocking_effects.get("block_first_visitor"):
                visitors = [v for v in state.visit_log if v[1] == player_id]
                if not visitors:
                    continue
                first_visitor_id, _, action = visitors[0]
                # Випадковий інший живий гравець (не власник капкана)
                candidates = [p for p in alive_members if p != player_id]
                if not candidates:
                    continue
                placeholders = ",".join(["%s"] * len(candidates))
                alive_rows = await self._db_fetchall(
                    f"SELECT id FROM users WHERE id IN ({placeholders}) AND killed = 0",
                    tuple(candidates),
                )
                alive_candidates = [r[0] for r in (alive_rows or [])]
                if not alive_candidates:
                    continue
                redirect_target = random.choice(alive_candidates)
                redirected = False
                # Вбивство - перевіряємо відповідне поле за типом відвідувача
                if action in ("kill_don", "kill_mafia") and (state.victim_id == player_id) and (
                    first_visitor_id == state.all_capone_id or (state.mafia_ids and first_visitor_id in state.mafia_ids)
                ):
                    state.victim_id = redirect_target
                    redirected = True
                elif action == "kill_maniac" and getattr(state, "maniac_victim_id", 0) == player_id and first_visitor_id == state.maniac_id:
                    state.maniac_victim_id = redirect_target
                    redirected = True
                elif action == "kill_comm" and getattr(state, "commissioner_kill_id", 0) == player_id and first_visitor_id == state.commissioner_id:
                    state.commissioner_kill_id = redirect_target
                    redirected = True
                elif action == "kill_sadistic" and getattr(state, "sadistic_kill_id", 0) == player_id and first_visitor_id == state.sadistic_doctor_id:
                    state.sadistic_kill_id = redirect_target
                    redirected = True
                elif action == "heal" and first_visitor_id == state.doctor_id and state.patient_id == player_id:
                    state.patient_id = redirect_target
                    redirected = True
                elif action == "heal_sadistic" and first_visitor_id == state.sadistic_doctor_id and getattr(state, "sadistic_heal_id", 0) == player_id:
                    state.sadistic_heal_id = redirect_target
                    redirected = True
                elif action == "block" and first_visitor_id == state.prostitute_id and state.block_action_target_id == player_id:
                    state.block_action_target_id = redirect_target
                    blocked_ids.discard(player_id)
                    blocked_ids.add(redirect_target)
                    redirected = True
                if redirected:
                    if not try_consume_buff(chat_id, player_id, "trap"):
                        pass  # немає зарядів - не застосовуємо ефект
                    else:
                        state.trap_used_this_game.add(player_id)
                        self.print_log(f"🪤 Капкан спрацював для {player_id}: дія перенаправлена на {redirect_target}")
                        try:
                            await bot.send_message(
                                chat_id=first_visitor_id,
                                text="🪤 <b>Капкан</b> спрацював!\n\nТвоя нічна дія була перенаправлена на іншого гравця.",
                                parse_mode="html"
                            )
                        except Exception:
                            pass
        
        newly_silenced_ids: set[int] = set()
        for blocked in blocked_ids:
            if blocked == state.all_capone_id:
                # Не скидаємо victim_id, якщо гравець ще не написав останнє повідомлення
                if not state.is_last_message or state.victim_id != blocked:
                    state.victim_id = 0
            if blocked == state.doctor_id:
                state.patient_id = 0
            if blocked == state.guardian_id:
                state.guardian_protect_id = 0
            if blocked == state.maniac_id:
                state.maniac_victim_id = 0
            if blocked == state.sadistic_doctor_id:
                state.sadistic_kill_id = 0
                state.sadistic_heal_id = 0
            if blocked == state.sheriff_id:
                state.sheriff_check_id = 0
            if blocked == state.commissioner_id:
                state.commissioner_check_id = 0
                state.commissioner_kill_id = 0
            if blocked == state.journalist_id:
                state.journalist_targets.clear()
            if blocked == state.lawyer_id:
                state.lawyer_client_id = 0
            if blocked == state.deceiver_id:
                state.deceiver_target_id = 0
            # Silence if not healed by doctor
            if blocked and blocked != state.patient_id:
                state.silenced_ids.add(blocked)
                newly_silenced_ids.add(blocked)

        # Якщо мовчун з'явився вже після старту дня (наприклад, через дії Коханки),
        # одразу зам'ютиуємо в чаті, щоб повідомлення не проходили.
        if newly_silenced_ids:
            try:
                until_date = int((datetime.utcnow() + timedelta(hours=6)).timestamp())
                if not hasattr(state, "muted_during_game") or state.muted_during_game is None:
                    state.muted_during_game = set()
                for sid in newly_silenced_ids:
                    try:
                        await bot.restrict_chat_member(
                            chat_id,
                            sid,
                            permissions=ChatPermissions(can_send_messages=False),
                            until_date=until_date,
                        )
                        state.muted_during_game.add(sid)
                    except Exception:
                        pass
            except Exception:
                pass
        
        # Після того як Коханка заблокувала нічні дії (у тому числі Комісара), обчислюємо результат його перевірки.
        # Якщо Комісар заблокований, commissioner_check_id уже скинуто і перевірка просто не спрацює.
        await self._resolve_commissioner_check(state, bot, chat_id, item_processor)
        
        # Портал: на ціль з «Запах фрі» або в ізоляції лікування не спрацьовує
        if state.patient_id and (state.patient_id in getattr(state, "portal_smell_fry_targets", set()) or state.patient_id in getattr(state, "portal_spirit_isolated", set())):
            state.patient_id = 0
        sadistic_heal_id = getattr(state, "sadistic_heal_id", 0)
        if sadistic_heal_id and (sadistic_heal_id in getattr(state, "portal_smell_fry_targets", set()) or sadistic_heal_id in getattr(state, "portal_spirit_isolated", set())):
            state.sadistic_heal_id = 0

        # Захист від "фантомного лікування":
        # зараховуємо doctor/sadistic-heal лише якщо є реальний heal-візит цієї ночі.
        doctor_heal_target = 0
        if state.doctor_id and state.patient_id:
            has_doctor_heal_visit = any(
                v_id == state.doctor_id and t_id == state.patient_id and action == "heal"
                for v_id, t_id, action in (state.visit_log or [])
            )
            if has_doctor_heal_visit:
                doctor_heal_target = state.patient_id
            else:
                state.patient_id = 0

        sadistic_heal_target = 0
        sadistic_doctor_id = getattr(state, "sadistic_doctor_id", 0)
        current_sadistic_heal_id = getattr(state, "sadistic_heal_id", 0)
        if sadistic_doctor_id and current_sadistic_heal_id:
            has_sadistic_heal_visit = any(
                v_id == sadistic_doctor_id and t_id == current_sadistic_heal_id and action == "heal_sadistic"
                for v_id, t_id, action in (state.visit_log or [])
            )
            if has_sadistic_heal_visit:
                sadistic_heal_target = current_sadistic_heal_id
            else:
                state.sadistic_heal_id = 0

        protection_ids = {
            doctor_heal_target,
            sadistic_heal_target,
        } | set(getattr(state, "custom_protect_ids", set()) or set())
        protection_ids.discard(0)

        # Диявол: контрактник не приніс 2 душі - йде в пекло (вбиваємо)
        devil_contract_holders = getattr(state, "devil_contract_holders", set())
        devil_contract_pending = getattr(state, "devil_contract_pending", 0)
        devil_kill_targets = getattr(state, "devil_kill_targets", []) or []
        failed_contract_kill = 0
        # Контракт вважається проваленим тільки після ТОЇ ночі, на яку він був виданий
        start_night = getattr(state, "devil_contract_start_night", 0)
        if devil_contract_pending and not devil_kill_targets and start_night and getattr(state, "night_number", 1) > start_night:
            failed_contract_kill = devil_contract_pending
            state.devil_failed_contract_holder_ids.add(devil_contract_pending)
            devil_contract_holders.discard(devil_contract_pending)
            state.devil_contract_holders = devil_contract_holders
            state.devil_contract_pending = 0
            try:
                # Повідомлення гравцю, що не виконав контракт
                try:
                    await bot.send_message(
                        chat_id=failed_contract_kill,
                        text=emoji_to_premium(
                            "⏳ Час вийшов.\n"
                            "Ти не виконав умови контракту.\n"
                            "👹 «Я завжди забираю своє.»\n"
                            "Твоя душа більше не належить тобі."
                        ),
                        parse_mode="html",
                    )
                except Exception:
                    pass
                devil_id = getattr(state, "devil_id", 0)
                if devil_id:
                    await bot.send_message(
                        chat_id=devil_id,
                        text=emoji_to_premium(
                            "👹 Твоя жертва не виконала умови контракту, тому вона відправляється в пекло!"
                        ),
                        parse_mode="html",
                    )
            except Exception:
                pass

        # Якщо Аль Капоне вбив того, кого контрактник обрав як жертву (душу) - душа перехоплена
        devil_id = getattr(state, "devil_id", 0)
        contract_holder_id = getattr(state, "devil_contract_pending", 0)
        if (state.victim_id and state.victim_id in devil_kill_targets and contract_holder_id
                and contract_holder_id != getattr(state, "all_capone_id", 0)):
            devil_kill_targets = [t for t in devil_kill_targets if t != state.victim_id]
            state.devil_kill_targets = devil_kill_targets
            state.devil_souls_brought = max(0, getattr(state, "devil_souls_brought", 0) - 1)
            msg_intercept = (
                "👹 Душу перехоплено.\n"
                "Аль Капоне вбив твою ціль - ця душа не зараховується."
            )
            try:
                if devil_id:
                    await bot.send_message(
                        chat_id=devil_id,
                        text=emoji_to_premium(msg_intercept),
                        parse_mode="html",
                    )
                if contract_holder_id:
                    await bot.send_message(chat_id=contract_holder_id, text=msg_intercept, parse_mode="html")
            except Exception:
                pass

        custom_kill_ids = getattr(state, "custom_kill_ids", []) or []
        kill_targets = [state.victim_id, state.maniac_victim_id, state.sadistic_kill_id, state.commissioner_kill_id]
        kill_targets.extend(devil_kill_targets)
        kill_targets.extend(custom_kill_ids)
        if failed_contract_kill:
            kill_targets.append(failed_contract_kill)
        kill_targets = [t for t in kill_targets if t]
        if devil_id:
            kill_targets = [t for t in kill_targets if t != devil_id]

        # Зберігаємо оригінальний список kill_targets для перевірки замаху на пацієнта
        # Враховуємо також потенційні вбивства заточкою (knife_kill_ids) і кастомні вбивства,
        # щоб Лікар міг рятувати від усіх типів нічних атак
        knife_ids_for_original = getattr(state, "knife_kill_ids", []) or []
        original_kill_targets = set(kill_targets) | set(knife_ids_for_original) | set(custom_kill_ids)

        # Bodyguard dies instead of protected target
        if state.guardian_protect_id and state.guardian_id:
            if state.guardian_protect_id in kill_targets:
                kill_targets = [t for t in kill_targets if t != state.guardian_protect_id]
                if state.guardian_id not in kill_targets:
                    kill_targets.append(state.guardian_id)

        # Та сама ціль може потрапити в список кілька разів (мафія + маніяк + кастомні kill тощо).
        # Без дедуплікації пасивні бафи (талісман, Tommy Gun) спрацьовують по «клону» - кілька разів за світанок.
        _seen_kill: set[int] = set()
        _kill_unique: list[int] = []
        for _tid in kill_targets:
            if _tid not in _seen_kill:
                _seen_kill.add(_tid)
                _kill_unique.append(_tid)
        kill_targets = _kill_unique

        killed_texts = []
        killed_players = []  # Зберігаємо список вбитих для пост-ефектів

        smoke_invisible = getattr(state, "smoke_grenade_activated_this_night", set())
        self.print_log(f"🎩 DEBUG: smoke_invisible at kill processing = {smoke_invisible}")
        self.print_log(f"🎩 DEBUG: kill_targets = {kill_targets}")
        for target_id in kill_targets:
            # Якщо гравець вже мертвий (наприклад, був повішений вдень),
            # нічні ефекти/бафи на ньому не повинні спрацьовувати.
            try:
                target_state_row = await self._db_fetchone(
                    "SELECT killed FROM users WHERE id = %s",
                    (target_id,),
                )
                if target_state_row and int(target_state_row[0] or 0) == 1:
                    continue
            except Exception:
                pass
            if target_id in protection_ids:
                self.print_log(
                    f"💊 Гравець {target_id} вилікуваний цієї ночі - пасивні бафи захисту (Tommy Gun/Талісман/Щасливчик) не спрацьовують"
                )
                continue
            if target_id == getattr(state, "devil_id", 0):
                continue
            if target_id in getattr(state, "devil_contract_holders", set()):
                continue
            if target_id in smoke_invisible:
                self.print_log(f"🕳 Гравець {target_id} невидимий (Димова шашка/Капелюх) - вбивство не спрацювало")
                continue
            if target_id in getattr(state, "devil_covenant_night_shield", set()):
                self.print_log(f"💥 Гравець {target_id} під захистом контракту з дияволом - вбивство не спрацювало")
                continue
            # Портал: ізоляція «Дух 2021» або «Запах фрі» - на ціль не впливають
            if target_id in getattr(state, "portal_spirit_isolated", set()):
                self.print_log(f"🌊 Гравець {target_id} в ізоляції (Дух 2021) - вбивство не спрацювало")
                continue
            if target_id in getattr(state, "portal_smell_fry_targets", set()):
                self.print_log(f"🍟 На ціль {target_id} «Запах фрі» - візитер нічого не зробив")
                continue
            # Портал: стрічка - жертва виживає, власник стрічки втрачає баф
            ribbon_protected = getattr(state, "portal_ribbon_protected", {})
            if target_id in ribbon_protected:
                owner_id = ribbon_protected[target_id]
                if try_consume_buff(chat_id, owner_id, "portal_ribbon"):
                    self.print_log(f"🎀 Стрічка врятувала {target_id}, баф списано у {owner_id}")
                    try:
                        await bot.send_message(chat_id=target_id, text="🎀 <b>Кольорова стрічка</b> врятувала тебе цієї ночі.", parse_mode="html")
                        await bot.send_message(chat_id=owner_id, text="🎀 Стрічку використано - ти втратив баф «Кольорова стрічка».", parse_mode="html")
                    except Exception:
                        pass
                    continue
            # Обробка предметів: перевірка блокування вбивства
            if item_processor.should_block_action(target_id, "kill", state):
                self.print_log(f"🛡️ Предмет заблокував вбивство гравця {target_id}")
                continue
            
            # Зберігаємо інформацію про вбивцю для пост-ефектів (узгоджено з victim_id / maniac_* — не «перший рядок у логу»)
            killer_id = self._resolve_night_killer_for_target(state, target_id)

            # Пріоритет захисту: спочатку Tommy Gun (1 раз за гру), потім Талісман (1 раз за гру).
            # Якщо обидва активні - перший напад спрацює Tommy Gun, наступний - Талісман.
            # Tommy Gun: жертва виживає, гине тільки нападник (перевірка ДО вбивства жертви)
            tommy_used = getattr(state, "tommy_gun_used_this_game", set())
            if killer_id and target_id not in tommy_used and try_consume_buff(chat_id, target_id, "tommy_gun"):
                tommy_used.add(target_id)
                state.tommy_gun_used_this_game = tommy_used
                self.print_log(f"🔫 Tommy Gun активовано для {target_id}: жертва виживає, нападник {killer_id} має загинути")
                try:
                    # Повідомлення жертві (вижила)
                    await bot.send_message(
                        chat_id=target_id,
                        text=(
                            "Хтось зайшов не в той дім - і отримав відповідь.\n"
                            "«Нічого особистого - тільки бізнес.»"
                        ),
                        parse_mode="html"
                    )
                    # Талісман у нападника: якщо він має талісман - рятує від смерті від Tommy Gun (виживає)
                    talisman_used = getattr(state, "talisman_shop_used_this_game", set())
                    if killer_id not in talisman_used and try_consume_buff(chat_id, killer_id, "talisman"):
                        talisman_used = set(talisman_used)
                        talisman_used.add(int(killer_id))
                        state.talisman_shop_used_this_game = talisman_used
                        self.print_log(f"📿 Талісман врятував нападника {killer_id} від смерті від Tommy Gun")
                        try:
                            await bot.send_message(
                                chat_id=killer_id,
                                text=emoji_to_premium("📿 <b>Талісман</b> спрацював!\n\nКажуть, він береже від фатального пострілу - цього разу він врятував вас від відбою жертви."),
                                parse_mode="html",
                            )
                        except Exception:
                            pass
                        try:
                            await message.answer(
                                emoji_to_premium(
                                    "🔫 Tommy Gun спрацював, але нападника врятував 📿 Талісман."
                                ),
                                parse_mode="html",
                            )
                        except Exception:
                            pass
                    else:
                        # Нападник гине від Tommy Gun, але лікарське лікування теж повинно рятувати.
                        if killer_id in protection_ids:
                            self.print_log(f"💊 Tommy Gun: нападник {killer_id} вижив завдяки лікуванню")
                            try:
                                await bot.send_message(
                                    chat_id=killer_id,
                                    text="💊 Лікування спрацювало: наслідки Tommy Gun не стали фатальними.",
                                    parse_mode="html",
                                )
                            except Exception:
                                pass
                            try:
                                await message.answer(
                                    emoji_to_premium("💊 Лікар встиг втрутитися - постріл Tommy Gun не став смертельним."),
                                    parse_mode="html",
                                )
                            except Exception:
                                pass
                        else:
                            # Нападник гине від Tommy Gun
                            await bot.send_message(
                                chat_id=chat_id,
                                text=emoji_to_premium("🔫 Хтось зайшов не в той дім."),
                                parse_mode="html",
                            )
                            await self._kill_player(killer_id, bot, message, chat_id)
                            killed_players.append((killer_id, None))
                            state.is_killed = 1
                except Exception as e:
                    self.print_log(f" Помилка обробки Tommy Gun: {e}")
                continue

            # Талісман: пасивно, один раз за гру рятує від фатального пострілу (жертва виживає, вбивця не гине)
            talisman_used_v = getattr(state, "talisman_shop_used_this_game", set())
            if target_id not in talisman_used_v and try_consume_buff(chat_id, target_id, "talisman"):
                talisman_used_v = set(talisman_used_v)
                talisman_used_v.add(int(target_id))
                state.talisman_shop_used_this_game = talisman_used_v
                self.print_log(f"📿 Талісман активовано для {target_id}: гравець уникнув смерті")
                try:
                    await bot.send_message(
                        chat_id=target_id,
                        text=emoji_to_premium("📿 <b>Талісман</b> спрацював!\n\nКажуть, він береже від фатального пострілу - цього разу він врятував вас."),
                        parse_mode="html",
                    )
                except Exception:
                    pass
                try:
                    await message.answer(
                        emoji_to_premium("📿 Талісман прийняв удар на себе."),
                        parse_mode="html",
                    )
                except Exception:
                    pass
                continue

            # Lucky 75% survive - тільки для ролі Щасливчик і лише 1 раз за гру.
            # Порядок: Tommy Gun -> Талісман -> Щасливчик.
            lucky_used = getattr(state, "lucky_used_this_game", set())
            target_role = None
            try:
                r = await self._db_fetchone(
                    "SELECT role FROM users WHERE id = %s",
                    (target_id,),
                )
                target_role = (r[0] or "").strip() if r else ""
            except Exception:
                pass
            if target_role == "Щасливчик" and target_id not in lucky_used:
                if random.random() < 0.75:  # 75% шанс вижити (один раз за гру)
                    lucky_used.add(target_id)
                    state.lucky_used_this_game = lucky_used
                    try:
                        lucky_result = await self._db_fetchone(
                            "SELECT tg_name FROM users WHERE id = %s",
                            (target_id,),
                        )
                        lucky_name = lucky_result[0] if lucky_result else "Гравець"
                        # Повідомлення гравцю в особисті повідомлення
                        try:
                            await bot.send_message(
                                chat_id=target_id,
                                text="🍀 Доля дала тобі відстрочку.",
                                parse_mode="html",
                            )
                        except Exception as e:
                            self.print_log(f" Помилка надсилання повідомлення Щасливчику в ПП {target_id}: {e}")
                        # Повідомлення в груповий чат
                        try:
                            await message.answer(
                                "<b>🍀 Схоже цієї ночі комусь пощастило </b>",
                                parse_mode="html",
                            )
                        except Exception as e:
                            self.print_log(f" Помилка надсилання повідомлення в чат про Щасливчика: {e}")
                        self.print_log(f"🍀 Щасливчик {lucky_name} (ID: {target_id}) вижив завдяки 75% шансу! (1 раз за гру)")
                        self._record_achievement_event(state, "lucky_survive_kill", target_id)
                    except Exception as e:
                        self.print_log(f" Помилка обробки виживання Щасливчика {target_id}: {e}")
                    continue
                else:
                    # 25% шанс померти - продовжуємо з вбивством
                    self.print_log(f"💀 Щасливчик (ID: {target_id}) не вижив (25% шанс смерті)")
            
            victim_text = await self._kill_player(target_id, bot, message, chat_id)
            if not victim_text:
                if getattr(state, "victim_id", 0) == target_id:
                    state.victim_id = 0
                if getattr(state, "maniac_victim_id", 0) == target_id:
                    state.maniac_victim_id = 0
                if getattr(state, "commissioner_kill_id", 0) == target_id:
                    state.commissioner_kill_id = 0
                if getattr(state, "sadistic_kill_id", 0) == target_id:
                    state.sadistic_kill_id = 0
                cxs = getattr(state, "custom_kill_ids", []) or []
                if target_id in cxs:
                    state.custom_kill_ids = [t for t in cxs if t != target_id]
                continue
            if victim_text not in killed_texts:
                killed_texts.append(victim_text)
            state.is_killed = 1
            killed_players.append((target_id, killer_id))

            # Повідомлення жертві маніяка
            is_maniac_kill = False
            for visitor_id, visited_id, action in state.visit_log:
                if visited_id == target_id and action == "kill_maniac":
                    is_maniac_kill = True
                    break
            if is_maniac_kill:
                if target_id == state.doctor_id and state.maniac_id:
                    self._record_achievement_event(state, "maniac_kill_doctor", state.maniac_id)
                try:
                    await bot.send_message(
                        chat_id=target_id,
                        text=emoji_to_premium(
                            "🔪 «Твоя ніч закінчилась раніше, ніж ти думав»"
                        ),
                        parse_mode="html"
                    )
                except Exception:
                    pass
            
            # Обробка предметів: Міна Апокаліпсис - вбиває всіх атакуючих
            post_effects = item_processor.process_post_effects(target_id, state, "after_death")
            if post_effects.get("kill_all_attackers"):
                # Списуємо заряд Міни Апокаліпсис
                if not try_consume_buff(chat_id, target_id, "apocalypse_mine"):
                    self.print_log(f"⚠️ Міна Апокаліпсис для {target_id}: немає зарядів")
                else:
                    self.print_log(f"🧨 Міна Апокаліпсис активована для {target_id} (списано заряд)")
                    # Знаходимо всіх, хто атакував гравця
                    attackers = set()
                    for visitor_id, visited_id, action in state.visit_log:
                        if visited_id == target_id and action in ["kill_don", "kill_mafia", "kill_maniac", "kill_comm", "kill_yakuza", "kill_sadistic"]:
                            attackers.add(visitor_id)
                    
                    for attacker_id in attackers:
                        if attacker_id in state.membersList and attacker_id != target_id:
                            self.print_log(f"🧨 Міна Апокаліпсис вбиває атакуючого {attacker_id}")
                        try:
                            await bot.send_message(
                                chat_id=attacker_id,
                                text="🧨 <b>Міна Апокаліпсис</b> спрацювала!\n\nТи загинув разом зі своєю жертвою.",
                                parse_mode="html"
                            )
                            await self._kill_player(attacker_id, bot, message, chat_id)
                            killed_players.append((attacker_id, None))
                        except Exception as e:
                            self.print_log(f" Помилка обробки міни Апокаліпсис: {e}")
            
            # Обробка пост-ефектів смерті (пріоритет 6)
            post_effects_death = item_processor.process_post_effects(target_id, state, "after_death")
            
            if post_effects_death.get("kill_killer") and killer_id:
                # Tommy Gun / Закладка - вбивця гине разом з жертвою (списуємо заряд)
                consumed = False
                # Обмеження: кожен баф - максимум 1 раз за гру для гравця
                tommy_used = getattr(state, "tommy_gun_used_this_game", set())
                if target_id not in tommy_used and try_consume_buff(chat_id, target_id, "tommy_gun"):
                    consumed = True
                    tommy_used.add(target_id)
                    state.tommy_gun_used_this_game = tommy_used
                    effect_name = "Tommy Gun"
                    effect_emoji = "🔫"
                elif try_consume_buff(chat_id, target_id, "booby_trap"):
                    consumed = True
                    effect_name = "Закладка"
                    effect_emoji = "💣"
                else:
                    self.print_log(f"⚠️ Tommy Gun / Закладка для {target_id}: немає зарядів або вже використано в цій грі")
                if consumed:
                    self.print_log(f"{effect_emoji} {effect_name} активовано для {target_id} (списано заряд)")
                    if killer_id in state.membersList:
                        self.print_log(f"{effect_emoji} {effect_name} активується! Вбивця {killer_id} гине разом з жертвою {target_id}")
                    try:
                        # Талісман у нападника (гілка після смерті жертви — раніше тут не перевірявся)
                        talisman_used_post = getattr(state, "talisman_shop_used_this_game", set())
                        if (
                            killer_id
                            and killer_id not in talisman_used_post
                            and try_consume_buff(chat_id, killer_id, "talisman")
                        ):
                            talisman_used_post = set(talisman_used_post)
                            talisman_used_post.add(int(killer_id))
                            state.talisman_shop_used_this_game = talisman_used_post
                            self.print_log(
                                f"📿 Талісман врятував нападника {killer_id} від смерті від {effect_name} (після смерті жертви)"
                            )
                            try:
                                await bot.send_message(
                                    chat_id=killer_id,
                                    text=emoji_to_premium(
                                        "📿 <b>Талісман</b> спрацював!\n\nКажуть, він береже від фатального пострілу - цього разу він врятував вас від відбою жертви."
                                    ),
                                    parse_mode="html",
                                )
                            except Exception:
                                pass
                            try:
                                await message.answer(
                                    emoji_to_premium(
                                        f"{effect_emoji} {effect_name} спрацював, але нападника врятував 📿 Талісман."
                                    ),
                                    parse_mode="html",
                                )
                            except Exception:
                                pass
                        else:
                            await bot.send_message(
                                chat_id=killer_id,
                                text=emoji_to_premium(f"{effect_emoji} <b>{effect_name}</b> спрацював!\n\nТи загинув разом зі своєю жертвою."),
                                parse_mode="html"
                            )
                            # Вбиваємо вбивцю
                            await self._kill_player(killer_id, bot, message, chat_id)
                            killed_players.append((killer_id, None))
                    except Exception as e:
                        self.print_log(f" Помилка обробки {effect_name}: {e}")
            
            if post_effects_death.get("reveal_killer") and killer_id and self._flashlight_killer_is_genuine(state, target_id):
                # Новий Ліхтарик - показує, хто тебе вбив (1 раз за гру).
                # Світимо ЛИШЕ якщо на жертві є справжній запис вбивства у visit_log.
                # Перенаправлені удари (Магніт/Чорна діра, «Водний потік» Русалки,
                # «Щаслива ніч») лишають запис на первісній цілі, тож резолвер падає у
                # фолбек і повертає Дона — таку (хибну) атрибуцію ліхтарик не показує.
                flash_used = getattr(state, "flashlight_used_this_game", set())
                if target_id in flash_used or not try_consume_buff(chat_id, target_id, "flashlight_new"):
                    self.print_log(f"⚠️ Ліхтарик (reveal_killer) для {target_id}: немає зарядів або вже використано цю гру")
                else:
                    flash_used.add(target_id)
                    state.flashlight_used_this_game = flash_used
                    try:
                        r = await self._db_fetchone(
                            "SELECT tg_name FROM users WHERE id = %s",
                            (killer_id,),
                        )
                        killer_name = r[0] if r else "Невідомий"
                        await bot.send_message(
                            chat_id=target_id,
                            text=emoji_to_premium(
                                "🔦 <b>Ліхтарик</b> спрацював.\n\n"
                                f"Тебе вбив(ла): <b>{killer_name}</b>."
                            ),
                            parse_mode="html"
                        )
                    except Exception as e:
                        self.print_log(f" Помилка надсилання результату Ліхтарика (reveal_killer) для {target_id}: {e}")
            
            if post_effects_death.get("hide_role"):
                # Папка X - приховує роль після смерті (списуємо заряд)
                if not try_consume_buff(chat_id, target_id, "folder_x"):
                    self.print_log(f"⚠️ Папка X для {target_id}: немає зарядів")
                else:
                    self.print_log(f"🧾 Папка X активується для гравця {target_id} (списано заряд)")
                    # TODO: Реалізувати приховування ролі в повідомленнях
            
            if post_effects_death.get("skip_next_night"):
                # Чорний феєрверк - наступна ніч без дій (списуємо заряд)
                if not try_consume_buff(chat_id, target_id, "black_firework"):
                    self.print_log(f"⚠️ Чорний феєрверк для {target_id}: немає зарядів")
                else:
                    self.print_log(f"🧨 Чорний феєрверк активується для гравця {target_id} (списано заряд)")
                    # TODO: Додати прапорець для пропуску наступної ночі
        
        # Додаткові вбивства заточкою: застосовуємо на світанку після основних нічних дій
        knife_ids = getattr(state, "knife_kill_ids", []) or []
        if knife_ids:
            already_killed = {pid for pid, _ in killed_players}
            for target_id in knife_ids:
                # Якщо ціль уже вбито іншою дією - пропускаємо
                if target_id in already_killed:
                    continue
                # Лікар / садистське лікування захищають і від заточки
                if target_id in protection_ids:
                    self.print_log(f"💊 Заточка проти {target_id} була заблокована лікуванням (Лікар/садист).")
                    continue
                if target_id in getattr(state, "devil_covenant_night_shield", set()):
                    self.print_log(f"💥 Заточка проти {target_id} не спрацювала (контракт з дияволом).")
                    continue
                # Талісман: пасивно, один раз за гру рятує і від заточки
                talisman_used_v = getattr(state, "talisman_shop_used_this_game", set())
                if target_id not in talisman_used_v and try_consume_buff(chat_id, target_id, "talisman"):
                    talisman_used_v = set(talisman_used_v)
                    talisman_used_v.add(int(target_id))
                    state.talisman_shop_used_this_game = talisman_used_v
                    self.print_log(f"📿 Талісман активовано для {target_id}: гравець уникнув смерті від заточки")
                    try:
                        await bot.send_message(
                            chat_id=target_id,
                            text=emoji_to_premium(
                                "📿 <b>Талісман</b> спрацював!\n\n"
                                "Цього разу він врятував вас від заточки."
                            ),
                            parse_mode="html",
                        )
                    except Exception:
                        pass
                    try:
                        await message.answer(
                            emoji_to_premium("📿 Талісман прийняв удар заточки на себе."),
                            parse_mode="html",
                        )
                    except Exception:
                        pass
                    continue
                victim_text = await self._kill_player(target_id, bot, message, chat_id)
                if not victim_text:
                    continue
                if victim_text not in killed_texts:
                    killed_texts.append(victim_text)
                state.is_killed = 1
                # Для заточки «вбивця» прихований, тому killer_id = None
                killed_players.append((target_id, None))

        # Дуель: 50/50 вже вирішено під час виклику; на світанку гине той, хто програв.
        # Це постріл впритул - лікування/захист не рятують (окрім уже мертвого).
        duel_ids = getattr(state, "duel_kill_ids", []) or []
        if duel_ids:
            already_killed_duel = {pid for pid, _ in killed_players}
            for target_id in duel_ids:
                if target_id in already_killed_duel:
                    continue
                victim_text = await self._kill_player(target_id, bot, message, chat_id)
                if not victim_text:
                    continue
                if victim_text not in killed_texts:
                    killed_texts.append(victim_text)
                state.is_killed = 1
                killed_players.append((target_id, None))
            # Публічне оголошення дуелі
            pend = getattr(state, "duel_pending", None)
            if pend:
                try:
                    cr = await self._db_fetchone("SELECT tg_name FROM users WHERE id = %s", (pend[0],))
                    tr = await self._db_fetchone("SELECT tg_name FROM users WHERE id = %s", (pend[1],))
                    lr = await self._db_fetchone("SELECT tg_name FROM users WHERE id = %s", (pend[2],))
                    cname = cr[0] if cr and cr[0] else "Гравець"
                    tname = tr[0] if tr and tr[0] else "Гравець"
                    lname = lr[0] if lr and lr[0] else "Гравець"
                    await message.answer(
                        emoji_to_premium(
                            f"⚔️ <b>Дуель на світанку</b>\n\n"
                            f"{cname} викликав {tname} до бар'єру. "
                            f"Пролунав постріл - і замертво впав <b>{lname}</b>."
                        ),
                        parse_mode="html",
                    )
                except Exception:
                    pass
                setattr(state, "duel_pending", None)

        # Legacy for single victim text
        if killed_texts:
            state.victim_text = ", ".join(killed_texts)
        else:
            state.victim_text = ""  # Очищаємо, якщо немає вбитих
        
        # Inform silenced players
        for silenced_id in state.silenced_ids:
            try:
                # Перевіряємо, чи гравець був заблокований Коханкою (не Головорізом)
                is_blocked_by_prostitute = (
                    state.block_action_target_id == silenced_id and state.prostitute_id
                )
                if is_blocked_by_prostitute:
                    # Повідомлення ранком
                    try:
                        await bot.send_message(
                            chat_id=silenced_id,
                            text="💋 «Залишайся» - шепоче Коханка. «Інакше розповім все дружині »",
                            parse_mode="html"
                        )
                    except:
                        pass
                else:
                    await bot.send_message(chat_id=silenced_id, text="🤐 Сьогодні ти не можеш голосувати.")
            except:
                pass

        # Волоцюга: show visitors (without action types and without own visits)
        # Досягнення Волоцюга: зайти до учасника до якого ходила коханка
        if state.homeless_id and state.homeless_target_id and state.homeless_target_id == state.block_action_target_id and state.prostitute_id:
            self._record_achievement_event(state, "homeless_visit_prostitute_target", state.homeless_id)
        if state.homeless_id and state.homeless_target_id:
            if state.eavesdropping_blocked:
                try:
                    await bot.send_message(
                        chat_id=state.homeless_id,
                        text=(
                            "📵 Підслуховування заблоковано. Сигнал заглушено."
                        ),
                        parse_mode="html"
                    )
                except:
                    pass
            else:
                visitors = [v for v in state.visit_log if v[1] == state.homeless_target_id and v[0] != state.homeless_id]
                if not visitors:
                    try:
                        await bot.send_message(
                            chat_id=state.homeless_id,
                            text=(
                                "🧥 <b>Волоцюга</b> тихо хмикає:\n"
                                "«Порожньо. Сьогодні без гостей.»"
                            ),
                            parse_mode="html"
                        )
                    except:
                        pass
                else:
                    visitor_list = []
                    seen_visitors = set()
                    for visitor_id, _, _ in visitors:
                        if visitor_id in seen_visitors:
                            continue
                        seen_visitors.add(visitor_id)
                        r = await self._db_fetchone(
                            "SELECT tg_name FROM users WHERE id = %s",
                            (visitor_id,),
                        )
                        if r:
                            visitor_list.append(r[0])
                    visitor_text = "\n".join([f"• 🧱{html.escape(v)}" for v in visitor_list]) if visitor_list else "• 🧱Невідомо"
                    try:
                        await bot.send_message(
                            chat_id=state.homeless_id,
                            text=(
                                "🧥:«Цікаво… тут сьогодні було людно.»\n"
                                "👣 Відвідувачі цієї ночі:\n"
                                f"{visitor_text}"
                            ),
                            parse_mode="html"
                        )
                    except:
                        pass

        # Journalist: compare factions
        def _journalist_faction_from_role_name(role_name: str) -> str:
            """Fallback faction resolver when role metadata is unavailable."""
            normalized_role = str(role_name or "").strip().lower()
            don_alias = str(getattr(state, "name_of_all_capone", "Аль Капоне") or "Аль Капоне").strip().lower()
            civilian_alias = str(getattr(state, "name_of_civilian", "Мирний житель") or "Мирний житель").strip().lower()

            mafia_roles = {
                "аль капоне",
                don_alias,
                "мафія",
                "адвокат",
                "брехун",
            }
            neutral_roles = {
                "маніяк",
                "заражений",
            }
            civilian_roles = {
                "мирний житель",
                civilian_alias,
            }

            if normalized_role in mafia_roles:
                return "mafia"
            if normalized_role in neutral_roles:
                return "neutral"
            if normalized_role in civilian_roles:
                return "civilians"
            return "civilians"

        covenant_night_done = getattr(state, "devil_covenant_night_shield", set())
        if state.journalist_id and len(state.journalist_targets) == 2:
            t1, t2 = state.journalist_targets
            if t1 in covenant_night_done or t2 in covenant_night_done:
                try:
                    await bot.send_message(
                        chat_id=state.journalist_id,
                        text=emoji_to_premium(
                            "💥 <b>Контракт з дияволом</b> зірвав інтерв'ю - результат недоступний."
                        ),
                        parse_mode="html",
                    )
                except Exception:
                    pass
            else:
                r1 = await self._db_fetchone(
                    "SELECT role, tg_name FROM users WHERE id = %s",
                    (t1,),
                )
                r2 = await self._db_fetchone(
                    "SELECT role, tg_name FROM users WHERE id = %s",
                    (t2,),
                )
                if r1 and r2:
                    role1, name1 = r1[0], r1[1] or "Гравець А"
                    role2, name2 = r2[0], r2[1] or "Гравець Б"
                    # Отримуємо creator_id для цієї групи
                    creator_result = await self._db_fetchone(
                        "SELECT creator_id FROM admin_panel WHERE group_id = %s",
                        (chat_id,),
                    )
                    creator_id = creator_result[0] if creator_result else 0
                    role_obj1 = ChatRoleRegistry.get_role_for_chat(creator_id, chat_id, role1) if creator_id else None
                    role_obj2 = ChatRoleRegistry.get_role_for_chat(creator_id, chat_id, role2) if creator_id else None
                    faction1 = role_obj1.faction if role_obj1 and getattr(role_obj1, "faction", None) else _journalist_faction_from_role_name(role1)
                    faction2 = role_obj2.faction if role_obj2 and getattr(role_obj2, "faction", None) else _journalist_faction_from_role_name(role2)
                    n1 = html.escape(str(name1))
                    n2 = html.escape(str(name2))
                    if faction1 == faction2:
                        result_text = (
                            "🔍 <b>Результат перевірки</b>\n\n"
                            "🎤 «Інтерв'ю пройшло гладко — вони на одній хвилі»\n"
                            f"➡️ Показує: {n1} і {n2} з однієї команди 👌🏻"
                        )
                    else:
                        result_text = (
                            "🔍 <b>Результат перевірки</b>\n\n"
                            "🎤 «Думки розходяться… цікаво»\n"
                            f"➡️ Показує: {n1} і {n2} з різних команд 🤔"
                        )
                    # Досягнення Журналіст: знайти водночас Аль Капоне і Мафія
                    don_roles = ["Аль Капоне"] + ([state.name_of_all_capone] if state.name_of_all_capone and state.name_of_all_capone != "Аль Капоне" else [])
                    if (role1 in don_roles and role2 == "Мафія") or (role2 in don_roles and role1 == "Мафія"):
                        if state.journalist_id:
                            self._record_achievement_event(state, "journalist_find_both", state.journalist_id)
                    await bot.send_message(
                        chat_id=state.journalist_id,
                        text=result_text,
                        parse_mode="html",
                    )

        # Infected: convert target
        if state.infected_target_id:
            r = await self._db_fetchone(
                "SELECT killed, role, tg_name FROM users WHERE id = %s",
                (state.infected_target_id,),
            )
            if r and r[0] == 0 and r[1] != "Заражений":
                if state.infected_target_id in covenant_night_done:
                    try:
                        await bot.send_message(
                            chat_id=state.infected_target_id,
                            text=emoji_to_premium(
                                "💥 <b>Контракт з дияволом</b> не дає зараженню знайти вхід."
                            ),
                            parse_mode="html",
                        )
                    except Exception:
                        pass
                else:
                    await self._set_player_role_async(state.infected_target_id, "Заражений")
                    if state.infected_target_id not in state.infected_ids:
                        state.infected_ids.append(state.infected_target_id)
                    try:
                        await bot.send_message(chat_id=state.infected_target_id, text="🧟 Тебе заражено. Тепер ти Заражений!")
                    except Exception:
                        pass
                    for inf_id in state.infected_ids:
                        if inf_id != state.infected_target_id:
                            try:
                                await bot.send_message(chat_id=inf_id, text=f"🧟 Новий заражений: {r[2]}")
                            except Exception:
                                pass
        
        # Reset flags для наступного циклу (очищуємо прапорці для наступної ночі)
        # НЕ очищуємо killed тут, бо він залишається назавжди
        await self._db_execute_commit(
            "UPDATE users SET cured = %s WHERE id IN %s",
            (0, tuple(state.membersList) if state.membersList else (None,)),
        )
        
        # Надсилаємо повідомлення гравцю, якого лікував лікар
        if state.patient_id and state.patient_id > 0:
            try:
                patient_result = await self._db_fetchone(
                    "SELECT tg_name FROM users WHERE id = %s",
                    (state.patient_id,),
                )
                patient_name = patient_result[0] if patient_result else "Гравець"
                
                # Перевіряємо, чи був замах на пацієнта (оригінальний список до перевірки захисту)
                was_attacked = state.patient_id in original_kill_targets
                # Досягнення Лікар: врятувати мирне населення від замоху (замаху мафії)
                if was_attacked and state.doctor_id:
                    pat_role_row = await self._db_fetchone(
                        "SELECT role FROM users WHERE id = %s",
                        (state.patient_id,),
                    )
                    pat_role = pat_role_row[0] if pat_role_row else ""
                    civilian_roles = ["Мирний житель", "Лікар", "Комісар Каттані", "Сержант", "Мед. сестра", "Коханка", "Журналіст", "Волоцюга", "Камікадзе", "Щасливчик", "Самогубець", "Адвокат"]
                    if pat_role in civilian_roles:
                        self._record_achievement_event(state, "doctor_save_civilians", state.doctor_id)
                # Перевіряємо, чи це колишня Мед. сестра (яка стала Лікарем)
                is_former_nurse = state.doctor_was_nurse
                
                # Якщо лікар лікує себе
                if state.patient_id == state.doctor_id:
                    if was_attacked:
                        if is_former_nurse:
                            # Мед. сестра лікує себе, коли били
                            await bot.send_message(
                                chat_id=state.patient_id,
                                text="💉 Медсестра діє різко і впевнено - руки тремтять, але рухи точні:\n«Перша ніч без нього… і одразу замах. Класична медицина.»",
                                parse_mode="html"
                            )
                        else:
                            # Оригінальний Лікар лікує себе, коли били
                            await bot.send_message(
                                chat_id=state.patient_id,
                                text="💊 «Замах на зміні. Ну, я вже звик, головне що вижив»",
                                parse_mode="html"
                            )
                    else:
                        if is_former_nurse:
                            # Мед. сестра лікує себе, коли не били
                            await bot.send_message(
                                chat_id=state.patient_id,
                                text="💉 «Паніка - не симптом. Дихай. Все під контролем.»",
                                parse_mode="html"
                            )
                        else:
                            # Оригінальний Лікар лікує себе, коли не били
                            await bot.send_message(
                                chat_id=state.patient_id,
                                text="💊«Це точно приймається не внутрішньовенно, добре що не перебрав»",
                                parse_mode="html"
                            )
                else:
                    # Лікар лікує іншого гравця
                    # Не надсилаємо ПП про "візит лікаря" мертвому гравцю.
                    patient_alive_row = await self._db_fetchone(
                        "SELECT killed FROM users WHERE id = %s",
                        (state.patient_id,),
                    )
                    if patient_alive_row and int(patient_alive_row[0]) == 1:
                        self.print_log(f"💊 Пропущено ПП пацієнту {state.patient_id}: гравець уже мертвий")
                    else:
                        if was_attacked:
                            if is_former_nurse:
                                # Мед. сестра лікує іншого, коли били
                                await bot.send_message(
                                    chat_id=state.patient_id,
                                    text="💉 Медсестра діє різко і впевнено - руки тремтять, але рухи точні:\n«Лікар би мною пишався. Живи.»",
                                    parse_mode="html"
                                )
                            else:
                                # Оригінальний Лікар лікує іншого, коли били
                                await bot.send_message(
                                    chat_id=state.patient_id,
                                    text="💊Лікар вривається в приміщення, він встигає тебе врятувати від сьогоднішнього замаху.\n«Просив же не бажати спокійної зміни»",
                                    parse_mode="html"
                                )
                        else:
                            if is_former_nurse:
                                # Мед. сестра лікує іншого, коли не били
                                await bot.send_message(
                                    chat_id=state.patient_id,
                                    text="💉 Медсестра зітхає, перевіряє пульс і тихо каже:\n«Я ще вчуся, але здається, ти просто перевтомився…»",
                                    parse_mode="html"
                                )
                            else:
                                # Оригінальний Лікар лікує іншого, коли не били
                                await bot.send_message(
                                    chat_id=state.patient_id,
                                    text="💊Лікар осудливо дивиться на тебе: «Температура 36.9 не причина викликати швидку, ми могли врятувати інше життя»",
                                    parse_mode="html"
                                )
                
                self.print_log(f"💊 Надіслано повідомлення пацієнту {patient_name} (ID: {state.patient_id}) про візит лікаря")
            except Exception as e:
                self.print_log(f" Помилка надсилання повідомлення пацієнту {state.patient_id}: {e}")
        
        # Обробка пост-ефектів після ночі (пріоритет 6)
        for player_id in state.membersList:
            post_effects = item_processor.process_post_effects(player_id, state, "after_night")
            
            # Пейджер - 1 раз за гру; показує тільки коли до гравця хтось приходив; тільки імена, без ролей
            if post_effects.get("reveal_visitors") and player_id not in getattr(state, "pager_used_this_game", set()):
                try:
                    if state.eavesdropping_blocked:
                        if not try_consume_buff(chat_id, player_id, "pager"):
                            pass  # немає зарядів - не показуємо пейджер
                        else:
                            state.pager_used_this_game.add(player_id)
                            await bot.send_message(
                                chat_id=player_id,
                                text="📟 <b>Пейджер</b>\n\nПідслуховування заблоковано. Сигнал заглушено.",
                                parse_mode="html"
                            )
                    else:
                        visitors = [v for v in state.visit_log if v[1] == player_id]
                        unique_visitors = set()
                        visitor_names = []
                        for visitor_id, _, _ in visitors:
                            if visitor_id not in unique_visitors:
                                unique_visitors.add(visitor_id)
                                r = await self._db_fetchone(
                                    "SELECT tg_name FROM users WHERE id = %s",
                                    (visitor_id,),
                                )
                                if r:
                                    visitor_names.append(r[0])
                        # Спрацьовує лише коли хтось приходив - імена без ролей; один раз за гру
                        if visitor_names:
                            if not try_consume_buff(chat_id, player_id, "pager"):
                                pass  # немає зарядів
                            else:
                                state.pager_used_this_game.add(player_id)
                                visitors_text = ", ".join(visitor_names)
                                await bot.send_message(
                                    chat_id=player_id,
                                    text=f"📟 <b>Пейджер</b> спрацював!\n\n"
                                         f"Цієї ночі до тебе приходили: {visitors_text}",
                                    parse_mode="html"
                                )
                        # Якщо ніхто не приходив - нічого не надсилаємо (пейджер не спрацьовує, можна ще раз наступної ночі)
                except Exception as e:
                    self.print_log(f" Помилка надсилання повідомлення про пейджер гравцю {player_id}: {e}")
        
        # Ліхтарик - результат для тих, хто обрав гравця вночі
        flashlight_choice = getattr(state, "flashlight_choice", {})
        for user_id, target_id in list(flashlight_choice.items()):
            try:
                tr = await self._db_fetchone(
                    "SELECT tg_name FROM users WHERE id = %s",
                    (target_id,),
                )
                target_name = tr[0] if tr else "Гравець"
                visitors = [v for v in state.visit_log if v[1] == target_id]
                unique_visitors = set()
                visitor_names = []
                for vid, _, _ in visitors:
                    if vid not in unique_visitors:
                        unique_visitors.add(vid)
                        vr = await self._db_fetchone(
                            "SELECT tg_name FROM users WHERE id = %s",
                            (vid,),
                        )
                        if vr:
                            visitor_names.append(vr[0])
                if state.eavesdropping_blocked:
                    result_text = f"🔦 <b>Ліхтарик</b>\n\nОбрано: {target_name}.\n\nПідслуховування цієї ночі було заблоковано."
                elif visitor_names:
                    visitors_str = ", ".join(visitor_names)
                    result_text = f"🔦 <b>Ліхтарик</b>\n\nДо {target_name} приходили: {visitors_str}"
                else:
                    result_text = f"🔦 <b>Ліхтарик</b>\n\nДо {target_name} ніхто не приходив."
                await bot.send_message(chat_id=user_id, text=emoji_to_premium(result_text), parse_mode="html")
            except Exception as e:
                self.print_log(f" Помилка надсилання результату ліхтарика гравцю {user_id}: {e}")
        state.flashlight_choice.clear()
        
        # Очищуємо тимчасові змінні для наступної ночі
        # НЕ скидаємо victim_id, якщо гравець ще не написав останнє повідомлення
        if not state.is_last_message:
            state.victim_id = 0
        state.patient_id = 0
        state.eavesdropping_blocked = False
        state.fire_extinguisher_used_this_night = set()
        # Невидимість діє лише одну ніч
        state.smoke_grenade_activated_this_night = set()
        # Маска (рандомізація перевірок) - ліміт на ніч
        state.mask_used_this_night = set()
        # Заточка: список жертв лише для поточної ночі
        state.knife_kill_ids = []
        # Дуель: список жертв лише для поточної ночі (дуель одноразова, але чистимо про всяк випадок)
        state.duel_kill_ids = []
        # Кастомні вбивства: теж лише для поточної ночі
        state.custom_kill_ids = []
        # Нічний щит «Контракт з дияволом» - після обробки нічних вбивств (включно зі світанковою заточкою)
        state.devil_covenant_night_shield.clear()

        # Не завершуємо гру до денного анонсу: гравці мають побачити підсумок ночі ("День настав"),
        # а фінальний результат перевіряється нижче після формування/надсилання денного повідомлення.

        # Галас у казино: чи була смерть першої ночі
        if state.night_number == 1 and killed_players:
            state.first_night_any_death = True

        # Одне повідомлення: відео дня (day.mp4) з текстом у підписі, або лише текст
        media_dir_day = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Media'))
        day_video = os.path.join(media_dir_day, 'day.mp4')

        if state.is_killed == 1:
            # Regular death message - показуємо, хто приходив до жертви (перелік ролей), і підтримуємо кілька вбивств
            if "killed_players" in locals():
                killed_ids = list(dict.fromkeys(pid for pid, _ in killed_players))  # без дублікатів
                # Жертви заточки в killed_players мають killer=None; state.knife_kill_ids вже скинуто для наступної ночі
                knife_victim_ids = {pid for pid, k in killed_players if k is None}
            else:
                killed_ids = []
                knife_victim_ids = set()
            if not killed_ids:
                seen = set()
                for target_id in kill_targets:
                    if target_id in protection_ids or target_id in seen:
                        continue
                    seen.add(target_id)
                    killed_ids.append(target_id)
            hide_dead_roles, hide_killer_roles, secret_voting, show_night_targets = await self._get_thematic_settings_async(chat_id, state)

            def _safe_str(val) -> str:
                """Повертає безпечний рядок для HTML; уникає None, bytes та зламаного кодування."""
                if val is None:
                    return "Гравець"
                if isinstance(val, bytes):
                    try:
                        return val.decode("utf-8", errors="replace").strip() or "Гравець"
                    except Exception:
                        return "Гравець"
                s = str(val).strip()
                return s if s else "Гравець"

            async def _get_victim_link_and_role_async(victim_id: int, hide_role: bool) -> tuple[str, str]:
                try:
                    r = await self._db_fetchone(
                        "SELECT role, tg_name FROM users WHERE id = %s",
                        (victim_id,),
                    )
                    if r:
                        v_role_raw = "Гравець" if hide_role else (r[0] if len(r) > 0 and r[0] else "Гравець")
                        v_name_raw = r[1] if len(r) > 1 else "Гравець"
                        v_role = _safe_str(v_role_raw)
                        v_name = _safe_str(v_name_raw)
                        v_link = vip_mod.html_user_link(victim_id, v_name)
                        return v_link, html.escape(v_role)
                except Exception:
                    pass
                return "Гравець", "Гравець"

            # Тільки дії-вбивства: у блоці «Сорока» показуємо лише ролі, які вбивають
            _kill_actions = ("kill_don", "kill_mafia", "kill_maniac", "kill_comm", "kill_sadistic", "kill_yakuza", "kill_custom")

            async def _get_visiting_roles_async(victim_id: int) -> list[str]:
                roles_list: list[str] = []
                # Для стандартних вбивств показуємо роль за типом дії, а не за поточним role в БД.
                # Це прибирає хибні випадки, коли в текст «вбивці» потрапляють не-вбивчі ролі (напр. Волоцюга).
                action_to_role = {
                    "kill_don": "Аль Капоне",
                    "kill_mafia": "Мафія",
                    "kill_maniac": "Маніяк",
                    "kill_comm": "Комісар Каттані",
                    "kill_sadistic": "Доктор-садист",
                    "kill_yakuza": "Оябун",
                }
                for visitor_id, visited_id, action in state.visit_log:
                    if visited_id != victim_id or action not in _kill_actions:
                        continue

                    if action == "kill_custom":
                        try:
                            rr = await self._db_fetchone(
                                "SELECT role FROM users WHERE id = %s",
                                (visitor_id,),
                            )
                            role_name = rr[0] if rr and rr[0] else "Невідома роль"
                        except Exception:
                            role_name = "Невідома роль"
                    else:
                        role_name = action_to_role.get(action, "Невідома роль")

                    if role_name not in roles_list:
                        roles_list.append(role_name)
                return roles_list

            # Формуємо "Сорока..." блок
            soroka_lines: list[str] = []
            for victim_id in killed_ids:
                hide_role_victim = item_processor.should_hide_role_on_death(victim_id) or hide_dead_roles
                if hide_role_victim:
                    soroka_lines.append("• 📁 Папка X - дії та роль не розкриваються.")
                    continue
                visiting_roles = await _get_visiting_roles_async(victim_id)
                if not visiting_roles:
                    soroka_lines.append("• Ніхто не заходив у гості.")
                    continue
                v_link, _v_role = await _get_victim_link_and_role_async(victim_id, hide_role=False)
                if hide_killer_roles:
                    roles_str = "невідомі гості"
                else:
                    roles_str = ", ".join([f"<b>{html.escape(r)}</b>" for r in visiting_roles])
                soroka_lines.append(f"• До {v_link} заходили: {roles_str}")

            action_text = "Сорока на хвості принесла звістку, що:\n" + "\n".join(soroka_lines)

            # Текст про жертву/жертви (для 2+ жертв - перераховуємо ролі та імена)
            if len(killed_ids) == 1:
                victim_id = killed_ids[0]
                hide_role_victim = item_processor.should_hide_role_on_death(victim_id) or hide_dead_roles
                victim_link, victim_role = await _get_victim_link_and_role_async(victim_id, hide_role_victim)
                killed_block = f"Цієї ночі <b>{victim_role}</b> {victim_link} було вбито.\n"

                # Підбираємо роль вбивці (перша з тих, хто реально вбивав цю ніч)
                killer_roles = await _get_visiting_roles_async(victim_id)
                if killer_roles:
                    killer_role_text = f"<b>{html.escape(killer_roles[0])}</b>"
                else:
                    killer_role_text = "невідомий"
                # Якщо ціль убили заточкою - показуємо «Невідомий» замість конкретної ролі
                killed_by_knife_single = victim_id in knife_victim_ids
            else:
                # Формат для кількох жертв - в одному рядку через кому
                victim_entries: list[str] = []
                killer_roles_global: list[str] = []

                for vid in killed_ids:
                    hide_role_victim = item_processor.should_hide_role_on_death(vid) or hide_dead_roles
                    v_link, v_role = await _get_victim_link_and_role_async(vid, hide_role_victim)
                    victim_entries.append(f"<b>{v_role}</b> {v_link}")

                    visiting_roles = await _get_visiting_roles_async(vid)
                    if not hide_killer_roles and visiting_roles:
                        for r in visiting_roles:
                            if r not in killer_roles_global:
                                killer_roles_global.append(r)

                killed_block = "Цієї ночі були вбиті:\n" + ", ".join(victim_entries) + "\n"

                # Якщо когось убили заточкою - додаємо «Невідомий» до списку вбивць (як окремий пункт)
                has_knife_victim = bool(knife_victim_ids.intersection(set(killed_ids)))

                if hide_killer_roles:
                    killers_str = "невідомі гості"
                else:
                    killers_display: list[str] = []
                    if killer_roles_global:
                        killers_display.extend([f"<b>{html.escape(r)}</b>" for r in killer_roles_global])
                    if has_knife_victim:
                        killers_display.append("<b>Невідомий</b>")
                    killers_str = ", ".join(killers_display) if killers_display else "невідомі гості"

                killed_block += f"Кажуть, що за цим стоять {killers_str}.\n"
            if len(killed_ids) == 1:
                # Формат для однієї жертви - короткий текст; «сороку» показуємо лише якщо ввімкнено нічні цілі
                if 'killed_by_knife_single' in locals() and killed_by_knife_single:
                    killer_summary = "<b>Невідомий</b>"
                elif hide_killer_roles:
                    killer_summary = "невідомий"
                else:
                    killer_summary = killer_role_text
                day_text = (
                    "🌄 <b>СВІТАНОК</b> 🌄\n\n"
                    "Місто прокинулося з поганою новиною.\n\n"
                    f"{killed_block}"
                    f"<i>Кажуть, що за цим стоїть {killer_summary}.</i>\n"
                )
            else:
                # Для 2+ жертв: новий формат повідомлення з переліком убитих та ролей убивць
                day_text = (
                    "🌄 <b>СВІТАНОК</b> 🌄\n\n"
                    "Місто прокинулося з поганою новиною.\n\n"
                    f"{killed_block}"
                )
        else:
            # Без вбивства - не показуємо блок «Сорока…», навіть якщо хтось робив вибір, але жертв немає
            action_line = ""
            day_text = (
                "🌄 <b>СВІТАНОК</b> 🌄\n\n"
                "<blockquote>Цієї ночі місто вціліло — жодної жертви.\n"
                "Але Сім'я нікуди не зникла…</blockquote>"
                f"{action_line}"
            )

        if mafia_day_preface:
            try:
                await message.answer(
                    emoji_to_premium(mafia_day_preface, skip_vip_badges=False),
                    parse_mode="html",
                )
            except Exception:
                pass

        day_caption = emoji_to_premium(day_text, skip_vip_badges=False)

        # Пріоритет — піксельарт-анімація дня (Media/day.gif) через send_animation.
        day_sent_media = await self._send_phase_media(bot, chat_id, 'day', day_caption)
        path_day_send = None
        if not day_sent_media and os.path.isfile(day_video):
            path_day_send = await self._prepare_video_9_16(day_video) or day_video
        try:
            if day_sent_media:
                pass
            elif path_day_send and os.path.isfile(path_day_send):
                await bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(path_day_send),
                    caption=day_caption,
                    parse_mode="html",
                )
            else:
                await message.answer(day_caption, parse_mode="html")
        except Exception as e:
            self.print_log(f"⚠️ Не вдалося надіслати day.mp4: {e}")
            try:
                await message.answer(day_caption, parse_mode="html")
            except Exception:
                pass
        finally:
            if path_day_send and path_day_send != day_video:
                try:
                    os.unlink(path_day_send)
                except OSError:
                    pass

        # Check win conditions after night
        winner = await self.check_win_conditions_async(chat_id)
        if winner:
            await self._handle_game_end(message, bot, chat_id, winner)
            return

        # Якщо після нічних подій у грі не залишилось жодного гравця - завершуємо гру без обговорення
        if not state.membersList or not state.membersNames:
            await message.answer(
                "⏰ <b>Гру завершено.</b>\n\n"
                "У грі не залишилось жодного активного гравця.",
                parse_mode="html"
            )
            await self._unmute_users_muted_during_game(bot, chat_id)
            state.game_active = False
            self._reset_last_word_tracking(state)
            return

        # Список живих гравців (імена)
        players_text = self._format_players_list_numbered_html(state.membersNames)

        # Інформація про живих гравців за ролями
        alive_roles_info = await self._get_alive_roles_info_async(chat_id, state)

        total_players = len(state.membersList)
        discussion_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=f"Пропустити обговорення (0/{total_players})", callback_data="skip_discussion")]]
        )

        discussion_body = (
            f"Список гравців:\n\n"
            f"{players_text}\n\n"
            f"{alive_roles_info}\n\n"
        )
        discussion_payload = emoji_to_premium(discussion_body, skip_vip_badges=False)
        try:
            discussion_msg = await message.answer(
                discussion_payload,
                reply_markup=discussion_keyboard,
                parse_mode="html",
            )
        except TelegramBadRequest as e:
            # Fail-safe: якщо HTML у списку гравців виявився битим, не блокуємо перехід фази.
            self.print_log(f"⚠️ discussion HTML fallback: {e}")
            discussion_plain = re.sub(r"<[^>]+>", "", html.unescape(discussion_payload)).strip()
            discussion_msg = await message.answer(
                discussion_plain or "Список гравців недоступний.",
                reply_markup=discussion_keyboard,
            )
        state.discussion_message = discussion_msg

        if len(state.membersList) <= 1:
            # Final win check
            winner = await self.check_win_conditions_async(chat_id)
            if winner:
                await self._send_endgame_summary(message, bot, chat_id, winner)
                await self._award_win_rewards(bot, chat_id, winner)
                roster_data, game_events = await self._build_roster_for_achievements_async(chat_id, winner)
                if roster_data or game_events:
                    try:
                        from commands.story_achievements import process_achievements_after_game
                        await process_achievements_after_game(bot, roster_data or [], winner, game_events=game_events)
                    except Exception as e:
                        self.print_log(f"Досягнення після гри: {e}")
                await self._unmute_users_muted_during_game(bot, chat_id)
                state.game_active = False
                self._reset_last_word_tracking(state)
                return
        else:
            # Запускаємо обговорення (30 секунд) з відліком часу
            async def discussion_timer():
                try:
                    self.print_log(f"⏰ discussion_timer запущено для chat_id={chat_id}, чекаю 30 секунд...")
                    discussion_duration = 30
                    update_interval = 5  # Оновлюємо кожні 5 секунд
                    remaining = discussion_duration
                    
                    while remaining > 0:
                        # Чекаємо 1 секунду перед перевіркою
                        await asyncio.sleep(1)
                        remaining -= 1
                        
                        # Перевіряємо, чи гра ще активна та чи обговорення не пропущено
                        state = self._get_state(chat_id)
                        if not state.game_active or state.discussion_skipped:
                            self.print_log(f"⚠️ Обговорення зупинено: game_active={state.game_active}, discussion_skipped={state.discussion_skipped}")
                            return
                        
                        # Оновлюємо повідомлення кожні 5 секунд або коли залишилося менше 5 секунд (не показуємо 0 - одразу переходимо до голосування)
                        if remaining > 0 and (remaining % update_interval == 0 or remaining < update_interval):
                            if state.discussion_message:
                                try:
                                    # Отримуємо актуальні дані для повідомлення
                                    current_players_text = self._format_players_list_numbered_html(state.membersNames)
                                    current_alive_roles_info = await self._get_alive_roles_info_async(chat_id, state)
                                    votes_count = len(state.skip_discussion_votes)
                                    total_players = len(state.membersList)
                                    current_discussion_keyboard = InlineKeyboardMarkup(
                                        inline_keyboard=[[InlineKeyboardButton(text=f"Пропустити обговорення ({votes_count}/{total_players})", callback_data="skip_discussion")]]
                                    )
                                    _disc_body = (
                                        f"Список гравців:\n\n"
                                        f"{current_players_text}\n\n"
                                        f"{current_alive_roles_info}\n\n"
                                    )
                                    await state.discussion_message.edit_text(
                                        emoji_to_premium(_disc_body, skip_vip_badges=False),
                                        reply_markup=current_discussion_keyboard,
                                        parse_mode="html",
                                    )
                                except TelegramRetryAfter as e:
                                    self.print_log(f"⚠️ Flood control при оновленні повідомлення про обговорення: чекаємо {e.retry_after} секунд")
                                    await asyncio.sleep(e.retry_after)
                                except Exception:
                                    # Інші помилки (наприклад, повідомлення видалено) - просто продовжуємо
                                    pass
                    
                    # Після завершення відліку перевіряємо, чи обговорення не було пропущено
                    state = self._get_state(chat_id)
                    state.discussion_started_at = None  # фаза обговорення завершена
                    self.print_log(f"⏰ discussion_timer: після 30 секунд для chat_id={chat_id}, game_active={state.game_active}, discussion_skipped={state.discussion_skipped}")
                    if state.game_active and not state.discussion_skipped:
                        self.print_log(f"🚀 Запускаю відлік до голосування після обговорення для chat_id={chat_id}")
                        # Запускаємо відлік до голосування
                        await self._start_voting_prep_timer(message, bot, chat_id)
                    else:
                        self.print_log(f"⚠️ Не запускаю відлік: game_active={state.game_active}, discussion_skipped={state.discussion_skipped}")
                except asyncio.CancelledError:
                    # Завдання було скасовано (обговорення пропущено)
                    self.print_log(f" discussion_timer скасовано для chat_id={chat_id}")
                    pass
                except Exception as e:
                    self.print_log(f" Помилка в discussion_timer для chat_id={chat_id}: {e}")
                    import traceback
                    self.print_log(f" Traceback: {traceback.format_exc()}")
            
            # Зберігаємо завдання для можливості скасування
            state.discussion_started_at = datetime.now()
            state.discussion_task = asyncio.create_task(discussion_timer())
            self.print_log(f" discussion_task створено для chat_id={chat_id}")
    
    def _ensure_last_word_queue(self, state: GameState) -> None:
        """Сумісність зі старими об'єктами GameState під час hot-reload."""
        if not hasattr(state, "last_word_queue"):
            state.last_word_queue = []

    def _ensure_last_word_allowed_ids(self, state: GameState) -> None:
        """Список гравців, яким дозволено надіслати останнє слово прямо зараз."""
        if not hasattr(state, "last_word_allowed_ids"):
            state.last_word_allowed_ids = set()

    def _reset_last_word_tracking(self, state: GameState) -> None:
        self._ensure_last_word_queue(state)
        self._ensure_last_word_allowed_ids(state)
        state.last_word_queue.clear()
        state.last_word_allowed_ids.clear()
        state.is_last_message = False
        state.victim_id = 0

    def _last_word_lock(self, group_chat_id: int) -> asyncio.Lock:
        lock = self._last_word_locks.get(group_chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._last_word_locks[group_chat_id] = lock
        return lock

    async def _send_last_word_invite_dm(self, bot: Bot, player_id: int, killed_by_don: bool) -> None:
        if killed_by_don:
            await bot.send_message(
                chat_id=player_id,
                text=emoji_to_premium(
                    "🎩 Сім'я Аль Капоне не прощає зради, ти відправляєшся в пекло.\n\n"
                    "💬 <b>Напиши своє останнє повідомлення!</b>\n\n"
                ),
                parse_mode="html",
            )
        else:
            await bot.send_message(
                chat_id=player_id,
                text=(
                    "💀 <b>Тебе вбили!</b> 💀\n\n"
                    "💬 <b>Напиши своє останнє повідомлення!</b>\n\n"
                ),
                parse_mode="html",
            )

    async def _try_send_last_word_invite_dm(
        self,
        bot: Bot,
        message: Optional[Message],
        chat_id: int,
        player_id: int,
        killed_by_don: bool,
    ) -> None:
        """
        Запрошення на останнє слово в ПП. Помилка Telegram (не /start, блок тощо) не повинна ламати _kill_player:
        інакше гравець уже мертвий у БД, а функція повертає None і ламає світанок.
        message може бути None (наприклад, виклик з черги після попереднього останнього слова).
        """
        try:
            await self._send_last_word_invite_dm(bot, player_id, killed_by_don)
        except Exception as e:
            self.print_log(f"⚠️ Останнє слово: основне ПП для {player_id} не надіслано: {e}")
            try:
                plain = (
                    "🎩 Сім'я Аль Капоне не прощає зради.\n\n"
                    "💬 Напиши боту в особистих повідомленнях (/start), потім одне повідомлення - твоє останнє слово для групи."
                    if killed_by_don
                    else "💀 Тебе вбили!\n\n"
                    "💬 Відкрий чат з ботом, натисни /start, потім надішли одне повідомлення - твоє останнє слово."
                )
                await bot.send_message(chat_id=player_id, text=plain)
            except Exception as e2:
                self.print_log(f"⚠️ Останнє слово: запасне ПП для {player_id} теж не вдалось: {e2}")
            try:
                row = await self._db_fetchone(
                    "SELECT COALESCE(NULLIF(TRIM(tg_name), ''), '') FROM users WHERE id = %s",
                    (player_id,),
                )
                disp = (row[0] if row and row[0] else "") or "Гравець"
                who = vip_mod.html_user_link(int(player_id), disp)
            except Exception:
                who = f"<a href=\"tg://user?id={int(player_id)}\">Гравець</a>"
            hint = (
                f"💬 {who}: бот не зміг надіслати запрошення в ПП.\n"
                f"Відкрий чат з ботом, /start, потім <b>в особистих</b> надішли текст останнього слова - бот перешле в групу."
            )
            try:
                if message is not None:
                    await message.answer(hint, parse_mode="html")
                else:
                    await bot.send_message(chat_id=chat_id, text=hint, parse_mode="html")
            except Exception:
                pass

    async def _activate_next_queued_last_word(self, bot: Bot, chat_id: int) -> None:
        """Передає останнє слово наступному з черги (після успішної відправки або відмови поточного)."""
        state = self._get_state(chat_id)
        self._ensure_last_word_queue(state)
        while state.last_word_queue:
            if not state.game_active:
                state.last_word_queue.clear()
                return
            next_id, killed_by_don = state.last_word_queue.pop(0)
            try:
                r = await self._db_fetchone(
                    "SELECT killed FROM users WHERE id = %s",
                    (next_id,),
                )
                if r is not None and (r[0] or 0) == 0:
                    self.print_log(f"⏭️ last_word_queue: пропускаю {next_id} - у БД не killed")
                    continue
            except Exception:
                pass
            state.victim_id = next_id
            state.is_last_message = True
            await self._try_send_last_word_invite_dm(bot, None, chat_id, next_id, killed_by_don)
            return

    async def _kill_player(self, player_id: int, bot: Bot, message: Message, chat_id: int):
        """Helper function to remove a killed player from the game"""
        state = self._get_state(chat_id)
        
        try:
            result = await self._db_fetchone(
                "SELECT tg_name, role, COALESCE(killed, 0) FROM users WHERE id = %s",
                (player_id,),
            )
            if result:
                name, role, already_dead = result[0], result[1], int(result[2] or 0)
                if already_dead == 1:
                    return None
                victim_text = f"{role} {name}"
                state.victim_text = victim_text
                
                # Update database
                await self._db_execute_commit(
                    "UPDATE users SET killed = %s, cured = %s WHERE id = %s",
                    (1, 0, player_id,),
                )
                
                # Remove from lists
                if player_id in state.membersList:
                    state.membersList.remove(player_id)
                
                for member in state.membersNames[:]:
                    if member[0] == player_id:
                        state.membersNames.remove(member)
                        break

                self._sync_devil_contract_on_player_elimination(state, player_id)
                
                if player_id in state.list_of_patient:
                    state.list_of_patient.remove(player_id)
                
                if player_id in state.list_of_victim:
                    state.list_of_victim.remove(player_id)
                
                if player_id in state.civilian_ids:
                    state.civilian_ids.remove(player_id)
                if player_id in state.mafia_ids:
                    state.mafia_ids.remove(player_id)
                if player_id in state.infected_ids:
                    state.infected_ids.remove(player_id)
                if player_id in state.lucky_ids:
                    state.lucky_ids.remove(player_id)
                
                if player_id == state.doctor_id:
                    await self._promote_nurse_to_doctor_after_doctor_death_async(state)
                if player_id == state.all_capone_id:
                    await self._elect_new_don_from_alive_mafia_async(
                        state, bot, chat_id, dead_don_id=player_id, dm_old_don=True
                    )
                if player_id == state.commissioner_id:
                    await self._promote_sergeant_to_commissioner_after_comm_death_async(state, bot, chat_id)
                if player_id == state.nurse_id:
                    state.nurse_id = 0
                # Якщо медсестра, яку цієї ж ночі підвищили до Лікаря, гине - скасовуємо денне повідомлення про підвищення.
                if player_id == int(getattr(state, "nurse_promoted_day_notify_id", 0) or 0):
                    state.nurse_promoted_day_notify_id = 0
                if player_id == state.kamikaze_id:
                    state.kamikaze_id = 0
                    # Якщо Камікадзе вбитий вночі - здатність не активується
                    # (kamikaze_choice викликається тільки при повішанні вдень)
                if player_id == state.deceiver_id:
                    state.deceiver_id = 0
                if player_id == state.clown_id:
                    state.clown_id = 0
                if player_id == getattr(state, "devil_id", 0):
                    state.devil_id = 0
                
                # Перевіряємо, чи вбивство від Аль Капоне.
                # Для денних смертей (повішення тощо) це не застосовується.
                killed_by_don = False
                if not getattr(state, "day_active", False):
                    for visitor_id, target_id, action in state.visit_log:
                        if target_id == player_id and action == "kill_don":
                            killed_by_don = True
                            break
                
                # Перевірка: не давати передсмертне повідомлення, якщо гра вже закінчена або щойно закінчилась (ця смерть)
                winner_after_death = await self.check_win_conditions_async(chat_id)
                if state.game_active and not winner_after_death:
                    self._ensure_last_word_queue(state)
                    self._ensure_last_word_allowed_ids(state)
                    state.last_word_allowed_ids.add(player_id)
                    state.is_last_message = True
                    # Для сумісності лишаємо victim_id як "першого активного",
                    # але дозвіл тепер перевіряється через last_word_allowed_ids.
                    if not state.victim_id:
                        state.victim_id = player_id
                    await self._try_send_last_word_invite_dm(
                        bot, message, chat_id, player_id, killed_by_don
                    )
                else:
                    # Якщо цією смертю вже сформована перемога - не лишаємо "останнє слово" активним.
                    if winner_after_death:
                        self._ensure_last_word_allowed_ids(state)
                        state.last_word_allowed_ids.discard(player_id)
                        if state.victim_id == player_id:
                            state.victim_id = 0
                        state.is_last_message = bool(state.last_word_allowed_ids)
                        self._ensure_last_word_queue(state)
                        state.last_word_queue = [(uid, kd) for uid, kd in state.last_word_queue if uid != player_id]
                    # Гра вже закінчена - не даємо можливість написати останнє повідомлення
                    try:
                        if killed_by_don:
                            await bot.send_message(
                                chat_id=player_id,
                                text=emoji_to_premium(
                                    "🎩 Сім'я Аль Капоне не прощає зради, ти відправляєшся в пекло.\n\n"
                                    + PLAY_LAST_WORD_GAME_OVER,
                                    skip_vip_badges=False,
                                ),
                                parse_mode="html",
                            )
                        else:
                            await bot.send_message(
                                chat_id=player_id,
                                text=emoji_to_premium(
                                    "💀 <b>Тебе вбили!</b> 💀\n\n" + PLAY_LAST_WORD_GAME_OVER,
                                    skip_vip_badges=False,
                                ),
                                parse_mode="html",
                            )
                    except Exception as e:
                        self.print_log(f"⚠️ ПП «гра закінчена» для {player_id}: {e}")
                return victim_text
        except Exception as e:
            self.print_log(f"Error killing player {player_id}: {e}")
        return None

    def _vip_player_link_for_roster(self, user_id: int, display_name: str | None = None) -> str:
        """Посилання на гравця для HTML-списків без додаткового DB-запиту."""
        raw_display = (display_name or "").strip()
        # Захист від "подвійного HTML": якщо в state вже лежить <a>/<b> з попередніх версій,
        # вирізаємо теги й лишаємо тільки видимий текст імені.
        display = re.sub(r"<[^>]+>", "", html.unescape(raw_display)).strip() or "Гравець"
        return vip_mod.html_user_link(int(user_id), display)

    def _format_players_list_numbered_html(self, pairs) -> str:
        """Нумерований список гравців для HTML у групі (обговорення, тести, старт гри)."""
        if not pairs:
            return ""
        return "\n".join(
            f"{i + 1}. {self._vip_player_link_for_roster(uid, name)}"
            for i, (uid, name) in enumerate(pairs)
        )

    def _lobby_text(self, state, remaining_seconds: int, total_seconds: int, max_players: int = 30) -> str:
        """Красиве повідомлення лоббі: заголовок, лічильник N/max, нумерований список, прогрес-бар часу."""
        n = len(getattr(state, "membersList", []) or [])
        players = self._format_players_list_numbered_html(getattr(state, "membersNames", []) or [])
        if not players:
            players = "<i>Поки що нікого. Тисни «Приєднатися».</i>"
        total = max(1, int(total_seconds or 1))
        rem = max(0, int(remaining_seconds or 0))
        filled = max(0, min(10, round(10 * rem / total)))
        bar = "▓" * filled + "░" * (10 - filled)
        return (
            "🎩 <b>ЗБІР СІМʼЇ</b> 🍋\n\n"
            f"👥 <b>У грі ({n}/{max_players}):</b>\n"
            f"{players}\n\n"
            f"⏳ {bar} <b>{rem}с</b>"
        )

    def _format_members_comma_separated_html(self, pairs) -> str:
        """Список через кому для реєстрації / таймера (VIP + преміум-емодзі після emoji_to_premium)."""
        if not pairs:
            return "Поки ніхто"
        return ", ".join(self._vip_player_link_for_roster(uid, name) for uid, name in pairs)

    def _get_alive_roles_info(self, chat_id: int, state: GameState) -> str:
        """Legacy sync helper (kept for compatibility)."""
        return ""

    async def _get_alive_roles_info_async(self, chat_id: int, state: GameState) -> str:
        """Асинхронно отримати інформацію про живих гравців з ролями (без імен)."""
        try:
            roster = state.all_membersNames if state.all_membersNames else state.membersNames
            if not roster:
                return ""

            alive_roles = []
            for player_id, _ in roster:
                result = await self._db_fetchone(
                    "SELECT role, killed FROM users WHERE id = %s",
                    (player_id,),
                )
                if result:
                    role_name = result[0] if result[0] else "Невідома роль"
                    killed = result[1] if len(result) > 1 else 0
                    if killed == 0:
                        alive_roles.append(role_name)

            if not alive_roles:
                return ""

            from collections import Counter
            role_counts = Counter(alive_roles)

            civilians_count = role_counts.get("Мирний житель", 0)
            all_capone_count = role_counts.get("Аль Капоне", 0)
            mafia_count = role_counts.get("Мафія", 0)
            doctor_count = role_counts.get("Лікар", 0)

            main_roles = {"Мирний житель", "Аль Капоне", "Мафія", "Лікар"}
            other_roles_parts = [
                f"{role}: {count}" for role, count in sorted(role_counts.items())
                if role not in main_roles and count > 0
            ]

            roles_parts = []
            if civilians_count > 0:
                roles_parts.append(f"Мирні жителі: {civilians_count}")
            if all_capone_count > 0:
                roles_parts.append(f"Аль Капоне: {all_capone_count}")
            if mafia_count > 0:
                roles_parts.append(f"Мафія: {mafia_count}")
            if doctor_count > 0:
                roles_parts.append(f"Лікар: {doctor_count}")
            if other_roles_parts:
                roles_parts.append(", ".join(other_roles_parts))

            roles_text = ", ".join(roles_parts)
            return f"<blockquote>{roles_text}</blockquote>"
        except Exception as e:
            self.print_log(f"Error getting alive roles info (async): {e}")
            return ""


    async def voiting_function(self, message: Message, bot: Bot, membersList, chat_id: int):
        state = self._get_state(chat_id)
        state.membersList = membersList
        list_of_candidates_buttons = InlineKeyboardBuilder()

        try:
            # Filter out dead players
            alive_players = []
            for candidate_id in state.membersList:
                killed_result = await self._db_fetchone(
                    "SELECT killed FROM users WHERE id = %s",
                    (candidate_id,),
                )
                if killed_result and killed_result[0] == 0:  # Player is alive
                    alive_players.append(candidate_id)
            
            if len(alive_players) < 2:
                await message.answer(
                    emoji_to_premium(PLAY_ALERT_NOT_ENOUGH_ALIVE_FOR_VOTE, skip_vip_badges=False),
                    parse_mode="html",
                )
                return
            
            # Хто має проголосувати (живі, не в мовці) - для раннього завершення, коли всі проголосують
            state.expected_voter_ids = set()
            # Send voting interface only to alive players (exclude silenced)
            item_processor = ItemEffectProcessor(chat_id)
            underground_taxi_used = getattr(state, "underground_taxi_used_this_game", set())
            for voter_id in alive_players:
                if voter_id in state.silenced_ids:
                    continue
                # Якщо за гравця вже зараховано голос (напр. автодобір), ПП-кнопки не надсилаємо.
                if voter_id in state.voted_users:
                    continue
                state.expected_voter_ids.add(voter_id)
                voter_kb = InlineKeyboardBuilder()
                for candidate_id in alive_players:
                    if candidate_id == voter_id:
                        continue  # не показуємо самого себе в списку кандидатів
                    result = await self._db_fetchone(
                        "SELECT tg_name FROM users WHERE id = %s",
                        (candidate_id,),
                    )
                    if result:
                        voter_kb.button(text=result[0], callback_data=f"vote_{candidate_id}")
                voter_kb.button(text="⏭️ Пропустити", callback_data="vote_skip")
                if item_processor.can_escape_voting(voter_id) and voter_id not in underground_taxi_used:
                    _esc_cid = custom_emoji_id_for_symbol("🚗")
                    if _esc_cid:
                        voter_kb.button(
                            text="Втекти з голосування",
                            callback_data="vote_escape",
                            icon_custom_emoji_id=_esc_cid,
                        )
                    else:
                        voter_kb.button(text="🚗 Втекти з голосування", callback_data="vote_escape")
                voter_kb.adjust(1)
                try:
                    state.message_list_of_candidates[voter_id] = await bot.send_message(
                        chat_id=voter_id,
                        text="Обери за кого ти проголосуєш:",
                        reply_markup=voter_kb.as_markup()
                    )
                except Exception as e:
                    self.print_log(f"Error sending vote message to {voter_id}: {e}")

            # Handler is already registered in __init__, no need to register again
        
        except Exception as e:
            self.print_log(f"Error in voiting_function: {e}")
            await message.answer(f"Помилка при створенні голосування: {str(e)}")

    async def chosen_candidate_handler(self, callback: CallbackQuery, bot: Bot):
        user_id = callback.from_user.id
        callback_data = callback.data
        
        # Find the chat_id where this user is playing
        # Since voting happens in private messages, we need to find the group chat_id
        chat_id = None
        for active_chat_id in game_state_manager.get_all_active_chats():
            state = self._get_state(active_chat_id)
            if user_id in state.membersList:
                chat_id = active_chat_id
                break
        
        if not chat_id:
            await callback.answer(PLAY_ALERT_NO_ACTIVE_GAME_JOIN, show_alert=True)
            return
        
        state = self._get_state(chat_id)

        # Якщо гра вже завершена або зараз не день/голосування - блокуємо кнопку
        if not state.game_active:
            await callback.answer(PLAY_ALERT_PARTY_OVER, show_alert=True)
            return
        if not getattr(state, "day_active", False):
            await callback.answer(PLAY_ALERT_VERDICT_WRONG_TIME, show_alert=True)
            return
        if not bool(getattr(state, "day_vote_window_open", False)):
            await callback.answer(PLAY_ALERT_VERDICT_WRONG_TIME, show_alert=True)
            return
        # Голосування за страту з ПП дозволене лише після офіційного старту (voting_start_time),
        # інакше під час обговорення спрацьовують застарілі кнопки з минулого раунду.
        voting_start = getattr(state, "voting_start_time", None)
        if not voting_start:
            await callback.answer(PLAY_ALERT_VERDICT_WRONG_TIME, show_alert=True)
            return
        # Голосування триває AFK_AUTO_CHOICE_TOTAL_SECONDS - відхиляємо голоси після часу
        if (datetime.now() - voting_start).total_seconds() > AFK_AUTO_CHOICE_TOTAL_SECONDS:
            await callback.answer(PLAY_ALERT_DAY_VOTE_45_EXPIRED, show_alert=True)
            return
        expected_voters = getattr(state, "expected_voter_ids", set()) or set()
        if expected_voters and user_id not in expected_voters:
            await callback.answer(PLAY_ALERT_VERDICT_WRONG_TIME, show_alert=True)
            return

        # Validate user is alive and in game
        if user_id not in state.membersList:
            await callback.answer(PLAY_ALERT_STRANGER_NOT_ON_LIST, show_alert=True)
            return
        
        # Втеча з голосування (баф) — лише кнопка «Втекти з голосування»
        if callback_data == "vote_escape":
            item_processor = ItemEffectProcessor(chat_id)
            underground_taxi_used = getattr(state, "underground_taxi_used_this_game", set())
            if item_processor.can_escape_voting(user_id) and user_id not in underground_taxi_used:
                if not try_consume_buff(chat_id, user_id, "underground_taxi"):
                    await callback.answer(
                        "⛔️ Немає зарядів для цієї дії.",
                        show_alert=True,
                    )
                    return
                state.underground_taxi_used_this_game.add(user_id)
                state.voted_users.add(user_id)  # щоб голосування могло завершитись одразу, коли всі вже зробили вибір
                state.day_voting_participants.add(user_id)
                try:
                    await callback.answer()
                except Exception:
                    pass
                if user_id in state.message_list_of_candidates:
                    try:
                        await state.message_list_of_candidates[user_id].delete()
                        del state.message_list_of_candidates[user_id]
                    except Exception:
                        pass
                return
            try:
                await callback.answer()
            except Exception:
                pass
            return
        if user_id in state.silenced_ids:
            await callback.answer(PLAY_ALERT_SILENCED_CANNOT_VOTE, show_alert=True)
            return
        
        killed_result = await self._db_fetchone(
            "SELECT killed FROM users WHERE id = %s",
            (user_id,),
        )
        if killed_result and killed_result[0] == 1:
            await callback.answer(PLAY_ALERT_DEAD_SILENT, show_alert=True)
            return

        hide_dead_roles, hide_killer_roles, secret_voting, show_night_targets = await self._get_thematic_settings_async(chat_id, state)

        if user_id in state.voted_users:
            await callback.answer(PLAY_ALERT_ALREADY_VOTED_THIS_ROUND, show_alert=True)
            return

        # Обробка пропуску голосування
        if callback_data == "vote_skip":
            state.voted_users.add(user_id)  # Відмічаємо, що гравець "проголосував" (пропустив)
            state.day_voting_participants.add(user_id)
            
            # Видаляємо повідомлення про голосування
            if user_id in state.message_list_of_candidates:
                try:
                    await state.message_list_of_candidates[user_id].delete()
                    del state.message_list_of_candidates[user_id]
                except Exception as e:
                    self.print_log(f"Помилка видалення повідомлення про голосування для {user_id}: {e}")
                    try:
                        await state.message_list_of_candidates[user_id].edit_text(
                            text="Обери за кого ти проголосуєш:\n⏭️ Ти пропустив голосування"
                        )
                    except:
                        pass
            
            voter_result = await self._db_fetchone(
                "SELECT tg_name FROM users WHERE id = %s",
                (user_id,),
            )
            voter_name = voter_result[0] if voter_result else "Невідомий"
            
            if chat_id:
                try:
                    voter_link = vip_mod.html_user_link(user_id, voter_name)
                    log_msg = await bot.send_message(
                        chat_id=chat_id,
                        text=emoji_to_premium(f"{voter_link} пропустив голосування", skip_vip_badges=False),
                        parse_mode="html",
                    )
                    state.voting_log_messages.append(log_msg)
                except:
                    pass
            
            await callback.answer("Голосування пропущено ⏭️")
            return
        
        # Обробка вибору кандидата
        try:
            candidate_id = int((callback_data or "").split("_", 1)[1])
        except Exception:
            await callback.answer(PLAY_ALERT_VOTE_STALE_OR_INVALID, show_alert=True)
            return

        # Validate candidate is alive
        candidate_killed_result = await self._db_fetchone(
            "SELECT killed FROM users WHERE id = %s",
            (candidate_id,),
        )
        if candidate_killed_result and candidate_killed_result[0] == 1:
            await callback.answer(PLAY_ALERT_DO_NOT_VOTE_DEAD, show_alert=True)
            return

        if user_id == candidate_id:
            await callback.answer(PLAY_ALERT_CANNOT_VOTE_SELF, show_alert=True)
            return

        state.voted_users.add(user_id)
        state.day_voting_participants.add(user_id)

        try:
            candidate_result = await self._db_fetchone(
                "SELECT tg_name FROM users WHERE id = %s",
                (candidate_id,),
            )
            candidate_name = candidate_result[0] if candidate_result else "Невідомий"

            voter_result = await self._db_fetchone(
                "SELECT tg_name FROM users WHERE id = %s",
                (user_id,),
            )
            voter_name = voter_result[0] if voter_result else "Невідомий"

            # Портал: Київський смак - голос проти того, хто пригостив, не рахується
            portal_kyiv = getattr(state, "portal_kyiv_taste", {})
            if portal_kyiv.get(user_id) == candidate_id:
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text="🍰 <b>Київський смак</b>: ти прийняв підкуп - твій голос проти цього гравця не зараховано.",
                        parse_mode="html",
                    )
                except Exception:
                    pass
                if user_id in state.message_list_of_candidates:
                    try:
                        await state.message_list_of_candidates[user_id].delete()
                        del state.message_list_of_candidates[user_id]
                    except Exception:
                        pass
                await callback.answer("Голос не зараховано (Київський смак).", show_alert=True)
                return

            # Видаляємо повідомлення про голосування після голосування
            if user_id in state.message_list_of_candidates:
                try:
                    await state.message_list_of_candidates[user_id].delete()
                    del state.message_list_of_candidates[user_id]
                except Exception as e:
                    self.print_log(f"Помилка видалення повідомлення про голосування для {user_id}: {e}")
                    # Якщо не вдалося видалити, хоча б редагуємо
                    try:
                        candidate_link = vip_mod.html_user_link(candidate_id, candidate_name)
                        await state.message_list_of_candidates[user_id].edit_text(
                            text=f"{candidate_link}\n\n Ти вибрав цього гравця",
                            parse_mode="html"
                        )
                    except:
                        pass

            # Лог у групі: хто проголосував; при таємному голосуванні не показуємо, за кого саме
            if chat_id:
                try:
                    voter_link = vip_mod.html_user_link(user_id, voter_name)
                    if secret_voting:
                        # Таємне голосування: показуємо тільки факт голосу, без цілі
                        text = f"🗳 {voter_link} проголосував(ла) за…"
                    else:
                        candidate_link = vip_mod.html_user_link(candidate_id, candidate_name)
                        text = f"🗳 {voter_link} проголосував(ла) за страту {candidate_link}."
                    log_msg = await bot.send_message(
                        chat_id=chat_id,
                        text=emoji_to_premium(text, skip_vip_badges=False),
                        parse_mode="html"
                    )
                    # Зберігаємо, щоб видалити всі такі повідомлення після підрахунку голосів
                    state.voting_log_messages.append(log_msg)
                except Exception as e:
                    self.print_log(f"Помилка надсилання лог-повідомлення про голосування: {e}")

            await self._db_execute_commit(
                "UPDATE users SET votes = votes + 1 WHERE id = %s",
                (candidate_id,),
            )

            await callback.answer("Голос зараховано! ")
        
        except Exception as e:
            self.print_log(f"Error in chosen_candidate_handler: {e}")
            await callback.answer(f"Помилка при обробці голосування: {str(e)}", show_alert=True)



    async def results_def(self, message: Message, bot: Bot, chat_id: int):
        """Process voting results and execute the lynched player"""
        state = self._get_state(chat_id)
        # Дозволити наступному дню знову показати «Голосування розпочато!»
        state.voting_start_message_sent = False
        # Закриваємо вікно денного голосування ДО будь-яких очисток, щоб пізні callback-и не зараховувались.
        state.day_vote_window_open = False
        # Закриваємо вікно денного голосування за страту (і блокуємо застарілі vote_* у ПП під час 👍/👎 тощо).
        state.voting_start_time = None
        state.afk_day_auto_choice_applied = False
        state.list_of_all_votes.clear()
        
        # Очищаємо лог-повідомлення про голосування ("X проголосував(ла) за Y")
        if getattr(state, "voting_log_messages", None):
            for msg in state.voting_log_messages:
                try:
                    await msg.delete()
                except Exception:
                    pass
            state.voting_log_messages.clear()
        
        # Обробка предметів: зменшення голосів
        item_processor = ItemEffectProcessor(chat_id)
        vote_reductions = {}  # {player_id: reduction_amount}
        for player_id in state.membersList:
            reduction = item_processor.get_vote_reduction(player_id)
            if reduction > 0:
                vote_reductions[player_id] = reduction
        
        # Collect votes for alive players only
        candy_used = getattr(state, "candy_used_this_game", set())
        for player_id in state.membersList:
            result = await self._db_fetchone(
                "SELECT votes, killed FROM users WHERE id = %s",
                (player_id,),
            )
            if result:
                votes, killed = result
                if killed == 0:  # Only count alive players
                    vote_count = votes[0] if isinstance(votes, tuple) else votes
                    # Застосовуємо зменшення голосів від предметів (Кепка) - один раз за гру списується один заряд
                    if player_id in vote_reductions and vote_reductions[player_id] > 0:
                        if try_consume_buff(chat_id, player_id, "cap"):
                            vote_count = max(0, vote_count - vote_reductions[player_id])
                            self.print_log(f"🧢 Кепка з козирком зменшила голоси проти {player_id} на {vote_reductions[player_id]}")
                    # Цукерка: перший голос проти тебе не рахується (1 раз за гру)
                    if item_processor.should_ignore_first_vote(player_id) and player_id not in candy_used and vote_count > 0:
                        if try_consume_buff(chat_id, player_id, "candy"):
                            vote_count = max(0, vote_count - 1)
                            state.candy_used_this_game.add(player_id)
                            self.print_log(f"🍬 Цукерка зменшила голоси проти {player_id} на 1")
                    state.list_of_all_votes.append((player_id, vote_count))
        
        if not state.list_of_all_votes:
            await message.answer(
                emoji_to_premium(PLAY_ALERT_NO_VOTE_CANDIDATES, skip_vip_badges=False),
                parse_mode="html",
            )
            return
        
        # Sort by votes (descending)
        state.list_of_all_votes.sort(key=lambda x: x[1], reverse=True)
        
        # Get highest vote count
        max_votes = state.list_of_all_votes[0][1]
        
        # Загальна кількість голосів за кандидатів (кожен голос "за X" = +1 до суми)
        total_votes_cast = sum(v for _, v in state.list_of_all_votes)
        # Скільки гравців проголосували за пропуск (всі хто голосував, мінус ті хто голосував за когось)
        skip_count = len(state.voted_users) - total_votes_cast
        
        # Якщо всі пропустили (max_votes == 0) АБО більшість за пропуск (skip_count >= max_votes) - нікого не вішаємо
        if max_votes == 0:
            await message.answer(
                "Жителі міста так і не обрали, кого стратити.\n\n"
                "🌙 Гра продовжується, переходимо до ночі...",
                parse_mode="html"
            )
            # Очищаємо голоси для наступного раунду
            await self._db_execute_commit(
                "UPDATE users SET votes = %s WHERE id IN %s",
                (0, tuple(state.membersList) if state.membersList else (None,)),
            )
            state.voted_users.clear()
            # Переходимо до ночі
            state.night_number += 1
            await self.night_function(message, bot)
            return
        
        if skip_count >= max_votes:
            # Більшість або нічия на користь пропуску: більше (або стільки ж) голосів за пропуск, ніж за будь-якого кандидата
            await message.answer(
                "Жителі міста так і не обрали, кого стратити.\n\n"
                "🌙 Гра продовжується, переходимо до ночі...",
                parse_mode="html"
            )
            await self._db_execute_commit(
                "UPDATE users SET votes = %s WHERE id IN %s",
                (0, tuple(state.membersList) if state.membersList else (None,)),
            )
            state.voted_users.clear()
            state.night_number += 1
            await self.night_function(message, bot)
            return
        
        # Check for ties
        tied_candidates = [player_id for player_id, votes in state.list_of_all_votes if votes == max_votes]
        
        if len(tied_candidates) > 1:
            # Нічия - не вішаємо нікого
            await message.answer(
                "Жителі міста не змогли визначитися - голоси розділилися порівну.\n\n"
                "🌙 Гра продовжується, переходимо до ночі...",
                parse_mode="html"
            )
            # Очищаємо голоси для наступного раунду
            await self._db_execute_commit(
                "UPDATE users SET votes = %s WHERE id IN %s",
                (0, tuple(state.membersList) if state.membersList else (None,)),
            )
            state.voted_users.clear()
            # Переходимо до ночі
            state.night_number += 1
            await self.night_function(message, bot)
            return
        
        # Підпільне таксі: гравець не може бути повішений, якщо він втік
        underground_taxi_escaped = getattr(state, "underground_taxi_used_this_game", set())
        lynched_id = None
        for pid, _ in state.list_of_all_votes:
            if pid not in underground_taxi_escaped:
                lynched_id = pid
                break
        if lynched_id is None:
            # Усі кандидати з голосу втекли (баф) — нікого не вішаємо
            await message.answer(
                emoji_to_premium(
                    "⚠️ <b>Ніхто не лишився під вироком.</b>\n\n"
                    "Усі, на кого припали голоси, скористалися втечею з голосування.\n\n"
                    "<b>Нікого не страчено.</b>\n\n"
                    "🌙 <i>Гра продовжується, переходимо до ночі...</i>",
                    skip_vip_badges=False,
                ),
                parse_mode="html",
            )
            await self._db_execute_commit(
                "UPDATE users SET votes = %s WHERE id IN %s",
                (0, tuple(state.membersList) if state.membersList else (None,)),
            )
            state.voted_users.clear()
            state.night_number += 1
            await self.night_function(message, bot)
            return
        
        # Get lynched player info
        lynched_result = await self._db_fetchone(
            "SELECT tg_name, role FROM users WHERE id = %s",
            (lynched_id,),
        )
        if not lynched_result:
            await message.answer(
                " <b>Помилка</b> \n\n"
                "Не знайдено гравця для страти!\n\n"
                "💡 <i>Гра продовжується...</i>",
                parse_mode="html"
            )
            return
        
        lynched_name, lynched_role = lynched_result
        
        # Зберігаємо кандидата для додаткового голосування
        state.lynched_candidate_id = lynched_id
        state.lynched_candidate_name = lynched_name
        state.lynched_candidate_role = lynched_role
        state.hanging_vote_yes.clear()
        state.hanging_vote_no.clear()
        # Видаляємо всі приватні повідомлення про голосування
        for voter_id, msg in state.hanging_vote_private_messages.items():
            try:
                await msg.delete()
            except:
                pass
        state.hanging_vote_private_messages.clear()
        state.like = 0
        state.dislike = 0
        
        # Надсилаємо повідомлення з кнопками 👍/👎 для всіх живих гравців (окрім кандидата)
        alive_voters = []
        for player_id in state.membersList:
            if player_id == lynched_id:
                continue  # Пропускаємо кандидата
            killed_result = await self._db_fetchone(
                "SELECT killed FROM users WHERE id = %s",
                (player_id,),
            )
            if killed_result and killed_result[0] == 0:  # Тільки живі
                alive_voters.append(player_id)
        
        # Підготуємо тег-кандидата
        candidate_link = vip_mod.html_user_link(lynched_id, lynched_name)
        
        # Надсилаємо повідомлення в групу
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"👍  ({state.like})", callback_data="like")],
            [InlineKeyboardButton(text=f"👎  ({state.dislike})", callback_data="dislike")]
        ])
        
        # Час фінального голосування (налаштовується адмінами, мін 20 сек, макс 3 хв)
        vote_duration = await self._get_hanging_vote_time_async(chat_id)
        
        _hanging_intro = (
            f"👤 Кандидат: {candidate_link}\n\n"
            f"⏳ Час на голосування: {vote_duration} секунд"
        )
        state.hanging_vote_message = await message.answer(
            emoji_to_premium(_hanging_intro, skip_vip_badges=False),
            reply_markup=keyboard,
            parse_mode="html",
        )
        
        # Надсилаємо повідомлення в приватні повідомлення всім живим гравцям (окрім кандидата та заблокованих)
        for voter_id in alive_voters:
            # Пропускаємо заблокованих гравців
            if voter_id in state.silenced_ids:
                continue
            try:
                group_url = self._group_chat_link(chat_id, getattr(state.hanging_vote_message, "message_id", None))
                vote_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Проголосувати!", url=group_url)]
                ])
                _pv_hanging = (
                    f"{candidate_link}\n\n"
                    f"⬇️ <b>Перейди в групу та проголосуй:</b> ⬇️"
                )
                msg = await bot.send_message(
                    chat_id=voter_id,
                    text=emoji_to_premium(_pv_hanging, skip_vip_badges=False),
                    parse_mode="html",
                    reply_markup=vote_keyboard,
                )
                state.hanging_vote_private_messages[voter_id] = msg
            except Exception as e:
                self.print_log(f"Error sending hanging vote message to {voter_id}: {e}")
        
        # Зберігаємо час початку голосування
        state.hanging_vote_start_time = datetime.now()
        
        # Запускаємо таймер для підрахунку голосів
        asyncio.create_task(self._hanging_vote_timer(message, bot, chat_id, lynched_id))
        
        # Не продовжуємо виконання - чекаємо на таймер
        return

    async def _hanging_vote_timer(self, message: Message, bot: Bot, chat_id: int, lynched_id: int):
        """Таймер для підрахунку голосів про повішення (оновлення повідомлення кожні 10 секунд)"""
        state = self._get_state(chat_id)
        vote_duration = await self._get_hanging_vote_time_async(chat_id)
        
        # Оновлюємо повідомлення кожні 10 секунд (відлік внутрішньо йде по секундах)
        for remaining in range(vote_duration - 1, 0, -1):
            await asyncio.sleep(1)
            
            # Перевіряємо, чи гра все ще активна
            state = self._get_state(chat_id)
            if not state.game_active:
                return
            # Кандидат змінився/скасований (наприклад, гравець вийшов із гри) - зупиняємо застарілий таймер.
            if getattr(state, "lynched_candidate_id", 0) != lynched_id:
                return
            
            # Оновлюємо повідомлення тільки кожні 10 секунд (remaining 40, 30, 20, 10)
            should_update = (remaining % 10 == 0)
            
            # Оновлюємо повідомлення з таймером
            if state.hanging_vote_message and should_update:
                try:
                    # Отримуємо поточні голоси
                    yes_count = len(state.hanging_vote_yes)
                    no_count = len(state.hanging_vote_no)
                    
                    # Отримуємо ім'я кандидата
                    lynched_result = await self._db_fetchone(
                        "SELECT tg_name FROM users WHERE id = %s",
                        (lynched_id,),
                    )
                    lynched_name = lynched_result[0] if lynched_result else "Гравець"
                    candidate_link = vip_mod.html_user_link(lynched_id, lynched_name)
                    
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=f"👍({yes_count})", callback_data="like")],
                        [InlineKeyboardButton(text=f"👎 ({no_count})", callback_data="dislike")]                    ])
                    
                    _hv_body = (
                        f"👤 Кандидат: {candidate_link}\n\n"
                        f"⏳ Час на голосування: {remaining} секунд"
                    )
                    await state.hanging_vote_message.edit_text(
                        emoji_to_premium(_hv_body, skip_vip_badges=False),
                        reply_markup=keyboard,
                        parse_mode="html",
                    )
                except TelegramRetryAfter as e:
                    # Обробка flood control - чекаємо потрібний час
                    self.print_log(f"⚠️ Flood control: чекаємо {e.retry_after} секунд")
                    await asyncio.sleep(e.retry_after)
                    # Після очікування спробуємо оновити ще раз
                    try:
                        state = self._get_state(chat_id)
                        if state.hanging_vote_message and state.game_active:
                            yes_count = len(state.hanging_vote_yes)
                            no_count = len(state.hanging_vote_no)
                            lynched_result = await self._db_fetchone(
                                "SELECT tg_name FROM users WHERE id = %s",
                                (lynched_id,),
                            )
                            lynched_name = lynched_result[0] if lynched_result else "Гравець"
                            candidate_link = vip_mod.html_user_link(lynched_id, lynched_name)
                            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text=f"👍({yes_count})", callback_data="like")],
                                [InlineKeyboardButton(text=f"👎({no_count})", callback_data="dislike")]
                            ])
                            _hv_body_retry = (
                                f"👤 Кандидат: {candidate_link}\n\n"
                                f"⏳ Час на голосування: {remaining} секунд"
                            )
                            await state.hanging_vote_message.edit_text(
                                emoji_to_premium(_hv_body_retry, skip_vip_badges=False),
                                reply_markup=keyboard,
                                parse_mode="html",
                            )
                    except Exception:
                        pass
                except Exception:
                    pass
        
        # Чекаємо останню секунду
        await asyncio.sleep(1)
        
        state = self._get_state(chat_id)
        
        # Перевіряємо, чи гра все ще активна
        if not state.game_active:
            return
        if getattr(state, "lynched_candidate_id", 0) != lynched_id:
            return
        
        # Після завершення таймера видаляємо повідомлення з кнопками фінального голосування
        if state.hanging_vote_message:
            try:
                await state.hanging_vote_message.delete()
            except Exception:
                pass
            state.hanging_vote_message = None
        
        # Підраховуємо голоси
        yes_votes = len(state.hanging_vote_yes)
        no_votes = len(state.hanging_vote_no)
        
        # Рахуємо скільки гравців МАЛИ ПРАВО голосу (живі, не кандидат, не заглушені)
        eligible_voters = 0
        for player_id in state.membersList:
            if player_id == lynched_id:
                continue
            if player_id in state.silenced_ids:
                continue
            r = await self._db_fetchone(
                "SELECT killed FROM users WHERE id = %s",
                (player_id,),
            )
            if r and r[0] == 0:
                eligible_voters += 1
        
        voted_count = yes_votes + no_votes
        abstained_count = max(eligible_voters - voted_count, 0)
        
        # Отримуємо інформацію про кандидата
        lynched_result = await self._db_fetchone(
            "SELECT tg_name, role FROM users WHERE id = %s",
            (lynched_id,),
        )
        if not lynched_result:
            return
        lynched_name, lynched_role = lynched_result
        
        # Зберігаємо інформацію про те, чи був повішений Камікадзе (для використання пізніше)
        kamikaze_was_lynched = False
        
        # Вирішуємо, чи вбивати:
        # 1) «За повішення» має бути більше, ніж «Проти» (більшість)
        # 2) Якщо 50/50 (yes_votes == no_votes) - не вішаємо
        # 3) Хтось взагалі проголосував
        #
        # Голос більшості - вішають того, за кого більшість (в разі нічиї - не вішають)
        if yes_votes > no_votes and voted_count > 0:
            # Спочатку перевіряємо пасивний баф «Чорний Опель» - автоматичне спасіння від першої страти
            item_processor = ItemEffectProcessor(chat_id)
            black_opel_used = getattr(state, "black_opel_used_this_game", set())
            # Самогубець свідомо йде на страту - Опель не рятує від «власної» страти
            if (
                lynched_id not in black_opel_used
                and lynched_role != "Самогубець"
                and getattr(state, "suicide_id", 0) != lynched_id
                and item_processor.should_prevent_lynch(lynched_id)
                and try_consume_buff(chat_id, lynched_id, "black_opel")
            ):
                lynched_link = vip_mod.html_user_link(lynched_id, lynched_name)
                try:
                    await message.answer(
                        emoji_to_premium(
                            "Коли натовп уже затягував зашморг, біля шибениці різко загальмувала чорна машина.\n"
                            f"{lynched_link} зник у темному провулку.\n\n"
                        ),
                        parse_mode="html",
                    )
                except TelegramRetryAfter as e:
                    self.print_log(f"⚠️ Flood control при відправці результату (Чорний Опель): чекаємо {e.retry_after} секунд")
                    await asyncio.sleep(e.retry_after)
                    await message.answer(
                        emoji_to_premium(
                            "Коли натовп уже затягував зашморг, біля шибениці різко загальмувала чорна машина.\n"
                            f"{lynched_link} зник у темному провулку.\n\n"
                        ),
                        parse_mode="html",
                    )
                # Позначаємо, що в цій грі баф уже врятував цього гравця
                black_opel_used.add(lynched_id)
                state.black_opel_used_this_game = black_opel_used

                # Врятований не вважається «вбитим» - останнє слово для нього недоступне
                self._ensure_last_word_queue(state)
                self._ensure_last_word_allowed_ids(state)
                state.last_word_queue = [(uid, kd) for uid, kd in state.last_word_queue if uid != lynched_id]
                state.last_word_allowed_ids.discard(lynched_id)
                if state.victim_id == lynched_id:
                    state.victim_id = next(iter(state.last_word_allowed_ids), 0)
                    state.is_last_message = bool(state.last_word_allowed_ids)

                # Скидаємо голоси і продовжуємо гру без страти
                await self._db_execute_commit(
                    "UPDATE users SET votes = %s WHERE id IN %s",
                    (0, tuple(state.membersList) if state.membersList else (None,)),
                )
                state.voted_users.clear()
                winner = await self.check_win_conditions_async(chat_id)
                if not winner:
                    state.night_number += 1
                    await self.night_function(message, bot)
                else:
                    await self._handle_game_end(message, bot, chat_id, winner)
                return

            if lynched_id in getattr(state, "devil_covenant_day_shield", set()):
                lynched_link = vip_mod.html_user_link(lynched_id, lynched_name)
                try:
                    await message.answer(
                        emoji_to_premium(
                            f"💥 <b>Контракт з дияволом</b>\n\n"
                            f"Натовп тягне зашморг - але ніщо не лишає сліду на {lynched_link}.\n"
                            f"«Угода старіша за ваші закони.»\n\n"
                            f"<b>Страта не відбулася.</b>"
                        ),
                        parse_mode="html",
                    )
                except TelegramRetryAfter as e:
                    self.print_log(f"⚠️ Flood control (контракт / страта): чекаємо {e.retry_after} секунд")
                    await asyncio.sleep(e.retry_after)
                    await message.answer(
                        emoji_to_premium(
                            f"💥 <b>Контракт з дияволом</b>\n\n"
                            f"Страта {lynched_link} не відбулася."
                        ),
                        parse_mode="html",
                    )
                self._ensure_last_word_queue(state)
                self._ensure_last_word_allowed_ids(state)
                state.last_word_queue = [(uid, kd) for uid, kd in state.last_word_queue if uid != lynched_id]
                state.last_word_allowed_ids.discard(lynched_id)
                if state.victim_id == lynched_id:
                    state.victim_id = next(iter(state.last_word_allowed_ids), 0)
                    state.is_last_message = bool(state.last_word_allowed_ids)
                await self._db_execute_commit(
                    "UPDATE users SET votes = %s WHERE id IN %s",
                    (0, tuple(state.membersList) if state.membersList else (None,)),
                )
                state.voted_users.clear()
                winner = await self.check_win_conditions_async(chat_id)
                if not winner:
                    state.night_number += 1
                    await self.night_function(message, bot)
                else:
                    await self._handle_game_end(message, bot, chat_id, winner)
                return

            # Вбиваємо гравця (якщо баф не спрацював)
            lynched_link = vip_mod.html_user_link(lynched_id, lynched_name)
            try:
                # Перше повідомлення: кого стратили
                await message.answer(
                    emoji_to_premium(f"⚖️ <b>За результатами голосування було страчено</b> {lynched_link}"),
                    parse_mode="html",
                )
                # Друге повідомлення: його роль
                await message.answer(
                    emoji_to_premium(f"🃏 Він був: <b>{lynched_role}</b>"),
                    parse_mode="html",
                )
            except TelegramRetryAfter as e:
                self.print_log(f"⚠️ Flood control при відправці результату: чекаємо {e.retry_after} секунд")
                await asyncio.sleep(e.retry_after)
                await message.answer(
                    emoji_to_premium(f"⚖️ <b>За результатами голосування було страчено</b> {lynched_link}"),
                    parse_mode="html",
                )
                await message.answer(
                    emoji_to_premium(f"🃏 Він був: <b>{lynched_role}</b>"),
                    parse_mode="html",
                )
            await self._kill_player(lynched_id, bot, message, chat_id)

            # Галас у казино: Комісар/Сержант усунуто до 3-го дня
            if lynched_role in ("Комісар Каттані", "Сержант") and state.night_number <= 3:
                state.commissioner_lynched_on_day = state.night_number
            
            # Suicide win condition - встановлюємо прапорець, але гра продовжується
            if lynched_role == "Самогубець":
                state.suicide_was_lynched = True
                try:
                    await bot.send_message(
                        chat_id=lynched_id,
                        text="🏍️Тобі вдалося всіх обманути, та померти. Твоя душа відправляється в кращий світ(або ж ні? Самогубць в рай не пускають).",
                    )
                except Exception as e:
                    self.print_log(f" Помилка надсилання повідомлення Самогубцю {lynched_id}: {e}")
                # Самогубець одразу вважається переможцем, але гра продовжується для інших гравців
                # Перемога самогубця буде визначена в кінці гри, коли гра дійсно закінчиться

            # Kamikaze ability - тільки при повішанні вдень
            if lynched_role == "Камікадзе":
                kamikaze_was_lynched = True
                # Встановлюємо стан для відстеження вибору Камікадзе
                state.kamikaze_target_id = 0
                state.kamikaze_choice_made = False
                state.kamikaze_lynched_id = lynched_id  # Зберігаємо ID повішеного Камікадзе
                await self.kamikaze_choice(bot, chat_id, lynched_id)
            
            # Reset votes for next round
            await self._db_execute_commit(
                "UPDATE users SET votes = %s WHERE id IN %s",
                (0, tuple(state.membersList) if state.membersList else (None,)),
            )
            state.voted_users.clear()
            
            # Check win conditions after lynching
            # Якщо самогубця повісили - гра ПРОДОВЖУЄТЬСЯ для інших гравців
            # Самогубець вже вважається переможцем, але гра триває до повного завершення
            winner = await self.check_win_conditions_async(chat_id)

            # Додаткова перевірка безпеки:
            # якщо Дона вже немає і немає жодного живого гравця з роллю «Мафія»,
            # вважаємо, що мафія повністю знищена і мирні перемогли  - 
            # але тільки якщо не залишився живий Маніяк (він грає окремо і гра має продовжитись).
            if not winner and state.all_capone_id == 0 and not state.mafia_ids:
                has_alive_maniac = False
                for pid in (state.membersList or []):
                    row = await self._db_fetchone(
                        "SELECT role, killed FROM users WHERE id = %s",
                        (pid,),
                    )
                    if row and row[1] == 0 and row[0] == "Маніяк":
                        has_alive_maniac = True
                        break
                if not has_alive_maniac:
                    winner = "civilians"
            
            # Якщо є переможець (мафія, мирні тощо) - завершуємо гру. Самогубець (якщо повішений) уже входить у список переможців у summary.
            if winner:
                await self._handle_game_end(message, bot, chat_id, winner)
                return
        else:
            # НЕ вбиваємо гравця (немає більшості за повішення або 50/50)
            try:
                await message.answer(
                    emoji_to_premium(
                        f"⚖️ <b>Результат голосування:</b>\n\n"
                        f"Жителі міста так і не дійшли згоди.\n"
                        f"Цього дня ніхто не був страчений."
                    ),
                    parse_mode="html"
                )
            except TelegramRetryAfter as e:
                self.print_log(f"⚠️ Flood control при відправці результату: чекаємо {e.retry_after} секунд")
                await asyncio.sleep(e.retry_after)
                await message.answer(
                    emoji_to_premium(
                        f"⚖️ <b>Результат голосування:</b>\n\n"
                        f"Жителі міста так і не дійшли згоди.\n"
                        f"Цього дня ніхто не був страчений."
                    ),
                    parse_mode="html"
                )
        
        # Очищаємо стан голосування
        state.lynched_candidate_id = 0
        state.lynched_candidate_name = ""
        state.lynched_candidate_role = ""
        state.hanging_vote_yes.clear()
        state.hanging_vote_no.clear()
        # Видаляємо всі приватні повідомлення про голосування
        for voter_id, msg in state.hanging_vote_private_messages.items():
            try:
                await msg.delete()
            except:
                pass
        state.hanging_vote_private_messages.clear()
        # Видаляємо повідомлення про голосування в чаті
        if state.hanging_vote_message:
            try:
                await state.hanging_vote_message.delete()
            except Exception as e:
                self.print_log(f"Помилка видалення повідомлення про голосування: {e}")
        state.hanging_vote_message = None
        state.like = 0
        state.dislike = 0
        
        # Reset votes for next round
        await self._db_execute_commit(
            "UPDATE users SET votes = %s WHERE id IN %s",
            (0, tuple(state.membersList) if state.membersList else (None,)),
        )
        state.voted_users.clear()
        
        # Якщо Камікадзе був повішений - чекаємо на його вибір
        if kamikaze_was_lynched and not state.kamikaze_choice_made:
            # Чекаємо до 30 секунд на вибір Камікадзе
            wait_time = 0
            while wait_time < 30 and not state.kamikaze_choice_made and state.game_active:
                await asyncio.sleep(2)
                wait_time += 2
                state = self._get_state(chat_id)  # Re-get state
            
            # Якщо Камікадзе не зробив вибір за 30 секунд - продовжуємо без вибору
            if not state.kamikaze_choice_made:
                self.print_log(f"⚠️ Камікадзе {state.kamikaze_lynched_id} не зробив вибір за 30 секунд, гра продовжується")
                
                # Відправляємо повідомлення про пропуск вибору
                try:
                    await bot.send_message(
                        chat_id=state.kamikaze_lynched_id,
                        text=(
                            "💥 <b>Взаємодія з відвідуваним гравцем</b> 💥\n"
                            "(Якщо жодного гравця не обрано - Камікадзе пропускає можливість підірвати)\n\n"
                            "💥 Тиша. Лише ти і твоє рішення.\n"
                            "«Можливо, іншого разу…»"
                        ),
                        parse_mode="html"
                    )
                except:
                    pass
                
                # Відправляємо повідомлення про нічний хід в групу
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text="💥 «Разом - на інший світ…»",
                        parse_mode="html"
                    )
                except:
                    pass
                
                # Скидаємо стан, щоб гра продовжилась
                state.kamikaze_choice_made = True
        
        # Continue game loop: wait a bit then go to next night
        await asyncio.sleep(10)
        state = self._get_state(chat_id)  # Re-get state
        if state.game_active and len(state.membersList) >= 2:
            # Повідомлення про перехід до ночі (з retry при flood control)
            for attempt in range(3):
                try:
                    await message.answer(
                        "🌃 Ніч знову опускається на місто… 🌃",
                        parse_mode="html"
                    )
                    break
                except TelegramRetryAfter as e:
                    self.print_log(f"⚠️ Flood control при переході до ночі: чекаємо {e.retry_after} с (спроба {attempt + 1}/3)")
                    await asyncio.sleep(e.retry_after)
            state.night_number += 1
            try:
                await self.night_function(message, bot)
            except TelegramRetryAfter as e:
                self.print_log(f"⚠️ Flood control у night_function: чекаємо {e.retry_after} с, повторний виклик")
                await asyncio.sleep(e.retry_after)
                await self.night_function(message, bot)
                

    async def like_def(self, callback: CallbackQuery, bot: Bot):
        # Find which chat this belongs to
        user_id = callback.from_user.id
        for chat_id in game_state_manager.get_all_active_chats():
            state = game_state_manager.get_state(chat_id)
            
            # Перевіряємо, чи це голосування про повішення
            if state.hanging_vote_message and state.lynched_candidate_id:
                vote_duration = await self._get_hanging_vote_time_async(chat_id)
                if state.hanging_vote_start_time and (datetime.now() - state.hanging_vote_start_time).total_seconds() > vote_duration:
                    await callback.answer(PLAY_ALERT_HANGING_VOTE_EXPIRED, show_alert=True)
                    return
                
                # Перевіряємо, чи гравець взагалі грає (в membersList - живі гравці)
                if user_id not in state.membersList:
                    await callback.answer(PLAY_ALERT_STRANGER_NOT_ON_LIST, show_alert=True)
                    return
                
                # Перевіряємо, чи гравець не є кандидатом
                if user_id == state.lynched_candidate_id:
                    await callback.answer(PLAY_ALERT_CANNOT_VOTE_SELF, show_alert=True)
                    return
                
                # Додаткова перевірка: чи гравець мертвий (на випадок, якщо він був видалений з membersList)
                killed_result = await self._db_fetchone(
                    "SELECT killed FROM users WHERE id = %s",
                    (user_id,),
                )
                if killed_result and killed_result[0] == 1:
                    await callback.answer(PLAY_ALERT_DEAD_SILENT, show_alert=True)
                    return
                
                # Перевіряємо, чи гравець заблокований
                if user_id in state.silenced_ids:
                    await callback.answer(PLAY_ALERT_SILENCED_CANNOT_VOTE, show_alert=True)
                    return
                
                # Логіка зміни голосу:
                # Натискання 👍 завжди означає «за повішення»:
                # прибираємо попередній вибір (якщо був 👎) і ставимо 👍
                state.hanging_vote_yes.discard(user_id)
                state.hanging_vote_no.discard(user_id)
                state.hanging_vote_yes.add(user_id)
                state.day_voting_participants.add(user_id)

                # Поточна кількість голосів після натискання
                yes_count = len(state.hanging_vote_yes)
                no_count = len(state.hanging_vote_no)

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=f"👍({yes_count})", callback_data="like")],
                    [InlineKeyboardButton(text=f"👎({no_count})", callback_data="dislike")]
                ])
                
                # Оновлюємо текст повідомлення з актуальними даними (кандидат з тегом)
                candidate_link = vip_mod.html_user_link(state.lynched_candidate_id, state.lynched_candidate_name)
                
                # Обчислюємо залишковий час з урахуванням налаштувань адмінів
                vote_duration = await self._get_hanging_vote_time_async(chat_id)
                remaining_time = vote_duration
                if state.hanging_vote_start_time:
                    elapsed = (datetime.now() - state.hanging_vote_start_time).total_seconds()
                    remaining_time = max(0, int(vote_duration - elapsed))
                
                message_text = (
                    f"👤 Кандидат: {candidate_link}\n\n"
                    f"⏳ Час на голосування: {remaining_time} секунд"
                )
                
                await state.hanging_vote_message.edit_text(
                    text=emoji_to_premium(message_text, skip_vip_badges=False),
                    reply_markup=keyboard,
                    parse_mode="html",
                )

                # Лог в чаті видалено - не показуємо хто проголосував

                await callback.answer("Твій голос: 👍 (за повішення) ")
                return
            
            # Стара логіка для іншого голосування
            if user_id in state.membersList and state.message_about_voiting:
                state.like += 1
                state.day_voting_participants.add(user_id)
                self.print_log(state.like)

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=f"👍 {state.like}", callback_data="like")],
                    [InlineKeyboardButton(text=f"👎 {state.dislike}", callback_data="dislike")]
                ])

                await state.message_about_voiting.edit_text(
                    text=state.message_about_voiting.text if hasattr(state.message_about_voiting, 'text') else "Голосування",
                    reply_markup=keyboard
                )
                break

    async def dislike_def(self, callback: CallbackQuery, bot: Bot):
        # Find which chat this belongs to
        user_id = callback.from_user.id
        for chat_id in game_state_manager.get_all_active_chats():
            state = game_state_manager.get_state(chat_id)
            
            # Перевіряємо, чи це голосування про повішення
            if state.hanging_vote_message and state.lynched_candidate_id:
                vote_duration = await self._get_hanging_vote_time_async(chat_id)
                if state.hanging_vote_start_time and (datetime.now() - state.hanging_vote_start_time).total_seconds() > vote_duration:
                    await callback.answer(PLAY_ALERT_HANGING_VOTE_EXPIRED, show_alert=True)
                    return
                
                # Перевіряємо, чи гравець взагалі грає (в membersList - живі гравці)
                if user_id not in state.membersList:
                    await callback.answer(PLAY_ALERT_STRANGER_NOT_ON_LIST, show_alert=True)
                    return
                
                # Перевіряємо, чи гравець не є кандидатом
                if user_id == state.lynched_candidate_id:
                    await callback.answer(PLAY_ALERT_CANNOT_VOTE_SELF, show_alert=True)
                    return
                
                # Додаткова перевірка: чи гравець мертвий (на випадок, якщо він був видалений з membersList)
                killed_result = await self._db_fetchone(
                    "SELECT killed FROM users WHERE id = %s",
                    (user_id,),
                )
                if killed_result and killed_result[0] == 1:
                    await callback.answer(PLAY_ALERT_DEAD_SILENT, show_alert=True)
                    return
                
                # Перевіряємо, чи гравець заблокований
                if user_id in state.silenced_ids:
                    await callback.answer(PLAY_ALERT_SILENCED_CANNOT_VOTE, show_alert=True)
                    return
                
                # Логіка зміни голосу:
                # Натискання 👎 завжди означає «проти повішення»:
                # прибираємо попередній вибір (якщо був 👍) і ставимо 👎
                state.hanging_vote_yes.discard(user_id)
                state.hanging_vote_no.discard(user_id)
                state.hanging_vote_no.add(user_id)
                state.day_voting_participants.add(user_id)

                # Поточна кількість голосів після натискання
                yes_count = len(state.hanging_vote_yes)
                no_count = len(state.hanging_vote_no)

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=f"👍({yes_count})", callback_data="like")],
                    [InlineKeyboardButton(text=f"👎({no_count})", callback_data="dislike")]
                ])
                
                # Оновлюємо текст повідомлення з актуальними даними (кандидат з тегом)
                candidate_link = vip_mod.html_user_link(state.lynched_candidate_id, state.lynched_candidate_name)
                
                # Обчислюємо залишковий час з урахуванням налаштувань адмінів
                vote_duration = await self._get_hanging_vote_time_async(chat_id)
                remaining_time = vote_duration
                if state.hanging_vote_start_time:
                    elapsed = (datetime.now() - state.hanging_vote_start_time).total_seconds()
                    remaining_time = max(0, int(vote_duration - elapsed))
                
                message_text = (
                    f"👤 Кандидат: {candidate_link}\n\n"
                    f"⏳ Час на голосування: {remaining_time} секунд"
                )
                
                await state.hanging_vote_message.edit_text(
                    text=emoji_to_premium(message_text, skip_vip_badges=False),
                    reply_markup=keyboard,
                    parse_mode="html",
                )
                # Видаляємо приватне повідомлення про голосування після голосування
                if user_id in state.hanging_vote_private_messages:
                    try:
                        await state.hanging_vote_private_messages[user_id].delete()
                        del state.hanging_vote_private_messages[user_id]
                    except Exception as e:
                        self.print_log(f"Помилка видалення приватного повідомлення про голосування для {user_id}: {e}")

                # Лог в чаті видалено - не показуємо хто проголосував

                await callback.answer("Твій голос: 👎 (проти повішення) ")
                return
            
            # Стара логіка для іншого голосування
            if user_id in state.membersList and state.message_about_voiting:
                state.dislike += 1
                state.day_voting_participants.add(user_id)
                self.print_log(state.dislike)

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=f"👍 {state.like}", callback_data="like")],
                    [InlineKeyboardButton(text=f"👎 {state.dislike}", callback_data="dislike")]
                ])

                await state.message_about_voiting.edit_text(
                    text=state.message_about_voiting.text if hasattr(state.message_about_voiting, 'text') else "Голосування",
                    reply_markup=keyboard
                )
                break

    async def _send_phase_media(self, bot: Bot, chat_id: int, kind: str, caption: str, reply_markup=None) -> bool:
        """Надіслати анімацію фази гри (день/ніч) через send_animation (зациклено, без звуку).
        kind: 'day' | 'night' → шукає Media/<kind>.mp4, потім Media/<kind>.gif.
        Повертає True, якщо надіслано."""
        media_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Media'))
        media_path = None
        for ext in ('mp4', 'gif'):
            p = os.path.join(media_dir, f'{kind}.{ext}')
            if os.path.isfile(p):
                media_path = p
                break
        if not media_path:
            return False
        for attempt in range(3):
            try:
                await bot.send_animation(
                    chat_id=chat_id,
                    animation=FSInputFile(media_path),
                    caption=caption,
                    parse_mode="html",
                    reply_markup=reply_markup,
                )
                return True
            except TelegramRetryAfter as e:
                self.print_log(f"⚠️ Flood control при анонсі {kind}: чекаємо {e.retry_after} с (спроба {attempt + 1}/3)")
                await asyncio.sleep(e.retry_after)
            except Exception as e:
                self.print_log(f"⚠️ Не вдалося надіслати {kind}.gif: {e}")
                return False
        return False

    async def _prepare_video_9_16(self, video_path: str) -> str | None:
        """Підготовка відео під iPhone/мобільні: 9:16 з лишебоксуванням і відступами, щоб нічого не обрізалося. Потрібен ffmpeg."""
        if not os.path.isfile(video_path):
            return None
        ffmpeg_exe = shutil.which("ffmpeg")
        if not ffmpeg_exe:
            return None
        fd, out_path = tempfile.mkstemp(suffix=".mp4", prefix="mafia_9x16_")
        os.close(fd)
        # Масштабуємо вміст у менший прямокутник (576x1024), потім доповнюємо до 720x1280 - чорні поля навколо, щоб клієнт не обрізав
        try:
            proc = await asyncio.create_subprocess_exec(
                ffmpeg_exe, "-y", "-i", video_path,
                "-vf", "scale=576:1024:force_original_aspect_ratio=decrease,pad=720:1280:(720-iw)/2:(1280-ih)/2:black",
                "-c:a", "copy", out_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode != 0:
                try:
                    os.unlink(out_path)
                except OSError:
                    pass
                return None
            return out_path
        except Exception:
            try:
                os.unlink(out_path)
            except OSError:
                pass
            return None

    def _role_image_basename(self, role: str) -> str:
        """Повертає базове ім'я файлу для фото ролі (без розширення). Маппінг для ролей з пробілами/крапками."""
        # Роль "Мед. сестра" в грі - файл може бути "Медсестра.jpg"
        role_to_file = {
            "Мед. сестра": "Медсестра",
            # Файл картки названо "Мисливець на русалок.jpg" (без «у») — мапимо на роль.
            "Мисливець на русалку": "Мисливець на русалок",
        }
        return role_to_file.get(role, role)

    MAX_CARD_WIDTH = 512

    def _resize_card_image(self, path: str) -> tuple[bytes, str] | None:
        """Resize image to max width 512px, keep aspect ratio, no upscale. Returns (bytes, filename) or None."""
        if Image is None:
            try:
                with open(path, "rb") as f:
                    return (f.read(), os.path.basename(path))
            except Exception:
                return None
        try:
            with Image.open(path) as im:
                im.load()
                w, h = im.size
                if w <= self.MAX_CARD_WIDTH:
                    # No upscale: use as-is
                    bio = io.BytesIO()
                    fmt = im.format or "PNG"
                    im.save(bio, format=fmt, optimize=True)
                    ext = ".png" if fmt.upper() == "PNG" else ".jpg"
                    return (bio.getvalue(), "card" + ext)
                new_w = self.MAX_CARD_WIDTH
                new_h = int(h * self.MAX_CARD_WIDTH / w)
                resized = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
                bio = io.BytesIO()
                resized.save(bio, format="PNG", optimize=True)
                return (bio.getvalue(), "card.png")
        except Exception as e:
            self.print_log(f"⚠️ Resize failed for {path}: {e}")
            return None

    async def _send_role_announce_photos(self, bot: Bot, chat_id: int, role: str, caption: str | None = None):
        """Send exactly TWO images (front role card + back logo), then опис ролі окремим повідомленням якщо є caption."""
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Media', 'role_announce'))
        role_dir = os.path.join(base, 'role_images')
        bg_dir = os.path.join(base, 'background')
        basename = self._role_image_basename(role)
        front_path: str | None = None
        back_path: str | None = None
        for ext in ('.jpg', '.jpeg', '.png'):
            p = os.path.join(role_dir, basename + ext)
            if os.path.isfile(p):
                front_path = p
                break
        for name in ('default.jpg', 'default.jpeg', 'default.png'):
            p = os.path.join(bg_dir, name)
            if os.path.isfile(p):
                back_path = p
                break
        if front_path and back_path:
            front_data = self._resize_card_image(front_path)
            back_data = self._resize_card_image(back_path)
            if front_data and back_data:
                try:
                    media = [
                        InputMediaPhoto(media=BufferedInputFile(front_data[0], front_data[1])),
                        InputMediaPhoto(media=BufferedInputFile(back_data[0], back_data[1])),
                    ]
                    await bot.send_media_group(chat_id=chat_id, media=media)
                except Exception as e:
                    self.print_log(f"⚠️ Не вдалося надіслати картки ролі {role}: {e}")
            else:
                try:
                    await bot.send_photo(chat_id=chat_id, photo=FSInputFile(front_path))
                    await bot.send_photo(chat_id=chat_id, photo=FSInputFile(back_path))
                except Exception as e:
                    self.print_log(f"⚠️ Не вдалося надіслати фото ролі {role}: {e}")
        elif front_path:
            front_data = self._resize_card_image(front_path)
            if front_data:
                try:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=BufferedInputFile(front_data[0], front_data[1]),
                    )
                except Exception as e:
                    self.print_log(f"⚠️ Не вдалося надіслати фото ролі {role}: {e}")
            else:
                try:
                    await bot.send_photo(chat_id=chat_id, photo=FSInputFile(front_path))
                except Exception as e:
                    self.print_log(f"⚠️ Не вдалося надіслати фото ролі {role}: {e}")
        elif back_path:
            back_data = self._resize_card_image(back_path)
            if back_data:
                try:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=BufferedInputFile(back_data[0], back_data[1]),
                    )
                except Exception as e:
                    self.print_log(f"⚠️ Не вдалося надіслати фон: {e}")
            else:
                try:
                    await bot.send_photo(chat_id=chat_id, photo=FSInputFile(back_path))
                except Exception as e:
                    self.print_log(f"⚠️ Не вдалося надіслати фон: {e}")
        if caption:
            # Опис ролі - окремим повідомленням (після карток або якщо карток немає).
            # Причепурюємо: перший рядок (назва ролі) жирним, ціль - курсивом.
            # Лише якщо в тексті ще немає HTML-розмітки, щоб не зламати кастомні описи.
            pretty = caption.strip()
            if "<" not in pretty:
                if "\n\n" in pretty:
                    head, _, tail = pretty.partition("\n\n")
                    pretty = f"<b>{head.strip()}</b>\n\n<i>{tail.strip()}</i>"
                else:
                    pretty = f"<b>{pretty}</b>"
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=pretty,
                    parse_mode="HTML",
                )
            except Exception as e:
                self.print_log(f"⚠️ Не вдалося надіслати опис ролі {role}: {e}")

    async def start_game(self, message: Message, bot: Bot):
        chat_id = message.chat.id
        state = self._get_state(chat_id)
        
        # Перевірка: чи гра вже активна (запобігає подвійному запуску)
        if state.game_active:
            self.print_log(f"⚠️ Гра вже активна для чату {chat_id}, ігноруємо повторний виклик start_game")
            return
        
        # #region agent log
        _log_debug('debug-session', 'run1', 'H1', 'play.py:start_game:entry', 'start_game called', {
            'chat_id': chat_id,
            'membersList_len': len(state.membersList),
            'membersNames_len': len(state.membersNames),
            'MN': state.MN,
            'conn_is_none': conn is None,
            'cursor_is_none': cursor is None
        })
        # #endregion
        
        self.print_log(f"🎮 start_game викликано!")
        self.print_log(f"👥 state.membersList: {state.membersList} (кількість: {len(state.membersList)})")
        self.print_log(f"👥 state.membersNames: {state.membersNames} (кількість: {len(state.membersNames)})")
        self.print_log(f"📊 state.MN (мінімум гравців): {state.MN}")
        
        # Синхронізуємо state.membersList з state.membersNames на випадок розсинхронізації
        if len(state.membersNames) > len(state.membersList):
            self.print_log(f"⚠️ Синхронізація: membersNames ({len(state.membersNames)}) > membersList ({len(state.membersList)})")
            state.membersList = [member_id for member_id, _ in state.membersNames]
            self.print_log(f" Після синхронізації: membersList = {state.membersList}")
            # #region agent log
            _log_debug('debug-session', 'run1', 'H2', 'play.py:start_game:sync', 'membersList synced from membersNames', {
                'membersList_len': len(state.membersList)
            })
            # #endregion
        
        if len(state.membersList) >= state.MN:
            frame = inspect.currentframe().f_back
            self.print_log(f"\n--- Нова гра починається!")
            
            # Встановлюємо game_active = True ПЕРЕД reset_for_new_game, щоб запобігти подвійному виклику
            state.game_active = True
            try:
                # Закриваємо ставки на цю гру та прибираємо повідомлення казино в групі
                open_round = await casino_get_open_round_async(chat_id)
                if open_round:
                    round_id = open_round[0]
                    message_id = open_round[2] if len(open_round) > 2 else None
                    await casino_close_bets_for_round_async(round_id)
                    if message_id:
                        try:
                            await bot.delete_message(chat_id=chat_id, message_id=message_id)
                        except Exception:
                            pass
                await bot.send_message(
                    chat_id=chat_id,
                    text=emoji_to_premium("🎰Казино «У Лева» прийняло ставки"),
                    parse_mode="html",
                )
            except Exception as e:
                self.print_log(f"Казино: повідомлення при старті гри: {e}")
            try:
                # Розмутити всіх, кого замутили під час попередньої гри
                await self._unmute_users_muted_during_game(bot, chat_id)
                # Reset game state
                state.reset_for_new_game()
                # Знімок активного сезонного івенту на старті гри: подальші вмикання/
                # вимикання з адмін-панелі не вплинуть на цю партію (нічого не зламається).
                try:
                    state.active_seasonal_event = await seasonal_mod.get_active_event_id()
                except Exception:
                    state.active_seasonal_event = None
                # «Купальська ніч»: вінки тепер звичайні бафи — заповнюємо нижче,
                # ПІСЛЯ роздачі ролей (бо «Щаслива ніч» діє лише на Аль Капоне).
                state.kupala_buffs = {}
                # Snapshot full roster for end-of-game summary
                state.all_membersList = list(state.membersList)
                state.all_membersNames = list(state.membersNames)
                
                # Reset database flags for all players
                await self._db_execute_commit(
                    "UPDATE users SET role = NULL, killed = %s, cured = %s, votes = %s WHERE id IN %s",
                    (0, 0, 0, tuple(state.membersList) if state.membersList else (None,)),
                )
                self.print_log(f"🔄 Всі ролі та статуси очищені перед роздачею")
                
                # Reset role holders that may persist from previous games.
                # Important for paired-role notifications: we must not send PMs to users
                # who are not in the current roster.
                state.all_capone_id = 0
                state.civilian_ids = []
                state.doctor_id = 0
                state.nurse_id = 0
                state.commissioner_id = 0
                state.sheriff_id = 0
                state.list_of_victim = []
                state.list_of_patient = []
                
                # Завантаження ролей з ChatRoleRegistry для цього чату
                creator_result = await self._db_fetchone(
                    "SELECT creator_id FROM admin_panel WHERE group_id = %s",
                    (chat_id,),
                )
                creator_id = creator_result[0] if creator_result else message.from_user.id
                # Завантажуємо назви ролей з адмін-панелі (щоб коректно розпізнати Дона/Мафію при роздачі)
                admin_names = await self._db_fetchone(
                    "SELECT doctor, all_capone, civilian FROM admin_panel WHERE creator_id = %s AND group_id = %s",
                    (creator_id, chat_id),
                )
                if admin_names and admin_names[1]:
                    state.name_of_all_capone = admin_names[1]
                if admin_names and admin_names[0]:
                    state.name_of_doctor = admin_names[0]
                if admin_names and admin_names[2]:
                    state.name_of_civilian = admin_names[2]
                
                # Перевірка: чи є гравці (мінімум 4, максимум 30)
                MAX_PLAYERS = 30
                MIN_PLAYERS = 4
                if not state.membersList or len(state.membersList) < MIN_PLAYERS:
                    self.print_log(
                        f"start_game: замало гравців у чаті {chat_id} (є {len(state.membersList or [])}, потрібно {MIN_PLAYERS})"
                    )
                    state.game_active = False
                    return
                
                if len(state.membersList) > MAX_PLAYERS:
                    self.print_log(
                        f"start_game: забагато гравців у чаті {chat_id} ({len(state.membersList)} > {MAX_PLAYERS})"
                    )
                    state.game_active = False
                    return
                
                self.print_log(f"👥 Кількість гравців для розподілу ролей: {len(state.membersList)}")
                self.print_log(f"👥 Список гравців: {state.membersList}")
                
                # Отримуємо всі ролі для цього чату
                # ensure_default_roles_for_chat викликається всередині get_all_roles_for_chat і оновлює ролі
                all_roles = ChatRoleRegistry.get_all_roles_for_chat(creator_id, chat_id)
                # #region agent log
                _log_debug('debug-session', 'run1', 'H3', 'play.py:start_game:roles_loaded', 'Roles loaded for chat', {
                    'creator_id': creator_id,
                    'chat_id': chat_id,
                    'roles_count': len(all_roles),
                    'role_names': [role.name for role in all_roles]
                })
                # #endregion
                self.print_log(f"📋 Завантажено {len(all_roles)} ролей з реєстру для групи {chat_id}: {[r.name for r in all_roles]}")
                # Знаходимо обов'язкові ролі: МЖ і Дон (Аль Капоне)
                civilian_role_name = None
                don_role_name = None
                other_unique_roles = []
                # Клоун та Диявол - тільки якщо у групи є куплена підписка (власник групи купив підписку)
                group_has_purchased_sub = ShopManager.is_subscription_active(creator_id) if creator_id else False
                if not group_has_purchased_sub:
                    self.print_log(f"📋 Група {chat_id} без купленої підписки: ролі Клоун та Диявол недоступні")

                players_count = len(state.membersList)
                # Увімкнення ролей тільки з налаштувань цієї групи (construct_event)
                for role in all_roles:
                    role_name = role.name
                    role_enabled = getattr(role, "enabled", True)
                    if not role_enabled:
                        continue
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'H3', 'play.py:start_game:role_iter', 'Iterating role', {
                        'role_name': role_name
                    })
                    # #endregion
                    # МЖ може бути багато - обов'язкова роль
                    if role_name == "Мирний житель" or ("мирний" in role_name.lower() and "житель" in role_name.lower()):
                        civilian_role_name = role_name
                    # Дон (Аль Капоне) - обов'язкова роль, тільки 1 - НЕ додаємо до інших ролей
                    elif role_name == "Аль Капоне" or role_name == state.name_of_all_capone:
                        don_role_name = role_name
                    # Комісар Каттані - додається окремо в логіці роздачі (гарантовано, якщо увімкнено і min_players вистачає)
                    elif role_name == "Комісар Каттані":
                        pass
                    # Лікар - обробляємо окремо (додається далі в логіці)
                    elif role_name == "Лікар":
                        pass
                    # Щасливчик - через other_unique_roles (якщо увімкнено в construct_event)
                    # Мафія - обробляємо окремо (тільки 1)
                    elif role_name == "Мафія":
                        # Мафія буде додана окремо в логіці роздачі ролей
                        pass
                    # Самогубець, Коханка, Мед. сестра, Камікадзе, Волоцюга - обробляємо окремо
                    elif role_name in ["Самогубець", "Коханка", "Мед. сестра", "Камікадзе", "Волоцюга"]:
                        # Будуть додані окремо в логіці роздачі ролей
                        pass
                    else:
                        # Клоун та Диявол - тільки для груп з купленою підпискою
                        if role_name in ("Клоун", "Диявол") and not group_has_purchased_sub:
                            continue
                        # Кастомні ролі та інші стандартні (Комісар, Сержант, Журналіст, Адвокат, Клоун, Брехун, Маніяк тощо)
                        min_players = getattr(role, "min_players", 3)
                        if players_count >= min_players and role_name not in other_unique_roles:
                            other_unique_roles.append(role_name)
                # Адвокат АБО Брехун - не може бути обидві ролі в одній грі
                if "Адвокат" in other_unique_roles and "Брехун" in other_unique_roles:
                    to_remove = random.choice(["Адвокат", "Брехун"])
                    other_unique_roles.remove(to_remove)
                    self.print_log(f"📋 В грі лише одна з ролей (Адвокат/Брехун): залишено {'Брехун' if to_remove == 'Адвокат' else 'Адвокат'}")
                # #region agent log
                _log_debug('debug-session', 'run1', 'H3', 'play.py:start_game:roles_parsed', 'Parsed roles', {
                    'don_role_name': don_role_name,
                    'civilian_role_name': civilian_role_name,
                    'other_unique_roles_count': len(other_unique_roles)
                })
                # #endregion
                
                # Якщо МЖ не знайдено, використовуємо назву з state.name_of_civilian
                if not civilian_role_name:
                    civilian_role_name = state.name_of_civilian
                
                # Якщо Дон не знайдено, використовуємо назву з state.name_of_all_capone
                if not don_role_name:
                    don_role_name = state.name_of_all_capone
                    # Перевіряємо чи є в інших ролях
                    if don_role_name in other_unique_roles:
                        other_unique_roles.remove(don_role_name)
                # #region agent log
                _log_debug('debug-session', 'run1', 'H3', 'play.py:start_game:required_roles', 'Resolved required roles', {
                    'don_role_name': don_role_name,
                    'civilian_role_name': civilian_role_name,
                    'other_unique_roles_count': len(other_unique_roles)
                })
                # #endregion
                
                # Перевірка: має бути Дон для початку гри
                if not don_role_name:
                    self.print_log(
                        f"start_game: роль Дона (Аль Капоне) не знайдена для чату {chat_id}, переривання роздачі"
                    )
                    state.game_active = False
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'H4', 'play.py:start_game:missing_don', 'Missing Don role', {
                        'don_role_name': don_role_name,
                        'civilian_role_name': civilian_role_name
                    })
                    # #endregion
                    return
                
                if not civilian_role_name:
                    self.print_log(
                        f"start_game: роль мирного жителя не знайдена для чату {chat_id}, переривання роздачі"
                    )
                    state.game_active = False
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'H4', 'play.py:start_game:missing_civilian', 'Missing civilian role', {
                        'don_role_name': don_role_name,
                        'civilian_role_name': civilian_role_name
                    })
                    # #endregion
                    return
                
                # Створюємо список ролей для роздачі
                # Ролі для роздачі:
                # 1. Аль Капоне - завжди рівно 1
                # 2. Лікар - рівно 1 (тільки якщо гравців >= 4)
                # 3. Мафія - рівно 1 (при players 8+)
                # 4. Самогубець - рівно 1 (тільки якщо гравців >= 3) - ВИМКНЕНО
                # 5. Коханка - рівно 1 (тільки якщо гравців >= 3) - ВИМКНЕНО
                # 6. Мед. сестра - рівно 1 (тільки якщо гравців >= 3)
                # 7. Камікадзе - рівно 1 (тільки якщо гравців >= 3)
                # 8. Волоцюга - рівно 1 (тільки якщо гравців >= 3)
                # 9. Всі інші - Мирний житель
                
                roles = []
                players_count = len(state.membersList)
                
                # 1. Аль Капоне - завжди рівно 1
                if don_role_name:
                    roles.append(don_role_name)
                
                # 2. Комісар Каттані - рівно 1, якщо роль увімкнена в групі та гравців >= min_players з налаштувань
                commissioner_role_name = None
                for role in all_roles:
                    if role.name == "Комісар Каттані":
                        role_enabled = getattr(role, "enabled", True)
                        if role_enabled:
                            min_players = getattr(role, "min_players", 4)
                            if players_count >= min_players:
                                commissioner_role_name = role.name
                                roles.append(commissioner_role_name)
                                self.print_log(
                                    f" Додано роль Комісар Каттані до списку ролей для роздачі (min_players={min_players})"
                                )
                            else:
                                self.print_log(
                                    f"⚠️ Комісар Каттані не доданий: гравців ({players_count}) < min_players ({min_players})"
                                )
                        else:
                            self.print_log("⚠️ Комісар Каттані не доданий: роль вимкнена для цієї групи")
                        break
                
                # 3. Лікар - рівно 1 (тільки якщо гравців >= 4)
                doctor_role_name = None
                for role in all_roles:
                    if role.name == "Лікар":
                        role_enabled = getattr(role, "enabled", True)
                        if role_enabled:
                            min_players = getattr(role, "min_players", 4)
                            if players_count >= min_players:
                                doctor_role_name = role.name
                                roles.append(doctor_role_name)
                                break
                
                # 4. Щасливчик - рівно 1 (тільки якщо гравців >= 4) - ВИМКНЕНО
                # lucky_role_name = None
                # for role in all_roles:
                #     if role.name == "Щасливчик":
                #         role_enabled = getattr(role, "enabled", True)
                #         if role_enabled:
                #             min_players = getattr(role, "min_players", 4)
                #             if players_count >= min_players:
                #                 lucky_role_name = role.name
                #                 roles.append(lucky_role_name)
                #                 break
                
                # 5. Мафія - масштабована кількість (без Дона; Дон завжди окремо):
                #  - до 10 гравців: 1 (малий стіл — не «трійка» зла)
                #  - 11-15: 2
                #  - 16-22: 3
                #  - 23+: 5
                mafia_role_name = None
                mafia_found = False
                desired_mafia_count = 1
                for role in all_roles:
                    if role.name == "Мафія":
                        mafia_found = True
                        role_enabled = getattr(role, "enabled", True)
                        min_players = getattr(role, "min_players", 3)
                        mafia_scale_defaults = {
                            "up_to_10": 1,
                            "from_11": 2,
                            "from_16": 3,
                            "from_23": 5,
                        }
                        mafia_scale = mafia_scale_defaults.copy()
                        custom_data = getattr(role, "custom_data", None) or {}
                        raw_scale = custom_data.get("mafia_scale", {})
                        if isinstance(raw_scale, dict):
                            for key, default_value in mafia_scale_defaults.items():
                                try:
                                    mafia_scale[key] = int(raw_scale.get(key, default_value))
                                except Exception:
                                    mafia_scale[key] = default_value
                        desired_mafia_count = max(0, int(mafia_scale["up_to_10"]))
                        if players_count >= 23:
                            desired_mafia_count = max(0, int(mafia_scale["from_23"]))
                        elif players_count >= 16:
                            desired_mafia_count = max(0, int(mafia_scale["from_16"]))
                        elif players_count >= 11:
                            desired_mafia_count = max(0, int(mafia_scale["from_11"]))
                        self.print_log(f"🔍 Знайдено роль Мафія: enabled={role_enabled}, min_players={min_players}, players_count={players_count}")
                        self.print_log(
                            f"📈 Схема мафії: 1-10={mafia_scale['up_to_10']}, "
                            f"11-15={mafia_scale['from_11']}, 16-22={mafia_scale['from_16']}, 23+={mafia_scale['from_23']}"
                        )
                        # Перевіряємо, чи роль увімкнена або в списку дозволених
                        if role_enabled:
                            if players_count >= min_players:
                                mafia_role_name = role.name
                                roles.extend([mafia_role_name] * desired_mafia_count)
                                self.print_log(
                                    f" Додано роль Мафія до списку ролей для роздачі: {desired_mafia_count} шт."
                                )
                                break
                            else:
                                self.print_log(f"⚠️ Мафія не додана: гравців ({players_count}) < min_players ({min_players})")
                        else:
                            self.print_log(f"⚠️ Мафія не додана: роль вимкнена для цієї групи")
                if not mafia_found:
                    self.print_log(f" Роль Мафія не знайдена в all_roles! Доступні ролі: {[r.name for r in all_roles]}")
                
                # 6. Самогубець - рівно 1 (тільки якщо гравців >= 3)
                suicide_role_name = None
                suicide_found = False
                for role in all_roles:
                    if role.name == "Самогубець":
                        suicide_found = True
                        role_enabled = getattr(role, "enabled", True)
                        min_players = getattr(role, "min_players", 3)
                        self.print_log(f"🔍 Знайдено роль Самогубець: enabled={role_enabled}, min_players={min_players}, players_count={players_count}")
                        # Перевіряємо, чи роль увімкнена або в списку дозволених
                        if role_enabled:
                            if players_count >= min_players:
                                suicide_role_name = role.name
                                roles.append(suicide_role_name)
                                self.print_log(f" Додано роль Самогубець до списку ролей для роздачі")
                                break
                            else:
                                self.print_log(f"⚠️ Самогубець не доданий: гравців ({players_count}) < min_players ({min_players})")
                        else:
                            self.print_log(f"⚠️ Самогубець не доданий: роль вимкнена для цієї групи")
                if not suicide_found:
                    self.print_log(f" Роль Самогубець не знайдена в all_roles! Доступні ролі: {[r.name for r in all_roles]}")
                
                # 7. Коханка - рівно 1 (тільки якщо гравців >= 3)
                prostitute_role_name = None
                prostitute_found = False
                self.print_log(f"🔍 Шукаю роль Коханка в {len(all_roles)} ролях...")
                for role in all_roles:
                    if role.name == "Коханка":
                        prostitute_found = True
                        role_enabled = getattr(role, "enabled", True)
                        min_players = getattr(role, "min_players", 3)
                        self.print_log(f"🔍 Знайдено роль Коханка: enabled={role_enabled}, min_players={min_players}, players_count={players_count}")
                        if role_enabled:
                            if players_count >= min_players:
                                prostitute_role_name = role.name
                                roles.append(prostitute_role_name)
                                self.print_log(f" Додано роль Коханка до списку ролей для роздачі")
                                break
                            else:
                                self.print_log(f"⚠️ Коханка не додана: гравців ({players_count}) < min_players ({min_players})")
                        else:
                            self.print_log(f"⚠️ Коханка не додана: роль вимкнена для цієї групи")
                if not prostitute_found:
                    self.print_log(f" Роль Коханка не знайдена в all_roles! Доступні ролі: {[r.name for r in all_roles]}")
                
                # 8. Мед. сестра - рівно 1 (тільки якщо гравців >= 3)
                nurse_role_name = None
                nurse_found = False
                for role in all_roles:
                    if role.name == "Мед. сестра":
                        nurse_found = True
                        role_enabled = getattr(role, "enabled", True)
                        min_players = getattr(role, "min_players", 3)
                        self.print_log(f"🔍 Знайдено роль Мед. сестра: enabled={role_enabled}, min_players={min_players}, players_count={players_count}")
                        # Перевіряємо, чи роль увімкнена або в списку дозволених
                        if role_enabled:
                            if players_count >= min_players:
                                nurse_role_name = role.name
                                roles.append(nurse_role_name)
                                self.print_log(f" Додано роль Мед. сестра до списку ролей для роздачі")
                                break
                            else:
                                self.print_log(f"⚠️ Мед. сестра не додана: гравців ({players_count}) < min_players ({min_players})")
                        else:
                            self.print_log(f"⚠️ Мед. сестра не додана: роль вимкнена для цієї групи")
                if not nurse_found:
                    self.print_log(f" Роль Мед. сестра не знайдена в all_roles! Доступні ролі: {[r.name for r in all_roles]}")
                
                # 9. Камікадзе - рівно 1 (тільки якщо гравців >= 3)
                kamikaze_role_name = None
                kamikaze_found = False
                for role in all_roles:
                    if role.name == "Камікадзе":
                        kamikaze_found = True
                        role_enabled = getattr(role, "enabled", True)
                        min_players = getattr(role, "min_players", 3)
                        self.print_log(f"🔍 Знайдено роль Камікадзе: enabled={role_enabled}, min_players={min_players}, players_count={players_count}")
                        # Перевіряємо, чи роль увімкнена або в списку дозволених
                        if role_enabled:
                            if players_count >= min_players:
                                kamikaze_role_name = role.name
                                roles.append(kamikaze_role_name)
                                self.print_log(f" Додано роль Камікадзе до списку ролей для роздачі")
                                break
                            else:
                                self.print_log(f"⚠️ Камікадзе не доданий: гравців ({players_count}) < min_players ({min_players})")
                        else:
                            self.print_log(f"⚠️ Камікадзе не доданий: роль вимкнена для цієї групи")
                if not kamikaze_found:
                    self.print_log(f" Роль Камікадзе не знайдена в all_roles! Доступні ролі: {[r.name for r in all_roles]}")
                
                # 10. Волоцюга - рівно 1 (тільки якщо гравців >= 3)
                homeless_role_name = None
                homeless_found = False
                for role in all_roles:
                    if role.name == "Волоцюга":
                        homeless_found = True
                        role_enabled = getattr(role, "enabled", True)
                        min_players = getattr(role, "min_players", 3)
                        self.print_log(f"🔍 Знайдено роль Волоцюга: enabled={role_enabled}, min_players={min_players}, players_count={players_count}")
                        # Перевіряємо, чи роль увімкнена або в списку дозволених
                        if role_enabled:
                            if players_count >= min_players:
                                homeless_role_name = role.name
                                roles.append(homeless_role_name)
                                self.print_log(f" Додано роль Волоцюга до списку ролей для роздачі")
                                break
                            else:
                                self.print_log(f"⚠️ Волоцюга не доданий: гравців ({players_count}) < min_players ({min_players})")
                        else:
                            self.print_log(f"⚠️ Волоцюга не доданий: роль вимкнена для цієї групи")
                if not homeless_found:
                    self.print_log(f" Роль Волоцюга не знайдена в all_roles! Доступні ролі: {[r.name for r in all_roles]}")
                
                # 10a. Кастомні та інші унікальні ролі (по одній) - увімкнені в construct_event для цієї групи
                # Додаємо лише стільки, скільки є вільних місць. Кастомні ролі мають пріоритет - спочатку їх, потім стандартні.
                # Комісар уже в roles — не дублювати з кешованих списків
                if "Комісар Каттані" in other_unique_roles:
                    other_unique_roles = [n for n in other_unique_roles if n != "Комісар Каттані"]
                remaining_slots = players_count - len(roles)
                if remaining_slots > 0 and other_unique_roles:
                    custom_role_names = {r.name for r in all_roles if not getattr(r, "is_default", True)}
                    custom_in_other = [n for n in other_unique_roles if n in custom_role_names]
                    standard_in_other = [n for n in other_unique_roles if n not in custom_role_names]
                    to_add = []
                    to_add.extend(custom_in_other[:remaining_slots])
                    remaining_after_custom = remaining_slots - len(to_add)
                    if remaining_after_custom > 0 and standard_in_other:
                        to_add_standard = standard_in_other[:remaining_after_custom] if len(standard_in_other) <= remaining_after_custom else random.sample(standard_in_other, remaining_after_custom)
                        to_add.extend(to_add_standard)
                    for role_name in to_add:
                        roles.append(role_name)
                
                # 11. Решта гравців - МЖ (мінімум 1)
                self.print_log(f"📊 Стан перед додаванням МЖ: roles={len(roles)}, players_count={players_count}")
                self.print_log(f"📊 Поточний список ролей перед МЖ: {roles}")
                remaining_players = players_count - len(roles)
                self.print_log(f"📊 Залишилося гравців для МЖ: {remaining_players}")
                if remaining_players > 0 and civilian_role_name:
                    roles.extend([civilian_role_name] * remaining_players)
                elif not civilian_role_name:
                    # Якщо МЖ не знайдено, використовуємо назву з state
                    if state.name_of_civilian:
                        roles.extend([state.name_of_civilian] * remaining_players)
                
                # Фінальна перевірка: гарантуємо мінімум 1 МЖ
                if civilian_role_name and civilian_role_name not in roles:
                    # Якщо МЖ немає взагалі, замінюємо останню роль (якщо це не Аль Капоне)
                    if len(roles) > 1:
                        roles[-1] = civilian_role_name
                    else:
                        # Якщо тільки Аль Капоне, додаємо МЖ
                        roles.append(civilian_role_name)

                # #region agent log
                _log_debug('debug-session', 'run1', 'H5', 'play.py:start_game:roles_built', 'Built roles list', {
                    'roles_len': len(roles),
                    'membersList_len': len(state.membersList),
                    'roles_preview': roles[:5]
                })
                # #endregion
                
                self.print_log(f"📋 Завантажено ролей: {len(all_roles)}")
                self.print_log(f"📋 Дон (Аль Капоне): {don_role_name}")
                self.print_log(f"📋 МЖ: {civilian_role_name}")
                self.print_log(f"📋 Мафія: {mafia_role_name} x{desired_mafia_count if mafia_role_name else 0}")
                self.print_log(f"📋 Самогубець: {suicide_role_name}")
                self.print_log(f"📋 Коханка: {prostitute_role_name}")
                self.print_log(f"📋 Лікар: {doctor_role_name}")
                self.print_log(f"📋 Комісар Каттані: {commissioner_role_name}")
                self.print_log(f"📋 Мед. сестра: {nurse_role_name}")
                self.print_log(f"📋 Камікадзе: {kamikaze_role_name}")
                self.print_log(f"📋 Волоцюга: {homeless_role_name}")
                self.print_log(f"📋 Інші унікальні ролі (по 1): {other_unique_roles}")
                self.print_log(f"📋 Кількість гравців: {len(state.membersList)}")
                self.print_log(f"📋 До перемішування ({len(roles)} ролей): {roles}")
                
                # Перевірка бафів: перевіряємо чи всі бафи мають обмеження на кількість використань
                self.print_log("🔍 Перевірка бафів: перевіряю наявність обмежень на кількість використань...")
                active_buffs = await self._db_fetchall(
                    """
                    SELECT user_id, buff_id, COALESCE(quantity, 1) as qty, COALESCE(is_active, FALSE) as active
                    FROM user_buffs
                    WHERE COALESCE(is_active, FALSE) = TRUE
                    ORDER BY user_id, buff_id
                    """
                )
                if active_buffs:
                    self.print_log(f"📊 Знайдено {len(active_buffs)} активних бафів у гравців:")
                    for user_id, buff_id, qty, active in active_buffs:
                        self.print_log(f"   👤 {user_id}: {buff_id} - зарядів: {qty}, активний: {active}")
                        if qty is None or qty <= 0:
                            self.print_log(f"   ⚠️ УВАГА: Баф {buff_id} у гравця {user_id} має невалідну кількість ({qty})!")
                else:
                    self.print_log(" Активних бафів не знайдено")
                
                # Перевірка балансу гри: відношення мафії та мирних
                mafia_role_names = {don_role_name, state.name_of_all_capone}
                if mafia_role_name:
                    mafia_role_names.add(mafia_role_name)
                mafia_role_names.update({"Адвокат", "Брехун"})
                mafia_count = sum(1 for r in roles if r in mafia_role_names)
                peaceful_count = len(roles) - mafia_count
                self.print_log(f"📊 Баланс гри: всього гравців {len(roles)}, мафія: {mafia_count}, мирні: {peaceful_count}")
                if peaceful_count < 1:
                    self.print_log(f" ПОМИЛКА: Немає мирних ролей!")
                    state.game_active = False
                    return
                if mafia_count >= peaceful_count:
                    self.print_log(f" ПОМИЛКА: Мафія ({mafia_count}) >= Мирні ({peaceful_count}) - гра незбалансована!")
                    state.game_active = False
                    return
                
                # Перевірка: має бути хоча б 2 гравці та 2 ролі (Дон + МЖ)
                if len(roles) < 2:
                    state.game_active = False
                    self.print_log(
                        f"start_game: не вистачає ролей для роздачі (roles={len(roles)}) у чаті {chat_id}"
                    )
                    # #region agent log
                    _log_debug('debug-session', 'run1', 'H4', 'play.py:start_game:roles_too_few', 'Not enough roles to assign', {
                        'roles_len': len(roles),
                        'membersList_len': len(state.membersList)
                    })
                    # #endregion
                    return
                
                if len(roles) != len(state.membersList):
                    self.print_log(
                        f"start_game: кількість ролей ({len(roles)}) != гравців ({len(state.membersList)}) у чаті {chat_id}"
                    )
                
                # Перевірка: має бути стільки ж ролей скільки гравців
                if len(roles) != len(state.membersList):
                    self.print_log(f"⚠️ ПОМИЛКА: Кількість ролей ({len(roles)}) != кількість гравців ({len(state.membersList)})")
                    # Додаємо МЖ для решти гравців
                    while len(roles) < len(state.membersList):
                        if civilian_role_name:
                            roles.append(civilian_role_name)
                        else:
                            break
                    self.print_log(f"🔧 Виправлено список ролей: {len(roles)} ролей")
                
                # Якщо увімкнено забагато унікальних ролей для столу, zip() раніше відкидав «хвіст» після shuffle —
                # Комісар міг не потрапити до роздачі. Обрізаємо надлишок іменно з непріоритетних ролей,
                # зберігаючи Дона та Комісара (якщо він уже в списку за min_players / construct_event).
                if len(roles) > len(state.membersList):
                    protected_names = {don_role_name}
                    if commissioner_role_name:
                        protected_names.add(commissioner_role_name)
                    trimmed = []
                    while len(roles) > len(state.membersList):
                        removed_idx = None
                        for idx in range(len(roles) - 1, -1, -1):
                            if roles[idx] not in protected_names:
                                removed_idx = idx
                                break
                        if removed_idx is None:
                            self.print_log(
                                "⚠️ start_game: не вдалося вкласти ролі в кількість гравців без видалення Дона/Комісара"
                            )
                            break
                        trimmed.append(roles.pop(removed_idx))
                    if trimmed:
                        self.print_log(
                            f"⚠️ Забагато ролей для столу ({len(trimmed)} зайвих): прибрано з роздачі: {trimmed}"
                        )
                
                # ── Купальська ніч: підмішуємо пару івент-ролей (Русалка + Мисливець) ──
                # Атомарно: або обидві, або жодна (щоб не було самотньої Русалки).
                # Спершу займаємо слоти «Мирних жителів», а якщо їх замало — найменш
                # критичні ролі, захищаючи ядро балансу (Дон, Мафія, Лікар, Комісар).
                try:
                    if getattr(state, "active_seasonal_event", None) == "kupala_night" and len(state.membersList) >= 6:
                        _ev_roles = ["Русалка", "Мисливець на русалку"]
                        _protected = {
                            don_role_name, "Аль Капоне",
                            getattr(state, "name_of_all_capone", "Аль Капоне"),
                            "Мафія",
                            getattr(state, "name_of_doctor", "Лікар"), "Лікар",
                            "Русалка", "Мисливець на русалку",
                        }
                        if commissioner_role_name:
                            _protected.add(commissioner_role_name)
                        _protected.add("Комісар Каттані")
                        # Кандидати-слоти: спершу Мирні жителі, потім будь-які незахищені ролі.
                        _civ_slots = [i for i, rn in enumerate(roles) if rn == civilian_role_name]
                        _other_slots = [i for i, rn in enumerate(roles) if rn != civilian_role_name and rn not in _protected]
                        _slots = _civ_slots + _other_slots
                        if len(_slots) >= len(_ev_roles):
                            for _ev_role, _slot in zip(_ev_roles, _slots):
                                _replaced = roles[_slot]
                                roles[_slot] = _ev_role
                                self.print_log(f"☀️ Купальська ніч: підмішано {_ev_role} (замість «{_replaced}»)")
                        else:
                            self.print_log(
                                f"☀️ Купальська ніч: замало вільних слотів ({len(_slots)}) для пари івент-ролей — пропускаємо"
                            )
                except Exception as _e:
                    self.print_log(f"Купальська ніч (роздача): помилка: {_e}")

                # Перемішуємо ролі: Дон завжди в списку, інші - випадковий порядок
                if len(roles) > 1:
                    other_roles = roles[1:]
                    random.shuffle(other_roles)
                    roles = [roles[0]] + other_roles
                # Перемішуємо порядок гравців
                shuffled_members = list(state.membersList)
                random.shuffle(shuffled_members)

                self.print_log(f" Після перемішування ({len(roles)} ролей): {roles}")
                self.print_log(f"🎯 Аль Капоне гарантовано в грі, випадковому гравцю")

                self.print_log(f"🎲 Починаємо розподіл ролей для {len(state.membersList)} гравців...")
                # #region agent log
                _log_debug('debug-session', 'run1', 'H5', 'play.py:start_game:assign_begin', 'Begin role assignment', {
                    'roles_len': len(roles),
                    'membersList_len': len(state.membersList),
                    'roles_preview': roles[:5]
                })
                # #endregion
                
                roles_assigned = 0
                for id, random_role in zip(shuffled_members, roles):
                    try:
                        # Оновлення ролі в БД
                        await self._db_execute_commit(
                            "UPDATE users SET role = %s WHERE id = %s",
                            (random_role, id,),
                        )
                    except Exception as e:
                        # #region agent log
                        _log_debug('debug-session', 'run1', 'H6', 'play.py:start_game:assign_error', 'DB update failed', {
                            'player_id': id,
                            'role': random_role,
                            'error_type': type(e).__name__,
                            'error_message': str(e)
                        })
                        # #endregion
                        raise
                    
                    # Перевірка, що запис у БД правильний
                    role_result = await self._db_fetchone(
                        "SELECT role FROM users WHERE id = %s",
                        (id,),
                    )
                    if role_result:
                        role = role_result[0]
                        roles_assigned += 1
                        self.print_log(f" [{roles_assigned}/{len(state.membersList)}] {id} отримав роль: {role}")
                        # #region agent log
                        _log_debug('debug-session', 'run1', 'H7', 'play.py:start_game:assigned', 'Role assigned', {
                            'player_id': id,
                            'role': role,
                            'expected_role': random_role,
                            'roles_assigned': roles_assigned
                        })
                        # #endregion
                        
                        if role != random_role:
                            self.print_log(f" ПОМИЛКА! Очікувалося {random_role}, а в БД записано {role}")
                        
                        # Знаходимо роль об'єкт для отримання опису з реєстру ролей
                        role_obj = ChatRoleRegistry.get_role_for_chat(creator_id, chat_id, role)
                        if not role_obj:
                            # Сезонні ролі (Купальська ніч) не в реєстрі групи — беремо опис з реєстру івенту.
                            _ev_desc = None
                            try:
                                from game.role_system import create_event_roles as _cer
                                _ev_obj = _cer().get(role)
                                if _ev_obj and (_ev_obj.description or "").strip():
                                    _ev_desc = _ev_obj.description.strip()
                            except Exception:
                                _ev_desc = None
                            role_description = _ev_desc if _ev_desc else f"Цієї гри ти - {role}!"
                        else:
                            raw_desc = (role_obj.description or "").strip()
                            role_description = raw_desc if raw_desc and raw_desc != "." else f"Цієї гри ти - {role}!"
                        
                        # Визначаємо емоджі для ролі
                        role_icons = {
                            "Лікар": "💊", "Аль Капоне": "🎩", "Мирний житель": "🧍",
                            "Комісар Каттані": "🕵️", "Коханка": "💃", "Тілоохоронець": "🛡️",
                            "Маніяк": "🔪", "Доктор-садист": "⚕️", "Мафія": "🤵",
                            "Русалка": "🧜", "Мисливець на русалку": "🩸",
                            "Самогубець": "🤦‍♂️", "Волоцюга": "🧥",
                            "Камікадзе": "😈", "Сержант": "👮‍♂️",
                            "Щасливчик": "🍀", "Мед. сестра": "👩‍⚕️", "Журналіст": "📰",
                            "Адвокат": "👨‍💼", "Перевертень": "🐺"
                        }
                        role_icon = role_icons.get(role, "🎭")
                        
                        # Перевірка чи це МЖ
                        is_civilian = (role == civilian_role_name or role == "Мирний житель" or 
                                     role == state.name_of_civilian or
                                     ("мирний" in role.lower() and "житель" in role.lower()))
                        
                        # Формуємо текст ролі і відправляємо картки разом з текстом (caption під фото)
                        if role == "Аль Капоне" or role == state.name_of_all_capone:
                            state.all_capone_id = id
                            state.list_of_patient.append(id)
                            await self._send_role_announce_photos(bot, id, role, caption=role_description)
                            # НЕ викликаємо all_capone тут - він буде викликаний в night_function
                        elif role == "Мафія":
                            if id not in state.mafia_ids:
                                state.mafia_ids.append(id)
                            await self._send_role_announce_photos(bot, id, role, caption=role_description)
                            state.list_of_patient.append(id)
                        elif role == "Лікар" or role == state.name_of_doctor:
                            state.doctor_id = id
                            await self._send_role_announce_photos(bot, id, role, caption=role_description)
                            # НЕ викликаємо doctor тут - він буде викликаний в night_function
                        elif role == "Мед. сестра":
                            state.nurse_id = id
                            await self._send_role_announce_photos(bot, id, role, caption=role_description)
                            state.list_of_patient.append(id)
                        elif role == "Комісар Каттані":
                            state.commissioner_id = id
                            await self._send_role_announce_photos(bot, id, role, caption=role_description)
                            state.list_of_patient.append(id)
                        elif role == "Сержант":
                            state.sheriff_id = id
                            await self._send_role_announce_photos(bot, id, role, caption=role_description)
                            state.list_of_patient.append(id)
                        elif role == "Самогубець":
                            await self._send_role_announce_photos(bot, id, role, caption=role_description)
                            state.list_of_patient.append(id)
                        elif role == "Журналіст":
                            role_text = role_description
                            await self._send_role_announce_photos(bot, id, role, caption=role_text)
                            state.list_of_patient.append(id)
                        elif role == "Маніяк":
                            role_text = role_description
                            await self._send_role_announce_photos(bot, id, role, caption=role_text)
                            state.list_of_patient.append(id)
                        elif role == "Клоун":
                            role_text = role_description
                            await self._send_role_announce_photos(bot, id, role, caption=role_text)
                            state.list_of_patient.append(id)
                        elif is_civilian:
                            if id not in state.civilian_ids:
                                await self._send_role_announce_photos(bot, id, role, caption=role_description)
                                state.civilian_ids.append(id)
                                state.list_of_patient.append(id)
                        else:
                            await self._send_role_announce_photos(bot, id, role, caption=role_description)
                            if role not in [state.name_of_all_capone, state.name_of_doctor]:
                                state.list_of_patient.append(id)
                
                # Після роздачі всіх ролей, надсилаємо інформацію про союзників Мафії та Аль Капоне
                # Збираємо список всіх союзників (Аль Капоне + всі Мафія)
                # ВАЖЛИВО: Збираємо союзників ПІСЛЯ того, як всі ролі роздані
                all_allies = []
                if state.all_capone_id:
                    don_result = await self._db_fetchone(
                        "SELECT tg_name FROM users WHERE id = %s",
                        (state.all_capone_id,),
                    )
                    if don_result:
                        all_allies.append(("🎩 Аль Капоне", don_result[0]))
                
                # Додаємо всіх Мафія до списку союзників
                for mafia_id in state.mafia_ids:
                    mafia_result = await self._db_fetchone(
                        "SELECT tg_name FROM users WHERE id = %s",
                        (mafia_id,),
                    )
                    if mafia_result:
                        all_allies.append(("🤵 Мафія", mafia_result[0]))
                
                self.print_log(f"🔍 Діагностика союзників: all_capone_id={state.all_capone_id}, mafia_ids={state.mafia_ids}, all_allies={all_allies}")
                
                # Надсилаємо інформацію про союзників Аль Капоне
                if state.all_capone_id:
                    # Формуємо список Мафія (без Аль Капоне)
                    mafia_allies = [ally for ally in all_allies if ally[0] == "🤵 Мафія"]
                    if mafia_allies:
                        allies_list_text = "\n".join([f"• {role_icon} {name}" for role_icon, name in mafia_allies])
                        allies_message_don = (
                            f"🤝 <b>Твої союзники (Мафія):</b>\n\n"
                            f"{allies_list_text}\n\n"
                        )
                        try:
                            await bot.send_message(chat_id=state.all_capone_id, text=allies_message_don, parse_mode="html")
                            self.print_log(f" Надіслано повідомлення про союзників Аль Капоне (ID: {state.all_capone_id})")
                        except Exception as e:
                            self.print_log(f" Помилка надсилання повідомлення Аль Капоне: {e}")
                    else:
                        self.print_log(f"⚠️ Аль Капоне немає союзників Мафія")
                
                # Надсилаємо інформацію про союзників Мафії
                if state.mafia_ids:
                    for mafia_id in state.mafia_ids:
                        # Отримуємо ім'я поточного гравця Мафії
                        current_mafia_result = await self._db_fetchone(
                            "SELECT tg_name FROM users WHERE id = %s",
                            (mafia_id,),
                        )
                        current_mafia_name = current_mafia_result[0] if current_mafia_result else None
                        
                        # Формуємо список союзників (Аль Капоне + інші Мафія, без поточного гравця)
                        current_mafia_allies = []
                        # Додаємо Аль Капоне
                        if state.all_capone_id:
                            don_name_result = await self._db_fetchone(
                                "SELECT tg_name FROM users WHERE id = %s",
                                (state.all_capone_id,),
                            )
                            if don_name_result:
                                current_mafia_allies.append(("🎩 Аль Капоне", don_name_result[0]))
                        # Додаємо інших Мафія (без поточного)
                        for other_mafia_id in state.mafia_ids:
                            if other_mafia_id != mafia_id:
                                other_mafia_result = await self._db_fetchone(
                                    "SELECT tg_name FROM users WHERE id = %s",
                                    (other_mafia_id,),
                                )
                                if other_mafia_result:
                                    current_mafia_allies.append(("🤵 Мафія", other_mafia_result[0]))
                        
                        if current_mafia_allies:
                            allies_list_for_mafia = "\n".join([f"• {role_icon} {name}" for role_icon, name in current_mafia_allies])
                            allies_message_mafia = (
                                f"🤝 <b>Твої союзники:</b>\n\n"
                                f"{allies_list_for_mafia}\n\n"
                            )
                            try:
                                await bot.send_message(chat_id=mafia_id, text=allies_message_mafia, parse_mode="html")
                                self.print_log(f" Надіслано повідомлення про союзників Мафії (ID: {mafia_id})")
                            except Exception as e:
                                self.print_log(f" Помилка надсилання повідомлення Мафії (ID: {mafia_id}): {e}")
                        else:
                            self.print_log(f"⚠️ Мафія (ID: {mafia_id}) немає союзників")
                if state.all_capone_id or state.mafia_ids:
                    state.mafia_allies_sent = True  # щоб night_function не дублював
                
                # Напарник Лікар - Мед. сестра (і навпаки): показуємо хто є хто + підказка про чат
                if (
                    state.doctor_id
                    and state.nurse_id
                    and state.doctor_id != state.nurse_id
                    and state.doctor_id in state.membersList
                    and state.nurse_id in state.membersList
                ):
                    try:
                        doc_result = await self._db_fetchone(
                            "SELECT tg_name FROM users WHERE id = %s",
                            (state.doctor_id,),
                        )
                        nurse_result = await self._db_fetchone(
                            "SELECT tg_name FROM users WHERE id = %s",
                            (state.nurse_id,),
                        )
                        doc_name = doc_result[0] if doc_result else "Лікар"
                        nurse_name = nurse_result[0] if nurse_result else "Мед. сестра"
                        await bot.send_message(
                            chat_id=state.doctor_id,
                            text=f"💊 <b>Твій напарник</b> - 👩‍⚕️ Мед. сестра: <b>{html.escape(nurse_name)}</b>",
                            parse_mode="html"
                        )
                        await bot.send_message(
                            chat_id=state.nurse_id,
                            text=f"👩‍⚕️ <b>Твій напарник</b> - 💊 Лікар: <b>{html.escape(doc_name)}</b>",
                            parse_mode="html"
                        )
                        self.print_log(f" Надіслано інформацію про напарника Лікарю та Мед. сестрі")
                    except Exception as e:
                        self.print_log(f" Помилка надсилання напарника Лікар/Мед. сестра: {e}")
                
                # Напарник Сержант - Комісар Каттані (і навпаки): показуємо хто є хто
                if (
                    state.sheriff_id
                    and state.commissioner_id
                    and state.sheriff_id in state.membersList
                    and state.commissioner_id in state.membersList
                ):
                    try:
                        comm_result = await self._db_fetchone(
                            "SELECT tg_name FROM users WHERE id = %s",
                            (state.commissioner_id,),
                        )
                        serg_result = await self._db_fetchone(
                            "SELECT tg_name FROM users WHERE id = %s",
                            (state.sheriff_id,),
                        )
                        comm_name = comm_result[0] if comm_result else "Комісар Каттані"
                        serg_name = serg_result[0] if serg_result else "Сержант"
                        await bot.send_message(
                            chat_id=state.sheriff_id,
                            text=f"👮‍♂️ <b>Твій напарник</b> - 🕵️ Комісар Каттані: <b>{html.escape(comm_name)}</b>",
                            parse_mode="html"
                        )
                        await bot.send_message(
                            chat_id=state.commissioner_id,
                            text=f"🕵️ <b>Твій напарник</b> - 👮‍♂️ Сержант: <b>{html.escape(serg_name)}</b>",
                            parse_mode="html"
                        )
                        self.print_log(f" Надіслано інформацію про напарника Сержанту та Комісару")
                    except Exception as e:
                        self.print_log(f" Помилка надсилання напарника Комісар/Сержант: {e}")
                
                # НЕ викликаємо civilian тут - питання будуть надіслані в night_function
                # Це запобігає подвійному надсиланню питань (при старті і під час ночі)
                
                self.print_log(f" Розподіл ролей завершено! Ролей видано: {roles_assigned}/{len(state.membersList)}")
                self.print_log(f" Гра розпочата успішно! Переходимо до ночі...")

                # ── Купальська ніч: вінки-бафи тепер звичайні бафи. ──
                # Беремо активні баф-вінки гравців і споживаємо заряд (1 раз/гру).
                # «Щаслива ніч» діє лише на Аль Капоне — тож списуємо її тільки в нього.
                try:
                    state.kupala_buffs = {}
                    for _uid in state.membersList:
                        for _it in get_active_items_for_player(_uid, chat_id):
                            _eff = (_it.get("effect_data") or {}).get("effect")
                            _bid = _it.get("item_id")
                            if _eff == "kupala_magic":
                                if try_consume_buff(chat_id, _uid, _bid):
                                    state.kupala_buffs[_uid] = "kupala_magic"
                            elif _eff == "lucky_night" and _uid == getattr(state, "all_capone_id", 0):
                                if try_consume_buff(chat_id, _uid, _bid):
                                    state.kupala_buffs[_uid] = "lucky_night"
                    if state.kupala_buffs:
                        self.print_log(f"☀️ Купальська ніч: активні вінки-бафи: {state.kupala_buffs}")
                except Exception as _e:
                    self.print_log(f"Купальська ніч (вінки-бафи): {_e}")

                # night_function will automatically transition to day_function after 60 seconds
                # Питання для МЖ будуть надіслані в night_function
                await self.night_function(message=message, bot=bot)
            except Exception as e:
                await self._unmute_users_muted_during_game(bot, chat_id)
                state.game_active = False
                import traceback
                self.print_log(f" КРИТИЧНА ПОМИЛКА в start_game: {e}")
                self.print_log(f"Traceback: {traceback.format_exc()}")
                print(f" КРИТИЧНА ПОМИЛКА в start_game: {e}\n{traceback.format_exc()}")
                raise
        else:
            self.print_log(
                f"start_game: недостатньо учасників у чаті {chat_id} (members={len(state.membersList)}, MN={state.MN})"
            )


    async def last_message(self, message: Message, bot: Bot):
        user_id = message.from_user.id
        group_chat_id = None
        
        self.print_log(f"📨 last_message викликано! user_id={user_id}, chat_type={message.chat.type}")
        
        # Останнє повідомлення має бути тільки з приватних повідомлень
        if not _chat_is_private_msg(message.chat):
            await bot.send_message(
                chat_id=message.chat.id,
                text=emoji_to_premium(PLAY_LAST_WORD_PRIVATE_ONLY, skip_vip_badges=False),
                parse_mode="html",
            )
            return
        
        # Шукаємо групу: спочатку по всіх станах з is_last_message (щоб не втратити при зміні фази), потім по активних
        group_chat_id = game_state_manager.get_chat_awaiting_last_message_from(user_id)
        if group_chat_id is None:
            active_chats = game_state_manager.get_all_active_chats()
            self.print_log(f"🔍 Активні чати: {active_chats}")
            for chat_id in active_chats:
                state = self._get_state(chat_id)
                allowed = set(getattr(state, "last_word_allowed_ids", set()) or set())
                if (state.is_last_message and state.victim_id == user_id) or (user_id in allowed):
                    group_chat_id = chat_id
                    break
        if group_chat_id is not None:
            self.print_log(f" Знайдено групу для останнього повідомлення: {group_chat_id}")
        
        if not group_chat_id:
            self.print_log(f" Не знайдено групу для user_id={user_id}")
            await bot.send_message(chat_id=user_id, text=" Не знайдено активну гру або ти не маєш права писати останнє повідомлення.")
            return

        async with self._last_word_lock(group_chat_id):
            state = self._get_state(group_chat_id)
            self._ensure_last_word_allowed_ids(state)

            # Додаткова перевірка: чи це саме вбитий гравець
            if user_id not in state.last_word_allowed_ids:
                self.print_log(
                    f" Перевірка не пройдена: allowed={list(state.last_word_allowed_ids)}, user_id={user_id}, victim_id={state.victim_id}"
                )
                if not state.last_word_allowed_ids:
                    await bot.send_message(
                        chat_id=user_id,
                        text=" Останнє слово вже надіслано в групу.",
                    )
                else:
                    await bot.send_message(
                        chat_id=user_id,
                        text=" Ти не маєш права писати останнє повідомлення. Це може зробити тільки загиблий гравець цієї ночі.",
                    )
                return

            # Якщо гравець у БД не позначений як вбитий (наприклад, врятував Чорний Опель) - останнє слово недоступне
            try:
                r = await self._db_fetchone(
                    "SELECT killed FROM users WHERE id = %s",
                    (user_id,),
                )
                if r is not None and (r[0] or 0) == 0:
                    state.last_word_allowed_ids.discard(user_id)
                    if state.victim_id == user_id:
                        state.victim_id = next(iter(state.last_word_allowed_ids), 0)
                    state.is_last_message = bool(state.last_word_allowed_ids)
                    await bot.send_message(
                        chat_id=user_id,
                        text=emoji_to_premium(PLAY_LAST_WORD_ALIVE_ONLY, skip_vip_badges=False),
                        parse_mode="html",
                    )
                    return
            except Exception:
                pass

            # Перевірка: не давати передсмертне повідомлення при закінченні гри; скидаємо стан, щоб далі команди працювали
            if not state.game_active:
                self.print_log(f" Гра вже закінчена, передсмертне повідомлення недоступне - скидаємо is_last_message")
                self._reset_last_word_tracking(state)
                await bot.send_message(
                    chat_id=user_id,
                    text=emoji_to_premium(PLAY_LAST_WORD_GAME_OVER, skip_vip_badges=False),
                    parse_mode="html",
                )
                return

            # Отримуємо ім'я вбитого гравця
            victim_result = await self._db_fetchone(
                "SELECT tg_name FROM users WHERE id = %s",
                (user_id,),
            )
            victim_name = victim_result[0] if victim_result else "Вбитий гравець"

            # Формуємо тег гравця; надсилаємо завжди в group_chat_id
            victim_link = vip_mod.html_user_link(user_id, victim_name)

            self.print_log(f"📤 Надсилання повідомлення в групу {group_chat_id} від {victim_name} (user_id={user_id})")

            async def _send_to_group(text: str):
                """Надіслати текст у групу з однією спробою повтору при TelegramRetryAfter."""
                premium_text = emoji_to_premium(text, skip_vip_badges=False)
                try:
                    await bot.send_message(chat_id=group_chat_id, text=premium_text, parse_mode="html")
                except TelegramRetryAfter as e:
                    self.print_log(f"⚠️ Rate limit при відправці останнього повідомлення, чекаю {e.retry_after}s")
                    await asyncio.sleep(e.retry_after)
                    await bot.send_message(chat_id=group_chat_id, text=premium_text, parse_mode="html")

            message_sent = False
            try:
                if message.text:
                    self.print_log(f"📝 Текст повідомлення: {message.text[:50]}...")
                    await _send_to_group(f"💬 <b>Останнє слово {victim_link}:</b>\n<blockquote>{html.escape(message.text)}</blockquote>")
                    message_sent = True

                if message.caption:
                    self.print_log(f"📝 Підпис до медіа: {message.caption[:50]}...")
                    if not message_sent:
                        await _send_to_group(f"💬 <b>Останнє слово {victim_link}:</b>\n<blockquote>{html.escape(message.caption)}</blockquote>")
                        message_sent = True
                    else:
                        await _send_to_group(f"📝 <i>Підпис:</i> {message.caption}")

                if message.photo or message.video or message.animation or message.sticker or message.voice or message.video_note or message.document:
                    if not message_sent:
                        await _send_to_group(f"💬 <b>Останнє слово {victim_link}:</b>")
                    try:
                        await bot.forward_message(
                            chat_id=group_chat_id,
                            from_chat_id=user_id,
                            message_id=message.message_id
                        )
                        self.print_log(f" Медіа переслано в групу {group_chat_id}")
                        message_sent = True
                    except TelegramRetryAfter as e:
                        await asyncio.sleep(e.retry_after)
                        await bot.forward_message(chat_id=group_chat_id, from_chat_id=user_id, message_id=message.message_id)
                        message_sent = True
                    except Exception as e:
                        self.print_log(f" Помилка пересилання медіа в групу: {e}")
                        if not message_sent:
                            await _send_to_group(f"💬 <b>Останнє слово {victim_link}</b> (медіа)")
                            message_sent = True

                if not message_sent:
                    self.print_log("⚠️ Останнє слово: немає тексту/медіа - режим лишається, просимо повторити")
                    await bot.send_message(
                        chat_id=user_id,
                        text="Надішли текст останнього слова або медіа (фото, стікер тощо). Порожнє повідомлення не зараховується.",
                    )
                    return

            except Exception as e:
                self.print_log(f" ПОМИЛКА надсилання останнього повідомлення в групу {group_chat_id}: {e}")
                import traceback
                self.print_log(f" Traceback: {traceback.format_exc()}")
                try:
                    await bot.send_message(chat_id=user_id, text=f" Помилка надсилання повідомлення: {e}")
                except Exception:
                    pass
                # Не скидаємо is_last_message/victim_id - користувач зможе спробувати ще раз
                return

            # Відключаємо режим тільки якщо щось успішно надіслано
            state.last_word_allowed_ids.discard(user_id)
            state.victim_id = next(iter(state.last_word_allowed_ids), 0)
            state.is_last_message = bool(state.last_word_allowed_ids)
            self.print_log(f"🔄 Режим останнього повідомлення вимкнено для чату {group_chat_id}")

            if _chat_is_private_msg(message.chat):
                await bot.send_message(chat_id=user_id, text=" Твоє останнє повідомлення надіслано в групу!")

    async def mafia_private_message(self, message: Message, bot: Bot):
        """Handle private messages from mafia players and forward to other mafia members"""
        user_id = message.from_user.id
        active_chats = game_state_manager.get_all_active_chats()
        
        # Find the chat where this mafia player is active
        for chat_id in active_chats:
            state = self._get_state(chat_id)
            if not state.game_active:
                continue
            
            # Check if user is Don or Mafia in this game
            is_don = (user_id == state.all_capone_id)
            is_mafia = (user_id in state.mafia_ids)
            
            if not (is_don or is_mafia):
                continue
            
            # Get sender name
            sender_result = await self._db_fetchone(
                "SELECT tg_name FROM users WHERE id = %s",
                (user_id,),
            )
            sender_name = sender_result[0] if sender_result else "Невідомий"
            
            # Determine role name for display
            role_name = "🎩 Аль Капоне" if is_don else "🤵 Мафія"
            
            # Prepare message text
            if message.text:
                message_text = message.text
            elif message.caption:
                message_text = message.caption
            else:
                message_text = "(Медіа повідомлення)"
            
            # Forward message to all other mafia members (Don + all Mafia)
            recipients = []
            if state.all_capone_id and state.all_capone_id != user_id:
                recipients.append(state.all_capone_id)
            for mafia_id in state.mafia_ids:
                if mafia_id != user_id and mafia_id not in recipients:
                    recipients.append(mafia_id)
            
            # Send to all recipients
            forwarded_count = 0
            for recipient_id in recipients:
                # Check if recipient is alive
                recipient_result = await self._db_fetchone(
                    "SELECT killed FROM users WHERE id = %s",
                    (recipient_id,),
                )
                if recipient_result and recipient_result[0] == 1:  # Dead
                    continue
                
                try:
                    # Send text message
                    if message.text:
                        await bot.send_message(
                            chat_id=recipient_id,
                            text=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}",
                            parse_mode="html"
                        )
                    # Forward media messages
                    elif message.photo:
                        await bot.send_photo(
                            chat_id=recipient_id,
                            photo=message.photo[-1].file_id,
                            caption=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}" if message_text != "(Медіа повідомлення)" else f"{role_name} <b>{sender_name}</b>",
                            parse_mode="html"
                        )
                    elif message.video:
                        await bot.send_video(
                            chat_id=recipient_id,
                            video=message.video.file_id,
                            caption=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}" if message_text != "(Медіа повідомлення)" else f"{role_name} <b>{sender_name}</b>",
                            parse_mode="html"
                        )
                    elif message.document:
                        await bot.send_document(
                            chat_id=recipient_id,
                            document=message.document.file_id,
                            caption=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}" if message_text != "(Медіа повідомлення)" else f"{role_name} <b>{sender_name}</b>",
                            parse_mode="html"
                        )
                    elif message.audio:
                        await bot.send_audio(
                            chat_id=recipient_id,
                            audio=message.audio.file_id,
                            caption=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}" if message_text != "(Медіа повідомлення)" else f"{role_name} <b>{sender_name}</b>",
                            parse_mode="html"
                        )
                    elif message.voice:
                        await bot.send_voice(
                            chat_id=recipient_id,
                            voice=message.voice.file_id,
                            caption=f"{role_name} <b>{sender_name}</b>",
                            parse_mode="html"
                        )
                    else:
                        # Fallback for other media types
                        await bot.send_message(
                            chat_id=recipient_id,
                            text=f"{role_name} <b>{sender_name}</b> надіслав(ла) повідомлення",
                            parse_mode="html"
                        )
                    forwarded_count += 1
                except Exception as e:
                    self.print_log(f" Помилка надсилання повідомлення мафії до {recipient_id}: {e}")
            
            # Не надсилаємо підтвердження напарникам - листування без спаму
            if forwarded_count == 0:
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=emoji_to_premium(PLAY_PM_ALLY_DEAD, skip_vip_badges=False),
                        parse_mode="html",
                    )
                except Exception:
                    pass
            
            # Only process first matching game
            break
    
    async def doctor_nurse_private_message(self, message: Message, bot: Bot):
        """Handle private messages from doctor or nurse and forward to the other"""
        user_id = message.from_user.id
        active_chats = game_state_manager.get_all_active_chats()
        
        # Find the chat where this doctor/nurse player is active
        for chat_id in active_chats:
            state = self._get_state(chat_id)
            if not state.game_active:
                continue
            
            # Check if user is Doctor or Nurse in this game
            is_doctor = (user_id == state.doctor_id)
            is_nurse = (user_id == state.nurse_id and state.nurse_id != state.doctor_id)
            
            if not (is_doctor or is_nurse):
                continue
            
            # Get sender name
            sender_result = await self._db_fetchone(
                "SELECT tg_name FROM users WHERE id = %s",
                (user_id,),
            )
            sender_name = sender_result[0] if sender_result else "Невідомий"
            
            # Determine role name for display
            role_name = "💊 Лікар" if is_doctor else "👩‍⚕️ Мед. сестра"
            
            # Prepare message text
            if message.text:
                message_text = message.text
            elif message.caption:
                message_text = message.caption
            else:
                message_text = "(Медіа повідомлення)"
            
            # Forward message to the other (Doctor -> Nurse or Nurse -> Doctor)
            recipient_id = None
            if is_doctor and state.nurse_id and state.nurse_id != state.doctor_id:
                recipient_id = state.nurse_id
            elif is_nurse and state.doctor_id:
                recipient_id = state.doctor_id
            
            if recipient_id:
                # Check if recipient is alive
                recipient_result = await self._db_fetchone(
                    "SELECT killed FROM users WHERE id = %s",
                    (recipient_id,),
                )
                if recipient_result and recipient_result[0] == 1:  # Dead
                    await message.answer(
                        emoji_to_premium(PLAY_PM_ALLY_DEAD, skip_vip_badges=False),
                        parse_mode="html",
                    )
                    return
                
                try:
                    # Send text message
                    if message.text:
                        await bot.send_message(
                            chat_id=recipient_id,
                            text=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}",
                            parse_mode="html"
                        )
                    # Forward media messages
                    elif message.photo:
                        await bot.send_photo(
                            chat_id=recipient_id,
                            photo=message.photo[-1].file_id,
                            caption=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}" if message_text != "(Медіа повідомлення)" else f"{role_name} <b>{sender_name}</b>",
                            parse_mode="html"
                        )
                    elif message.video:
                        await bot.send_video(
                            chat_id=recipient_id,
                            video=message.video.file_id,
                            caption=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}" if message_text != "(Медіа повідомлення)" else f"{role_name} <b>{sender_name}</b>",
                            parse_mode="html"
                        )
                    elif message.document:
                        await bot.send_document(
                            chat_id=recipient_id,
                            document=message.document.file_id,
                            caption=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}" if message_text != "(Медіа повідомлення)" else f"{role_name} <b>{sender_name}</b>",
                            parse_mode="html"
                        )
                    elif message.audio:
                        await bot.send_audio(
                            chat_id=recipient_id,
                            audio=message.audio.file_id,
                            caption=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}" if message_text != "(Медіа повідомлення)" else f"{role_name} <b>{sender_name}</b>",
                            parse_mode="html"
                        )
                    elif message.voice:
                        await bot.send_voice(
                            chat_id=recipient_id,
                            voice=message.voice.file_id,
                            caption=f"{role_name} <b>{sender_name}</b>",
                            parse_mode="html"
                        )
                    else:
                        # Fallback for other media types
                        await bot.send_message(
                            chat_id=recipient_id,
                            text=f"{role_name} <b>{sender_name}</b> надіслав(ла) повідомлення",
                            parse_mode="html"
                        )
                except Exception as e:
                    self.print_log(f"Помилка пересилання повідомлення лікаря/мед. сестри до {recipient_id}: {e}")
                    await message.answer(
                        emoji_to_premium(PLAY_PM_SEND_FAILED, skip_vip_badges=False),
                        parse_mode="html",
                    )
            else:
                await message.answer(
                    emoji_to_premium(PLAY_PM_ALLY_LINK_LOST, skip_vip_badges=False),
                    parse_mode="html",
                )
            return
        
        await message.answer(
            emoji_to_premium(PLAY_PM_NO_CHAT_RIGHTS, skip_vip_badges=False),
            parse_mode="html",
        )

    async def commissioner_sergeant_private_message(self, message: Message, bot: Bot):
        """Handle private messages from Commissioner or Sergeant and forward to the other"""
        user_id = message.from_user.id
        active_chats = game_state_manager.get_all_active_chats()
        for chat_id in active_chats:
            state = self._get_state(chat_id)
            if not state.game_active:
                continue
            is_commissioner = (user_id == state.commissioner_id)
            is_sergeant = (user_id == state.sheriff_id)
            if not (is_commissioner or is_sergeant):
                continue
            sender_result = await self._db_fetchone(
                "SELECT tg_name FROM users WHERE id = %s",
                (user_id,),
            )
            sender_name = sender_result[0] if sender_result else "Невідомий"
            role_name = "🕵️ Комісар Каттані" if is_commissioner else "👮‍♂️ Сержант"
            if message.text:
                message_text = message.text
            elif message.caption:
                message_text = message.caption
            else:
                message_text = "(Медіа повідомлення)"
            recipient_id = state.sheriff_id if is_commissioner else state.commissioner_id
            if not recipient_id:
                await message.answer(
                    emoji_to_premium(PLAY_PM_PARTNER_NONE, skip_vip_badges=False),
                    parse_mode="html",
                )
                return
            recipient_result = await self._db_fetchone(
                "SELECT killed FROM users WHERE id = %s",
                (recipient_id,),
            )
            if recipient_result and recipient_result[0] == 1:
                await message.answer(
                    emoji_to_premium(PLAY_PM_PARTNER_DEAD, skip_vip_badges=False),
                    parse_mode="html",
                )
                return
            try:
                if message.text:
                    await bot.send_message(
                        chat_id=recipient_id,
                        text=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}",
                        parse_mode="html"
                    )
                elif message.photo:
                    await bot.send_photo(
                        chat_id=recipient_id,
                        photo=message.photo[-1].file_id,
                        caption=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}" if message_text != "(Медіа повідомлення)" else f"{role_name} <b>{sender_name}</b>",
                        parse_mode="html"
                    )
                elif message.video:
                    await bot.send_video(
                        chat_id=recipient_id,
                        video=message.video.file_id,
                        caption=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}" if message_text != "(Медіа повідомлення)" else f"{role_name} <b>{sender_name}</b>",
                        parse_mode="html"
                    )
                elif message.document:
                    await bot.send_document(
                        chat_id=recipient_id,
                        document=message.document.file_id,
                        caption=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}" if message_text != "(Медіа повідомлення)" else f"{role_name} <b>{sender_name}</b>",
                        parse_mode="html"
                    )
                elif message.audio:
                    await bot.send_audio(
                        chat_id=recipient_id,
                        audio=message.audio.file_id,
                        caption=f"{role_name} <b>{sender_name}</b>:\n\n{message_text}" if message_text != "(Медіа повідомлення)" else f"{role_name} <b>{sender_name}</b>",
                        parse_mode="html"
                    )
                elif message.voice:
                    await bot.send_voice(
                        chat_id=recipient_id,
                        voice=message.voice.file_id,
                        caption=f"{role_name} <b>{sender_name}</b>",
                        parse_mode="html"
                    )
                else:
                    await bot.send_message(
                        chat_id=recipient_id,
                        text=f"{role_name} <b>{sender_name}</b> надіслав(ла) повідомлення",
                        parse_mode="html"
                    )
            except Exception as e:
                self.print_log(f"Помилка пересилання повідомлення Комісар/Сержант до {recipient_id}: {e}")
                await message.answer(
                    emoji_to_premium(PLAY_PM_SEND_FAILED, skip_vip_badges=False),
                    parse_mode="html",
                )
            return
        await message.answer(
            emoji_to_premium(PLAY_PM_NO_CHAT_RIGHTS, skip_vip_badges=False),
            parse_mode="html",
        )

    async def _is_chat_admin(self, bot: Bot, chat_id: int, user_id: int) -> bool:
        """Чи є користувач адміністратором або власником чату (Telegram)."""
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            return member.status in (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR)
        except Exception:
            return False

    async def silenced_message_handler(self, message: Message, bot: Bot):
        """Delete messages from silenced players in group chat during day phase"""
        # Додаткова перевірка для команд +адмін/-адмін
        if message.text:
            text_lower = message.text.strip().lower()
            if text_lower.startswith("+адмін") or text_lower.startswith("-адмін"):
                print(f"[play] ⚠️ silenced_message_handler: пропускаємо команду '+адмін'")
                return
        
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Адміни можуть писати під час гри, якщо починають повідомлення з !
        if message.text and message.text.strip().startswith("!"):
            if await self._is_chat_admin(bot, chat_id, user_id):
                return  # не видаляємо
        
        state = self._get_state(chat_id)
        
        # Видаляємо повідомлення протягом усієї активної гри.
        # Раніше було прив'язано до `day_active`, через що інколи мовчанка «вимикалась» після переходів фаз.
        
        # Get player name for notification
        result = await self._db_fetchone(
            "SELECT tg_name FROM users WHERE id = %s",
            (user_id,),
        )
        player_name = result[0] if result else "Гравець"
        
        try:
            # Delete the message
            await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            
            # Optionally send a notification (commented out to avoid spam)
            # await bot.send_message(
            #     chat_id=chat_id,
            #     text=f"🤐 <b>{player_name}</b> заблокований і не може писати в чат.",
            #     parse_mode="html"
            # )
        except Exception as e:
            # If we can't delete (e.g., message already deleted, bot not admin), just log
            self.print_log(f"⚠️ Не вдалося видалити повідомлення від заблокованого гравця {user_id}: {e}")

    async def dead_player_message_handler(self, message: Message, bot: Bot):
        """Під час гри: видалити повідомлення від мертвого гравця (коли увімкнена мовчанка для мертвих)."""
        chat_id = message.chat.id
        user_id = message.from_user.id
        state = self._get_state(chat_id)
        silence_dead_players_enabled, _ = await self._get_silence_settings_async(chat_id, state)
        if not silence_dead_players_enabled:
            return
        # Адміни чату можуть писати під час гри, якщо починають повідомлення з !
        if message.text and message.text.strip().startswith("!"):
            if await self._is_chat_admin(bot, chat_id, user_id):
                return
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        except Exception as e:
            self.print_log(f"⚠️ Не вдалося видалити повідомлення від мертвого гравця {user_id}: {e}")

    async def _unmute_users_muted_during_game(self, bot: Bot, chat_id: int):
        """Розмутити всіх, хто був замучений під час гри (не гравці). Викликати перед reset_for_new_night / reset_for_new_game."""
        state = self._get_state(chat_id)
        to_unmute = list(getattr(state, "muted_during_game", None) or [])
        if not to_unmute:
            return
        state.muted_during_game.clear()
        full_permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        )
        for user_id in to_unmute:
            try:
                await bot.restrict_chat_member(chat_id, user_id, permissions=full_permissions)
                self.print_log(f" Розмучено не-гравця {user_id} в чаті {chat_id} (при скиданні фази/гри).")
            except Exception as e:
                self.print_log(f"⚠️ Не вдалося розмутити {user_id} в чаті {chat_id}: {e}")

    async def non_player_message_handler(self, message: Message, bot: Bot):
        """Під час гри: видалити повідомлення від тих, хто не грає, мут на 1 хв, написати в ПП. Адміни з ! - не чіпаємо."""
        chat_id = message.chat.id
        user_id = message.from_user.id
        state = self._get_state(chat_id)
        _, silence_non_players_enabled = await self._get_silence_settings_async(chat_id, state)
        if not silence_non_players_enabled:
            return
        # Адміни чату можуть писати під час гри, якщо починають повідомлення з !
        if message.text and message.text.strip().startswith("!"):
            if await self._is_chat_admin(bot, chat_id, user_id):
                return  # не видаляємо і не мутимо
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
        except Exception as e:
            self.print_log(f"⚠️ Не вдалося видалити повідомлення від не-гравця {user_id}: {e}")
        # Unix timestamp для until_date (Telegram не завжди надійно знімає мут по часу - тому через 60 с явно розмутимо)
        until_date = int((datetime.utcnow() + timedelta(seconds=60)).timestamp())
        if not hasattr(state, "muted_during_game"):
            state.muted_during_game = set()
        state.muted_during_game.add(user_id)
        try:
            await bot.restrict_chat_member(
                chat_id,
                user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date,
            )
        except Exception as e:
            self.print_log(f"⚠️ Не вдалося замутити не-гравця {user_id}: {e}")
        # Явно зняти мут через 60 секунд (Telegram іноді не знімає автоматично по until_date)
        async def unmute_after_minute():
            await asyncio.sleep(60)
            try:
                await bot.restrict_chat_member(
                    chat_id,
                    user_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                    ),
                )
                s = self._get_state(chat_id)
                if getattr(s, "muted_during_game", None) is not None:
                    s.muted_during_game.discard(user_id)
                self.print_log(f" Розмучено не-гравця {user_id} в чаті {chat_id} після 1 хв.")
            except Exception as e:
                self.print_log(f"⚠️ Не вдалося розмутити не-гравця {user_id} після 1 хв: {e}")
        asyncio.create_task(unmute_after_minute())

    async def all_capone(self, message: Message, bot: Bot, chat_id: int):
        state = self._get_state(chat_id)
        list_of_victim_buttons = InlineKeyboardBuilder()
        added_buttons = 0
        # #region agent log
        _log_debug('debug-session', 'run1', 'K1', 'play.py:all_capone:entry', 'all_capone started', {
            'chat_id': chat_id,
            'all_capone_id': state.all_capone_id,
            'membersList_len': len(state.membersList),
            'list_of_victim_len': len(state.list_of_victim)
        })
        # #endregion

        devil_contract_holders = getattr(state, "devil_contract_holders", set())
        devil_id = getattr(state, "devil_id", 0)
        allow_friendly_fire = await self._is_friendly_fire_allowed_async(chat_id, state)
        for id in state.membersList:
            if id != state.all_capone_id and id not in devil_contract_holders and id != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed, role FROM users WHERE id = %s",
                    (id,),
                )
                if not result:
                    continue
                
                member_name, killed, member_role = result
                # Обмеження: без дружнього вогню Аль Капоне не може вбивати мафію
                if not allow_friendly_fire and member_role == "Мафія":
                    continue  # Пропускаємо мафію, якщо friendly fire вимкнено
                
                # Only show alive players as potential victims
                if killed == 0:
                    list_of_victim_buttons.button(text=member_name, callback_data=f"{chat_id}_{id}_killed")
                    list_of_victim_buttons.adjust(1)
                    added_buttons += 1
                    if id not in state.list_of_victim:
                        state.list_of_victim.append(id)

        # Додаємо кнопку пропуску, якщо налаштування дозволяє
        allow_skip = await self._is_skip_night_action_allowed_async(chat_id, state)
        self.print_log(f"🔍 all_capone: chat_id={chat_id}, allow_skip={allow_skip}")
        if allow_skip:
            list_of_victim_buttons.button(text="⏭️ Пропустити", callback_data=f"skip_night_mafia_{chat_id}")
            self.print_log(f"✅ all_capone: Додано кнопку пропуску для chat_id={chat_id}")

        state.choose_who_you_will_kill = await bot.send_message(
            chat_id=state.all_capone_id,
            text=(
                "🤔 Хто перейшов тобі дорогу сьогодні?"
            ),
            reply_markup=list_of_victim_buttons.as_markup(),
            parse_mode="html"
        )
        # #region agent log
        _log_debug('debug-session', 'run1', 'K1', 'play.py:all_capone:buttons', 'Victim buttons built', {
            'added_buttons': added_buttons,
            'list_of_victim_len': len(state.list_of_victim)
        })
        # #endregion

        # #region agent log
        _log_debug('debug-session', 'run1', 'K1', 'play.py:all_capone:registered', 'Don victim buttons (unified night_standard_target_callback)', {
            'registered_count': len(state.list_of_victim)
        })
        # #endregion

    async def night_standard_target_callback(self, callback: CallbackQuery, bot: Bot):
        """Єдині обробники для кнопок виду chat_target_suffix (без накопичення хендлерів щоночі)."""
        m = re.match(
            r"^(-?\d+)_(\d+)_(protect|check|maniac|homeless|lawyer|clown|infect|deceiver|sadistic_heal|sadistic_kill|maf_killed|killed)$",
            callback.data or "",
        )
        if not m:
            return
        chat_id = int(m.group(1))
        target_id = int(m.group(2))
        suffix = m.group(3)
        uid = callback.from_user.id
        state = self._get_state(chat_id)
        # Після swap ролей (Клоун) ID ролей у state могли застаріти.
        # Синхронізуємо перед перевіркою "це меню тільки для ролі X".
        try:
            await self._refresh_state_role_ids_async(state)
        except Exception:
            pass
        if await self._is_clown_role_temporarily_blocked(state, uid):
            await callback.answer("🤡 Після зміни ролі Клоуном дія доступна з наступної ночі.", show_alert=True)
            return
        if not state.game_active:
            await callback.answer(" Ця гра вже завершена. Нічні дії більше недоступні.", show_alert=True)
            return
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась.", show_alert=True)
            return

        if suffix == "killed":
            if uid != getattr(state, "all_capone_id", 0):
                await callback.answer("Це меню тільки для Аль Капоне.", show_alert=True)
                return
            await self._apply_don_kill_pick(callback, bot, state, chat_id, target_id)
            return
        if suffix == "maf_killed":
            if uid not in (state.mafia_ids or []):
                await callback.answer("Це меню тільки для гравця з роллю Мафія.", show_alert=True)
                return
            await self._apply_mafia_kill_pick(callback, bot, state, chat_id, target_id, uid)
            return
        if suffix == "protect":
            if uid != getattr(state, "guardian_id", 0):
                await callback.answer("Це меню тільки для гравця з роллю Тілоохоронець.", show_alert=True)
                return
            await self._apply_guardian_protect_pick(callback, bot, state, chat_id, target_id)
            return
        if suffix == "check":
            if uid != getattr(state, "sheriff_id", 0):
                await callback.answer("Це меню тільки для гравця з роллю Комісар Каттані.", show_alert=True)
                return
            await self._apply_sheriff_check_pick(callback, bot, state, chat_id, target_id)
            return
        if suffix == "maniac":
            if uid != getattr(state, "maniac_id", 0):
                await callback.answer("Це меню тільки для гравця з роллю Маніяк.", show_alert=True)
                return
            await self._apply_maniac_kill_pick(callback, bot, state, chat_id, target_id)
            return
        if suffix == "homeless":
            if uid != getattr(state, "homeless_id", 0):
                await callback.answer("Це меню тільки для гравця з роллю Волоцюга.", show_alert=True)
                return
            await self._apply_homeless_pick(callback, bot, state, chat_id, target_id)
            return
        if suffix == "lawyer":
            if uid != getattr(state, "lawyer_id", 0):
                await callback.answer("Це меню тільки для гравця з роллю Адвокат.", show_alert=True)
                return
            await self._apply_lawyer_pick(callback, bot, state, chat_id, target_id)
            return
        if suffix == "clown":
            cid = getattr(state, "clown_id", 0)
            if uid != cid:
                await callback.answer("Ця дія тільки для Клоуна.", show_alert=True)
                return
            await self._apply_clown_pick(callback, bot, state, chat_id, target_id)
            return
        if suffix == "infect":
            if uid not in (getattr(state, "infected_ids", None) or []):
                await callback.answer("Це меню тільки для гравця з роллю Заражений.", show_alert=True)
                return
            await self._apply_infected_pick(callback, bot, state, chat_id, target_id, uid)
            return
        if suffix == "deceiver":
            if uid != getattr(state, "deceiver_id", 0):
                await callback.answer("Це меню тільки для гравця з роллю Брехун.", show_alert=True)
                return
            await self._apply_deceiver_pick(callback, bot, state, chat_id, target_id)
            return
        if suffix == "sadistic_heal":
            if uid != getattr(state, "sadistic_doctor_id", 0):
                await callback.answer("Це меню тільки для гравця з роллю Доктор-садист.", show_alert=True)
                return
            await self._apply_sadistic_heal_pick(callback, bot, state, chat_id, target_id)
            return
        if suffix == "sadistic_kill":
            if uid != getattr(state, "sadistic_doctor_id", 0):
                await callback.answer("Це меню тільки для гравця з роллю Доктор-садист.", show_alert=True)
                return
            await self._apply_sadistic_kill_pick(callback, bot, state, chat_id, target_id)
            return

    async def _apply_don_kill_pick(self, callback: CallbackQuery, bot: Bot, state: GameState, chat_id: int, id: int):
        _log_debug('debug-session', 'run1', 'K2', 'play.py:_apply_don_kill_pick', 'Kill button clicked', {
            'chat_id': chat_id,
            'victim_id': id,
            'from_user_id': callback.from_user.id,
            'mafia_action_taken': state.mafia_action_taken,
            'callback_data': callback.data
        })
        if state.mafia_action_taken:
            await callback.answer("Ти вже зробив свій вибір цієї ночі!", show_alert=True)
            return
        if id == getattr(state, "devil_id", 0):
            await callback.answer("Диявола неможливо вбити.", show_alert=True)
            return

        result = await self._db_fetchone(
            "SELECT killed, tg_name, role FROM users WHERE id = %s",
            (id,),
        )
        if not result:
            await callback.answer("Помилка: гравець не знайдений!", show_alert=True)
            return

        killed, member_name, role = result
        if killed == 1:
            await callback.answer("Не можна вбити вже мертвого гравця!", show_alert=True)
            return

        if role == "Перевертень":
            await self._set_player_role_async(id, "Мафія")
            await bot.send_message(chat_id=id, text="🐺 Тебе атакував Дон - ти стаєш мафією!")
            await callback.answer("Перевертень перетворився на мафію!", show_alert=True)
            return

        await bot.edit_message_text(
            chat_id=state.all_capone_id,
            message_id=state.choose_who_you_will_kill.message_id,
            text=emoji_to_premium(f"🎩 Ти обрав: {member_name}"),
            parse_mode="html",
            reply_markup=None,
        )

        state.victim_id = id
        state.mafia_action_taken = True
        self._record_visit(state, state.all_capone_id, id, "kill_don")

        try:
            mafia_recipients = [mid for mid in (state.mafia_ids or []) if mid and mid != state.all_capone_id]
            if mafia_recipients:
                victim_row = await self._db_fetchone(
                    "SELECT tg_name FROM users WHERE id = %s",
                    (id,),
                )
                victim_name = victim_row[0] if victim_row and victim_row[0] else "гравець"
                notify_text = f"<b>Аль Капоне</b> обрав ціль цієї ночі:\n\n<b>{html.escape(victim_name)}</b>"
                for mid in mafia_recipients:
                    try:
                        r_alive = await self._db_fetchone(
                            "SELECT killed FROM users WHERE id = %s",
                            (mid,),
                        )
                        if r_alive and int(r_alive[0]) == 1:
                            continue
                        await bot.send_message(chat_id=mid, text=notify_text, parse_mode="html")
                    except Exception:
                        pass
        except Exception:
            pass

        don_id = state.all_capone_id
        if don_id and getattr(state, 'devil_contract_pending', 0) == don_id and don_id in getattr(state, 'devil_contract_holders', set()) and not getattr(state, 'devil_contract_action_taken', False):
            state.devil_contract_action_taken = True
            state.devil_souls_brought = getattr(state, 'devil_souls_brought', 0) + 1
            souls = state.devil_souls_brought
            if id not in getattr(state, "devil_kill_targets", []):
                state.devil_kill_targets.append(id)
            devil_id = getattr(state, 'devil_id', 0)
            if souls >= 2:
                state.devil_successful_contracts = getattr(state, 'devil_successful_contracts', 0) + 1
                state.devil_contract_pending = 0
            if devil_id:
                try:
                    if souls == 1:
                        await bot.send_message(chat_id=devil_id, text=emoji_to_premium("Ти відчуваєш, як щось згасає.\n🩸 Одна душа принесена.\nПрогрес контракту: 1 / 2\nЩе одна… і угода буде завершена."), parse_mode="html")
                    elif souls >= 2:
                        await bot.send_message(
                            chat_id=devil_id,
                            text=emoji_to_premium(
                                "Друга душа падає в безодню.\n🔥 Контракт виконано.\nПрогрес: 2 / 2\nПекло прийняло свою плату."
                            ),
                            parse_mode="html",
                        )
                except Exception:
                    pass
            if souls == 1:
                try:
                    await bot.send_message(chat_id=don_id, text="«Ти вже відчуваєш, як стаєш менш людиною»", parse_mode="html")
                except Exception:
                    pass
            elif souls >= 2:
                try:
                    await bot.send_message(
                        chat_id=don_id,
                        text=emoji_to_premium(
                            "Друга душа падає в безодню.\n🔥 Контракт виконано.\nПрогрес: 2 / 2\n«Тепер ти лише тінь того, ким був.»"
                        ),
                        parse_mode="html",
                    )
                except Exception:
                    pass

        await callback.answer("Вибір зроблено! ")


    async def civilian(self, message: Message, bot: Bot, chat_id: int):
        state = self._get_state(chat_id)
        self.print_log(f"Відправляю питання МЖ: {state.civilian_ids}")
        
        # Перевіряємо, чи вже надсилали питання цим МЖ (щоб уникнути подвійного надсилання)
        # Очищаємо старі повідомлення перед новою ніччю (питань МЖ; message_list_of_candidates - для голосування)
        if not hasattr(state, "civilian_question_messages"):
            state.civilian_question_messages = {}
        state.civilian_question_messages.clear()
        state.civilian_questions.clear()
        
        # Список питань для МЖ
        question_and_two_answers = [
            ("Чи любиш ти пити каву зранку?", "Так", "Ні"), 
            ("Чи вмієш ти готувати яєчню?", "Так", "Ні"), 
            ("Ти віддаєш перевагу перегляду фільмів вдома, чи кінотеатрі?", "Вдома", "В кінотеатрі"),
            ("Ти полюбляєш вечірні прогулянки?", "Так", "Ні"), 
            ("Ти за паперові чи електронні книги?", "Паперові", "Електронні"), 
            ("Ти слухаєш подкасти?", "Так", "Ні"), 
            ("Ти маєш улюблену музичну групу, чи виконавців?", "Так", "Ні"),
            ("Чи часто ти відвідуєш музеї/виставки?", "Так", "Ні"), 
            ("У тебе є домашні улюбленці?", "Так", "Ні"), 
            ("Любиш подорожі на велосипеді?", "Так", "Ні")
        ]
        
        # Надсилаємо одне випадкове питання кожному МЖ (окреме сховище - щоб голосування не перезаписувало)
        for id in state.civilian_ids:
            # Не надсилаємо тим, хто вже покинув гру
            if id not in state.membersList:
                continue
            # Перевіряємо, чи гравець живий
            killed_result = await self._db_fetchone(
                "SELECT killed FROM users WHERE id = %s",
                (id,),
            )
            if killed_result and killed_result[0] == 1:
                continue  # Пропускаємо мертвих гравців
            
            # Кожен МЖ отримує своє випадкове питання
            list_question = random.choice(question_and_two_answers)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=list_question[1], callback_data="answer_1"), 
                 InlineKeyboardButton(text=list_question[2], callback_data="answer_2")]
            ])
            
            # Надсилаємо питання конкретному МЖ (тільки якщо ще не надсилали)
            if id not in state.civilian_question_messages:
                try:
                    msg = await bot.send_message(
                        chat_id=id, 
                        text=f"{list_question[0]}", 
                        reply_markup=keyboard
                    )
                    # Зберігаємо в окремому словнику, щоб голосування (message_list_of_candidates) не перезаписало
                    state.civilian_question_messages[id] = msg
                    state.civilian_questions[id] = list_question
                    # Також зберігаємо для сумісності зі старим кодом
                    state.list_question = list_question
                    state.message_for_civilian = msg
                except Exception as e:
                    self.print_log(f"Error sending question to civilian {id}: {e}")


    async def yes_btn(self, callback: CallbackQuery, bot: Bot):
        user_id = callback.from_user.id
        for chat_id in game_state_manager.get_all_active_chats():
            state = game_state_manager.get_state(chat_id)
            if user_id not in state.membersList:
                continue
            # Використовуємо окреме сховище для повідомлень з питанням МЖ (не message_list_of_candidates)
            if hasattr(state, "civilian_question_messages") and user_id in state.civilian_question_messages and user_id in state.civilian_questions:
                msg = state.civilian_question_messages[user_id]
                list_question = state.civilian_questions[user_id]
                try:
                    await bot.edit_message_text(
                        chat_id=user_id,
                        message_id=msg.message_id,
                        text=f"{list_question[0]}\nТи обрав: {list_question[1]}"
                    )
                except Exception:
                    pass
                await callback.answer()
                return
        await callback.answer("Питання вже не актуальне або гру завершено.", show_alert=True)

    async def no_btn(self, callback: CallbackQuery, bot: Bot):
        user_id = callback.from_user.id
        for chat_id in game_state_manager.get_all_active_chats():
            state = game_state_manager.get_state(chat_id)
            if user_id not in state.membersList:
                continue
            if hasattr(state, "civilian_question_messages") and user_id in state.civilian_question_messages and user_id in state.civilian_questions:
                msg = state.civilian_question_messages[user_id]
                list_question = state.civilian_questions[user_id]
                try:
                    await bot.edit_message_text(
                        chat_id=user_id,
                        message_id=msg.message_id,
                        text=f"{list_question[0]}\nТи обрав: {list_question[2]}"
                    )
                except Exception:
                    pass
                await callback.answer()
                return
        await callback.answer("Питання вже не актуальне або гру завершено.", show_alert=True)


    async def doctor(self, message: Message, bot: Bot, chat_id: int):
        state = self._get_state(chat_id)

        list_of_patient_buttons = InlineKeyboardBuilder()
        devil_id = getattr(state, "devil_id", 0)
        # Самолікування - 1 раз за гру
        if not getattr(state, "doctor_self_heal_used", False):
            list_of_patient_buttons.button(
                text="💊 Самолікування (1 раз за гру)",
                callback_data=f"{state.doctor_id}_cured"
            )
        for id in state.membersList:
            if id == devil_id or id == state.doctor_id:
                continue
            result = await self._db_fetchone(
                "SELECT tg_name, killed FROM users WHERE id = %s",
                (id,),
            )
            if not result:
                continue
            member_name, killed = result
            if killed == 0:
                list_of_patient_buttons.button(text=member_name, callback_data=f"{id}_cured")
                if id not in state.list_of_patient:
                    state.list_of_patient.append(id)
        list_of_patient_buttons.adjust(1)

        # Додаємо кнопку пропуску, якщо налаштування дозволяє
        allow_skip = await self._is_skip_night_action_allowed_async(chat_id, state)
        self.print_log(f"🔍 doctor: chat_id={chat_id}, allow_skip={allow_skip}")
        if allow_skip:
            list_of_patient_buttons.button(text="⏭️ Пропустити", callback_data=f"skip_night_doctor_{chat_id}")
            self.print_log(f"✅ doctor: Додано кнопку пропуску для chat_id={chat_id}")

        markup = list_of_patient_buttons.as_markup()
        rows = getattr(markup, "inline_keyboard", None) or []
        if not rows:
            self.print_log(
                f"⚠️ Лікар {state.doctor_id}: порожня клавіатура (немає цілей / усі відфільтровані)"
            )
            try:
                await bot.send_message(
                    chat_id=state.doctor_id,
                    text=(
                        "💊 <b>Лікар</b>\n\n"
                        "Цієї ночі немає доступних цілей для лікування (немає інших живих гравців "
                        "або обмеження ролі). Ніч може продовжитись без твого вибору."
                    ),
                    parse_mode="html",
                )
            except TelegramBadRequest as e:
                if "chat not found" in str(e).lower() or "bot can't initiate" in str(e).lower():
                    self.print_log(
                        f"⚠️ Лікар {state.doctor_id}: не вдалося надіслати ПП - відкрий чат з ботом і натисни /start"
                    )
                else:
                    self.print_log(f"⚠️ Лікар send_message: {e}")
            except Exception as e:
                self.print_log(f"⚠️ Лікар send_message: {e}")
            state.doctor_action_taken = True
            return

        try:
            state.choose_who_you_will_cured = await bot.send_message(
                chat_id=state.doctor_id,
                text=(
                    "🤔 Кого лікуватимемо сьогодні?\n\n"
                    "<i>Натисни кнопку нижче.</i>"
                ),
                reply_markup=markup,
                parse_mode="html",
            )
        except TelegramBadRequest as e:
            self.print_log(f"⚠️ Не вдалося надіслати меню Лікарю {state.doctor_id}: {e}")
            state.doctor_action_taken = True
        except Exception as e:
            self.print_log(f"⚠️ Не вдалося надіслати меню Лікарю: {e}")
            state.doctor_action_taken = True


    async def chosen_patient_handler(self, callback: CallbackQuery, bot: Bot):
        """Handle doctor patient selection callback"""
        user_id = callback.from_user.id
        callback_data = callback.data
        
        # Extract patient ID from callback_data (format: "{patient_id}_cured")
        try:
            patient_id = int(callback_data.replace("_cured", ""))
        except ValueError:
            await callback.answer(" Помилка: некоректні дані!", show_alert=True)
            return
        
        # Find which chat this belongs to
        for chat_id in game_state_manager.get_all_active_chats():
            state = self._get_state(chat_id)
            if state.doctor_id == user_id and state.choose_who_you_will_cured:
                # Приймаємо callback лише з актуального меню вибору Лікаря.
                # Інакше старі кнопки з попередніх ночей можуть перезаписати ціль лікування.
                current_msg = getattr(state, "choose_who_you_will_cured", None)
                cb_msg = getattr(callback, "message", None)
                if not current_msg or not cb_msg or int(getattr(cb_msg, "message_id", 0) or 0) != int(getattr(current_msg, "message_id", 0) or 0):
                    await callback.answer("Це старе меню лікування. Відкрий актуальне повідомлення від бота.", show_alert=True)
                    return
                if await self._is_clown_role_temporarily_blocked(state, user_id):
                    await callback.answer("🤡 Після зміни ролі Клоуном дія доступна з наступної ночі.", show_alert=True)
                    return
                # Якщо гра вже завершена або ніч закінчилась - блокуємо кнопку
                if not state.game_active:
                    await callback.answer(" Ця гра вже завершена. Нічні дії більше недоступні.", show_alert=True)
                    return
                if getattr(state, "day_active", False):
                    await callback.answer("🌅 Ніч уже закінчилась. Лікування більше неможливе.", show_alert=True)
                    return
                # Found the correct game
                await self._handle_patient_selection(callback, bot, patient_id, chat_id)
                return
        
        # If not found, try to handle anyway
        await callback.answer(" Не знайдено активну гру!", show_alert=True)
    
    async def _handle_patient_selection(self, callback: CallbackQuery, bot: Bot, patient_id: int, chat_id: int):
        """Handle the actual patient selection logic"""
        state = self._get_state(chat_id)
        user_id = callback.from_user.id
        heal_lock = self._doctor_heal_locks.setdefault(chat_id, asyncio.Lock())
        async with heal_lock:
            await self._handle_patient_selection_inner(callback, bot, patient_id, chat_id, state, user_id)

    async def _handle_patient_selection_inner(
        self,
        callback: CallbackQuery,
        bot: Bot,
        patient_id: int,
        chat_id: int,
        state: GameState,
        user_id: int,
    ):
        """Логіка вибору пацієнта під lock чату (без подвійних повідомлень у групу)."""
        # Додаткова перевірка безпеки на випадок ручного виклику
        if not state.game_active:
            await callback.answer(" Ця гра вже завершена. Нічні дії більше недоступні.", show_alert=True)
            return
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась. Лікування більше неможливе.", show_alert=True)
            return

        # Prevent duplicate actions
        if state.doctor_action_taken:
            await callback.answer("Ти вже зробив свій вибір цієї ночі!", show_alert=True)
            return
        if patient_id == getattr(state, "devil_id", 0):
            await callback.answer("До Диявола ніхто не може ходити.", show_alert=True)
            return
        
        if patient_id == state.doctor_id and state.doctor_self_heal_used:
            await callback.answer("Самолікування можна використати лише 1 раз за гру!", show_alert=True)
            return
        
        # Validate target exists and is alive
        result = await self._db_fetchone(
            "SELECT killed, tg_name, role FROM users WHERE id = %s",
            (patient_id,),
        )
        if not result:
            await callback.answer("Помилка: гравець не знайдений!", show_alert=True)
            return
        
        killed, member_name, role = result
        if killed == 1:
            await callback.answer("Не можна лікувати вже мертвого гравця!", show_alert=True)
            return
        
        if role == "Перевертень":
            await self._set_player_role_async(patient_id, "Мед. сестра")
            await bot.send_message(chat_id=patient_id, text="🐺 Тебе лікували - ти стаєш Мед. сестрою!")
        
        safe_member_name = html.escape(str(member_name))
        try:
            # Спершу прибираємо кнопки з того повідомлення, на якому натиснули callback.
            # Це гарантує зникнення клавіатури навіть якщо редагування тексту не вдасться.
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        try:
            await bot.edit_message_text(
                chat_id=state.doctor_id,
                message_id=state.choose_who_you_will_cured.message_id,
                text=(
                    f" <b>Вибір зроблено!</b> \n\n"
                    f"💊 <b>Ти обрав:</b> <code>{safe_member_name}</code>\n\n"
                ),
                parse_mode="html",
                reply_markup=None,
            )
        except Exception as e:
            self.print_log(f"⚠️ Не вдалося оновити повідомлення вибору Лікаря: {e}")
        
        if chat_id:
            try:
                is_former_nurse = state.doctor_was_nurse
                # Тематичні налаштування: якщо ввімкнено показ нічних цілей - показуємо, кого лікує
                _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
                if show_night_targets:
                    base_text = "🚑 <b>Карета швидкої допомоги</b> знову мчить містом." if is_former_nurse else "🚑 <b>Карета швидкої допомоги</b> помчала містом."
                    text = f"{base_text} Лікуємо <code>{safe_member_name}</code>."
                else:
                    text = "🚑 <b>Карета швидкої допомоги</b> знову мчить містом." if is_former_nurse else "🚑 <b>Карета швидкої допомоги</b> помчала містом."
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="html"
                )
            except:
                pass
        
        state.patient_id = patient_id
        state.doctor_action_taken = True
        self._record_visit(state, state.doctor_id, patient_id, "heal")

        if patient_id == state.doctor_id:
            state.doctor_self_heal_used = True

        await callback.answer(" Вибір зараховано!")
        self.print_log(f"💊 Лікар {user_id} обрав пацієнта {patient_id} ({member_name})")

    async def nurse_action(self, message: Message, bot: Bot, chat_id: int, nurse_id: int):
        """Handle night action for Nurse when Doctor is alive"""
        state = self._get_state(chat_id)
        
        # Перевіряємо, чи Лікар живий
        if state.doctor_id and state.doctor_id in state.membersList:
            doctor_result = await self._db_fetchone(
                "SELECT killed FROM users WHERE id = %s",
                (state.doctor_id,),
            )
            doctor_alive = doctor_result and doctor_result[0] == 0 if doctor_result else False
        else:
            doctor_alive = False
        
        if doctor_alive:
            # Лікар живий - Мед. сестра не виконує дій (без додаткового повідомлення).
            return
        else:
            # Лікаря вбили - Мед. сестра стає Лікарем
            # Це має оброблятися в _kill_player, але якщо це перша ніч після смерті
            if state.doctor_id == 0 or (state.doctor_id and state.doctor_id not in state.membersList):
                # Мед. сестра вже стала Лікарем в _kill_player, тому викликаємо doctor
                await self.doctor(message, bot, chat_id)

    async def guardian_angel(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        state = self._get_state(chat_id)
        list_of_guardian_buttons = InlineKeyboardBuilder()
        added_buttons = 0
        # #region agent log
        _log_debug('debug-session', 'run1', 'GUA', 'play.py:guardian_angel:entry', 'guardian_angel started', {
            'chat_id': chat_id,
            'player_id': player_id,
            'membersList_len': len(state.membersList)
        })
        # #endregion
        devil_id = getattr(state, "devil_id", 0)
        for pid in state.membersList:
            if pid != player_id and pid != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if not result:
                    continue
                member_name, killed = result
                if killed == 0:
                    list_of_guardian_buttons.button(text=member_name, callback_data=f"{chat_id}_{pid}_protect")
                    added_buttons += 1
                    if pid not in state.list_of_guardian:
                        state.list_of_guardian.append(pid)
        list_of_guardian_buttons.adjust(1)
        state.choose_who_you_will_protect = await bot.send_message(
            chat_id=player_id,
            text="😇 <b>Захист</b>\n\nОбери гравця, якого ти хочеш захистити цієї ночі:",
            reply_markup=list_of_guardian_buttons.as_markup(),
            parse_mode="html"
        )
        # #region agent log
        _log_debug('debug-session', 'run1', 'GUA', 'play.py:guardian_angel:buttons', 'Guardian buttons built', {
            'added_buttons': added_buttons,
            'list_of_guardian_len': len(state.list_of_guardian)
        })
        # #endregion
        # #region agent log
        _log_debug('debug-session', 'run1', 'GUA', 'play.py:guardian_angel:registered', 'Guardian (unified night_standard_target_callback)', {
            'registered_count': len(state.list_of_guardian)
        })
        # #endregion

    async def _apply_guardian_protect_pick(
        self, callback: CallbackQuery, bot: Bot, state: GameState, chat_id: int, target_id: int
    ):
        player_id = state.guardian_id
        if state.guardian_action_taken:
            await callback.answer("Ти вже зробив свій вибір цієї ночі!", show_alert=True)
            return
        if target_id == getattr(state, "devil_id", 0):
            await callback.answer("До Диявола ніхто не може ходити.", show_alert=True)
            return
        result = await self._db_fetchone(
            "SELECT killed, tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        if not result:
            await callback.answer("Помилка: гравець не знайдений!", show_alert=True)
            return
        killed, member_name = result
        if killed == 1:
            await callback.answer("Не можна захищати вже мертвого гравця!", show_alert=True)
            return
        await bot.edit_message_text(
            chat_id=player_id,
            message_id=state.choose_who_you_will_protect.message_id,
            text=(
                f" <b>Вибір зроблено!</b> \n\n"
                f"😇 <b>Ти обрав:</b> <code>{member_name}</code>\n\n"
                f"💡 <i>Захист активовано на цю ніч.</i>"
            ),
            parse_mode="html",
            reply_markup=None,
        )
        state.guardian_protect_id = target_id
        state.guardian_action_taken = True
        self._record_visit(state, player_id, target_id, "protect")
        try:
            _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
            if show_night_targets:
                text = f"🛡️ <b>Тілоохоронець</b> захищає <code>{member_name}</code>."
            else:
                text = f"🛡️ <b>Тілоохоронець</b> зробив свій вибір"
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="html")
        except Exception:
            pass
        await callback.answer("Вибір зроблено! ")

    async def _get_players_with_parfum(self, chat_id: int, state) -> list[tuple[int, str]]:
        """Повертає список (user_id, buff_id) гравців (живих, не Коханка), у яких активні "парфуми"."""
        result: list[tuple[int, str]] = []
        for pid in state.membersList:
            if pid == getattr(state, "prostitute_id", 0):
                continue
            row = await self._db_fetchone(
                "SELECT killed FROM users WHERE id = %s",
                (pid,),
            )
            if not row or row[0] != 0:
                continue
            items = get_active_items_for_player(pid, chat_id)
            item_ids = {item.get("item_id") for item in items}
            # звичайний парфум з магазину
            if "parfum" in item_ids:
                if pid not in getattr(state, "parfum_shop_used_this_game", set()):
                    result.append((pid, "parfum"))
                continue
            # портальні "парфуми Gucci" (впливають на перевірку Комісара)
            if "portal_perfume_gucci" in item_ids:
                result.append((pid, "portal_perfume_gucci"))
        return result

    def _prostitute_has_black_cat(self, player_id: int, chat_id: int) -> bool:
        """Чи має гравець активний баф 🐈‍⬛ Чорний кіт."""
        items = get_active_items_for_player(player_id, chat_id)
        return any(item.get("item_id") == "black_cat" for item in items)

    async def _strip_message_reply_markup(self, bot: Bot, chat_id: int, msg) -> None:
        """Прибирає inline-кнопки з повідомлення (якщо ще лишились після нюху кота)."""
        if not msg or not chat_id:
            return
        mid = getattr(msg, "message_id", None)
        if not mid:
            return
        try:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=mid, reply_markup=None)
        except Exception:
            pass

    async def _send_prostitute_target_choice(self, bot: Bot, chat_id: int, player_id: int) -> bool:
        """Відправляє Коханці список гравців для блоку. Повертає True якщо список не порожній і повідомлення відправлено."""
        state = self._get_state(chat_id)
        list_of_block_buttons = InlineKeyboardBuilder()
        devil_id = getattr(state, "devil_id", 0)
        prostitute_last_target_id = getattr(state, "prostitute_last_target_id", 0)
        state.list_of_block = []
        for pid in state.membersList:
            if pid != player_id and pid != devil_id and pid != prostitute_last_target_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if not result:
                    continue
                member_name, killed = result
                if killed == 0:
                    list_of_block_buttons.button(text=member_name, callback_data=f"{chat_id}_{pid}_block")
                    state.list_of_block.append(pid)
        list_of_block_buttons.adjust(1)
        if not state.list_of_block:
            try:
                await bot.send_message(
                    chat_id=player_id,
                    text="💋 <b>Коханка</b>\n\nЦієї ночі нікого не можна обрати - минулої нічі ти вже була в єдиного доступного.",
                    parse_mode="html",
                )
            except Exception:
                pass
            return False
        state.choose_who_you_will_block = await bot.send_message(
            chat_id=player_id,
            text="💋 <b>Коханка</b>\n\n🤔 Хто ж сьогодні був не вірним?",
            reply_markup=list_of_block_buttons.as_markup(),
            parse_mode="html"
        )
        return True

    async def prostitute_block_choice_handler(self, callback: CallbackQuery, bot: Bot):
        """
        Обробник кліків по кнопках Коханки виду `{chat_id}_{target_id}_block`.
        Робимо глобально, щоб кнопки не "ламались" через (не)реєстрацію хендлерів.
        """
        data = (callback.data or "").strip()
        parts = data.split("_")
        if len(parts) != 3 or parts[2] != "block":
            return  # не наш формат
        try:
            chat_id = int(parts[0])
            target_id = int(parts[1])
        except ValueError:
            return

        user_id = callback.from_user.id if callback.from_user else 0
        if not user_id:
            return
        state = self._get_state(chat_id)
        if await self._is_clown_role_temporarily_blocked(state, user_id):
            await callback.answer("🤡 Після зміни ролі Клоуном дія доступна з наступної ночі.", show_alert=True)
            return
        if user_id not in getattr(state, "membersList", []):
            await callback.answer("Ти не в цій грі.", show_alert=True)
            return
        if not state.game_active:
            await callback.answer("Ця гра вже завершена. Нічні дії більше недоступні.", show_alert=True)
            return
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась. Блокування більше неможливе.", show_alert=True)
            return
        # Дозволяємо натискати лише самій Коханці
        if user_id != getattr(state, "prostitute_id", 0):
            await callback.answer("Ця дія тільки для Коханки.", show_alert=True)
            return
        if state.block_action_taken:
            await callback.answer("Ти вже зробила свій вибір цієї ночі!", show_alert=True)
            return
        if target_id == getattr(state, "devil_id", 0):
            await callback.answer("До Диявола ніхто не може ходити.", show_alert=True)
            return
        if target_id == getattr(state, "prostitute_last_target_id", 0):
            await callback.answer("До цього гравця ти вже ходила минулої ночі - зможеш обрати знову наступної ночі.", show_alert=True)
            return
        row = await self._db_fetchone(
            "SELECT killed, tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        if not row:
            await callback.answer("Помилка: гравець не знайдений!", show_alert=True)
            return
        killed, member_name = row
        if killed == 1:
            await callback.answer("Не можна блокувати вже мертвого гравця!", show_alert=True)
            return

        try:
            msg = getattr(state, "choose_who_you_will_block", None)
            if msg:
                await bot.edit_message_text(
                    chat_id=user_id,
                    message_id=msg.message_id,
                    text=(
                        f"💋 <b>Ти обрала:</b> <code>{member_name}</code>\n\n"
                    ),
                    parse_mode="html",
                    reply_markup=None,
                )
        except Exception:
            pass

        state.block_action_target_id = target_id
        state.block_action_taken = True
        self._record_visit(state, user_id, target_id, "block")

        # Повідомлення в групу + ПП цілі (як у старій логіці)
        try:
            _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
            if show_night_targets:
                text = f"💋 <b>Коханка</b> провела ніч з <code>{member_name}</code>."
            else:
                text = f"💋 <b>Коханка</b> зробила свій вибір"
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="html")
        except Exception:
            pass
        state.prostitute_day_notify_target_id = target_id

        state.prostitute_last_target_id = target_id
        await callback.answer("Вибір зроблено! ")

    async def prostitute_bc_close_callback(self, callback: CallbackQuery, bot: Bot):
        """🚪 Закрити пропозицію Чорного кота - звичайний вибір цілі."""
        parts = (callback.data or "").split(":", 1)
        if len(parts) != 2:
            await callback.answer()
            return
        try:
            chat_id = int(parts[1])
        except ValueError:
            await callback.answer()
            return
        player_id = callback.from_user.id if callback.from_user else 0
        state = self._get_state(chat_id)
        if player_id != getattr(state, "prostitute_id", 0):
            await callback.answer("Це не твоє повідомлення.", show_alert=True)
            return
        await callback.answer()
        if not state.game_active or getattr(state, "day_active", False):
            return
        if state.block_action_taken:
            return
        state.prostitute_black_cat_declined_this_game = True
        await self._send_prostitute_target_choice(bot, chat_id, player_id)

    async def prostitute_bc_learn_callback(self, callback: CallbackQuery, bot: Bot):
        """🔎 Дізнатися — один успішний нюх за гру (і без дубль-кліків за ніч)."""
        parts = (callback.data or "").split(":", 1)
        if len(parts) != 2:
            await callback.answer()
            return
        try:
            chat_id = int(parts[1])
        except ValueError:
            await callback.answer()
            return
        player_id = callback.from_user.id if callback.from_user else 0
        state = self._get_state(chat_id)
        if player_id != getattr(state, "prostitute_id", 0):
            await callback.answer("Це не твоє повідомлення.", show_alert=True)
            return
        if not state.game_active or getattr(state, "day_active", False):
            await callback.answer("Гра не активна або вже день.", show_alert=True)
            return
        if state.block_action_taken:
            await callback.answer("Вибір уже зроблено.", show_alert=True)
            return
        if getattr(state, "prostitute_black_cat_sniff_used_this_game", False):
            await callback.answer("Нюх чорного кота вже використано цієї гри.", show_alert=True)
            return
        if getattr(state, "prostitute_black_cat_used_this_night", False):
            await callback.answer("Кіт уже був у пошуку цієї ночі.", show_alert=True)
            return
        # Одразу блокуємо повторні кліки та нічну гілку «нюх при візиті» до завершення сцени
        state.prostitute_black_cat_used_this_night = True
        await callback.answer()
        try:
            await bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                text=emoji_to_premium(
                    "🐈‍⬛Чорний кіт граційно зникає у темних провулках.\n"
                    "Він знає цей запах і швидко знайде, кому він належить."
                ),
                parse_mode="html",
                reply_markup=None,
            )
        except Exception:
            pass
        await asyncio.sleep(3)
        state = self._get_state(chat_id)
        if not state.game_active:
            state.prostitute_black_cat_used_this_night = False
            return
        parfum_users = await self._get_players_with_parfum(chat_id, state)
        found = parfum_users[0] if parfum_users else None
        if found is None:
            state.prostitute_black_cat_used_this_night = False
            await self._send_prostitute_target_choice(bot, chat_id, player_id)
            return
        parfum_user_id, parfum_buff_id = found
        if parfum_buff_id == "parfum" and parfum_user_id in getattr(state, "parfum_shop_used_this_game", set()):
            state.prostitute_black_cat_used_this_night = False
            await self._send_prostitute_target_choice(bot, chat_id, player_id)
            return
        if not try_consume_buff(chat_id, parfum_user_id, parfum_buff_id):
            state.prostitute_black_cat_used_this_night = False
            await self._send_prostitute_target_choice(bot, chat_id, player_id)
            return
        if parfum_buff_id == "parfum":
            used_bc = set(getattr(state, "parfum_shop_used_this_game", set()))
            used_bc.add(int(parfum_user_id))
            state.parfum_shop_used_this_game = used_bc
        try_consume_buff(chat_id, player_id, "black_cat")
        row = await self._db_fetchone(
            "SELECT tg_name FROM users WHERE id = %s",
            (parfum_user_id,),
        )
        member_name = row[0] if row else "Гравець"
        try:
            await bot.send_message(
                chat_id=player_id,
                text=emoji_to_premium(
                    "🐈‍⬛Кіт повернувся і тихо потерся об ноги.\n"
                    "Тепер я знаю цей запах.\n\n"
                    "🧴 Парфум використовує:\n"
                    f"<b>{html.escape(member_name)}</b>\n\n"
                    "Тепер його аромат не зможе завадити вашій ночі."
                ),
                parse_mode="html",
            )
        except Exception:
            pass
        try:
            await bot.send_message(
                chat_id=parfum_user_id,
                text=emoji_to_premium(
                    "🐈‍⬛Чорний кіт граційно вистрибнув на підвіконня.\n"
                    "Він зачепив лапою ваш флакон парфуму.\n\n"
                    "🧴 Флакон впав і розбився.\n\n"
                    "Цієї ночі парфум більше не працює."
                ),
                parse_mode="html",
            )
        except Exception:
            pass
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=emoji_to_premium("🐈‍⬛У темному провулку чути дзенькіт скла…"),
                parse_mode="html",
            )
        except Exception:
            pass
        state.prostitute_black_cat_sniff_used_this_game = True
        await self._strip_message_reply_markup(
            bot, player_id, getattr(state, "choose_who_you_will_block", None)
        )
        await self._send_prostitute_target_choice(bot, chat_id, player_id)

    async def prostitute_block(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        state = self._get_state(chat_id)
        # Кнопки «Дізнатися / Закрити» — поки не було нюху за гру й Коханка не відмовилась від пропозиції
        if (
            not getattr(state, "prostitute_black_cat_declined_this_game", False)
            and not getattr(state, "prostitute_black_cat_sniff_used_this_game", False)
            and self._prostitute_has_black_cat(player_id, chat_id)
        ):
            parfum_users = await self._get_players_with_parfum(chat_id, state)
            if parfum_users:
                kb_offer = InlineKeyboardBuilder()
                kb_offer.button(text="🔎 Дізнатися", callback_data=f"prostitute_bc_learn:{chat_id}")
                kb_offer.button(text="🚪 Закрити", callback_data=f"prostitute_bc_close:{chat_id}")
                kb_offer.adjust(1)
                try:
                    state.choose_who_you_will_block = await bot.send_message(
                        chat_id=player_id,
                        text=emoji_to_premium(
                            "🐈‍⬛Я відчуваю цей дешевий запах…\n\n"
                            "Хочеш дізнатися, хто користується таким несмаком?"
                        ),
                        reply_markup=kb_offer.as_markup(),
                        parse_mode="html",
                    )
                    return
                except Exception:
                    pass
        await self._send_prostitute_target_choice(bot, chat_id, player_id)

    async def sheriff_check(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        state = self._get_state(chat_id)
        list_of_sheriff_buttons = InlineKeyboardBuilder()
        devil_contract_holders = getattr(state, "devil_contract_holders", set())
        devil_id = getattr(state, "devil_id", 0)
        for pid in state.membersList:
            if pid != player_id and pid not in devil_contract_holders and pid != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if not result:
                    continue
                member_name, killed = result
                if killed == 0:
                    list_of_sheriff_buttons.button(text=member_name, callback_data=f"{chat_id}_{pid}_check")
                    if pid not in state.list_of_sheriff:
                        state.list_of_sheriff.append(pid)
        list_of_sheriff_buttons.adjust(1)
        state.choose_who_sheriff_will_check = await bot.send_message(
            chat_id=player_id,
            text="👮 <b>Перевірка ролі</b>\n\nОбери гравця, чию роль хочеш перевірити:",
            reply_markup=list_of_sheriff_buttons.as_markup(),
            parse_mode="html"
        )
    async def _apply_sheriff_check_pick(self, callback: CallbackQuery, bot: Bot, state: GameState, chat_id: int, target_id: int):
        player_id = state.sheriff_id
        if state.sheriff_action_taken:
            await callback.answer("Ти вже зробив свій вибір цієї ночі!", show_alert=True)
            return
        if target_id == getattr(state, "devil_id", 0):
            await callback.answer("До Диявола ніхто не може ходити.", show_alert=True)
            return
        result = await self._db_fetchone(
            "SELECT role, killed, tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        if not result:
            await callback.answer("Помилка: гравець не знайдений!", show_alert=True)
            return
        role, killed, member_name = result
        if killed == 1:
            await callback.answer("Не можна перевіряти мертвого гравця!", show_alert=True)
            return
        if target_id in getattr(state, "devil_covenant_night_shield", set()):
            try:
                await bot.edit_message_text(
                    chat_id=player_id,
                    message_id=state.choose_who_sheriff_will_check.message_id,
                    text=emoji_to_premium(
                        "💥 <b>Контракт з дияволом</b>: перевірка не спрацювала."
                    ),
                    parse_mode="html",
                    reply_markup=None,
                )
            except Exception:
                pass
            state.sheriff_check_id = 0
            state.sheriff_action_taken = True
            await callback.answer("Перевірка не спрацювала.", show_alert=True)
            return
        
        # Обробка предметів: перевірка блокування перевірок
        item_processor = ItemEffectProcessor(chat_id)
        id_card_used = getattr(state, "id_card_used_this_game", set())
        if item_processor.should_block_action(target_id, "check", state) and target_id not in id_card_used:
            used = False
            # Спочатку новий «Паспорт Лиса», потім старе «Посвідчення особи»
            if try_consume_buff(chat_id, target_id, "fox_passport"):
                used = True
                role = "Невідомо"
                state.id_card_used_this_game.add(target_id)
                try:
                    await bot.send_message(
                        chat_id=target_id,
                        text=emoji_to_premium(
                            "📜 <b>Паспорт Лиса</b> спрацював!\n\n"
                            "Фальшивий документ збив перевірку."
                        ),
                        parse_mode="html",
                    )
                except Exception:
                    pass
            elif try_consume_buff(chat_id, target_id, "id_card"):
                used = True
                role = "Невідомо"
                state.id_card_used_this_game.add(target_id)
                try:
                    await bot.send_message(
                        chat_id=target_id,
                        text="🪪 <b>Посвідчення особи</b> спрацювало!\n\n"
                             "Перевірка дала результат «Невідомо».",
                        parse_mode="html"
                    )
                except Exception:
                    pass
            if not used:
                # Немає заряду - предмет не блокує перевірку повторно.
                pass
        else:
            # Обробка предметів: випадковізація перевірок (Маска хаосу, Маска особистості)
            ultra_effects = item_processor.process_ultra_passive_effects(target_id, state)
            blocking_effects = item_processor.process_blocking_effects(target_id, state)
            
            # Маска хаосу - списуємо заряд при використанні
            if ultra_effects.get("randomize_checks"):
                items = item_processor.get_player_items(target_id, ActivationTime.NIGHT)
                for item in items:
                    if item.get("item_id") == "chaos_mask" and item.get("effect_data", {}).get("effect") == "randomize_all_checks_and_buffs":
                        if try_consume_buff(chat_id, target_id, "chaos_mask"):
                            all_roles = ["Мирний житель", "Аль Капоне", "Мафія", "Лікар", "Комісар Каттані", 
                                        "Брехун", "Адвокат", "Камікадзе", "Маніяк"]
                            role = random.choice(all_roles)
                            self.print_log(f"🎭 Маска хаосу: перевірка {target_id} показує випадкову роль {role} (списано заряд)")
                        break
            elif blocking_effects.get("block_role_check"):
                # Посвідчення особи вже обробляється вище з consume_buff_use
                pass
        
        # Deceiver (Брехун) - інвертує результат перевірки (в ПП перевіреному не пишемо - тільки в загальний чат коли Брехун ходить)
        if target_id == state.deceiver_target_id:
            # Визначаємо чи роль є мафією (злі ролі) - Брехун інвертує результат
            mafia_roles = ["Аль Капоне", "Мафія", "Адвокат", "Брехун"]
            if state.name_of_all_capone:
                mafia_roles.append(state.name_of_all_capone)
            is_mafia = role in mafia_roles
            if is_mafia:
                role = "Мирний житель"
            else:
                role = state.name_of_all_capone if state.name_of_all_capone else "Аль Капоне"
        # Lawyer protection - захист працює для ВСІХ ролей
        if target_id == state.lawyer_client_id:
            role = "Мирний житель"
            # Повідомляємо гравця про втручання Адвоката
            try:
                await bot.send_message(
                    chat_id=target_id,
                    text="⚖️ <b>Адвокат</b> втрутився в перевірку.\n\n"
                         "➡️ Слідчий бачить тебе як мирного жителя.",
                    parse_mode="html"
                )
            except:
                pass
        await bot.edit_message_text(
            chat_id=player_id,
            message_id=state.choose_who_sheriff_will_check.message_id,
            text=(
                f" <b>Вибір зроблено!</b> \n\n"
                f"👮 <b>Роль гравця:</b> <code>{member_name}</code> - <b>{role}</b>"
            ),
            parse_mode="html",
            reply_markup=None,
        )
        state.sheriff_check_id = target_id
        state.sheriff_action_taken = True
        self._record_visit(state, player_id, target_id, "check")
        
        # Повідомлення в групу
        try:
            _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
            text = await self._build_check_action_group_text(
                actor_id=player_id,
                target_name=member_name if show_night_targets else None,
                show_target=show_night_targets,
            )
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="html")
        except:
            pass
        
        await callback.answer("Вибір зроблено! ")

    async def maniac_kill(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        state = self._get_state(chat_id)
        list_of_maniac_buttons = InlineKeyboardBuilder()
        devil_contract_holders = getattr(state, "devil_contract_holders", set())
        devil_id = getattr(state, "devil_id", 0)
        for pid in state.membersList:
            if pid != player_id and pid not in devil_contract_holders and pid != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if not result:
                    continue
                member_name, killed = result
                if killed == 0:
                    list_of_maniac_buttons.button(text=member_name, callback_data=f"{chat_id}_{pid}_maniac")
                    if pid not in state.list_of_maniac:
                        state.list_of_maniac.append(pid)
        list_of_maniac_buttons.adjust(1)
        state.choose_who_maniac_will_kill = await bot.send_message(
            chat_id=player_id,
            text=(
                "🤔 Кого атакуєш цієї ночі?\n"
                "Вибираєш одного гравця для вбивства"
            ),
            reply_markup=list_of_maniac_buttons.as_markup(),
            parse_mode="html"
        )
    async def _apply_maniac_kill_pick(self, callback: CallbackQuery, bot: Bot, state: GameState, chat_id: int, target_id: int):
        player_id = state.maniac_id
        if state.maniac_action_taken:
            await callback.answer("Ти вже зробив свій вибір цієї ночі!", show_alert=True)
            return
        if target_id == getattr(state, "devil_id", 0):
            await callback.answer("Диявола неможливо вбити.", show_alert=True)
            return
        result = await self._db_fetchone(
            "SELECT killed, tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        if not result:
            await callback.answer("Помилка: гравець не знайдений!", show_alert=True)
            return
        killed, member_name = result
        if killed == 1:
            await callback.answer("Не можна вбити вже мертвого гравця!", show_alert=True)
            return
        await bot.edit_message_text(
            chat_id=player_id,
            message_id=state.choose_who_maniac_will_kill.message_id,
            text=emoji_to_premium(
                f" <b>Вибір зроблено!</b> \n\n"
                f"🔪 <b>Ти обрав:</b> <code>{member_name}</code>"
            ),
            parse_mode="html",
            reply_markup=None,
        )
        state.maniac_victim_id = target_id
        state.maniac_action_taken = True
        self._record_visit(state, player_id, target_id, "kill_maniac")
        try:
            _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
            if show_night_targets:
                group_text = f"\n\n🪓 <b>Маніяк</b> заносить сокиру над: <code>{member_name}</code>."
            else:
                group_text = "\n\n🪓 <b>Маніяк</b> виходить на полювання"
            await bot.send_message(
                chat_id=chat_id,
                text=group_text,
                parse_mode="html"
            )
        except Exception:
            pass
        await callback.answer("Вибір зроблено! ")

    async def sadistic_doctor(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        state = self._get_state(chat_id)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💊 Лікувати", callback_data=f"sadistic_heal_{chat_id}_{player_id}")],
            [InlineKeyboardButton(text="🔪 Вбити", callback_data=f"sadistic_kill_{chat_id}_{player_id}")]
        ])
        await bot.send_message(
            chat_id=player_id,
            text="⚕️ <b>Доктор-садист</b>\n\nОбери дію цієї ночі:",
            reply_markup=keyboard,
            parse_mode="html"
        )

    async def sadistic_mode_entry_callback(self, callback: CallbackQuery, bot: Bot):
        m = re.match(r"^sadistic_(heal|kill)_(-?\d+)_(\d+)$", callback.data or "")
        if not m:
            return
        mode, chat_s, menu_uid_s = m.group(1), m.group(2), m.group(3)
        chat_id = int(chat_s)
        menu_uid = int(menu_uid_s)
        uid = callback.from_user.id
        state = self._get_state(chat_id)
        if not state.game_active:
            await callback.answer(" Ця гра вже завершена. Нічні дії більше недоступні.", show_alert=True)
            return
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась.", show_alert=True)
            return
        if uid != getattr(state, "sadistic_doctor_id", 0) or menu_uid != uid:
            await callback.answer("Це меню тільки для гравця з роллю Доктор-садист.", show_alert=True)
            return
        if mode == "heal":
            await self.sadistic_heal_list(callback, chat_id, uid)
        else:
            await self.sadistic_kill_list(callback, chat_id, uid)

    async def sadistic_heal_list(self, callback: CallbackQuery, chat_id: int, player_id: int):
        bot = callback.bot
        state = self._get_state(chat_id)
        # Перевірка стану гри/фази
        if not state.game_active:
            await callback.answer(" Ця гра вже завершена. Нічні дії більше недоступні.", show_alert=True)
            return
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась. Лікування більше неможливе.", show_alert=True)
            return
        list_of_sadistic_buttons = InlineKeyboardBuilder()
        devil_id = getattr(state, "devil_id", 0)
        for pid in state.membersList:
            if pid != player_id and pid != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if not result:
                    continue
                member_name, killed = result
                if killed == 0:
                    list_of_sadistic_buttons.button(text=member_name, callback_data=f"{chat_id}_{pid}_sadistic_heal")
                    if pid not in state.list_of_sadistic:
                        state.list_of_sadistic.append(pid)
        list_of_sadistic_buttons.adjust(1)
        state.choose_who_sadistic_will_heal = await bot.send_message(
            chat_id=player_id,
            text="💊 <b>Лікування</b>\n\nОбери гравця, якого хочеш вилікувати:",
            reply_markup=list_of_sadistic_buttons.as_markup(),
            parse_mode="html"
        )

    async def sadistic_kill_list(self, callback: CallbackQuery, chat_id: int, player_id: int):
        bot = callback.bot
        state = self._get_state(chat_id)
        # Перевірка стану гри/фази
        if not state.game_active:
            await callback.answer(" Ця гра вже завершена. Нічні дії більше недоступні.", show_alert=True)
            return
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась. Вбивати більше не можна.", show_alert=True)
            return
        list_of_sadistic_buttons = InlineKeyboardBuilder()
        devil_id = getattr(state, "devil_id", 0)
        for pid in state.membersList:
            if pid != player_id and pid != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if not result:
                    continue
                member_name, killed = result
                if killed == 0:
                    list_of_sadistic_buttons.button(text=member_name, callback_data=f"{chat_id}_{pid}_sadistic_kill")
                    if pid not in state.list_of_sadistic:
                        state.list_of_sadistic.append(pid)
        list_of_sadistic_buttons.adjust(1)
        state.choose_who_sadistic_will_kill = await bot.send_message(
            chat_id=player_id,
            text=emoji_to_premium("🔪 <b>Вбивство</b>\n\nОбери гравця, якого хочеш вбити:"),
            reply_markup=list_of_sadistic_buttons.as_markup(),
            parse_mode="html"
        )

    async def _apply_sadistic_heal_pick(self, callback: CallbackQuery, bot: Bot, state: GameState, chat_id: int, target_id: int):
        player_id = state.sadistic_doctor_id
        if state.sadistic_action_taken:
            await callback.answer("Ти вже зробив свій вибір цієї ночі!", show_alert=True)
            return
        if target_id == getattr(state, "devil_id", 0):
            await callback.answer("До Диявола ніхто не може ходити.", show_alert=True)
            return
        result = await self._db_fetchone(
            "SELECT killed, tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        if not result:
            await callback.answer("Помилка: гравець не знайдений!", show_alert=True)
            return
        killed, member_name = result
        if killed == 1:
            await callback.answer("Не можна лікувати вже мертвого гравця!", show_alert=True)
            return
        await bot.edit_message_text(
            chat_id=player_id,
            message_id=state.choose_who_sadistic_will_heal.message_id,
            text=(
                f" <b>Вибір зроблено!</b> \n\n"
                f"💊 <b>Ти обрав:</b> <code>{member_name}</code>"
            ),
            parse_mode="html",
            reply_markup=None,
        )
        state.sadistic_heal_id = target_id
        state.sadistic_action_taken = True
        self._record_visit(state, player_id, target_id, "heal_sadistic")
        try:
            _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
            if show_night_targets:
                text = f"⚕️ <b>Доктор-садист</b> обрав для експерименту <code>{member_name}</code>."
            else:
                text = f"⚕️ <b>Доктор-садист</b> зробив свій вибір"
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="html")
        except Exception:
            pass
        await callback.answer("Вибір зроблено! ")

    async def _apply_sadistic_kill_pick(self, callback: CallbackQuery, bot: Bot, state: GameState, chat_id: int, target_id: int):
        player_id = state.sadistic_doctor_id
        if state.sadistic_action_taken:
            await callback.answer("Ти вже зробив свій вибір цієї ночі!", show_alert=True)
            return
        if target_id == getattr(state, "devil_id", 0):
            await callback.answer("Диявола неможливо вбити.", show_alert=True)
            return
        result = await self._db_fetchone(
            "SELECT killed, tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        if not result:
            await callback.answer("Помилка: гравець не знайдений!", show_alert=True)
            return
        killed, member_name = result
        if killed == 1:
            await callback.answer("Не можна вбити вже мертвого гравця!", show_alert=True)
            return
        await bot.edit_message_text(
            chat_id=player_id,
            message_id=state.choose_who_sadistic_will_kill.message_id,
            text=emoji_to_premium(
                f" <b>Вибір зроблено!</b> \n\n"
                f"🔪 <b>Ти обрав:</b> <code>{member_name}</code>"
            ),
            parse_mode="html",
            reply_markup=None,
        )
        state.sadistic_kill_id = target_id
        state.sadistic_action_taken = True
        self._record_visit(state, player_id, target_id, "kill_sadistic")
        try:
            _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
            if show_night_targets:
                text = f"⚕️ <b>Доктор-садист</b> вибрав жертву: <code>{member_name}</code>."
            else:
                text = f"⚕️ <b>Доктор-садист</b> вибрав жертву"
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="html")
        except Exception:
            pass
        await callback.answer("Вибір зроблено! ")

    async def mafia_kill(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        state = self._get_state(chat_id)
        list_of_victim_buttons = InlineKeyboardBuilder()
        devil_contract_holders = getattr(state, "devil_contract_holders", set())
        devil_id = getattr(state, "devil_id", 0)
        for pid in state.membersList:
            if pid != player_id and pid not in devil_contract_holders and pid != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if not result:
                    continue
                member_name, killed = result
                if killed == 0:
                    list_of_victim_buttons.button(text=member_name, callback_data=f"{chat_id}_{pid}_maf_killed")
        list_of_victim_buttons.adjust(1)
        await bot.send_message(
            chat_id=player_id,
            text=(
                "🕴🏻Великий Ел загинув від рук зрадників, "
                "твоя черга зайняти його місце, та помститися🎩\n\n"
                "🤔Кому ми помстимося сьогодні?"
            ),
            reply_markup=list_of_victim_buttons.as_markup(),
            parse_mode="html"
        )
    async def _apply_mafia_kill_pick(
        self, callback: CallbackQuery, bot: Bot, state: GameState, chat_id: int, target_id: int, actor_uid: int
    ):
        if state.mafia_action_taken or state.victim_id:
            await callback.answer("Вибір вже зроблено цієї ночі!", show_alert=True)
            return
        if target_id == getattr(state, "devil_id", 0):
            await callback.answer("Диявола неможливо вбити.", show_alert=True)
            return
        result = await self._db_fetchone(
            "SELECT role, killed, tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        if not result:
            await callback.answer("Гравець не знайдений!", show_alert=True)
            return
        role, killed, member_name = result
        if killed == 1:
            await callback.answer("Не можна вбити мертвого гравця!", show_alert=True)
            return
        if role == "Перевертень":
            await self._set_player_role_async(target_id, "Мафія")
            await bot.send_message(chat_id=target_id, text="🐺 Тебе атакувала мафія - ти стаєш мафією!")
            await callback.answer("Перевертень перетворився на мафію!", show_alert=True)
            return
        await bot.edit_message_text(
            chat_id=actor_uid,
            message_id=callback.message.message_id,
            text=f" <b>Вибір зроблено!</b> \n\n🤵 <b>Жертва:</b> <code>{member_name}</code>",
            parse_mode="html",
            reply_markup=None,
        )
        state.victim_id = target_id
        state.mafia_action_taken = True
        self._record_visit(state, actor_uid, target_id, "kill_mafia")
        await callback.answer("Вибір зроблено! ")

    async def commissioner_action(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        state = self._get_state(chat_id)
        # Перевіряємо чи це Сержант, який став Комісаром
        role_result = await self._db_fetchone(
            "SELECT role FROM users WHERE id = %s",
            (player_id,),
        )
        is_sergeant_became_commissioner = role_result and role_result[0] == "Сержант"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👮 Перевірити роль", callback_data=f"comm_mode_check_{chat_id}")],
            [InlineKeyboardButton(text="🔫 Усунути", callback_data=f"comm_mode_kill_{chat_id}")]
        ])
        
        # Зберігаємо "меню Комісара", щоб після вибору прибрати кнопки
        try:
            state.choose_commissioner_action_menu = await bot.send_message(
                chat_id=player_id,
                text="🤔 Кого перевіримо цієї ночі?",
                reply_markup=keyboard,
                parse_mode="html",
            )
        except Exception:
            state.choose_commissioner_action_menu = None

    def _is_commissioner_role_name(self, role_name: Optional[str]) -> bool:
        """Толерантне розпізнавання назви ролі Комісара (на випадок орфо-варіантів у БД)."""
        if not role_name:
            return False
        n = str(role_name).strip().lower()
        return (
            n == "комісар каттані"
            or n == "комісар катанні"
            or n.startswith("комісар каттан")
        )

    async def _resolve_commissioner_callback_actor(self, state: GameState, uid: int) -> int:
        """
        Повертає id гравця, який має право натискати кнопки Комісара.
        Фолбек на БД потрібен, коли state.commissioner_id тимчасово розсинхронений.
        """
        commissioner_id = int(getattr(state, "commissioner_id", 0) or 0)
        if uid and uid == commissioner_id:
            return uid

        role_row = await self._db_fetchone(
            "SELECT role FROM users WHERE id = %s",
            (uid,),
        )
        role_name = role_row[0] if role_row else None

        # Якщо в БД це Комісар — синхронізуємо state і дозволяємо дію.
        if self._is_commissioner_role_name(role_name):
            state.commissioner_id = uid
            return uid

        # Якщо Комісар відсутній, Сержант може виконувати його дію.
        if role_name == "Сержант" and commissioner_id == 0:
            return uid

        return 0

    async def commissioner_mode_pick_callback(self, callback: CallbackQuery, bot: Bot):
        m = re.match(r"^comm_mode_(check|kill)_(-?\d+)$", callback.data or "")
        if not m:
            return
        mode, chat_s = m.group(1), m.group(2)
        chat_id = int(chat_s)
        state = self._get_state(chat_id)
        try:
            await self._refresh_state_role_ids_async(state)
        except Exception:
            pass
        uid = callback.from_user.id
        if await self._is_clown_role_temporarily_blocked(state, uid):
            await callback.answer("🤡 Після зміни ролі Клоуном дія доступна з наступної ночі.", show_alert=True)
            return
        actor_id = await self._resolve_commissioner_callback_actor(state, uid)
        if not actor_id:
            await callback.answer("Ця дія тільки для Комісара.", show_alert=True)
            return
        if not state.game_active or getattr(state, "day_active", False):
            await callback.answer("Недоступно.", show_alert=True)
            return
        await callback.answer()
        try:
            await bot.edit_message_reply_markup(
                chat_id=uid,
                message_id=callback.message.message_id,
                reply_markup=None,
            )
        except Exception:
            pass
        cid = actor_id
        if mode == "check":
            await self.commissioner_check_list(callback, chat_id, cid)
        else:
            await self.commissioner_kill_list(callback, chat_id, cid)

    async def commissioner_back_callback(self, callback: CallbackQuery, bot: Bot):
        m = re.match(r"^comm_back_(-?\d+)$", callback.data or "")
        if not m:
            return
        chat_id = int(m.group(1))
        state = self._get_state(chat_id)
        try:
            await self._refresh_state_role_ids_async(state)
        except Exception:
            pass
        uid = callback.from_user.id
        if await self._is_clown_role_temporarily_blocked(state, uid):
            await callback.answer("🤡 Після зміни ролі Клоуном дія доступна з наступної ночі.", show_alert=True)
            return
        actor_id = await self._resolve_commissioner_callback_actor(state, uid)
        if not actor_id:
            await callback.answer("Ця дія тільки для Комісара.", show_alert=True)
            return
        await callback.answer()
        if not state.game_active or getattr(state, "day_active", False):
            return
        if state.commissioner_action_taken:
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👮 Перевірити роль", callback_data=f"comm_mode_check_{chat_id}")],
            [InlineKeyboardButton(text="🔫 Усунути", callback_data=f"comm_mode_kill_{chat_id}")],
        ])
        try:
            await bot.edit_message_text(
                chat_id=actor_id,
                message_id=callback.message.message_id,
                text="🤔 Кого перевіримо цієї ночі?",
                reply_markup=keyboard,
                parse_mode="html",
            )
        except Exception:
            try:
                await bot.send_message(
                    chat_id=actor_id,
                    text="🤔 Кого перевіримо цієї ночі?",
                    reply_markup=keyboard,
                    parse_mode="html",
                )
            except Exception:
                pass

    async def commissioner_check_list(self, callback: CallbackQuery, chat_id: int, player_id: int):
        bot = callback.bot
        state = self._get_state(chat_id)
        builder = InlineKeyboardBuilder()
        devil_contract_holders = getattr(state, "devil_contract_holders", set())
        devil_id = getattr(state, "devil_id", 0)
        # Список цілей: живі гравці, крім себе, напарника (Сержанта) та диявола - Комісар не може перевіряти свого напарника
        state.list_of_commissioner = []
        sheriff_id = getattr(state, "sheriff_id", 0)
        for pid in state.membersList:
            if pid != player_id and pid != sheriff_id and pid not in devil_contract_holders and pid != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if result and result[1] == 0:
                    builder.button(text=result[0], callback_data=f"comm_check_{chat_id}_{pid}")
                    if pid not in state.list_of_commissioner:
                        state.list_of_commissioner.append(pid)
        builder.button(text="⬅️ Назад", callback_data=f"comm_back_{chat_id}")
        builder.adjust(1)
        state.choose_who_commissioner_will_check = await bot.send_message(
            chat_id=player_id,
            text=emoji_to_premium(
                "🔫 <b>Нічний хід</b>\n\n"
                "🕵️ <b>Комісар Каттані</b> виходить на перевірку\n\n"
                "🤔 Кого перевіримо цієї ночі?"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="html"
        )

    async def commissioner_kill_list(self, callback: CallbackQuery, chat_id: int, player_id: int):
        bot = callback.bot
        state = self._get_state(chat_id)
        builder = InlineKeyboardBuilder()
        devil_contract_holders = getattr(state, "devil_contract_holders", set())
        devil_id = getattr(state, "devil_id", 0)
        # Комісар не може усувати свого напарника (Сержанта)
        sheriff_id = getattr(state, "sheriff_id", 0)
        state.list_of_commissioner = []
        for pid in state.membersList:
            if pid != player_id and pid != sheriff_id and pid not in devil_contract_holders and pid != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if result and result[1] == 0:
                    builder.button(text=result[0], callback_data=f"comm_kill_{chat_id}_{pid}")
                    if pid not in state.list_of_commissioner:
                        state.list_of_commissioner.append(pid)
        builder.button(text="⬅️ Назад", callback_data=f"comm_back_{chat_id}")
        builder.adjust(1)
        state.choose_who_commissioner_will_kill = await bot.send_message(
            chat_id=player_id,
            text=emoji_to_premium("🔫 <b>Нічний хід</b>\n\nОбери гравця для усунення:"),
            reply_markup=builder.as_markup(),
            parse_mode="html"
        )

    async def commissioner_check_target_callback(self, callback: CallbackQuery, bot: Bot):
        m = re.match(r"^comm_check_(-?\d+)_(\d+)$", callback.data or "")
        if not m:
            return
        chat_id, target_id = int(m.group(1)), int(m.group(2))
        state = self._get_state(chat_id)
        try:
            await self._refresh_state_role_ids_async(state)
        except Exception:
            pass
        uid = callback.from_user.id
        if await self._is_clown_role_temporarily_blocked(state, uid):
            await callback.answer("🤡 Після зміни ролі Клоуном дія доступна з наступної ночі.", show_alert=True)
            return
        actor_id = await self._resolve_commissioner_callback_actor(state, uid)
        if not actor_id:
            await callback.answer("Ця дія тільки для Комісара.", show_alert=True)
            return
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась. Перевірка більше неможлива.", show_alert=True)
            return
        if state.commissioner_action_taken:
            await callback.answer("Ти вже зробив вибір цієї ночі!", show_alert=True)
            return
        await self._apply_commissioner_check_pick(callback, bot, state, chat_id, target_id, actor_id)

    async def commissioner_kill_target_callback(self, callback: CallbackQuery, bot: Bot):
        m = re.match(r"^comm_kill_(-?\d+)_(\d+)$", callback.data or "")
        if not m:
            return
        chat_id, target_id = int(m.group(1)), int(m.group(2))
        state = self._get_state(chat_id)
        try:
            await self._refresh_state_role_ids_async(state)
        except Exception:
            pass
        uid = callback.from_user.id
        if await self._is_clown_role_temporarily_blocked(state, uid):
            await callback.answer("🤡 Після зміни ролі Клоуном дія доступна з наступної ночі.", show_alert=True)
            return
        actor_id = await self._resolve_commissioner_callback_actor(state, uid)
        if not actor_id:
            await callback.answer("Ця дія тільки для Комісара.", show_alert=True)
            return
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась. Усунення більше неможливе.", show_alert=True)
            return
        if state.commissioner_action_taken:
            await callback.answer("Ти вже зробив вибір цієї ночі!", show_alert=True)
            return
        await self._apply_commissioner_kill_pick(callback, bot, state, chat_id, target_id, actor_id)

    async def _apply_commissioner_check_pick(
        self, callback: CallbackQuery, bot: Bot, state: GameState, chat_id: int, target_id: int, player_id: int
    ):
        result = await self._db_fetchone(
            "SELECT role, killed, tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        if not result:
            await callback.answer("Гравець не знайдений!", show_alert=True)
            return
        role, killed, member_name = result
        _log_debug('debug-session', 'run1', 'C1', 'play.py:_apply_commissioner_check_pick', 'Commissioner check selected', {
            'chat_id': chat_id,
            'commissioner_id': player_id,
            'target_id': target_id,
            'target_role': role
        })
        if killed == 1:
            await callback.answer("Не можна перевіряти мертвого гравця!", show_alert=True)
            return
        if target_id == getattr(state, "sheriff_id", 0):
            await callback.answer("Не можна перевіряти свого напарника - Сержанта!", show_alert=True)
            return
        state.commissioner_check_id = target_id
        state.commissioner_action_taken = True
        self._record_visit(state, player_id, target_id, "check_comm")
        try:
            await bot.edit_message_text(
                chat_id=player_id,
                message_id=state.choose_who_commissioner_will_check.message_id,
                text="⏳ Результат перевірки буде показано на світанку.",
                parse_mode="html"
            )
            await bot.edit_message_reply_markup(
                chat_id=player_id,
                message_id=state.choose_who_commissioner_will_check.message_id,
                reply_markup=None
            )
        except Exception:
            pass
        try:
            _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
            if show_night_targets:
                text = f"🕵️ <b>Комісар Каттані</b> виходить на перевірку: <code>{member_name}</code>."
            else:
                text = "🕵️ <b>Комісар Каттані</b> виходить на перевірку"
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="html")
        except Exception:
            pass
        await callback.answer("Вибір зроблено! ")

    async def _apply_commissioner_kill_pick(
        self, callback: CallbackQuery, bot: Bot, state: GameState, chat_id: int, target_id: int, player_id: int
    ):
        if target_id == getattr(state, "devil_id", 0):
            await callback.answer("Диявола неможливо вбити.", show_alert=True)
            return
        if target_id == getattr(state, "sheriff_id", 0):
            await callback.answer("Не можна усувати свого напарника - Сержанта!", show_alert=True)
            return
        result = await self._db_fetchone(
            "SELECT role, killed, tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        if not result:
            await callback.answer("Гравець не знайдений!", show_alert=True)
            return
        role, killed, member_name = result
        if killed == 1:
            await callback.answer("Не можна вбити мертвого гравця!", show_alert=True)
            return
        if role == "Перевертень":
            await self._set_player_role_async(target_id, "Сержант")
            await bot.send_message(chat_id=target_id, text="🐺 Тебе атакували - ти стаєш Сержантом!")
            await callback.answer("Перевертень перетворився на Сержанта!", show_alert=True)
            return
        await bot.edit_message_text(
            chat_id=player_id,
            message_id=state.choose_who_commissioner_will_kill.message_id,
            text=f" <b>Ціль усунення:</b> <code>{member_name}</code>",
            parse_mode="html",
            reply_markup=None,
        )
        state.commissioner_kill_id = target_id
        state.commissioner_action_taken = True
        self._record_visit(state, player_id, target_id, "kill_comm")
        if state.sheriff_id:
            await bot.send_message(chat_id=state.sheriff_id, text=f"🕵️ <b>Комісар Каттані</b> пішов до: {member_name}", parse_mode="html")
        try:
            _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
            if show_night_targets:
                text = f"🕵️ <b>Комісар Каттані</b> виходить на усунення: <code>{member_name}</code>."
            else:
                text = "🕵️ <b>Комісар Каттані</b> витягнув зброю з кобури"
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="html"
            )
        except Exception:
            pass
        await callback.answer("Вибір зроблено! ")

    async def homeless_watch(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        state = self._get_state(chat_id)
        builder = InlineKeyboardBuilder()
        devil_id = getattr(state, "devil_id", 0)
        for pid in state.membersList:
            if pid != player_id and pid != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if result and result[1] == 0:
                    builder.button(text=result[0], callback_data=f"{chat_id}_{pid}_homeless")
                    if pid not in state.list_of_homeless:
                        state.list_of_homeless.append(pid)
        builder.adjust(1)
        try:
            state.choose_who_homeless_will_check = await bot.send_message(
                chat_id=player_id,
                text=(
                    "🤔 До кого навідаємось сьогодні?"
                ),
                reply_markup=builder.as_markup(),
                parse_mode="html"
            )
        except TelegramBadRequest as e:
            if "chat not found" in str(e).lower():
                state.choose_who_homeless_will_check = None
                self.print_log(f"⚠️ Волоцюга (id={player_id}): не вдалося надіслати ПП (chat not found), пропускаємо")
                return
            raise
    async def _apply_homeless_pick(self, callback: CallbackQuery, bot: Bot, state: GameState, chat_id: int, target_id: int):
        player_id = state.homeless_id
        self._ensure_knife_role_locked_users(state)
        if player_id in state.knife_role_locked_users:
            await callback.answer("🔪 Цієї ночі можна зробити тільки одну дію: або рольову, або заточку.", show_alert=True)
            return
        if not state.game_active:
            await callback.answer(" Ця гра вже завершена.", show_alert=True)
            return
        if target_id == getattr(state, "devil_id", 0):
            await callback.answer("До Диявола ніхто не може ходити.", show_alert=True)
            return
        if target_id in getattr(state, "devil_covenant_night_shield", set()):
            await callback.answer("💥 Контракт з дияволом: на цього гравця не діє.", show_alert=True)
            return
        state.homeless_target_id = target_id
        self._record_visit(state, player_id, target_id, "homeless")
        _log_debug('debug-session', 'run1', 'HOM1', 'play.py:_apply_homeless_pick', 'Homeless target selected', {
            'chat_id': chat_id,
            'homeless_id': player_id,
            'target_id': target_id
        })
        target_result = await self._db_fetchone(
            "SELECT tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        target_name = target_result[0] if target_result else "Гравець"
        if state.choose_who_homeless_will_check:
            await bot.edit_message_text(
                chat_id=player_id,
                message_id=state.choose_who_homeless_will_check.message_id,
                text=(
                    f" <b>Вибір зроблено!</b> \n\n"
                    f"🧥 <b>Ти обрав:</b> <code>{target_name}</code>\n\n"
                ),
                parse_mode="html",
                reply_markup=None,
            )
        try:
            _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
            if show_night_targets:
                text = f"🧥 Волоцюга спостерігає за <code>{target_name}</code>."
            else:
                text = "🧥 Волоцюга спостерігає з темряви."
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="html"
            )
        except Exception:
            pass
        await callback.answer("Вибір зроблено! ")

    async def journalist_action(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        state = self._get_state(chat_id)
        builder = InlineKeyboardBuilder()
        devil_id = getattr(state, "devil_id", 0)
        for pid in state.membersList:
            if pid != player_id and pid != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if result and result[1] == 0:
                    builder.button(text=result[0], callback_data=f"{chat_id}_{pid}_journal")
                    if pid not in state.list_of_journalist:
                        state.list_of_journalist.append(pid)
        builder.adjust(1)
        state.choose_who_journalist_will_check = await bot.send_message(
            chat_id=player_id,
            text=(
                "🤔 Кого оберемо на інтерв'ю цієї ночі?"
            ),
            reply_markup=builder.as_markup(),
            parse_mode="html"
        )

    async def journalist_target_pick_handler(self, callback: CallbackQuery, bot: Bot):
        """Один обробник на всі ночі: раніше щоночі додавались нові хендлери зі старим player_id → хибна відмова справжньому Журналісту."""
        m = re.match(r"^(-?\d+)_(\d+)_journal$", callback.data or "")
        if not m:
            return
        chat_id = int(m.group(1))
        target_id = int(m.group(2))
        user_id = callback.from_user.id
        state = self._get_state(chat_id)
        if await self._is_clown_role_temporarily_blocked(state, user_id):
            await callback.answer("🤡 Після зміни ролі Клоуном дія доступна з наступної ночі.", show_alert=True)
            return
        self._ensure_knife_role_locked_users(state)
        if user_id in state.knife_role_locked_users:
            await callback.answer("🔪 Цієї ночі можна зробити тільки одну дію: або рольову, або заточку.", show_alert=True)
            return
        if not state.game_active:
            await callback.answer(" Ця гра вже завершена.", show_alert=True)
            return
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась.", show_alert=True)
            return
        if getattr(state, "journalist_id", 0) != user_id:
            await callback.answer("Це меню тільки для гравця з роллю Журналіст.", show_alert=True)
            return
        journalist_id = state.journalist_id
        if len(state.journalist_targets) < 2:
            if target_id in state.journalist_targets:
                await callback.answer("Цей гравець вже обраний!", show_alert=True)
                return
            if target_id == getattr(state, "devil_id", 0):
                await callback.answer("До Диявола ніхто не може ходити.", show_alert=True)
                return
            if target_id in getattr(state, "devil_covenant_night_shield", set()):
                await callback.answer("💥 Контракт з дияволом: інтерв'ю з цим гравцем неможливе.", show_alert=True)
                return
            state.journalist_targets.append(target_id)
            if len(state.journalist_targets) == 1:
                builder = InlineKeyboardBuilder()
                for pid in state.list_of_journalist:
                    if pid != target_id and pid != journalist_id:
                        result = await self._db_fetchone(
                            "SELECT tg_name, killed FROM users WHERE id = %s",
                            (pid,),
                        )
                        if result and result[1] == 0:
                            builder.button(text=result[0], callback_data=f"{chat_id}_{pid}_journal")
                builder.adjust(1)
                try:
                    if state.choose_who_journalist_will_check:
                        await bot.edit_message_text(
                            chat_id=journalist_id,
                            message_id=state.choose_who_journalist_will_check.message_id,
                            text=(
                                "🎤 <b>Нічний хід</b>\n\n"
                                "🤔 Кого ще оберемо на інтерв'ю?"
                            ),
                            reply_markup=builder.as_markup(),
                            parse_mode="html"
                        )
                except Exception:
                    await bot.send_message(
                        chat_id=journalist_id,
                        text=(
                            "🎤 <b>Нічний хід</b>\n\n"
                            "🤔 Кого ще оберемо на інтерв'ю?"
                        ),
                        reply_markup=builder.as_markup(),
                        parse_mode="html"
                    )
            elif len(state.journalist_targets) == 2:
                if state.choose_who_journalist_will_check:
                    try:
                        await bot.edit_message_reply_markup(
                            chat_id=journalist_id,
                            message_id=state.choose_who_journalist_will_check.message_id,
                            reply_markup=None,
                        )
                    except Exception:
                        try:
                            await bot.edit_message_text(
                                chat_id=journalist_id,
                                message_id=state.choose_who_journalist_will_check.message_id,
                                text=" Обрано двох гравців для інтерв'ю.",
                                reply_markup=None,
                            )
                        except Exception:
                            pass
                try:
                    await bot.send_message(
                        chat_id=journalist_id,
                        text="✍🏻 Журналіст бере диктофон та блокнот",
                        parse_mode="html",
                    )
                except Exception:
                    pass
            await callback.answer("Вибір прийнято ")
        else:
            await callback.answer("Ти вже обрав двох гравців цієї ночі.", show_alert=True)

    async def lawyer_protect(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        state = self._get_state(chat_id)
        builder = InlineKeyboardBuilder()
        devil_id = getattr(state, "devil_id", 0)
        for pid in state.membersList:
            if pid != player_id and pid != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if result and result[1] == 0:
                    builder.button(text=result[0], callback_data=f"{chat_id}_{pid}_lawyer")
                    if pid not in state.list_of_lawyer:
                        state.list_of_lawyer.append(pid)
        builder.adjust(1)
        state.choose_who_lawyer_will_protect = await bot.send_message(
            chat_id=player_id,
            text="⚖️ <b>Адвокат</b>\n\n"
                 "🤔 До кого підемо сьогодні?",
            reply_markup=builder.as_markup(),
            parse_mode="html"
        )
    async def _apply_lawyer_pick(self, callback: CallbackQuery, bot: Bot, state: GameState, chat_id: int, target_id: int):
        player_id = state.lawyer_id
        self._ensure_knife_role_locked_users(state)
        if player_id in state.knife_role_locked_users:
            await callback.answer("🔪 Цієї ночі можна зробити тільки одну дію: або рольову, або заточку.", show_alert=True)
            return
        if state.lawyer_client_id != 0:
            await callback.answer("Ти вже зробив вибір цієї ночі!", show_alert=True)
            return
        if target_id == getattr(state, "devil_id", 0):
            await callback.answer("До Диявола ніхто не може ходити.", show_alert=True)
            return
        state.lawyer_client_id = target_id
        self._record_visit(state, player_id, target_id, "lawyer")
        try:
            _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
            if show_night_targets and state.commissioner_check_id:
                r = await self._db_fetchone(
                    "SELECT tg_name FROM users WHERE id = %s",
                    (state.commissioner_check_id,),
                )
                target_name = r[0] if r else "гравець"
                text = f"⚖️ <b>Адвокат</b> пішов по слідах Комісара до <code>{target_name}</code>."
            else:
                text = f"⚖️ <b>Адвокат</b> пішов по слідах Комісара."
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="html")
        except Exception:
            pass
        if getattr(state, "choose_who_lawyer_will_protect", None):
            try:
                await bot.edit_message_reply_markup(
                    chat_id=player_id,
                    message_id=state.choose_who_lawyer_will_protect.message_id,
                    reply_markup=None
                )
            except Exception:
                pass
        await callback.answer("Вибір зроблено! ")

    async def item_use_handler(self, callback: CallbackQuery, bot: Bot):
        """Обробка використання активних предметів під час ночі"""
        user_id = callback.from_user.id
        data_parts = (callback.data or "").split(":")
        if len(data_parts) < 3:
            await callback.answer("Помилка: некоректні дані.", show_alert=True)
            return
        
        item_id = data_parts[1]
        chat_id = int(data_parts[2])
        state = self._get_state(chat_id)
        
        # Перевірка стану гри
        if not state.game_active:
            await callback.answer(PLAY_ALERT_GAME_INACTIVE, show_alert=True)
            return
        
        if user_id not in state.membersList:
            await callback.answer(PLAY_ALERT_STRANGER_NOT_ON_LIST, show_alert=True)
            return
        
        # Перевірка чи предмет активний (функція з buff_shop)
        can_use, reason = can_use_item(user_id, item_id)
        self.print_log(f"🎩 DEBUG item_use: user_id={user_id}, item_id={item_id}, can_use={can_use}, reason={reason}")
        if not can_use:
            await callback.answer(f" {reason}", show_alert=True)
            return
        
        item = ITEMS.get(item_id) or UNIQUE_BUFFS.get(item_id)
        if not item:
            await callback.answer(" Предмет не знайдено.", show_alert=True)
            return
        
        # Обробка конкретних предметів
        effect_data = item.effect_data or {}
        effect_type = effect_data.get("effect")
        
        if effect_type == "block_eavesdropping":
            # Глушилка сигналу - цієї ночі ніхто не дізнається про відвідувачів (Волоцюга, Пейджер)
            if not try_consume_buff(chat_id, user_id, item_id):
                await callback.answer(" Немає зарядів.", show_alert=True)
                return
            state.eavesdropping_blocked = True
            await callback.answer("📵 Глушилка активована. Підслуховування цієї ночі заблоковано.", show_alert=True)
        elif effect_type == "cancel_night_action":
            # Вогнегасник - 1 раз за гру, скасовує одну нічну дію на гравця (блок повії, вбивство тощо)
            n_before = len(state.fire_extinguisher_used_this_game)
            state.fire_extinguisher_used_this_game.add(user_id)
            if len(state.fire_extinguisher_used_this_game) == n_before:
                await callback.answer("🧯 Вогнегасник вже використано цю гру (1 раз за гру).", show_alert=True)
                return
            if not try_consume_buff(chat_id, user_id, "fire_extinguisher"):
                state.fire_extinguisher_used_this_game.discard(user_id)
                await callback.answer(" Немає зарядів.", show_alert=True)
                return
            state.fire_extinguisher_used_this_night.add(user_id)
            await callback.answer("🧯 Вогнегасник активовано! Одна нічна дія на тебе буде скасована.", show_alert=True)
        elif effect_type == "devil_covenant_shield":
            if not try_consume_buff(chat_id, user_id, "devil_covenant"):
                await callback.answer(" Немає зарядів або баф недоступний у цій групі.", show_alert=True)
                return
            day_s = set(getattr(state, "devil_covenant_day_shield", set()) or set())
            night_s = set(getattr(state, "devil_covenant_night_shield", set()) or set())
            day_s.add(user_id)
            night_s.add(user_id)
            state.devil_covenant_day_shield = day_s
            state.devil_covenant_night_shield = night_s
            await callback.answer(
                "💥 Контракт активовано! До кінця поточного дня й ночі ворожі дії проти тебе не спрацюють.",
                show_alert=True,
            )
        elif effect_type == "invisible_to_night_actions":
            # Ефект невидимості для нічних дій (димова шашка / Капелюх КаПоне)
            self.print_log(f"🎩 DEBUG invisible: user_id={user_id}, item_id={item_id}")
            smoke_used = getattr(state, "smoke_grenade_used_this_game", set())
            self.print_log(f"🎩 DEBUG invisible: smoke_used={smoke_used}")
            if user_id in smoke_used:
                await callback.answer(f"🕳 {item.name} вже використано цю гру.", show_alert=True)
                return

            if item_id == "capone_hat":
                # Капелюх можна активувати лише вдень, він працює на наступну ніч
                day_active = getattr(state, "day_active", False)
                self.print_log(f"🎩 DEBUG capone_hat: day_active={day_active}")
                if not day_active:
                    await callback.answer("🎩 Капелюх КаПоне можна активувати тільки вдень. Зачекай до дня.", show_alert=True)
                    return
                # Спочатку перевіряємо і списуємо заряд
                if not try_consume_buff(chat_id, user_id, "capone_hat"):
                    self.print_log(f"🎩 DEBUG capone_hat: try_consume_buff failed")
                    await callback.answer(" Немає зарядів.", show_alert=True)
                    return
                # Тільки після успішного списання додаємо до smoke_used
                self.print_log(f"🎩 DEBUG capone_hat: Adding user {user_id} to smoke_used and hat_scheduled")
                smoke_used.add(user_id)
                state.smoke_grenade_used_this_game = smoke_used
                hat_scheduled = getattr(state, "capone_hat_scheduled_for_night", set())
                hat_scheduled.add(user_id)
                state.capone_hat_scheduled_for_night = hat_scheduled
                self.print_log(f"🎩 DEBUG capone_hat: smoke_used={smoke_used}, hat_scheduled={hat_scheduled}")
                await callback.answer(
                    "🎩 Капелюх КаПоне активовано! Наступної ночі ти будеш невидимим для всіх нічних дій.",
                    show_alert=True,
                )
            else:
                # Димова шашка - активується вночі й діє цю ж ніч
                if getattr(state, "day_active", False):
                    await callback.answer("🕳 Димову шашку можна активувати тільки вночі.", show_alert=True)
                    return
                if not try_consume_buff(chat_id, user_id, item_id):
                    await callback.answer(" Немає зарядів.", show_alert=True)
                    return
                smoke_used.add(user_id)
                state.smoke_grenade_used_this_game = smoke_used
                state.smoke_grenade_activated_this_night.add(user_id)
                await callback.answer(
                    f"🕳 {item.name} активовано! Ти невидимий для нічних дій цієї ночі.",
                    show_alert=True,
                )
        else:
            await callback.answer(f" {item.name} активовано!", show_alert=True)
        
        # Позначаємо предмет як використаний (для кулдаунів)
        # TODO: Додати логіку кулдаунів
        
        try:
            await callback.message.edit_text(
                f" <b>{item.name}</b> використано!\n\n"
                f"<i>{item.description}</i>",
                parse_mode="html",
                reply_markup=None,
            )
        except:
            pass
    
    async def flashlight_handler(self, callback: CallbackQuery, bot: Bot):
        """Ліхтарик - обрав гравця, результат буде після ночі"""
        user_id = callback.from_user.id
        data_parts = (callback.data or "").split(":")
        if len(data_parts) < 3:
            await callback.answer("Помилка.", show_alert=True)
            return
        chat_id = int(data_parts[1])
        target_id = int(data_parts[2])
        state = self._get_state(chat_id)
        if not state.game_active or user_id not in state.membersList:
            await callback.answer(PLAY_ALERT_GAME_INACTIVE_OR_NOT_MEMBER, show_alert=True)
            return
        if user_id in getattr(state, "flashlight_used_this_game", set()):
            await callback.answer("🔦 Ліхтарик вже використано цю гру.", show_alert=True)
            return
        if not try_consume_buff(chat_id, user_id, "flashlight"):
            await callback.answer(" Немає зарядів.", show_alert=True)
            return
        state.flashlight_used_this_game.add(user_id)
        state.flashlight_choice[user_id] = target_id
        r = await self._db_fetchone(
            "SELECT tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        target_name = r[0] if r else "Гравець"
        await callback.answer(f"🔦 Обрано: {target_name}. Результат - після ночі.", show_alert=True)
        try:
            await callback.message.edit_text(
                f"🔦 <b>Ліхтарик</b>\n\nТи обрав(ла): <b>{target_name}</b>.\n\n"
                "Результат (чи хтось приходив до нього) побачиш після ночі.",
                parse_mode="html",
                reply_markup=None,
            )
        except Exception:
            pass

    async def knife_kill_handler(self, callback: CallbackQuery, bot: Bot):
        """Заточка - позначає ціль для гарантованого вбивства цієї ночі (смерть на світанку)."""
        user_id = callback.from_user.id
        data_parts = (callback.data or "").split(":")
        if len(data_parts) < 3:
            await callback.answer("Помилка.", show_alert=True)
            return
        chat_id = int(data_parts[1])
        target_id = int(data_parts[2])
        state = self._get_state(chat_id)
        if not state.game_active or user_id not in state.membersList:
            await callback.answer(PLAY_ALERT_GAME_INACTIVE_OR_NOT_MEMBER, show_alert=True)
            return
        if target_id not in state.membersList:
            await callback.answer(" Цей гравець вже не в грі.", show_alert=True)
            return
        # Мафія не може використовувати заточку по своїх союзниках.
        mafia_team_ids = set(getattr(state, "mafia_ids", []) or [])
        capone_id = int(getattr(state, "all_capone_id", 0) or 0)
        if capone_id:
            mafia_team_ids.add(capone_id)
        if user_id in mafia_team_ids and target_id in mafia_team_ids:
            await callback.answer("🔪 Не можна використати заточку на союзника мафії.", show_alert=True)
            return
        if user_id in self._collect_players_acted_this_night(state):
            await callback.answer("🔪 Цієї ночі можна зробити тільки одну дію: або рольову, або заточку.", show_alert=True)
            return
        # Якщо ти Аль Капоне і вже обрав жертву цієї ночі - заточку активувати не можна
        if user_id == getattr(state, "all_capone_id", 0) and getattr(state, "victim_id", 0):
            await callback.answer("🔪 Як Аль Капоне ти вже обрав жертву цієї ночі. Заточку можна використовувати лише замість вбивства, а не додатково.", show_alert=True)
            return
        # Перевіряємо, чи баф доступний та активний
        knife_used = getattr(state, "knife_used_this_game", set())
        if user_id in knife_used:
            await callback.answer("🔪 Заточку вже використано цю гру.", show_alert=True)
            return
        can_use, reason = can_use_item(user_id, "knife")
        if not can_use:
            await callback.answer(f" {reason}", show_alert=True)
            return
        if not try_consume_buff(chat_id, user_id, "knife"):
            await callback.answer(" Немає зарядів.", show_alert=True)
            return
        knife_used.add(user_id)
        state.knife_used_this_game = knife_used
        # Записуємо жертву заточки, щоб на світанку її вбити разом з іншими нічними жертвами
        knife_kill_ids = getattr(state, "knife_kill_ids", None) or []
        if target_id not in knife_kill_ids:
            knife_kill_ids.append(target_id)
        state.knife_kill_ids = knife_kill_ids
        self._lock_night_role_action_for_user(state, user_id)
        self._ensure_knife_role_locked_users(state)
        state.knife_role_locked_users.add(int(user_id))
        # Жертва формально помре в day_function; зараз лише підтверджуємо вибір
        try:
            r = await self._db_fetchone(
                "SELECT tg_name FROM users WHERE id = %s",
                (target_id,),
            )
            target_name = r[0] if r else "Гравець"
        except Exception:
            target_name = "Гравець"
        await callback.answer(f"🔪 Заточка обрана: {target_name} помре на світанку.", show_alert=True)
        try:
            await callback.message.edit_text(
                f"🔪 <b>Заточка</b>\n\nТи обрав(ла): <b>{target_name}</b>.\n\n"
                "Ціль буде усунута на світанку.",
                parse_mode="html",
                reply_markup=None,
            )
        except Exception:
            pass
    
    async def knife_menu_handler(self, callback: CallbackQuery, bot: Bot):
        """Кнопка заточки: після натискання показує список цілей."""
        user_id = callback.from_user.id
        data_parts = (callback.data or "").split(":")
        if len(data_parts) < 2:
            await callback.answer("Помилка.", show_alert=True)
            return
        chat_id = int(data_parts[1])
        state = self._get_state(chat_id)
        if not state.game_active or user_id not in state.membersList:
            await callback.answer(PLAY_ALERT_GAME_INACTIVE_OR_NOT_MEMBER, show_alert=True)
            return
        # Якщо ти Аль Капоне і вже обрав жертву цієї ночі - не показуємо меню заточки
        if user_id == getattr(state, "all_capone_id", 0) and getattr(state, "victim_id", 0):
            await callback.answer("🔪 Як Аль Капоне ти вже обрав жертву цієї ночі. Заточку можна використовувати лише замість вбивства, а не додатково.", show_alert=True)
            return
        # Перевіряємо, чи баф ще не використовувався
        knife_used = getattr(state, "knife_used_this_game", set())
        if user_id in knife_used:
            await callback.answer("🔪 Заточку вже використано цю гру.", show_alert=True)
            return
        can_use, reason = can_use_item(user_id, "knife")
        if not can_use:
            await callback.answer(f" {reason}", show_alert=True)
            return
        # Формуємо список доступних цілей
        try:
            knife_builder = InlineKeyboardBuilder()
            mafia_team_ids = set(getattr(state, "mafia_ids", []) or [])
            capone_id = int(getattr(state, "all_capone_id", 0) or 0)
            if capone_id:
                mafia_team_ids.add(capone_id)
            user_is_mafia = user_id in mafia_team_ids
            for pid in state.membersList:
                if pid == user_id:
                    continue
                # Якщо виконавець з мафії - не показуємо його маф-союзників у списку.
                if user_is_mafia and pid in mafia_team_ids:
                    continue
                r = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if r and r[1] == 0:
                    knife_builder.button(text=r[0], callback_data=f"knife_kill:{chat_id}:{pid}")
            if not knife_builder.buttons:
                await callback.answer(" Немає доступних цілей.", show_alert=True)
                return
            knife_builder.adjust(1)
            text = emoji_to_premium(
                "🔪 <b>Заточка</b>\n\n"
                "Оберіть гравця - він буде вбитий незалежно від ролі. "
                "Усі бафи можна використати лише один раз за гру."
            )
            try:
                await callback.message.edit_text(
                    text,
                    reply_markup=knife_builder.as_markup(),
                    parse_mode="html",
                )
            except Exception:
                await bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=knife_builder.as_markup(),
                    parse_mode="html",
                )
            await callback.answer()
        except Exception as e:
            self.print_log(f" Помилка побудови меню заточки: {e}")
            await callback.answer(" Помилка при побудові списку цілей.", show_alert=True)

    async def duel_menu_handler(self, callback: CallbackQuery, bot: Bot):
        """Дуель: кнопка виклику - показує список опонентів обраному Мирному жителю."""
        user_id = callback.from_user.id
        parts = (callback.data or "").split(":")
        if len(parts) < 2:
            await callback.answer("Помилка.", show_alert=True)
            return
        chat_id = int(parts[1])
        state = self._get_state(chat_id)
        if not state.game_active or user_id not in state.membersList:
            await callback.answer(PLAY_ALERT_GAME_INACTIVE_OR_NOT_MEMBER, show_alert=True)
            return
        if int(user_id) != int(getattr(state, "duel_shooter_id", 0) or 0):
            await callback.answer("⚔️ Патрони не в тебе.", show_alert=True)
            return
        if getattr(state, "duel_used", False):
            await callback.answer("⚔️ Дуель уже проведено цю гру.", show_alert=True)
            return
        try:
            builder = InlineKeyboardBuilder()
            for pid in state.membersList:
                if pid == user_id:
                    continue
                r = await self._db_fetchone(
                    "SELECT tg_name, COALESCE(killed, 0) FROM users WHERE id = %s", (pid,)
                )
                if r and r[1] == 0:
                    builder.button(text=r[0], callback_data=f"duelcall_pick:{chat_id}:{pid}")
            if not builder.buttons:
                await callback.answer("Немає доступних цілей.", show_alert=True)
                return
            builder.adjust(1)
            text = emoji_to_premium(
                "⚔️ <b>Дуель</b>\n\n"
                "Обери опонента. Постріл вб'є одного з вас - шанс 50/50. Тільки один раз за гру."
            )
            try:
                await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="html")
            except Exception:
                await bot.send_message(chat_id=user_id, text=text, reply_markup=builder.as_markup(), parse_mode="html")
            await callback.answer()
        except Exception as e:
            self.print_log(f" Помилка побудови меню дуелі: {e}")
            await callback.answer(" Помилка при побудові списку цілей.", show_alert=True)

    async def duel_call_handler(self, callback: CallbackQuery, bot: Bot):
        """Дуель: 50/50 - гине викликач або опонент (смерть настане на світанку)."""
        import random as _rnd_duel
        user_id = callback.from_user.id
        parts = (callback.data or "").split(":")
        if len(parts) < 3:
            await callback.answer("Помилка.", show_alert=True)
            return
        chat_id = int(parts[1])
        target_id = int(parts[2])
        state = self._get_state(chat_id)
        if not state.game_active or user_id not in state.membersList:
            await callback.answer(PLAY_ALERT_GAME_INACTIVE_OR_NOT_MEMBER, show_alert=True)
            return
        if int(user_id) != int(getattr(state, "duel_shooter_id", 0) or 0):
            await callback.answer("⚔️ Патрони не в тебе.", show_alert=True)
            return
        if getattr(state, "duel_used", False):
            await callback.answer("⚔️ Дуель уже проведено цю гру.", show_alert=True)
            return
        if target_id not in state.membersList:
            await callback.answer("Цей гравець вже не в грі.", show_alert=True)
            return
        loser_id = _rnd_duel.choice([int(user_id), int(target_id)])
        state.duel_used = True
        duel_kill_ids = getattr(state, "duel_kill_ids", None) or []
        if loser_id not in duel_kill_ids:
            duel_kill_ids.append(loser_id)
        state.duel_kill_ids = duel_kill_ids
        setattr(state, "duel_pending", (int(user_id), int(target_id), int(loser_id)))
        try:
            tr = await self._db_fetchone("SELECT tg_name FROM users WHERE id = %s", (target_id,))
            tname = tr[0] if tr and tr[0] else "Гравець"
        except Exception:
            tname = "Гравець"
        await callback.answer(f"⚔️ Дуель призначено проти {tname}. Долю вирішить світанок.", show_alert=True)
        try:
            await callback.message.edit_text(
                emoji_to_premium(
                    f"⚔️ <b>Дуель</b>\n\n"
                    f"Ти викликав(ла) <b>{tname}</b> до бар'єру.\n\n"
                    "На світанку постріл знайде одного з вас."
                ),
                parse_mode="html",
                reply_markup=None,
            )
        except Exception:
            pass

    async def kamikaze_choice(self, bot: Bot, chat_id: int, kamikaze_id: int):
        """Камікадзе обирає гравця, якого забере з собою при повішанні"""
        state = self._get_state(chat_id)
        builder = InlineKeyboardBuilder()
        
        # Збираємо список живих гравців (окрім самого Камікадзе)
        alive_players = []
        for pid in state.membersList:
            if pid != kamikaze_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if result and result[1] == 0:  # Тільки живі
                    alive_players.append((pid, result[0]))
                    builder.button(text=result[0], callback_data=f"kamikaze_{pid}")
        
        if not alive_players:
            # Якщо немає живих гравців, Камікадзе не може нікого забрати
            try:
                await bot.send_message(
                    chat_id=kamikaze_id,
                    text="💥 Ти Камікадзе, але немає інших живих гравців, яких можна забрати з собою."
                )
            except:
                pass
            state.kamikaze_choice_made = True  # Встановлюємо, щоб гра продовжилась
            return
        
        # Додаємо кнопку "Пропустити"
        builder.button(text="⏭️ Пропустити", callback_data="kamikaze_skip")
        builder.adjust(1)
        try:
            await bot.send_message(
                chat_id=kamikaze_id,
                text=(
                    "🤔 Кого обереш на свій останній рейд?"
                ),
                reply_markup=builder.as_markup(),
                parse_mode="html"
            )
        except Exception as e:
            self.print_log(f"Error sending kamikaze choice to {kamikaze_id}: {e}")
            state.kamikaze_choice_made = True  # Якщо не вдалося надіслати, гра продовжується
    
    async def chosen_kamikaze_handler(self, callback: CallbackQuery, bot: Bot):
        """Обробник вибору Камікадзе"""
        user_id = callback.from_user.id
        callback_data = callback.data
        
        # Знаходимо chat_id та target_id
        chat_id = None
        target_id = None
        
        # Перевіряємо, чи це пропуск вибору
        if callback_data == "kamikaze_skip":
            # Шукаємо гру, де цей гравець є Камікадзе, який був повішений
            for active_chat_id in game_state_manager.get_all_active_chats():
                state = self._get_state(active_chat_id)
                if not state.game_active:
                    continue
                
                # Перевіряємо, чи це саме Камікадзе, який був повішений
                if state.kamikaze_lynched_id == user_id:
                    # Перевіряємо, чи Камікадзе вже зробив вибір
                    if state.kamikaze_choice_made:
                        await callback.answer(" Ти вже зробив свій вибір!", show_alert=True)
                        return
                    
                    chat_id = active_chat_id
                    break
            
            if not chat_id:
                await callback.answer(" Не знайдено активну гру або ти не маєш права на цю дію!", show_alert=True)
                return
            
            state = self._get_state(chat_id)
            
            # Перевіряємо, чи гра все ще активна
            if not state.game_active:
                await callback.answer(" Гра вже закінчена!", show_alert=True)
                return
            
            # Встановлюємо, що вибір пропущено
            state.kamikaze_target_id = 0
            state.kamikaze_choice_made = True
            
            # Відправляємо повідомлення про пропуск вибору
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=(
                        "💥 <b>Взаємодія з відвідуваним гравцем</b> 💥\n"
                        "(Якщо жодного гравця не обрано - Камікадзе пропускає можливість підірвати)\n\n"
                        "💥 Тиша. Лише ти і твоє рішення.\n"
                        "«Можливо, іншого разу…»"
                    ),
                    parse_mode="html"
                )
            except:
                pass
            
            # Відправляємо повідомлення про нічний хід в групу
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text="💥 «Разом - на інший світ…»",
                    parse_mode="html"
                )
            except:
                pass
            
            await callback.answer(" Вибір пропущено.", show_alert=True)
            return
        
        # Формат callback_data: "kamikaze_{target_id}"
        if callback_data.startswith("kamikaze_"):
            try:
                target_id = int(callback_data.replace("kamikaze_", ""))
            except ValueError:
                await callback.answer(" Помилка: некоректні дані!", show_alert=True)
                return
        
        # Шукаємо гру, де цей гравець є Камікадзе, який був повішений
        for active_chat_id in game_state_manager.get_all_active_chats():
            state = self._get_state(active_chat_id)
            if not state.game_active:
                continue
            
            # Перевіряємо, чи це саме Камікадзе, який був повішений (через стан)
            if state.kamikaze_lynched_id == user_id:
                # Перевіряємо, чи Камікадзе вже зробив вибір
                if state.kamikaze_choice_made:
                    await callback.answer(" Ти вже зробив свій вибір!", show_alert=True)
                    return
                
                chat_id = active_chat_id
                break
        
        if not chat_id or not target_id:
            await callback.answer(" Не знайдено активну гру або ти не маєш права на цю дію!", show_alert=True)
            return
        
        state = self._get_state(chat_id)
        
        # Перевіряємо, чи гра все ще активна
        if not state.game_active:
            await callback.answer(" Гра вже закінчена!", show_alert=True)
            return
        
        # Перевіряємо, чи ціль жива та доступна
        target_result = await self._db_fetchone(
            "SELECT tg_name, killed FROM users WHERE id = %s",
            (target_id,),
        )
        if not target_result:
            await callback.answer(" Гравець не знайдений!", show_alert=True)
            return
        
        target_name, target_killed = target_result
        if target_killed == 1:
            await callback.answer(" Цей гравець вже мертвий!", show_alert=True)
            return
        
        # Перевіряємо, чи ціль все ще в грі
        if target_id not in state.membersList:
            await callback.answer(" Цей гравець вже не в грі!", show_alert=True)
            return
        
        if target_id in getattr(state, "devil_covenant_day_shield", set()):
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=emoji_to_premium(
                        "💥 <b>Контракт з дияволом</b> не дає забрати цю душу."
                    ),
                    parse_mode="html",
                )
            except Exception:
                pass
            try:
                await bot.send_message(
                    chat_id=target_id,
                    text=emoji_to_premium(
                        "💥 <b>Контракт з дияволом</b> відбив останній порив Камікадзе."
                    ),
                    parse_mode="html",
                )
            except Exception:
                pass
            state.kamikaze_choice_made = True
            await callback.answer("Дія не спрацювала.", show_alert=True)
            return
        
        # Встановлюємо вибір
        state.kamikaze_target_id = target_id
        state.kamikaze_choice_made = True
        # Досягнення Камікадзе: взірвати Аль Капоне
        if target_id == state.all_capone_id and state.kamikaze_lynched_id:
            self._record_achievement_event(state, "kamikaze_blow_don", state.kamikaze_lynched_id)
        # Відправляємо повідомлення про взаємодію з відвідуваним гравцем
        try:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    "💥 <b>Взаємодія з відвідуваним гравцем</b> 💥\n"
                    "(Коли гравця обрано для «останнього рейду» після повішання)\n\n"
                    f"💥 Камікадзе посміхається крізь останнє дихання:\n"
                    f"«Сьогодні ти йдеш зі мною.»"
                ),
                parse_mode="html"
            )
        except Exception:
            pass
        
        # Відправляємо повідомлення про нічний хід в групу
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="💥 «Разом - на інший світ…»",
                parse_mode="html"
            )
        except Exception:
            pass
        
        # Вбиваємо обраного гравця разом з Камікадзе
        try:
            await self._kill_player(target_id, bot, callback.message, chat_id)
            
            # Повідомляємо в групу
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"💥 <b>Камікадзе</b> забрав з собою {target_name}! 💥\n\n",
                    parse_mode="html"
                )
            except Exception as e:
                self.print_log(f"Помилка надсилання повідомлення про вибір Камікадзе в групу: {e}")
            
            await callback.answer(" Вибір зроблено! Обраний гравець також вибуває з гри.", show_alert=True)
            # Після вибуху Камікадзе перевіряємо умови перемоги з урахуванням нових смертей
            try:
                winner_after_kamikaze = await self.check_win_conditions_async(chat_id)
                if winner_after_kamikaze:
                    await self._handle_game_end(callback.message, bot, chat_id, winner_after_kamikaze)
                    return
            except Exception as e:
                self.print_log(f"Помилка перевірки умов перемоги після вибору Камікадзе: {e}")
        except Exception as e:
            self.print_log(f"Помилка вбивства обраного гравця Камікадзе: {e}")
            await callback.answer(" Помилка при обробці вибору!", show_alert=True)

    async def clown_swap(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        state = self._get_state(chat_id)
        used_players = set(getattr(state, "clown_swap_used_players", set()) or set())
        notified_players = set(getattr(state, "clown_swap_end_notified_players", set()) or set())
        if player_id in used_players:
            if player_id not in notified_players:
                try:
                    await bot.send_message(
                        chat_id=player_id,
                        text=emoji_to_premium(
                            "🤡 «Вибач, вечірка вже закінчилась»"
                        ),
                        parse_mode="html",
                    )
                except Exception:
                    pass
                notified_players.add(int(player_id))
                state.clown_swap_end_notified_players = notified_players
            return
        builder = InlineKeyboardBuilder()
        devil_id = getattr(state, "devil_id", 0)
        for pid in state.membersList:
            if pid != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if result and result[1] == 0:
                    label = f"🙋 {result[0]}" if pid == player_id else result[0]
                    builder.button(text=label, callback_data=f"{chat_id}_{pid}_clown")
                    if pid not in state.list_of_clown:
                        state.list_of_clown.append(pid)
        offer_shown_to = getattr(state, "clown_mass_shuffle_offer_shown_to", None)
        if not isinstance(offer_shown_to, set):
            offer_shown_to = set()
            state.clown_mass_shuffle_offer_shown_to = offer_shown_to

        show_mass_shuffle = (
            int(getattr(state, "clown_role_changes_count", 0) or 0) == 0
            and int(player_id) not in offer_shown_to
        )
        if show_mass_shuffle:
            builder.button(
                text="🎲 Перемішати всі ролі (1 раз)",
                callback_data=f"clown_shuffle_all:{chat_id}",
            )
            offer_shown_to.add(int(player_id))
        builder.adjust(1)
        # Спочатку надсилаємо PM клоуну; якщо не вдалося (наприклад тестовий ID) - не оголошуємо в групі
        try:
            state.choose_who_clown_will_swap = await bot.send_message(
                chat_id=player_id,
                text=(
                    "🤔 Кого «відвідаєш» цієї ночі?\n"
                ),
                reply_markup=builder.as_markup(),
                parse_mode="html"
            )
        except Exception:
            return
        # Не оголошуємо в групі «Клоун виходить на арену» тут - клоун ще лише отримав вибір; оголошення буде після його ходу (обміну ролями)
    async def _apply_clown_pick(self, callback: CallbackQuery, bot: Bot, state: GameState, chat_id: int, target_id: int):
        player_id = state.clown_id
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась. Обмін ролями більше неможливий.", show_alert=True)
            return
        used_players = set(getattr(state, "clown_swap_used_players", set()) or set())
        if player_id in used_players:
            await callback.answer("Ти вже використав цю здатність (раз за гру).", show_alert=True)
            return
        if target_id in state.clown_targets:
            await callback.answer("Цей гравець вже обраний.", show_alert=True)
            return
        if target_id == getattr(state, "devil_id", 0):
            await callback.answer("До Диявола ніхто не може ходити.", show_alert=True)
            return
        state.clown_targets.append(target_id)
        if len(state.clown_targets) < 2:
            builder = InlineKeyboardBuilder()
            for pid in state.list_of_clown:
                if pid != target_id:
                    result = await self._db_fetchone(
                        "SELECT tg_name, killed FROM users WHERE id = %s",
                        (pid,),
                    )
                    if result and result[1] == 0:
                        label = f"🙋 {result[0]}" if pid == player_id else result[0]
                        builder.button(text=label, callback_data=f"{chat_id}_{pid}_clown")
            builder.adjust(1)
            try:
                await bot.edit_message_text(
                    chat_id=player_id,
                    message_id=state.choose_who_clown_will_swap.message_id,
                    text="🤔 Кого ще «відвідаєш»? (2/2)",
                    reply_markup=builder.as_markup(),
                    parse_mode="html"
                )
            except Exception:
                pass
            await callback.answer("Обери другого гравця.", show_alert=True)
            return
        first_id, second_id = state.clown_targets[0], state.clown_targets[1]

        # Логування перед обміном
        self.print_log(f"🤡 Клоун починає обмін ролями між {first_id} та {second_id}")

        r1 = await self._db_fetchone(
            "SELECT role FROM users WHERE id = %s",
            (first_id,),
        )
        r2 = await self._db_fetchone(
            "SELECT role FROM users WHERE id = %s",
            (second_id,),
        )
        if not r1 or not r2:
            self.print_log(f"❌ Клоун: не вдалося отримати ролі з БД для {first_id} або {second_id}")
            await callback.answer("Помилка обміну ролями.", show_alert=True)
            return

        role1, role2 = r1[0], r2[0]
        self.print_log(f"🤡 Обмін ролей: {first_id} ({role1}) ↔ {second_id} ({role2})")

        # Перевірка, що обидва гравці живі та в membersList
        if first_id not in state.membersList:
            self.print_log(f"❌ Клоун: гравець {first_id} не в membersList!")
            await callback.answer("Помилка: гравець не в списку учасників.", show_alert=True)
            return
        if second_id not in state.membersList:
            self.print_log(f"❌ Клоун: гравець {second_id} не в membersList!")
            await callback.answer("Помилка: гравець не в списку учасників.", show_alert=True)
            return

        # Оновлюємо ролі в БД
        await self._set_player_role_async(first_id, role2)
        await self._set_player_role_async(second_id, role1)

        self.print_log(f"🤡 Ролі оновлено в БД, викликаємо _refresh_state_role_ids_async")

        # КРИТИЧНО: Оновлюємо всі role_id в state після обміну
        await self._refresh_state_role_ids_async(state)

        self.print_log(f"🤡 Після оновлення state: doctor_id={state.doctor_id}, all_capone_id={state.all_capone_id}, clown_id={state.clown_id}")
        # Блокуємо нові ролі для гравців, які обмінялись (активація з наступної ночі)
        blocked_now = set(getattr(state, "clown_role_blocked_this_night", set()) or set())
        blocked_now.add(int(first_id))
        blocked_now.add(int(second_id))
        state.clown_role_blocked_this_night = blocked_now

        # Позначаємо, що Клоун використав здатність
        used_players.add(int(player_id))
        state.clown_swap_used_players = used_players
        state.clown_role_changes_count = int(getattr(state, "clown_role_changes_count", 0) or 0) + 1
        state.clown_used = True  # legacy flag (зберігаємо для сумісності старих перевірок)
        state.clown_action_taken = True
        state.clown_targets.clear()

        # КРИТИЧНА ПЕРЕВІРКА: Переконуємось, що обидва гравці все ще в membersList після обміну
        if first_id not in state.membersList:
            self.print_log(f"❌ КРИТИЧНА ПОМИЛКА: після обміну ролей гравець {first_id} зник з membersList!")
        if second_id not in state.membersList:
            self.print_log(f"❌ КРИТИЧНА ПОМИЛКА: після обміну ролей гравець {second_id} зник з membersList!")

        self.print_log(f"🤡 Обмін ролей завершено успішно. Гравці {first_id} та {second_id} отримають нові ролі з наступної ночі.")
        try:
            await bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                text=" Ролі поміняно.\n🤡 «Гра стає цікавішою»",
                reply_markup=None,
                parse_mode="html"
            )
        except Exception:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    reply_markup=None
                )
            except Exception:
                pass
        try:
            _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
            if show_night_targets:
                first_name_row = await self._db_fetchone(
                    "SELECT tg_name FROM users WHERE id = %s",
                    (first_id,),
                )
                second_name_row = await self._db_fetchone(
                    "SELECT tg_name FROM users WHERE id = %s",
                    (second_id,),
                )
                first_name = first_name_row[0] if first_name_row and first_name_row[0] else "гравця"
                second_name = second_name_row[0] if second_name_row and second_name_row[0] else "гравця"
                group_text = f"🎪 <b>Клоун</b> влаштував вечірку в <code>{first_name}</code> та <code>{second_name}</code>."
            else:
                group_text = "🎪 Клоун вийшов на арену."
            await bot.send_message(
                chat_id=chat_id,
                text=group_text,
                parse_mode="html"
            )
        except Exception:
            pass
        try:
            await bot.send_message(chat_id=player_id, text="🤡 «Гра стає цікавішою»", parse_mode="html")
        except Exception:
            pass
        await bot.send_message(chat_id=first_id, text=f"🤡 Твоя роль змінена на: <b>{role2}</b>", parse_mode="html")
        await bot.send_message(chat_id=second_id, text=f"🤡 Твоя роль змінена на: <b>{role1}</b>", parse_mode="html")
        await callback.answer("Ролі поміняно ", show_alert=True)

    async def clown_shuffle_all_callback(self, callback: CallbackQuery, bot: Bot):
        data = (callback.data or "").strip()
        parts = data.split(":", 1)
        if len(parts) != 2:
            await callback.answer()
            return
        try:
            chat_id = int(parts[1])
        except ValueError:
            await callback.answer()
            return
        state = self._get_state(chat_id)
        uid = callback.from_user.id if callback.from_user else 0
        if not uid or uid != getattr(state, "clown_id", 0):
            await callback.answer("Ця дія тільки для Клоуна.", show_alert=True)
            return
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась.", show_alert=True)
            return
        if int(getattr(state, "clown_role_changes_count", 0) or 0) != 0:
            await callback.answer("Ролі вже змінювалися у цій грі.", show_alert=True)
            return
        used_players = set(getattr(state, "clown_swap_used_players", set()) or set())
        if uid in used_players:
            await callback.answer("Ти вже використав здатність Клоуна в цій грі.", show_alert=True)
            return

        self.print_log(f"🎲 Клоун: перемішування всіх ролей для {len(state.membersList)} гравців")

        rows = await self._db_fetchall(
            """
            SELECT id, role
            FROM users
            WHERE id = ANY(%s) AND killed = 0
            """,
            (list(state.membersList or []),),
        )
        alive_rows = [(int(r[0]), str(r[1] or "")) for r in (rows or []) if r and r[1]]

        self.print_log(f"🎲 Клоун: знайдено {len(alive_rows)} живих гравців з ролями")

        if len(alive_rows) < 2:
            self.print_log(f"❌ Клоун: недостатньо гравців для перемішування")
            await callback.answer("Недостатньо живих гравців для перемішування.", show_alert=True)
            return

        ids = [x[0] for x in alive_rows]
        roles = [x[1] for x in alive_rows]

        self.print_log(f"🎲 Клоун: ролі до перемішування: {list(zip(ids, roles))}")

        shuffled_roles = list(roles)
        for _ in range(10):
            random.shuffle(shuffled_roles)
            if any(a != b for a, b in zip(roles, shuffled_roles)):
                break
        if all(a == b for a, b in zip(roles, shuffled_roles)):
            self.print_log(f"❌ Клоун: не вдалося перемішати ролі (всі залишились на місці)")
            await callback.answer("Не вдалося коректно перемішати ролі. Спробуй ще раз.", show_alert=True)
            return

        self.print_log(f"🎲 Клоун: ролі після перемішування: {list(zip(ids, shuffled_roles))}")

        # Оновлюємо ролі в БД
        for pid, new_role in zip(ids, shuffled_roles):
            await self._set_player_role_async(pid, new_role)

        self.print_log(f"🎲 Клоун: ролі оновлено в БД, викликаємо _refresh_state_role_ids_async")

        # КРИТИЧНО: Оновлюємо всі role_id в state після перемішування
        await self._refresh_state_role_ids_async(state)

        self.print_log(f"🎲 Клоун: оновлення state завершено")
        # Блокуємо нові ролі для всіх гравців, чиї ролі змінились
        blocked_now = set(getattr(state, "clown_role_blocked_this_night", set()) or set())
        for pid, old_role, new_role in zip(ids, roles, shuffled_roles):
            if old_role != new_role:
                blocked_now.add(int(pid))
        state.clown_role_blocked_this_night = blocked_now

        used_players.add(int(uid))
        state.clown_swap_used_players = used_players
        state.clown_role_changes_count = int(getattr(state, "clown_role_changes_count", 0) or 0) + 1
        state.clown_used = True  # legacy compatibility
        state.clown_action_taken = True
        state.clown_targets.clear()

        # КРИТИЧНА ПЕРЕВІРКА: Переконуємось, що всі гравці все ще в membersList після перемішування
        for pid in ids:
            if pid not in state.membersList:
                self.print_log(f"❌ КРИТИЧНА ПОМИЛКА: після перемішування ролей гравець {pid} зник з membersList!")

        self.print_log(f"🎲 Перемішування ролей завершено успішно для {len(ids)} гравців.")

        try:
            if callback.message:
                await bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    text="🎲 Ролі всіх живих гравців перемішано.\n🤡 Клоун відкрив нову виставу.",
                    parse_mode="html",
                    reply_markup=None,
                )
        except Exception:
            pass

        try:
            await bot.send_message(chat_id=chat_id, text="🎪 Клоун перемішав усі карти.", parse_mode="html")
        except Exception:
            pass
        for pid, new_role in zip(ids, shuffled_roles):
            try:
                await bot.send_message(chat_id=pid, text=f"🤡 Твоя нова роль: <b>{new_role}</b>", parse_mode="html")
            except Exception:
                pass
        await callback.answer("Ролі перемішано.", show_alert=True)

    async def infected_action(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        state = self._get_state(chat_id)
        builder = InlineKeyboardBuilder()
        devil_id = getattr(state, "devil_id", 0)
        for pid in state.membersList:
            if pid != player_id and pid != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed, role FROM users WHERE id = %s",
                    (pid,),
                )
                if result and result[1] == 0:
                    role = result[2]
                    if role != "Заражений":
                        builder.button(text=result[0], callback_data=f"{chat_id}_{pid}_infect")
                        if pid not in state.list_of_infected:
                            state.list_of_infected.append(pid)
        builder.adjust(1)
        state.choose_who_infected_will_infect = await bot.send_message(
            chat_id=player_id,
            text="🧟 Обери гравця для зараження:",
            reply_markup=builder.as_markup(),
            parse_mode="html"
        )
    async def _apply_infected_pick(
        self, callback: CallbackQuery, bot: Bot, state: GameState, chat_id: int, target_id: int, player_id: int
    ):
        if state.infected_action_taken:
            await callback.answer("Ти вже зробив вибір.", show_alert=True)
            return
        if target_id == getattr(state, "devil_id", 0):
            await callback.answer("До Диявола ніхто не може ходити.", show_alert=True)
            return
        if target_id in getattr(state, "devil_covenant_night_shield", set()):
            await callback.answer("💥 Контракт з дияволом блокує зараження.", show_alert=True)
            return
        state.infected_target_id = target_id
        state.infected_action_taken = True
        self._record_visit(state, player_id, target_id, "infect")
        target_result = await self._db_fetchone(
            "SELECT tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        target_name = target_result[0] if target_result else "Гравець"
        if getattr(state, "choose_who_infected_will_infect", None):
            try:
                await bot.edit_message_text(
                    chat_id=player_id,
                    message_id=state.choose_who_infected_will_infect.message_id,
                    text=f" <b>Вибір зроблено!</b> \n\n🧟 <b>Ти обрав:</b> <code>{target_name}</code>",
                    parse_mode="html",
                    reply_markup=None,
                )
            except Exception:
                pass
        try:
            await bot.send_message(chat_id=chat_id, text=f"🧟 <b>Заражений</b> зробив свій вибір", parse_mode="html")
        except Exception:
            pass
        await callback.answer("Вибір зроблено! ")

    async def deceiver_fake(self, message: Message, bot: Bot, chat_id: int, player_id: int):
        state = self._get_state(chat_id)
        builder = InlineKeyboardBuilder()
        devil_id = getattr(state, "devil_id", 0)
        for pid in state.membersList:
            if pid != player_id and pid != devil_id:
                result = await self._db_fetchone(
                    "SELECT tg_name, killed FROM users WHERE id = %s",
                    (pid,),
                )
                if result and result[1] == 0:
                    builder.button(text=result[0], callback_data=f"{chat_id}_{pid}_deceiver")
                    if pid not in state.list_of_deceiver:
                        state.list_of_deceiver.append(pid)
        builder.adjust(1)
        state.choose_who_deceiver_will_fake = await bot.send_message(
            chat_id=player_id,
            text="🎭 <b>Брехун</b>\n\n"
                 "🤔 Чиї карти заплутаємо сьогодні?",
            reply_markup=builder.as_markup(),
            parse_mode="html"
        )
    async def _apply_deceiver_pick(self, callback: CallbackQuery, bot: Bot, state: GameState, chat_id: int, target_id: int):
        player_id = state.deceiver_id
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась. Вибір більше неможливий.", show_alert=True)
            return
        if target_id == getattr(state, "devil_id", 0):
            await callback.answer("До Диявола ніхто не може ходити.", show_alert=True)
            return
        if target_id in getattr(state, "devil_covenant_night_shield", set()):
            await callback.answer("💥 Контракт з дияволом: підміну зірвано.", show_alert=True)
            return
        state.deceiver_target_id = target_id
        state.deceiver_action_taken = True
        self._record_visit(state, player_id, target_id, "deceiver")
        target_result = await self._db_fetchone(
            "SELECT tg_name FROM users WHERE id = %s",
            (target_id,),
        )
        target_name = target_result[0] if target_result else "Гравець"
        if getattr(state, "choose_who_deceiver_will_fake", None):
            try:
                await bot.edit_message_text(
                    chat_id=player_id,
                    message_id=state.choose_who_deceiver_will_fake.message_id,
                    text=f" <b>Вибір зроблено!</b> \n\n🎭 <b>Ти обрав:</b> <code>{target_name}</code>",
                    parse_mode="html",
                    reply_markup=None,
                )
            except Exception:
                pass
        try:
            _, _, _, show_night_targets = await self._get_thematic_settings_async(chat_id, state)
            if show_night_targets:
                text = f"🎭 <b>Брехун</b> підміняє факти навколо <code>{target_name}</code>."
            else:
                text = "🎭 <b>Брехун</b> підміняє факти."
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="html")
        except Exception:
            pass
        await callback.answer("Вибір зроблено! ")

    async def devil_callback_handler(self, callback: CallbackQuery):
        """Диявол: обробка devil_offer_<chat_id>_<target_id>, devil_accept_<chat_id>, devil_refuse_<chat_id>, devil_soul1_<chat_id>_<pid>, devil_soul2_<chat_id>_<pid>"""
        data = callback.data or ""
        bot = callback.bot
        user_id = callback.from_user.id if callback.from_user else 0
        if not data.startswith("devil_"):
            return
        parts = data.split("_")
        if len(parts) < 3:
            await callback.answer("Помилка даних.", show_alert=True)
            return
        try:
            chat_id = int(parts[2])
        except (ValueError, IndexError):
            await callback.answer("Помилка даних.", show_alert=True)
            return
        state = self._get_state(chat_id)
        if getattr(state, "day_active", False):
            await callback.answer("🌅 Ніч уже закінчилась.", show_alert=True)
            return
        if data.startswith("devil_offer_"):
            if len(parts) < 4:
                return
            try:
                target_id = int(parts[3])
            except ValueError:
                return
            if user_id != getattr(state, "devil_id", 0):
                await callback.answer("Це не твоя дія.", show_alert=True)
                return
            # Якщо вже запропонували комусь контракт раніше - більше обирати не можна
            if getattr(state, "devil_offered_this_game", False):
                await callback.answer("Ти вже запропонував контракт одній людині цієї гри.", show_alert=True)
                # Сховаємо стару клавіатуру, якщо по ній ще клацають
                try:
                    await bot.edit_message_reply_markup(chat_id=callback.message.chat.id, message_id=callback.message.message_id, reply_markup=None)
                except Exception:
                    pass
                return
            state.devil_contract_offered_id = target_id
            state.devil_offered_this_game = True  # За гру лише одна пропозиція
            try:
                # Повідомляємо групу, що «земля вже розверзлась»
                await bot.send_message(
                    chat_id=chat_id,
                    text=emoji_to_premium("🌋 <b>Диявол</b> відкриває врата пекла."),
                    parse_mode="html",
                )

                await bot.send_message(
                    chat_id=target_id,
                    text=emoji_to_premium(
                        "👹 <b>Диявол пропонує тобі контракт.</b>\n"
                        "Взамін на повний імунітет до кінця гри,\n"
                        "ти маєш принести йому дві душі.\n\n"
                    ),
                    reply_markup=_devil_contract_choice_markup(chat_id),
                    parse_mode="html",
                )
                # Очищаємо список вибору в Диявола, щоб не можна було натиснути ще раз
                try:
                    await bot.edit_message_text(
                        chat_id=callback.message.chat.id,
                        message_id=callback.message.message_id,
                        text=emoji_to_premium("👹 Пропозицію контракту надіслано. Чекай відповіді."),
                        parse_mode="html",
                    )
                except Exception:
                    # Якщо редагувати не вдалось - просто надішлемо окремим повідомленням
                    await bot.send_message(
                        chat_id=user_id,
                        text=emoji_to_premium("👹 Пропозицію контракту надіслано. Чекай відповіді."),
                        parse_mode="html",
                    )
            except Exception as e:
                self.print_log(f"devil_offer send error: {e}")
            await callback.answer("Пропозицію надіслано.")
            return
        if data.startswith("devil_accept_"):
            if user_id != getattr(state, "devil_contract_offered_id", 0):
                await callback.answer("Це не тобі запропоновано.", show_alert=True)
                return
            target_id = user_id
            state.devil_contract_holders.add(target_id)
            state.devil_contract_pending = target_id
            # Запам’ятовуємо, в яку ніч контракт було підписано
            if hasattr(state, "devil_contract_start_night"):
                state.devil_contract_start_night = getattr(state, "night_number", 1)
            state.devil_contract_offered_id = 0
            # скидати лічильник відмов для цього гравця
            if hasattr(state, "devil_refusal_counts"):
                state.devil_refusal_counts.pop(target_id, None)
            try:
                # Повідомлення гравцю
                await bot.send_message(
                    chat_id=target_id,
                    text=emoji_to_premium(
                        "🔥 <b>Погодитися</b>\n"
                        "«Я завжди виконую свої обіцянки…»\n\n"
                        "👹 <b>Контракт підписано.</b>\n"
                        "Тепер ти невразливий.\n"
                        "Тепер тебе не бачать.\n"
                        "Тепер тебе не можна зупинити.\n"
                        "Залишилось лише віддати мені дві душі.\n\n"
                        "Поточний статус: <b>0 / 2</b> душі принесено."
                    ),
                    parse_mode="html",
                )
                # Повідомлення Дияволу
                devil_id = getattr(state, "devil_id", 0)
                if devil_id:
                    try:
                        r = await self._db_fetchone(
                            "SELECT tg_name FROM users WHERE id = %s",
                            (target_id,),
                        )
                        nick = r[0] if r else str(target_id)
                    except Exception:
                        nick = str(target_id)
                    await bot.send_message(
                        chat_id=devil_id,
                        text=emoji_to_premium(
                            "📜 <b>Контракт підписано.</b>\n"
                            f"Ім’я: <b>{nick}</b>\n"
                            "Ще одна душа погодилась на угоду.\n"
                            "Тепер усе залежить від того, чи виконає вона свою частину.\n"
                            "Поточний статус: <b>0 / 2</b> душі принесено."
                        ),
                        parse_mode="html",
                    )
            except Exception as e:
                self.print_log(f"devil_accept send error: {e}")
            # Прибираємо кнопки з повідомлення-пропозиції
            try:
                await bot.edit_message_reply_markup(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    reply_markup=None
                )
            except Exception:
                pass
            await callback.answer("Контракт підписано.")
            return
        if data.startswith("devil_refuse_"):
            if user_id != getattr(state, "devil_contract_offered_id", 0):
                await callback.answer("Це не тобі запропоновано.", show_alert=True)
                return
            state.devil_contract_offered_id = 0
            # Жертва відмовилась - Диявол може запропонувати контракт іншому (лише прийнятий контракт забороняє повтор)
            state.devil_offered_this_game = False
            # Рахуємо кількість відмов цього гравця
            counts = getattr(state, "devil_refusal_counts", {})
            current = counts.get(user_id, 0) + 1
            counts[user_id] = current
            state.devil_refusal_counts = counts

            # Друга відмова завжди робить гравця «назавжди нецікавим»
            permanent = False
            if current >= 2:
                permanent = True
            else:
                # Перша відмова: 75% що Диявол більше не запропонує, 25% що може повернутися
                if random.random() < 0.75:
                    permanent = True

            if permanent:
                state.devil_refused_permanent.add(user_id)
                msg_target = (
                    "Ти розірвав контракт ще до підпису.\n"
                    "👹 Диявол з цікавістю подивився на тебе.\n"
                    "«Ти не вартий моєї угоди.»\n"
                    "Він більше не прийде до тебе."
                )
            else:
                msg_target = (
                    "Ти відмовився підписувати контракт.\n"
                    "👹 Диявол тихо засміявся.\n"
                    "«Я терплячий.»\n"
                    "Можливо, він повернеться знову."
                )
            try:
                await bot.send_message(chat_id=user_id, text=emoji_to_premium(msg_target), parse_mode="html")
                devil_id = getattr(state, "devil_id", 0)
                if devil_id:
                    await bot.send_message(
                        chat_id=devil_id,
                        text=emoji_to_premium("👹 Жертва відмовилася від контракту."),
                        parse_mode="html",
                    )
            except Exception as e:
                self.print_log(f"devil_refuse send error: {e}")
            # Прибираємо кнопки з повідомлення-пропозиції
            try:
                await bot.edit_message_reply_markup(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    reply_markup=None
                )
            except Exception:
                pass
            await callback.answer("Відмовлено.")
            return
        if data.startswith("devil_soul1_"):
            if len(parts) < 4:
                return
            try:
                victim_id = int(parts[3])
            except ValueError:
                return
            if user_id != getattr(state, "devil_contract_pending", 0):
                await callback.answer("Це не твоя дія.", show_alert=True)
                return
            # вже приносили душу цієї ночі
            if getattr(state, "devil_contract_action_taken", False):
                await callback.answer("Цієї ночі ти вже приніс душу.", show_alert=True)
                return
            state.devil_contract_action_taken = True
            # додаємо жертву до нічних вбивств
            if victim_id not in getattr(state, "devil_kill_targets", []):
                state.devil_kill_targets.append(victim_id)
            # інкрементуємо кількість принесених душ
            souls = getattr(state, "devil_souls_brought", 0) + 1
            state.devil_souls_brought = souls

            # Оновлюємо повідомлення з кнопками, щоб вибір зник
            try:
                row_name = await self._db_fetchone(
                    "SELECT tg_name FROM users WHERE id = %s",
                    (victim_id,),
                )
                name = row_name[0] if row_name else "?"
                await bot.edit_message_text(
                    chat_id=callback.message.chat.id,
                    message_id=callback.message.message_id,
                    text=emoji_to_premium(
                        f"👹 Жертва: <b>{name}</b>.\n\n"
                        "«Ти вже відчуваєш, як стаєш менш людиною»"
                    ),
                    parse_mode="html",
                )
            except Exception:
                pass

            devil_id = getattr(state, "devil_id", 0)
            # Повідомлення Дияволу
            try:
                if devil_id:
                    if souls == 1:
                        await bot.send_message(
                            chat_id=devil_id,
                            text=emoji_to_premium(
                                "Ти відчуваєш, як щось згасає.\n"
                                "🩸 Одна душа принесена.\n"
                                "Прогрес контракту: <b>1 / 2</b>\n"
                                "Ще одна… і угода буде завершена."
                            ),
                            parse_mode="html"
                        )
                    elif souls >= 2:
                        state.devil_successful_contracts = getattr(state, "devil_successful_contracts", 0) + 1
                        state.devil_contract_pending = 0
                        await bot.send_message(
                            chat_id=devil_id,
                            text=emoji_to_premium(
                                "Друга душа падає в безодню.\n"
                                "🔥 Контракт виконано.\n"
                                "Прогрес: <b>2 / 2</b>\n"
                                "Пекло прийняло свою плату."
                            ),
                            parse_mode="html",
                        )
            except Exception as e:
                self.print_log(f"devil_soul1/2 notify error: {e}")

            # Повідомлення гравцю при другій душі
            if souls >= 2:
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=emoji_to_premium(
                            "Друга душа падає в безодню.\n"
                            "🔥 Контракт виконано.\n"
                            "Прогрес: <b>2 / 2</b>\n\n"
                            "«Тепер ти лише тінь того, ким був.»"
                        ),
                        parse_mode="html",
                    )
                except Exception:
                    pass

            await callback.answer("Вибір зроблено.")
            return
        await callback.answer()

    async def devil_offer_contract(self, message: Message, bot: Bot, chat_id: int, devil_id: int):
        state = self._get_state(chat_id)
        if getattr(state, "devil_offered_this_game", False):
            try:
                await bot.send_message(
                    chat_id=devil_id,
                    text=emoji_to_premium(
                        "👹 <b>Диявол</b>\n\nТи вже запропонував контракт одній людині цієї гри. За гру можна лише одного обрати."
                    ),
                    parse_mode="html",
                )
            except Exception:
                pass
            return
        builder = InlineKeyboardBuilder()
        for pid in state.membersList:
            if pid == devil_id or pid in getattr(state, "devil_refused_permanent", set()) or pid in getattr(state, "devil_contract_holders", set()):
                continue
            result = await self._db_fetchone(
                "SELECT tg_name, killed FROM users WHERE id = %s",
                (pid,),
            )
            if result and result[1] == 0:
                builder.button(text=result[0], callback_data=f"devil_offer_{chat_id}_{pid}")
                if pid not in getattr(state, "list_of_devil", []):
                    state.list_of_devil.append(pid)
        builder.adjust(1)
        try:
            await bot.send_message(
                chat_id=devil_id,
                text=emoji_to_premium("👹 <b>Диявол</b>\n\nКому запропонувати контракт цієї ночі?"),
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
        except Exception as e:
            self.print_log(f"devil_offer_contract send error: {e}")

    async def devil_contract_holder_choose(self, message: Message, bot: Bot, chat_id: int, holder_id: int):
        state = self._get_state(chat_id)
        builder = InlineKeyboardBuilder()
        for pid in state.membersList:
            if pid == holder_id:
                continue
            result = await self._db_fetchone(
                "SELECT tg_name, killed FROM users WHERE id = %s",
                (pid,),
            )
            if result and result[1] == 0:
                builder.button(text=result[0], callback_data=f"devil_soul1_{chat_id}_{pid}")
        builder.adjust(1)
        try:
            await bot.send_message(
                chat_id=holder_id,
                text=emoji_to_premium(
                    "👹 Ви підписали контракт з Дияволом. Обери <b>першу жертву</b> (душу для пекла):"
                ),
                reply_markup=builder.as_markup(),
                parse_mode="html",
            )
        except Exception as e:
            self.print_log(f"devil_contract_holder_choose send error: {e}")

    async def play_cmd(self, message: Message, bot: Bot):
        # Видаляємо повідомлення з командою /play
        try:
            await message.delete()
        except Exception as e:
            self.print_log(f"⚠️ Не вдалося видалити повідомлення /play: {e}")
        
        # Check if group is blocked
        if message.chat.type in ["supergroup", "group"]:
            if await self._is_group_blocked_async(message.chat.id):
                await self._answer_with_retry(
                    message,
                    "🚫Лавочку прикрили. Доступу немає.",
                )
                return
        print(f"\n{'='*60}")
        print(f"🎯 PLAY_CMD ВИКЛИКАНО!")
        print(f"📋 Тип чату: {message.chat.type}")
        print(f"📋 Chat ID: {message.chat.id}")
        print(f"📋 User ID: {message.from_user.id if message.from_user else 'None'}")
        print(f"{'='*60}\n")
        
        try:
            if message.chat.type in ["supergroup", "group"]:
                print(f" Це група/супергрупа, продовжую...")
                chat_id = message.chat.id
                # Пінгачок: гарантовано запамʼятовуємо того, хто викликав /play.
                # У aiogram обробка часто зупиняється на першому хендлері, тому загальний трекер
                # може не отримати це ж повідомлення.
                try:
                    if message.from_user and not getattr(message.from_user, "is_bot", False):
                        now_ts = datetime.now().timestamp()
                        by_chat = self._ping_recent_users.get(chat_id)
                        if by_chat is None:
                            by_chat = {}
                            self._ping_recent_users[chat_id] = by_chat
                        by_chat[int(message.from_user.id)] = now_ts
                except Exception:
                    pass
                # Якщо вже йде гра або набір (таймер) - не дозволяти новий /play
                if game_state_manager.has_state(chat_id):
                    state = self._get_state(chat_id)
                    if state.game_active or state.gameTime > 0:
                        await self._answer_with_retry(
                            message,
                            "⏳Тут не прохідний двір. Спочатку закінчимо цю гру, потім почнемо нову.",
                        )
                        return
                state = self._get_state(chat_id)
                print(f" Отримано стан для чату {chat_id}")

                # Пінгачок: збережемо склад попередньої гри (privacy mode у групах часто не дає
                # наповнювати recent_chat_users, тому найнадійніше тегати останніх гравців).
                try:
                    state.last_game_membersNames = list(getattr(state, "membersNames", []))
                    state.last_game_membersList = list(getattr(state, "membersList", []))
                except Exception:
                    pass

                # Очищаємо список гравців при новому /play
                state.membersList.clear()
                state.membersNames.clear()
                state.registration_open = True
                print(f"🔄 Очищено списки гравців для нового набору")
                
                link = await create_start_link(bot, f'{chat_id}', encode=False)

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Приєднатися", url=link)]
                ])

                # Отримуємо час реєстрації з БД для цієї конкретної групи (за замовчуванням 90 секунд)
                # Використовуємо найбільший час реєстрації для цієї групи (якщо є кілька записів)
                time_result = await self._db_fetchone(
                    "SELECT MAX(registration_time) FROM admin_panel WHERE group_id = %s",
                    (chat_id,),
                )
                registration_time = time_result[0] if time_result and time_result[0] else 90
                
                # Reset game time and set minimum players
                # Таймер йде в зворотному напрямку від registration_time секунд до 0
                state.gameTime = registration_time
                MIN_PLAYERS = 4
                MAX_PLAYERS = 30
                
                # Формуємо текст з залишковим часом
                if registration_time <= 0:
                    remaining_text = "0 секунд"
                elif registration_time == 1:
                    remaining_text = "1 секунда"
                elif registration_time < 5:
                    remaining_text = f"{registration_time} секунди"
                else:
                    remaining_text = f"{registration_time} секунд"
                
                # Формуємо початкове повідомлення (з retry при flood control)
                state.registration_total = registration_time
                _reg_open_text = self._lobby_text(state, registration_time, registration_time, MAX_PLAYERS)
                state.messageOfRegistration = await self._answer_with_retry(
                    message,
                    text=emoji_to_premium(_reg_open_text, skip_vip_badges=False),
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
                
                # Спробуємо закріпити повідомлення (необов'язково)
                try:
                    await bot.pin_chat_message(chat_id=chat_id, message_id=state.messageOfRegistration.message_id)
                    print(f" Повідомлення закріплено")
                except Exception as pin_error:
                    print(f"⚠️ Не вдалося закріпити повідомлення (не критично): {pin_error}")
                    # Продовжуємо виконання навіть якщо pin не вдався
                
                # Логування для перевірки
                print(f"\n{'='*60}")
                print(f"🎮 PLAY_CMD: Створено повідомлення реєстрації для чату {chat_id}")
                print(f"📊 Стан: gameTime={state.gameTime}, membersList={len(state.membersList)}")
                print(f"{'='*60}\n")
                self.print_log(f"🎮 PLAY_CMD: Створено повідомлення реєстрації для чату {chat_id}")

                # Казино запускається разом з /play і стосується цієї ж гри
                try:
                    from commands.casino import send_casino_message
                    open_round = await casino_get_open_round_async(chat_id)
                    round_id = open_round[0] if open_round else await casino_create_round_async(chat_id)
                    await send_casino_message(bot, chat_id, round_id, in_group=True)
                except Exception as e:
                    self.print_log(f"Казино «У Лева» (/play): {e}")

                # Пінгачок у фоні (тимчасово вимкнений прапорцем REGISTRATION_PING_ENABLED)
                if REGISTRATION_PING_ENABLED:
                    try:
                        asyncio.create_task(self._send_registration_ping_messages(bot, chat_id))
                    except Exception as e:
                        self.print_log(f"Не вдалося запланувати пінгачок: {e}")

                # Start timer task in background (non-blocking)
                async def timer_wrapper():
                    """Wrapper to catch and log any errors in timer task"""
                    print(f"🚀 TIMER_WRAPPER: Запущено для чату {chat_id}")
                    try:
                        self.print_log(f"🚀 timer_wrapper запущено для чату {chat_id}")
                        await self._game_timer_task(message, bot, chat_id, MIN_PLAYERS, MAX_PLAYERS, keyboard)
                    except Exception as e:
                        print(f" ПОМИЛКА в timer_wrapper: {e}")
                        import traceback
                        print(traceback.format_exc())
                        self.print_log(f" КРИТИЧНА ПОМИЛКА в timer_wrapper для чату {chat_id}: {e}")
                        self.print_log(f"Traceback: {traceback.format_exc()}")
                
                # Створюємо завдання та відразу запускаємо його
                print(f"🔄 Створюю таймер-завдання для чату {chat_id}...")
                try:
                    loop = asyncio.get_running_loop()
                    task = loop.create_task(timer_wrapper())
                    print(f" Таймер-завдання створено: {task}, done={task.done()}")
                    self.print_log(f" Таймер-завдання створено для чату {chat_id}, task: {task}, done: {task.done()}")
                except RuntimeError as e:
                    print(f"⚠️ RuntimeError при створенні завдання: {e}")
                    try:
                        task = asyncio.create_task(timer_wrapper())
                        print(f" Таймер-завдання створено (fallback): {task}")
                        self.print_log(f" Таймер-завдання створено (fallback) для чату {chat_id}, task: {task}")
                    except Exception as e2:
                        print(f" КРИТИЧНА ПОМИЛКА при створенні завдання: {e2}")
                        import traceback
                        print(traceback.format_exc())
                
                # Додаткова перевірка через 2 секунди
                async def check_timer():
                    await asyncio.sleep(2)
                    check_state = self._get_state(chat_id)
                    print(f"🔍 CHECK_TIMER: Перевірка через 2 сек, gameTime={check_state.gameTime}")
                    if check_state.gameTime == 0:
                        print(f"⚠️ УВАГА: Таймер не оновлюється! Час все ще 0с")
                        self.print_log(f"⚠️ УВАГА: Таймер не оновлюється! Час все ще 0с для чату {chat_id}")
                        # Спробуємо перезапустити таймер
                        print(f"🔄 Перезапускаю таймер...")
                        self.print_log(f"🔄 Спробую перезапустити таймер для чату {chat_id}")
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(timer_wrapper())
                        except:
                            try:
                                asyncio.create_task(timer_wrapper())
                            except Exception as e:
                                print(f" Помилка перезапуску: {e}")
                    else:
                        print(f" Таймер працює! Час: {check_state.gameTime}с")
                        self.print_log(f" Таймер працює! Час: {check_state.gameTime}с для чату {chat_id}")
                
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(check_timer())
                except:
                    asyncio.create_task(check_timer())
            else:
                print(f" Це не група/супергрупа! Тип чату: {message.chat.type}")
                print(f"💡 Команда /play працює тільки в групах та супергрупах")
                await self._answer_with_retry(
                    message,
                    "⏳Тут не прохідний двір. Спочатку закінчимо цю гру, потім почнемо нову.",
                )
        except asyncio.CancelledError:
            raise
        except TelegramNetworkError as e:
            # Типово: зупинка бота (Ctrl+C), обрив з’єднання, рестарт - не «критична» логіка гри
            self.print_log(f"⚠️ play_cmd: мережа Telegram / зупинка процесу (без повторної відправки): {e}")
            print(f"\n⚠️ play_cmd: TelegramNetworkError (часто при Ctrl+C або обриві): {e}\n")
            return
        except Exception as e:
            print(f"\n КРИТИЧНА ПОМИЛКА в play_cmd:")
            print(f"Помилка: {e}")
            import traceback
            print(traceback.format_exc())
            print(f"{'='*60}\n")
            try:
                await self._answer_with_retry(
                    message,
                    "⏳Тут не прохідний двір. Спочатку закінчимо цю гру, потім почнемо нову.",
                )
            except (TelegramNetworkError, asyncio.CancelledError):
                pass
            except Exception:
                pass
    
    async def carry_on_cmd(self, message: Message, bot: Bot):
        # Видаляємо повідомлення з командою /carry_on
        try:
            await message.delete()
        except Exception as e:
            self.print_log(f"⚠️ Не вдалося видалити повідомлення /carry_on: {e}")
        # Check if group is blocked
        if message.chat.type in ["supergroup", "group"]:
            if await self._is_group_blocked_async(message.chat.id):
                await message.answer("🚫Лавочку прикрили. Доступу немає.")
                return
        """Продовжити реєстрацію, додавши секунди до таймера"""
        try:
            if message.chat.type not in ["supergroup", "group"]:
                return
            
            chat_id = message.chat.id
            state = self._get_state(chat_id)

            # Перевірка, чи є активна реєстрація
            if state.game_active:
                await message.answer(
                    "⛔️ Ми вже в грі. Додавати час пізно, розбираємося з тим, що є."
                )
                return

            if state.messageOfRegistration is None:
                await message.answer(
                    "⚠️Чекати нікого. Спочатку збери людей через /play, а потім розтягуй час."
                )
                return

            # Перевірка, чи реєстрація ще відкрита (таймер не закінчився)
            if not getattr(state, "registration_open", True):
                await message.answer(
                    "⏰ Час вийшов. Реєстрація вже закрита, додавати час пізно."
                )
                return
            
            # Отримуємо параметр (кількість секунд)
            command_args = message.text.split()
            if len(command_args) < 2:
                await message.answer(
                    "💡Хочеш почекати запізнілих? Напиши: /carry_on [секунди] (наприклад: /carry_on 30)."
                )
                return
            
            try:
                additional_seconds = int(command_args[1])
                if additional_seconds <= 0:
                    await message.answer(
                        "⏳Час не гумовий. Вкажи число більше нуля, якщо реально хочеш когось почекати."
                    )
                    return
                
                # Додаємо секунди до поточного часу
                old_time = state.gameTime
                state.gameTime += additional_seconds
                new_time = state.gameTime
                
                self.print_log(f"⏱️ carry_on: додано {additional_seconds} секунд. Було: {old_time}с, стало: {new_time}с")
                
                # Оновлюємо повідомлення реєстрації
                try:
                    # Формуємо список гравців
                    members_names = self._format_members_comma_separated_html(state.membersNames)
                    
                    # Формуємо текст з залишковим часом
                    remaining_seconds = state.gameTime
                    if remaining_seconds <= 0:
                        remaining_text = "0 секунд"
                    elif remaining_seconds == 1:
                        remaining_text = "1 секунда"
                    elif remaining_seconds < 5:
                        remaining_text = f"{remaining_seconds} секунди"
                    else:
                        remaining_text = f"{remaining_seconds} секунд"
                    
                    # Отримуємо посилання для кнопки
                    link = await create_start_link(bot, f'{chat_id}', encode=False)
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Приєднатися", url=link)]
                    ])
                    
                    _carry_reg_text = self._lobby_text(
                        state, remaining_seconds,
                        getattr(state, "registration_total", remaining_seconds), 30
                    )
                    await state.messageOfRegistration.edit_text(
                        text=emoji_to_premium(_carry_reg_text, skip_vip_badges=False),
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )

                    await message.answer(
                        f"⏳Добре, почекаємо ще трохи. Додано {additional_seconds} сек."
                    )
                    
                except Exception as e:
                    self.print_log(f" Помилка оновлення повідомлення: {e}")
                    await message.answer(
                        "⚠️Час пішов, але зв'язок барахлить. Секунди враховані, хоча звіт не оновився."
                    )
                    
            except ValueError:
                await message.answer(
                    "🚨Не вдалося відтягнути час. Спробуй ще раз, або починаємо з тими, хто є."
                )
            except Exception as e:
                self.print_log(f" Помилка в carry_on_cmd: {e}")
                await message.answer(
                    "🚨Не вдалося відтягнути час. Спробуй ще раз, або починаємо з тими, хто є."
                )
                
        except Exception as e:
            self.print_log(f" Критична помилка в carry_on_cmd: {e}")
            import traceback
            print(traceback.format_exc())
            try:
                await message.answer(
                    "🚨Не вдалося відтягнути час. Спробуй ще раз, або починаємо з тими, хто є."
                )
            except Exception:
                pass

    async def stop_game_cmd(self, message: Message, bot: Bot):
        """Зупинити гру (тільки для адмінів групи: власник або додані через +адмін)."""
        # Видаляємо повідомлення з командою /stop_game
        try:
            await message.delete()
        except Exception as e:
            self.print_log(f"⚠️ Не вдалося видалити повідомлення /stop_game: {e}")
        if message.chat.type not in ["supergroup", "group"]:
            await message.answer(" Команда працює тільки в групах.")
            return
        if await self._is_group_blocked_async(message.chat.id):
            await message.answer("🚫Лавочку прикрили. Доступу немає.")
            return
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        creator_id = await get_group_creator_id_async(chat_id)
        admin_level = await get_group_admin_level_async(chat_id, user_id)
        if creator_id != user_id and admin_level < 1:
            await message.answer(
                "⛔️Руки геть від столу. Скасовувати справу може тільки адміністрація. Хочеш влади? Юзай +адмін."
            )
            return
        state = self._get_state(chat_id)
        if not state.game_active and (not getattr(state, "gameTime", 0) or state.gameTime <= 0):
            await message.answer(
                "⚠️За столом пусто. Ми ще навіть не починали, щоб давати відбій."
            )
            return
        state.game_active = False
        state.gameTime = 0
        state.registration_open = False
        self._reset_last_word_tracking(state)
        if state.messageOfRegistration:
            try:
                await state.messageOfRegistration.delete()
            except Exception:
                pass
            state.messageOfRegistration = None
        await self._unmute_users_muted_during_game(bot, chat_id)
        stop_msg = await message.answer("⏹️ Фінал. Адміністратор прикрив лавочку.")
        try:
            await asyncio.sleep(3)
            await stop_msg.delete()
        except Exception:
            pass
        self.print_log(f"Гру зупинено адмінистратором (user_id={user_id}) у chat_id={chat_id}")

    async def set_registration_time_cmd(self, message: Message, bot: Bot):
        """Встановити час реєстрації для групи (тільки для власника)"""
        # Приберемо саму команду — щоб не засмічувати чат.
        try:
            self._autoclean(bot, message.chat.id, message.message_id, 3)
        except Exception:
            pass
        # Check if group is blocked
        if message.chat.type in ["supergroup", "group"]:
            if await self._is_group_blocked_async(message.chat.id):
                await self._answer_autoclean(message, "🚫Лавочку прикрили. Доступу немає.", bot)
                return

        try:
            if message.chat.type not in ["supergroup", "group"]:
                await self._answer_autoclean(message, " Команда працює тільки в групах та супергрупах!", bot)
                return
            
            chat_id = message.chat.id
            user_id = message.from_user.id
            
            # Головний власник бота завжди має права
            if _is_bot_owner_id(user_id):
                # Перевіряємо, чи запис існує в БД, якщо ні - створюємо
                owner_row = await self._db_fetchone(
                    "SELECT creator_id FROM admin_panel WHERE creator_id = %s AND group_id = %s",
                    (user_id, chat_id),
                )
                if not owner_row:
                    await self._db_execute_commit(
                        "INSERT INTO admin_panel (creator_id, group_id, registration_time) VALUES (%s, %s, 90) ON CONFLICT (creator_id, group_id) DO NOTHING",
                        (user_id, chat_id),
                    )
            else:
                # Перевіряємо, чи користувач є власником цієї конкретної групи
                creator_result = await self._db_fetchone(
                    "SELECT creator_id FROM admin_panel WHERE creator_id = %s AND group_id = %s",
                    (user_id, chat_id),
                )
                
                if not creator_result:
                    # Додаткова перевірка: чи користувач є CREATOR в Telegram для цієї групи
                    try:
                        chat_member = await bot.get_chat_member(chat_id, user_id)
                        from aiogram.enums import ChatMemberStatus
                        if chat_member.status != ChatMemberStatus.CREATOR:
                            await self._answer_autoclean(
                                message,
                                "⛔️ Рівень доступу: Власник. Тільки засновник Резиденції встановлює регламент підготовки до Справи.",
                                bot,
                            )
                            return
                        # Якщо користувач CREATOR в Telegram, але не в БД, додаємо його
                        await self._db_execute_commit(
                            "INSERT INTO admin_panel (creator_id, group_id, registration_time) VALUES (%s, %s, 90) ON CONFLICT (creator_id, group_id) DO NOTHING",
                            (user_id, chat_id),
                        )
                    except Exception as e:
                        self.print_log(f"Помилка перевірки власника: {e}")
                        await self._answer_autoclean(
                            message,
                            "⛔️ Рівень доступу: Власник. Тільки засновник Резиденції встановлює регламент підготовки до Справи.",
                            bot,
                        )
                        return
            
            # Отримуємо параметр (кількість секунд)
            command_args = message.text.split()
            if len(command_args) < 2:
                # Показуємо поточне значення для цієї конкретної групи
                time_result = await self._db_fetchone(
                    "SELECT registration_time FROM admin_panel WHERE creator_id = %s AND group_id = %s",
                    (user_id, chat_id),
                )
                current_time = time_result[0] if time_result and time_result[0] else 90
                await self._answer_autoclean(
                    message,
                    f"⏱️ На збори відведено: {current_time} сек.💡 Змінити: /set_registration_time [сек]",
                    bot,
                )
                return

            try:
                new_time = int(command_args[1])
                if new_time < 10:
                    await self._answer_autoclean(
                        message,
                        "⏳Не вписуємось у графік. Збори мають тривати від 10 до 600 секунд. Вибери щось посередині.",
                        bot,
                    )
                    return
                if new_time > 600:
                    await self._answer_autoclean(
                        message,
                        "⏳Не вписуємось у графік. Збори мають тривати від 10 до 600 секунд. Вибери щось посередині.",
                        bot,
                    )
                    return
                
                # Оновлюємо час в БД для всіх записів цієї групи (щоб уникнути конфліктів)
                updated = await self._db_fetchone(
                    "UPDATE admin_panel SET registration_time = %s WHERE group_id = %s RETURNING 1",
                    (new_time, chat_id),
                )
                if not updated:
                    await self._db_execute_commit(
                        "INSERT INTO admin_panel (creator_id, group_id, registration_time) VALUES (%s, %s, %s) ON CONFLICT (creator_id, group_id) DO UPDATE SET registration_time = %s",
                        (user_id, chat_id, new_time, new_time),
                    )
                
                await self._answer_autoclean(
                    message,
                    f"Час оновлено. Тепер у колег є {new_time} секунд, щоб приєднатися до справи.",
                    bot,
                    seconds=12,
                )

            except ValueError:
                await self._answer_autoclean(
                    message,
                    "Щось не те з цифрами. Напиши просто кількість секунд, без зайвого.",
                    bot,
                )
            except Exception as e:
                self.print_log(f" Помилка в set_registration_time_cmd: {e}")
                
        except Exception as e:
            self.print_log(f" Критична помилка в set_registration_time_cmd: {e}")
            import traceback
            print(traceback.format_exc())
    
    async def _game_timer_task(self, message: Message, bot: Bot, chat_id: int, MIN_PLAYERS: int, MAX_PLAYERS: int, keyboard):
        """Background task for game timer - runs independently"""
        print(f"\n{'='*60}")
        print(f"🎯 _GAME_TIMER_TASK: ВИКЛИКАНО для чату {chat_id}")
        print(f"{'='*60}\n")
        self.print_log(f"🎯 _game_timer_task ВИКЛИКАНО для чату {chat_id}")
        try:
            state = self._get_state(chat_id)
            timer_messages = []
            
            print(f"📊 Стан: game_active={state.game_active}, gameTime={state.gameTime}, messageOfRegistration={state.messageOfRegistration is not None}")
            self.print_log(f"📊 Стан для чату {chat_id}: game_active={state.game_active}, gameTime={state.gameTime}, messageOfRegistration={state.messageOfRegistration is not None}")
            
            # Перевірка, чи гра вже не почалася
            if state.game_active:
                print(f"⚠️ Гра вже активна, таймер не запускається")
                self.print_log(f"⚠️ Гра вже активна, таймер не запускається")
                return
            
            # Перевірка, чи існує повідомлення реєстрації
            if state.messageOfRegistration is None:
                print(f" Помилка: messageOfRegistration не існує")
                self.print_log(f" Помилка: messageOfRegistration не існує для чату {chat_id}")
                return
            
            # Отримуємо час реєстрації з БД (якщо не встановлено, використовуємо поточне значення)
            # Використовуємо найбільший час реєстрації для цієї групи (якщо є кілька записів)
            time_result = await self._db_fetchone(
                "SELECT MAX(registration_time) FROM admin_panel WHERE group_id = %s",
                (chat_id,),
            )
            initial_registration_time = time_result[0] if time_result and time_result[0] else state.gameTime
            if state.gameTime == 0:
                state.gameTime = initial_registration_time
            elif state.gameTime != initial_registration_time:
                # Якщо час змінився в БД, оновлюємо
                state.gameTime = initial_registration_time
            
            print(f"⏱️ Запускаю таймер реєстрації, початковий час: {state.gameTime}")
            self.print_log(f"⏱️ Запускаю таймер реєстрації для чату {chat_id}, початковий час: {state.gameTime}")
            
            # Оновлюємо повідомлення кожні 5 секунд, щоб уникнути flood control
            # Для зворотного відліку починаємо з початкового часу
            last_update_time = state.gameTime
            update_interval = 5  # Оновлюємо кожні 5 секунд
            retry_after_seconds = 0  # Час очікування після flood control
            # Локальний список жартів на цю реєстрацію
            local_jokes = REGISTRATION_JOKES.copy()
            random.shuffle(local_jokes)
            next_joke_index = 0
            # Рідкі точки: кожні ~30% прогресу (рахуємо по "залишилось секунд").
            # Напр., для 300с: 210 / 120 / 30; для 90с: 63 / 36 / 9 (але нижче підріжемо мінімум).
            try:
                t0 = int(initial_registration_time or state.gameTime or 0)
            except Exception:
                t0 = int(state.gameTime or 0)
            points = []
            if t0 > 0:
                for frac in (0.7, 0.4, 0.1):
                    p = int(round(t0 * frac))
                    if p > 0:
                        points.append(p)
            # Не спамимо на зовсім малих значеннях
            joke_trigger_points = sorted({p for p in points if p >= 10}, reverse=True)
            joke_chance = 0.4
            
            # Функція для оновлення повідомлення
            async def update_timer_message():
                nonlocal retry_after_seconds
                try:
                    if state.messageOfRegistration is None:
                        return False
                    
                    # Якщо є retry_after, чекаємо
                    if retry_after_seconds > 0:
                        print(f"⏳ Чекаю {retry_after_seconds} секунд через flood control...")
                        await asyncio.sleep(retry_after_seconds)
                        retry_after_seconds = 0
                    
                    # Формуємо список гравців
                    members_names = self._format_members_comma_separated_html(state.membersNames)
                    
                    # Формуємо текст з залишковим часом
                    remaining_seconds = state.gameTime
                    if remaining_seconds <= 0:
                        remaining_text = "0 секунд"
                    elif remaining_seconds == 1:
                        remaining_text = "1 секунда"
                    elif remaining_seconds < 5:
                        remaining_text = f"{remaining_seconds} секунди"
                    else:
                        remaining_text = f"{remaining_seconds} секунд"
                    
                    _timer_reg_text = self._lobby_text(
                        state, remaining_seconds,
                        getattr(state, "registration_total", remaining_seconds), 30
                    )
                    await state.messageOfRegistration.edit_text(
                        text=emoji_to_premium(_timer_reg_text, skip_vip_badges=False),
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
                    self.print_log(f" Оновлено таймер для чату {chat_id}, залишилось: {state.gameTime} секунд")
                    return True
                except TelegramRetryAfter as e:
                    # Обробка flood control
                    retry_after_seconds = e.retry_after
                    print(f"⚠️ Flood control: чекаю {retry_after_seconds} секунд (залишилось: {state.gameTime}с)")
                    self.print_log(f"⚠️ Flood control: чекаю {retry_after_seconds} секунд (залишилось: {state.gameTime}с)")
                    return False
                except TelegramBadRequest as e:
                    err_lower = str(e).lower()
                    # Повідомлення видалено, недійсний ID або недоступне (наприклад, через /start_game або видалення в чаті)
                    if "message to edit not found" in err_lower or "message not found" in err_lower or "message_id_invalid" in err_lower:
                        state.messageOfRegistration = None
                        self.print_log(f"ℹ️ Повідомлення таймера недоступне (видалено або MESSAGE_ID_INVALID), зупиняю оновлення")
                        return False
                    # Текст не змінився (Telegram не дозволяє edit з тим самим контентом)
                    if "message is not modified" in err_lower:
                        return True  # Вважаємо успіхом - повідомлення вже актуальне
                    raise
                except Exception as e:
                    self.print_log(f"⚠️ Помилка оновлення таймера (залишилось: {state.gameTime}с): {e}")
                    return False
            
            # Негайне перше оновлення
            print(f"🔄 Виконую перше оновлення повідомлення...")
            await update_timer_message()
            last_update_time = state.gameTime
            print(f" Перше оновлення виконано, залишилось: {state.gameTime} секунд")
            
            iteration_count = 0
            print(f"🔄 Починаю цикл таймера (зворотний відлік від 90 до 0)...")
            while True:
                iteration_count += 1
                # Логуємо тільки кожні 10 секунд або коли залишилось менше 10
                if state.gameTime % 10 == 0 or state.gameTime <= 10:
                    print(f"⏰ Залишилось: {state.gameTime} секунд")
                
                # Перевірка, чи гра не почалася (якщо хтось використав /start_game)
                if state.game_active:
                    print(f"⏱️ Гра почалася, зупиняю таймер")
                    self.print_log(f"⏱️ Гра почалася, зупиняю таймер")
                    break
                
                await asyncio.sleep(1)
                state.gameTime -= 1  # Зменшуємо таймер (зворотний відлік)
                
                # Перевірка, чи повідомлення все ще існує
                if state.messageOfRegistration is None:
                    self.print_log(f" Повідомлення реєстрації видалено, зупиняю таймер")
                    break

                # Іноді вкидаємо атмосферні жарти під час набору
                if (
                    next_joke_index < len(local_jokes)
                    and state.gameTime in joke_trigger_points
                    and random.random() < joke_chance
                ):
                    try:
                        text = emoji_to_premium(local_jokes[next_joke_index])
                        await bot.send_message(chat_id=chat_id, text=text, parse_mode="html")
                    except Exception as e:
                        self.print_log(f"⚠️ Помилка відправки реєстраційного жарту: {e}")
                    finally:
                        next_joke_index += 1
                
                # Оновлюємо повідомлення кожні 5 секунд або на важливих моментах
                # Використовуємо динамічні точки оновлення на основі початкового часу
                initial_time = initial_registration_time
                update_points = [initial_time, initial_time - 30, initial_time - 45, initial_time - 60] if initial_time >= 60 else [initial_time]
                update_points.extend([30, 20, 15, 10, 5, 0])
                update_points = sorted(set([p for p in update_points if p >= 0]), reverse=True)
                
                should_update = (
                    last_update_time - state.gameTime >= update_interval or
                    state.gameTime in update_points
                )
                
                if should_update:
                    success = await update_timer_message()
                    if success:
                        last_update_time = state.gameTime
                
                # Timer messages для зворотного відліку
                if state.gameTime == 60:
                    try:
                        timer_messages.append(await state.messageOfRegistration.reply(text="⏱️ Залишилось 1 хвилина"))
                    except Exception as e:
                        self.print_log(f"⚠️ Помилка відправки повідомлення про 1 хвилину: {e}")
                elif state.gameTime == 30:
                    try:
                        timer_messages.append(await state.messageOfRegistration.reply(text="⏱️ Залишилось 30 секунд"))
                    except Exception as e:
                        self.print_log(f"⚠️ Помилка відправки повідомлення про 30 секунд: {e}")
                elif state.gameTime == 10:
                    try:
                        timer_messages.append(await state.messageOfRegistration.reply(text="⏱️ Залишилось 10 секунд!"))
                    except Exception as e:
                        self.print_log(f"⚠️ Помилка відправки повідомлення про 10 секунд: {e}")
                
                # Check if timer reached 0 seconds (гра починається)
                if state.gameTime <= 0:
                    state.registration_open = False
                    # Delete timer messages
                    for msg in timer_messages:
                        try:
                            await msg.delete()
                        except TelegramBadRequest:
                            pass
                        except Exception:
                            pass
                    
                    print(f"⏰ Таймер досяг 0 секунд, перевіряю кількість гравців...")

                    async def _remove_registration_announcement():
                        """Прибрати закріплене лобі до інших дій (інакше лишається «0 секунд» при помилках send)."""
                        reg = state.messageOfRegistration
                        if not reg:
                            return
                        mid = int(reg.message_id)
                        try:
                            await bot.unpin_chat_message(chat_id=chat_id, message_id=mid)
                        except Exception:
                            pass
                        try:
                            await bot.delete_message(chat_id=chat_id, message_id=mid)
                        except TelegramBadRequest as e:
                            self.print_log(
                                f"⚠️ Не вдалося видалити повідомлення реєстрації (chat={chat_id}, msg={mid}): {e}"
                            )
                        state.messageOfRegistration = None
                    
                    if len(state.membersList) < MIN_PLAYERS:
                        try:
                            await _remove_registration_announcement()
                            # Якщо гра не стартувала через таймер - повертаємо ставки казино за цей раунд
                            try:
                                import commands.casino as casino_mod
                                row = await self._db_fetchone(
                                    "SELECT id FROM casino_rounds WHERE chat_id = %s AND resolved_at IS NULL ORDER BY id DESC LIMIT 1",
                                    (chat_id,),
                                )
                                if row and row[0]:
                                    try:
                                        await casino_mod.refund_casino_round(bot, chat_id, row[0])
                                    except AttributeError:
                                        # Якщо функція ще не реалізована - пропускаємо
                                        pass
                            except Exception as e:
                                self.print_log(f"⚠️ Помилка повернення ставок казино при скасуванні гри: {e}")

                            # Замість сухого «гру скасовано» — міні-гра «Наперстки» для тих,
                            # хто встиг зайти в лобі (вгадай стаканець із лимоном → ліри).
                            started_thimble = False
                            joined = list(getattr(state, "membersNames", []) or [])
                            if joined:
                                try:
                                    import commands.thimble as thimble_mod
                                    started_thimble = await thimble_mod.start_thimble(bot, chat_id, joined)
                                except Exception as e:
                                    self.print_log(f"⚠️ Не вдалося запустити Наперстки: {e}")
                            if not started_thimble:
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text="Час вийшов - гру скасовано.",
                                    parse_mode="html"
                                )
                        except Exception as e:
                            self.print_log(f"⚠️ Помилка при завершенні таймера (недостатньо гравців): {e}")
                        state.gameTime = 0
                        break
                    else:
                        try:
                            await _remove_registration_announcement()
                            # Повідомлення про початок гри.
                            # Якщо старт ініційований автозапуском при досягненні MAX_PLAYERS,
                            # це дозволяє уникнути дублювання повідомлень.
                            if not getattr(state, "start_by_max", False):
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text="🌃 <b>Гру розпочато. Місто засинає…</b> 🌃",
                                    parse_mode="html"
                                )
                                # Список усіх гравців у грі (VIP-посилання + преміум-емодзі)
                                players_text = self._format_players_list_numbered_html(state.membersNames)
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text=emoji_to_premium(
                                        f"<b>Список гравців:</b>\n{players_text}",
                                        skip_vip_badges=False,
                                    ),
                                    parse_mode="html",
                                )
                        except Exception as e:
                            self.print_log(f"⚠️ Помилка при завершенні таймера (гра починається): {e}")
                        # Викликаємо start_game лише якщо гра ще не активна (не запущена через /start_game)
                        if not state.game_active:
                            await self.start_game(message=message, bot=bot)
                        state.gameTime = 0
                        state.start_by_max = False
                        break
        except Exception as e:
            # Критична помилка в таймері
            self.print_log(f" КРИТИЧНА ПОМИЛКА в _game_timer_task для чату {chat_id}: {e}")
            import traceback
            self.print_log(f"Traceback: {traceback.format_exc()}")
    
    async def force_start_game(self, message: Message, bot: Bot):
        # Видаляємо повідомлення з командою /start_game
        try:
            await message.delete()
        except Exception as e:
            self.print_log(f"⚠️ Не вдалося видалити повідомлення /start_game: {e}")
        # Check if group is blocked
        if message.chat.type in ["supergroup", "group"]:
            if await self._is_group_blocked_async(message.chat.id):
                await message.answer("🚫Лавочку прикрили. Доступу немає.")
                return
        """Force start game immediately without waiting for timer"""
        if message.chat.type not in ["supergroup", "group"]:
            await message.answer(
                "⏳Тут не прохідний двір. Спочатку закінчимо цю гру, потім почнемо нову.",
            )
            return
        
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        creator_id = await get_group_creator_id_async(chat_id)
        admin_level = await get_group_admin_level_async(chat_id, user_id)
        if creator_id != user_id and admin_level < 1:
            await message.answer(
                "⛔️У тебе немає повноважень. Такі накази віддає тільки Адмінистратор 1+ або Власник закладу."
            )
            return

        state = self._get_state(chat_id)

        MIN_PLAYERS = 4
        MAX_PLAYERS = 30
        
        # Check if game is already active
        if state.game_active:
            await message.answer(
                "⚠️Ми не починаємо нову партію, поки не розібралися з цією.",
            )
            return
        
        # Check minimum players
        if len(state.membersList) < MIN_PLAYERS:
            await message.answer(
                f"👥Натовп замалий. Потрібно хоча б 4, щоб почати. Зараз на місці: {len(state.membersList)}.",
            )
            return
        
        # Check maximum players
        if len(state.membersList) > MAX_PLAYERS:
            await message.answer(
                "🚨Нас забагато. У цій кімнаті поміститься не більше 30 осіб.",
            )
            return
        
        state.registration_open = False
        # Stop timer if running
        state.gameTime = 0  # Set to 0 to stop timer loop (зворотний відлік)
        
        # Delete registration message if exists (вимикає таймер - він перевірить messageOfRegistration is None)
        if state.messageOfRegistration:
            try:
                await state.messageOfRegistration.delete()
            except TelegramBadRequest:
                pass
            except Exception:
                pass
            state.messageOfRegistration = None
        
        # Start game immediately
        await message.answer(
            "🥃Час пішов. Ролі розподілено, карти на руках. Починаємо...",
        )
        
        await self.start_game(message=message, bot=bot)

    def _autoclean(self, bot: Bot, chat_id: int, message_id, seconds: int = 8) -> None:
        """Прибрати службове/командне повідомлення через `seconds` секунд (тихо, без помилок).
        Тримає груповий чат чистим: команди й разові сповіщення не накопичуються спамом."""
        if not message_id:
            return

        async def _worker():
            try:
                await asyncio.sleep(max(1, int(seconds)))
                await bot.delete_message(chat_id=chat_id, message_id=int(message_id))
            except Exception:
                pass

        try:
            asyncio.create_task(_worker())
        except Exception:
            pass

    async def _answer_autoclean(self, message: Message, text: str, bot: Bot, seconds: int = 8, **kwargs):
        """Відповісти й автоматично прибрати відповідь через `seconds` секунд (для разових сповіщень)."""
        try:
            sent = await message.answer(text, **kwargs)
        except Exception:
            return None
        try:
            self._autoclean(bot, sent.chat.id, sent.message_id, seconds)
        except Exception:
            pass
        return sent

    async def _process_registration_join(self, message: Message, bot: Bot, chat_id: int) -> None:
        """Приєднання до набору для заданого chat_id групи (deep link з ПП або /join у групі)."""
        if message.from_user is None:
            return
        # Приберемо саму команду /join (deep-link /start) — щоб не було спаму в чаті.
        try:
            self._autoclean(bot, message.chat.id, message.message_id, 3)
        except Exception:
            pass
        try:
            if await self._is_group_blocked_async(chat_id):
                await self._answer_autoclean(message, "🚫Лавочку прикрили. Доступу немає.", bot)
                return
        except Exception:
            pass
        state = self._get_state(chat_id)

        self.print_log(f"Значення state.numbers_of_members: {state.numbers_of_members}")
        self.print_log(f"Кількість гравців зараз: {len(state.membersList)}")
        
        if state.game_active:
            await self._answer_autoclean(
                message,
                "⛔️ Двері зачинені. Справа вже в розпалі, зайвих не пускаємо. Чекай наступного разу.",
                bot,
            )
            return
        if not getattr(state, "registration_open", True):
            await self._answer_autoclean(
                message,
                "⏳Час вийшов. Ми вже почали розподіляти ролі, ти не встиг.",
                bot,
            )
            return
        if state.messageOfRegistration is None:
            await self._answer_autoclean(
                message,
                "⚠️Це старі папери. Зараз ніхто нікого не збирає. Використовуй актуальне оголошення.",
                bot,
            )
            return

        if message.from_user.id in state.membersList:
            await self._answer_autoclean(
                message,
                "Ти вже з нами. Не треба нагадувати про себе двічі.",
                bot,
            )
            return

        # Максимум 30 гравців
        MAX_PLAYERS = 30
        if len(state.membersList) >= MAX_PLAYERS:
            await self._answer_autoclean(
                message,
                "🚫У кімнаті немає місця. Ми вже зібрали 30 осіб, більше цей стіл не витримає.",
                bot,
            )
            return
        
        uid = message.from_user.id
        state.membersList.append(uid)

        # Safety: handle rare race where two joins can pass the pre-check
        # and exceed MAX_PLAYERS. Roll back this user and stop there.
        if len(state.membersList) > MAX_PLAYERS:
            state.membersList = [x for x in state.membersList if x != uid]
            await self._answer_autoclean(
                message,
                "🚫У кімнаті немає місця. Ми вже зібрали 30 осіб, більше цей стіл не витримає.",
                bot,
            )
            return

        await add_user_to_db(message=message)
        
        link = await create_start_link(bot, f'{chat_id}', encode=False)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Приєднатися", url=link)]
        ])

        fn = message.from_user.first_name or "Гравець"
        # Зберігаємо plain ім'я; HTML-лінк будується пізніше в _format_members_comma_separated_html.
        state.membersNames.append((uid, fn))

        members_names = self._format_members_comma_separated_html(state.membersNames)

        # Формуємо текст з залишковим часом
        remaining_seconds = state.gameTime
        if remaining_seconds <= 0:
            remaining_text = "0 секунд"
        elif remaining_seconds == 1:
            remaining_text = "1 секунда"
        elif remaining_seconds < 5:
            remaining_text = f"{remaining_seconds} секунди"
        else:
            remaining_text = f"{remaining_seconds} секунд"

        _join_reg_text = self._lobby_text(
            state, remaining_seconds,
            getattr(state, "registration_total", remaining_seconds), 30
        )
        reg_msg = state.messageOfRegistration
        message_gone = False
        premium_text = emoji_to_premium(_join_reg_text, skip_vip_badges=False)
        for attempt in range(5):
            try:
                await reg_msg.edit_text(
                    text=premium_text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
                break
            except TelegramRetryAfter as e:
                wait_s = min(float(getattr(e, "retry_after", 1) or 1), 8.0)
                self.print_log(
                    f"start_cmd_link: RetryAfter chat_id={chat_id} uid={uid} wait={wait_s}s attempt={attempt + 1}"
                )
                await asyncio.sleep(wait_s)
            except TelegramBadRequest as e:
                err_lower = str(e).lower()
                if "message is not modified" in err_lower:
                    break
                if (
                    "message to edit not found" in err_lower
                    or "message not found" in err_lower
                    or "message_id_invalid" in err_lower
                    or "chat not found" in err_lower
                ):
                    message_gone = True
                    state.messageOfRegistration = None
                    self.print_log(f"start_cmd_link: повідомлення реєстрації зникло chat_id={chat_id}: {e}")
                    break
                self.print_log(f"start_cmd_link: TelegramBadRequest chat_id={chat_id} uid={uid}: {e}")
                await asyncio.sleep(0.25 * (attempt + 1))
            except Exception as e:
                self.print_log(f"start_cmd_link: edit_text failed chat_id={chat_id} uid={uid}: {e}")
                await asyncio.sleep(0.3 * (attempt + 1))

        if message_gone:
            state.membersList = [x for x in state.membersList if x != uid]
            state.membersNames = [(i, n) for i, n in state.membersNames if i != uid]
            await self._answer_autoclean(
                message,
                "⚠️Твоє прізвище не вписали. Сталася заминка зі списком, тебе не додано до гри. Спробуй ще раз.",
                bot,
            )
            return

        # Підтвердження приєднання — тільки в ЛС гравцю, щоб не спамити груповий чат.
        try:
            await bot.send_message(
                chat_id=uid,
                text=emoji_to_premium("👤Ти в справі."),
                parse_mode="html",
            )
        except Exception:
            pass

        # Auto-start: when we reach MAX_PLAYERS, start the game immediately
        # instead of waiting for the registration timer to hit 0.
        if (
            len(state.membersList) == MAX_PLAYERS
            and not state.game_active
            and getattr(state, "registration_open", True)
        ):
            # Used by _game_timer_task to suppress duplicate "game started" messages.
            state.start_by_max = True
            state.registration_open = False
            state.gameTime = 0
            # Важливо: контекст для start_game має бути з групового чату.
            # deep-link /join часто приходить у приваті, і тоді message.chat.id не збігається з chat_id гри.
            start_message_ctx = state.messageOfRegistration or message

            # Stop registration timer updates ASAP.
            if state.messageOfRegistration:
                try:
                    await state.messageOfRegistration.delete()
                except TelegramBadRequest:
                    pass
                except Exception:
                    pass
                state.messageOfRegistration = None

            try:
                await message.answer(
                    "🚨Нас забагато. У цій кімнаті поміститься не більше 30 осіб.",
                )
            except Exception:
                pass

            asyncio.create_task(self.start_game(message=start_message_ctx, bot=bot))

        nick_full = (message.from_user.full_name or message.from_user.first_name or "").strip() or fn
        asyncio.create_task(
            vip_mod.maybe_vip_join_group_ping(bot, chat_id, uid, nick_full)
        )

    async def start_cmd_link(self, message: Message, bot: Bot):
        parts = (message.text or "").split()
        last = parts[-1] if parts else ""
        token = (last.split("@", 1)[0] if last else "") or ""
        if message.text and token and token.lstrip("-").isdigit():
            try:
                chat_id = int(token)
            except ValueError:
                chat_id = message.chat.id
        else:
            chat_id = message.chat.id
        await self._process_registration_join(message, bot, chat_id)

    async def join_game_cmd(self, message: Message, bot: Bot):
        if message.chat.type not in ("group", "supergroup"):
            await message.answer(
                "Напиши <code>/join</code> у групі, де йде набір, або натисни «Приєднатися» в повідомленні реєстрації бота.",
                parse_mode="html",
            )
            return
        if message.from_user is None:
            return
        if await self._is_group_blocked_async(message.chat.id):
            await message.answer("🚫Лавочку прикрили. Доступу немає.")
            return
        await self._process_registration_join(message, bot, message.chat.id)

    async def players_cmd(self, message: Message, bot: Bot):
        if message.chat.type not in ("group", "supergroup"):
            return
        if await self._is_group_blocked_async(message.chat.id):
            await message.answer("🚫Лавочку прикрили. Доступу немає.")
            return
        chat_id = message.chat.id
        state = self._get_state(chat_id)
        if state.game_active:
            players_text = self._format_players_list_numbered_html(state.membersNames)
            try:
                alive_roles_info = await self._get_alive_roles_info_async(chat_id, state)
            except Exception:
                alive_roles_info = ""
            body = f"<b>Гравці у грі</b>\n\n{players_text}"
            if alive_roles_info:
                body += f"\n\n{alive_roles_info}"
            await message.answer(emoji_to_premium(body, skip_vip_badges=False), parse_mode="html")
        elif state.membersList and (getattr(state, "registration_open", True) or state.messageOfRegistration):
            names = self._format_members_comma_separated_html(state.membersNames)
            await message.answer(
                f"<b>Набір до гри ({len(state.membersList)})</b>\n\n{names}",
                parse_mode="html",
            )
        else:
            await message.answer("Зараз немає активного набору чи гри в цьому чаті.", parse_mode="html")

    async def end_discussion_cmd(self, message: Message, bot: Bot):
        if message.chat.type not in ("group", "supergroup"):
            return
        if message.from_user is None:
            return
        chat_id = message.chat.id
        user_id = message.from_user.id
        if await self._is_group_blocked_async(chat_id):
            await message.answer("🚫Лавочку прикрили. Доступу немає.")
            return
        if not await self._is_chat_admin(bot, chat_id, user_id):
            await message.answer(
                "Цю команду можуть використовувати лише <b>адміністратори чату</b> у Telegram.",
                parse_mode="html",
            )
            return
        state = self._get_state(chat_id)
        if not state.game_active:
            await message.answer("Гра зараз не йде.", parse_mode="html")
            return
        if state.voting_prep_message:
            await message.answer(
                emoji_to_premium(PLAY_ALERT_DISCUSSION_COUNTDOWN_STARTED, skip_vip_badges=False),
                parse_mode="html",
            )
            return
        if state.discussion_skipped:
            await message.answer(
                emoji_to_premium(PLAY_ALERT_DISCUSSION_ALREADY_CLOSED, skip_vip_badges=False),
                parse_mode="html",
            )
            return
        in_discussion = bool(
            state.discussion_message
            or (
                getattr(state, "discussion_task", None)
                and state.discussion_task
                and not state.discussion_task.done()
            )
        )
        if not in_discussion:
            await message.answer(
                "Зараз немає фази обговорення, яку можна достроково завершити.",
                parse_mode="html",
            )
            return
        state.discussion_skipped = True
        if getattr(state, "discussion_task", None) and state.discussion_task and not state.discussion_task.done():
            state.discussion_task.cancel()
            try:
                await state.discussion_task
            except asyncio.CancelledError:
                pass
        if state.discussion_message:
            try:
                players_text = self._format_players_list_numbered_html(state.membersNames)
                alive_roles_info = await self._get_alive_roles_info_async(chat_id, state)
                skip_body = (
                    f"Список гравців:\n\n{players_text}\n\n"
                    f"{alive_roles_info}\n\n"
                    "⏭️ Обговорення завершено адміном. Йде голосування."
                )
                await state.discussion_message.edit_text(
                    emoji_to_premium(skip_body, skip_vip_badges=False),
                    reply_markup=None,
                    parse_mode="html",
                )
            except Exception as e:
                self.print_log(f"⚠️ end_discussion: не вдалося оновити повідомлення: {e}")
        await self._start_voting_prep_timer(message, bot, chat_id, skip_prep=True)
        try:
            await message.answer("Обговорення в групі завершено адміністратором.", parse_mode="html")
        except Exception:
            pass

    def _remove_player_from_roster_lists(self, state, player_id: int) -> None:
        state.membersList = [p for p in state.membersList if p != player_id]
        state.membersNames = [(p, n) for p, n in state.membersNames if p != player_id]

    async def _apply_active_game_leave_side_effects(self, bot: Bot, chat_id: int, state, player_id: int) -> None:
        """БД і поля стану після виходу гравця під час активної гри (спільне для /leave і виходу з чату)."""
        if not state.game_active:
            return
        self._sync_devil_contract_on_player_elimination(state, player_id)
        await self._db_execute_commit(
            "UPDATE users SET killed = 1 WHERE id = %s",
            (player_id,),
        )
        was_doctor = (player_id == getattr(state, "doctor_id", 0))
        await self._refresh_state_role_ids_async(state)
        if was_doctor:
            await self._promote_nurse_to_doctor_after_doctor_death_async(state)
            await self._refresh_state_role_ids_async(state)
        self._ensure_last_word_queue(state)
        self._ensure_last_word_allowed_ids(state)
        state.last_word_queue = [(uid, kd) for uid, kd in state.last_word_queue if uid != player_id]
        state.last_word_allowed_ids.discard(player_id)
        if player_id == getattr(state, "victim_id", 0):
            state.victim_id = next(iter(state.last_word_allowed_ids), 0)
            state.is_last_message = bool(state.last_word_allowed_ids)
        if player_id == getattr(state, "patient_id", 0):
            state.patient_id = 0
        if player_id == getattr(state, "guardian_protect_id", 0):
            state.guardian_protect_id = 0
        if player_id == getattr(state, "block_action_target_id", 0):
            state.block_action_target_id = 0
        custom_block_ids = set(getattr(state, "custom_block_ids", set()) or set())
        if player_id in custom_block_ids:
            custom_block_ids.discard(player_id)
            state.custom_block_ids = custom_block_ids
        custom_protect_ids = set(getattr(state, "custom_protect_ids", set()) or set())
        if player_id in custom_protect_ids:
            custom_protect_ids.discard(player_id)
            state.custom_protect_ids = custom_protect_ids
        if player_id == getattr(state, "maniac_victim_id", 0):
            state.maniac_victim_id = 0
        if player_id == getattr(state, "sheriff_check_id", 0):
            state.sheriff_check_id = 0
        if player_id == getattr(state, "commissioner_check_id", 0):
            state.commissioner_check_id = 0
        if player_id == getattr(state, "commissioner_kill_id", 0):
            state.commissioner_kill_id = 0
        if player_id == getattr(state, "lawyer_client_id", 0):
            state.lawyer_client_id = 0
        if player_id == getattr(state, "homeless_target_id", 0):
            state.homeless_target_id = 0
        if player_id == getattr(state, "sadistic_kill_id", 0):
            state.sadistic_kill_id = 0
        if player_id == getattr(state, "sadistic_heal_id", 0):
            state.sadistic_heal_id = 0
        if player_id == getattr(state, "devil_first_kill_id", 0):
            state.devil_first_kill_id = 0
        for lst in (getattr(state, "list_of_patient", None), getattr(state, "list_of_victim", None),
                    getattr(state, "list_of_block", None), getattr(state, "list_of_guardian", None),
                    getattr(state, "list_of_sheriff", None), getattr(state, "list_of_commissioner", None),
                    getattr(state, "list_of_homeless", None), getattr(state, "list_of_lawyer", None),
                    getattr(state, "list_of_maniac", None), getattr(state, "list_of_clown", None)):
            if lst is not None and player_id in lst:
                lst.remove(player_id)
        if getattr(state, "devil_kill_targets", None) and player_id in state.devil_kill_targets:
            state.devil_kill_targets = [x for x in state.devil_kill_targets if x != player_id]
        if getattr(state, "clown_targets", None) and player_id in state.clown_targets:
            state.clown_targets.remove(player_id)
        if getattr(state, "journalist_targets", None):
            state.journalist_targets = [x for x in state.journalist_targets if x != player_id]
        if getattr(state, "silenced_ids", None):
            state.silenced_ids.discard(player_id)
        if getattr(state, "underground_taxi_used_this_game", None):
            state.underground_taxi_used_this_game.discard(player_id)
        if getattr(state, "expected_voter_ids", None):
            state.expected_voter_ids.discard(player_id)
        if getattr(state, "voted_users", None):
            state.voted_users.discard(player_id)
        if getattr(state, "day_voting_participants", None):
            state.day_voting_participants.discard(player_id)
        if getattr(state, "hanging_vote_yes", None):
            state.hanging_vote_yes.discard(player_id)
        if getattr(state, "hanging_vote_no", None):
            state.hanging_vote_no.discard(player_id)

        # Якщо з гри вийшов поточний кандидат на страту - скасовуємо це голосування.
        if getattr(state, "lynched_candidate_id", 0) == player_id:
            if getattr(state, "hanging_vote_message", None):
                try:
                    await state.hanging_vote_message.delete()
                except Exception:
                    pass
                state.hanging_vote_message = None
            state.lynched_candidate_id = 0
            state.lynched_candidate_name = ""
            state.lynched_candidate_role = ""
            state.hanging_vote_yes.clear()
            state.hanging_vote_no.clear()
            state.hanging_vote_start_time = None

    async def left_chat_member_game_handler(self, message: Message, bot: Bot):
        """Гравець вийшов з групи під час гри — прибираємо зі складу й оголошуємо в чаті."""
        left = message.left_chat_member
        if not left or getattr(left, "is_bot", False):
            return
        chat_id = message.chat.id
        if message.chat.type not in ("group", "supergroup"):
            return
        if await self._is_group_blocked_async(chat_id):
            return
        state = self._get_state(chat_id)
        if not state.game_active:
            return
        uid = int(left.id)
        if uid not in state.membersList:
            return
        role_row = await self._db_fetchone("SELECT role, tg_name FROM users WHERE id = %s", (uid,))
        role_name = (role_row[0] if role_row and role_row[0] else None) or "невідома"
        role_html = html.escape(str(role_name))
        display = html.escape((left.full_name or left.first_name or "Гравець").strip() or "Гравець")
        un = (left.username or "").strip()
        if un:
            mention_html = f'<a href="tg://user?id={uid}">@{html.escape(un)}</a>'
        else:
            mention_html = f'<a href="tg://user?id={uid}">{display}</a>'
        self._remove_player_from_roster_lists(state, uid)
        await self._apply_active_game_leave_side_effects(bot, chat_id, state, uid)
        body = (
            f"<b>☝Щур втік з корабля!</b>\n\n"
            f"{mention_html} <b>вилучено з гри</b>, його роль була <b>{role_html}</b>"
        )
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=emoji_to_premium(body, skip_vip_badges=False),
                parse_mode="html",
            )
        except Exception as e:
            self.print_log(f"⚠️ left_chat_member_game_handler: не вдалося надіслати оголошення: {e}")

    async def leave_game_cmd(self, message: Message, bot: Bot):
        if not message.from_user or not message.chat:
            return
        player_id = message.from_user.id
        chat_id: int | None = None
        state = None
        from_private = _chat_is_private_msg(message.chat)

        # У групі/супергрупі виходимо саме з поточного чату.
        if message.chat.type in ["supergroup", "group"]:
            if await self._is_group_blocked_async(message.chat.id):
                await message.answer("🚫Лавочку прикрили. Доступу немає.")
                return
            chat_id = message.chat.id
            state = self._get_state(chat_id)
        else:
            # У ПП: знаходимо активний чат(и), де користувач є у складі гри.
            candidate_chat_ids: list[int] = []
            for active_chat_id in game_state_manager.get_all_active_chats():
                st = self._get_state(active_chat_id)
                if player_id in getattr(st, "membersList", []):
                    candidate_chat_ids.append(active_chat_id)
            if not candidate_chat_ids:
                await message.answer(
                    "⚠️Тебе немає у списку. Неможливо вийти з того, до чого не приєднувався.",
                )
                return
            # Якщо одночасно в кількох іграх - виходимо з останньої знайденої (найсвіжіша в менеджері).
            chat_id = candidate_chat_ids[-1]
            if await self._is_group_blocked_async(chat_id):
                await message.answer("🚫Лавочку прикрили. Доступу немає.")
                return
            state = self._get_state(chat_id)

        if chat_id is None or state is None:
            await message.answer("🚨Осічка. Не вдалося визначити чат гри.")
            return

        try:
            if player_id not in getattr(state, "membersList", []):
                await message.answer(
                    "⚠️Тебе немає у списку. Неможливо вийти з того, до чого не приєднувався.",
                )
                return

            was_game_active = bool(getattr(state, "game_active", False))
            role_name = "невідома"
            if was_game_active:
                role_row = await self._db_fetchone("SELECT role FROM users WHERE id = %s", (player_id,))
                role_name = (role_row[0] if role_row and role_row[0] else None) or "невідома"

            self._remove_player_from_roster_lists(state, player_id)
            await self._apply_active_game_leave_side_effects(bot, chat_id, state, player_id)

            # Оголошення з роллю тільки під час активної гри.
            if was_game_active:
                try:
                    mention_html = vip_mod.html_user_link(player_id, message.from_user.first_name or "Гравець")
                    body = (
                        "<b>☝Щур втік з корабля!</b>\n\n"
                        f"{mention_html} <b>вилучено з гри</b>, його роль була <b>{html.escape(str(role_name))}</b>"
                    )
                    await bot.send_message(
                        chat_id=chat_id,
                        text=emoji_to_premium(body, skip_vip_badges=False),
                        parse_mode="html",
                    )
                except Exception:
                    pass

            if from_private:
                group_label = f"<code>{chat_id}</code>"
                try:
                    ch = await bot.get_chat(chat_id)
                    title = (getattr(ch, "title", None) or "").strip()
                    if title:
                        group_label = f"<b>{html.escape(title)}</b> (<code>{chat_id}</code>)"
                except Exception:
                    pass
                if was_game_active:
                    await message.answer(
                        f"🚪Ти покинув гру в чаті {group_label}. Якщо передумаєш - повертайся через /play, поки є час.",
                        parse_mode="html",
                    )
                else:
                    await message.answer(
                        f"🚪Ти вийшов із реєстрації в чаті {group_label}.",
                        parse_mode="html",
                    )
            else:
                if was_game_active:
                    await message.answer(
                        "🚪Ти покинув гру. Якщо передумаєш - повертайся через /play, поки є час.",
                    )
                else:
                    await message.answer("🚪Ти вийшов із реєстрації.")
        except Exception as e:
            self.print_log(f"Error in leave_game_cmd: {e}")
            await message.answer(
                "🚨Осічка.Не вдалося викреслити тебе зі списку. Спробуй ще раз.",
            )


