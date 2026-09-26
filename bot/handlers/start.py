"""Привітання і правила."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot import texts

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(texts.START)


@router.message(Command("rules", "help"))
async def cmd_rules(message: Message) -> None:
    await message.answer(texts.rules())
