"""Панель власника бота (OWNER_IDS у .env). Працює лише в особистих."""

from __future__ import annotations

import asyncio
import logging

import asyncpg
from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import Message

from bot import economy, texts
from bot.config import Settings
from bot.db import payments, promocodes, users
from bot.game.manager import GameManager

router = Router(name="owner")
log = logging.getLogger(__name__)

HELP = (
    "🛠 <b>Панель власника</b>\n\n"
    "{stats}\n\n"
    "<code>/give ID shagy|cherv СУМА</code> — видати (або мінус — забрати)\n"
    "<code>/vip_give ID ДНІВ</code> — подарувати VIP\n"
    "<code>/block ID</code> · <code>/unblock ID</code>\n"
    "<code>/broadcast ТЕКСТ</code> — розсилка всім (або відповіддю на повідомлення)\n"
    "<code>/promo_new КОД ШАГИ ЧЕРВІНЦІ VIP_ДНІВ ВИКОРИСТАНЬ</code>\n"
    "<code>/promo_list</code> · <code>/promo_del КОД</code>\n"
    "<code>/purchases</code> — останні покупки · <code>/refund CHARGE_ID</code> — повернути зірки\n"
    "<code>/games</code> — активні ігри"
)


class IsOwner(Filter):
    async def __call__(self, message: Message, config: Settings) -> bool:
        return message.chat.type == "private" and message.from_user.id in config.owner_ids


router.message.filter(IsOwner())


def ints(args: str | None, count: int) -> list[int] | None:
    parts = (args or "").split()
    if len(parts) != count:
        return None
    try:
        return [int(p) for p in parts]
    except ValueError:
        return None


@router.message(Command("owner"))
async def cmd_owner(message: Message, pool: asyncpg.Pool, manager: GameManager) -> None:
    s = await users.stats(pool)
    stats = (
        f"👥 Гравців: {s['users']} (VIP: {s['vips']})\n"
        f"🎲 Ігор: {s['games']} (за добу: {s['games_day']}) · зараз іде: {len(manager.runners)}\n"
        f"⭐ Зароблено зірок: {s['stars']}"
    )
    await message.answer(HELP.format(stats=stats))


@router.message(Command("give"))
async def cmd_give(message: Message, command: CommandObject, pool: asyncpg.Pool) -> None:
    parts = (command.args or "").split()
    currency = {"shagy": "shagy", "cherv": "chervintsi"}.get(parts[1] if len(parts) == 3 else "")
    if not currency or not parts[0].isdigit() or not parts[2].lstrip("-").isdigit():
        await message.answer("Формат: <code>/give ID shagy|cherv СУМА</code>")
        return
    balance = await users.add_balance(pool, int(parts[0]), currency, int(parts[2]))
    if balance is None:
        await message.answer("❌ Гравця не знайдено або баланс пішов би в мінус.")
        return
    await message.answer(f"✅ Новий баланс ({currency}): {balance}")


@router.message(Command("vip_give"))
async def cmd_vip_give(message: Message, command: CommandObject, pool: asyncpg.Pool) -> None:
    nums = ints(command.args, 2)
    if not nums or nums[1] <= 0:
        await message.answer("Формат: <code>/vip_give ID ДНІВ</code>")
        return
    until = await users.extend_vip(pool, nums[0], nums[1])
    await message.answer(f"✅ VIP до {until:%d.%m.%Y}" if until else "❌ Гравця не знайдено.")


@router.message(Command("block", "unblock"))
async def cmd_block(message: Message, command: CommandObject, pool: asyncpg.Pool) -> None:
    nums = ints(command.args, 1)
    if not nums:
        await message.answer("Формат: <code>/block ID</code>")
        return
    blocked = command.command == "block"
    ok = await users.set_blocked(pool, nums[0], blocked)
    await message.answer(("⛔ Заблоковано" if blocked else "✅ Розблоковано") if ok else "❌ Гравця не знайдено.")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject, bot: Bot, pool: asyncpg.Pool) -> None:
    source = message.reply_to_message
    if source is None and not command.args:
        await message.answer("Формат: <code>/broadcast ТЕКСТ</code> або відповіддю на повідомлення.")
        return
    ids = await users.all_ids(pool)
    await message.answer(f"📣 Розсилаю {len(ids)} гравцям…")
    sent = 0
    for uid in ids:
        for attempt in range(2):
            try:
                if source is not None:
                    await source.copy_to(uid)
                else:
                    await bot.send_message(uid, command.args)
                sent += 1
                break
            except TelegramRetryAfter as e:
                if attempt == 0:
                    await asyncio.sleep(e.retry_after)
            except TelegramAPIError:
                break
        await asyncio.sleep(0.05)  # ~20 повідомлень на секунду
    await message.answer(f"✅ Доставлено: {sent}/{len(ids)}")


@router.message(Command("promo_new"))
async def cmd_promo_new(message: Message, command: CommandObject, pool: asyncpg.Pool) -> None:
    parts = (command.args or "").split()
    nums = ints(" ".join(parts[1:]), 4) if len(parts) == 5 else None
    if not nums or min(nums) < 0 or nums[3] == 0:
        await message.answer("Формат: <code>/promo_new КОД ШАГИ ЧЕРВІНЦІ VIP_ДНІВ ВИКОРИСТАНЬ</code>")
        return
    ok = await promocodes.create(pool, parts[0], *nums)
    await message.answer(f"✅ Промокод <code>{texts.escape(parts[0].upper())}</code> створено."
                         if ok else "❌ Такий код уже існує.")


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
    await message.answer("🗑 Видалено." if ok else "❌ Не знайдено.")


@router.message(Command("refund"))
async def cmd_refund(message: Message, command: CommandObject, bot: Bot, pool: asyncpg.Pool) -> None:
    charge_id = (command.args or "").strip()
    purchase = await payments.get(pool, charge_id) if charge_id else None
    if purchase is None:
        await message.answer("❌ Покупку не знайдено.")
        return
    if purchase["refunded"]:
        await message.answer("Цю покупку вже повернуто.")
        return
    try:
        await bot.refund_star_payment(purchase["user_id"], charge_id)
    except TelegramAPIError as e:
        await message.answer(f"❌ Telegram відмовив: {texts.escape(str(e))}")
        return
    product = economy.PRODUCTS.get(purchase["product"])
    async with pool.acquire() as conn, conn.transaction():
        await payments.mark_refunded(conn, charge_id)
        if product and product.chervintsi:
            # Забираємо стільки червінців, скільки лишилось (не йдемо в мінус).
            await conn.execute(
                "UPDATE users SET chervintsi = GREATEST(chervintsi - $2, 0) WHERE id = $1",
                purchase["user_id"], product.chervintsi,
            )
        if product and product.vip_days:
            await users.revoke_vip_days(conn, purchase["user_id"], product.vip_days)
    await message.answer(f"✅ Повернуто {purchase['stars']}⭐ гравцю {purchase['user_id']}.")


@router.message(Command("games"))
async def cmd_games(message: Message, manager: GameManager) -> None:
    if not manager.runners:
        await message.answer("Зараз ігор немає.")
        return
    lines = [
        f"• {texts.escape(r.chat_title or str(chat_id))}: {r.game.phase.value}, "
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
        f"{r['created_at']:%d.%m %H:%M} · {r['user_id']} · {texts.escape(r['product'])} · {r['stars']}⭐"
        f"{' · повернуто' if r['refunded'] else ''}\n<code>{texts.escape(r['charge_id'])}</code>"
        for r in rows
    ]
    await message.answer("\n".join(lines))
