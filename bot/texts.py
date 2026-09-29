"""Усі тексти бота. Українською, у стилі «Сицилійська мафія».

Мітки :ключ: (наприклад :night:, :vidma:) перед надсиланням перетворюються на анімовані
емодзі - див. bot/ui/emoji.py і bot/ui/safe.py. У тексті кнопок і спливних вікон HTML не
працює, там мітки стають звичайними емодзі.
"""

from __future__ import annotations

from html import escape

from bot.engine.items import ITEMS
from bot.engine.roles import ROLES, Team

GAME_NAME = "Сицилійська мафія"
SHAGY = ":shagy:"
CHERV = ":cherv:"

TEAM_TITLES = {
    Team.VILLAGE: ":village: Мирні",
    Team.EVIL: ":evil: Мафія",
    Team.WOLF: ":vovkulaka: Маніяк",
    Team.FOOL: ":duren: Самогубець",
}


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{escape(name)}</a>'


def role_title(key: str) -> str:
    r = ROLES[key]
    if not r.custom:
        return f":{key}: {r.name}"
    # Власна роль чату: назва від адміна (екрануємо), емодзі — звичайний або premium.
    icon = f'<tg-emoji emoji-id="{r.custom_emoji_id}">{r.emoji}</tg-emoji>' if r.custom_emoji_id else r.emoji
    return f"{icon} {escape(r.name)}"


def role_description(key: str) -> str:
    return ROLE_DESCRIPTIONS.get(key) or escape(ROLES[key].description)


def team_title(key: str) -> str:
    r = ROLES[key]
    return ":moon: Одинак" if r.custom and r.team == Team.WOLF else TEAM_TITLES[r.team]


def item_title(key: str) -> str:
    return f":{key}: {ITEMS[key].name}"


def fmt_seconds(s: int) -> str:
    if s >= 60 and s % 60 == 0:
        return f"{s // 60} хв"
    if s >= 60:
        return f"{s // 60} хв {s % 60} с"
    return f"{s} с"


def bar(value: int, total: int, width: int = 10) -> str:
    filled = 0 if total <= 0 else min(width, round(width * value / total))
    return "▰" * filled + "▱" * (width - filled)


def numbered(players: list[tuple[int, str]]) -> str:
    return "\n".join(f"<b>{n}.</b> {mention(uid, name)}" for n, (uid, name) in enumerate(players, start=1))


# ---------- старт / допомога ----------

# ---------- персонаж ----------
# Щоб змінити персонажа - достатньо цих констант.

PERSONA = "Консильєре"
CATCHPHRASE = "Бонджорно"

# Профіль бота в Telegram (застосовується при старті бота; аватарку ставить власник у @BotFather).
BOT_NAME = f"{PERSONA} | {GAME_NAME}"
BOT_ABOUT = "Веду сицилійську мафію у вашій групі: ролі, нічні розбірки, голосування й чорний ринок."
BOT_DESCRIPTION = (
    "🎩 Бонджорно! Над Палермо сутеніє, і сім'ї вже ділять місто - знайди мафію раніше, ніж вона знайде тебе.\n"
    "👇 Тисни «Старт», і консильєре розповість, як тут усе влаштовано."
)


# ---------- старт і головне меню ----------

def start(first_name: str) -> str:
    return (
        f":wave: <b>{CATCHPHRASE}, {escape(first_name)}!</b>\n"
        f"Я - <b>{PERSONA}</b>, права рука Дона і ведучий гри «{GAME_NAME}».\n"
        "У Палермо вдень усі - поважні синьйори, а вночі хтось не повертається з вечері в траторії.\n\n"
        "Обирай, з чого почнемо ↓"
    )


# Кнопки головного меню: ключ розділу → (емодзі, підпис). Емодзі розділу однакове всюди.
MENU_WIDE_TOP = ("howto", "chat", "Порада консильєре")
MENU_GRID = [
    ("game", "dice", "Правила сім'ї"),
    ("roles", "theater", "Хто є хто"),
    ("items", "bag", "Арсенал"),
    ("profile", "profile", "Моє досьє"),
    ("daily", "gift", "Конверт від Дона"),
    ("vip", "vip", "VIP-ложа"),
]
MENU_ADD_GROUP = ("people", "Додати в групу")
BACK = "Повернутись"


def section(emo: str, title: str, intro: str, items: list[str], call: str) -> str:
    """Розділ меню: жирний заголовок, слово персонажа, (список), заклик."""
    body = "\n\n" + "\n".join(items) if items else ""
    return f":{emo}: <b>{title}</b>\n\n{intro}{body}\n\n<i>{call}</i>"


SECTION_HOWTO = section(
    "chat", "Порада консильєре",
    f"{CATCHPHRASE}, синьйоре! У нас усе просто: тиснеш кнопку - я роблю.",
    [
        ":people: Додай мене в групу - там я збиратиму гравців на гру",
        ":lock: Ролі, нічні дії й голосування приходять мені в особисті",
        ":settings: Адміни групи можуть налаштувати гру під себе",
        ":sparkle: Усе інше - кнопками в цьому меню",
    ],
    "Додавай мене в групу - і сім'ї зберуться до столу.",
)


SECTION_GAME = section(
    "dice", "Правила сім'ї",
    "Гра йде по колу, поки хтось не переможе. Я веду - ви хитруєте.",
    [
        ":night: <b>Ніч</b> - кнопки дій приходять в особисті",
        ":morning: <b>Ранок</b> - дізнаєтесь, хто не дожив до світанку",
        ":discuss: <b>Обговорення</b> - шукайте, хто бреше",
        ":vote: <b>Голосування</b> - в особистих, потім вирок :like:/:dislike:",
    ],
    "Мирні перемагають, коли мафії не лишилось. Мафія - коли її не менше, ніж решти.",
)


def section_roles() -> str:
    lines = [f":{r.key}: <b>{r.name}</b> - {ROLE_DESCRIPTIONS[r.key]}" for r in ROLES.values() if not r.custom]
    return section("theater", "Хто є хто", "У Палермо кожен не той, ким здається. Ось хто тут живе:", lines,
                   "Роль приходить в особисті на початку гри - нікому не показуй!")


def section_items() -> str:
    lines = [f":{i.key}: <b>{i.name}</b> · {i.price} :shagy: - {i.description}" for i in ITEMS.values()]
    return section("bag", "Арсенал", "На чорному ринку можна дістати дещо корисне - у гру береться само.",
                   lines, "Зазирни на чорний ринок, поки ліри в кишені!")


def section_profile(card: str) -> str:
    return section("profile", "Моє досьє", card, [], "Грай частіше - ліри самі в кишеню не стрибнуть!")


def section_daily(result: str) -> str:
    return section("gift", "Конверт від Дона", result, [], "Дон щедрий до своїх - заходь щодня!")


SECTION_VIP = section(
    "vip", "VIP-ложа",
    "VIP - для поважних синьйорів. Купується за :star: зірки або золоті монети.",
    [
        ":fire: ×1.5 лір за кожну гру",
        ":gift: товщий щоденний конверт",
        ":bag: +1 предмет у кишеню на гру",
        ":vip: корона в профілі",
    ],
    "Сім'я не забуває тих, хто її підтримує.",
)


ROLE_DESCRIPTIONS = {
    "selianyn": "Звичайний мирний житель. Вночі спить, вдень шукає мафію і голосує.",
    "znaharka": "Щоночі лікує одного гравця від смерті. Себе - лише раз за гру. Одну людину двічі поспіль не можна.",
    "harakternyk": "Щоночі перевіряє, чи гравець мирний. Один раз за гру може замість цього вистрілити.",
    "kum": "Переживає перший напад уночі - везе ж людям!",
    "storozh": "Вночі ходить до когось і зранку знає, хто туди приходив.",
    "kobzar": "Порівнює двох гравців і дізнається, чи вони з одного боку.",
    "otaman": "Його голос на денному голосуванні важить подвійно.",
    "vidma": "Ватажок мафії. Його слово вирішує, кого вбити вночі.",
    "upyr": "Голосує за жертву разом із Доном. Якщо Дон загине - стає новим Доном.",
    "mavka": "Мафія. Проводить ніч із гравцем - його дія не спрацьовує. Якщо лишиться сама з мафії - вбиває.",
    "vovkulaka": "Одинак. Щоночі вбиває і хоче лишитися останнім.",
    "duren": "Одинак. Мріє, щоб його стратили на голосуванні - тоді він переможе.",
}


def rules() -> str:
    parts = [
        f":rules: <b>ПРАВИЛА «{GAME_NAME.upper()}»</b>",
        "",
        ":night: <b>Ніч.</b> Хто має нічну справу, отримує кнопки в особисті. "
        "Мафія обирає жертву, лікар лікує, комісар перевіряє.",
        ":morning: <b>Ранок.</b> Місто дізнається, хто не дожив до світанку.",
        ":discuss: <b>День.</b> Обговорення: хто підозрілий, хто вночі не спав?",
        ":vote: <b>Голосування</b> в особистих, потім гравці підтверджують страту :like:/:dislike:.",
        "",
        ":trophy: <b>Перемога</b>",
        "<blockquote>Мирні - коли вся мафія і маніяк мертві.\n"
        "Мафія - коли її не менше, ніж решти.\n"
        "Маніяк - коли лишиться сам на сам з кимось.\n"
        "Самогубець - якщо його стратять.</blockquote>",
    ]
    for team in (Team.VILLAGE, Team.EVIL, Team.WOLF, Team.FOOL):
        lines = [f"{role_title(r.key)} - {ROLE_DESCRIPTIONS[r.key]}" for r in ROLES.values()
                 if r.team == team and not r.custom]
        parts.append(f"<b>{TEAM_TITLES[team]}</b>\n<blockquote expandable>" + "\n".join(lines) + "</blockquote>")
    items = [f"{item_title(i.key)} - {i.description}" for i in ITEMS.values()]
    parts.append(":bag: <b>Арсенал</b> (купується на чорному ринку й сам береться в гру)\n"
                 "<blockquote expandable>" + "\n".join(items) + "</blockquote>")
    return "\n".join(parts)


# ---------- лобі ----------

def lobby(players: list[tuple[int, str]], seconds: int, min_players: int) -> str:
    n = len(players)
    need = max(0, min_players - n)
    status = f"ще потрібно: <b>{need}</b>" if need else ":ok: можна починати"
    lines = [
        ":bell: <b>СІМ'Ї ЗБИРАЮТЬСЯ!</b>",
        "",
        f":timer: До початку: <b>{fmt_seconds(seconds)}</b>",
        f":people: Записались: <b>{n}</b> · {status}",
        f"<code>{bar(min(n, min_players), min_players)}</code>",
        "",
        numbered(players) if players else "<i>Поки нікого… Будь першим!</i>",
    ]
    return "\n".join(lines)


JOIN_BUTTON = "Долучитися до гри"
LOBBY_REMINDER = ":bell: До початку гри лишилось <b>{left}</b>! Хто ще не записався - тисни «Долучитися»."
LOBBY_NOT_ENOUGH = ":skip: Не зібралось навіть {min} людей. Гру скасовано - Палермо спить спокійно."
LOBBY_ALREADY = ":dice: Гра в цьому чаті вже йде. Дочекайся наступної."
JOINED_PM = ":ok: Тебе записано на гру в чаті <b>{chat}</b>. Чекай на свою роль!"
JOIN_ALREADY_HERE = "Ти вже записаний на цю гру."
JOIN_IN_OTHER = "Ти вже граєш в іншому чаті. Одна гра за раз!"
JOIN_CLOSED = "Реєстрацію вже закрито."
JOIN_FULL = "За столом немає місць - більше {max} гравців не можна."
LEFT_LOBBY = ":wave: {name} іде з вечері - не цього разу."
NOT_IN_LOBBY = "Ти не записаний у цю гру або вона вже почалась."
GROUP_ONLY = "Ця команда працює лише в групі."
PRIVATE_ONLY = "Ця команда працює лише в особистих повідомленнях з ботом."
ADMIN_ONLY = ":lock: Це може зробити лише адміністратор чату."
NO_GAME = "Зараз у чаті немає гри."
FORCE_START_FEW = "Замало гравців: потрібно щонайменше {min}."
GAME_STOPPED = ":no: Гру зупинено адміністратором."
GAME_RESUMED = ":refresh: Бот перезапустився. Продовжуємо гру з початку поточної фази."
GAME_CRASHED = ":no: У грі сталася помилка, і її довелося зупинити. Предмети повернуто в інвентар."


# ---------- старт гри та ролі ----------

def game_started(n: int, composition: list[str]) -> str:
    return (
        f":fire: <b>ГРУ РОЗПОЧАТО!</b>\n\n"
        f":people: Гравців: <b>{n}</b>\n"
        ":lock: Кожен отримав роль в особисті.\n\n"
        "<b>Хто в місті:</b>\n" + "\n".join(composition)
    )


def role_card(role_key: str, pocket: list[str], allies: list[str]) -> str:
    text = [
        ":theater: <b>ТВОЯ РОЛЬ</b>",
        "",
        f"<tg-spoiler><b>{role_title(role_key)}</b></tg-spoiler>",
        f"Сторона: {team_title(role_key)}",
        "",
        f"<blockquote>{role_description(role_key)}</blockquote>",
    ]
    if allies:
        text += ["", ":evil: <b>Твоя сім'я:</b>", *[f"{a}" for a in allies],
                 "<i>Пиши мені сюди - я передам повідомлення своїм.</i>"]
    if pocket:
        text += ["", ":bag: <b>При собі:</b> " + ", ".join(item_title(i) for i in pocket)]
    return "\n".join(text)


# ---------- ніч ----------

def night_start(day: int, alive: list[tuple[int, str]]) -> str:
    return (
        f":night: <b>НІЧ {day}</b>\n\n"
        "<blockquote>Палермо засинає. У порту шепочуться, на вулицях гасне світло…</blockquote>\n"
        ":lock: Хто має нічні справи - перевірте особисті.\n\n"
        f":people: <b>Живі ({len(alive)}):</b>\n{numbered(alive)}"
    )


NIGHT_PROMPTS = {
    "kill": ":evil: <b>Кого мафія вб'є цієї ночі?</b>",
    "heal": ":znaharka: <b>Кого лікуватимеш цієї ночі?</b>",
    "check": ":harakternyk: <b>Кого перевіриш?</b>",
    "saber": ":harakternyk: Або вистрілити <i>(лише раз за гру)</i>:",
    "watch": ":storozh: <b>До кого підеш цієї ночі?</b>",
    "compare": ":kobzar: <b>Кого порівняєш?</b> Обери першого.",
    "compare2": ":kobzar: А тепер другого - порівняємо з <b>{first}</b>.",
    "lure": ":mavka: <b>З ким проведеш ніч?</b>",
    "wolf": ":vovkulaka: <b>Кого маніяк уб'є цієї ночі?</b>",
    "pitchfork": ":pitchfork: У тебе є заточка. Кого приберемо? <i>(необов'язково)</i>",
    "ckill": ":skull: <b>Кого приберемо цієї ночі?</b>",
}

# Для власних ролей чату — нейтральні підказки (без згадок Мавки, Знахарки тощо).
CUSTOM_NIGHT_PROMPTS = {
    "kill": ":evil: <b>Кого мафія вб'є цієї ночі?</b>",
    "ckill": ":skull: <b>Кого приберемо цієї ночі?</b>",
    "heal": ":heal: <b>Кого захистиш цієї ночі?</b>",
    "check": ":check: <b>Кого перевіриш?</b>",
    "lure": ":lock: <b>Кого затримаєш цієї ночі?</b>",
    "watch": ":eye: <b>За ким стежитимеш?</b>",
}

NIGHT_CHOSEN = ":ok: Обрано: <b>{target}</b>"
NIGHT_EXPIRED = ":hourglass: Ніч минула, вибір не зроблено."
NIGHT_BAD_TARGET = "Цю ціль обрати не можна."
NIGHT_NOT_NOW = "Зараз не час для цього."
EVIL_VOTE_RELAY = ":evil: {actor} пропонує жертву: {target}."
EVIL_CHAT = ":evil: <b>{name}:</b> {text}"
SKIP_BUTTON = "Пропустити"


# ---------- ранок ----------

DEATH_CAUSES = {
    "custom": "не дожили до ранку",
    "evil": "мафія не залишила шансів",
    "wolf": "не пережили зустрічі з маніяком",
    "saber": "впали від пострілу комісара",
    "pitchfork": "не помітили заточки в темряві",
}


def morning(day: int, deaths: list[tuple[int, str, str, str | None]], saved_count: int) -> str:
    """deaths: (uid, name, cause, role_key або None, якщо ролі приховано)."""
    lines = [f":morning: <b>РАНОК {day}</b>", "",
             "<blockquote>Над Палермо світає, місто прокидається…</blockquote>"]
    if not deaths:
        lines.append(":dove: Цієї ночі всі живі! Мафія лишилась без роботи.")
    for uid, name, cause, role_key in deaths:
        role_part = f"\n    <i>Роль: {role_title(role_key)}</i>" if role_key else ""
        lines.append(f":coffin: {mention(uid, name)} - {DEATH_CAUSES.get(cause, 'не дожили до ранку')}.{role_part}")
    if saved_count:
        lines.append(f"\n:sparkle: Цієї ночі когось дивом врятували ({saved_count}).")
    return "\n".join(lines)


YOU_DIED = ":coffin: Тебе вбили цієї ночі. Можеш спостерігати, але мовчи - мертві не говорять."
YOU_SAVED = {
    "heal": ":znaharka: На тебе напали, але лікар встиг тебе врятувати!",
    "obereg": ":obereg: На тебе напали, але талісман захистив! Удача цього разу на твоєму боці.",
    "kum": ":kum: На тебе напали, але ти, щасливчику, як завжди, викрутився!",
}
YOU_LURED = ":mavka: Цієї ночі тебе відволікли - твоя дія не спрацювала."
GARLIC_WORKED = ":garlic: Коханка хотіла провести з тобою ніч, але твій парфум її відлякав!"
CHECK_RESULT = {
    True: ":harakternyk: {target} - :village: <b>мирний житель</b>.",
    False: ":harakternyk: {target} - <b>НЕ мирний!</b> :evil:",
}
COMPARE_RESULT = {True: ":kobzar: {a} і {b} - <b>з одного боку</b>.", False: ":kobzar: {a} і {b} - <b>з різних боків</b>."}
WATCH_RESULT = ":storozh: До {target} цієї ночі приходили: {visitors}"
WATCH_NOBODY = ":storozh: До {target} цієї ночі ніхто не приходив."
CANDLE_RESULT = ":candle: Ліхтарик вихопив із темряви гостей. До тебе вночі приходили: {visitors}"
NEW_LEADER = ":vidma: Ти тепер Дон - твоє слово вирішальне."


# ---------- день і голосування ----------

DAY_START = ":discuss: <b>ОБГОВОРЕННЯ</b> · {time}\nХто підозрілий? Хто вночі не спав?"
VOTE_START = ":vote: <b>ГОЛОСУВАННЯ!</b>\nКожен живий голосує в особистих · {time}"
VOTE_PROMPT = ":vote: <b>Кого стратити?</b>"
HONEY_BUTTON = "Сигара Дона: голос ×2"
HONEY_USED = ":honey: Ти запалив сигару Дона - твій голос сьогодні важить більше!"
HONEY_FAIL = "Сигари немає або її вже викурено."
VOTE_CAST = ":ok: Твій голос: <b>{target}</b>"
VOTE_SKIP_CAST = ":ok: Твій голос: нікого не страчувати."
VOTE_ANNOUNCE = ":vote: {voter} → {target}"
VOTE_ANNOUNCE_SKIP = ":vote: {voter} → :skip: нікого"
VOTE_ANNOUNCE_SECRET = ":secret: Хтось проголосував · {count}/{total}"
VOTE_EXPIRED = ":hourglass: Голосування завершилось."
VOTE_NOBODY = ":dove: Місто не дійшло згоди - сьогодні нікого не стратять."


def vote_results(rows: list[tuple[str, int]]) -> str:
    """rows: (підпис, голоси) від найбільшого."""
    if not rows:
        return ":stats: <b>ПІДСУМКИ</b>\n\nніхто не голосував"
    top = max(c for _, c in rows) or 1
    lines = [":stats: <b>ПІДСУМКИ ГОЛОСУВАННЯ</b>", ""]
    for label, count in rows:
        lines.append(f"{label}\n<code>{bar(count, top, 8)}</code> {count}")
    return "\n".join(lines)


CONFIRM_ASK = ":rope: <b>ВИРОК</b>\n\nМісто вирішує долю: {name}. Стратити?\n\n:like: {yes}   ·   :dislike: {no}"
CONFIRM_YES = "Стратити"
CONFIRM_NO = "Помилувати"
CONFIRM_NOT_ALLOWED = "Голосувати можуть лише живі гравці, крім самого підсудного."
CONFIRM_THANKS = "Голос враховано."
PARDON = ":dove: Місто змилувалось: {name} лишається жити. ({yes} :like: / {no} :dislike:)"
LYNCHED = ":rope: Місто винесло вирок: {name} страчено.{role}"
HORSESHOE_SAVED = ":horseshoe: Під'їхав чорний «Опель» - і {name} зникає з площі до вироку!"
FOOL_WON = ":duren: Та це ж був Самогубець! Він хотів цього - і переміг. Гра триває."


# ---------- кінець гри ----------

WINNER_TITLES = {
    Team.VILLAGE: ":village: <b>Перемогли мирні жителі!</b> Мафію вигнали з Палермо.",
    Team.EVIL: ":evil: <b>Перемогла мафія!</b> Палермо тепер під контролем сім'ї.",
    Team.WOLF: ":vovkulaka: <b>Переміг Маніяк!</b> Лишився лише він.",
    "draw": ":candle: <b>Нічия.</b> На вулицях Палермо не лишилось нікого…",
}
WIN_SCENES = {Team.VILLAGE: "win_village", Team.EVIL: "win_evil", Team.WOLF: "win_wolf", "draw": "draw"}


def game_over(winner: str, winners: list[str], others: list[str], days: int) -> str:
    parts = [f":trophy: <b>ГРУ ЗАВЕРШЕНО</b> · днів: {days}", "", WINNER_TITLES.get(winner, str(winner)), ""]
    if winners:
        parts += [":party: <b>Переможці:</b>", "<blockquote>" + "\n".join(winners) + "</blockquote>"]
    if others:
        parts += ["<b>Решта міста:</b>", "<blockquote expandable>" + "\n".join(others) + "</blockquote>"]
    return "\n".join(parts)


REWARD_PM = "{result}\nНагорода: <b>+{amount}</b> {shagy}"
RESULT_WIN = ":trophy: <b>Перемога!</b>"
RESULT_LOSE = ":dice: Цього разу не пощастило."


# ---------- профіль ----------

def profile(name: str, shagy: int, cherv: int, vip_until: str | None, games: int, wins: int,
            inventory: list[str]) -> str:
    rate = round(wins * 100 / games) if games else 0
    lines = [
        f":house: <b>{escape(name)}</b>" + (" :vip:" if vip_until else ""),
        "",
        f"{SHAGY} Ліри: <b>{shagy}</b>",
        f"{CHERV} Золоті монети: <b>{cherv}</b>",
        f":vip: VIP до: <b>{vip_until}</b>" if vip_until else ":vip: VIP: немає",
        "",
        f":dice: Ігор: <b>{games}</b>   :trophy: Перемог: <b>{wins}</b>",
        f"<code>{bar(rate, 100)}</code> {rate}%",
        "",
        ":bag: <b>Арсенал:</b>",
        "<blockquote>" + ("\n".join(inventory) if inventory else "порожньо") + "</blockquote>",
    ]
    return "\n".join(lines)


DAILY_OK = ":gift: Дон передав тобі конверт: <b>+{amount}</b> {shagy}! Приходь завтра."
DAILY_WAIT = ":timer: Конверт уже отримано. Наступний - через <b>{left}</b>."
TOP_HEAD = ":trophy: <b>НАЙПОВАЖНІШІ СИНЬЙОРИ</b>\n"
TOP_MEDALS = (":gold:", ":silver:", ":bronze:")
TOP_EMPTY = "Тут ще ніхто не грав. Почніть з /game!"
PROMO_USAGE = "Напиши так: <code>/promo КОД</code>"
PROMO_ERRORS = {
    "not_found": ":no: Такого промокоду немає.",
    "used": "Ти вже активував цей промокод.",
    "exhausted": ":hourglass: Промокод уже вичерпано.",
}


def promo_ok(shagy: int, cherv: int, vip_days: int) -> str:
    parts = []
    if shagy:
        parts.append(f"+{shagy} {SHAGY}")
    if cherv:
        parts.append(f"+{cherv} {CHERV}")
    if vip_days:
        parts.append(f":vip: VIP +{vip_days} дн.")
    return ":party: Промокод активовано: " + (", ".join(parts) or "нічого")


# ---------- чорний ринок ----------

def shop(balance: int, inventory: dict[str, int], slots: int) -> str:
    lines = [
        ":shop: <b>ЧОРНИЙ РИНОК</b>",
        "",
        f"Твій гаманець: <b>{balance}</b> {SHAGY}",
        f"<i>На гру береш до {slots} різних предметів (VIP - більше).</i>",
        "",
    ]
    for item in ITEMS.values():
        have = inventory.get(item.key, 0)
        own = f"  · в арсеналі: {have}" if have else ""
        lines.append(f"{item_title(item.key)} - <b>{item.price}</b> {SHAGY}{own}\n<blockquote>{item.description}</blockquote>")
    return "\n".join(lines)


SHOP_BOUGHT = ":ok: Куплено: {item}. Залишок: {balance} {shagy}"
SHOP_NO_MONEY = "Не вистачає лір. Зіграй ще кілька ігор або забери конверт від Дона."


# ---------- VIP і золоті монети ----------

def vip_menu(cherv: int, vip_until: str | None, vip_price: int, rate: int) -> str:
    status = f":vip: У тебе VIP до <b>{vip_until}</b>." if vip_until else ":vip: VIP ще немає."
    return (
        f":vip: <b>VIP-ЛОЖА</b>\n\n"
        "<blockquote>:fire: ×1.5 лір за кожну гру\n"
        ":gift: щоденний конверт 120 :shagy: замість 50\n"
        ":bag: +1 предмет у кишеню на гру\n"
        ":vip: корона в профілі</blockquote>\n"
        f"{status}\n"
        f"{CHERV} Золотих монет у гаманці: <b>{cherv}</b>\n\n"
        f"VIP можна купити за зірки :star: або за {vip_price} {CHERV}.\n"
        f"Обмін: 1 {CHERV} = {rate} {SHAGY}."
    )


VIP_BOUGHT = ":vip: VIP активовано до {until}! Сім'я пам'ятає своїх друзів."
VIP_NO_CHERV = "Не вистачає золотих монет."
CHERV_BOUGHT = ":cherv: Зараховано {amount} золотих монет. Grazie за підтримку!"
EXCHANGED = ":refresh: Обміняно {cherv} {cherv_icon} на {shagy} {shagy_icon}."
PAYMENT_UNKNOWN = "Невідомий товар. Спробуй ще раз через /vip."


# ---------- налаштування чату ----------

ITEM_KEYS = tuple(ITEMS)


RATIO_LABELS = {  # розмір сім'ї → (емодзі, підпис)
    "few": ("upyr", "Мала"),
    "normal": ("vidma", "Звична"),
    "many": ("blood", "Велика"),
}
RATIO_HINTS = {"few": "1 на 4-5 гравців", "normal": "1 на 3-4 гравці", "many": "1 на 2-3 гравці"}
PLAYER_LABELS = {"min_players": ("people", "Мінімум"), "max_players": ("people", "Максимум")}


def settings_home(chat_title: str, s) -> str:
    """s - GroupSettings: коротке зведення поточних налаштувань."""
    on, off = ":ok:", ":no:"
    items = f"{on} {len(ITEM_KEYS) - len(s.disabled_items)} з {len(ITEM_KEYS)}" if s.items_enabled else off
    omerta = [name for flag, name in ((s.omerta_dead, "мертві"), (s.omerta_night, "ніч")) if flag]
    return (
        ":settings: <b>Налаштування сім'ї</b>\n"
        f"<i>{escape(chat_title or 'ваш чат')}</i>\n\n"
        f"{CATCHPHRASE}, доне! Тут вирішується, як я вестиму гру у вашому чаті. "
        "Зміни діють з наступної гри.\n\n"
        "<blockquote>"
        f":night: Ніч {fmt_seconds(s.night_time)} · :discuss: День {fmt_seconds(s.day_time)}\n"
        f":vidma: Сім'я: {RATIO_LABELS[s.mafia_ratio][1].lower()} · :people: {s.min_players}-{s.max_players} гравців\n"
        f":vote: {'таємне' if s.secret_vote else 'відкрите'} голосування · :bag: Арсенал: {items}\n"
        f":secret: Омерта: {', '.join(omerta) if omerta else 'вимкнена'}"
        "</blockquote>"
    )


SETTINGS_MODULES = [
    ("timers", "timer", "Таймери"),
    ("roles", "theater", "Хто є хто"),
    ("vote", "vote", "Голосування"),
    ("items", "bag", "Арсенал"),
]
SETTINGS_CUSTOM_BTN = "Кастомні налаштування"
SETTINGS_CUSTOM_MODULES = [
    ("lobby", "bell", "Реєстрація"),
    ("family", "vidma", "Розмір сім'ї"),
    ("omerta", "secret", "Омерта"),
]
SETTINGS_CUSTOM_HEAD = (
    ":tools: <b>Кастомні налаштування</b>\n\n"
    "Тут сім'я грає за власними правилами: як збирати гравців, скільки мафії за столом, закон мовчання "
    "і власні ролі вашого чату."
)
SETTINGS_RESET_BTN = "Скинути все"
SETTINGS_REFRESH = "Освіжити"
SETTINGS_SENT = ":settings: Доне, налаштування сім'ї чекають на тебе в особистих."
SETTINGS_SENT_BTN = "Відкрити особисті"
SETTINGS_OPEN_PM = (
    ":lock: Налаштування сім'ї обговорюють без свідків. Натисни кнопку, і я відкрию їх в особистих."
)
SETTINGS_OPEN_PM_BTN = "Налаштувати в особистих"
SETTINGS_PICK_CHAT = ":settings: <b>Налаштування сім'ї</b>\n\nОбери чат, який налаштовуємо:"
SETTINGS_NO_CHATS = (
    ":settings: Напиши /settings у групі, де ти адмін, і я надішлю панель сюди."
)
SETTINGS_TIMERS_HEAD = ":timer: <b>Таймери</b>\n\nСкільки триває кожна фаза гри. Тисни −/+."
SETTINGS_LOBBY_HEAD = (
    ":bell: <b>Реєстрація</b>\n\nСкільки чекаємо на гравців, чи закріплювати запрошення в чаті "
    "і хто може почати гру достроково. Для закріплення боту потрібне право закріплювати повідомлення."
)
SETTINGS_ROLES_HEAD = (
    ":theater: <b>Хто є хто</b>\n\nЗелені - в грі, червоні - вимкнені. Дон, Мафія і Мирний житель - обов'язкові. "
    "Власні ролі сім'ї створюються кнопкою нижче."
)
SETTINGS_FAMILY_HEAD = (
    ":vidma: <b>Розмір сім'ї</b>\n\nСкільки мафії за столом і скільки гравців потрібно для гри.\n"
    + "\n".join(f":{emo}: {label}: {RATIO_HINTS[key]}" for key, (emo, label) in RATIO_LABELS.items())
)
SETTINGS_VOTE_HEAD = ":vote: <b>Голосування</b>\n\nЯк гравці голосують і що дізнаються про загиблих."
SETTINGS_OMERTA_HEAD = (
    ":secret: <b>Омерта</b>\n\nЗакон мовчання: я видаляю повідомлення тих, кому говорити не можна. "
    "Для цього боту потрібне право видаляти повідомлення."
)
SETTINGS_ITEMS_HEAD = (
    ":bag: <b>Арсенал</b>\n\nЯкі речі з чорного ринку можна пронести в гру. Зелені - дозволені, червоні - під забороною."
)
SETTINGS_RESET_HEAD = (
    ":skip: <b>Скинути все?</b>\n\nТаймери, ролі, арсенал і решта налаштувань повернуться до звичних. "
    "Власні ролі залишаться."
)
SETTINGS_RESET_DONE = "Налаштування скинуто"
RESET_YES = "Так, скинути"
# Ключ таймера → (емодзі, підпис)
TIMER_NAMES = {
    "night_time": ("night", "Ніч"),
    "day_time": ("discuss", "Обговорення"),
    "vote_time": ("vote", "Голосування"),
    "confirm_time": ("rope", "Вирок"),
}
REG_TIMER = ("timer", "Реєстрація")
# Перемикач → ((емодзі, підпис) коли вимкнено, (емодзі, підпис) коли увімкнено)
TOGGLE_LABELS = {
    "hide_dead_roles": (("eye", "Ролі загиблих: показувати"), ("secret", "Ролі загиблих: приховувати")),
    "secret_vote": (("vote", "Голосування: відкрите"), ("secret", "Голосування: таємне")),
    "items_enabled": (("skip", "Арсенал: закритий"), ("bag", "Арсенал: відкритий")),
    "omerta_dead": (("chat", "Мертві: можуть писати"), ("coffin", "Мертві: мовчать")),
    "omerta_night": (("chat", "Уночі: чат відкритий"), ("night", "Уночі: всі мовчать")),
    "pin_lobby": (("bell", "Не закріплювати реєстрацію"), ("bell", "Закріплювати реєстрацію")),
    "start_admins_only": (("people", "Почати раніше: адміни й ведучий"), ("lock", "Почати раніше: лише адміни")),
}


# ---------- власні ролі: майстер і керування ----------

ROLE_TEAM_LABELS = {"village": ("village", "Мирні"), "evil": ("evil", "Мафія"), "wolf": ("moon", "Одинак")}
ROLE_ABILITY_HINTS = {
    "kill": "щоночі вбиває (мафія - разом зі своїми)",
    "heal": "щоночі рятує когось від смерті",
    "check": "дізнається, чи гравець мирний",
    "block": "затримує гравця - його нічна дія не спрацює",
    "watch": "дізнається, хто приходив до гравця",
    "none": "нічних дій немає, лише голос удень",
}
ROLE_ABILITY_EMO = {"kill": "skull", "heal": "heal", "check": "check", "block": "lock", "watch": "eye", "none": "dove"}
ROLE_MIN_PLAYERS = (4, 5, 6, 8, 10, 12, 15)

ROLES_CREATE = "Створити роль"
ROLES_MINE = "Мої ролі"
ROLE_CANCEL = "Скасувати"
ROLE_SAVE = "Зберегти"
ROLE_ENABLE = "Увімкнути"
ROLE_DISABLE = "Вимкнути"
ROLE_DELETE = "Видалити"
ROLES_NOT_ADMIN = ":lock: Керувати ролями можуть лише адміністратори того чату."
ROLES_LIMIT = ":no: У чаті вже {max} власних ролей - видали якусь, щоб створити нову."
ROLE_STEP_NAME = (
    ":sparkle: <b>Нова роль</b> для чату <i>{chat}</i>\n\n"
    "Як назвемо роль? Напиши назву (до 24 символів).\n<i>Передумав - /cancel</i>"
)
ROLE_STEP_EMOJI = "Добре! Тепер надішли <b>одне емодзі</b> для ролі (можна premium - тоді воно буде анімоване)."
ROLE_STEP_DESC = "Опиши роль одним-двома реченнями (до 200 символів) - це побачить гравець у своїй картці."
ROLE_STEP_TEAM = "За кого грає роль?"
ROLE_STEP_ABILITY = "Що роль уміє вночі?"
ROLE_STEP_MIN = "З якої кількості гравців роль з'являється в грі?"
ROLE_BAD_NAME = "Назва має бути від 1 до 24 символів. Спробуй ще раз."
ROLE_BAD_EMOJI = "Надішли саме емодзі, без літер і цифр."
ROLE_BAD_DESC = "Опис має бути від 1 до 200 символів."
ROLE_CANCELLED = ":no: Створення ролі скасовано."
ROLE_SAVED = ":party: Роль {title} створено! Вона вже в грі - вимкнути можна в /settings → Хто є хто."
ROLE_DELETED = ":ok: Роль видалено."
ROLES_EMPTY = "У цьому чаті ще немає власних ролей."
ROLES_LIST_HEAD = ":theater: <b>Власні ролі</b> чату <i>{chat}</i>\n\nОбери роль, щоб змінити її."


def role_preview(name: str, emoji_html: str, description: str, team: str, ability: str, min_players: int) -> str:
    from bot.engine.roles import ABILITIES

    team_emo, team_label = ROLE_TEAM_LABELS[team]
    return (
        f"{emoji_html} <b>{escape(name)}</b>\n\n"
        f"<blockquote>{escape(description)}</blockquote>\n"
        f":{team_emo}: Сторона: <b>{team_label}</b>\n"
        f":{ROLE_ABILITY_EMO[ability]}: Здатність: <b>{ABILITIES[ability]}</b> - {ROLE_ABILITY_HINTS[ability]}\n"
        f":people: З'являється від <b>{min_players}</b> гравців"
    )


# ---------- кабінет Дона (власник бота) ----------

def owner_home(stats: dict, running: int) -> str:
    return (
        ":vip: <b>КАБІНЕТ ДОНА</b>\n\n"
        "<blockquote>"
        f":people: Гравців: <b>{stats['users']}</b> · :vip: VIP: <b>{stats['vips']}</b>\n"
        f":dice: Ігор: <b>{stats['games']}</b> · за добу: <b>{stats['games_day']}</b>\n"
        f":fire: Зараз за столами: <b>{running}</b>\n"
        f":star: Зірок зароблено: <b>{stats['stars']}</b>"
        "</blockquote>\n\n"
        f"{CATCHPHRASE}, доне. Що робимо сьогодні?"
    )


OWNER_MODULES = [
    ("player", "profile", "Гравець"),
    ("bc", "megaphone", "Розсилка"),
    ("promos", "gift", "Промокоди"),
    ("buys", "star", "Покупки"),
    ("games", "dice", "Ігри"),
    ("design", "sparkle", "Оформлення"),
]
OWNER_REFRESH = "Освіжити"
OWNER_ASK_PLAYER = ":profile: Надішли ID гравця (число). Передумав - /cancel"
OWNER_BAD_ID = "Потрібен ID - лише цифри."
OWNER_NO_PLAYER = ":no: Такого гравця я не знаю."
OWNER_OTHER_PLAYER = "Інший гравець"
OWNER_BLOCK = "Заблокувати"
OWNER_UNBLOCK = "Розблокувати"
OWNER_NO_FUNDS = "Баланс пішов би в мінус"
OWNER_CANCELLED = "Скасовано."
OWNER_ASK_BC = (
    ":megaphone: Надішли повідомлення для розсилки: текст, фото, відео - що завгодно. "
    "Спершу покажу, як воно виглядатиме. Передумав - /cancel"
)
OWNER_BC_CONFIRM = ":megaphone: Ось так побачать гравці. Розіслати <b>{count}</b> гравцям?"
OWNER_BC_GO = "Розіслати"
OWNER_BC_RUNNING = ":megaphone: Розсилаю {count} гравцям…"
OWNER_BC_DONE = ":ok: Доставлено: {sent}/{total}"
OWNER_PROMOS_HEAD = ":gift: <b>Промокоди</b>\n\n"
OWNER_PROMOS_EMPTY = "Промокодів ще немає."
OWNER_PROMO_NEW = "Новий промокод"
OWNER_ASK_PROMO = (
    ":gift: Надішли одним рядком:\n<code>КОД ЛІРИ МОНЕТИ VIP_ДНІВ ВИКОРИСТАНЬ</code>\n"
    "Наприклад: <code>BONJORNO 500 0 0 100</code>. Передумав - /cancel"
)
OWNER_PROMO_BAD = "Не розібрав. Формат: <code>КОД ЛІРИ МОНЕТИ VIP_ДНІВ ВИКОРИСТАНЬ</code>"
OWNER_PROMO_EXISTS = ":no: Такий код уже існує."
OWNER_PROMO_CREATED = ":ok: Промокод <code>{code}</code> створено."
OWNER_BUYS_HEAD = ":star: <b>Останні покупки</b>\n\n"
OWNER_BUYS_EMPTY = "Покупок ще не було."
OWNER_REFUND_ASK = ":star: Повернути <b>{stars}</b> зірок гравцю <code>{user}</code> за «{product}»?"
OWNER_REFUND_GO = "Повернути зірки"
OWNER_GAMES_HEAD = ":dice: <b>Ігри зараз</b>\n\n"
OWNER_GAMES_EMPTY = "Зараз за столами порожньо."
OWNER_STOP_ASK = ":dice: Зупинити гру в <b>{chat}</b>? Предмети повернуться гравцям."
OWNER_STOP_GO = "Зупинити гру"
OWNER_STOPPED = "Гру зупинено"


def owner_player(u) -> str:
    vip = f"до {u.vip_until:%d.%m.%Y}" if u.is_vip else "немає"
    status = "\n:lock: <b>Заблокований</b>" if u.blocked else ""
    return (
        f":profile: <b>{escape(u.name or 'Без імені')}</b>"
        f"{' @' + escape(u.username) if u.username else ''}\n"
        f"ID <code>{u.id}</code>\n\n"
        "<blockquote>"
        f"{SHAGY} Ліри: <b>{u.shagy}</b>\n"
        f"{CHERV} Золоті монети: <b>{u.chervintsi}</b>\n"
        f":vip: VIP: <b>{vip}</b>\n"
        f":dice: Ігор: <b>{u.games}</b> · :trophy: перемог: <b>{u.wins}</b>"
        f"</blockquote>{status}"
    )
