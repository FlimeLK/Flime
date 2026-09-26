import html as html_module

from aiogram import Router, F, Bot
from aiogram.types import Message, PreCheckoutQuery, LabeledPrice, ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.filters import Command, BaseFilter
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import datetime, timedelta
from database.database import cursor, conn, run_db_call_async
from premium_emoji import emoji_to_premium, custom_emoji_id_for_symbol
from typing import Optional

router_pay = Router()
COIN_STAR_RATE = 5  # 5⭐ = 1🪙
BANK_UAH_RATE = 2  # 2 грн = 1🪙
COIN_PACKS: dict[str, int] = {
    "coins_10": 10,
    "coins_25": 25,
    "coins_50": 50,
}


def _subscription_tier_buttons(kb: InlineKeyboardBuilder, vip_item_id: str, vip_plus_item_id: str) -> None:
    """VIP - преміум-діамант ⚒️; VIP+ - преміум-корона ⛏️ (icon_custom_emoji_id)."""
    vip_cid = custom_emoji_id_for_symbol("⚒️")
    plus_cid = custom_emoji_id_for_symbol("⛏️")
    if vip_cid:
        kb.button(
            text="Придбати VIP",
            callback_data=f"subscription:pay_select:{vip_item_id}",
            icon_custom_emoji_id=vip_cid,
        )
    else:
        kb.button(text="Придбати ⚒️VIP", callback_data=f"subscription:pay_select:{vip_item_id}")
    if plus_cid:
        kb.button(
            text="Придбати VIP+",
            callback_data=f"subscription:pay_select:{vip_plus_item_id}",
            icon_custom_emoji_id=plus_cid,
        )
    else:
        kb.button(text="Придбати ⛏️VIP+", callback_data=f"subscription:pay_select:{vip_plus_item_id}")


# Користувачі, які очікують введення ID транзакції після /stop_subscription (тільки їх повідомлення обробляються як ID)
refund_awaiting_user_ids: set[int] = set()
vip_gift_awaiting: dict[int, str] = {}


def _gift_payload(item_id: str, recipient_id: int) -> str:
    return f"gift:{item_id}:{int(recipient_id)}"


def _parse_gift_payload(payload: str) -> tuple[str, int] | None:
    if not payload.startswith("gift:"):
        return None
    parts = payload.split(":")
    if len(parts) != 3:
        return None
    item_id = (parts[1] or "").strip()
    try:
        recipient_id = int(parts[2])
    except Exception:
        return None
    if not item_id or recipient_id <= 0:
        return None
    return item_id, recipient_id


async def _resolve_gift_recipient_user_id(raw_text: str, bot: Bot) -> Optional[int]:
    """
    ID отримувача подарунку: числовий Telegram ID, @username з БД (users.link),
    або публічний @username через Bot API (якщо людина ще не писала боту).
    """
    raw = (raw_text or "").strip()
    if not raw:
        return None

    username: Optional[str] = None
    if raw.startswith("@"):
        username = raw[1:].strip().lower()
        if not username:
            return None
    else:
        try:
            uid = int(raw)
            return uid if uid > 0 else None
        except ValueError:
            username = raw.strip().lower()
            if not username:
                return None

    row = _db_fetchone_sync(
        "SELECT id FROM users WHERE LOWER(TRIM(COALESCE(link, ''))) = %s LIMIT 1",
        (username,),
    )
    if row:
        return int(row[0])

    try:
        chat = await bot.get_chat(f"@{username}")
    except Exception:
        return None
    if chat.type != ChatType.PRIVATE:
        return None
    try:
        return int(chat.id)
    except Exception:
        return None


def _db_fetchone_sync(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_fetchall_sync(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchall()


def _db_execute_sync(query: str, params: tuple = ()) -> int:
    cursor.execute(query, params)
    return cursor.rowcount if cursor.rowcount is not None else 0


def _db_execute_commit_sync(query: str, params: tuple = ()) -> int:
    affected = _db_execute_sync(query, params)
    conn.commit()
    return affected


async def _db_fetchone_async(query: str, params: tuple = ()):
    return await run_db_call_async(lambda: _db_fetchone_sync(query, params))


async def _db_fetchall_async(query: str, params: tuple = ()):
    return await run_db_call_async(lambda: _db_fetchall_sync(query, params))


class RefundAwaitingFilter(BaseFilter):
    """Пропускає тільки повідомлення від користувачів, які очікують ID транзакції, і лише якщо текст не команда (не починається з /). Інакше /story, /shop тощо обробляються своїми обробниками."""
    async def __call__(self, message: Message) -> bool:
        if not getattr(message, "from_user", None) or message.from_user.id not in refund_awaiting_user_ids:
            return False
        text = (message.text or "").strip()
        return bool(text) and not text.startswith("/")


class VipGiftAwaitingFilter(BaseFilter):
    """Ловить тільки текст, коли чекаємо одержувача подарунку VIP/VIP+."""

    async def __call__(self, message: Message) -> bool:
        if not getattr(message, "from_user", None):
            return False
        if message.from_user.id not in vip_gift_awaiting:
            return False
        text = (message.text or "").strip()
        return bool(text) and not text.startswith("/")

# @router_pay.message(Command("buy"))
# async def order(message: Message):
#     await message.answer_invoice(
#         title="Тут назва для товару",
#         description="Тут його опис",
#         payload="buy_premium",
#         provider_token="1661751239:TEST:5f6F-WLUs-br4k-RL7m",
#         currency="UAH",
#         prices=[LabeledPrice(
#                 label="Назва товару",
#                 amount=15000
#             )],
#         start_parameter="buy",
#         provider_data=None,
#         need_name=True,
#         need_email=True,
#         need_phone_number=True,
#         need_shipping_address=False,
#         send_phone_number_to_provider=False,
#         send_email_to_provider=False,
#         is_flexible=False,
#         disable_notification=False,
#         protect_content=True,
#         reply_to_message_id=None,
#         allow_sending_without_reply=True,
#         reply_markup=None,
#         request_timeout=15,
#     )

# @router_pay.pre_checkout_query()
# async def pre_checkout_query(pre_checkout_query: PreCheckoutQuery, bot: Bot):
#     await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

# @router_pay.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
# async def successful_payment(message: Message):
#     await message.answer(text="Оплата пройшла успішно! <blockquote>Ви купили преміум підписку для доступу бота для </blockquote>", parse_mode="html")
#     message_date = message.date

#     one_month_later = message_date + timedelta(days=30)


class ShopItem:
    """Represents a shop item/subscription"""
    def __init__(self, item_id: str, name: str, description: str, price: int, duration_days: int = 0, price_gold: Optional[int] = None):
        self.item_id = item_id
        self.name = name
        self.description = description
        self.price = price  # In Telegram Stars (XTR)
        self.duration_days = duration_days  # 0 = one-time purchase, >0 = subscription duration
        self.price_gold = price_gold  # Золоті монети (донат); None = тільки Stars


def _checkout_perks_block_html(item: ShopItem) -> tuple[str, str]:
    """
    Заголовок блоку + тіло (HTML).
    Довгі описи з «·» перетворює на список - щоб не злипалось в один рядок.
    """
    desc = (item.description or "").strip()
    if not desc:
        return ("", "")

    if "·" in desc:
        parts = [c.strip() for c in desc.split("·") if c.strip()]
        if len(parts) >= 2:
            if item.item_id == "vip_plus_30":
                title = "⛏️ <b>VIP+ - переваги</b>"
            elif item.item_id == "vip_30":
                title = "⚒️ <b>VIP - переваги</b>"
            else:
                title = "📋 <b>Що входить</b>"
            body = "\n".join(f"  • {html_module.escape(p)}" for p in parts)
            return (title, body)

    return ("📝 <b>Опис</b>", html_module.escape(desc))


def _catalog_description_html(item: ShopItem) -> str:
    """Опис товару для каталогу /shop - списком, якщо в описі є «·»."""
    desc = (item.description or "").strip()
    if not desc:
        return ""
    if "·" in desc:
        parts = [c.strip() for c in desc.split("·") if c.strip()]
        if len(parts) >= 2:
            return "\n".join(f"  • {html_module.escape(p)}" for p in parts)
    return html_module.escape(desc)


def _checkout_message_html(item: ShopItem, star_price: int, newbie_note_html: str) -> str:
    """Текст екрану перед інвойсом: чіткі блоки та порожні рядки між ними."""
    perks_title, perks_body = _checkout_perks_block_html(item)
    chunks: list[str] = [
        "🛒 <b>Оформлення покупки</b> 🛒",
        "",
        "📦 <b>Товар</b>",
        item.name,
        "",
    ]
    if perks_title and perks_body:
        chunks.extend([perks_title, "", perks_body, ""])
    chunks.append(f"💰 <b>Ціна:</b> <code>{star_price} ⭐</code> <i>(Telegram Stars)</i>")
    if newbie_note_html:
        chunks.extend(["", newbie_note_html.strip()])
    chunks.extend(
        [
            "",
            f"⏱️ <b>Тривалість:</b> <code>{item.duration_days} днів</code>",
            "",
            "⬇️ <b>Оплата</b>",
            "<i>Натисни кнопку оплати нижче.</i>",
        ]
    )
    return "\n".join(chunks)


def _replace_buy_button_with_pay_url(
    markup: InlineKeyboardMarkup | None,
    *,
    target_callback_data: str,
    pay_label: str,
    pay_url: str,
) -> InlineKeyboardMarkup:
    """Міняє тільки кнопку покупки на URL-оплату, інші кнопки лишає без змін."""
    rows = getattr(markup, "inline_keyboard", None) or []
    if not rows:
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=pay_label, url=pay_url)]]
        )

    new_rows: list[list[InlineKeyboardButton]] = []
    replaced = False
    for row in rows:
        new_row: list[InlineKeyboardButton] = []
        for btn in row:
            cb = getattr(btn, "callback_data", None)
            if isinstance(cb, str) and cb == target_callback_data:
                new_row.append(InlineKeyboardButton(text=pay_label, url=pay_url))
                replaced = True
            else:
                new_row.append(btn)
        new_rows.append(new_row)

    if not replaced:
        new_rows.append([InlineKeyboardButton(text=pay_label, url=pay_url)])
    return InlineKeyboardMarkup(inline_keyboard=new_rows)


class ShopManager:
    """Manages shop items and purchases"""
    
    # Available shop items
    SHOP_ITEMS = {
        "vip_30": ShopItem(
            item_id="vip_30",
            name="⚒️ VIP (30 днів)",
            description=(
                "+20% до виграшів у рулетці · щодня +1000💵 · 1 страховка/день (50% повернення програшу) · "
                "мʼякше КД (-15%) · значок ⚒️ у перевагах. "
            ),
            price=120,
            duration_days=30,
            price_gold=60,
        ),
        "vip_plus_30": ShopItem(
            item_id="vip_plus_30",
            name="⛏️ VIP+ (30 днів)",
            description=(
                "+30% до виграшів · щодня +2000💵 · 2 страховки/день · «перекрут» у рулетці після програшу · "
                "доступ до VIP Ринку (-25% на бафи) · КД -25%. "
            ),
            price=120,
            duration_days=30,
            price_gold=50,
        ),
        "subscription_1month": ShopItem(
            item_id="subscription_1month",
            name="Свій хлоп",
            description="Місяць без зайвого клопоту.",
            price=300,  # 300 stars
            duration_days=30,
            price_gold=100,
        ),
        "subscription_3months": ShopItem(
            item_id="subscription_3months",
            name="Поважний ґазда",
            description="До твого слова починають дослухатись.",
            price=500,  # 500 stars (10% discount)
            duration_days=90,
            price_gold=250,
        ),
        "subscription_6months": ShopItem(
            item_id="subscription_6months",
            name="Права рука",
            description="Тебе знають по імені навіть ті, хто не знайомий.",
            price=700,  # 700 stars (20% discount)
            duration_days=180,
            price_gold=350,
        ),
        "subscription_12months": ShopItem(
            item_id="subscription_12months",
            name="Під словом Ела",
            description="Рік під дахом. І без зайвих запитань.",
            price=1000,  # 1000 stars (30% discount)
            duration_days=365,
            price_gold=500,
        ),
    }
    
    @staticmethod
    def get_item(item_id: str) -> Optional[ShopItem]:
        """Get shop item by ID"""
        return ShopManager.SHOP_ITEMS.get(item_id)
    
    @staticmethod
    def get_user_subscription(user_id: int) -> Optional[dict]:
        """Get user's active subscription"""
        result = _db_fetchone_sync("""
            SELECT subscription_type, subscription_start, subscription_end, is_active, auto_renew, COALESCE(is_purchased, TRUE)
            FROM subscriptions
            WHERE user_id = %s AND is_active = TRUE
        """, (user_id,))
        if result:
            return {
                "subscription_type": result[0],
                "subscription_start": result[1],
                "subscription_end": result[2],
                "is_active": result[3],
                "auto_renew": result[4],
                "is_purchased": result[5],
            }
        return None

    @staticmethod
    async def get_user_subscription_async(user_id: int) -> Optional[dict]:
        result = await _db_fetchone_async(
            """
            SELECT subscription_type, subscription_start, subscription_end, is_active, auto_renew, COALESCE(is_purchased, TRUE)
            FROM subscriptions
            WHERE user_id = %s AND is_active = TRUE
            """,
            (user_id,),
        )
        if result:
            return {
                "subscription_type": result[0],
                "subscription_start": result[1],
                "subscription_end": result[2],
                "is_active": result[3],
                "auto_renew": result[4],
                "is_purchased": result[5],
            }
        return None

    @staticmethod
    def has_purchased_subscription(user_id: int) -> bool:
        """Чи має користувач активну підписку, яку саме купив (не подарунок адміна/промо)."""
        sub = ShopManager.get_user_subscription(user_id)
        if not sub or not ShopManager.is_subscription_active(user_id):
            return False
        return bool(sub.get("is_purchased", True))
    
    @staticmethod
    def _deactivate_subscription_row(user_id: int) -> None:
        """Зняти is_active у рядка підписки (після прострочення або некоректних даних)."""
        try:
            affected = _db_execute_sync(
                """
                UPDATE subscriptions
                SET is_active = FALSE, updated_at = %s
                WHERE user_id = %s AND is_active = TRUE
                """,
                (datetime.now(), user_id),
            )
            if affected:
                conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    @staticmethod
    def is_subscription_active(user_id: int) -> bool:
        """Check if user has active subscription"""
        subscription = ShopManager.get_user_subscription(user_id)
        if not subscription:
            return False

        end = subscription.get("subscription_end")
        st = (subscription.get("subscription_type") or "").strip()

        # Термін минув - у БД часто лишається is_active=TRUE; виправляємо, інакше «фантомний» VIP.
        if end is not None:
            try:
                expired = datetime.now() >= end
            except TypeError:
                end_cmp = end.replace(tzinfo=None) if getattr(end, "tzinfo", None) else end
                expired = datetime.now() >= end_cmp
            if expired:
                ShopManager._deactivate_subscription_row(user_id)
                return False
            return True

        # vip_30 / vip_plus_30 завжди мають дату закінчення; без дати - некоректний рядок (фантом).
        if st in ("vip_30", "vip_plus_30"):
            ShopManager._deactivate_subscription_row(user_id)
            return False

        return bool(subscription["is_active"])

    @staticmethod
    async def is_subscription_active_async(user_id: int) -> bool:
        subscription = await ShopManager.get_user_subscription_async(user_id)
        if not subscription:
            return False

        end = subscription.get("subscription_end")
        st = (subscription.get("subscription_type") or "").strip()

        if end is not None:
            try:
                expired = datetime.now() >= end
            except TypeError:
                end_cmp = end.replace(tzinfo=None) if getattr(end, "tzinfo", None) else end
                expired = datetime.now() >= end_cmp
            if expired:
                await run_db_call_async(lambda: ShopManager._deactivate_subscription_row(user_id))
                return False
            return True

        if st in ("vip_30", "vip_plus_30"):
            await run_db_call_async(lambda: ShopManager._deactivate_subscription_row(user_id))
            return False

        return bool(subscription["is_active"])

    @staticmethod
    def try_grant_test_vip(user_id: int) -> tuple[bool, str]:
        """
        Один раз на акаунт: ⛏️ VIP+ на 2 дні (не покупка).
        Повертає (True, html_текст_успіху) або (False, html_текст_відмови).
        """
        from commands import vip as vip_mod

        # Ігровий VIP/VIP+ з таблиці subscriptions (не плутати з підпискою «для чату»)
        if ShopManager.is_subscription_active(user_id):
            sub = ShopManager.get_user_subscription(user_id)
            if sub:
                st = (sub.get("subscription_type") or "").strip()
                if st in (vip_mod.VIP_ITEM_ID, vip_mod.VIP_PLUS_ITEM_ID):
                    return (
                        False,
                        "У тебе вже є активна підписка <b>VIP</b> або <b>VIP+</b>. "
                        "Тестовий <b>VIP+</b> можна взяти лише коли ігрової підписки немає.",
                    )
        if vip_mod.game_vip_test_active(user_id):
            return (
                False,
                "Тестовий <b>VIP+</b> у тебе вже активний - дочекайся його закінчення.",
            )

        try:
            _db_execute_sync(
                "INSERT INTO users (id, balance) VALUES (%s, 0) ON CONFLICT (id) DO NOTHING",
                (user_id,),
            )
            row = _db_fetchone_sync(
                "SELECT COALESCE(test_vip_used, FALSE) FROM users WHERE id = %s",
                (user_id,),
            )
            if row is None:
                try:
                    conn.rollback()
                except Exception:
                    pass
                return (False, "Не вдалося знайти профіль. Натисни /start і спробуй ще раз.")
            if bool(row[0]):
                try:
                    conn.rollback()
                except Exception:
                    pass
                return (
                    False,
                    "Ти вже використав(ла) безкоштовний тест <b>VIP+</b>. Він доступний лише <b>один раз</b>.",
                )

            item = ShopManager.get_item(vip_mod.VIP_PLUS_ITEM_ID)
            if not item:
                try:
                    conn.rollback()
                except Exception:
                    pass
                return (False, "Тимчасова помилка: тариф VIP+ не знайдено. Спробуй пізніше.")

            now = datetime.now()
            end_date = now + timedelta(days=2)

            charge_id = f"test_vip_{user_id}_{int(now.timestamp() * 1000)}"
            gift_label = f"{item.name} (тест /test_vip, 2 дні)"
            _db_execute_sync(
                """
                INSERT INTO shop_purchases (user_id, item_name, item_type, amount_paid, currency, telegram_payment_charge_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (user_id, gift_label, item.item_id, 0, "TEST_VIP_PLUS", charge_id),
            )

            _db_execute_sync(
                """
                UPDATE users
                SET test_vip_used = TRUE, game_vip_test_until = %s
                WHERE id = %s
                """,
                (end_date, user_id),
            )
            conn.commit()
            vip_mod.clear_vip_farewell_flag(user_id)
            end_txt = end_date.strftime("%d.%m.%Y %H:%M")
            return (
                True,
                "Тобі видано <b>тестовий VIP+ у грі</b> на <b>2 дні</b>!\n\n"
                "⛏️ Як у повного VIP+: рулетка +30%, щодня +2000💵, 2 страховки/день, перекрут після програшу, "
                "VIP Ринок (−25% на бафи), мʼякше КД.\n"
                f"📅 Діє до: <b>{end_txt}</b>\n\n",
            )
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return (False, f"Помилка: {html_module.escape(str(e))}")

    @staticmethod
    async def try_grant_test_vip_async(user_id: int) -> tuple[bool, str]:
        return await run_db_call_async(lambda: ShopManager.try_grant_test_vip(user_id))
    
    @staticmethod
    def activate_subscription(
        user_id: int,
        item: ShopItem,
        telegram_payment_charge_id: str,
        stars_paid: Optional[int] = None,
    ):
        """Activate subscription for user. stars_paid - фактично сплачено ⭐ (з урахуванням знижок)."""
        now = datetime.now()
        end_date = now + timedelta(days=item.duration_days) if item.duration_days > 0 else None
        paid = int(stars_paid) if stars_paid is not None else int(item.price)
        _db_execute_sync(
            "INSERT INTO users (id, balance, donate_coins) VALUES (%s, 0, 0) ON CONFLICT (id) DO NOTHING",
            (user_id,),
        )
        
        # Якщо підписка вже активна - продовжуємо від поточного subscription_end (а не з now).
        existing = _db_fetchone_sync(
            "SELECT user_id, subscription_start, subscription_end, is_active FROM subscriptions WHERE user_id = %s",
            (user_id,),
        )
        if existing:
            _uid, prev_start, prev_end, prev_active = existing[0], existing[1], existing[2], existing[3]
            if item.duration_days > 0 and prev_active and prev_end is not None:
                try:
                    if prev_end > now:
                        end_date = prev_end + timedelta(days=item.duration_days)
                except TypeError:
                    prev_end_cmp = prev_end.replace(tzinfo=None) if getattr(prev_end, "tzinfo", None) else prev_end
                    if prev_end_cmp > now:
                        end_date = prev_end_cmp + timedelta(days=item.duration_days)
            elif item.duration_days > 0 and prev_active and prev_end is None:
                # Безстрокова активна підписка не обрізається новою покупкою.
                end_date = None
        
        if existing:
            _db_execute_sync("""
                UPDATE subscriptions 
                SET subscription_type = %s, subscription_start = %s, subscription_end = %s,
                    is_active = TRUE, is_purchased = TRUE, updated_at = %s
                WHERE user_id = %s
            """, (item.item_id, now, end_date, now, user_id))
        else:
            _db_execute_sync("""
                INSERT INTO subscriptions (user_id, subscription_type, subscription_start, subscription_end, is_active, is_purchased)
                VALUES (%s, %s, %s, %s, TRUE, TRUE)
            """, (user_id, item.item_id, now, end_date))

        # Save purchase history
        _db_execute_sync("""
            INSERT INTO shop_purchases (user_id, item_name, item_type, amount_paid, currency, telegram_payment_charge_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, item.name, item.item_id, paid, "XTR", telegram_payment_charge_id))
        
        conn.commit()
        if (item.item_id or "").startswith("vip"):
            from commands import vip as vip_mod

            vip_mod.clear_vip_farewell_flag(user_id)

    @staticmethod
    async def activate_subscription_async(
        user_id: int,
        item: ShopItem,
        telegram_payment_charge_id: str,
        stars_paid: Optional[int] = None,
    ):
        await run_db_call_async(
            lambda: ShopManager.activate_subscription(user_id, item, telegram_payment_charge_id, stars_paid=stars_paid)
        )

    @staticmethod
    def activate_subscription_with_gold(user_id: int, item: ShopItem) -> bool:
        """Активує підписку за золоті монети. Повертає True при успіху."""
        from commands import vip as vip_mod

        cost = vip_mod.effective_gold_price(item, user_id) or (item.price_gold or 0)
        if cost <= 0:
            return False
        row = _db_fetchone_sync("SELECT COALESCE(donate_coins, 0) FROM users WHERE id = %s FOR UPDATE", (user_id,))
        if not row or row[0] < cost:
            return False
        now = datetime.now()
        end_date = now + timedelta(days=item.duration_days) if item.duration_days > 0 else None
        existing = _db_fetchone_sync(
            "SELECT user_id, subscription_start, subscription_end, is_active FROM subscriptions WHERE user_id = %s",
            (user_id,),
        )
        if existing:
            _uid, prev_start, prev_end, prev_active = existing[0], existing[1], existing[2], existing[3]
            if item.duration_days > 0 and prev_active and prev_end is not None:
                try:
                    if prev_end > now:
                        end_date = prev_end + timedelta(days=item.duration_days)
                except TypeError:
                    prev_end_cmp = prev_end.replace(tzinfo=None) if getattr(prev_end, "tzinfo", None) else prev_end
                    if prev_end_cmp > now:
                        end_date = prev_end_cmp + timedelta(days=item.duration_days)
            elif item.duration_days > 0 and prev_active and prev_end is None:
                end_date = None
        if existing:
            _db_execute_sync("""
                UPDATE subscriptions
                SET subscription_type = %s, subscription_start = %s, subscription_end = %s, is_active = TRUE, is_purchased = TRUE, updated_at = %s
                WHERE user_id = %s
            """, (item.item_id, now, end_date, now, user_id))
        else:
            _db_execute_sync("""
                INSERT INTO subscriptions (user_id, subscription_type, subscription_start, subscription_end, is_active, is_purchased)
                VALUES (%s, %s, %s, %s, TRUE, TRUE)
            """, (user_id, item.item_id, now, end_date))
        _db_execute_sync("UPDATE users SET donate_coins = COALESCE(donate_coins, 0) - %s WHERE id = %s", (cost, user_id))
        _db_execute_sync("""
            INSERT INTO shop_purchases (user_id, item_name, item_type, amount_paid, currency, telegram_payment_charge_id)
            VALUES (%s, %s, %s, %s, %s, NULL)
        """, (user_id, item.name, item.item_id, cost, "GOLD"))
        conn.commit()
        if (item.item_id or "").startswith("vip"):
            vip_mod.clear_vip_farewell_flag(user_id)
        return True

    @staticmethod
    async def activate_subscription_with_gold_async(user_id: int, item: ShopItem) -> bool:
        return await run_db_call_async(lambda: ShopManager.activate_subscription_with_gold(user_id, item))
    
    @staticmethod
    def get_user_purchases(user_id: int, limit: int = 10) -> list:
        """Get user's purchase history"""
        return _db_fetchall_sync("""
            SELECT item_name, purchase_date, amount_paid, refunded
            FROM shop_purchases
            WHERE user_id = %s
            ORDER BY purchase_date DESC
            LIMIT %s
        """, (user_id, limit))

    @staticmethod
    async def get_user_purchases_async(user_id: int, limit: int = 10) -> list:
        return await _db_fetchall_async(
            """
            SELECT item_name, purchase_date, amount_paid, refunded
            FROM shop_purchases
            WHERE user_id = %s
            ORDER BY purchase_date DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
    
    @staticmethod
    def refund_purchase(user_id: int, telegram_payment_charge_id: str):
        """Mark purchase as refunded"""
        _db_execute_sync("""
            UPDATE shop_purchases 
            SET refunded = TRUE, refund_date = %s
            WHERE telegram_payment_charge_id = %s AND user_id = %s
        """, (datetime.now(), telegram_payment_charge_id, user_id))
        
        # Deactivate subscription if it was a subscription purchase
        result = _db_fetchone_sync("""
            SELECT item_type FROM shop_purchases 
            WHERE telegram_payment_charge_id = %s AND user_id = %s
        """, (telegram_payment_charge_id, user_id))
        
        if result and ("subscription" in result[0] or (result[0] or "").startswith("vip")):
            _db_execute_sync("""
                UPDATE subscriptions 
                SET is_active = FALSE, updated_at = %s
                WHERE user_id = %s
            """, (datetime.now(), user_id))
        
        conn.commit()

    @staticmethod
    async def refund_purchase_async(user_id: int, telegram_payment_charge_id: str):
        await run_db_call_async(lambda: ShopManager.refund_purchase(user_id, telegram_payment_charge_id))

    @staticmethod
    def add_gold_coins_purchase(user_id: int, coins_amount: int, telegram_payment_charge_id: str) -> bool:
        """Нарахування золотих монет за оплату Telegram Stars."""
        if int(coins_amount) <= 0:
            return False
        stars_paid = int(coins_amount) * COIN_STAR_RATE
        _db_execute_sync(
            "INSERT INTO users (id, balance, donate_coins) VALUES (%s, 0, 0) ON CONFLICT (id) DO NOTHING",
            (user_id,),
        )
        _db_execute_sync(
            "UPDATE users SET donate_coins = COALESCE(donate_coins, 0) + %s WHERE id = %s",
            (int(coins_amount), user_id),
        )
        _db_execute_sync(
            """
            INSERT INTO shop_purchases (user_id, item_name, item_type, amount_paid, currency, telegram_payment_charge_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                f"Золоті монети x{int(coins_amount)}",
                "gold_coins_pack",
                stars_paid,
                "XTR",
                telegram_payment_charge_id,
            ),
        )
        conn.commit()
        return True

    @staticmethod
    async def add_gold_coins_purchase_async(user_id: int, coins_amount: int, telegram_payment_charge_id: str) -> bool:
        return await run_db_call_async(
            lambda: ShopManager.add_gold_coins_purchase(user_id, coins_amount, telegram_payment_charge_id)
        )


# VIP - ігрові переваги (рулетка, бонуси, VIP Ринок); «чат» - тарифи статусу в групі
VIP_GAME_SUBSCRIPTION_IDS: tuple[str, ...] = ("vip_30", "vip_plus_30")
CHAT_SUBSCRIPTION_IDS: tuple[str, ...] = (
    "subscription_1month",
    "subscription_3months",
    "subscription_6months",
    "subscription_12months",
)


def _discount_suffix_catalog(item_id: str, *, store_style: bool) -> str:
    if item_id == "subscription_3months":
        return " (знижка 10%) 🎁" if store_style else " (-10%)"
    if item_id == "subscription_6months":
        return " (знижка 20%) 🎁🎁" if store_style else " (-20%)"
    if item_id == "subscription_12months":
        return " (знижка 30%) 🎁🎁🎁" if store_style else " (-30%)"
    return ""


def _catalog_block_borislav_html(item: ShopItem, user_id: int, vip_mod) -> str:
    discount_text = _discount_suffix_catalog(item.item_id, store_style=False)
    star_p = vip_mod.effective_star_price(item, user_id)
    g_line = ""
    if getattr(item, "price_gold", None):
        g_p = vip_mod.effective_gold_price(item, user_id) or item.price_gold
        g_line = f" або {g_p} 🪙"
    block = f"• \"{item.name}\" - {item.duration_days} днів{discount_text}\n"
    block += f"💰 {star_p} ⭐{g_line}\n"
    if item.item_id == vip_mod.VIP_PLUS_ITEM_ID:
        block += f"🎁 <i>VIP+ зараз за акційною ціною <b>{star_p} ⭐</b> (тимчасово).</i>\n"
    elif item.item_id == vip_mod.VIP_ITEM_ID and vip_mod.newbie_vip_discount_eligible(user_id):
        block += "🎁 Перші 24 год - знижка 50% на VIP.\n"
    det = _catalog_description_html(item)
    if det:
        block += f"{det}\n"
    return block + "\n"


def _catalog_block_store_html(item: ShopItem, user_id: int, vip_mod) -> str:
    discount_text = _discount_suffix_catalog(item.item_id, store_style=True)
    star_p = vip_mod.effective_star_price(item, user_id)
    block = f"• <b>{item.name}</b>{discount_text}\n"
    block += f"  💰 Ціна: <code>{star_p} ⭐</code>\n"
    block += f"  ⏱️ Тривалість: <code>{item.duration_days} днів</code>\n"
    det = _catalog_description_html(item)
    if det:
        block += f"{det}\n"
    return block + "\n"


class DonateCommand:
    def __init__(self):
        self.router_donate = Router()

        self.router_donate.message.register(self.shop_menu_handler, Command("shop"))
        self.router_donate.message.register(
            self.test_vip_cmd,
            Command("test_vip"),
            F.chat.type == ChatType.PRIVATE,
        )
        self.router_donate.message.register(self.buy_subscription_handler, Command("buy_subscription"))
        self.router_donate.message.register(self.my_subscription_handler, Command("my_subscription"))
        self.router_donate.message.register(self.stop_subscription_handler, Command("stop_subscription"))
        self.router_donate.message.register(self.subscription_menu_handler, Command("subscription"))
        self.router_donate.message.register(self.refund_handler, RefundAwaitingFilter())
        self.router_donate.message.register(
            self.vip_gift_recipient_handler,
            VipGiftAwaitingFilter(),
            F.chat.type == ChatType.PRIVATE,
        )
        self.router_donate.errors.register(self.errors_handler)
        self.router_donate.message.register(self.success_donate_handler, F.successful_payment)
        self.router_donate.pre_checkout_query.register(self.pre_checkout_handler)

        # Register callback handlers for shop items (Stars)
        for item_id in ShopManager.SHOP_ITEMS.keys():
            self.router_donate.callback_query.register(
                self.create_buy_item_handler(item_id), F.data == f"buy_{item_id}"
            )
        # Купівля підписки за золоті монети
        for item_id in ShopManager.SHOP_ITEMS.keys():
            self.router_donate.callback_query.register(
                self.create_buy_gold_handler(item_id), F.data == f"buy_gold_{item_id}"
            )
        
        self.router_donate.callback_query.register(
            self.my_subscription_callback, F.data == "my_subscription"
        )
        self.router_donate.callback_query.register(
            self.purchase_history_callback, F.data == "purchase_history"
        )
        self.router_donate.callback_query.register(
            self.subscription_menu_callback, F.data.startswith("subscription:")
        )
        self.router_donate.callback_query.register(
            self.vip_upsell_open_shop, F.data == "vip_upsell:shop"
        )

        # Заголовкові кнопки категорій у меню /shop (без покупки)
        self.router_donate.callback_query.register(
            self.shop_section_handler, F.data == "shop_section_vip"
        )
        self.router_donate.callback_query.register(
            self.shop_section_handler, F.data == "shop_section_chat"
        )
        self.router_donate.callback_query.register(
            self.shop_section_handler, F.data == "shop_section_overview"
        )
        self.router_donate.callback_query.register(
            self.shop_section_handler, F.data == "shop_section_coins"
        )
        for pack_id in COIN_PACKS.keys():
            self.router_donate.callback_query.register(
                self.create_buy_coins_handler(pack_id), F.data == f"buy_{pack_id}"
            )
        for item_id in VIP_GAME_SUBSCRIPTION_IDS:
            self.router_donate.callback_query.register(
                self.create_gift_vip_prompt_handler(item_id),
                F.data == f"gift_start_{item_id}",
            )
    
    def create_buy_item_handler(self, item_id: str):
        """Create a handler for buying a specific item"""
        async def handler(callback: CallbackQuery, bot: Bot):
            item = ShopManager.get_item(item_id)
            if not item:
                await callback.answer("Товар не знайдено!", show_alert=True)
                return
            from commands import vip as vip_mod

            uid = callback.from_user.id if callback.from_user else 0
            star_price = vip_mod.effective_star_price(item, uid)

            try:
                link = await bot.create_invoice_link(
                    title=item.name,
                    description=item.description[:255],
                    payload=item.item_id,
                    provider_token="",
                    currency="XTR",
                    prices=[LabeledPrice(label=item.name, amount=star_price)],
                )
                pay_label = f"Оплатити {star_price} ⭐"
                current_markup = callback.message.reply_markup if callback.message else None
                new_markup = _replace_buy_button_with_pay_url(
                    current_markup,
                    target_callback_data=f"buy_{item.item_id}",
                    pay_label=pay_label,
                    pay_url=link,
                )
                if callback.message:
                    await callback.message.edit_reply_markup(reply_markup=new_markup)
                await callback.answer(
                    f"Натисни «{pay_label}» під цим повідомленням.",
                    show_alert=False,
                )
            except Exception:
                # Fallback: звичайний інвойс окремим повідомленням
                if not callback.message:
                    await callback.answer("Не вдалося відкрити оплату.", show_alert=True)
                    return
                await callback.message.answer_invoice(
                    title=item.name,
                    description=item.description[:255],
                    prices=[LabeledPrice(label=item.name, amount=star_price)],
                    provider_token="",
                    currency="XTR",
                    payload=item.item_id,
                    protect_content=True,
                    message_effect_id="5159385139981059251",
                )
                await callback.answer()
        return handler

    def create_gift_vip_prompt_handler(self, item_id: str):
        async def handler(callback: CallbackQuery):
            if not callback.from_user:
                await callback.answer()
                return
            item = ShopManager.get_item(item_id)
            if not item:
                await callback.answer("Тариф не знайдено.", show_alert=True)
                return
            vip_gift_awaiting[callback.from_user.id] = item_id
            await callback.answer()
            if callback.message:
                await callback.message.answer(
                    emoji_to_premium(
                        f"🎁 <b>Подарунок: {item.name}</b>\n\n"
                        "Надішли <b>@username</b> або <b>ID</b> отримувача одним повідомленням.\n"
                        "Щоб скасувати - напиши <code>скасувати</code>."
                    ),
                    parse_mode="html",
                )

        return handler

    async def vip_gift_recipient_handler(self, message: Message, bot: Bot):
        if not message.from_user:
            return
        buyer_id = message.from_user.id
        item_id = vip_gift_awaiting.get(buyer_id)
        if not item_id:
            return

        raw = (message.text or "").strip()
        if raw.lower() in {"скасувати", "cancel", "/cancel"}:
            vip_gift_awaiting.pop(buyer_id, None)
            await message.answer("❎ Подарунок скасовано.")
            return

        recipient_id = await _resolve_gift_recipient_user_id(raw, bot)
        if not recipient_id:
            await message.answer(
                "Не знайшов користувача. Надішли коректний <code>@username</code> або числовий <code>ID</code>.",
                parse_mode="html",
            )
            return
        if recipient_id == buyer_id:
            await message.answer("Не можна подарувати VIP самому собі.")
            return

        item = ShopManager.get_item(item_id)
        if not item:
            vip_gift_awaiting.pop(buyer_id, None)
            await message.answer("Тариф не знайдено. Спробуй ще раз через крамницю.")
            return

        from commands import vip as vip_mod

        star_price = vip_mod.effective_star_price(item, buyer_id)
        payload = _gift_payload(item.item_id, recipient_id)
        try:
            link = await bot.create_invoice_link(
                title=f"🎁 Подарунок: {item.name}",
                description=f"Подарунок VIP для користувача {recipient_id}",
                payload=payload,
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(label=f"Подарунок {item.name}", amount=star_price)],
            )
        except Exception:
            await message.answer("Не вдалося створити оплату. Спробуй ще раз.")
            return
        finally:
            vip_gift_awaiting.pop(buyer_id, None)

        kb = InlineKeyboardBuilder()
        kb.button(text=f"Оплатити {star_price} ⭐", url=link)
        kb.button(text="Відкрити VIP магазин", callback_data="subscription:buy")
        kb.adjust(1)

        await message.answer(
            emoji_to_premium(
                f"🎁 <b>Подарунок готовий</b>\n\n"
                f"📦 Тариф: <b>{item.name}</b>\n"
                f"👤 Отримувач ID: <code>{recipient_id}</code>\n"
                f"💳 До сплати: <b>{star_price} ⭐</b>"
            ),
            parse_mode="html",
            reply_markup=kb.as_markup(),
        )

    def create_buy_gold_handler(self, item_id: str):
        """Купівля підписки за золоті монети (донат)."""
        async def handler(callback: CallbackQuery, bot: Bot):
            item = ShopManager.get_item(item_id)
            if not item or not getattr(item, "price_gold", None):
                await callback.answer("Товар не знайдено або оплата золотом недоступна.", show_alert=True)
                return
            user_id = callback.from_user.id
            from commands import vip as vip_mod

            gold_cost = vip_mod.effective_gold_price(item, user_id) or item.price_gold
            if await ShopManager.activate_subscription_with_gold_async(user_id, item):
                end_str = (datetime.now() + timedelta(days=item.duration_days)).strftime("%d.%m.%Y")
                await callback.message.edit_text(
                    emoji_to_premium(
                        f"✅ <b>Підписку придбано за золоті монети!</b>\n\n"
                        f"📦 {item.name}\n"
                        f"🪙 Списано: {gold_cost} золотих монет\n"
                        f"📅 Діє до: {end_str}\n\n"
                        "Дякуємо за підтримку!"
                    ),
                    parse_mode="html",
                )
            else:
                await callback.answer("❌ Недостатньо золотих монет. Перевір баланс у /profile", show_alert=True)
            await callback.answer()
        return handler

    def create_buy_coins_handler(self, pack_id: str):
        """Купівля пакета золотих монет за Telegram Stars."""
        async def handler(callback: CallbackQuery, bot: Bot):
            coins = COIN_PACKS.get(pack_id)
            if not coins:
                await callback.answer("Пакет не знайдено.", show_alert=True)
                return
            stars = int(coins) * COIN_STAR_RATE
            title = f"🪙 Золоті монети x{coins}"
            description = f"Пакет {coins} золотих монет. Курс: {COIN_STAR_RATE}⭐ = 1🪙."
            try:
                link = await bot.create_invoice_link(
                    title=title,
                    description=description[:255],
                    payload=pack_id,
                    provider_token="",
                    currency="XTR",
                    prices=[LabeledPrice(label=title, amount=stars)],
                )
                pay_label = f"Оплатити {stars} ⭐"
                current_markup = callback.message.reply_markup if callback.message else None
                new_markup = _replace_buy_button_with_pay_url(
                    current_markup,
                    target_callback_data=f"buy_{pack_id}",
                    pay_label=pay_label,
                    pay_url=link,
                )
                if callback.message:
                    await callback.message.edit_reply_markup(reply_markup=new_markup)
                await callback.answer(
                    f"Натисни «{pay_label}» під цим повідомленням.",
                    show_alert=False,
                )
            except Exception:
                if not callback.message:
                    await callback.answer("Не вдалося відкрити оплату.", show_alert=True)
                    return
                await callback.message.answer_invoice(
                    title=title,
                    description=description[:255],
                    prices=[LabeledPrice(label=title, amount=stars)],
                    provider_token="",
                    currency="XTR",
                    payload=pack_id,
                    protect_content=True,
                    message_effect_id="5159385139981059251",
                )
                await callback.answer()
        return handler
    
    async def _shop_menu_content(
        self, user_id: int, section: str = "overview"
    ) -> tuple[str, InlineKeyboardMarkup]:
        from commands import vip as vip_mod

        has_active_subscription = await ShopManager.is_subscription_active_async(user_id)
        subscription_info = ""

        if has_active_subscription:
            sub = await ShopManager.get_user_subscription_async(user_id)
            if sub and sub["subscription_end"]:
                end_date_str = sub["subscription_end"].strftime("%d.%m.%Y %H:%M")
                subscription_info = f"\n\n🕴 <b>Твій теперішній стан:</b>\n✅ Під опікою до: {end_date_str}\nСім'я своїх не забуває."

        builder = InlineKeyboardBuilder()

        def _add_buy_buttons_for(item: ShopItem) -> None:
            star_p = vip_mod.effective_star_price(item, user_id)
            builder.button(
                text=f"{item.name} - {star_p} ⭐",
                callback_data=f"buy_{item.item_id}",
            )
            if getattr(item, "price_gold", None):
                g_p = vip_mod.effective_gold_price(item, user_id) or item.price_gold
                builder.button(
                    text=f"{item.name} - {g_p} 🪙",
                    callback_data=f"buy_gold_{item.item_id}",
                )

        sm = ShopManager.SHOP_ITEMS
        # Огляд: показуємо тільки категорії, без переліку всіх товарів.
        if section == "overview":
            shop_text = (
                "🛖 <b>РИНОК ПАЛЕРМО</b> 🍋\n\n"
                "<blockquote>У Палермо кожен має свій статус. Хтось платить — хтось наказує.</blockquote>\n\n"
                "👤 <b>Особиста підписка</b>\n"
                "<i>рулетка, щоденні гроші, страховка, VIP-Ринок (VIP+), значок біля ніку</i>\n\n"
                "💬 <b>Підписки для чату</b>\n"
                "<i>статус і підтримка в групі на обраний термін</i>\n"
                f"{subscription_info}\n\n"
                "📜 <b>Каталог</b>\n"
                "<i>Оберіть категорію нижче.</i>"
            )

            builder.button(text="⚒️ Особиста підписка", callback_data="shop_section_vip")
            builder.button(text="💬 Підписки для чату", callback_data="shop_section_chat")
            builder.button(text="🪙 Золоті монети", callback_data="shop_section_coins")
            builder.button(text="📋 Моя підписка", callback_data="my_subscription")
            builder.button(text="📜 Історія покупок", callback_data="purchase_history")
            builder.button(text="Повернутися", callback_data="buffshop_back_to_profile")
            builder.adjust(1)
            return shop_text, builder.as_markup()

        # VIP у грі
        if section == "vip":
            shop_text = (
                f"<b>🛖 Ринок Палермо 🛖</b>\n\n"
                f"👤 <b>Особиста підписка</b>\n"
                f"<i>Обери тариф і натисни кнопку з ⭐ або 🪙 нижче.</i>\n\n"
            )
            if subscription_info:
                shop_text = (
                    f"<b>🛖 Ринок Палермо 🛖</b>\n\n"
                    f"Вітаємо.\n"
                    f"У Палермо кожен має свій статус.\n\n"
                    f"{subscription_info}\n\n"
                    f"👤 <b>Особиста підписка</b>\n"
                    f"<i>Обери тариф і натисни кнопку з ⭐ або 🪙 нижче.</i>\n\n"
                )

            # Навігація + самі товари VIP
            builder.button(text="💬 Підписки для чату", callback_data="shop_section_chat")
            builder.button(text="🪙 Золоті монети", callback_data="shop_section_coins")
            builder.button(text="⬅️ Огляд магазину", callback_data="shop_section_overview")
            for iid in VIP_GAME_SUBSCRIPTION_IDS:
                if iid in sm:
                    _add_buy_buttons_for(sm[iid])
            if "vip_30" in sm:
                builder.button(text="🎁 Подарувати VIP", callback_data="gift_start_vip_30")
            if "vip_plus_30" in sm:
                builder.button(text="🎁 Подарувати VIP+", callback_data="gift_start_vip_plus_30")
            builder.button(text="📋 Моя підписка", callback_data="my_subscription")
            builder.button(text="📜 Історія покупок", callback_data="purchase_history")
            builder.button(text="Повернутися", callback_data="buffshop_back_to_profile")
            builder.adjust(1)

            for iid in VIP_GAME_SUBSCRIPTION_IDS:
                if iid in sm:
                    shop_text += _catalog_block_borislav_html(sm[iid], user_id, vip_mod)

            return shop_text, builder.as_markup()

        # Підписки для чату
        if section == "chat":
            shop_text = (
                f"<b>🛖 Ринок Палермо 🛖</b>\n\n"
                f"💬 <b>Підписки для чату</b>\n"
                f"<i>Тривалість під опікою бота в групі.</i>\n\n"
            )
            if subscription_info:
                shop_text = (
                    f"<b>🛖 Ринок Палермо 🛖</b>\n\n"
                    f"Вітаємо.\n"
                    f"У Палермо кожен має свій статус.\n\n"
                    f"{subscription_info}\n\n"
                    f"💬 <b>Підписки для чату</b>\n"
                    f"<i>Тривалість під опікою бота в групі.</i>\n\n"
                )

            builder.button(text="⚒️ Особиста підписка", callback_data="shop_section_vip")
            builder.button(text="🪙 Золоті монети", callback_data="shop_section_coins")
            builder.button(text="⬅️ Огляд магазину", callback_data="shop_section_overview")
            for iid in CHAT_SUBSCRIPTION_IDS:
                if iid in sm:
                    _add_buy_buttons_for(sm[iid])
            builder.button(text="📋 Моя підписка", callback_data="my_subscription")
            builder.button(text="📜 Історія покупок", callback_data="purchase_history")
            builder.button(text="Повернутися", callback_data="buffshop_back_to_profile")
            builder.adjust(1)

            for iid in CHAT_SUBSCRIPTION_IDS:
                if iid in sm:
                    shop_text += _catalog_block_borislav_html(sm[iid], user_id, vip_mod)

            return shop_text, builder.as_markup()

        if section == "coins":
            shop_text = (
                f"<b>🛖 Ринок Палермо 🛖</b>\n\n"
                f"🪙 <b>Купівля золотих монет</b>\n"
                f"⭐ <b>Курс у боті:</b> <code>{COIN_STAR_RATE} ⭐ = 1 🪙</code>\n"
                f"🏦 <b>Через банк:</b> <code>{BANK_UAH_RATE} грн = 1 🪙</code>\n\n"
                f"<i>Оберіть пакет нижче.</i>\n\n"
            )
            for pack_id, coins in COIN_PACKS.items():
                stars = int(coins) * COIN_STAR_RATE
                builder.button(
                    text=f"🪙 {coins} монет - {stars} ⭐",
                    callback_data=f"buy_{pack_id}",
                )
            builder.button(text="Повернутися", callback_data="shop_main")
            builder.adjust(1)
            return shop_text, builder.as_markup()

        # На всяк випадок (якщо прийде невідомий section)
        shop_text = (
            f"<b>🛖 Ринок Палермо 🛖</b>\n\n"
            f"{subscription_info}\n\n"
            f"📜 <b>Каталог</b>\n\n"
            f"<i>Оберіть категорію нижче.</i>\n"
        )
        builder.button(text="🎮 VIP у грі", callback_data="shop_section_vip")
        builder.button(text="💬 Підписки для чату", callback_data="shop_section_chat")
        builder.button(text="📋 Моя підписка", callback_data="my_subscription")
        builder.button(text="📜 Історія покупок", callback_data="purchase_history")
        builder.adjust(1)
        return shop_text, builder.as_markup()

    async def shop_section_handler(self, callback: CallbackQuery):
        """Перемикає секцію меню /shop і редагує поточне повідомлення."""
        if not callback.from_user or not callback.message:
            await callback.answer()
            return

        section = "overview"
        if callback.data == "shop_section_vip":
            section = "vip"
        elif callback.data == "shop_section_chat":
            section = "chat"
        elif callback.data == "shop_section_coins":
            section = "coins"
        elif callback.data == "shop_section_overview":
            section = "overview"

        shop_text, markup = await self._shop_menu_content(callback.from_user.id, section=section)
        text = emoji_to_premium(shop_text)

        try:
            await callback.message.edit_text(text, reply_markup=markup, parse_mode="html")
        except TelegramBadRequest:
            # Якщо редагування неможливе (наприклад, текст не змінився) - просто відповідаємо.
            await callback.answer()
            return
        await callback.answer()

    async def shop_menu_handler(self, message: Message):
        """Show shop menu with available items"""
        if not message.from_user:
            return
        shop_text, markup = await self._shop_menu_content(message.from_user.id, section="overview")
        await message.answer(emoji_to_premium(shop_text), reply_markup=markup, parse_mode="html")

    async def test_vip_cmd(self, message: Message):
        """/test_vip - один раз: безкоштовний VIP+ на 2 дні (лише в ЛС)."""
        if not message.from_user:
            return
        ok, text = await ShopManager.try_grant_test_vip_async(message.from_user.id)
        await message.answer(emoji_to_premium(text), parse_mode="html")

    async def vip_upsell_open_shop(self, callback: CallbackQuery):
        if not callback.from_user or not callback.message:
            await callback.answer()
            return
        from commands import vip as vip_mod

        uid = callback.from_user.id
        text = (
            "Вітаємо.\n"
            "У Палермо кожен має свій статус.\n\n"
            "• <b>⚒️ VIP (30 днів)</b>\n"
            "  • +20% до виграшів у рулетці\n"
            "  • щодня +1000💵\n"
            "  • 1 страховка/день (50% повернення програшу)\n"
            "  • мʼякше КД (-15%)\n"
            "  • значок ⚒️ у перевагах.\n\n"
            "• <b>⛏️ VIP+ (30 днів)</b>\n"
            "  • +30% до виграшів\n"
            "  • щодня +2000💵\n"
            "  • 2 страховки/день\n"
            "  • «перекрут» у рулетці після програшу\n"
            "  • доступ до VIP Ринку (-25% на бафи)\n"
            "  • КД -25%."
        )
        kb = InlineKeyboardBuilder()
        _subscription_tier_buttons(kb, vip_mod.VIP_ITEM_ID, vip_mod.VIP_PLUS_ITEM_ID)
        kb.adjust(1)
        try:
            await callback.bot.send_message(
                chat_id=uid,
                text=emoji_to_premium(text),
                reply_markup=kb.as_markup(),
                parse_mode="html",
            )
        except TelegramForbiddenError:
            await callback.answer(
                "Спочатку натисни /start у приватному чаті з ботом - тоді надішлю меню VIP.",
                show_alert=True,
            )
            return
        except TelegramBadRequest as e:
            err = str(e).lower()
            if "chat not found" in err or "user not found" in err or "peer_id" in err:
                await callback.answer(
                    "Відкрий бота в особистих повідомленнях і натисни /start.",
                    show_alert=True,
                )
                return
            raise
        chat = callback.message.chat
        if getattr(chat, "type", None) == "private":
            await callback.answer()
        else:
            await callback.answer("Меню VIP надіслано в особисті повідомлення ✉️")
    
    async def buy_subscription_handler(self, message: Message):
        """Quick handler for /buy_subscription command"""
        await self.shop_menu_handler(message)

    async def subscription_menu_handler(
        self,
        message: Message,
        *,
        edit_current: bool = False,
        user_id: int | None = None,
    ):
        """
        Єдина команда /subscription:
        1) показує VIP статус;
        2) дає розвилку: Придбати VIP або Повернутися.
        """
        user_id = int(user_id) if user_id is not None else (message.from_user.id if message.from_user else None)
        if user_id is None:
            return
        from commands import vip as vip_mod
        sub = await ShopManager.get_user_subscription_async(user_id)
        active_tier = vip_mod.active_vip_tier(user_id)

        if not active_tier:
            text = "Ваш VIP статус неактивний❌"
        else:
            test_until = vip_mod.get_game_vip_test_until(user_id)
            vip_label = "⛏️VIP+" if active_tier == "vip_plus" else "⚒️VIP"
            if test_until:
                vip_label = "⛏️VIP+ <i>(тест)</i>"
            end_date = "Без обмежень"
            if test_until:
                end_date = test_until.strftime("%d.%m.%Y %H:%M")
            elif sub:
                sub_type = (sub.get("subscription_type") or "").strip()
                # Показуємо дату тільки для VIP/VIP+ тарифів
                if sub_type in (vip_mod.VIP_ITEM_ID, vip_mod.VIP_PLUS_ITEM_ID):
                    end_date = sub["subscription_end"].strftime("%d.%m.%Y %H:%M") if sub.get("subscription_end") else "Без обмежень"
            text = f"Ваш статус:\n{vip_label}\nАктуальний до: {end_date}"

        text = emoji_to_premium(text)

        kb = InlineKeyboardBuilder()
        kb.button(text="Придбати VIP", callback_data="subscription:buy")
        kb.button(text="Повернутися", callback_data="buffshop_back_to_profile")
        kb.adjust(1)
        if edit_current:
            await message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="html")
        else:
            await message.answer(text, reply_markup=kb.as_markup(), parse_mode="html")

    async def my_subscription_handler(self, message: Message):
        """Handler for /my_subscription command"""
        await self.show_subscription_info(message.from_user.id, message)

    async def my_subscription_callback(self, callback: CallbackQuery):
        """Callback handler for subscription info"""
        await self.show_subscription_info(callback.from_user.id, callback.message)
        await callback.answer()

    async def subscription_menu_callback(self, callback: CallbackQuery, bot: Bot):
        """
        Обробка кнопок з меню /subscription:
        - subscription:buy      → відкрити меню VIP (⚒️VIP / ⛏️VIP+)
        - subscription:pay_select:<item_id> → вибір способу оплати (⭐ або 🪙)
        - subscription:pause    → запустити процес повернення / призупинення
        """
        data = (callback.data or "")
        action = data.split(":", 1)[1] if ":" in data else ""
        # Якщо немає конкретної дії - просто показуємо меню підписки
        if not action or action == "menu":
            await self.subscription_menu_handler(
                callback.message,
                edit_current=True,
                user_id=callback.from_user.id if callback.from_user else None,
            )
            await callback.answer()
            return

        from commands import vip as vip_mod

        if action in ("buy", "extend"):
            # Твоя нова вітрина VIP: спочатку вибір VIP/VIP+, далі оплата.
            buy_text = (
                "Вітаємо.\n"
                "У Палермо кожен має свій статус.\n\n"
                "• <b>⚒️ VIP (30 днів)</b>\n"
                "  • +20% до виграшів у рулетці\n"
                "  • щодня +1000💵\n"
                "  • 1 страховка/день (50% повернення програшу)\n"
                "  • мʼякше КД (-15%)\n"
                "  • значок ⚒️ у перевагах.\n\n"
                "• <b>⛏️ VIP+ (30 днів)</b>\n"
                "  • +30% до виграшів\n"
                "  • щодня +2000💵\n"
                "  • 2 страховки/день\n"
                "  • «перекрут» у рулетці після програшу\n"
                "  • доступ до VIP Ринку (-25% на бафи)\n"
                "  • КД -25%.\n\n"
                "🎁 <i>Можна також подарувати VIP/VIP+ іншому гравцю.</i>"
            )
            kb = InlineKeyboardBuilder()
            _subscription_tier_buttons(kb, vip_mod.VIP_ITEM_ID, vip_mod.VIP_PLUS_ITEM_ID)
            kb.button(text="🎁 Подарувати VIP", callback_data=f"gift_start_{vip_mod.VIP_ITEM_ID}")
            kb.button(text="🎁 Подарувати VIP+", callback_data=f"gift_start_{vip_mod.VIP_PLUS_ITEM_ID}")
            kb.button(text="Повернутися", callback_data="subscription:menu")
            kb.adjust(1)
            if callback.from_user and callback.message:
                await callback.message.edit_text(
                    emoji_to_premium(buy_text),
                    reply_markup=kb.as_markup(),
                    parse_mode="html",
                )
            await callback.answer()
            return

        if action.startswith("pay_select:"):
            item_id = action.split(":", 1)[1] if ":" in action else ""
            if item_id not in (vip_mod.VIP_ITEM_ID, vip_mod.VIP_PLUS_ITEM_ID):
                await callback.answer("Некоректний вибір.", show_alert=True)
                return
            item = ShopManager.get_item(item_id)
            if not item:
                await callback.answer("Тариф не знайдено.", show_alert=True)
                return
            uid = callback.from_user.id if callback.from_user else 0
            star_price = vip_mod.effective_star_price(item, uid)
            gold_price = vip_mod.effective_gold_price(item, uid) or item.price_gold
            pay_text = "Оберіть спосіб оплати:"
            kb = InlineKeyboardBuilder()
            kb.button(text=f"⭐ Зірки - {star_price}", callback_data=f"buy_{item_id}")
            kb.button(text=f"🪙 Монети - {gold_price}", callback_data=f"buy_gold_{item_id}")
            kb.button(text="Повернутися", callback_data="subscription:buy")
            kb.adjust(1)
            if callback.from_user and callback.message:
                await callback.message.edit_text(
                    emoji_to_premium(pay_text),
                    reply_markup=kb.as_markup(),
                    parse_mode="html",
                )
            await callback.answer()
            return

        if action == "pause":
            await self._start_refund_flow(callback.from_user.id, callback.message, bot)
            await callback.answer()
            return
        await callback.answer()

    async def show_subscription_info(self, user_id: int, message: Message):
        """Show user's subscription information"""
        subscription = await ShopManager.get_user_subscription_async(user_id)
        
        if not subscription or not await ShopManager.is_subscription_active_async(user_id):
            await message.answer(
                "❌ <b>Немає активної підписки</b> ❌\n\n"
                ""
                "У тебе зараз немає активної підписки.\n\n"
                "💡 <i>Придбай підписку, щоб отримати доступ до всіх функцій бота!</i>\n\n"
                "👉 Використай <code>/shop</code> щоб переглянути доступні підписки.",
                parse_mode="html"
            )
            return
        
        item = ShopManager.get_item(subscription["subscription_type"])
        item_name = item.name if item else subscription["subscription_type"]
        
        start_date = subscription["subscription_start"].strftime("%d.%m.%Y %H:%M") if subscription["subscription_start"] else "N/A"
        end_date = subscription["subscription_end"].strftime("%d.%m.%Y %H:%M") if subscription["subscription_end"] else "Без обмежень"
        
        days_left = 0
        if subscription["subscription_end"]:
            delta = subscription["subscription_end"] - datetime.now()
            days_left = max(0, delta.days)
        
        status_emoji = "✅" if days_left > 7 else "⚠️" if days_left > 0 else "❌"
        
        info_text = (
            f"📋 <b>Моя підписка</b> 📋\n\n"
            f"📦 <b>Тип підписки:</b> {item_name}\n"
            f"📅 <b>Початок:</b> <code>{start_date}</code>\n"
            f"📅 <b>Закінчення:</b> <code>{end_date}</code>\n\n"
            f"⏰ <b>Залишилось днів:</b> <code>{days_left}</code> {status_emoji}\n"
            f"🔄 <b>Автопоновлення:</b> {'✅ Так' if subscription['auto_renew'] else '❌ Ні'}\n\n"
            f"{status_emoji} <b>Підписка активна!</b> {status_emoji}"
        )
        
        await message.answer(info_text, parse_mode="html")
    
    async def purchase_history_callback(self, callback: CallbackQuery):
        """Show user's purchase history"""
        purchases = await ShopManager.get_user_purchases_async(callback.from_user.id, limit=20)
        
        if not purchases:
            await callback.answer("У тебе немає покупок!", show_alert=True)
            return
        
        history_text = (
            "📜 <b>Історія покупок</b> 📜\n\n"
            ""
        )
        for idx, (item_name, purchase_date, amount_paid, refunded) in enumerate(purchases, 1):
            date_str = purchase_date.strftime("%d.%m.%Y %H:%M") if isinstance(purchase_date, datetime) else str(purchase_date)
            refunded_emoji = "🔴 (Повернено)" if refunded else "✅"
            history_text += (
                f"<b>{idx}.</b> {item_name}\n"
                f"   💰 <code>{amount_paid} ⭐</code>\n"
                f"   📅 {date_str}\n"
                f"   {refunded_emoji}\n\n"
            )
        history_text += ""
        
        await callback.message.edit_text(emoji_to_premium(history_text), parse_mode="html")
        await callback.answer()

    async def pre_checkout_handler(self, pre_checkout: PreCheckoutQuery, bot: Bot):
        """Handle pre-checkout query"""
        # Validate the item exists
        payload = pre_checkout.invoice_payload
        gift_info = _parse_gift_payload(payload)
        if gift_info:
            gift_item_id, _recipient_id = gift_info
            item = ShopManager.get_item(gift_item_id)
            if not item:
                await bot.answer_pre_checkout_query(pre_checkout.id, ok=False, error_message="Подарунковий тариф не знайдено!")
                return
            from commands import vip as vip_mod

            uid = pre_checkout.from_user.id if pre_checkout.from_user else 0
            expected = vip_mod.effective_star_price(item, uid)
            if pre_checkout.total_amount != expected:
                await bot.answer_pre_checkout_query(pre_checkout.id, ok=False, error_message="Невірна ціна подарунка!")
                return
            await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)
            return
        item = ShopManager.get_item(payload)
        if payload in COIN_PACKS:
            expected = int(COIN_PACKS[payload]) * COIN_STAR_RATE
            if pre_checkout.total_amount != expected:
                await bot.answer_pre_checkout_query(pre_checkout.id, ok=False, error_message="Невірна ціна пакета монет!")
                return
            await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)
            return
        if not item:
            await bot.answer_pre_checkout_query(pre_checkout.id, ok=False, error_message="Товар не знайдено!")
            return
        
        from commands import vip as vip_mod

        uid = pre_checkout.from_user.id if pre_checkout.from_user else 0
        expected = vip_mod.effective_star_price(item, uid)
        if pre_checkout.total_amount != expected:
            await bot.answer_pre_checkout_query(pre_checkout.id, ok=False, error_message="Невірна ціна товару!")
            return
        
        await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)

    async def success_donate_handler(self, message: Message, bot: Bot):
        """Handle successful payment"""
        if not message.successful_payment:
            return
        
        payment = message.successful_payment
        user_id = message.from_user.id
        
        # Get item from payload
        item_id = payment.invoice_payload
        gift_info = _parse_gift_payload(item_id)
        if gift_info:
            gift_item_id, recipient_id = gift_info
            item = ShopManager.get_item(gift_item_id)
            if not item:
                await message.answer("❌ Помилка: подарунковий тариф не знайдено.")
                return
            try:
                await ShopManager.activate_subscription_async(
                    recipient_id,
                    item,
                    payment.telegram_payment_charge_id,
                    stars_paid=int(payment.total_amount),
                )
                await message.answer(
                    emoji_to_premium(
                        f"✅ <b>Подарунок оплачено!</b>\n\n"
                        f"📦 {item.name}\n"
                        f"👤 Отримувач: <code>{recipient_id}</code>\n"
                        f"⭐ Списано: <b>{int(payment.total_amount)}</b>"
                    ),
                    parse_mode="html",
                )
                try:
                    await bot.send_message(
                        chat_id=recipient_id,
                        text=emoji_to_premium(
                            f"🎁 <b>Тобі подарували підписку!</b>\n\n"
                            f"Активовано: <b>{item.name}</b>\n"
                            "Перевір свій статус у <code>/subscription</code>."
                        ),
                        parse_mode="html",
                    )
                except Exception:
                    pass
                return
            except Exception as e:
                print(f"ERROR activating gift subscription: {e}")
                await message.answer("⚠️ Помилка при активації подарунка. Звернись до підтримки.")
                return
        if item_id in COIN_PACKS:
            coins = int(COIN_PACKS[item_id])
            try:
                ok = await ShopManager.add_gold_coins_purchase_async(
                    user_id, coins, payment.telegram_payment_charge_id
                )
                if not ok:
                    await message.answer("⚠️ Помилка нарахування монет. Звернись до підтримки.")
                    return
                await message.answer(
                    emoji_to_premium(
                        f"✅ <b>Оплата успішна!</b>\n\n"
                        f"🪙 Нараховано: <b>{coins}</b> золотих монет\n"
                        f"⭐ Списано: <b>{coins * COIN_STAR_RATE}</b> зірок\n\n"
                        f"🏦 Через банк також доступно: <b>{BANK_UAH_RATE} грн = 1 🪙</b>."
                    ),
                    parse_mode="html",
                )
                return
            except Exception:
                await message.answer("⚠️ Помилка нарахування монет. Звернись до підтримки.")
                return

        item = ShopManager.get_item(item_id)
        
        if not item:
            await message.answer("❌ Помилка: товар не знайдено!")
            return
        
        # Activate subscription
        try:
            await ShopManager.activate_subscription_async(
                user_id,
                item,
                payment.telegram_payment_charge_id,
                stars_paid=int(payment.total_amount),
            )
            
            days_text = f" на {item.duration_days} днів" if item.duration_days > 0 else ""
            
            await message.answer(
                f"✅ <b>Оплата успішна!</b> ✅\n\n"
                f"🎉 <b>Дякуємо за покупку!</b> 🎉\n\n"
                f"📦 <b>Придбано:</b> {item.name}{days_text}\n\n"
                f"✅ Твоя підписка <b>активована</b> та готова до використання!\n\n"
                f"💡 <i>Тепер ти маєш доступ до всіх преміум функцій бота.</i>",
                protect_content=True, 
                message_effect_id="5046509860389126442",
                parse_mode="html"
            )
        except Exception as e:
            print(f"ERROR activating subscription: {e}")
            await message.answer("⚠️ Помилка при активації підписки. Звернись до підтримки.")

    async def _start_refund_flow(self, user_id: int, message: Message, bot: Bot):
        """Починає діалог повернення / призупинення підписки (з повідомлення або callback)."""
        await message.answer(
            "💸 <b>Повернення коштів / призупинення підписки</b>\n\n"
            "⬇️ <b>Надішли ID транзакції</b> для повернення коштів:\n\n"
            "💡 <i>ID транзакції можна знайти в історії покупок:\n"
            "<code>/shop</code> → <b>Історія покупок</b></i>\n\n"
            "⚠️ <i>Після повернення підписка буде деактивована.</i>",
            protect_content=True,
            message_effect_id="5104841245755180586",
            parse_mode="html",
        )
        refund_awaiting_user_ids.add(user_id)

    async def stop_subscription_handler(self, message: Message, bot: Bot):
        """Handle subscription cancellation/refund request (старий /stop_subscription)."""
        await self._start_refund_flow(message.from_user.id, message, bot)

    async def refund_handler(self, message: Message, bot: Bot):
        """Handle refund request (тільки для користувача, який викликав /stop_subscription)."""
        user_id = message.from_user.id
        if user_id not in refund_awaiting_user_ids:
            return
        refund_awaiting_user_ids.discard(user_id)
        telegram_payment_charge_id = (message.text or "").strip()
        
        # Check if purchase exists and belongs to user
        result = await _db_fetchone_async("""
            SELECT refunded, item_name 
            FROM shop_purchases 
            WHERE telegram_payment_charge_id = %s AND user_id = %s
        """, (telegram_payment_charge_id, user_id))
        
        if not result:
            await message.answer(
                "❌ Транзакція не знайдена!\n"
                "Переконайся, що ID транзакції правильний.",
                protect_content=True
            )
            return
        
        is_refunded, item_name = result
        
        if is_refunded:
            await message.answer(
                "⚠️ За цю транзакцію вже було повернено кошти!",
                protect_content=True
            )
            return
        
        try:
            # Refund via Telegram API
            await bot.refund_star_payment(
                user_id=user_id, 
                telegram_payment_charge_id=telegram_payment_charge_id
            )
            
            # Mark as refunded in database
            await ShopManager.refund_purchase_async(user_id, telegram_payment_charge_id)
            
            await message.answer(
                f"✅ <b>Кошти повернено!</b>\n\n"
                f"Покупка '{item_name}' була скасована.\n"
                f"Твої зірочки повернені на баланс.",
                protect_content=True, 
                message_effect_id="5104841245755180586",
                parse_mode="html"
            )
        except TelegramBadRequest as e:
            error_msg = str(e)
            if "CHARGE_NOT_FOUND" in error_msg:
                await message.answer(
                    "❌ Цю транзакцію я не виконував!",
                    protect_content=True
                )
            elif "CHARGE_ALREADY_REFUNDED" in error_msg:
                await message.answer(
                    "⚠️ За цю транзакцію вже було повернено кошти!",
                    protect_content=True
                )
                await ShopManager.refund_purchase_async(user_id, telegram_payment_charge_id)
            else:
                await message.answer(
                    f"❌ Помилка при поверненні: {error_msg}",
                    protect_content=True
                )

    async def errors_handler(self, error: ErrorEvent):
        """Handle payment errors"""
        exception = error.exception
        update = error.update
        
        if isinstance(exception, TelegramBadRequest):
            error_str = str(exception)
            if "CHARGE_NOT_FOUND" in error_str:
                if update.message:
                    await update.message.answer(
                        "❌ Цю транзакцію я не виконував!",
                        protect_content=True
                    )
            elif "CHARGE_ALREADY_REFUNDED" in error_str:
                if update.message:
                    await update.message.answer(
                        "⚠️ За цю транзакцію вже було повернено кошти!",
                        protect_content=True
                    )


# Initialize DonateCommand and register its router
donate_command = DonateCommand()
router_pay.include_router(donate_command.router_donate)

