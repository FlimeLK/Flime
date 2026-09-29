"""Панель власника бота (OWNER_IDS у .env). Працює лише в особистих."""

from __future__ import annotations

import asyncio
import logging

import asyncpg
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import economy, keyboards, texts
from bot.config import Settings
from bot.db import payments, promocodes, users
from bot.game.manager import GameManager
from bot.keyboards import OwnCb

router = Router(name="owner")
log = logging.getLogger(__name__)

# Довідка по текстових командах (/owner_help) - усе те саме є кнопками в /owner.
HELP = (
    ":tools: <b>КОМАНДИ ДОНА</b>\n\n"
    "<code>/give ID shagy|cherv СУМА</code> - видати (або мінус - забрати)\n"
    "<code>/vip_give ID ДНІВ</code> - подарувати VIP\n"
    "<code>/block ID</code> · <code>/unblock ID</code>\n"
    "<code>/broadcast ТЕКСТ</code> - розсилка всім (або відповіддю на повідомлення)\n"
    "<code>/promo_new КОД ЛІРИ МОНЕТИ VIP_ДНІВ ВИКОРИСТАНЬ</code>\n"
    "<code>/promo_list</code> · <code>/promo_del КОД</code>\n"
    "<code>/purchases</code> - останні покупки · <code>/refund CHARGE_ID</code> - повернути зірки\n"
    "<code>/games</code> - активні ігри\n"
    "<code>/design</code> - анімовані емодзі та медіа для сцен"
)


class IsOwner(Filter):
    async def __call__(self, message: Message, config: Settings) -> bool:
        return message.chat.type == "private" and message.from_user.id in config.owner_ids


class IsOwnerCb(Filter):
    async def __call__(self, cb: CallbackQuery, config: Settings) -> bool:
        return cb.from_user.id in config.owner_ids


router.message.filter(IsOwner())
router.callback_query.filter(IsOwnerCb())


class OwnerForm(StatesGroup):
    player = State()
    broadcast = State()
    promo = State()


def ints(args: str | None, count: int) -> list[int] | None:
    parts = (args or "").split()
    if len(parts) != count:
        return None
    try:
        return [int(p) for p in parts]
    except ValueError:
        return None


# ================= кабінет Дона (кнопки) =================

async def home_text(pool: asyncpg.Pool, manager: GameManager) -> str:
    return texts.owner_home(await users.stats(pool), len(manager.runners))


@router.message(Command("owner"))
async def cmd_owner(message: Message, state: FSMContext, pool: asyncpg.Pool, manager: GameManager) -> None:
    await state.clear()
    await message.answer(await home_text(pool, manager), reply_markup=keyboards.owner_home())


@router.message(Command("owner_help"))
async def cmd_owner_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("cancel"), StateFilter(OwnerForm))
async def cmd_cancel(message: Message, state: FSMContext, pool: asyncpg.Pool, manager: GameManager) -> None:
    await state.clear()
    await message.answer(await home_text(pool, manager), reply_markup=keyboards.owner_home())


async def _show(cb: CallbackQuery, text: str, markup=None, note: str | None = None) -> None:
    await cb.answer(note)
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=markup)


async def player_card(pool: asyncpg.Pool, user_id: int):
    u = await users.get(pool, user_id)
    if u is None:
        return texts.OWNER_NO_PLAYER, keyboards.owner_back()
    return texts.owner_player(u), keyboards.owner_player(u.id, u.blocked)


@router.callback_query(OwnCb.filter())
async def on_owner(cb: CallbackQuery, callback_data: OwnCb, state: FSMContext, bot: Bot, pool: asyncpg.Pool,
                   manager: GameManager) -> None:
    action, value = callback_data.action, callback_data.value
    note = None
    if action == "home":
        await state.clear()
        await _show(cb, await home_text(pool, manager), keyboards.owner_home())
    elif action == "player":
        await state.set_state(OwnerForm.player)
        await _show(cb, texts.OWNER_ASK_PLAYER, keyboards.owner_back())
    elif action in ("give", "vip", "block", "card"):
        parts = value.split(".")
        if not parts[0].isdigit():
            await cb.answer()
            return
        uid = int(parts[0])
        if action == "give" and len(parts) == 3 and parts[1] in ("shagy", "cherv"):
            currency = "shagy" if parts[1] == "shagy" else "chervintsi"
            if await users.add_balance(pool, uid, currency, int(parts[2])) is None:
                note = texts.OWNER_NO_FUNDS
        elif action == "vip" and len(parts) == 2:
            await users.extend_vip(pool, uid, int(parts[1]))
        elif action == "block":
            u = await users.get(pool, uid)
            if u:
                await users.set_blocked(pool, uid, not u.blocked)
        text, markup = await player_card(pool, uid)
        await _show(cb, text, markup, note)
    elif action == "bc":
        await state.set_state(OwnerForm.broadcast)
        await _show(cb, texts.OWNER_ASK_BC, keyboards.owner_back())
    elif action == "bc_go":
        data = await state.get_data()
        await state.clear()
        if "bc_msg" not in data:
            await cb.answer()
            return
        ids = await users.all_ids(pool)
        await _show(cb, texts.OWNER_BC_RUNNING.format(count=len(ids)))
        sent = await broadcast(bot, ids, from_chat=data["bc_chat"], message_id=data["bc_msg"])
        await cb.message.answer(texts.OWNER_BC_DONE.format(sent=sent, total=len(ids)),
                                reply_markup=keyboards.owner_back())
    elif action in ("promos", "promo_del"):
        if action == "promo_del":
            await promocodes.delete(pool, value)
            note = "🗑"
        rows = await promocodes.list_all(pool)
        lines = [
            f"<code>{texts.escape(r['code'])}</code>: {r['shagy']}{texts.SHAGY} {r['chervintsi']}{texts.CHERV} "
            f"VIP {r['vip_days']}д · {r['uses']}/{r['max_uses']}"
            for r in rows
        ]
        text = texts.OWNER_PROMOS_HEAD + ("\n".join(lines) or texts.OWNER_PROMOS_EMPTY)
        await _show(cb, text, keyboards.owner_promos([r["code"] for r in rows]), note)
    elif action == "promo_new":
        await state.set_state(OwnerForm.promo)
        await _show(cb, texts.OWNER_ASK_PROMO, keyboards.owner_back())
    elif action == "buys":
        rows = await payments.recent(pool, 10)
        lines = [
            f"#{r['id']} · {r['created_at']:%d.%m %H:%M} · <code>{r['user_id']}</code> · "
            f"{texts.escape(r['product'])} · {r['stars']}:star:{' · повернуто' if r['refunded'] else ''}"
            for r in rows
        ]
        refundable = [(r["id"], f"#{r['id']} {r['stars']}⭐") for r in rows if not r["refunded"]]
        text = texts.OWNER_BUYS_HEAD + ("\n".join(lines) or texts.OWNER_BUYS_EMPTY)
        await _show(cb, text, keyboards.owner_buys(refundable))
    elif action in ("refund", "refund_go"):
        purchase = await payments.get_by_id(pool, int(value)) if value.isdigit() else None
        if purchase is None:
            await cb.answer()
            return
        if action == "refund":
            text = texts.OWNER_REFUND_ASK.format(stars=purchase["stars"], user=purchase["user_id"],
                                                 product=texts.escape(purchase["product"]))
            await _show(cb, text, keyboards.owner_confirm(
                texts.OWNER_REFUND_GO, OwnCb(action="refund_go", value=value), "buys"))
        else:
            result = await refund(bot, pool, purchase["charge_id"])
            await _show(cb, result, keyboards.owner_back())
    elif action == "games":
        games = [(chat_id, r.chat_title or str(chat_id)) for chat_id, r in manager.runners.items()]
        lines = [
            f"{texts.escape(r.chat_title or str(chat_id))}: {r.game.phase.value}, "
            f"день {r.game.day}, живих {len(r.game.alive())}/{len(r.game.players)}"
            for chat_id, r in manager.runners.items()
        ]
        text = texts.OWNER_GAMES_HEAD + ("\n".join(lines) or texts.OWNER_GAMES_EMPTY)
        await _show(cb, text, keyboards.owner_games(games))
    elif action in ("stop", "stop_go"):
        runner = manager.get(int(value)) if value.lstrip("-").isdigit() else None
        if runner is None:
            await _show(cb, texts.OWNER_GAMES_HEAD + texts.OWNER_GAMES_EMPTY, keyboards.owner_back())
            return
        if action == "stop":
            text = texts.OWNER_STOP_ASK.format(chat=texts.escape(runner.chat_title or value))
            await _show(cb, text, keyboards.owner_confirm(
                texts.OWNER_STOP_GO, OwnCb(action="stop_go", value=value), "games"))
        else:
            await runner.stop()
            await _show(cb, await home_text(pool, manager), keyboards.owner_home(), texts.OWNER_STOPPED)
    elif action == "design":
        from bot.handlers.design import HELP as DESIGN_HELP

        await _show(cb, DESIGN_HELP, keyboards.owner_back())
    else:
        await cb.answer()


@router.message(OwnerForm.player, F.text)
async def form_player(message: Message, state: FSMContext, pool: asyncpg.Pool) -> None:
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer(texts.OWNER_BAD_ID)
        return
    await state.clear()
    text, markup = await player_card(pool, int(raw))
    await message.answer(text, reply_markup=markup)


@router.message(OwnerForm.broadcast, ~F.text.startswith("/"))
async def form_broadcast(message: Message, state: FSMContext, pool: asyncpg.Pool) -> None:
    await state.update_data(bc_chat=message.chat.id, bc_msg=message.message_id)
    await message.copy_to(message.chat.id)
    count = len(await users.all_ids(pool))
    await message.answer(texts.OWNER_BC_CONFIRM.format(count=count), reply_markup=keyboards.owner_confirm(
        texts.OWNER_BC_GO, OwnCb(action="bc_go"), "home"))


@router.message(OwnerForm.promo, F.text)
async def form_promo(message: Message, state: FSMContext, pool: asyncpg.Pool) -> None:
    parts = message.text.split()
    nums = ints(" ".join(parts[1:]), 4) if len(parts) == 5 else None
    if not nums or min(nums) < 0 or nums[3] == 0:
        await message.answer(texts.OWNER_PROMO_BAD)
        return
    await state.clear()
    ok = await promocodes.create(pool, parts[0], *nums)
    text = texts.OWNER_PROMO_CREATED.format(code=texts.escape(parts[0].upper())) if ok else texts.OWNER_PROMO_EXISTS
    await message.answer(text, reply_markup=keyboards.owner_back())


# ================= спільна логіка =================

async def broadcast(bot: Bot, ids: list[int], *, text: str | None = None, from_chat: int | None = None,
                    message_id: int | None = None) -> int:
    sent = 0
    for uid in ids:
        for attempt in range(2):
            try:
                if message_id is not None:
                    await bot.copy_message(uid, from_chat, message_id)
                else:
                    await bot.send_message(uid, text)
                sent += 1
                break
            except TelegramRetryAfter as e:
                if attempt == 0:
                    await asyncio.sleep(e.retry_after)
            except TelegramAPIError:
                break
        await asyncio.sleep(0.05)  # ~20 повідомлень на секунду
    return sent


async def refund(bot: Bot, pool: asyncpg.Pool, charge_id: str) -> str:
    purchase = await payments.get(pool, charge_id) if charge_id else None
    if purchase is None:
        return ":no: Покупку не знайдено."
    if purchase["refunded"]:
        return "Цю покупку вже повернуто."
    try:
        await bot.refund_star_payment(purchase["user_id"], charge_id)
    except TelegramAPIError as e:
        return f":no: Telegram відмовив: {texts.escape(str(e))}"
    product = economy.PRODUCTS.get(purchase["product"])
    async with pool.acquire() as conn, conn.transaction():
        await payments.mark_refunded(conn, charge_id)
        if product and product.chervintsi:
            # Забираємо стільки золотих монет, скільки лишилось (не йдемо в мінус).
            await conn.execute(
                "UPDATE users SET chervintsi = GREATEST(chervintsi - $2, 0) WHERE id = $1",
                purchase["user_id"], product.chervintsi,
            )
        if product and product.vip_days:
            await users.revoke_vip_days(conn, purchase["user_id"], product.vip_days)
    return f":ok: Повернуто {purchase['stars']} :star: гравцю {purchase['user_id']}."


# ================= текстові команди =================


@router.message(Command("give"))
async def cmd_give(message: Message, command: CommandObject, pool: asyncpg.Pool) -> None:
    parts = (command.args or "").split()
    currency = {"shagy": "shagy", "cherv": "chervintsi"}.get(parts[1] if len(parts) == 3 else "")
    if not currency or not parts[0].isdigit() or not parts[2].lstrip("-").isdigit():
        await message.answer("Формат: <code>/give ID shagy|cherv СУМА</code>")
        return
    balance = await users.add_balance(pool, int(parts[0]), currency, int(parts[2]))
    if balance is None:
        await message.answer(":no: Гравця не знайдено або баланс пішов би в мінус.")
        return
    await message.answer(f":ok: Новий баланс ({currency}): {balance}")


@router.message(Command("vip_give"))
async def cmd_vip_give(message: Message, command: CommandObject, pool: asyncpg.Pool) -> None:
    nums = ints(command.args, 2)
    if not nums or nums[1] <= 0:
        await message.answer("Формат: <code>/vip_give ID ДНІВ</code>")
        return
    until = await users.extend_vip(pool, nums[0], nums[1])
    await message.answer(f":ok: VIP до {until:%d.%m.%Y}" if until else ":no: Гравця не знайдено.")


@router.message(Command("block", "unblock"))
async def cmd_block(message: Message, command: CommandObject, pool: asyncpg.Pool) -> None:
    nums = ints(command.args, 1)
    if not nums:
        await message.answer("Формат: <code>/block ID</code>")
        return
    blocked = command.command == "block"
    ok = await users.set_blocked(pool, nums[0], blocked)
    await message.answer((":lock: Заблоковано" if blocked else ":ok: Розблоковано") if ok else ":no: Гравця не знайдено.")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject, bot: Bot, pool: asyncpg.Pool) -> None:
    source = message.reply_to_message
    if source is None and not command.args:
        await message.answer("Формат: <code>/broadcast ТЕКСТ</code> або відповіддю на повідомлення.")
        return
    ids = await users.all_ids(pool)
    await message.answer(texts.OWNER_BC_RUNNING.format(count=len(ids)))
    if source is not None:
        sent = await broadcast(bot, ids, from_chat=source.chat.id, message_id=source.message_id)
    else:
        sent = await broadcast(bot, ids, text=command.args)
    await message.answer(texts.OWNER_BC_DONE.format(sent=sent, total=len(ids)))


@router.message(Command("promo_new"))
async def cmd_promo_new(message: Message, command: CommandObject, pool: asyncpg.Pool) -> None:
    parts = (command.args or "").split()
    nums = ints(" ".join(parts[1:]), 4) if len(parts) == 5 else None
    if not nums or min(nums) < 0 or nums[3] == 0:
        await message.answer("Формат: <code>/promo_new КОД ЛІРИ МОНЕТИ VIP_ДНІВ ВИКОРИСТАНЬ</code>")
        return
    ok = await promocodes.create(pool, parts[0], *nums)
    await message.answer(f":ok: Промокод <code>{texts.escape(parts[0].upper())}</code> створено."
                         if ok else ":no: Такий код уже існує.")


@router.message(Command("promo_list"))
async def cmd_promo_list(message: Message, pool: asyncpg.Pool) -> None:
    rows = await promocodes.list_all(pool)
    if not rows:
        await message.answer("Промокодів немає.")
        return
    lines = [
        f"<code>{texts.escape(r['code'])}</code>: {r['shagy']}{texts.SHAGY} {r['chervintsi']}{texts.CHERV} "
        f"VIP {r['vip_days']}д · {r['uses']}/{r['max_uses']}"
        for r in rows
    ]
    await message.answer("\n".join(lines))


@router.message(Command("promo_del"))
async def cmd_promo_del(message: Message, command: CommandObject, pool: asyncpg.Pool) -> None:
    code = (command.args or "").strip()
    ok = bool(code) and await promocodes.delete(pool, code)
    await message.answer(":trash: Видалено." if ok else ":no: Не знайдено.")


@router.message(Command("refund"))
async def cmd_refund(message: Message, command: CommandObject, bot: Bot, pool: asyncpg.Pool) -> None:
    await message.answer(await refund(bot, pool, (command.args or "").strip()))


@router.message(Command("games"))
async def cmd_games(message: Message, manager: GameManager) -> None:
    if not manager.runners:
        await message.answer("Зараз ігор немає.")
        return
    lines = [
        f"{texts.escape(r.chat_title or str(chat_id))}: {r.game.phase.value}, "
        f"день {r.game.day}, живих {len(r.game.alive())}/{len(r.game.players)}"
        for chat_id, r in manager.runners.items()
    ]
    await message.answer("\n".join(lines))


@router.message(Command("purchases"))
async def cmd_purchases(message: Message, pool: asyncpg.Pool) -> None:
    rows = await payments.recent(pool)
    if not rows:
        await message.answer("Покупок ще не було.")
        return
    lines = [
        f"{r['created_at']:%d.%m %H:%M} · {r['user_id']} · {texts.escape(r['product'])} · {r['stars']}:star:"
        f"{' · повернуто' if r['refunded'] else ''}\n<code>{texts.escape(r['charge_id'])}</code>"
        for r in rows
    ]
    await message.answer("\n".join(lines))
