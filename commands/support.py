"""
Тех. підтримка через ПП бота.
Користувач: меню -> категорія -> опис проблеми -> створення тікета.
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.database import create_support_ticket, get_ticket_notifier_ids
from aiogram import Router, F
from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

router_support = Router()

# Стан: user_id -> category (користувач очікує введення опису)
support_awaiting_description: dict[int, str] = {}


class SupportAwaitingFilter(BaseFilter):
    """Пропускає тільки повідомлення від користувачів, які очікують введення опису тікета. Інакше /shop, /buff_shop тощо не доходять до своїх обробників."""
    async def __call__(self, message: Message) -> bool:
        # Команди (/start, /cat, ...) НЕ перехоплюємо, навіть якщо користувач у стані опису тікета,
        # інакше застряглий стан "ковтає" команди й вони не доходять до своїх обробників.
        if (getattr(message, "text", None) or "").strip().startswith("/"):
            return False
        return bool(
            getattr(message, "from_user", None)
            and message.from_user.id in support_awaiting_description
        )

SUPPORT_CATEGORIES = {
    "purchases": "🛒 Покупки",
    "technical": "⚙️ Технічна проблема",
    "payment": "💳 Оплата",
    "other": "❓ Інше",
}


def get_categories_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"support_category_{key}")]
        for key, label in SUPPORT_CATEGORIES.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router_support.callback_query(F.data == "support_main")
async def support_main_cb(callback: CallbackQuery):
    """Відкрити вибір категорії підтримки."""
    if not callback.message or not callback.from_user:
        return
    if callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в особистих повідомленнях.", show_alert=True)
        return
    text = (
        "🛠 <b>Тех. Підтримка</b> 🛠\n\n"
        "Оберіть категорію звернення:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_categories_keyboard(), parse_mode="html")
    except Exception:
        await callback.message.answer(text, reply_markup=get_categories_keyboard(), parse_mode="html")
    await callback.answer()


@router_support.callback_query(F.data.startswith("support_category_"))
async def support_category_cb(callback: CallbackQuery):
    """Обрано категорію - просимо описати проблему."""
    if not callback.message or not callback.from_user:
        return
    if callback.message.chat.type != "private":
        await callback.answer()
        return
    data = callback.data
    if not data.startswith("support_category_"):
        await callback.answer()
        return
    category_key = data.replace("support_category_", "")
    if category_key not in SUPPORT_CATEGORIES:
        await callback.answer("Невідома категорія.", show_alert=True)
        return
    support_awaiting_description[callback.from_user.id] = category_key
    category_label = SUPPORT_CATEGORIES[category_key]
    text = (
        f"📝 <b>Категорія:</b> {category_label}\n\n"
        "Опишіть проблему текстом або надішліть фото (з підписом або без).\n"
        "Після відправки буде створено тікет, і підтримка відповість вам найближчим часом."
    )
    try:
        await callback.message.edit_text(text, parse_mode="html")
    except Exception:
        await callback.message.answer(text, parse_mode="html")
    await callback.answer()


def _extract_ticket_text(message: Message) -> str | None:
    """Повертає текст для тікета: з повідомлення (текст, підпис до фото) або позначку про медіа."""
    text = (message.text or message.caption or "").strip()
    if text:
        return text
    if message.photo:
        return "(прикріплено фото)"
    if message.video:
        return "(прикріплено відео)"
    if message.document:
        return "(прикріплено файл)"
    if message.voice or message.video_note:
        return "(голосове / відеоповідомлення)"
    return None


async def _create_ticket_and_notify(message: Message, user_id: int, category_key: str, text: str):
    """Створює тікет за текстом і сповіщає засновників; при наявності фото/медіа пересилає їх засновникам."""
    category_label = SUPPORT_CATEGORIES.get(category_key, category_key)
    username = message.from_user.username
    try:
        ticket_id = create_support_ticket(
            user_id=user_id,
            username=username,
            category=category_label,
            message_text=text,
        )
        await message.answer(
            f"✅ Ваш тікет №{ticket_id} створено. Очікуйте відповіді підтримки.",
            parse_mode="html",
        )
        notify_ids = get_ticket_notifier_ids()
        notify_text = (
            f"📩 <b>Новий тікет №{ticket_id}</b>\n\n"
            f"👤 ID: <code>{user_id}</code> | @{username or '-'}\n"
            f"📁 Категорія: {category_label}\n\n"
            f"💬 {text[:300]}{'…' if len(text) > 300 else ''}\n\n"
            f"Відповісти в ПП: <code>/support_panel</code> (підтримка) або "
            f"<code>/capone_admin</code> → «Тікети» (засновники)"
        )
        for fid in notify_ids:
            try:
                await message.bot.send_message(fid, notify_text, parse_mode="html")
                # Якщо є фото/медіа - пересилаємо засновнику
                if message.photo or message.video or message.document:
                    await message.forward(fid)
            except Exception:
                pass
    except Exception:
        support_awaiting_description[user_id] = category_key
        await message.answer("❌ Помилка при створенні тікета. Спробуйте пізніше або зверніться до адміністратора.")


@router_support.message(F.chat.type == "private", F.text, SupportAwaitingFilter())
async def support_message_handler(message: Message):
    """Текстовий опис - створюємо тікет."""
    if not message.from_user or not message.text:
        return
    user_id = message.from_user.id
    if (message.text or "").strip().startswith("/"):
        support_awaiting_description.pop(user_id, None)
        return
    category_key = support_awaiting_description.pop(user_id, None)
    if category_key is None:
        return
    text = (message.text or "").strip()
    if not text:
        support_awaiting_description[user_id] = category_key
        await message.answer("Будь ласка, надішліть текст опису проблеми.")
        return
    await _create_ticket_and_notify(message, user_id, category_key, text)


@router_support.message(F.chat.type == "private", F.photo, SupportAwaitingFilter())
async def support_photo_handler(message: Message):
    """Опис з фото - створюємо тікет, текст з підпису або «(прикріплено фото)», фото пересилаємо засновникам."""
    if not message.from_user:
        return
    user_id = message.from_user.id
    category_key = support_awaiting_description.pop(user_id, None)
    if category_key is None:
        return
    text = _extract_ticket_text(message)
    if not text:
        text = "(прикріплено фото)"
    await _create_ticket_and_notify(message, user_id, category_key, text)


@router_support.message(F.chat.type == "private", (F.video | F.document), SupportAwaitingFilter())
async def support_media_handler(message: Message):
    """Відео або файл з описом - створюємо тікет так само."""
    if not message.from_user:
        return
    user_id = message.from_user.id
    category_key = support_awaiting_description.pop(user_id, None)
    if category_key is None:
        return
    text = _extract_ticket_text(message)
    if not text:
        text = "(прикріплено медіа)"
    await _create_ticket_and_notify(message, user_id, category_key, text)
