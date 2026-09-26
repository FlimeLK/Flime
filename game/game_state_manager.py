"""
Game State Manager - manages isolated game state per chat
Ensures complete isolation between different Telegram chats
"""

from typing import Dict, Set, List, Optional, Tuple, Any, ClassVar
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
import json
import os
import threading


class MessageRef:
    """Легкий референс повідомлення (потрібен після рестарту)."""

    def __init__(self, message_id: int):
        self.message_id = int(message_id)


@dataclass
class GameState:
    """Represents game state for a single chat"""
    chat_id: int
    
    # Player lists
    membersList: List[int] = field(default_factory=list)
    membersNames: List[Tuple[int, str]] = field(default_factory=list)
    # Full roster snapshot for end-of-game summary
    all_membersList: List[int] = field(default_factory=list)
    all_membersNames: List[Tuple[int, str]] = field(default_factory=list)
    
    # Role assignments
    all_capone_id: int = 0
    mafia_ids: List[int] = field(default_factory=list)
    civilian_ids: List[int] = field(default_factory=list)
    doctor_id: int = 0
    guardian_id: int = 0
    commissioner_id: int = 0
    sheriff_id: int = 0
    prostitute_id: int = 0
    maniac_id: int = 0
    sadistic_doctor_id: int = 0
    nurse_id: int = 0
    doctor_was_nurse: bool = False  # Чи поточний Лікар - це колишня Мед. сестра
    journalist_id: int = 0
    lawyer_id: int = 0
    werewolf_id: int = 0
    kamikaze_id: int = 0
    suicide_id: int = 0
    lucky_ids: List[int] = field(default_factory=list)
    lucky_used_this_game: Set[int] = field(default_factory=set)  # Щасливчик - хто вже вижив 1 раз за гру
    homeless_id: int = 0
    clown_id: int = 0
    infected_ids: List[int] = field(default_factory=list)
    deceiver_id: int = 0
    devil_id: int = 0
    
    # Диявол: хто підписав контракт (імунітет), хто відмовив назавжди, хто має вибрати 2 жертви цієї ночі
    devil_contract_holders: Set[int] = field(default_factory=set)
    devil_refused_permanent: Set[int] = field(default_factory=set)
    devil_contract_pending: int = 0  # user_id, який має вибрати 2 жертви цієї ночі
    devil_kill_targets: List[int] = field(default_factory=list)
    devil_contract_offered_id: int = 0  # кому цієї ночі запропоновано контракт (для callback)
    devil_first_kill_id: int = 0  # перша обрана жертва контрактника (другу обирають другим кліком)
    devil_successful_contracts: int = 0
    devil_failed: bool = False  # Диявол програє (контрактник не виконав умову)
    devil_offered_this_game: bool = False  # Диявол за гру може лише одну людину вибрати
    devil_failed_contract_holder_ids: Set[int] = field(default_factory=set)  # хто підписав, але не виконав - не в списку переможців
    devil_refusal_counts: Dict[int, int] = field(default_factory=dict)  # скільки разів гравець відмовлявся від контракту
    devil_contract_start_night: int = 0  # в яку ніч був підписаний контракт (щоб не карати в ту ж ніч)
    devil_souls_brought: int = 0  # скільки душ уже приніс поточний контрактник за гру
    devil_contract_action_taken: bool = False  # чи вже приніс душу цієї ночі
    
    # Game flow state
    game_active: bool = False
    day_active: bool = False  # Флаг, що день активний (для видалення повідомлень заблокованих гравців)
    night_number: int = 1
    gameTime: int = 0
    # False одразу після закінчення таймера / примусового старту - блокує пізнє приєднання через deep link
    registration_open: bool = True
    # Галас у казино: знімок подій для ставок
    first_night_any_death: bool = False  # чи була хоч одна смерть першої ночі
    commissioner_lynched_on_day: int = 0  # 0 = не страчено, 1/2/3 = номер дня страти Комісара/Сержанта
    # Знімок активного сезонного івенту на момент СТАРТУ гри. Завдяки цьому
    # увімкнення/вимкнення івенту з адмін-панелі під час гри не ламає поточну партію:
    # гра до кінця користується тим івентом, з яким стартувала.
    active_seasonal_event: str = None
    # Сезонні бафи учасників цієї гри: {user_id: buff_id}. Завантажуються на старті
    # гри з kupala_pending_buffs (і там одразу споживаються). Інертні, якщо порожньо.
    kupala_buffs: dict = field(default_factory=dict)
    # ── Ролі івенту «Купальська ніч» ──
    mermaid_id: int = 0               # хто Русалка
    mermaid_redirect_a: int = 0       # «Водний потік»: ціль А (звідки перетікає)
    mermaid_redirect_b: int = 0       # «Водний потік»: ціль Б (куди перетікає)
    water_flow_redirected_to: int = 0 # кому реально перетекла атака (ліхтарик не світить на нього)
    mermaid_protect_id: int = 0       # «Оберіг глибин»: кого захищено цю ніч (невразливість)
    mermaid_weakened: bool = False    # «Виснаження»: цю ніч Русалка не діє
    mermaid_weakened_pending: bool = False  # стане «Виснаженою» наступної ночі (після захисту)
    mermaid_last_protect_id: int = 0  # для правила «не захищати себе двічі поспіль»
    hunter_id: int = 0                # хто Мисливець на русалку
    hunter_silence_id: int = 0        # «Засідка»: чию нічну дію скасовано
    hunter_harpoon_id: int = 0        # «Гарпун»: ціль цієї ночі (ігнорує щити)
    hunter_harpoon_used: bool = False # «Гарпун» вже використано (1/гру)

    # Action tracking (prevent duplicates)
    mafia_action_taken: bool = False
    doctor_action_taken: bool = False
    doctor_self_heal_used: bool = False  # Самолікування: 1 раз за гру
    guardian_action_taken: bool = False
    commissioner_action_taken: bool = False
    sheriff_action_taken: bool = False
    block_action_taken: bool = False
    prostitute_last_target_id: int = 0  # Коханка не може ходити до того самого гравця дві ночі поспіль
    prostitute_no_target_this_night: bool = False  # Коханці цієї ночі нікого не можна було обрати - не рахувати неактивність
    prostitute_black_cat_sniff_used_this_game: bool = False  # «Дізнатися» / нюх при візиті — щонайбільше 1 раз за гру
    maniac_action_taken: bool = False
    sadistic_action_taken: bool = False
    clown_action_taken: bool = False
    infected_action_taken: bool = False
    deceiver_action_taken: bool = False
    clown_used: bool = False
    clown_swap_used_players: Set[int] = field(default_factory=set)  # Кожен гравець може юзнути роль Клоуна лише 1 раз за гру
    clown_role_changes_count: int = 0  # Скільки разів у цій грі вже міняли ролі клоуном (звичайний swap або total shuffle)
    # Кому вже показували кнопку «перемішати всі» (по user_id клоуна) — щоб новий власник ролі після передачі бачив пропозицію
    clown_mass_shuffle_offer_shown_to: Set[int] = field(default_factory=set)
    # Після зміни ролей Клоуном: цієї ночі рольові кнопки заблоковані, нова роль активна з наступної ночі.
    clown_role_blocked_this_night: Set[int] = field(default_factory=set)
    clown_role_block_notice_sent_this_night: Set[int] = field(default_factory=set)
    sergeant_passive_night_sent: bool = False  # Повідомлення «Сержант не виконує нічних дій» - лише 1 раз за гру
    mafia_allies_sent: bool = False  # Повідомлення «Твої союзники» Дону та Мафії - лише 1 раз за гру
    big_el_wisdom_sent: bool = False  # «Великий Ел ділиться мудрістю» - лише 1 раз за гру
    victim_id: int = 0
    patient_id: int = 0
    guardian_protect_id: int = 0
    lucky_survived: bool = False  # Флаг, що Щасливчик вижив цієї ночі
    block_action_target_id: int = 0
    maniac_victim_id: int = 0
    sadistic_kill_id: int = 0
    custom_kill_ids: List[int] = field(default_factory=list)  # Кастомні ролі: цілі з нічною здібністю Kill
    custom_block_ids: Set[int] = field(default_factory=set)  # Кастомні ролі: цілі з нічною здібністю Block
    custom_protect_ids: Set[int] = field(default_factory=set)  # Кастомні ролі: цілі з нічною здібністю Heal/Protect
    sadistic_heal_id: int = 0
    sheriff_check_id: int = 0
    commissioner_check_id: int = 0
    commissioner_kill_id: int = 0
    lawyer_client_id: int = 0
    homeless_target_id: int = 0
    journalist_targets: List[int] = field(default_factory=list)
    silenced_ids: Set[int] = field(default_factory=set)
    visit_log: List[Tuple[int, int, str]] = field(default_factory=list)  # (visitor_id, target_id, action)
    eavesdropping_blocked: bool = False  # Глушилка сигналу - блокує всі підслуховування цієї ночі
    fire_extinguisher_used_this_night: Set[int] = field(default_factory=set)  # Хто натиснув вогнегасник цієї ночі
    fire_extinguisher_used_this_game: Set[int] = field(default_factory=set)  # Хто вже використав вогнегасник цю гру (1 раз за гру)
    pager_used_this_game: Set[int] = field(default_factory=set)  # Хто вже отримав повідомлення від пейджера цю гру (1 раз за гру)
    id_card_used_this_game: Set[int] = field(default_factory=set)  # Посвідчення особи - хто вже використав
    mirror_used_this_game: Set[int] = field(default_factory=set)  # Дзеркало - хто вже використав цю гру
    candy_used_this_game: Set[int] = field(default_factory=set)  # Цукерка - хто вже використав цю гру
    trap_used_this_game: Set[int] = field(default_factory=set)  # Капкан - хто вже спрацював
    underground_taxi_used_this_game: Set[int] = field(default_factory=set)  # Підпільне таксі - хто вже втік
    black_opel_used_this_game: Set[int] = field(default_factory=set)  # Чорний «Опель» - кого вже врятував від страти
    tommy_gun_used_this_game: Set[int] = field(default_factory=set)  # Tommy Gun - кого вже помстився за смерть
    knife_used_this_game: Set[int] = field(default_factory=set)  # Заточка - хто вже вдарив цією грою
    knife_offer_sent_this_game: Set[int] = field(default_factory=set)  # Заточка - кому вже надіслано запрошення (1 раз за гру)
    knife_role_locked_users: Set[int] = field(default_factory=set)  # Хто цієї ночі вже обрав заточку і не може робити рольову дію
    parfum_shop_used_this_game: Set[int] = field(default_factory=set)  # 🧴 Парфум з магазину — лише 1 спрацьовування на гру на гравця
    talisman_shop_used_this_game: Set[int] = field(default_factory=set)  # 📿 Талісман — лише 1 спрацьовування на гру на гравця (жертва або нападник у ланцюгу Tommy)
    knife_kill_ids: List[int] = field(default_factory=list)  # Заточка - хто вбитий цієї ночі (для ранкового оголошення)
    # ── Дуель (налаштування гри): рівно один Мирний житель отримує 2 патрони й може викликати когось уночі (50/50), 1 раз за гру ──
    duels_enabled: bool = False              # чи ввімкнено дуелі в цій грі (з admin_panel)
    duel_shooter_id: int = 0                 # обраний Мирний житель з патронами (0 = ще не обрано / вимкнено)
    duel_used: bool = False                  # дуель уже проведено цієї гри
    duel_offer_sent: bool = False            # запрошення дуелянту вже надіслано
    duel_kill_ids: List[int] = field(default_factory=list)  # хто гине від дуелі цієї ночі (для світанку)
    mafia_member_personal_night_done: Set[int] = field(default_factory=set)  # Мафія (не Дон): заточка/баф — не блокує вибір Аль Капоне
    flashlight_used_this_game: Set[int] = field(default_factory=set)  # Ліхтарик / новий Ліхтарик - хто вже використав
    smoke_grenade_activated_this_night: Set[int] = field(default_factory=set)  # Димова шашка / Капелюх - хто невидимий цієї ночі
    smoke_grenade_used_this_game: Set[int] = field(default_factory=set)  # Димова шашка / Капелюх - хто вже використав невидимість у цій грі
    capone_hat_scheduled_for_night: Set[int] = field(default_factory=set)  # Капелюх КаПоне - хто активував вдень на наступну ніч
    mask_used_this_night: Set[int] = field(default_factory=set)  # Маска - хто вже спрацювала цієї ночі
    flashlight_choice: Dict[int, int] = field(default_factory=dict)  # Ліхтарик: user_id -> target_id (результат після ночі)
    clown_targets: List[int] = field(default_factory=list)
    infected_target_id: int = 0
    deceiver_target_id: int = 0

    # Портал: унікальні бафи (цілі нічних активних бафів)
    portal_ribbon_protected: Dict[int, int] = field(default_factory=dict)   # target_id -> owner_id (стрічка: хто захищений і хто повʼязав)
    portal_smell_fry_targets: Set[int] = field(default_factory=set)        # target_id з «запахом фрі» - візитери нічого не роблять
    portal_spirit_isolated: Set[int] = field(default_factory=set)           # target_id в ізоляції «Дух 2021»
    portal_seeds_skip: Set[int] = field(default_factory=set)               # target_id пропускає ніч (лускали насіння)
    portal_kyiv_taste: Dict[int, int] = field(default_factory=dict)         # target_id -> owner_id (кого пригостили; голос проти owner анулюється)
    # Баф «Контракт з дияволом»: захист одного повного дня + однієї ночі після активації
    devil_covenant_day_shield: Set[int] = field(default_factory=set)
    devil_covenant_night_shield: Set[int] = field(default_factory=set)
    
    # Voting state
    voted_users: Set[int] = field(default_factory=set)
    list_of_all_votes: List[Tuple[int, int]] = field(default_factory=list)
    list_of_candidates: List[int] = field(default_factory=list)
    message_list_of_candidates: Dict[int, any] = field(default_factory=dict)
    
    # Hanging confirmation vote (👍/👎)
    lynched_candidate_id: int = 0  # ID гравця, якого обрали для повішення
    lynched_candidate_name: str = ""  # Ім'я кандидата
    lynched_candidate_role: str = ""  # Роль кандидата
    hanging_vote_yes: Set[int] = field(default_factory=set)  # Гравці, які проголосували 👍
    hanging_vote_no: Set[int] = field(default_factory=set)  # Гравці, які проголосували 👎
    hanging_vote_message: Optional[any] = None  # Повідомлення з кнопками 👍/👎
    hanging_vote_private_messages: Dict[int, any] = field(default_factory=dict)  # Приватні повідомлення про голосування про повішення
    hanging_vote_start_time: Optional[datetime] = None  # Час початку фінального голосування
    suicide_was_lynched: bool = False  # Чи був повішений Самогубець
    kamikaze_target_id: int = 0  # ID гравця, якого обрав Камікадзе для взяття з собою
    kamikaze_choice_made: bool = False  # Чи зробив Камікадзе вибір
    kamikaze_lynched_id: int = 0  # ID Камікадзе, який був повішений (для перевірки права на вибір)
    
    # Civilian questions storage (player_id -> question tuple)
    civilian_questions: Dict[int, Tuple[str, str, str]] = field(default_factory=dict)
    # Повідомлення з питанням для МЖ (player_id -> Message), окремо від message_list_of_candidates (голосування)
    civilian_question_messages: Dict[int, any] = field(default_factory=dict)
    
    # Night action lists
    list_of_victim: List[int] = field(default_factory=list)
    list_of_patient: List[int] = field(default_factory=list)
    list_of_guardian: List[int] = field(default_factory=list)
    list_of_block: List[int] = field(default_factory=list)
    list_of_maniac: List[int] = field(default_factory=list)
    list_of_sadistic: List[int] = field(default_factory=list)
    list_of_sheriff: List[int] = field(default_factory=list)
    list_of_commissioner: List[int] = field(default_factory=list)
    list_of_homeless: List[int] = field(default_factory=list)
    list_of_journalist: List[int] = field(default_factory=list)
    list_of_lawyer: List[int] = field(default_factory=list)
    list_of_clown: List[int] = field(default_factory=list)
    list_of_infected: List[int] = field(default_factory=list)
    list_of_deceiver: List[int] = field(default_factory=list)
    list_of_devil: List[int] = field(default_factory=list)
    
    # Game messages
    messageOfRegistration: Optional[any] = None
    choose_who_you_will_cured: Optional[any] = None
    choose_who_you_will_kill: Optional[any] = None
    choose_who_you_will_protect: Optional[any] = None
    choose_who_you_will_block: Optional[any] = None
    choose_who_maniac_will_kill: Optional[any] = None
    choose_who_sadistic_will_kill: Optional[any] = None
    choose_who_sadistic_will_heal: Optional[any] = None
    choose_who_sheriff_will_check: Optional[any] = None
    choose_who_commissioner_will_check: Optional[any] = None
    choose_who_commissioner_will_kill: Optional[any] = None
    choose_who_homeless_will_check: Optional[any] = None
    choose_who_journalist_will_check: Optional[any] = None
    choose_who_lawyer_will_protect: Optional[any] = None
    choose_who_clown_will_swap: Optional[any] = None
    choose_who_infected_will_infect: Optional[any] = None
    choose_who_deceiver_will_fake: Optional[any] = None
    message_about_voiting: Optional[any] = None
    message_for_civilian: Optional[any] = None
    # Messages with per-player voting logs ("X проголосував за Y") to clean up after voting
    voting_log_messages: List[any] = field(default_factory=list)
    
    # Discussion and voting prep state
    discussion_skipped: bool = False  # Чи було обговорення пропущено
    discussion_message: Optional[any] = None  # Повідомлення про обговорення
    discussion_started_at: Optional[datetime] = None  # Старт фази обговорення (для відновлення таймера після рестарту)
    voting_prep_message: Optional[any] = None  # Повідомлення про відлік до голосування
    voting_start_time: Optional[datetime] = None  # Час початку голосування (45 с) - щоб відхиляти голоси після часу
    expected_voter_ids: Set[int] = field(default_factory=set)  # Хто має проголосувати (живі, не в мовці) - щоб завершити голосування одразу, коли всі проголосували
    discussion_task: Optional[any] = None  # Завдання для обговорення (для можливості скасування)
    skip_discussion_votes: Set[int] = field(default_factory=set)  # Гравці, які проголосували за пропуск обговорення
    muted_during_game: Set[int] = field(default_factory=set)  # Користувачі, замучені під час гри (не гравці писали в чат)
    # Неактивність: 3 ночі поспіль без вибору в боті - виключення з гри (окрім МЖ та Щасливчика)
    inactive_nights_count: Dict[int, int] = field(default_factory=dict)  # user_id -> кількість ночей поспіль без дії
    kicked_for_inactivity: List[Tuple[int, str]] = field(default_factory=list)  # (user_id, tg_name) виключених цього переходу до дня
    day_voting_participants: Set[int] = field(default_factory=set)  # хто голосував удень — знімає лічильник AFK (як нічна дія)
    
    # Game results
    victim_text: str = ""
    is_killed: int = 0
    is_last_message: bool = False
    # Черга останніх слів після поточного victim_id: (user_id, killed_by_don)
    last_word_queue: List[Tuple[int, bool]] = field(default_factory=list)
    
    # Role names (customizable)
    name_of_all_capone: str = "Аль Капоне"
    name_of_doctor: str = "Лікар"
    name_of_civilian: str = "Мирний житель"
    description_of_doctor: str = "Ти - лікар! Рятуй гравців вночі."
    description_of_all_capone: str = "Ти - Аль Капоне! Вбивай гравців вночі."
    description_of_civilian: str = "Ти - мирний житель! Знайди мафію."
    
    # Game settings
    numbers_of_members: int = 2
    MN: int = 2
    
    # Civilian questions
    question_and_two_answers: List[Tuple[str, str, str]] = field(default_factory=list)
    list_question: Optional[Tuple[str, str, str]] = None
    
    # Feedback
    like: int = 0
    dislike: int = 0

    # Пінгачок: хто активний у чаті та хто попросив не тегати
    recent_chat_users: Set[int] = field(default_factory=set)
    ping_opt_out_ids: Set[int] = field(default_factory=set)
    
    # Події для досягнень (event_type, player_id) - накопичуються протягом гри
    game_achievement_events: List[Tuple[str, int]] = field(default_factory=list)
    
    # Timestamp for cleanup
    last_activity: datetime = field(default_factory=datetime.now)
    # Момент фактичного старту партії (після реєстрації) — для «Гра тривала: …» у фіналі
    game_started_at: Optional[datetime] = None
    # Коли стартувала поточна ніч (для відновлення таймера після рестарту)
    night_started_at: Optional[datetime] = None
    # AFK-автовибір уже застосовано в цій фазі
    afk_night_auto_choice_applied: bool = False
    afk_day_auto_choice_applied: bool = False

    _MESSAGE_REF_FIELDS: ClassVar[Set[str]] = {
        "messageOfRegistration",
        "choose_who_you_will_cured",
        "choose_who_you_will_kill",
        "choose_who_you_will_protect",
        "choose_who_you_will_block",
        "choose_who_maniac_will_kill",
        "choose_who_sadistic_will_kill",
        "choose_who_sadistic_will_heal",
        "choose_who_sheriff_will_check",
        "choose_who_commissioner_will_check",
        "choose_who_commissioner_will_kill",
        "choose_who_homeless_will_check",
        "choose_who_journalist_will_check",
        "choose_who_lawyer_will_protect",
        "choose_who_clown_will_swap",
        "choose_who_infected_will_infect",
        "choose_who_deceiver_will_fake",
        "message_about_voiting",
        "message_for_civilian",
        "discussion_message",
        "voting_prep_message",
        "hanging_vote_message",
        "choose_commissioner_action_menu",
    }
    _DROP_ON_PERSIST_FIELDS: ClassVar[Set[str]] = {
        "discussion_task",
        "message_list_of_candidates",
        "hanging_vote_private_messages",
        "civilian_question_messages",
        "voting_log_messages",
    }

    @staticmethod
    def _encode_value(value: Any) -> Any:
        if isinstance(value, datetime):
            return {"__dt__": value.isoformat()}
        if isinstance(value, set):
            return {"__set__": [GameState._encode_value(v) for v in value]}
        if isinstance(value, tuple):
            return {"__tuple__": [GameState._encode_value(v) for v in value]}
        if isinstance(value, list):
            return [GameState._encode_value(v) for v in value]
        if isinstance(value, dict):
            return {str(k): GameState._encode_value(v) for k, v in value.items()}
        return value

    @staticmethod
    def _decode_value(value: Any) -> Any:
        if isinstance(value, dict):
            if "__dt__" in value:
                try:
                    return datetime.fromisoformat(value["__dt__"])
                except Exception:
                    return None
            if "__set__" in value:
                return {GameState._decode_value(v) for v in value["__set__"]}
            if "__tuple__" in value:
                return tuple(GameState._decode_value(v) for v in value["__tuple__"])
            decoded: Dict[Any, Any] = {}
            for k, v in value.items():
                key = int(k) if isinstance(k, str) and k.lstrip("-").isdigit() else k
                decoded[key] = GameState._decode_value(v)
            return decoded
        if isinstance(value, list):
            return [GameState._decode_value(v) for v in value]
        return value

    def to_persist_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        for f in fields(self):
            name = f.name
            if name in self._DROP_ON_PERSIST_FIELDS:
                continue
            value = getattr(self, name)
            if name in self._MESSAGE_REF_FIELDS:
                data[name] = int(getattr(value, "message_id", 0) or 0) if value is not None else None
                continue
            data[name] = self._encode_value(value)
        return data

    @classmethod
    def from_persist_dict(cls, raw: Dict[str, Any]) -> "GameState":
        chat_id = int(raw.get("chat_id"))
        state = cls(chat_id=chat_id)
        for f in fields(state):
            name = f.name
            if name not in raw:
                continue
            if name in state._DROP_ON_PERSIST_FIELDS:
                continue
            if name in state._MESSAGE_REF_FIELDS:
                mid = raw.get(name)
                setattr(state, name, MessageRef(mid) if mid else None)
                continue
            setattr(state, name, cls._decode_value(raw.get(name)))

        # Колекції Message-об'єктів не відновлюємо після рестарту.
        state.message_list_of_candidates = {}
        state.hanging_vote_private_messages = {}
        state.civilian_question_messages = {}
        state.voting_log_messages = []
        state.discussion_task = None
        return state
    
    def reset_for_new_game(self):
        """Reset state for a new game"""
        self.game_active = True
        self.game_started_at = datetime.now()
        self.night_started_at = None
        self.afk_night_auto_choice_applied = False
        self.afk_day_auto_choice_applied = False
        self.day_active = False
        self.night_number = 1
        self.first_night_any_death = False
        self.mafia_action_taken = False
        self.mafia_member_personal_night_done.clear()
        self.doctor_action_taken = False
        self.doctor_self_heal_used = False
        self.guardian_action_taken = False
        self.commissioner_action_taken = False
        self.sheriff_action_taken = False
        self.block_action_taken = False
        self.prostitute_last_target_id = 0
        self.prostitute_no_target_this_night = False
        self.prostitute_black_cat_sniff_used_this_game = False
        setattr(self, "prostitute_black_cat_declined_this_game", False)
        setattr(self, "prostitute_black_cat_used_this_night", False)
        self.maniac_action_taken = False
        self.sadistic_action_taken = False
        self.clown_action_taken = False
        # ── Купальська ніч: повне скидання ролей івенту на нову гру ──
        self.mermaid_id = 0
        self.mermaid_redirect_a = 0
        self.mermaid_redirect_b = 0
        self.water_flow_redirected_to = 0
        self.mermaid_protect_id = 0
        self.mermaid_weakened = False
        self.mermaid_weakened_pending = False
        self.mermaid_last_protect_id = 0
        self.hunter_id = 0
        self.hunter_silence_id = 0
        self.hunter_harpoon_id = 0
        self.hunter_harpoon_used = False
        # Блок «нової ролі від Клоуна» діє лише ту ніч, коли стався обмін.
        # Без цього скидання прапорці прилипали назавжди й кнопки тих гравців
        # до кінця гри відповідали «дія доступна з наступної ночі».
        try:
            self.clown_role_blocked_this_night = set()
            self.clown_role_block_notice_sent_this_night = set()
        except Exception:
            pass
        self.infected_action_taken = False
        self.deceiver_action_taken = False
        self.mafia_ids.clear()
        self.infected_ids.clear()
        self.voted_users.clear()
        self.list_of_all_votes.clear()
        self.expected_voter_ids.clear()
        self.voting_log_messages.clear()
        self.victim_id = 0
        self.patient_id = 0
        self.guardian_protect_id = 0
        self.block_action_target_id = 0
        self.maniac_victim_id = 0
        self.sadistic_kill_id = 0
        self.custom_kill_ids.clear()
        self.custom_block_ids.clear()
        self.custom_protect_ids.clear()
        self.sadistic_heal_id = 0
        self.sheriff_check_id = 0
        self.commissioner_check_id = 0
        self.commissioner_kill_id = 0
        self.lawyer_client_id = 0
        self.homeless_target_id = 0
        self.journalist_targets.clear()
        self.silenced_ids.clear()
        self.visit_log.clear()
        self.eavesdropping_blocked = False
        self.fire_extinguisher_used_this_night.clear()
        self.fire_extinguisher_used_this_game.clear()
        self.pager_used_this_game.clear()
        self.id_card_used_this_game.clear()
        self.mirror_used_this_game.clear()
        self.candy_used_this_game.clear()
        self.trap_used_this_game.clear()
        self.underground_taxi_used_this_game.clear()
        self.black_opel_used_this_game.clear()
        self.tommy_gun_used_this_game.clear()
        self.lucky_used_this_game.clear()
        self.knife_used_this_game.clear()
        self.knife_offer_sent_this_game.clear()
        self.knife_role_locked_users.clear()
        # Дуель - повне скидання на нову гру
        self.duels_enabled = False
        self.duel_shooter_id = 0
        self.duel_used = False
        self.duel_offer_sent = False
        self.duel_kill_ids.clear()
        setattr(self, "duel_pending", None)
        self.parfum_shop_used_this_game.clear()
        self.talisman_shop_used_this_game.clear()
        self.flashlight_used_this_game.clear()
        self.smoke_grenade_activated_this_night.clear()
        self.smoke_grenade_used_this_game.clear()  # Очищаємо список використаних Капелюхів/Димових шашок
        self.capone_hat_scheduled_for_night.clear()
        self.mask_used_this_night.clear()
        self.clown_used = False  # Клоун: раз за гру - скидаємо для нової гри
        self.clown_swap_used_players.clear()
        self.clown_role_changes_count = 0
        self.clown_mass_shuffle_offer_shown_to.clear()
        self.clown_role_blocked_this_night.clear()
        self.clown_role_block_notice_sent_this_night.clear()
        self.sergeant_passive_night_sent = False
        self.mafia_allies_sent = False
        self.big_el_wisdom_sent = False
        self.clown_targets.clear()
        self.clown_role_blocked_this_night.clear()
        self.clown_role_block_notice_sent_this_night.clear()
        self.infected_target_id = 0
        self.deceiver_target_id = 0
        self.is_killed = 0
        self.is_last_message = False
        self.last_word_queue.clear()
        self.suicide_was_lynched = False
        self.list_of_victim.clear()
        self.list_of_patient.clear()
        self.list_of_guardian.clear()
        self.list_of_block.clear()
        self.list_of_maniac.clear()
        self.list_of_sadistic.clear()
        self.voting_log_messages.clear()
        self.list_of_sheriff.clear()
        self.list_of_commissioner.clear()
        self.list_of_homeless.clear()
        self.list_of_journalist.clear()
        self.list_of_lawyer.clear()
        self.list_of_clown.clear()
        self.list_of_infected.clear()
        self.list_of_deceiver.clear()
        self.list_of_devil.clear()
        self.devil_contract_holders.clear()
        self.devil_refused_permanent.clear()
        self.devil_contract_pending = 0
        self.devil_kill_targets.clear()
        self.devil_contract_offered_id = 0
        self.devil_first_kill_id = 0
        self.devil_successful_contracts = 0
        self.devil_failed = False
        self.devil_offered_this_game = False
        self.devil_failed_contract_holder_ids.clear()
        self.devil_refusal_counts.clear()
        self.devil_contract_start_night = 0
        self.devil_souls_brought = 0
        self.devil_contract_action_taken = False
        self.doctor_was_nurse = False  # Скидаємо при новій грі
        self.discussion_skipped = False
        self.portal_ribbon_protected.clear()
        self.portal_smell_fry_targets.clear()
        self.portal_spirit_isolated.clear()
        self.portal_seeds_skip.clear()
        self.portal_kyiv_taste.clear()
        self.devil_covenant_day_shield.clear()
        self.devil_covenant_night_shield.clear()
        self.discussion_message = None
        self.discussion_started_at = None
        self.voting_prep_message = None
        self.voting_start_time = None
        self.discussion_task = None
        self.skip_discussion_votes.clear()
        self.muted_during_game.clear()
        self.inactive_nights_count.clear()
        self.kicked_for_inactivity.clear()
        self.day_voting_participants.clear()
        self.hanging_vote_start_time = None
        self.game_achievement_events.clear()
        self.last_activity = datetime.now()
        self.portal_ribbon_protected.clear()
        self.portal_smell_fry_targets.clear()
        self.portal_spirit_isolated.clear()
        self.portal_seeds_skip.clear()
        self.portal_kyiv_taste.clear()
        self.devil_covenant_day_shield.clear()
        self.devil_covenant_night_shield.clear()
    
    def reset_for_new_night(self):
        """Reset state for a new night"""
        self.day_active = False  # Скидаємо флаг дня при переході до ночі
        self.night_started_at = datetime.now()
        self.afk_night_auto_choice_applied = False
        # Кіт: анти-дубль кліків «Дізнатися» за одну ніч (ліміт 1 раз / гру — у prostitute_black_cat_sniff_used_this_game)
        setattr(self, "prostitute_black_cat_used_this_night", False)
        self.mafia_action_taken = False
        self.mafia_member_personal_night_done.clear()
        self.doctor_action_taken = False
        # doctor_self_heal_used не скидаємо - 1 раз за всю гру
        self.guardian_action_taken = False
        self.commissioner_action_taken = False
        self.sheriff_action_taken = False
        self.block_action_taken = False
        self.prostitute_no_target_this_night = False
        self.maniac_action_taken = False
        self.sadistic_action_taken = False
        self.clown_action_taken = False
        # Блок «нової ролі від Клоуна» діє лише ту ніч, коли стався обмін.
        # Без цього скидання прапорці прилипали назавжди й кнопки тих гравців
        # до кінця гри відповідали «дія доступна з наступної ночі».
        try:
            self.clown_role_blocked_this_night = set()
            self.clown_role_block_notice_sent_this_night = set()
        except Exception:
            pass
        self.infected_action_taken = False
        self.deceiver_action_taken = False
        # ── Купальська ніч: скидання нічних цілей ролей + перехід «Виснаження» ──
        self.mermaid_redirect_a = 0
        self.mermaid_redirect_b = 0
        self.water_flow_redirected_to = 0
        self.mermaid_protect_id = 0
        self.hunter_silence_id = 0
        self.hunter_harpoon_id = 0
        # «Виснаження» спрацьовує саме ту ніч, що йде після використання «Оберегу глибин».
        self.mermaid_weakened = self.mermaid_weakened_pending
        self.mermaid_weakened_pending = False
        self.victim_id = 0
        self.patient_id = 0
        self.victim_text = ""  # Очищаємо текст жертви перед новою ніччю
        self.guardian_protect_id = 0
        self.block_action_target_id = 0
        self.maniac_victim_id = 0
        self.sadistic_kill_id = 0
        self.custom_kill_ids.clear()
        self.custom_block_ids.clear()
        self.custom_protect_ids.clear()
        self.sadistic_heal_id = 0
        self.sheriff_check_id = 0
        self.commissioner_check_id = 0
        self.commissioner_kill_id = 0
        self.lawyer_client_id = 0
        self.homeless_target_id = 0
        self.journalist_targets.clear()
        self.silenced_ids.clear()
        self.visit_log.clear()
        self.eavesdropping_blocked = False
        self.fire_extinguisher_used_this_night.clear()
        self.smoke_grenade_activated_this_night.clear()
        self.knife_kill_ids.clear()
        self.knife_role_locked_users.clear()
        self.duel_kill_ids.clear()
        self.mask_used_this_night.clear()
        self.flashlight_choice.clear()
        # НЕ скидаємо fire_extinguisher_used_this_game - вогнегасник лише 1 раз за гру
        self.clown_targets.clear()
        self.infected_target_id = 0
        self.deceiver_target_id = 0
        self.list_of_victim.clear()
        self.list_of_patient.clear()
        self.list_of_guardian.clear()
        self.list_of_block.clear()
        self.list_of_maniac.clear()
        self.list_of_sadistic.clear()
        self.list_of_sheriff.clear()
        self.list_of_commissioner.clear()
        self.list_of_homeless.clear()
        self.list_of_journalist.clear()
        self.list_of_lawyer.clear()
        self.list_of_clown.clear()
        self.list_of_infected.clear()
        self.list_of_deceiver.clear()
        self.list_of_devil.clear()
        self.devil_kill_targets.clear()
        self.devil_contract_offered_id = 0
        self.devil_first_kill_id = 0
        self.devil_contract_action_taken = False
        self.discussion_skipped = False  # Скидаємо при новій ночі
        self.discussion_message = None
        self.discussion_started_at = None
        self.voting_prep_message = None
        self.voting_start_time = None
        self.afk_day_auto_choice_applied = False
        self.discussion_task = None
        self.skip_discussion_votes.clear()
        self.muted_during_game.clear()
        self.kicked_for_inactivity.clear()
        self.hanging_vote_start_time = None
        self.last_activity = datetime.now()
        # Портал: унікальні бафи - цілі скидаємо щонічі (гравці обирають заново)
        self.portal_ribbon_protected.clear()
        self.portal_smell_fry_targets.clear()
        self.portal_spirit_isolated.clear()
        self.portal_seeds_skip.clear()
        self.portal_kyiv_taste.clear()
    
    def cleanup(self):
        """Cleanup resources"""
        self.membersList.clear()
        self.membersNames.clear()
        self.civilian_ids.clear()
        self.voted_users.clear()
        self.list_of_all_votes.clear()
        self.list_of_candidates.clear()
        self.message_list_of_candidates.clear()
        self.civilian_question_messages.clear()
        self.list_of_victim.clear()
        self.list_of_patient.clear()
        self.list_of_guardian.clear()
        self.list_of_block.clear()
        self.list_of_maniac.clear()
        self.list_of_sadistic.clear()
        self.list_of_sheriff.clear()
        self.list_of_commissioner.clear()
        self.list_of_homeless.clear()
        self.list_of_journalist.clear()
        self.list_of_lawyer.clear()
        self.mafia_ids.clear()
        self.silenced_ids.clear()
        self.visit_log.clear()
        self.eavesdropping_blocked = False
        self.fire_extinguisher_used_this_night.clear()
        self.fire_extinguisher_used_this_game.clear()
        self.pager_used_this_game.clear()
        self.mirror_used_this_game.clear()
        self.candy_used_this_game.clear()
        self.knife_role_locked_users.clear()
        self.list_of_clown.clear()
        self.list_of_infected.clear()
        self.list_of_deceiver.clear()
        self.infected_ids.clear()
        self.sergeant_passive_night_sent = False
        self.mafia_allies_sent = False


class GameStateManager:
    """Manages game state for multiple chats with thread-safe access"""
    
    def __init__(self):
        self._states: Dict[int, GameState] = {}
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        self._persist_path = (
            Path(__file__).resolve().parent.parent / "runtime" / "game_states.json"
        )
    
    def get_state(self, chat_id: int) -> GameState:
        """Get or create game state for a chat"""
        with self._lock:
            if chat_id not in self._states:
                self._states[chat_id] = GameState(chat_id=chat_id)
            self._states[chat_id].last_activity = datetime.now()
            return self._states[chat_id]
    
    def has_state(self, chat_id: int) -> bool:
        """Check if state exists for a chat"""
        with self._lock:
            return chat_id in self._states
    
    def remove_state(self, chat_id: int):
        """Remove game state for a chat"""
        with self._lock:
            if chat_id in self._states:
                self._states[chat_id].cleanup()
                del self._states[chat_id]
    
    def cleanup_inactive(self, max_age_seconds: int = 3600):
        """Remove inactive game states (older than max_age_seconds)"""
        with self._lock:
            now = datetime.now()
            to_remove = []
            for chat_id, state in self._states.items():
                age = (now - state.last_activity).total_seconds()
                if age > max_age_seconds and not state.game_active:
                    to_remove.append(chat_id)
            
            for chat_id in to_remove:
                self.remove_state(chat_id)
    
    def get_all_active_chats(self) -> List[int]:
        """Get list of all chats with active games"""
        with self._lock:
            return [chat_id for chat_id, state in self._states.items() if state.game_active]

    def get_chat_awaiting_last_message_from(self, user_id: int):
        """Повертає chat_id групи, де очікується останнє повідомлення від user_id (вбитого), або None.
        Шукає по всіх станах з is_last_message, не тільки де game_active - щоб не втратити повідомлення."""
        with self._lock:
            for cid, state in self._states.items():
                if getattr(state, "is_last_message", False) and getattr(state, "victim_id", 0) == user_id:
                    return cid
            return None

    def __contains__(self, chat_id: int) -> bool:
        """Check if chat_id has state"""
        return self.has_state(chat_id)

    def save_to_disk(self) -> None:
        """Зберігає всі стани в JSON (атомарно)."""
        with self._lock:
            payload = {
                "saved_at": datetime.now().isoformat(),
                "states": [state.to_persist_dict() for state in self._states.values()],
            }
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._persist_path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp_path, self._persist_path)

    def load_from_disk(self) -> int:
        """Завантажує стани з JSON. Повертає кількість відновлених чатів."""
        with self._lock:
            if not self._persist_path.exists():
                return 0
            try:
                with self._persist_path.open("r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                return 0

            loaded: Dict[int, GameState] = {}
            for raw in payload.get("states", []) or []:
                try:
                    state = GameState.from_persist_dict(raw)
                    loaded[int(state.chat_id)] = state
                except Exception:
                    continue
            self._states = loaded
            return len(self._states)


# Global game state manager instance
game_state_manager = GameStateManager()
