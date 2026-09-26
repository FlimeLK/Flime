"""Усі тексти бота. Українською, у стилі «Мафія: Хутір».

Стиль: одне доречне емодзі на заголовок чи кнопку, жирні заголовки, цитати для списків і атмосфери.
"""

from __future__ import annotations

from html import escape

from bot.economy import DAILY, DAILY_VIP
from bot.engine.items import ITEMS
from bot.engine.models import MIN_PLAYERS
from bot.engine.roles import ROLES, TEAM_TITLES, NightKind, Role, Team, custom_role, role

GAME_NAME = "Мафія: Хутір"


def mention(user_id: int, name: str) -> str:
    if -100 < user_id < 0:  # бот тестової гри
        return f"🤖 {escape(name)}"
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


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


SHAGY = "🪙"
CHERV = "💎"


def shagy(n: int) -> str:
    return f"{n} {SHAGY}"


def cherv(n: int) -> str:
    return f"{n} {CHERV}"


# ---------- опис бота (видно до натискання «Почати») ----------

BOT_SHORT_DESCRIPTION = "🌻 Мафія з українським колоритом: Громада проти Нечисті. Додай у групу й напиши /game."
BOT_DESCRIPTION = (
    "🌻 Мафія: Хутір\n\n"
    "На тихому хуторі завелася нечисть. Вдень усі — добрі сусіди, "
    "а вночі хтось не повертається з вечорниць.\n\n"
    "🎭 12 ролей і свої ролі чату\n"
    "🧿 Чарівні предмети\n"
    "🏆 Звання і рейтинг\n\n"
    "Додай мене в групу, напиши /game — і я буду ведучим."
)


# ---------- старт / допомога ----------

START = (
    f"🌻 <b>{GAME_NAME}</b>\n"
    "Мафія з українським колоритом.\n\n"
    + quote("<i>На тихому хуторі завелася нечисть. Вдень усі — добрі сусіди, "
            "а вночі хтось не повертається з вечорниць…</i>")
    + "\n\n<b>Як почати</b>\n"
    "1. Додай мене в групу кнопкою нижче.\n"
    "2. Напиши там /game.\n"
    f"3. Збери щонайменше {MIN_PLAYERS} гравців — і настане ніч 🌙"
)
MENU_BACK = "‹ Меню"
MENU_BUTTONS = {
    "profile": "🏡 Профіль",
    "shop": "🛒 Ярмарок",
    "daily": "🎁 Гостинець",
    "vip": "👑 VIP",
    "rules": "📜 Правила",
}
ADD_TO_GROUP = "➕ Додати в групу"
TO_BOT_BUTTON = "📩 Відкрити бота"

RULES_HEAD = (
    "📜 <b>Правила гри</b>\n\n"
    "🌙 <b>Ніч.</b> Кожен, хто має нічну справу, отримує кнопки в особисті. "
    "Нечисть обирає жертву, знахарка лікує, характерник перевіряє.\n\n"
    "☀️ <b>День.</b> Громада дізнається, хто не дожив до ранку, і обговорює.\n\n"
    "⚖️ <b>Голосування.</b> Кожен живий голосує в особистих. Потім громада "
    "підтверджує страту в групі.\n\n"
    "🏆 <b>Перемога</b>\n"
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
        parts.append(f"\n<i>{title}</i>\n" + quote("\n".join(roles), expandable=len(roles) > 2))
    items = [f"<b>{i.title}</b> — {i.description}" for i in ITEMS.values()]
    parts.append("\n\n🎒 <b>Предмети</b>\n<i>Купуються на ярмарку і самі беруться в гру.</i>\n"
                 + quote("\n".join(items), expandable=True))
    return "".join(parts)


# ---------- лобі ----------

def lobby(players: list[tuple[int, str]], seconds: int, min_players: int) -> str:
    n = len(players)
    need = (f"Потрібно ще {min_players - n}." if n < min_players
            else "Гравців достатньо.")
    names = "\n".join(f"{i}. {mention(uid, name)}" for i, (uid, name) in enumerate(players, start=1))
    return (
        "🌾 <b>Набір на гру</b>\n"
        f"⏳ До початку ~{fmt_seconds(seconds)}. {need}\n\n"
        f"👥 <b>Гравці · {n}</b>\n"
        + quote(names or "<i>поки нікого</i>")
    )


JOIN_BUTTON = "🙋 Долучитися"
RULES_BUTTON = "📜 Правила"
LOBBY_REMINDER = "⏳ До початку гри лишилось <b>{left}</b>."
LOBBY_NOT_ENOUGH = "😴 <b>Гру скасовано.</b> Не зібралось {min} гравців."
LOBBY_ALREADY = "Гра в цьому чаті вже йде. Дочекайся наступної."
JOINED_PM = "✅ Тебе записано на гру в чаті <b>{chat}</b>. Роль прийде сюди."
JOIN_ALREADY_HERE = "Ти вже записаний на цю гру."
JOIN_IN_OTHER = "Ти вже граєш в іншому чаті. Одна гра за раз."
JOIN_CLOSED = "Реєстрацію вже закрито."
JOIN_FULL = "Громада переповнена — більше {max} гравців не можна."
LEFT_LOBBY = "🚶 {name} виходить з гри."
NOT_IN_LOBBY = "Ти не записаний у цю гру або вона вже почалась."
GROUP_ONLY = "Ця команда працює лише в групі."
PRIVATE_ONLY = "Ця команда працює лише в особистих повідомленнях з ботом."
ADMIN_ONLY = "Це може зробити лише адміністратор чату."
NO_GAME = "Зараз у чаті немає гри."
FORCE_START_FEW = "Замало гравців: потрібно щонайменше {min}."
TEST_GAME_STARTED = (
    "🧪 <b>Тестова гра</b>\n"
    "Додав ботів: {bots}. Вони самі ходять уночі й голосують.\n"
    "Тисни «🙋 Долучитися», щоб грати з ними, або /start_now, щоб почати одразу.\n"
    "<i>Без нагород, предметів і статистики.</i>"
)
TEST_GAME_NOTE = "🧪 <i>Тестова гра — без нагород і статистики.</i>"
GAME_STOPPED = "🛑 <b>Гру зупинено</b> адміністратором."
GAME_RESUMED = "🔄 Бот перезапустився. Продовжуємо гру з початку поточної фази."
GAME_CRASHED = "⚠️ У грі сталася помилка, і її довелося зупинити. Предмети повернуто в інвентар."


# ---------- старт гри та ролі ----------

GAME_STARTED = (
    "🔥 <b>Гру розпочато</b>\n"
    "👥 Гравців: {n}\n"
    "<blockquote>{composition}</blockquote>\n"
    "🎭 Ролі надіслано в особисті."
)


def describe(r: Role) -> str:
    if not r.custom:
        return ROLE_DESCRIPTIONS[r.key]
    ability = ability_hint(r)
    own = escape(r.description)
    return f"{own}\n\n<i>{ability}</i>" if own else ability


def role_card(role_key: str, pocket: list[str], allies: list[str]) -> str:
    r = role(role_key)
    text = [
        f"🎭 Твоя роль — <b>{r.title}</b>",
        f"Сторона: {TEAM_TITLES[r.team]}",
        "",
        quote(describe(r)),
        f"🎯 <b>Мета:</b> {TEAM_GOALS[r.team]}",
    ]
    if allies:
        text += ["", "🌑 <b>Твоя нечиста братія</b>", quote("\n".join(allies)),
                 "<i>Пиши мені сюди — я передам повідомлення своїм.</i>"]
    if pocket:
        text += ["", "🎒 <b>У кишені:</b> " + ", ".join(ITEMS[i].title for i in pocket)]
    return "\n".join(text)


# ---------- ніч ----------

def night_start(day: int, alive: list[tuple[int, str]]) -> str:
    names = "\n".join(f"{n}. {mention(u, nm)}" for n, (u, nm) in enumerate(alive, start=1))
    return (
        f"🌙 <b>Ніч {day}</b>\n"
        "<i>Хутір засинає. У лісі щось шарудить…</i>\n"
        "Хто має нічні справи — перевірте особисті 📩\n\n"
        f"👥 <b>Живі · {len(alive)}</b>\n" + quote(names)
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
    "shot": "🎭 Кого вб'єш цієї ночі? Це можна зробити лише раз за гру.",
}

NIGHT_CHOSEN = "✅ Обрано: <b>{target}</b>"
NIGHT_EXPIRED = "⌛ Ніч минула, вибір не зроблено."
NIGHT_BAD_TARGET = "Цю ціль обрати не можна."
NIGHT_NOT_NOW = "Зараз не час для цього."
EVIL_VOTE_RELAY = "🌑 {actor} пропонує жертву: {target}."
EVIL_CHAT = "🌑 <b>{name}:</b> {text}"
SKIP_BUTTON = "🚫 Пропустити"
NEW_EVIL_LEADER = "🌑 Ти тепер ватажок нечисті — твоє слово вирішальне."


# ---------- ранок ----------

DEATH_CAUSES = {
    "evil": "нечисть забрала в темряву",
    "wolf": "не пережили зустрічі з вовкулакою",
    "saber": "впали від шаблі характерника",
    "pitchfork": "наткнулись на вила",
    "shot": "не пережили нічного візиту",
}


def morning(day: int, deaths: list[tuple[int, str, str, str | None]], saved_count: int) -> str:
    """deaths: (uid, name, cause, role_title або None, якщо ролі приховано)."""
    lines = [f"☀️ <b>Ранок {day}</b>", "<i>Півні проспівали, хутір прокидається.</i>", ""]
    if not deaths:
        lines.append("🕊 Цієї ночі всі живі.")
    for uid, name, cause, role_title in deaths:
        role_part = f" <i>({role_title})</i>" if role_title else ""
        lines.append(f"⚰️ {mention(uid, name)}{role_part} — {DEATH_CAUSES.get(cause, 'не дожили до ранку')}.")
    if saved_count:
        lines.append(f"\n✨ Когось цієї ночі врятували ({saved_count}).")
    return "\n".join(lines)


YOU_DIED = "⚰️ <b>Тебе вбили цієї ночі.</b>\nМожеш спостерігати, але мовчи — мертві не говорять."
YOU_SAVED = {
    "heal": "🌿 На тебе напали, але знахарка встигла тебе вилікувати.",
    "obereg": "🧿 На тебе напали, але оберіг захистив. Він розсипався на порох.",
    "kum": "🍀 На тебе напали, але ти, кум, як завжди, викрутився.",
    "lucky": "🍀 На тебе напали, але тобі пощастило вижити.",
}
YOU_LURED = "🧜‍♀️ Мавка заманила тебе до ставка — цієї ночі ти нічого не встиг."
GARLIC_WORKED = "🧄 Мавка кликала тебе до ставка, але від часнику аж скривилась."
CHECK_RESULT = {True: "🗡 {target} — з Громади.", False: "🗡 {target} — <b>не з Громади</b>."}
COMPARE_RESULT = {True: "🪕 {a} і {b} — з одного боку.", False: "🪕 {a} і {b} — з різних боків."}
WATCH_RESULT = "🏮 До хати {target} цієї ночі приходили: {visitors}"
WATCH_NOBODY = "🏮 До хати {target} цієї ночі ніхто не приходив."
CANDLE_RESULT = "🕯 Свічка догоріла. До тебе вночі приходили: {visitors}"


# ---------- день і голосування ----------

DAY_START = "🗣 <b>Обговорення</b> · {time}\nХто підозрілий? Хто вночі не спав?"
VOTE_START = "⚖️ <b>Голосування</b> · {time}\nГолосуйте в особистих з ботом 📩"
VOTE_PROMPT = "⚖️ Кого громада має стратити?"
HONEY_BUTTON = "🍯 Мед: мій голос ×2"
HONEY_USED = "🍯 Мед з'їдено — твій голос сьогодні важить подвійно."
HONEY_FAIL = "Меду немає або його вже з'їдено."
VOTE_CAST = "✅ Твій голос: <b>{target}</b>"
VOTE_SKIP_CAST = "✅ Твій голос: нікого не страчувати."
VOTE_ANNOUNCE = "🗳 {voter} голосує за {target}"
VOTE_ANNOUNCE_SKIP = "🗳 {voter} — проти страти"
VOTE_ANNOUNCE_SECRET = "🗳 Голосів: {count}/{total}"
VOTE_EXPIRED = "⌛ Голосування завершилось."
VOTE_NOBODY = "🤷 Громада не дійшла згоди — сьогодні нікого не стратять."
VOTE_SKIP_LABEL = "🚫 Нікого"


def vote_results(rows: list[tuple[str, int]]) -> str:
    """rows: (підпис, кількість голосів), від найбільшого."""
    lines = [f"{label} — {count}" for label, count in rows]
    return "📊 <b>Підсумки голосування</b>\n" + quote("\n".join(lines) or "<i>ніхто не голосував</i>")


CONFIRM_ASK = "🪢 <b>Суд громади</b>\nСтратити {name}?\n\n👍 {yes} · 👎 {no}"
CONFIRM_YES = "👍 Стратити"
CONFIRM_NO = "👎 Помилувати"
CONFIRM_NOT_ALLOWED = "Голосувати можуть лише живі гравці, крім самого підсудного."
CONFIRM_THANKS = "Голос враховано."
PARDON = "🙏 Громада змилувалась: {name} лишається жити. ({yes} 👍 / {no} 👎)"
LYNCHED = "🪢 Громада винесла вирок: {name} страчено.{role}"
HORSESHOE_SAVED = "🐴 Мотузка обірвалась — у кишені знайшлась підкова. {name} вціліли."
FOOL_WON = "🤪 Та це ж був Іван-дурень! Він хотів цього — і переміг. Гра триває."


# ---------- кінець гри ----------

WINNER_TITLES = {
    Team.VILLAGE: "🌾 Перемогла Громада",
    Team.EVIL: "🌑 Перемогла Нечисть",
    Team.WOLF: "🐺 Переміг Вовкулака",
    "draw": "🕯 Нічия",
}
WINNER_FLAVOR = {
    Team.VILLAGE: "Нечисть вигнали з хутора.",
    Team.EVIL: "Хутір тепер належить темряві.",
    Team.WOLF: "Лишився лише він — і місяць.",
    "draw": "На хуторі не лишилось нікого.",
}


def game_over(winner: str, win_lines: list[str], lose_lines: list[str], days: int) -> str:
    text = (
        f"🏁 <b>Гру завершено</b> · днів: {days}\n\n"
        f"<b>{WINNER_TITLES.get(winner, winner)}</b>\n"
        f"<i>{WINNER_FLAVOR.get(winner, '')}</i>"
    )
    if win_lines:
        text += "\n\n🏆 <b>Переможці</b>\n" + quote("\n".join(win_lines))
    if lose_lines:
        text += "\n▫️ <b>Решта</b>\n" + quote("\n".join(lose_lines))
    return text


REWARD_PM = "🏁 <b>Гру завершено.</b> {result}\nНагорода: +{amount}"
RESULT_WIN = "🏆 Перемога!"
RESULT_LOSE = "Цього разу не пощастило."


# ---------- профіль ----------

RANKS = [
    (0, "🌱 Приблуда"),
    (3, "🪵 Наймит"),
    (10, "🏡 Господар"),
    (25, "🐎 Козак"),
    (50, "⚔️ Сотник"),
    (100, "🏵 Полковник"),
    (200, "👑 Гетьман"),
]


def rank(wins: int) -> tuple[str, tuple[int, str] | None]:
    """Звання за перемогами і наступне звання (або None, якщо вже найвище)."""
    idx = max(i for i, (need, _) in enumerate(RANKS) if wins >= need)
    nxt = RANKS[idx + 1] if idx + 1 < len(RANKS) else None
    return RANKS[idx][1], nxt


def profile(name: str, shagy_: int, cherv_: int, vip_until: str | None, games: int, wins: int,
            inventory: list[str]) -> str:
    rate = f"{round(wins * 100 / games)}%" if games else "—"
    title, nxt = rank(wins)
    left = nxt[0] - wins if nxt else 0
    next_line = (f"До звання «{nxt[1]}» — ще {left} {plural(left, 'перемога', 'перемоги', 'перемог')}."
                 if nxt else "Найвище звання на хуторі.")
    lines = [
        f"🏡 <b>{escape(name)}</b>" + (" 👑" if vip_until else ""),
        f"{title}. <i>{next_line}</i>",
        "",
        f"{SHAGY} Шаги: <b>{shagy_}</b>",
        f"{CHERV} Червінці: <b>{cherv_}</b>",
        f"👑 VIP до {vip_until}" if vip_until else "👑 VIP: немає",
        "",
        f"🎲 Ігор: <b>{games}</b> · 🏆 Перемог: <b>{wins}</b> ({rate})",
        "",
        "🎒 <b>Скриня</b>",
        quote("\n".join(inventory) if inventory else "<i>порожньо</i>"),
    ]
    return "\n".join(lines)


DAILY_OK = "🎁 Кума передала гостинця: +{amount}. Приходь завтра."
DAILY_WAIT = "⏳ Гостинець уже отримано. Наступний — через {left}."
TOP_HEAD = "🏆 <b>Найкращі гравці чату</b>"
TOP_EMPTY = "Тут ще ніхто не грав. Почніть з /game."
PROMO_USAGE = "Напиши так: <code>/promo КОД</code>"
PROMO_ERRORS = {
    "not_found": "Такого промокоду немає.",
    "used": "Ти вже активував цей промокод.",
    "exhausted": "Промокод уже вичерпано.",
}


def promo_ok(shagy_: int, cherv_: int, vip_days: int) -> str:
    parts = []
    if shagy_:
        parts.append(f"+{shagy(shagy_)}")
    if cherv_:
        parts.append(f"+{cherv(cherv_)}")
    if vip_days:
        parts.append(f"👑 VIP +{vip_days} дн.")
    return "🎉 Промокод активовано: " + (", ".join(parts) or "нічого")


# ---------- ярмарок ----------

def shop(balance: int, inventory: dict[str, int], slots: int) -> str:
    lines = [
        "🛒 <b>Ярмарок</b>",
        f"💰 На рахунку: <b>{shagy(balance)}</b>",
        f"<i>На гру береш до {slots} різних предметів.</i>",
        "",
    ]
    for item in ITEMS.values():
        have = inventory.get(item.key, 0)
        own = f" · є {have}" if have else ""
        lines.append(f"<b>{item.title}</b> — {shagy(item.price)}{own}\n<i>{item.description}</i>\n")
    return "\n".join(lines).rstrip()


SHOP_BOUGHT = "✅ Куплено: {item}. Залишок: {balance}"
SHOP_NO_MONEY = "Не вистачає шагів. Зіграй ще кілька ігор або візьми гостинець."


# ---------- VIP і червінці ----------

def vip_menu(cherv_: int, vip_until: str | None, vip_price: int, rate: int) -> str:
    status = f"Активний до <b>{vip_until}</b>." if vip_until else "Не активний."
    return (
        "👑 <b>VIP</b>\n"
        f"{status}\n\n"
        + quote(
            "✨ ×1.5 шагів за кожну гру\n"
            f"🎁 Щоденний гостинець {shagy(DAILY_VIP)} замість {DAILY}\n"
            "🎒 +1 предмет у кишеню на гру"
        )
        + f"\n{CHERV} Червінці: <b>{cherv_}</b>\n\n"
        f"<i>VIP — за зірки ⭐ або за {cherv(vip_price)}. "
        f"Обмін: 1 {CHERV} = {shagy(rate)}.</i>"
    )


VIP_BOUGHT = "👑 VIP активовано до {until}. Дякуємо, що підтримуєш хутір."
VIP_NO_CHERV = "Не вистачає червінців."
CHERV_BOUGHT = "💎 Зараховано {amount}. Дякуємо за підтримку."
EXCHANGED = "🔄 Обміняно {cherv} на {shagy}."
PAYMENT_UNKNOWN = "Невідомий товар. Спробуй ще раз через /vip."


# ---------- налаштування чату ----------

def settings_head(chat_title: str) -> str:
    return (f"⚙️ <b>Налаштування гри</b> · {escape(chat_title)}\n"
            "<i>Зміни діють з наступної гри.</i>")


PANEL_SENT = "📩 Надіслав налаштування тобі в особисті."
PANEL_OPEN_PM = "Не можу написати тобі в особисті — спершу відкрий бота."
PANEL_OPEN_BUTTON = "⚙️ Відкрити налаштування"
SETTINGS_IN_GROUP = "Напиши /settings у групі, яку хочеш налаштувати, — я надішлю панель сюди."
SETTINGS_ROLES_HEAD = (
    "🎭 <b>Стандартні ролі</b>\n"
    "<i>Вимкнені ролі не роздаються. Відьма, Упир і Селянин — обов'язкові.</i>"
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
SETTINGS_ROLES_BUTTON = "🎭 Стандартні ролі"
SETTINGS_TO_PANEL = "‹ Налаштування"
SETTINGS_CLOSE = "✖️ Закрити"
SETTINGS_BACK = "‹ Назад"
SETTINGS_CLOSED = "⚙️ Налаштування збережено."


# ---------- конструктор своїх ролей ----------

ABILITY_LABELS = {
    "none": "💤 Без здібності",
    "heal": "🌿 Лікує",
    "check": "🔍 Перевіряє сторону",
    "watch": "🏮 Стереже хату",
    "compare": "🪕 Порівнює двох",
    "block": "🧜‍♀️ Блокує дію",
    "kill": "🗡 Вбиває",
    "lucky": "🍀 Переживає напад",
    "vote2": "🎖 Подвійний голос",
}
ABILITY_HINTS = {
    "none": "Нічних дій немає — лише обговорення і голос.",
    "heal": "Щоночі лікує одного гравця від смерті.",
    "check": "Щоночі дізнається, чи гравець із Громади.",
    "watch": "Стереже чиюсь хату і зранку знає, хто туди приходив.",
    "compare": "Дізнається, чи двоє гравців з одного боку.",
    "block": "Щоночі скасовує дію обраного гравця.",
    "kill_evil": "Щоночі разом з нечистю обирає жертву.",
    "kill": "Один раз за гру може вбити будь-кого вночі.",
    "lucky": "Переживає перший напад уночі.",
    "vote2": "Голос на денному голосуванні важить подвійно.",
}


def ability_hint(r: Role) -> str:
    if NightKind.KILL in r.night:
        return ABILITY_HINTS["kill_evil"]
    for key, kind in _ABILITY_KINDS.items():
        if kind in r.night:
            return ABILITY_HINTS[key]
    return ABILITY_HINTS[r.passives[0] if r.passives else "none"]


_ABILITY_KINDS = {
    "heal": NightKind.HEAL, "check": NightKind.CHECK, "watch": NightKind.WATCH,
    "compare": NightKind.COMPARE, "block": NightKind.LURE, "kill": NightKind.SABER,
}

RB_OPEN_BUTTON = "✨ Створення ролей"
RB_NO_RIGHTS = "Редагувати ролі можуть лише адміністратори цього чату."
RB_CREATE = "➕ Створити роль"
RB_BACK_TO_LIST = "‹ До списку"
RB_BACK = "‹ Назад"
RB_CANCEL = "Скасувати"
RB_NAME = "✏️ Назва"
RB_DESC = "📝 Опис"
RB_DELETE = "🗑 Видалити"
RB_DELETE_CONFIRM = "Так, видалити"
RB_ENABLE = "▶️ Увімкнути"
RB_DISABLE = "⏸ Вимкнути"
RB_ASK_NAME = "Напиши назву ролі — від 2 до 24 символів: літери, цифри, пробіл, дефіс, апостроф."
RB_ASK_DESC = "Напиши опис ролі — до 300 символів. Його гравець побачить разом з роллю."
RB_BAD_NAME = "Така назва не підходить. Від 2 до 24 символів: літери, цифри, пробіл, дефіс, апостроф."
RB_BAD_DESC = "Опис задовгий — до 300 символів."
RB_EXISTS = "Роль з такою назвою вже є."
RB_LIMIT = "У чаті вже максимум своїх ролей ({max})."
RB_DELETED = "Роль видалено."
RB_NOT_FOUND = "Цю роль уже видалено."


def rb_list(chat_title: str, roles: list, limit: int) -> str:
    lines = [f"✨ <b>Свої ролі</b> · {escape(chat_title)}",
             "<i>Нові ролі роздаються з наступної гри замість звичайних селян чи упирів.</i>", ""]
    if not roles:
        lines.append("Своїх ролей ще немає.")
    for r in roles:
        state = "" if r.enabled else " <i>(вимкнена)</i>"
        lines.append(f"🎭 <b>{escape(r.name)}</b> — {TEAM_TITLES[Team(r.team)]}, "
                     f"{ABILITY_LABELS[r.ability].lower()}, від {r.min_players}{state}")
    lines.append(f"\n{len(roles)} з {limit}")
    return "\n".join(lines)


def rb_role(r) -> str:
    engine = custom_role(r.to_engine())
    return "\n".join([
        f"🎭 <b>{escape(r.name)}</b>" + ("" if r.enabled else " <i>(вимкнена)</i>"),
        "",
        f"Сторона: {TEAM_TITLES[Team(r.team)]}",
        f"Здібність: {ABILITY_LABELS[r.ability]}",
        f"👥 З'являється від {r.min_players} гравців",
        "",
        "👁 <b>Як бачить гравець</b>",
        quote(describe(engine)),
    ])


def rb_abilities(r) -> str:
    lines = [f"🎭 <b>Здібність ролі {escape(r.name)}</b>", ""]
    for key, label in ABILITY_LABELS.items():
        hint = ability_hint(custom_role({**r.to_engine(), "ability": key}))
        lines.append(f"<b>{label}</b> — {hint}")
    return "\n".join(lines)
