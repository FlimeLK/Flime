"""Усі тексти бота. Українською, у стилі «Мафія: Хутір».

Мітки :ключ: (наприклад :night:, :vidma:) перед надсиланням перетворюються на анімовані
емодзі — див. bot/ui/emoji.py і bot/ui/safe.py. У тексті кнопок і спливних вікон HTML не
працює, там мітки стають звичайними емодзі.
"""

from __future__ import annotations

from html import escape

from bot.engine.items import ITEMS
from bot.engine.roles import ROLES, Team

GAME_NAME = "Мафія: Хутір"
SHAGY = ":shagy:"
CHERV = ":cherv:"
LINE = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈"

TEAM_TITLES = {
    Team.VILLAGE: ":village: Громада",
    Team.EVIL: ":evil: Нечисть",
    Team.WOLF: ":vovkulaka: Вовкулака",
    Team.FOOL: ":duren: Іван-дурень",
}


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{escape(name)}</a>'


def role_title(key: str) -> str:
    return f":{key}: {ROLES[key].name}"


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

START = (
    f":sunflower: <b>{GAME_NAME.upper()}</b>\n"
    f"{LINE}\n"
    "<blockquote>На тихому хуторі завелася нечисть. Вдень усі — добрі сусіди, "
    "а вночі хтось не повертається з вечорниць…</blockquote>\n"
    ":people: Додай мене в групу — і я буду ведучим.\n"
    ":dice: У групі напиши /game і збирай громаду.\n\n"
    ":profile: /profile — твоя хата і гаманець\n"
    ":shop: /shop — ярмарок предметів\n"
    ":gift: /daily — щоденний гостинець\n"
    ":vip: /vip — VIP і червінці\n"
    ":rules: /rules — правила та ролі"
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


def rules() -> str:
    parts = [
        f":rules: <b>ПРАВИЛА «{GAME_NAME.upper()}»</b>",
        LINE,
        ":night: <b>Ніч.</b> Хто має нічну справу, отримує кнопки в особисті. "
        "Нечисть обирає жертву, знахарка лікує, характерник перевіряє.",
        ":morning: <b>Ранок.</b> Громада дізнається, хто не дожив до світанку.",
        ":discuss: <b>День.</b> Обговорення: хто підозрілий, хто вночі не спав?",
        ":vote: <b>Голосування</b> в особистих, потім громада підтверджує страту :like:/:dislike:.",
        "",
        ":trophy: <b>Перемога</b>",
        "<blockquote>Громада — коли вся нечисть і вовкулака мертві.\n"
        "Нечисть — коли її не менше, ніж решти.\n"
        "Вовкулака — коли лишиться сам на сам з кимось.\n"
        "Іван-дурень — якщо його стратять.</blockquote>",
    ]
    for team in (Team.VILLAGE, Team.EVIL, Team.WOLF, Team.FOOL):
        lines = [f"{role_title(r.key)} — {ROLE_DESCRIPTIONS[r.key]}" for r in ROLES.values() if r.team == team]
        parts.append(f"<b>{TEAM_TITLES[team]}</b>\n<blockquote expandable>" + "\n".join(lines) + "</blockquote>")
    items = [f"{item_title(i.key)} — {i.description}" for i in ITEMS.values()]
    parts.append(":bag: <b>Предмети</b> (купуються в /shop і самі беруться в гру)\n"
                 "<blockquote expandable>" + "\n".join(items) + "</blockquote>")
    return "\n".join(parts)


# ---------- лобі ----------

def lobby(players: list[tuple[int, str]], seconds: int, min_players: int) -> str:
    n = len(players)
    need = max(0, min_players - n)
    status = f"ще потрібно: <b>{need}</b>" if need else ":ok: можна починати"
    lines = [
        ":sunflower: <b>ЗБИРАЄТЬСЯ ГРОМАДА!</b>",
        LINE,
        f":timer: До початку: <b>{fmt_seconds(seconds)}</b>",
        f":people: Записались: <b>{n}</b> · {status}",
        f"<code>{bar(min(n, min_players), min_players)}</code>",
        "",
        numbered(players) if players else "<i>Поки нікого… Будь першим!</i>",
    ]
    return "\n".join(lines)


JOIN_BUTTON = "Долучитися до гри"
LOBBY_REMINDER = ":bell: До початку гри лишилось <b>{left}</b>! Хто ще не записався — тисни «Долучитися»."
LOBBY_NOT_ENOUGH = ":skip: Не зібралось навіть {min} людей. Гру скасовано — хутір лягає спати."
LOBBY_ALREADY = ":dice: Гра в цьому чаті вже йде. Дочекайся наступної."
JOINED_PM = ":ok: Тебе записано на гру в чаті <b>{chat}</b>. Чекай на свою роль!"
JOIN_ALREADY_HERE = "Ти вже записаний на цю гру."
JOIN_IN_OTHER = "Ти вже граєш в іншому чаті. Одна гра за раз!"
JOIN_CLOSED = "Реєстрацію вже закрито."
JOIN_FULL = "Громада переповнена — більше {max} гравців не можна."
LEFT_LOBBY = ":wave: {name} іде додому — не цього разу."
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
        f":fire: <b>ГРУ РОЗПОЧАТО!</b>\n{LINE}\n"
        f":people: Гравців: <b>{n}</b>\n"
        ":lock: Кожен отримав роль в особисті.\n\n"
        "<b>Склад хутора:</b>\n" + "\n".join(composition)
    )


def role_card(role_key: str, pocket: list[str], allies: list[str]) -> str:
    r = ROLES[role_key]
    text = [
        ":mask: <b>ТВОЯ РОЛЬ</b>",
        LINE,
        f"<tg-spoiler><b>{role_title(role_key)}</b></tg-spoiler>",
        f"Сторона: {TEAM_TITLES[r.team]}",
        "",
        f"<blockquote>{ROLE_DESCRIPTIONS[role_key]}</blockquote>",
    ]
    if allies:
        text += ["", ":evil: <b>Твоя нечиста братія:</b>", *[f"• {a}" for a in allies],
                 "<i>Пиши мені сюди — я передам повідомлення своїм.</i>"]
    if pocket:
        text += ["", ":bag: <b>У кишені:</b> " + ", ".join(item_title(i) for i in pocket)]
    return "\n".join(text)


# ---------- ніч ----------

def night_start(day: int, alive: list[tuple[int, str]]) -> str:
    return (
        f":night: <b>НІЧ {day}</b>\n{LINE}\n"
        "<blockquote>Хутір засинає. Собаки гавкають, у лісі щось шарудить…</blockquote>\n"
        ":lock: Хто має нічні справи — перевірте особисті.\n\n"
        f":people: <b>Живі ({len(alive)}):</b>\n{numbered(alive)}"
    )


NIGHT_PROMPTS = {
    "kill": ":evil: <b>Кого нечисть забере цієї ночі?</b>",
    "heal": ":znaharka: <b>Кого лікуватимеш цієї ночі?</b>",
    "check": ":harakternyk: <b>Кого перевіриш?</b>",
    "saber": ":harakternyk: Або вдарити шаблею <i>(лише раз за гру)</i>:",
    "watch": ":storozh: <b>Чию хату стерегтимеш?</b>",
    "compare": ":kobzar: <b>Про кого співатимеш?</b> Обери першого.",
    "compare2": ":kobzar: А тепер другого — поруч із <b>{first}</b>.",
    "lure": ":mavka: <b>Кого заманиш до ставка?</b>",
    "wolf": ":vovkulaka: <b>Кого вовкулака розірве цієї ночі?</b>",
    "pitchfork": ":pitchfork: У тебе є вила. Кого проштрикнеш? <i>(необов'язково)</i>",
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
    "evil": "нечисть забрала в темряву",
    "wolf": "не пережили зустрічі з вовкулакою",
    "saber": "впали від шаблі характерника",
    "pitchfork": "наткнулись на вила",
}


def morning(day: int, deaths: list[tuple[int, str, str, str | None]], saved_count: int) -> str:
    """deaths: (uid, name, cause, role_key або None, якщо ролі приховано)."""
    lines = [f":morning: <b>РАНОК {day}</b>", LINE,
             "<blockquote>Півні проспівали, хутір прокидається…</blockquote>"]
    if not deaths:
        lines.append(":dove: Цієї ночі всі живі! Нечисть лишилась голодною.")
    for uid, name, cause, role_key in deaths:
        role_part = f"\n    <i>Роль: {role_title(role_key)}</i>" if role_key else ""
        lines.append(f":coffin: {mention(uid, name)} — {DEATH_CAUSES.get(cause, 'не дожили до ранку')}.{role_part}")
    if saved_count:
        lines.append(f"\n:sparkle: Цієї ночі когось дивом врятували ({saved_count}).")
    return "\n".join(lines)


YOU_DIED = ":coffin: Тебе вбили цієї ночі. Можеш спостерігати, але мовчи — мертві не говорять."
YOU_SAVED = {
    "heal": ":znaharka: На тебе напали, але знахарка встигла тебе вилікувати!",
    "obereg": ":obereg: На тебе напали, але оберіг захистив! Він розсипався на порох.",
    "kum": ":kum: На тебе напали, але ти, кум, як завжди, викрутився!",
}
YOU_LURED = ":mavka: Мавка заманила тебе до ставка — цієї ночі ти нічого не встиг."
GARLIC_WORKED = ":garlic: Мавка кликала тебе до ставка, але від часнику аж скривилась!"
CHECK_RESULT = {
    True: ":harakternyk: {target} — з :village: <b>Громади</b>.",
    False: ":harakternyk: {target} — <b>НЕ з Громади!</b> :evil:",
}
COMPARE_RESULT = {True: ":kobzar: {a} і {b} — <b>з одного боку</b>.", False: ":kobzar: {a} і {b} — <b>з різних боків</b>."}
WATCH_RESULT = ":storozh: До хати {target} цієї ночі приходили: {visitors}"
WATCH_NOBODY = ":storozh: До хати {target} цієї ночі ніхто не приходив."
CANDLE_RESULT = ":candle: Свічка догоріла. До тебе вночі приходили: {visitors}"
NEW_LEADER = ":evil: Ти тепер ватажок нечисті — твоє слово вирішальне."


# ---------- день і голосування ----------

DAY_START = ":discuss: <b>ОБГОВОРЕННЯ</b> · {time}\nХто підозрілий? Хто вночі не спав?"
VOTE_START = ":vote: <b>ГОЛОСУВАННЯ!</b>\nКожен живий голосує в особистих · {time}"
VOTE_PROMPT = ":vote: <b>Кого громада має стратити?</b>"
HONEY_BUTTON = "Мед: мій голос ×2"
HONEY_USED = ":honey: Мед з'їдено — твій голос сьогодні важить більше!"
HONEY_FAIL = "Меду немає або його вже з'їдено."
VOTE_CAST = ":ok: Твій голос: <b>{target}</b>"
VOTE_SKIP_CAST = ":ok: Твій голос: нікого не страчувати."
VOTE_ANNOUNCE = ":vote: {voter} → {target}"
VOTE_ANNOUNCE_SKIP = ":vote: {voter} → :skip: нікого"
VOTE_ANNOUNCE_SECRET = ":secret: Хтось проголосував · {count}/{total}"
VOTE_EXPIRED = ":hourglass: Голосування завершилось."
VOTE_NOBODY = ":dove: Громада не дійшла згоди — сьогодні нікого не стратять."


def vote_results(rows: list[tuple[str, int]]) -> str:
    """rows: (підпис, голоси) від найбільшого."""
    if not rows:
        return f":stats: <b>ПІДСУМКИ</b>\n{LINE}\nніхто не голосував"
    top = max(c for _, c in rows) or 1
    lines = [":stats: <b>ПІДСУМКИ ГОЛОСУВАННЯ</b>", LINE]
    for label, count in rows:
        lines.append(f"{label}\n<code>{bar(count, top, 8)}</code> {count}")
    return "\n".join(lines)


CONFIRM_ASK = ":rope: <b>ВИРОК</b>\n" + LINE + "\nГромада вирішує долю: {name}. Стратити?\n\n:like: {yes}   ·   :dislike: {no}"
CONFIRM_YES = "Стратити"
CONFIRM_NO = "Помилувати"
CONFIRM_NOT_ALLOWED = "Голосувати можуть лише живі гравці, крім самого підсудного."
CONFIRM_THANKS = "Голос враховано."
PARDON = ":dove: Громада змилувалась: {name} лишається жити. ({yes} :like: / {no} :dislike:)"
LYNCHED = ":rope: Громада винесла вирок: {name} страчено.{role}"
HORSESHOE_SAVED = ":horseshoe: Мотузка обірвалась! У кишені знайшлась підкова на щастя: {name} вціліли."
FOOL_WON = ":duren: Та це ж був Іван-дурень! Він хотів цього — і переміг. Гра триває."


# ---------- кінець гри ----------

WINNER_TITLES = {
    Team.VILLAGE: ":village: <b>Перемогла Громада!</b> Нечисть вигнали з хутора.",
    Team.EVIL: ":evil: <b>Перемогла Нечисть!</b> Хутір тепер належить темряві.",
    Team.WOLF: ":vovkulaka: <b>Переміг Вовкулака!</b> Лишився лише він — і місяць.",
    "draw": ":candle: <b>Нічия.</b> На хуторі не лишилось нікого…",
}
WIN_SCENES = {Team.VILLAGE: "win_village", Team.EVIL: "win_evil", Team.WOLF: "win_wolf", "draw": "draw"}


def game_over(winner: str, winners: list[str], others: list[str], days: int) -> str:
    parts = [f":trophy: <b>ГРУ ЗАВЕРШЕНО</b> · днів: {days}", LINE, WINNER_TITLES.get(winner, str(winner)), ""]
    if winners:
        parts += [":party: <b>Переможці:</b>", "<blockquote>" + "\n".join(winners) + "</blockquote>"]
    if others:
        parts += ["<b>Решта хутора:</b>", "<blockquote expandable>" + "\n".join(others) + "</blockquote>"]
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
        LINE,
        f"{SHAGY} Шаги: <b>{shagy}</b>",
        f"{CHERV} Червінці: <b>{cherv}</b>",
        f":vip: VIP до: <b>{vip_until}</b>" if vip_until else ":vip: VIP: немає · /vip",
        "",
        f":dice: Ігор: <b>{games}</b>   :trophy: Перемог: <b>{wins}</b>",
        f"<code>{bar(rate, 100)}</code> {rate}%",
        "",
        ":bag: <b>Скриня:</b>",
        "<blockquote>" + ("\n".join(inventory) if inventory else "порожньо — зазирни на /shop") + "</blockquote>",
    ]
    return "\n".join(lines)


DAILY_OK = ":gift: Кума передала гостинця: <b>+{amount}</b> {shagy}! Приходь завтра."
DAILY_WAIT = ":timer: Гостинець уже отримано. Наступний — через <b>{left}</b>."
TOP_HEAD = f":trophy: <b>НАЙКРАЩІ НА ХУТОРІ</b>\n{LINE}"
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


# ---------- ярмарок ----------

def shop(balance: int, inventory: dict[str, int], slots: int) -> str:
    lines = [
        ":shop: <b>ЯРМАРОК</b>",
        LINE,
        f"Твій гаманець: <b>{balance}</b> {SHAGY}",
        f"<i>На гру береш до {slots} різних предметів (VIP — більше).</i>",
        "",
    ]
    for item in ITEMS.values():
        have = inventory.get(item.key, 0)
        own = f"  · у скрині: {have}" if have else ""
        lines.append(f"{item_title(item.key)} — <b>{item.price}</b> {SHAGY}{own}\n<blockquote>{item.description}</blockquote>")
    return "\n".join(lines)


SHOP_BOUGHT = ":ok: Куплено: {item}. Залишок: {balance} {shagy}"
SHOP_NO_MONEY = "Не вистачає шагів. Зіграй ще кілька ігор або візьми /daily."


# ---------- VIP і червінці ----------

def vip_menu(cherv: int, vip_until: str | None, vip_price: int, rate: int) -> str:
    status = f":vip: У тебе VIP до <b>{vip_until}</b>." if vip_until else ":vip: VIP ще немає."
    return (
        f":vip: <b>VIP НА ХУТОРІ</b>\n{LINE}\n"
        "<blockquote>:fire: ×1.5 шагів за кожну гру\n"
        ":gift: щоденний гостинець 120 :shagy: замість 50\n"
        ":bag: +1 предмет у кишеню на гру\n"
        ":vip: корона в профілі</blockquote>\n"
        f"{status}\n"
        f"{CHERV} Червінців у гаманці: <b>{cherv}</b>\n\n"
        f"VIP можна купити за зірки :star: або за {vip_price} {CHERV}.\n"
        f"Обмін: 1 {CHERV} = {rate} {SHAGY}."
    )


VIP_BOUGHT = ":vip: VIP активовано до {until}! Дякуємо, що підтримуєш хутір."
VIP_NO_CHERV = "Не вистачає червінців."
CHERV_BOUGHT = ":cherv: Зараховано {amount} червінців. Дякуємо за підтримку!"
EXCHANGED = ":refresh: Обміняно {cherv} {cherv_icon} на {shagy} {shagy_icon}."
PAYMENT_UNKNOWN = "Невідомий товар. Спробуй ще раз через /vip."


# ---------- налаштування чату ----------

SETTINGS_HEAD = (
    f":settings: <b>НАЛАШТУВАННЯ ГРИ</b>\n{LINE}\n"
    "<i>Зміни діють з наступної гри.</i>"
)
SETTINGS_ROLES_HEAD = (
    f":mask: <b>РОЛІ</b>\n{LINE}\n"
    "<i>Вимкнені ролі не роздаються. Відьма, Упир і Селянин — обов'язкові.</i>"
)
# Ключ таймера → (емодзі, підпис)
TIMER_NAMES = {
    "reg_time": ("timer", "Реєстрація"),
    "night_time": ("night", "Ніч"),
    "day_time": ("discuss", "Обговорення"),
    "vote_time": ("vote", "Голосування"),
    "confirm_time": ("rope", "Вирок"),
}
# Перемикач → ((емодзі, підпис) коли вимкнено, (емодзі, підпис) коли увімкнено)
TOGGLE_LABELS = {
    "hide_dead_roles": (("eye", "Ролі загиблих: показувати"), ("secret", "Ролі загиблих: приховувати")),
    "secret_vote": (("vote", "Голосування: відкрите"), ("secret", "Голосування: таємне")),
    "items_enabled": (("skip", "Предмети: вимкнені"), ("bag", "Предмети: увімкнені")),
}
SETTINGS_CLOSED = ":ok: Налаштування збережено."
