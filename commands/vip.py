"""
VIP / VIP+ підписки: переваги в рулетці, щоденний бонус, VIP-ринок (див. buff_shop).

subscription_type у БД: vip_30, vip_plus_30
"""
from __future__ import annotations

import html as html_module
import random
from datetime import date, datetime, timedelta

from premium_emoji import emoji_to_premium
from typing import Literal, Optional

from database.database import cursor, conn

VIP_ITEM_ID = "vip_30"
VIP_PLUS_ITEM_ID = "vip_plus_30"
LEGACY_ADVENT_VIP_ITEM_ID = "advent"

VipTier = Literal["vip", "vip_plus"]


def _db_fetchone(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_fetchall(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchall()


def _db_execute_commit(query: str, params: tuple = ()) -> None:
    cursor.execute(query, params)
    conn.commit()


# Власник бота (засновник №1). Решта засновників — у таблиці founders.
BOT_OWNER_ID = 1859870653


def is_bot_founder(user_id: int) -> bool:
    """Засновник бота: власник або активний запис у таблиці founders.

    Засновники мають вічний VIP+ (без підписки/записів) — перевірка живе тут,
    щоб усі переваги VIP+ автоматично діяли через active_vip_tier().
    """
    try:
        uid = int(user_id)
    except Exception:
        return False
    if uid == BOT_OWNER_ID:
        return True
    try:
        row = _db_fetchone(
            "SELECT 1 FROM founders WHERE founder_id = %s AND is_active = TRUE",
            (uid,),
        )
        return bool(row)
    except Exception:
        return False


def _kyiv_today() -> date:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Kyiv")).date()
    except Exception:
        return (datetime.utcnow() + timedelta(hours=2)).date()


def _db_value_to_date(val: object) -> Optional[date]:
    """DATE/TIMESTAMP з БД (або str) → календарна дата. datetime перевіряємо раніше за date (підклас)."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def game_vip_test_active(user_id: int) -> bool:
    """Активний тестовий ігровий VIP+ з /test_vip (поле users.game_vip_test_until)."""
    row = _db_fetchone("SELECT game_vip_test_until FROM users WHERE id = %s", (user_id,))
    if not row or row[0] is None:
        return False
    until = row[0]
    now = datetime.now()
    try:
        return now < until
    except TypeError:
        until_cmp = until.replace(tzinfo=None) if getattr(until, "tzinfo", None) else until
        return datetime.now() < until_cmp


def get_game_vip_test_until(user_id: int) -> Optional[datetime]:
    """Дата закінчення тестового VIP+, якщо він ще діє; інакше None."""
    if not game_vip_test_active(user_id):
        return None
    row = _db_fetchone("SELECT game_vip_test_until FROM users WHERE id = %s", (user_id,))
    if not row or not row[0]:
        return None
    return row[0]


def active_vip_tier(user_id: int) -> Optional[VipTier]:
    """Активна VIP-підписка (таблиця subscriptions) або тестовий VIP+ у грі (/test_vip)."""
    # Засновники бота мають вічний VIP+ незалежно від підписки.
    if is_bot_founder(user_id):
        return "vip_plus"
    try:
        from commands.buy import ShopManager
    except ImportError:
        return None
    if ShopManager.is_subscription_active(user_id):
        sub = ShopManager.get_user_subscription(user_id)
        if sub:
            t = (sub.get("subscription_type") or "").strip()
            if t == VIP_PLUS_ITEM_ID:
                return "vip_plus"
            if t == VIP_ITEM_ID:
                return "vip"
            if t == LEGACY_ADVENT_VIP_ITEM_ID:
                return "vip_plus"
    if game_vip_test_active(user_id):
        return "vip_plus"
    return None


def win_bonus_multiplier(tier: Optional[VipTier]) -> float:
    if tier == "vip_plus":
        return 1.30
    if tier == "vip":
        return 1.20
    return 1.0


def game_win_reward_multiplier(tier: Optional[VipTier]) -> float:
    """Множник лір за перемогу в партії мафії (/play). VIP +25%, VIP+ +50%."""
    if tier == "vip_plus":
        return 1.50
    if tier == "vip":
        return 1.25
    return 1.0


def daily_balance_bonus(tier: Optional[VipTier]) -> int:
    if tier == "vip_plus":
        return 250
    if tier == "vip":
        return 100
    return 0


# Персональні винятки для щоденного VIP-бонусу: user_id -> сума.
# Застосовуються лише для VIP+ (щоб не впливати на звичайний VIP).
DAILY_BONUS_OVERRIDE_VIP_PLUS: dict[int, int] = {}


def daily_balance_bonus_for_user(user_id: int, tier: Optional[VipTier]) -> int:
    amount = daily_balance_bonus(tier)
    if tier != "vip_plus":
        return amount
    return int(DAILY_BONUS_OVERRIDE_VIP_PLUS.get(int(user_id), amount))


def insurance_cap(tier: Optional[VipTier]) -> int:
    if tier == "vip_plus":
        return 2
    if tier == "vip":
        return 1
    return 0


def cooldown_factor(tier: Optional[VipTier]) -> float:
    """Множник тривалості КД (1 = без знижки)."""
    if tier == "vip_plus":
        return 0.75
    if tier == "vip":
        return 0.85
    return 1.0


def user_registered_at(user_id: int) -> Optional[datetime]:
    row = _db_fetchone(
        "SELECT registered_at FROM users WHERE id = %s",
        (user_id,),
    )
    if not row or row[0] is None:
        return None
    return row[0]


def newbie_vip_discount_eligible(user_id: int) -> bool:
    """Перші 24 год з моменту registered_at: -50% на VIP (не на VIP+)."""
    ra = user_registered_at(user_id)
    if not ra:
        return False
    if hasattr(ra, "tzinfo") and ra.tzinfo is not None:
        try:
            ra = ra.replace(tzinfo=None)
        except Exception:
            pass
    return datetime.now() - ra <= timedelta(hours=24)


def effective_star_price(item, user_id: int) -> int:
    """Ціна в зірках з каталогу; VIP −50% перші 24 год після реєстрації (VIP+ — фіксована ціна в ShopItem)."""
    base = int(getattr(item, "price", 0) or 0)
    iid = getattr(item, "item_id", "") or ""
    if iid == VIP_ITEM_ID and newbie_vip_discount_eligible(user_id):
        return max(1, base // 2)
    return base


def effective_gold_price(item, user_id: int) -> Optional[int]:
    pg = getattr(item, "price_gold", None)
    if pg is None:
        return None
    base = int(pg)
    iid = getattr(item, "item_id", "") or ""
    if iid == VIP_ITEM_ID and newbie_vip_discount_eligible(user_id):
        return max(1, base // 2)
    return base


def roulette_vip_refresh_and_get_insurance_state(user_id: int) -> tuple[int, date]:
    """Повертає (використано сьогодні, календарний день). Оновлює БД при зміні доби."""
    from database.database import roulette_get_profile

    p = roulette_get_profile(user_id)
    today = _kyiv_today()
    raw_day = p.get("vip_insurance_day")
    used = int(p.get("vip_insurance_used_today") or 0)

    changed = False
    if raw_day is None:
        used = 0
        changed = True
    else:
        d = _db_value_to_date(raw_day)
        if d is None or d != today:
            used = 0
            changed = True

    if changed:
        _db_execute_commit(
            """
            UPDATE roulette_profiles
            SET vip_insurance_used_today = %s, vip_insurance_day = %s
            WHERE user_id = %s
            """,
            (used, today, user_id),
        )
    return used, today


def roulette_insurance_can_use(user_id: int, tier: Optional[VipTier]) -> bool:
    cap = insurance_cap(tier)
    if cap <= 0:
        return False
    used, _ = roulette_vip_refresh_and_get_insurance_state(user_id)
    return used < cap


def roulette_insurance_consume_and_refund(user_id: int, tier: Optional[VipTier], net_loss: int) -> int:
    """
    Якщо є страховка й net_loss > 0 - повертає 50% (округлення вниз), лічильник +1.
    net_loss - скільки лір гравець втратив за спін (без урахування бонусів VIP до виграшу).
    """
    if net_loss <= 0 or not roulette_insurance_can_use(user_id, tier):
        return 0
    # Сувора половина втрати (ціле ділення вниз), без float.
    refund = max(0, int(net_loss) // 2)
    if refund <= 0:
        return 0

    used, today = roulette_vip_refresh_and_get_insurance_state(user_id)
    _db_execute_commit(
        """
        UPDATE roulette_profiles
        SET vip_insurance_used_today = %s, vip_insurance_day = %s
        WHERE user_id = %s
        """,
        (used + 1, today, user_id),
    )
    return refund


def roulette_vip_reroll_consume(user_id: int) -> bool:
    """
    VIP+ перекрут: 1 раз на календарну добу (Київ).
    Повертає True, якщо перекрут доступний і ліміт успішно списано.
    """
    if active_vip_tier(user_id) != "vip_plus":
        return False
    from database.database import roulette_get_profile

    p = roulette_get_profile(user_id)
    today = _kyiv_today()
    used_day = _db_value_to_date(p.get("vip_reroll_used_day"))
    if used_day is not None and used_day == today:
        return False
    try:
        _db_execute_commit(
            """
            UPDATE roulette_profiles
            SET vip_reroll_used_day = %s
            WHERE user_id = %s
            """,
            (today, user_id),
        )
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def vip_try_daily_currency_bonus_with_tier(user_id: int) -> tuple[int, Optional[VipTier]]:
    """
    Якщо сьогодні ще не видавали VIP-бонус - нарахувати ліри й повернути (сума, тариф).
    Інакше (0, None). Тариф - лише коли сума > 0.
    """
    tier = active_vip_tier(user_id)
    amount = daily_balance_bonus_for_user(user_id, tier)
    if amount <= 0:
        return 0, None

    from database.database import roulette_get_profile

    p = roulette_get_profile(user_id)
    today = _kyiv_today()
    gd = p.get("vip_daily_grant_day")
    granted_day = _db_value_to_date(gd)
    if granted_day is not None and granted_day == today:
        return 0, None

    _db_execute_commit(
        """
        UPDATE roulette_profiles
        SET vip_daily_grant_day = %s
        WHERE user_id = %s
        """,
        (today, user_id),
    )
    from database.database import add_balance_to_user

    add_balance_to_user(user_id, amount)
    return amount, tier


def vip_daily_bonus_notification_html(amount: int, tier: VipTier) -> str:
    """Окреме повідомлення про щоденний бонус (HTML; обгорни через emoji_to_premium при відправці)."""
    if tier == "vip_plus":
        header = "👑VIP+"
    else:
        header = "💎VIP"
    return (
        f"{header}\n"
        f"Вам начислено +{amount}💵\n"
        f"Сім'я Аль Капоне дбає про своїх."
    )


def vip_try_daily_currency_bonus(user_id: int) -> int:
    """Одноразово на календарний день (Київ): +1000 / +2000 лір."""
    amt, _ = vip_try_daily_currency_bonus_with_tier(user_id)
    return amt


def vip_reset_daily_grant_flag(user_id: int) -> bool:
    """
    Скинути позначку «щоденний VIP-бонус уже видано сьогодні» (roulette_profiles.vip_daily_grant_day).
    Для тесту: після цього знову спрацює нарахування при /profile, /start, рулетці тощо.
    """
    from database.database import roulette_get_profile

    try:
        roulette_get_profile(user_id)
        _db_execute_commit(
            "UPDATE roulette_profiles SET vip_daily_grant_day = NULL WHERE user_id = %s",
            (user_id,),
        )
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def list_active_vip_game_user_ids() -> list[int]:
    """User id з активною ігровою підпискою VIP / VIP+ або тестовим /test_vip."""
    from commands.buy import ShopManager

    seen: set[int] = set()
    out: list[int] = []
    # Засновники — вічний VIP+, тож завжди в списку щоденного бонусу.
    founder_ids: list[int] = [BOT_OWNER_ID]
    try:
        for (fid,) in _db_fetchall("SELECT founder_id FROM founders WHERE is_active = TRUE") or []:
            founder_ids.append(int(fid))
    except Exception:
        pass
    for uid in founder_ids:
        if uid not in seen:
            seen.add(uid)
            out.append(uid)
    rows = _db_fetchall(
        """
        SELECT DISTINCT user_id FROM subscriptions
        WHERE is_active = TRUE
          AND subscription_type IN (%s, %s, %s)
        """,
        (VIP_ITEM_ID, VIP_PLUS_ITEM_ID, LEGACY_ADVENT_VIP_ITEM_ID),
    )
    for (uid,) in rows or []:
        uid = int(uid)
        if ShopManager.is_subscription_active(uid):
            seen.add(uid)
            out.append(uid)
    test_rows = _db_fetchall(
        "SELECT id FROM users WHERE game_vip_test_until IS NOT NULL",
    )
    for (uid,) in test_rows or []:
        uid = int(uid)
        if uid not in seen and game_vip_test_active(uid):
            seen.add(uid)
            out.append(uid)
    return out


def vip_force_daily_currency_payout(user_id: int) -> int:
    """
    Нарахувати щоденну суму VIP навіть якщо сьогодні вже було (компенсація).
    Оновлює vip_daily_grant_day на сьогодні, щоб автоматична видача не дублювала в той самий день після /start.
    """
    tier = active_vip_tier(user_id)
    amount = daily_balance_bonus_for_user(user_id, tier)
    if amount <= 0:
        return 0

    from database.database import add_balance_to_user, roulette_get_profile

    roulette_get_profile(user_id)
    today = _kyiv_today()
    _db_execute_commit(
        """
        UPDATE roulette_profiles
        SET vip_daily_grant_day = %s
        WHERE user_id = %s
        """,
        (today, user_id),
    )
    add_balance_to_user(user_id, amount)
    return amount


def vip_admin_payout_daily_all(*, force: bool = False) -> tuple[int, int, int, list[tuple[int, int, VipTier]]]:
    """
    Масова видача щоденних лір усім активним VIP/VIP+.
    Повертає (кількість нараховань >0, сума лір, усього VIP у вибірці, [(user_id, amount, tier), ...]).
    """
    ids = list_active_vip_game_user_ids()
    n_paid = 0
    total = 0
    recipients: list[tuple[int, int, VipTier]] = []
    for uid in ids:
        if force:
            a = vip_force_daily_currency_payout(uid)
            pay_tier = active_vip_tier(uid)
        else:
            a, pay_tier = vip_try_daily_currency_bonus_with_tier(uid)
        if a <= 0:
            continue
        if pay_tier not in ("vip", "vip_plus"):
            pay_tier = active_vip_tier(uid)
        if pay_tier not in ("vip", "vip_plus"):
            continue
        n_paid += 1
        total += a
        recipients.append((uid, a, pay_tier))
    return n_paid, total, len(ids), recipients


# --- Відображення значка (HTML tg://user, профіль, топ) ---
VIP_PLUS_BADGE_EMOJI: dict[str, str] = {
    "diamond": "💎",
    "crown": "⛏️",
    "fire": "🔥",
    "cat": "🐈‍⬛",
}

# Персональні (унікальні) значки VIP+ для конкретних user_id.
VIP_PLUS_BADGE_EMOJI_BY_USER: dict[int, dict[str, str]] = {
    7028677784: {"skull": "☠️"},
    1859870653: {"ring": "💍"},
}


def get_vip_plus_badge_emoji_map(user_id: int) -> dict[str, str]:
    """Доступні значки VIP+ для конкретного користувача (базові + персональні)."""
    custom = VIP_PLUS_BADGE_EMOJI_BY_USER.get(int(user_id), {})
    if not custom:
        return dict(VIP_PLUS_BADGE_EMOJI)
    merged = dict(VIP_PLUS_BADGE_EMOJI)
    merged.update(custom)
    return merged


def get_vip_plus_badge_choice_key(user_id: int) -> str:
    """Ключ значка VIP+ у БД; нормалізація та fallback (для спец-акаунтів теж)."""
    allowed = get_vip_plus_badge_emoji_map(user_id)
    row = _db_fetchone(
        "SELECT COALESCE(NULLIF(TRIM(vip_badge_choice), ''), 'crown') FROM users WHERE id = %s",
        (user_id,),
    )
    key = (row[0] or "crown").lower().strip() if row else "crown"
    if key in allowed:
        return key
    # Для спеціальних акаунтів робимо дефолт на їхній персональний значок.
    custom = VIP_PLUS_BADGE_EMOJI_BY_USER.get(int(user_id), {})
    if custom:
        first_custom_key = next(iter(custom.keys()), None)
        if first_custom_key and first_custom_key in allowed:
            return first_custom_key
    return "crown"


def get_vip_plus_badge_emoji(user_id: int) -> str:
    """Емодзі значка для VIP+ (кастомізація). За замовчуванням - корона."""
    em_map = get_vip_plus_badge_emoji_map(user_id)
    return em_map[get_vip_plus_badge_choice_key(user_id)]


def set_vip_plus_badge_choice(user_id: int, key: str) -> bool:
    """Зберегти ключ значка для VIP+. Повертає False, якщо ключ невідомий."""
    k = (key or "").strip().lower()
    if k not in get_vip_plus_badge_emoji_map(user_id):
        return False
    _db_execute_commit(
        "UPDATE users SET vip_badge_choice = %s WHERE id = %s",
        (k, user_id),
    )
    return True


def clear_vip_farewell_flag(user_id: int) -> None:
    """Після нової активації VIP - знову можна показати прощання наступного разу."""
    try:
        _db_execute_commit(
            "UPDATE users SET vip_farewell_last_end = NULL WHERE id = %s",
            (user_id,),
        )
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def consume_expired_vip_farewell_message(user_id: int) -> Optional[str]:
    """
    Якщо VIP щойно закінчився (підписка неактивна) і ще не показували це завершення -
    повертає текст і позначає в БД (один раз на конкретне subscription_end).
    """
    if active_vip_tier(user_id):
        return None
    row = _db_fetchone(
        "SELECT subscription_type, subscription_end, is_active, updated_at FROM subscriptions WHERE user_id = %s",
        (user_id,),
    )
    if not row:
        return None
    st, end, is_active, sub_updated = row[0], row[1], row[2], row[3]
    if not st or not str(st).strip().lower().startswith("vip"):
        return None

    now = datetime.now()
    end_naive = None
    if end is not None:
        try:
            end_naive = end.replace(tzinfo=None) if getattr(end, "tzinfo", None) else end
        except Exception:
            return None

    # Ще діє за датою кінця і запис не відкликаний - VIP фактично активний (active_vip_tier уже перевірив).
    if is_active and end_naive is not None and end_naive >= now:
        return None
    if is_active and end_naive is None:
        return None

    # Немає дати кінця й підписка активна в БД - не показуємо «закінчився».
    if end_naive is None and is_active:
        return None

    farewell_key = end if end is not None else sub_updated
    if farewell_key is None:
        return None

    urow = _db_fetchone("SELECT vip_farewell_last_end FROM users WHERE id = %s", (user_id,))
    last = urow[0] if urow else None
    if last is not None and last == farewell_key:
        return None

    _db_execute_commit(
        "UPDATE users SET vip_farewell_last_end = %s WHERE id = %s",
        (farewell_key, user_id),
    )
    return (
        "💀 <b>Ти більше не виглядаєш так впевнено.</b>\n\n"
        "VIP закінчився - значок зник.\n"
        "<i>Оформити знову: /shop</i>"
    )


def html_user_link(user_id: int, display_name: str | None) -> str:
    """HTML-посилання на користувача; VIP-значок перед посиланням (не всередині <a>).

    Значок - звичайний символ Unicode; преміум-обгортку <tg-emoji> робить один виклик
    emoji_to_premium(...) на весь текст повідомлення (інакше ⚒️ всередині вже готового
    тега перезапишеться вдруге і зламає HTML).
    """
    name = html_module.escape((display_name or "Гравець").strip() or "Гравець")
    tier = active_vip_tier(user_id)
    # Жирним лише VIP / VIP+; без підписки - звичайне посилання (як у списку гравців).
    inner = f"<b>{name}</b>" if tier in ("vip", "vip_plus") else name
    link = f'<a href="tg://user?id={user_id}">{inner}</a>'
    if tier == "vip":
        return f"⚒️ {link}"
    if tier == "vip_plus":
        em = get_vip_plus_badge_emoji(user_id)
        return f"{em} {link}"
    return link


def profile_status_line_html(user_id: int) -> str:
    """Рядок статусу для /profile (без посилання). Символи VIP - plain; обгортка через emoji_to_premium на рівні повідомлення."""
    tier = active_vip_tier(user_id)
    if tier == "vip":
        return "⚒️ <b>VIP</b> - активний статус"
    if tier == "vip_plus":
        em = get_vip_plus_badge_emoji(user_id)
        return f"{em} <b>VIP+</b> - преміум статус"
    return ""


def maybe_vip_context_flair_html(
    user_id: int, nickname_plain: str, *, rare_chance: float = 0.06
) -> str:
    """Рідкісний динамічний рядок для чату (HTML). nickname_plain - без тегів."""
    tier = active_vip_tier(user_id)
    if not tier or random.random() > rare_chance:
        return ""
    nick = html_module.escape((nickname_plain or "Гравець").strip() or "Гравець")
    if tier == "vip_plus":
        pool = [
            f"🔥 {nick} сьогодні явно в ударі.",
            f"💬 О, VIP+ на звʼязку: {nick}",
            f"✨ {nick} зірвав увагу столу.",
        ]
        if random.random() < 0.003:
            pool.append(f"⛏️ {nick} сьогодні ніби під захистом удачі.")
    else:
        pool = [
            f"⚒️ {nick} грає з VIP.",
            f"💬 VIP за столом: {nick}",
        ]
    return random.choice(pool)


async def maybe_vip_join_group_ping(bot, chat_id: int, user_id: int, nickname_plain: str) -> None:
    """Після входу в реєстрацію гри - дуже рідке групове повідомлення про VIP."""
    if chat_id >= 0:
        return
    tier = active_vip_tier(user_id)
    if not tier or random.random() > 0.04:
        return
    nick = html_module.escape((nickname_plain or "Гравець").strip() or "Гравець")
    try:
        if tier == "vip_plus":
            text = f"⛏️ {nick} підключився з VIP+"
        else:
            text = f"⚒️ {nick} у грі з VIP"
        await bot.send_message(chat_id, emoji_to_premium(text, skip_vip_badges=True), parse_mode="html")
    except Exception:
        pass


async def maybe_social_vip_ping(bot, chat_id: int, user, tier: Optional[VipTier]):
    """Рідкісний соціальний тригер у групах."""
    if not tier or chat_id >= 0:  # only groups negative ids
        return
    if random.random() > 0.004:
        return
    try:
        nick = (getattr(user, "full_name", None) or getattr(user, "first_name", None) or "Гравець").strip()
        if tier == "vip_plus":
            text = f"💰 {nick} явно не переживає за гроші"
        else:
            text = f"⚒️ {nick} грає з VIP"
        await bot.send_message(
            chat_id, emoji_to_premium(text, skip_vip_badges=True), parse_mode="html"
        )
    except Exception:
        pass


def vip_buff_discount_factor(tier: Optional[VipTier]) -> float:
    """VIP+ магазин: -25% до цін бафів."""
    if tier == "vip_plus":
        return 0.75
    return 1.0
