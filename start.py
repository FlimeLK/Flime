import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.database import *
from database.database import (
    block_user_async, unblock_user_async, is_user_blocked_async,
    get_predictions_enabled_async, set_predictions_enabled_async,
    try_grant_starter_gift_async, add_gold_to_subscription_fund, get_subscription_fund_gold, deduct_user_gold_async,
    add_gold_to_user_async, get_group_creator_id_async, run_db_call_async,
)
from commands.story_achievements import ensure_achievements_sync, _filter_obsolete_cards
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import CommandStart, Command
from aiogram.exceptions import TelegramBadRequest


router_start = Router()

# ID головного власника бота (завжди має права власника)
BOT_OWNER_ID = 1859870653

keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="➕ Додати бота до групи", url='https://t.me/sicilian_mafia_bot?startgroup=true')]
])


async def _db_fetchone(query: str, params: tuple = ()):
    def _run():
        cursor.execute(query, params)
        return cursor.fetchone()
    return await run_db_call_async(_run)


async def _db_fetchall(query: str, params: tuple = ()):
    def _run():
        cursor.execute(query, params)
        return cursor.fetchall()
    return await run_db_call_async(_run)


async def _db_execute_commit(query: str, params: tuple = ()) -> None:
    def _run():
        cursor.execute(query, params)
        conn.commit()
    await run_db_call_async(_run)


async def add_user_to_db(message: Message):
    """Add or update user in database"""
    if cursor is None or conn is None:
        return
    username = message.from_user.username
    telegram_id = message.from_user.id
    username_telegram = message.from_user.first_name
    record = await _db_fetchone("SELECT * FROM users WHERE id = %s", (telegram_id,))

    if message.chat.type == "private" or message.chat.type == "supergroup" or message.chat.type == "group":
        if record is None:
                await _db_execute_commit(
                    "INSERT INTO users (id, tg_name, link) VALUES (%s, %s, %s)",
                    (telegram_id, username_telegram, username),
                )
        else:
            if record[1] != username_telegram or record[1] != username:
                await _db_execute_commit(
                    "UPDATE users SET tg_name = %s, link = %s WHERE id = %s",
                    (username_telegram, username, telegram_id,),
                )

@router_start.message(CommandStart())
async def start_cmd(message: Message):
    """Start command handler"""
    await add_user_to_db(message=message)
    if message.chat.type == "private":
        from commands.support import support_awaiting_description
        if message.from_user:
            support_awaiting_description.pop(message.from_user.id, None)
        text = (
            "<b>Ласкаво просимо до штабу Галицької Мафії!</b> 🕵️‍♂️🏙️\n\n"
            "Ми розширюємо межі гри.\n"
            "Тепер ти не просто гравець - ти дослідник великого всесвіту.\n\n"
            "Що на тебе чекає?\n\n"
            "1️⃣ <b>Ексклюзивний контент:</b> Виконуй завдання та отримуй рідкісні карти.\n"
            "2️⃣ <b>Колекціонування:</b> Збери повний набір героїв Галицької Мафії.\n"
            "3️⃣ <b>Лор гри:</b> Кожна карта відкриває доступ до унікальної історії персонажа.\n\n"
            "Збери їх усіх та дізнайся, що приховує місто після заходу сонця! 🌑"
        )
        keyboard_main = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Розпочати перше завдання", callback_data="start_quest")],
            [InlineKeyboardButton(text="📜 Про всесвіт гри", callback_data="start_lore")],
            [InlineKeyboardButton(text="⚙️ Налаштування", callback_data="start_settings")],
        ])
        await message.answer(text, reply_markup=keyboard_main, parse_mode="html")
        # Подарунковий бонус для перших 100 користувачів
        if message.from_user:
            try:
                if await try_grant_starter_gift_async(message.from_user.id):
                    gift_text = (
                        "Вітаємо Вас у Всесвіті омитому Бориславською нафтою, та кров'ю зрадників. "
                        "Ви потрапили в список перших 100 жителів нашого міста, щоб Сім'я не знайшла і не знищила вас в перший день — "
                        "прийміть від нас (не)скромний подарунок. Впевнені — він вам знадобиться 🖤\n\n"
                        "<b>Начислення:</b>\n"
                        "💰 1000 злотих;\n"
                        "🪙 10 золотих монет."
                    )
                    await message.answer(gift_text, parse_mode="html")
            except Exception:
                pass
    else:
        text = (
            "🎮 <b>Mafia All Capone Bot</b> 🎮\n\n"
            "💡 Додай бота до групи та пиши <code>/play</code>, щоб почати гру!"
        )
        await message.answer(text, reply_markup=keyboard, parse_mode="html")


@router_start.message(Command("block"), F.chat.type == "private")
async def cmd_block_user(message: Message):
    """Заблокувати користувача за ID (тільки для власника бота). Використання: /block 123456789"""
    if message.from_user is None or message.from_user.id != BOT_OWNER_ID:
        return
    text = (message.text or "").strip()
    parts = text.split()
    if len(parts) < 2:
        await message.answer("Використання: <code>/block &lt;user_id&gt;</code>\nПриклад: /block 123456789", parse_mode="html")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("Невірний ID. Вкажіть числовий Telegram ID.")
        return
    if target_id == BOT_OWNER_ID:
        await message.answer("Не можна заблокувати власника бота.")
        return
    if await block_user_async(target_id):
        await message.answer(f"Користувача з ID <code>{target_id}</code> заблоковано. Він не зможе користуватися ботом.", parse_mode="html")
    else:
        await message.answer("Помилка при блокуванні (БД або вже заблоковано).")


@router_start.message(Command("unblock"), F.chat.type == "private")
async def cmd_unblock_user(message: Message):
    """Розблокувати користувача за ID (тільки для власника бота). Використання: /unblock 123456789"""
    if message.from_user is None or message.from_user.id != BOT_OWNER_ID:
        return
    text = (message.text or "").strip()
    parts = text.split()
    if len(parts) < 2:
        await message.answer("Використання: <code>/unblock &lt;user_id&gt;</code>\nПриклад: /unblock 123456789", parse_mode="html")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("Невірний ID. Вкажіть числовий Telegram ID.")
        return
    if await unblock_user_async(target_id):
        await message.answer(f"Користувача з ID <code>{target_id}</code> розблоковано.", parse_mode="html")
    else:
        await message.answer("Помилка при розблокуванні або користувач не був заблокований.")


@router_start.message(
    Command("transfer_gold"),
    F.chat.type.in_(["group", "supergroup"]),
)
async def cmd_transfer_gold_to_founder(message: Message):
    """Перевести золоті монети засновнику групи. Тільки в чаті групи. Використання: /transfer_gold <кількість>"""
    if not message.from_user:
        return
    text = (message.text or "").strip().split()
    if len(text) < 2:
        await message.answer(
            "🪙 <b>Переказ золотих засновнику групи</b>\n\n"
            "Використання: <code>/transfer_gold &lt;кількість&gt;</code>\n"
            "Приклад: <code>/transfer_gold 10</code>\n\n"
            "Після підтвердження вказана кількість золотих монет буде перерахована засновнику цієї групи.",
            parse_mode="html",
        )
        return
    try:
        amount = int(text[1])
    except ValueError:
        await message.answer("Вкажіть ціле число. Приклад: <code>/transfer_gold 10</code>", parse_mode="html")
        return
    if amount < 1:
        await message.answer("Кількість має бути не менше 1.")
        return
    chat_id = message.chat.id
    creator_id = await get_group_creator_id_async(chat_id)
    if not creator_id:
        await message.answer("У цій групі немає зареєстрованого засновника (створювача групи).")
        return
    if creator_id == message.from_user.id:
        await message.answer("Ви не можете перевести золото собі.")
        return
    row = await _db_fetchone(
        "SELECT COALESCE(donate_coins, 0) FROM users WHERE id = %s",
        (message.from_user.id,),
    )
    user_gold = int(row[0]) if row else 0
    if user_gold < amount:
        await message.answer(f"Недостатньо золотих монет. У вас: {user_gold} 🪙")
        return
    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Підтвердити",
                callback_data=f"transfer_founder_{message.from_user.id}_{amount}_{creator_id}_{message.message_id}",
            ),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="transfer_founder_cancel"),
        ],
    ])
    await message.answer(
        f"🪙 Перевести <b>{amount}</b> золотих монет засновнику цієї групи?\n\n"
        "Натисніть підтвердження, щоб виконати переказ.",
        reply_markup=confirm_keyboard,
        parse_mode="html",
    )


@router_start.callback_query(F.data == "transfer_founder_cancel")
async def transfer_founder_cancel_cb(callback: CallbackQuery):
    """Скасування переказу золота засновнику."""
    if not callback.message:
        return
    try:
        await callback.message.edit_text("❌ Переказ скасовано.")
    except TelegramBadRequest:
        pass
    await callback.answer("Скасовано")


@router_start.callback_query(F.data.startswith("transfer_founder_"))
async def transfer_founder_confirm_cb(callback: CallbackQuery):
    """Підтвердження переказу золота засновнику групи."""
    if not callback.message or not callback.from_user:
        return
    data = callback.data or ""
    if data == "transfer_founder_cancel":
        return
    if not data.startswith("transfer_founder_"):
        return
    parts = data.replace("transfer_founder_", "").split("_")
    if len(parts) != 4:
        await callback.answer("Помилка формату.", show_alert=True)
        return
    try:
        user_id = int(parts[0])
        amount = int(parts[1])
        creator_id = int(parts[2])
        user_msg_id = int(parts[3])
    except ValueError:
        await callback.answer("Помилка даних.", show_alert=True)
        return
    if callback.from_user.id != user_id:
        await callback.answer("Це підтвердження тільки для того, хто ініціював переказ.", show_alert=True)
        return
    if amount < 1:
        await callback.answer("Невірна сума.", show_alert=True)
        return
    if not await deduct_user_gold_async(user_id, amount):
        await callback.answer("Недостатньо золотих монет.", show_alert=True)
        return
    await add_gold_to_user_async(creator_id, amount)
    chat_id = callback.message.chat.id if callback.message else None
    try:
        await callback.message.delete()
    except Exception:
        pass
    if chat_id:
        try:
            await callback.bot.delete_message(chat_id=chat_id, message_id=user_msg_id)
        except Exception:
            pass
    await callback.answer("Готово ✓")


async def _get_settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавіатура налаштувань: перемикач передбачень + назад."""
    enabled = await get_predictions_enabled_async(user_id)
    if enabled:
        pred_btn = InlineKeyboardButton(text="🔮 Передбачення: Увімкнено ✓", callback_data="settings_prediction_off")
    else:
        pred_btn = InlineKeyboardButton(text="🔮 Передбачення: Вимкнено", callback_data="settings_prediction_on")
    return InlineKeyboardMarkup(inline_keyboard=[
        [pred_btn],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="start_settings_back")],
    ])


@router_start.callback_query(F.data == "start_settings")
async def start_settings_cb(callback: CallbackQuery):
    """Відкрити налаштування в ЛС."""
    if not callback.message or not callback.from_user:
        return
    if callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в особистих повідомленнях.", show_alert=True)
        return
    text = (
        "⚙️ <b>Налаштування</b> ⚙️\n\n"
        "Тут ти можеш увімкнути або вимкнути щоденні передбачення о 10:00 (Київ)."
    )
    await callback.message.edit_text(text, reply_markup=await _get_settings_keyboard(callback.from_user.id), parse_mode="html")
    await callback.answer()


@router_start.callback_query(F.data == "settings_prediction_on")
async def settings_prediction_on_cb(callback: CallbackQuery):
    """Увімкнути щоденні передбачення."""
    if not callback.message or not callback.from_user:
        return
    await set_predictions_enabled_async(callback.from_user.id, True)
    text = (
        "⚙️ <b>Налаштування</b> ⚙️\n\n"
        "Тут ти можеш увімкнути або вимкнути щоденні передбачення о 10:00 (Київ)."
    )
    try:
        await callback.message.edit_text(text, reply_markup=await _get_settings_keyboard(callback.from_user.id), parse_mode="html")
    except TelegramBadRequest:
        pass
    await callback.answer("Передбачення увімкнено ✓", show_alert=False)


@router_start.callback_query(F.data == "settings_prediction_off")
async def settings_prediction_off_cb(callback: CallbackQuery):
    """Вимкнути щоденні передбачення."""
    if not callback.message or not callback.from_user:
        return
    await set_predictions_enabled_async(callback.from_user.id, False)
    text = (
        "⚙️ <b>Налаштування</b> ⚙️\n\n"
        "Тут ти можеш увімкнути або вимкнути щоденні передбачення о 10:00 (Київ)."
    )
    try:
        await callback.message.edit_text(text, reply_markup=await _get_settings_keyboard(callback.from_user.id), parse_mode="html")
    except TelegramBadRequest:
        pass
    await callback.answer("Передбачення вимкнено", show_alert=False)


@router_start.callback_query(F.data == "start_settings_back")
async def start_settings_back_cb(callback: CallbackQuery):
    """Повернутися з налаштувань до головного меню."""
    if not callback.message or not callback.from_user:
        return
    if callback.message.chat.type != "private":
        await callback.answer()
        return
    text = (
        "<b>Ласкаво просимо до штабу Галицької Мафії!</b> 🕵️‍♂️🏙️\n\n"
        "Ми розширюємо межі гри.\n"
        "Тепер ти не просто гравець - ти дослідник великого всесвіту.\n\n"
        "Що на тебе чекає?\n\n"
        "1️⃣ <b>Ексклюзивний контент:</b> Виконуй завдання та отримуй рідкісні карти.\n"
        "2️⃣ <b>Колекціонування:</b> Збери повний набір героїв Галицької Мафії.\n"
        "3️⃣ <b>Лор гри:</b> Кожна карта відкриває доступ до унікальної історії персонажа.\n\n"
        "Збери їх усіх та дізнайся, що приховує місто після заходу сонця! 🌑"
    )
    keyboard_main = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Розпочати перше завдання", callback_data="start_quest")],
        [InlineKeyboardButton(text="📜 Про всесвіт гри", callback_data="start_lore")],
        [InlineKeyboardButton(text="⚙️ Налаштування", callback_data="start_settings")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=keyboard_main, parse_mode="html")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router_start.callback_query(F.data == "start_story_yes")
async def start_story_yes_cb(callback: CallbackQuery):
    """Так — пояснюємо: сюжет відкривається через досягнення, через 1–3 дні прийде повідомлення."""
    if not callback.message or not callback.from_user:
        return
    if cursor is None or conn is None:
        await callback.answer("Помилка сервісу.", show_alert=True)
        return
    try:
        if await _db_fetchone(
            "SELECT sc.id FROM story_cards sc JOIN user_story_cards usc ON usc.card_id = sc.id "
            "WHERE usc.user_id = %s AND sc.card_order = 0",
            (callback.from_user.id,),
        ):
            await callback.answer("Сюжет вже відкрито. Дивись: /story", show_alert=True)
            return
        keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="start_settings_back")],
        ])
        await callback.message.edit_text(
            "📖 <b>Як відкрити сюжет</b>\n\n"
            "Грай у мафію в групах і виконуй досягнення.\n\n"
            "Прогрес по досягненнях: /achievements",
            parse_mode="html",
            reply_markup=keyboard_back,
        )
        await callback.answer()
    except Exception:
        await callback.answer("Помилка.", show_alert=True)
    return


@router_start.callback_query(F.data == "start_story_no")
async def start_story_no_cb(callback: CallbackQuery):
    """Ні — коротке повідомлення."""
    if callback.message:
        keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="start_settings_back")],
        ])
        await callback.message.edit_text(
            "Добре. Коли захочете — напишіть /story.",
            reply_markup=keyboard_back,
        )
    await callback.answer()


@router_start.callback_query(F.data == "start_quest")
async def start_quest_cb(callback: CallbackQuery):
    """Розпочати перше завдання — питаємо «поринути» або показуємо сюжет."""
    if not callback.message or not callback.from_user:
        return
    user_id = callback.from_user.id
    if cursor and conn:
        try:
            if await _db_fetchone(
                "SELECT sc.id FROM story_cards sc JOIN user_story_cards usc ON usc.card_id = sc.id "
                "WHERE usc.user_id = %s AND sc.card_order = 0",
                (user_id,),
            ):
                await callback.answer("Перше завдання вже розпочато. Дивись сюжет: /story", show_alert=True)
                return
            keyboard_story = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Так", callback_data="start_story_yes")],
                [InlineKeyboardButton(text="Ні", callback_data="start_story_no")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="start_settings_back")],
            ])
            await callback.message.edit_text(
                "Чи хочете ви поринути в світ мафії?",
                reply_markup=keyboard_story,
            )
        except Exception:
            keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="start_settings_back")],
            ])
            await callback.message.edit_text("Напиши /story, щоб переглянути сюжет.", reply_markup=keyboard_back)
    else:
        keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="start_settings_back")],
        ])
        await callback.message.edit_text("Напиши /story для сюжету та завдань.", reply_markup=keyboard_back)
    await callback.answer()


@router_start.callback_query(F.data == "start_collection")
async def start_collection_cb(callback: CallbackQuery):
    """Моя колекція — показуємо відкриту сюжетку або підказку."""
    if not callback.message:
        return
    if cursor and conn:
        try:
            user_id = callback.from_user.id if callback.from_user else 0
            ensure_achievements_sync()  # оновлює синхронізацію і видаляє застарілі картки
            rows = _filter_obsolete_cards(await _db_fetchall(
                "SELECT sc.card_order, sc.title_uk FROM story_cards sc "
                "JOIN user_story_cards usc ON usc.card_id = sc.id WHERE usc.user_id = %s ORDER BY sc.card_order",
                (user_id,),
            ))
            
            # Клавіатура з кнопкою "Назад"
            keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="start_settings_back")]
            ])
            
            if not rows:
                await callback.message.edit_text(
                    "🗃 <b>Моя колекція</b>\n\n"
                    "Сюжет поки не відкрито. Натисни «Розпочати перше завдання» в /start.\n\n"
                    "Напиши /story після відкриття.",
                    parse_mode="html",
                    reply_markup=keyboard_back,
                )
            else:
                lines = [f"📌 {title}" for _order, title in rows]
                await callback.message.edit_text(
                    f"🗃 <b>Моя колекція</b>\n\n" + "\n\n".join(lines) + "\n\nНапиши /story, щоб перечитати.",
                    parse_mode="html",
                    reply_markup=keyboard_back,
                )
        except Exception:
            keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="start_settings_back")]
            ])
            await callback.message.edit_text("Напиши /story, щоб переглянути сюжет.", reply_markup=keyboard_back)
    else:
        keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="start_settings_back")]
        ])
        await callback.message.edit_text("Напиши /story для сюжету.", reply_markup=keyboard_back)
    await callback.answer()


def _cleanup_unused_story_cards():
    """Legacy maintenance hook; cleanup is handled elsewhere."""
    return


LORE_TEXT = (
    "📜 <b>Про всесвіт гри: Галицька Мафія</b>\n\n"
    "Галицька мафія - світ, який не мав би існувати в наших реаліях, та попри це, він існує. "
    "Чи, можливо, правильніше сказати - існував?\n\n"
    "Галичина 1930-тих. Пацифікація розриває села, польські чоботи важко топчуть бруківку Львова, а в повітрі пахне не лише гіркою кавою, а й липким страхом та дешевим порохом. "
    "Це була територія без майбутнього, затиснута між кривавим молотом Совітів та сталевим ковадлом Рейху. "
    "Земля, де кожен чекав на неминучий кінець.\n\n"
    "Але історія зробила крутий, неможливий поворот у порту Гданська, коли з палуби корабля на берег зійшов чоловік у фетровому капелюсі з італійським акцентом та важким поглядом людини, що бачила пекло.\n\n"
    "Аль Капоне привіз сюди не надію - він привіз силу.\n\n"
    "Він побачив те, чого не бачили інші: під брудом і злиднями Борислава пульсувало «чорне золото», а в серцях покинутих напризволяще батярів горів вогонь, якому потрібен був лише лідер.\n\n"
    "Тепер нафта тече впереміш із кров'ю, а Tommy Gun звучить голосніше за церковні дзвони.\n\n"
    "У цьому світі немає святих.\n\n"
    "Тут є тільки Сім'я, твій револьвер і місто, яке ніколи не прощає помилок."
)


@router_start.callback_query(F.data == "start_lore")
async def start_lore_cb(callback: CallbackQuery):
    """Про всесвіт гри: Галицька Мафія."""
    if not callback.message:
        return
    keyboard_back = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="start_settings_back")],
    ])
    await callback.message.edit_text(LORE_TEXT, parse_mode="html", reply_markup=keyboard_back)
    await callback.answer()


@router_start.message(Command("id"))
async def id_cmd(message: Message):
    """Show chat/user ID"""
    if message.chat.type == "private":
        await message.answer(
            f"🆔 <b>Твій Telegram ID</b> 🆔\n\n"
            f"📋 <b>ID:</b> <code>{message.chat.id}</code>\n\n"
            f"💡 <i>Використовуй цей ID для реєстрації груп та інших налаштувань.</i>",
            parse_mode="html"
        )
    if message.chat.type in ["supergroup", "group"]:
        await message.answer(
            f"🆔 <b>ID цього чату</b> 🆔\n\n"
            f"📁 <b>Назва:</b> {message.chat.title}\n"
            f"🆔 <b>ID:</b> <code>{message.chat.id}</code>\n\n"
            f"💡 <i>Використовуй цей ID для реєстрації групи в <code>/construct_event</code></i>",
            parse_mode="html"
        )


@router_start.message(Command("help"))
async def help_cmd(message: Message):
    """Help command handler"""
    from aiogram.enums import ChatMemberStatus
    
    # Перевіряємо, чи користувач є власником/адміном якоїсь групи
    is_owner = False
    is_admin = False
    
    # Головний власник бота завжди має права власника
    if message.from_user.id == BOT_OWNER_ID:
        is_owner = True
    else:
        try:
            # Перевіряємо в БД
            creator_result = await _db_fetchone(
                "SELECT creator_id FROM admin_panel WHERE creator_id = %s",
                (message.from_user.id,),
            )
            if creator_result:
                is_owner = True
            
            # Якщо це група, перевіряємо статус в Telegram
            if message.chat.type in ["supergroup", "group"]:
                try:
                    chat_member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
                    if chat_member.status == ChatMemberStatus.CREATOR:
                        is_owner = True
                    elif chat_member.status == ChatMemberStatus.ADMINISTRATOR:
                        is_admin = True
                except:
                    pass
        except:
            pass
    
    # Базові команди для всіх
    help_text = (
        "📖 <b>Допомога</b> 📖\n\n"
        ""
        "🎮 <b>Основні команди:</b>\n\n"
        "<code>/start</code> - Початок роботи з ботом\n"
        "<code>/play</code> - Запустити гру в Mafia\n"
        "<code>/start_game</code> - Запустити гру одразу (без очікування)\n"
        "<code>/leave</code> або <code>/leave_game</code> - Покинути гру\n"
        "<code>/carry_on</code> - Продовжити реєстрацію (додати секунди до таймера)\n"
        "<code>/shop</code> - Магазин підписок\n"
        "<code>/buff_shop</code> - Магазин бафів\n"
        "<code>/marigolds</code> - Купити або подарувати чорнобривці 🌼\n"
        "<code>/my_subscription</code> - Перевірити підписку\n"
        "<code>/id</code> - Дізнатися ID чату/користувача\n"
        "<code>/promocode</code> - Ввести промокод\n\n"
    )
    
    # Додаткові команди для власників/адмінів
    if is_owner or is_admin:
        help_text += (
            "👑 <b>Команди для власників/адміністраторів:</b>\n\n"
            "<code>/construct_event</code> - Налаштувати ролі\n"
            "<code>/set_registration_time</code> - Встановити час реєстрації для групи\n"
            "   Приклад: <code>/set_registration_time 120</code> (встановити 120 секунд)\n\n"
        )
    
    help_text += (
        "⚠️ <b>Відповідальність:</b>\n\n"
        "За будь-яку інформацію, яку надіслав бот, відповідальність несе <b>власник чату</b>, якщо це не реклама.\n\n"
        "💡 <i>Маєш питання? Звертайся до власника чату або скористайся тех. підтримкою нижче.</i>"
    )
    
    if message.chat.type == "private":
        keyboard_help = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛠 Тех. Підтримка", callback_data="support_main")],
        ])
        await message.answer(help_text, reply_markup=keyboard_help, parse_mode="html")
    else:
        await message.answer(help_text, parse_mode="html")


async def _get_profile_content_async(user_id: int, first_name: str = None, username: str = None):
    """Повертає (текст профілю, клавіатура) для показу профілю гравця."""
    result = await _db_fetchone("""
    SELECT tg_name, link, balance, COALESCE(donate_coins, 0), COALESCE(marigolds, 0), killed, cured, votes
    FROM users
    WHERE id = %s
    """, (user_id,))
    if not result:
        balance = 0
        donate_coins = 0
        marigolds = 0
        killed = 0
        cured = 0
        votes = 0
        name = first_name or username or "Гравець"
    else:
        tg_name, link, balance, donate_coins, marigolds, killed, cured, votes = result
        balance = balance if balance is not None else 0
        donate_coins = donate_coins if donate_coins is not None else 0
        marigolds = marigolds if marigolds is not None else 0
        killed = killed if killed is not None else 0
        cured = cured if cured is not None else 0
        votes = votes if votes is not None else 0
        name = tg_name or first_name or "Гравець"
    
    profile_text = (
        "👤  Профіль гравця  👤\n\n"
        f"💼 Ім'я: {name}\n"
        f"💰 Злоті: {balance}\n"
        f"🪙 Золоті монети: {donate_coins}\n"
        f"🌼 Чорнобривці: {marigolds}\n\n"
    )
    
    profile_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍️ Крамниця", callback_data="shop_main")],
        [InlineKeyboardButton(text="📦 Мої бафи", callback_data="buffshop_owned")],
        [InlineKeyboardButton(text="🪙 Перевести золоті на підписку", callback_data="transfer_gold_start")],
    ])
    
    return profile_text, profile_keyboard

@router_start.callback_query(F.data == "shop_main")
async def shop_main_cb(callback: CallbackQuery):
    """Головне меню крамниці"""
    shop_text = (
        "🛍️ <b>Крамниця</b> 🛍️\n\n"
        "📌 Оберіть розділ:\n\n"
        "1️⃣ Підписки - отримайте доступ до преміум функцій\n"
        "2️⃣ Бафи - тимчасові покращення для гри\n"
        "3️⃣ Чорнобривці - квіти-подарунки для близьких"
    )
    
    shop_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Підписки", callback_data="shop_subscriptions")],
        [InlineKeyboardButton(text="⚡ Бафи", callback_data="buff_shop")],
        [InlineKeyboardButton(text="🌼 Чорнобривці", callback_data="marigolds_shop")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buffshop_back_to_profile")]
    ])
    
    await callback.message.edit_text(shop_text, reply_markup=shop_keyboard, parse_mode="html")
    await callback.answer()

@router_start.message(Command("profile"))
async def profile_cmd(message: Message):
    """Profile command handler - show user profile with balance and Мої бафи"""
    if message.chat.type != "private":
        await message.answer(
            "👤 <b>Профіль</b> 👤\n\n"
            "💡 <i>Ця команда доступна тільки в особистих повідомленнях з ботом.</i>\n\n"
            "📩 Напиши мені: @sicilian_mafia_bot",
            parse_mode="html"
        )
        return
    await add_user_to_db(message=message)
    profile_text, profile_keyboard = await _get_profile_content_async(
        message.from_user.id,
        first_name=message.from_user.first_name,
        username=message.from_user.username
    )
    await message.answer(profile_text, reply_markup=profile_keyboard, parse_mode="html")


@router_start.callback_query(F.data == "buffshop_back_to_profile")
async def profile_back_from_buffs(callback: CallbackQuery):
    """Повернення з «Мої бафи» на профіль."""
    if callback.message.chat.type != "private":
        await callback.answer("Доступно тільки в приватному чаті.", show_alert=True)
        return
    profile_text, profile_keyboard = await _get_profile_content_async(
        callback.from_user.id,
        first_name=callback.from_user.first_name,
        username=callback.from_user.username
    )
    try:
        await callback.message.edit_text(
            profile_text,
            reply_markup=profile_keyboard,
            parse_mode="html"
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await callback.answer()


@router_start.callback_query(F.data == "transfer_gold_start")
async def transfer_gold_start_cb(callback: CallbackQuery):
    """Вибір суми переказу золотих монет на підписку."""
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer()
        return
    row = await _db_fetchone(
        "SELECT COALESCE(donate_coins, 0) FROM users WHERE id = %s",
        (callback.from_user.id,),
    )
    gold = int(row[0]) if row else 0
    if gold < 5:
        await callback.answer("У вас менше 5 золотих монет. Переказ недоступний.", show_alert=True)
        return
    text = (
        "🪙 <b>Перевести золоті монети на підписку</b>\n\n"
        f"У вас: <b>{gold}</b> 🪙\n\n"
        "Оберіть суму для переказу на рахунок бота (підтримка підписок):"
    )
    amounts = [5, 10, 25, 50, 100]
    buttons = [
        [InlineKeyboardButton(text=f"🪙 {a}", callback_data=f"transfer_gold_{a}")]
        for a in amounts
        if a <= gold
    ]
    if not buttons:
        await callback.answer("Недостатньо золотих монет.", show_alert=True)
        return
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="buffshop_back_to_profile")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="html")
    await callback.answer()


@router_start.callback_query(F.data.startswith("transfer_gold_"))
async def transfer_gold_confirm_cb(callback: CallbackQuery):
    """Виконання переказу золотих на фонд підписок."""
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer()
        return
    data = callback.data or ""
    if not data.startswith("transfer_gold_"):
        await callback.answer()
        return
    try:
        amount = int(data.replace("transfer_gold_", ""))
    except ValueError:
        await callback.answer()
        return
    if amount < 1:
        await callback.answer()
        return
    user_id = callback.from_user.id
    if not await deduct_user_gold_async(user_id, amount):
        await callback.answer("Недостатньо золотих монет або помилка.", show_alert=True)
        return
    add_gold_to_subscription_fund(amount)
    await callback.message.edit_text(
        f"✅ Дякуємо! Ви перевели <b>{amount}</b> 🪙 на підтримку підписок.\n\n"
        "Ваш внесок допоможе розвивати бота.",
        parse_mode="html",
    )
    await callback.answer("Переказ виконано ✓")

