"""
Керування глобальним вимкненням slash-команд бота.
Доступ лише у ЛС і лише для BOT_OWNER_IDS (див. commands.group_admin).
/cmd_off <команда>  - вимкнути (напр. play, roulette, promocode)
/cmd_on <команда>   - увімкнути
/cmd_list           - список вимкнених
"""
import html

from aiogram import Router, F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from commands.group_admin import BOT_OWNER_IDS
from database.database import list_disabled_bot_commands, set_bot_command_disabled

router_command_switch = Router()

# Не даємо заблокувати службові команди керування (інакше лише через БД)
_PROTECTED = frozenset({"cmd_off", "cmd_on", "cmd_list"})


def _norm_arg(text: str | None) -> str:
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        return ""
    arg = parts[1].strip().lower()
    if arg.startswith("/"):
        arg = arg[1:]
    if "@" in arg:
        arg = arg.split("@", 1)[0]
    return arg


def _deny(message: Message) -> bool:
    if not message.from_user or message.from_user.id not in BOT_OWNER_IDS:
        return True
    if message.chat.type != ChatType.PRIVATE:
        return True
    return False


@router_command_switch.message(Command("cmd_off"), F.chat.type == ChatType.PRIVATE)
async def cmd_off(message: Message):
    if _deny(message):
        return
    arg = _norm_arg(message.text)
    if not arg:
        await message.answer(
            "Вкажи команду без слеша: <code>/cmd_off roulette</code>",
            parse_mode="html",
        )
        return
    if arg in _PROTECTED:
        await message.answer("Цю службову команду не можна вимкнути.")
        return
    if set_bot_command_disabled(arg, True):
        await message.answer(f"Вимкнено: <code>/{html.escape(arg)}</code>", parse_mode="html")
    else:
        await message.answer("Не вдалося зберегти (перевір назву команди).")


@router_command_switch.message(Command("cmd_on"), F.chat.type == ChatType.PRIVATE)
async def cmd_on(message: Message):
    if _deny(message):
        return
    arg = _norm_arg(message.text)
    if not arg:
        await message.answer(
            "Вкажи команду: <code>/cmd_on roulette</code>",
            parse_mode="html",
        )
        return
    if set_bot_command_disabled(arg, False):
        await message.answer(f"Увімкнено: <code>/{html.escape(arg)}</code>", parse_mode="html")
    else:
        await message.answer("Не вдалося оновити або команда не була вимкнена.")


@router_command_switch.message(Command("cmd_list"), F.chat.type == ChatType.PRIVATE)
async def cmd_list(message: Message):
    if _deny(message):
        return
    names = list_disabled_bot_commands()
    if not names:
        await message.answer("Зараз усі команди увімкнені.")
        return
    body = "\n".join(f"• <code>/{html.escape(n)}</code>" for n in names)
    await message.answer(f"Вимкнені команди:\n{body}", parse_mode="html")
