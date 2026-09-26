"""Усі тексти бота. Українською, у стилі «Мафія: Хутір»."""

from __future__ import annotations

from html import escape

from bot.economy import DAILY, DAILY_VIP
from bot.engine.items import ITEMS
from bot.engine.models import MIN_PLAYERS
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


def quote(text: str, expandable: bool = False) -> str:
    tag = "blockquote expandable" if expandable else "blockquote"
    return f"<{tag}>{text}</blockquote>"


def bar(value: int, total: int, width: int = 10) -> str:
    filled = round(width * min(value, total) / total) if total > 0 else 0
    return "▰" * filled + "▱" * (width - filled)


# ---------- опис бота (видно до натискання «Почати») ----------

BOT_SHORT_DESCRIPTION = (
    "🌻 Мафія з українським колоритом: Громада проти Нечисті. Додай у групу й напиши /game!"
)
BOT_DESCRIPTION = (
    "🌻 Мафія: Хутір\n\n"
    "На тихому хуторі завелася нечисть. Вдень усі — добрі сусіди, а вночі хтось не повертається з вечорниць…\n\n"
    "🎭 12 ролей: Відьма, Мавка, Характерник, Знахарка, Вовкулака, Іван-дурень…\n"
    "🛒 Чарівні предмети: оберіг, часник, підкова, вила\n"
    "🏆 Звання, рейтинг чату, щоденні гостинці\n\n"
    "Додай мене в групу, напиши /game — і я буду ведучим."
)


# ---------- старт / допомога ----------

START = (
    f"🌻 <b>{GAME_NAME}</b>\n"
    "<i>мафія з українським колоритом</i>\n\n"
    + quote("На тихому хуторі завелася нечисть. Вдень усі — добрі сусіди, "
            "а вночі хтось не повертається з вечорниць…")
    + "\n\n<b>Як почати</b>\n"
    "1️⃣ Додай мене в групу кнопкою нижче\n"
    "2️⃣ Напиши там /game\n"
    f"3️⃣ Збери щонайменше {MIN_PLAYERS} сусідів — і настане ніч 🌙"
)
MENU_BACK = "⬅️ Меню"
MENU_BUTTONS = {
    "profile": "🏡 Моя хата",
    "shop": "🛒 Ярмарок",
    "daily": "🎁 Гостинець",
    "vip": "👑 VIP",
    "rules": "📜 Правила",
}
ADD_TO_GROUP = "➕ Додати в групу"
TO_BOT_BUTTON = "📩 Перейти до бота"

RULES_HEAD = (
    f"📜 <b>Правила «{GAME_NAME}»</b>\n\n"
    + quote(
        "🌙 <b>Ніч.</b> Кожен, хто має нічну справу, отримує кнопки в особисті. "
        "Нечисть обирає жертву, знахарка лікує, характерник перевіряє.\n"
        "☀️ <b>День.</b> Громада дізнається, хто не дожив до ранку, і обговорює.\n"
        "⚖️ <b>Голосування.</b> Кожен живий голосує в особистих. Потім громада "
        "підтверджує страту 👍/👎."
    )
    + "\n\n🏆 <b>Перемога</b>\n"
    + quote(
        "🌾 Громада — коли вся нечисть і вовкулака мертві.\n"
        "🌑 Нечисть — коли її не менше, ніж решти.\n"
        "🐺 Вовкулака — коли лишиться сам на сам з кимось.\n"
        "🤪 Іван-дурень — якщо його стратять."
    )
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
    "mavka": "Нечисть. Заманює гравця на ніч — його дія не спрацьовує. Якщо лишиться сама з нечисті — вбиває.",
    "vovkulaka": "Одинак. Щоночі вбиває і хоче лишитися останнім.",
    "duren": "Одинак. Мріє, щоб громада його стратила — тоді він переможе.",
}


TEAM_GOALS = {
    Team.VILLAGE: "знайти й стратити всю нечисть і вовкулаку.",
    Team.EVIL: "забирати сусідів, доки нечисті не стане не менше, ніж решти.",
    Team.WOLF: "лишитися останнім на хуторі.",
    Team.FOOL: "переконати громаду стратити тебе.",
}


def rules() -> str:
    parts = [RULES_HEAD, "\n\n🎭 <b>Ролі</b>"]
    groups = [(TEAM_TITLES[Team.VILLAGE], {Team.VILLAGE}), (TEAM_TITLES[Team.EVIL], {Team.EVIL}),
              ("🎲 Одинаки", {Team.WOLF, Team.FOOL})]
    for title, teams in groups:
        roles = [f"<b>{r.title}</b> — {ROLE_DESCRIPTIONS[r.key]}" for r in ROLES.values() if r.team in teams]
        parts.append(f"\n<b>{title}</b>\n" + quote("\n".join(roles), expandable=len(roles) > 2))
    items = [f"<b>{i.title}</b> — {i.description}" for i in ITEMS.values()]
    parts.append("\n\n🎒 <b>Предмети</b> купуються в /shop і самі беруться в гру\n"
                 + quote("\n".join(items), expandable=True))
    return "".join(parts)


# ---------- лобі ----------

def lobby(players: list[tuple[int, str]], seconds: int, min_players: int) -> str:
    n = len(players)
    if n < min_players:
        status = f"{bar(n, min_players)}  {n}/{min_players}\nЩе потрібно: <b>{min_players - n}</b>"
    else:
        status = f"{bar(1, 1)}  {n}\n✅ Гравців достатньо — можна починати!"
    names = "\n".join(f"{i}. {mention(uid, name)}" for i, (uid, name) in enumerate(players, start=1))
    return (
        "🌾 <b>Збирається громада!</b>\n"
        f"⏳ До початку ~{fmt_seconds(seconds)}\n\n"
        f"{status}\n\n"
        f"👥 <b>Записались ({n}):</b>\n"
        + quote(names or "<i>поки нікого… будь першим!</i>")
        + "\n\nТисни «🙋 Долучитися» — роль прийде в особисті."
    )


JOIN_BUTTON = "🙋 Долучитися"
RULES_BUTTON = "📜 Правила"
LOBBY_REMINDER = "⏳ <b>Лишилось {left}!</b> Хто ще не записався — тисни «🙋 Долучитися»."
LOBBY_NOT_ENOUGH = "😴 <b>Гру скасовано.</b> Не зібралось навіть {min} людей — хутір лягає спати."
LOBBY_ALREADY = "Гра в цьому чаті вже йде. Дочекайся наступної."
JOINED_PM = "✅ Тебе записано на гру в чаті <b>{chat}</b>.\n🎭 Чекай на свою роль — вона прийде сюди."
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
GAME_STOPPED = "🛑 <b>Гру зупинено адміністратором.</b>"
GAME_RESUMED = "🔄 Бот перезапустився. Продовжуємо гру з початку поточної фази."
GAME_CRASHED = "⚠️ У грі сталася помилка, і її довелося зупинити. Предмети повернуто в інвентар."


# ---------- старт гри та ролі ----------

GAME_STARTED = (
    "🔥 <b>Гру розпочато!</b>\n\n"
    "👥 Гравців: <b>{n}</b>\n"
    "<blockquote>{composition}</blockquote>\n\n"
    "🎭 Ролі вже в особистих — перевір, хто ти цієї гри."
)


def role_card(role_key: str, pocket: list[str], allies: list[str]) -> str:
    r = ROLES[role_key]
    text = [
        f"🎭 Твоя роль — <b>{r.title}</b>",
        f"Сторона: <b>{TEAM_TITLES[r.team]}</b>",
        "",
        quote(ROLE_DESCRIPTIONS[role_key]),
        "",
        f"🎯 <b>Мета:</b> {TEAM_GOALS[r.team]}",
    ]
    if allies:
        text += ["", "🌑 <b>Твоя нечиста братія:</b>", quote("\n".join(allies)),
                 "<i>Пиши мені сюди — я передам повідомлення своїм.</i>"]
    if pocket:
        text += ["", "🎒 <b>У кишені:</b> " + ", ".join(ITEMS[i].title for i in pocket)]
    return "\n".join(text)


# ---------- ніч ----------

def night_start(day: int, alive: list[tuple[int, str]]) -> str:
    names = "\n".join(f"{n}. {mention(u, nm)}" for n, (u, nm) in enumerate(alive, start=1))
    return (
        f"🌙 <b>Ніч {day}</b>\n"
        + quote("<i>Хутір засинає. Собаки гавкають, у лісі щось шарудить…</i>")
        + "\n\nХто має нічні справи — перевірте особисті 📩\n\n"
        f"👥 <b>Живі ({len(alive)}):</b>\n" + quote(names)
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
    lines = [f"☀️ <b>Ранок {day}</b>", quote("<i>Півні проспівали, хутір прокидається…</i>"), ""]
    if not deaths:
        lines.append("🕊 <b>Цієї ночі всі живі!</b> Нечисть лишилась голодною.")
    for uid, name, cause, role_title in deaths:
        lines.append(f"⚰️ {mention(uid, name)} — {DEATH_CAUSES.get(cause, 'не дожили до ранку')}.")
        if role_title:
            lines.append(f"      <i>Роль: {role_title}</i>")
    if saved_count:
        lines.append(f"\n✨ Когось цієї ночі дивом врятували ({saved_count}).")
    return "\n".join(lines)


YOU_DIED = "⚰️ <b>Тебе вбили цієї ночі.</b>\nМожеш спостерігати, але мовчи — мертві не говорять."
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

DAY_START = "🗣 <b>Час обговорення</b> · ⏳ {time}\nХто підозрілий? Хто вночі не спав?"
VOTE_START = "⚖️ <b>Голосування!</b> · ⏳ {time}\nКожен живий голосує в особистих з ботом 📩"
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
VOTE_NOBODY = "🤷 <b>Громада не дійшла згоди</b> — сьогодні нікого не стратять."


def vote_results(rows: list[tuple[str, int]]) -> str:
    """rows: (підпис, кількість голосів), від найбільшого."""
    if not rows:
        return "📊 <b>Підсумки голосування</b>\n" + quote("<i>ніхто не голосував</i>")
    top = rows[0][1]
    lines = [f"{label} — <b>{count}</b>\n{bar(count, top, 8)}" for label, count in rows]
    return "📊 <b>Підсумки голосування</b>\n" + quote("\n".join(lines))


CONFIRM_ASK = "🪢 <b>Суд громади</b>\n\nНа лаві підсудних: {name}\nСтратити?\n\n👍 <b>{yes}</b>   ·   👎 <b>{no}</b>"
CONFIRM_YES = "👍 Так"
CONFIRM_NO = "👎 Ні"
CONFIRM_NOT_ALLOWED = "Голосувати можуть лише живі гравці, крім самого підсудного."
CONFIRM_THANKS = "Голос враховано."
PARDON = "🙏 <b>Громада змилувалась:</b> {name} лишається жити. ({yes} 👍 / {no} 👎)"
LYNCHED = "🪢 <b>Громада винесла вирок:</b> {name} страчено.{role}"
HORSESHOE_SAVED = "🐴 Мотузка обірвалась! У кишені знайшлась підкова на щастя: {name} вціліли."
FOOL_WON = "🤪 Та це ж був Іван-дурень! Він хотів цього — і переміг. Гра триває."


# ---------- кінець гри ----------

WINNER_TITLES = {
    Team.VILLAGE: "🌾 Перемогла Громада! Нечисть вигнали з хутора.",
    Team.EVIL: "🌑 Перемогла Нечисть! Хутір тепер належить темряві.",
    Team.WOLF: "🐺 Переміг Вовкулака! Лишився лише він — і місяць.",
    "draw": "🕯 На хуторі не лишилось нікого… Нічия.",
}


def game_over(winner: str, win_lines: list[str], lose_lines: list[str], days: int) -> str:
    text = (
        f"🏁 <b>Гру завершено</b> · днів: {days}\n\n"
        + quote(f"<b>{WINNER_TITLES.get(winner, winner)}</b>")
    )
    if win_lines:
        text += "\n\n🏆 <b>Переможці</b>\n" + quote("\n".join(win_lines))
    if lose_lines:
        text += "\n\n▫️ <b>Решта хутора</b>\n" + quote("\n".join(lose_lines))
    return text


REWARD_PM = "🏁 <b>Гру завершено</b>\n{result}\n\nНагорода: <b>+{amount}</b> {shagy}"
RESULT_WIN = "🏆 <b>Перемога!</b> Хутір тебе не забуде."
RESULT_LOSE = "Цього разу не пощастило — наступна ніч буде твоєю."


# ---------- профіль ----------

RANKS = [
    (0, "🌱", "Приблуда"),
    (3, "🪵", "Наймит"),
    (10, "🏡", "Господар"),
    (25, "🐎", "Козак"),
    (50, "⚔️", "Сотник"),
    (100, "🏵", "Полковник"),
    (200, "👑", "Гетьман"),
]


def rank(wins: int) -> tuple[str, tuple[int, str, str] | None]:
    """Звання за перемогами і наступне звання (або None, якщо вже найвище)."""
    current = RANKS[0]
    for r in RANKS:
        if wins >= r[0]:
            current = r
    idx = RANKS.index(current)
    nxt = RANKS[idx + 1] if idx + 1 < len(RANKS) else None
    return f"{current[1]} {current[2]}", nxt


def profile(name: str, shagy: int, cherv: int, vip_until: str | None, games: int, wins: int,
            inventory: list[str]) -> str:
    rate = f"{round(wins * 100 / games)}%" if games else "—"
    title, nxt = rank(wins)
    progress = (f"{bar(wins, nxt[0])}  {wins}/{nxt[0]} до «{nxt[1]} {nxt[2]}»" if nxt
                else "Найвище звання на хуторі!")
    lines = [
        f"🏡 <b>Хата: {escape(name)}</b>" + (" 👑" if vip_until else ""),
        f"Звання: <b>{title}</b>",
        progress,
        "",
        "💰 <b>Гаманець</b>",
        quote(f"{SHAGY} Шаги: <b>{shagy}</b>\n{CHERV} Червінці: <b>{cherv}</b>"),
        "",
        "📊 <b>Статистика</b>",
        quote(f"🎲 Ігор: <b>{games}</b>\n🏆 Перемог: <b>{wins}</b> ({rate})"),
        "",
        f"👑 VIP до <b>{vip_until}</b>" if vip_until else "👑 VIP: немає — /vip",
        "",
        "🎒 <b>Скриня</b>",
        quote("\n".join(inventory) if inventory else "<i>порожньо — зазирни на ярмарок</i>"),
    ]
    return "\n".join(lines)


DAILY_OK = "🎁 Кума передала гостинця: +{amount} {shagy}! Приходь завтра."
DAILY_WAIT = "⏳ Гостинець уже отримано. Наступний — через {left}."
TOP_HEAD = "🏆 <b>Найкращі гравці цього хутора</b>"
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
        "<i>Усе, щоб пережити ніч на хуторі</i>",
        "",
        f"💰 Гаманець: <b>{balance}</b> {SHAGY}",
        f"🎒 На гру береш до <b>{slots}</b> різних предметів (VIP — більше)",
        "",
    ]
    for item in ITEMS.values():
        have = inventory.get(item.key, 0)
        own = f"  ·  у скрині: <b>{have}</b>" if have else ""
        lines.append(quote(f"<b>{item.title}</b> — {item.price} {SHAGY}{own}\n<i>{item.description}</i>"))
    return "\n".join(lines)


SHOP_BOUGHT = "✅ Куплено: {item}. Залишок: {balance} {shagy}"
SHOP_NO_MONEY = "Не вистачає шагів. Зіграй ще кілька ігор або візьми /daily."


# ---------- VIP і червінці ----------

def vip_menu(cherv: int, vip_until: str | None, vip_price: int, rate: int) -> str:
    status = f"👑 У тебе VIP до <b>{vip_until}</b>." if vip_until else "👑 VIP ще немає."
    return (
        "👑 <b>VIP на хуторі</b>\n\n"
        + quote(
            "✨ ×1.5 шагів за кожну гру\n"
            f"🎁 щоденний гостинець {DAILY_VIP} {SHAGY} замість {DAILY}\n"
            "🎒 +1 предмет у кишеню на гру\n"
            "👑 корона в профілі"
        )
        + f"\n\n{status}\n"
        f"{CHERV} Червінців у гаманці: <b>{cherv}</b>\n\n"
        f"<i>VIP можна купити за зірки ⭐ або за {vip_price} {CHERV}.\n"
        f"Обмін: 1 {CHERV} = {rate} {SHAGY}.</i>"
    )


VIP_BOUGHT = "👑 VIP активовано до {until}! Дякуємо, що підтримуєш хутір."
VIP_NO_CHERV = "Не вистачає червінців."
CHERV_BOUGHT = "💎 Зараховано {amount} червінців. Дякуємо за підтримку!"
EXCHANGED = "🔄 Обміняно {cherv} {cherv_icon} на {shagy} {shagy_icon}."
PAYMENT_UNKNOWN = "Невідомий товар. Спробуй ще раз через /vip."


# ---------- налаштування чату ----------

SETTINGS_HEAD = (
    "⚙️ <b>Налаштування гри в цьому чаті</b>\n"
    "<i>Зміни діють з наступної гри. ➖/➕ змінюють таймери.</i>"
)
SETTINGS_ROLES_HEAD = (
    "🎭 <b>Ролі</b>\n"
    "Вимкнені ролі не роздаються. Відьма, Упир і Селянин — обов'язкові."
)
TIMER_NAMES = {
    "reg_time": "⏳ Реєстрація",
    "night_time": "🌙 Ніч",
    "day_time": "🗣 Обговорення",
    "vote_time": "⚖️ Голосування",
    "confirm_time": "🪢 Вирок",
}
TOGGLE_LABELS = {
    "hide_dead_roles": ("👁 Ролі загиблих: показувати", "🙈 Ролі загиблих: приховувати"),
    "secret_vote": ("🗳 Голосування: відкрите", "🤫 Голосування: таємне"),
    "items_enabled": ("🚫 Предмети: вимкнені", "🎒 Предмети: увімкнені"),
}
SETTINGS_CLOSED = "⚙️ Налаштування збережено."
