"""Усі тексти бота. Українською, у стилі «Мафія: Хутір»."""

from __future__ import annotations

from html import escape

from bot.engine.items import ITEMS
from bot.engine.roles import ROLES, TEAM_TITLES, Team

GAME_NAME = "Мафія: Хутір"
SHAGY = "🪙"
CHERV = "💎"


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{escape(name)}</a>'


def fmt_seconds(s: int) -> str:
    if s >= 60 and s % 60 == 0:
        return f"{s // 60} хв"
    if s >= 60:
        return f"{s // 60} хв {s % 60} с"
    return f"{s} с"


# ---------- старт / допомога ----------

START = (
    f"🌻 <b>{GAME_NAME}</b>\n\n"
    "На тихому хуторі завелася нечисть. Вдень усі — добрі сусіди, "
    "а вночі хтось не повертається з вечорниць…\n\n"
    "➕ Додай мене в групу та дай права адміністратора, щоб я міг вести гру.\n"
    "🎲 У групі напиши /game — і збирай громаду.\n\n"
    "👤 /profile — твоя хата і гаманець\n"
    "🛒 /shop — ярмарок предметів\n"
    "🎁 /daily — щоденний гостинець\n"
    "👑 /vip — VIP і червінці\n"
    "📜 /rules — правила та ролі"
)

RULES_HEAD = (
    f"📜 <b>Правила «{GAME_NAME}»</b>\n\n"
    "🌙 <b>Ніч.</b> Кожен, хто має нічну справу, отримує кнопки в особисті. "
    "Нечисть обирає жертву, знахарка лікує, характерник перевіряє.\n"
    "☀️ <b>День.</b> Громада дізнається, хто не дожив до ранку, і обговорює.\n"
    "⚖️ <b>Голосування.</b> Кожен живий голосує в особистих. Потім громада "
    "підтверджує страту 👍/👎.\n\n"
    "🏆 <b>Перемога.</b> Громада — коли вся нечисть і вовкулака мертві. "
    "Нечисть — коли її не менше, ніж решти. Вовкулака — коли лишиться сам на сам "
    "з кимось. Іван-дурень — якщо його стратять.\n\n"
    "<b>Ролі:</b>\n"
)

ROLE_DESCRIPTIONS = {
    "selianyn": "Звичайний селянин. Вночі спить, вдень шукає нечисть і голосує.",
    "znaharka": "Щоночі лікує одного гравця від смерті. Себе — лише раз за гру. Одну людину двічі поспіль не можна.",
    "harakternyk": "Щоночі перевіряє, чи гравець із Громади. Один раз за гру може замість цього вдарити шаблею.",
    "kum": "Везунчик: переживає перший напад уночі.",
    "storozh": "Стереже чиюсь хату і зранку знає, хто туди приходив.",
    "kobzar": "Співає про двох гравців і дізнається, чи вони з одного боку.",
    "otaman": "Його голос на денному голосуванні важить подвійно.",
    "vidma": "Ватажок нечисті. Її слово вирішує, кого забрати вночі.",
    "upyr": "Нечисть. Голосує за жертву. Якщо Відьма загине — стає ватажком.",
    "mavka": "Нечисть. Заманює гравця на ніч — його дія не спрацьовує.",
    "vovkulaka": "Одинак. Щоночі вбиває і хоче лишитися останнім.",
    "duren": "Одинак. Мріє, щоб громада його стратила — тоді він переможе.",
}


def rules() -> str:
    lines = [RULES_HEAD]
    for team in (Team.VILLAGE, Team.EVIL, Team.WOLF, Team.FOOL):
        lines.append(f"\n<b>{TEAM_TITLES[team]}</b>")
        for r in ROLES.values():
            if r.team == team:
                lines.append(f"{r.title} — {ROLE_DESCRIPTIONS[r.key]}")
    lines.append("\n<b>Предмети</b> купуються в /shop і самі беруться в гру:")
    for i in ITEMS.values():
        lines.append(f"{i.title} — {i.description}")
    return "\n".join(lines)


# ---------- лобі ----------

def lobby(players: list[tuple[int, str]], seconds: int, min_players: int) -> str:
    lines = [
        "🌾 <b>Збирається громада!</b>",
        f"Реєстрація триває ще ~{fmt_seconds(seconds)}. Потрібно щонайменше {min_players}.",
        "",
        f"<b>Записались ({len(players)}):</b>",
    ]
    lines += [f"{n}. {mention(uid, name)}" for n, (uid, name) in enumerate(players, start=1)] or ["поки нікого…"]
    return "\n".join(lines)


JOIN_BUTTON = "🙋 Долучитися"
LOBBY_REMINDER = "⏳ До початку гри лишилось {left}! Хто ще не записався — тисни «Долучитися»."
LOBBY_NOT_ENOUGH = "😴 Не зібралось навіть {min} людей. Гру скасовано — хутір лягає спати."
LOBBY_ALREADY = "Гра в цьому чаті вже йде. Дочекайся наступної."
JOINED_PM = "✅ Тебе записано на гру в чаті <b>{chat}</b>. Чекай на свою роль!"
JOIN_ALREADY_HERE = "Ти вже записаний на цю гру."
JOIN_IN_OTHER = "Ти вже граєш в іншому чаті. Одна гра за раз!"
JOIN_CLOSED = "Реєстрацію вже закрито."
JOIN_FULL = "Громада переповнена — більше {max} гравців не можна."
LEFT_LOBBY = "🚶 {name} іде додому — не цього разу."
NOT_IN_LOBBY = "Ти не записаний у цю гру або вона вже почалась."
GROUP_ONLY = "Ця команда працює лише в групі."
PRIVATE_ONLY = "Ця команда працює лише в особистих повідомленнях з ботом."
ADMIN_ONLY = "Це може зробити лише адміністратор чату."
NO_GAME = "Зараз у чаті немає гри."
FORCE_START_FEW = "Замало гравців: потрібно щонайменше {min}."
GAME_STOPPED = "🛑 Гру зупинено адміністратором."
GAME_RESUMED = "🔄 Бот перезапустився. Продовжуємо гру з початку поточної фази."
GAME_CRASHED = "⚠️ У грі сталася помилка, і її довелося зупинити. Предмети повернуто в інвентар."


# ---------- старт гри та ролі ----------

GAME_STARTED = (
    "🔥 <b>Гру розпочато!</b> Гравців: {n}.\n"
    "Кожен отримав свою роль в особисті. Склад хутора: {composition}"
)


def role_card(role_key: str, pocket: list[str], allies: list[str]) -> str:
    r = ROLES[role_key]
    text = [
        f"🎭 Твоя роль — <b>{r.title}</b>",
        f"Сторона: {TEAM_TITLES[r.team]}",
        "",
        ROLE_DESCRIPTIONS[role_key],
    ]
    if allies:
        text += ["", "🌑 Твоя нечиста братія: " + ", ".join(allies),
                 "Пиши мені сюди — я передам повідомлення своїм."]
    if pocket:
        text += ["", "🎒 У кишені: " + ", ".join(ITEMS[i].title for i in pocket)]
    return "\n".join(text)


# ---------- ніч ----------

def night_start(day: int, alive: list[tuple[int, str]]) -> str:
    names = "\n".join(f"{n}. {mention(u, nm)}" for n, (u, nm) in enumerate(alive, start=1))
    return (
        f"🌙 <b>Ніч {day}</b>\n"
        "Хутір засинає. Собаки гавкають, у лісі щось шарудить…\n"
        "Хто має нічні справи — перевірте особисті.\n\n"
        f"<b>Живі ({len(alive)}):</b>\n{names}"
    )


NIGHT_PROMPTS = {
    "kill": "🌑 Кого нечисть забере цієї ночі?",
    "heal": "🌿 Кого лікуватимеш цієї ночі?",
    "check": "🗡 Кого перевіриш?",
    "saber": "⚔️ Або вдарити шаблею (лише раз за гру):",
    "watch": "🏮 Чию хату стерегтимеш?",
    "compare": "🪕 Про кого співатимеш? Обери першого.",
    "compare2": "🪕 А тепер другого — поруч із {first}.",
    "lure": "🧜‍♀️ Кого заманиш до ставка?",
    "wolf": "🐺 Кого вовкулака розірве цієї ночі?",
    "pitchfork": "🔱 У тебе є вила. Кого проштрикнеш? (необов'язково)",
}

NIGHT_CHOSEN = "✅ Обрано: {target}"
NIGHT_EXPIRED = "⌛ Ніч минула, вибір не зроблено."
NIGHT_BAD_TARGET = "Цю ціль обрати не можна."
NIGHT_NOT_NOW = "Зараз не час для цього."
EVIL_VOTE_RELAY = "🌑 {actor} пропонує жертву: {target}."
EVIL_CHAT = "🌑 <b>{name}:</b> {text}"
SKIP_BUTTON = "🚫 Пропустити"


# ---------- ранок ----------

DEATH_CAUSES = {
    "evil": "нечисть забрала в темряву",
    "wolf": "не пережили зустрічі з вовкулакою",
    "saber": "впали від шаблі характерника",
    "pitchfork": "наткнулись на вила",
}


def morning(day: int, deaths: list[tuple[int, str, str, str | None]], saved_count: int) -> str:
    """deaths: (uid, name, cause, role_title або None, якщо ролі приховано)."""
    lines = [f"☀️ <b>Ранок {day}</b>. Півні проспівали, хутір прокидається…", ""]
    if not deaths:
        lines.append("🕊 Цієї ночі всі живі! Нечисть лишилась голодною.")
    for uid, name, cause, role_title in deaths:
        role_part = f" Роль: {role_title}." if role_title else ""
        lines.append(f"⚰️ {mention(uid, name)} — {DEATH_CAUSES.get(cause, 'не дожили до ранку')}.{role_part}")
    if saved_count:
        lines.append(f"\n✨ Когось цієї ночі дивом врятували ({saved_count}).")
    return "\n".join(lines)


YOU_DIED = "⚰️ Тебе вбили цієї ночі. Можеш спостерігати, але мовчи — мертві не говорять."
YOU_SAVED = {
    "heal": "🌿 На тебе напали, але знахарка встигла тебе вилікувати!",
    "obereg": "🧿 На тебе напали, але оберіг захистив! Він розсипався на порох.",
    "kum": "🍀 На тебе напали, але ти, кум, як завжди, викрутився!",
}
YOU_LURED = "🧜‍♀️ Мавка заманила тебе до ставка — цієї ночі ти нічого не встиг."
GARLIC_WORKED = "🧄 Мавка кликала тебе до ставка, але від часнику аж скривилась!"
CHECK_RESULT = {True: "🗡 {target} — з 🌾 Громади.", False: "🗡 {target} — НЕ з Громади!"}
COMPARE_RESULT = {True: "🪕 {a} і {b} — з одного боку.", False: "🪕 {a} і {b} — з різних боків."}
WATCH_RESULT = "🏮 До хати {target} цієї ночі приходили: {visitors}"
WATCH_NOBODY = "🏮 До хати {target} цієї ночі ніхто не приходив."
CANDLE_RESULT = "🕯 Свічка догоріла. До тебе вночі приходили: {visitors}"


# ---------- день і голосування ----------

DAY_START = "🗣 Час обговорення: {time}. Хто підозрілий? Хто вночі не спав?"
VOTE_START = "⚖️ <b>Голосування!</b> Кожен живий голосує в особистих повідомленнях ({time})."
VOTE_PROMPT = "⚖️ Кого громада має стратити?"
HONEY_BUTTON = "🍯 Мед: мій голос ×2"
HONEY_USED = "🍯 Мед з'їдено — твій голос сьогодні важить більше!"
HONEY_FAIL = "Меду немає або його вже з'їдено."
VOTE_CAST = "✅ Твій голос: {target}"
VOTE_SKIP_CAST = "✅ Твій голос: нікого не страчувати."
VOTE_ANNOUNCE = "🗳 {voter} → {target}"
VOTE_ANNOUNCE_SKIP = "🗳 {voter} → 🚫 нікого не страчувати"
VOTE_ANNOUNCE_SECRET = "🗳 Хтось проголосував. Голосів: {count}/{total}"
VOTE_EXPIRED = "⌛ Голосування завершилось."
VOTE_NOBODY = "🤷 Громада не дійшла згоди — сьогодні нікого не стратять."


def vote_results(lines: list[str]) -> str:
    return "📊 <b>Підсумки голосування:</b>\n" + ("\n".join(lines) if lines else "ніхто не голосував")


CONFIRM_ASK = "🪢 Громада вирішує долю: {name}. Стратити?\n👍 {yes}  |  👎 {no}"
CONFIRM_YES = "👍 Так"
CONFIRM_NO = "👎 Ні"
CONFIRM_NOT_ALLOWED = "Голосувати можуть лише живі гравці, крім самого підсудного."
CONFIRM_THANKS = "Голос враховано."
PARDON = "🙏 Громада змилувалась: {name} лишається жити. ({yes} 👍 / {no} 👎)"
LYNCHED = "🪢 Громада винесла вирок: {name} страчено.{role}"
HORSESHOE_SAVED = "🐴 Мотузка обірвалась! У кишені знайшлась підкова на щастя: {name} вціліли."
FOOL_WON = "🤪 Та це ж був Іван-дурень! Він хотів цього — і переміг. Гра триває."


# ---------- кінець гри ----------

WINNER_TITLES = {
    Team.VILLAGE: "🌾 Перемогла Громада! Нечисть вигнали з хутора.",
    Team.EVIL: "🌑 Перемогла Нечисть! Хутір тепер належить темряві.",
    Team.WOLF: "🐺 Переміг Вовкулака! Лишився лише він — і місяць.",
    "draw": "🕯 На хуторі не лишилось нікого… Нічия.",
}


def game_over(winner: str, lines: list[str], days: int) -> str:
    return (
        f"🏁 <b>Гру завершено</b> (днів: {days})\n\n"
        f"{WINNER_TITLES.get(winner, winner)}\n\n"
        "<b>Хто ким був:</b>\n" + "\n".join(lines)
    )


REWARD_PM = "🏁 Гра завершилась. {result} Нагорода: +{amount} {shagy}."
RESULT_WIN = "🏆 Перемога!"
RESULT_LOSE = "Цього разу не пощастило."


# ---------- профіль ----------

def profile(name: str, shagy: int, cherv: int, vip_until: str | None, games: int, wins: int,
            inventory: list[str]) -> str:
    rate = f"{round(wins * 100 / games)}%" if games else "—"
    lines = [
        f"🏡 <b>Хата: {escape(name)}</b>" + (" 👑" if vip_until else ""),
        "",
        f"{SHAGY} Шаги: <b>{shagy}</b>",
        f"{CHERV} Червінці: <b>{cherv}</b>",
        f"👑 VIP до: {vip_until}" if vip_until else "👑 VIP: немає (/vip)",
        "",
        f"🎲 Ігор: {games} · 🏆 Перемог: {wins} ({rate})",
        "",
        "🎒 <b>Скриня:</b> " + (", ".join(inventory) if inventory else "порожньо — зазирни на /shop"),
    ]
    return "\n".join(lines)


DAILY_OK = "🎁 Кума передала гостинця: +{amount} {shagy}! Приходь завтра."
DAILY_WAIT = "⏳ Гостинець уже отримано. Наступний — через {left}."
TOP_HEAD = "🏆 <b>Найкращі гравці цього хутора</b>\n"
TOP_EMPTY = "Тут ще ніхто не грав. Почніть з /game!"
PROMO_USAGE = "Напиши так: <code>/promo КОД</code>"
PROMO_ERRORS = {
    "not_found": "❌ Такого промокоду немає.",
    "used": "Ти вже активував цей промокод.",
    "exhausted": "😔 Промокод уже вичерпано.",
}


def promo_ok(shagy: int, cherv: int, vip_days: int) -> str:
    parts = []
    if shagy:
        parts.append(f"+{shagy} {SHAGY}")
    if cherv:
        parts.append(f"+{cherv} {CHERV}")
    if vip_days:
        parts.append(f"👑 VIP +{vip_days} дн.")
    return "🎉 Промокод активовано: " + (", ".join(parts) or "нічого 🙃")


# ---------- ярмарок ----------

def shop(balance: int, inventory: dict[str, int], slots: int) -> str:
    lines = [
        "🛒 <b>Ярмарок</b>",
        f"Твій гаманець: <b>{balance}</b> {SHAGY}",
        f"На гру береш із собою до {slots} різних предметів (VIP — більше).",
        "",
    ]
    for item in ITEMS.values():
        have = inventory.get(item.key, 0)
        own = f" · у скрині: {have}" if have else ""
        lines.append(f"{item.title} — <b>{item.price}</b> {SHAGY}{own}\n<i>{item.description}</i>")
    return "\n".join(lines)


SHOP_BOUGHT = "✅ Куплено: {item}. Залишок: {balance} {shagy}"
SHOP_NO_MONEY = "Не вистачає шагів. Зіграй ще кілька ігор або візьми /daily."


# ---------- VIP і червінці ----------

def vip_menu(cherv: int, vip_until: str | None, vip_price: int, rate: int) -> str:
    status = f"👑 У тебе VIP до <b>{vip_until}</b>." if vip_until else "👑 VIP ще немає."
    return (
        "👑 <b>VIP на хуторі</b>\n\n"
        "• ×1.5 шагів за кожну гру\n"
        "• щоденний гостинець 120 🪙 замість 50\n"
        "• +1 предмет у кишеню на гру\n"
        "• корона 👑 у профілі\n\n"
        f"{status}\n"
        f"{CHERV} Червінців у гаманці: <b>{cherv}</b>\n\n"
        f"VIP можна купити за зірки ⭐ або за {vip_price} {CHERV}.\n"
        f"Червінці можна обміняти на шаги: 1 {CHERV} = {rate} {SHAGY}."
    )


VIP_BOUGHT = "👑 VIP активовано до {until}! Дякуємо, що підтримуєш хутір."
VIP_NO_CHERV = "Не вистачає червінців."
CHERV_BOUGHT = "💎 Зараховано {amount} червінців. Дякуємо за підтримку!"
EXCHANGED = "🔄 Обміняно {cherv} {cherv_icon} на {shagy} {shagy_icon}."
PAYMENT_UNKNOWN = "Невідомий товар. Спробуй ще раз через /vip."
