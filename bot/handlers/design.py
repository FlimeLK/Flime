"""Оформлення бота для власника: анімовані емодзі та медіа для сцен."""

from __future__ import annotations

import asyncpg
from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, MessageEntity

from bot import texts
from bot.db import ui as ui_db
from bot.handlers.owner import IsOwner
from bot.ui import emoji, media

router = Router(name="design")
router.message.filter(IsOwner())

HELP = (
    ":sparkle: <b>ОФОРМЛЕННЯ</b>\n\n"
    "<b>Анімовані емодзі</b>\n"
    "<code>/emoji</code> - усі ключі й поточні емодзі\n"
    "<code>/emoji_id</code> - відповіддю на повідомлення з premium-емодзі: покаже їхні ID\n"
    "<code>/emoji_set КЛЮЧ</code> - відповіддю на повідомлення з premium-емодзі (або емодзі одразу після ключа)\n"
    "<code>/emoji_reset КЛЮЧ</code> - повернути емодзі за замовчуванням\n"
    "<code>/emoji_pack НАЗВА</code> - показати, що з пака підходить; <code>/emoji_pack НАЗВА apply</code> - застосувати\n\n"
    "<b>Медіа для сцен</b>\n"
    "<code>/media</code> - список сцен\n"
    "<code>/media СЦЕНА</code> - відповіддю на фото / GIF / відео\n"
    "<code>/media_clear СЦЕНА</code>"
)


def custom_emojis(message: Message | None) -> list[tuple[str, str]]:
    """(символ, custom_emoji_id) з тексту або підпису повідомлення."""
    if message is None:
        return []
    text = message.text or message.caption or ""
    entities: list[MessageEntity] = message.entities or message.caption_entities or []
    found = []
    for ent in entities:
        if ent.type == "custom_emoji" and ent.custom_emoji_id:
            found.append((ent.extract_from(text), ent.custom_emoji_id))
    return found


def _norm(s: str) -> str:
    return s.replace("️", "")


async def send_chunks(message: Message, lines: list[str], limit: int = 3500) -> None:
    chunk: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) > limit and chunk:
            await message.answer("\n".join(chunk))
            chunk, size = [], 0
        chunk.append(line)
        size += len(line) + 1
    if chunk:
        await message.answer("\n".join(chunk))


@router.message(Command("design"))
async def cmd_design(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("emoji"))
async def cmd_emoji(message: Message) -> None:
    lines = [":sparkle: <b>ЕМОДЗІ БОТА</b> (ключ - вигляд - ID)", ""]
    for key in emoji.DEFAULTS:
        cid = emoji.custom_id(key)
        lines.append(f"<code>{key}</code> - {emoji.e(key)} - {f'<code>{cid}</code>' if cid else 'звичайний'}")
    await send_chunks(message, lines)


@router.message(Command("emoji_id"))
async def cmd_emoji_id(message: Message) -> None:
    found = custom_emojis(message.reply_to_message) + custom_emojis(message)
    if not found:
        await message.answer("Надішли повідомлення з premium-емодзі й відповідай на нього командою /emoji_id.")
        return
    lines = [f'<tg-emoji emoji-id="{cid}">{ch}</tg-emoji> - <code>{cid}</code>' for ch, cid in found]
    await message.answer("\n".join(lines))


@router.message(Command("emoji_set"))
async def cmd_emoji_set(message: Message, command: CommandObject, pool: asyncpg.Pool) -> None:
    key = (command.args or "").split(" ")[0].strip()
    if key not in emoji.DEFAULTS:
        await message.answer("Невідомий ключ. Список: /emoji")
        return
    found = custom_emojis(message) or custom_emojis(message.reply_to_message)
    if not found:
        await message.answer(f"Додай premium-емодзі після ключа: <code>/emoji_set {key} 🔥</code> "
                             "або відповідай командою на повідомлення з ним.")
        return
    cid = found[0][1]
    await ui_db.set_emoji(pool, key, cid)
    emoji.set_override(key, cid)
    await message.answer(f":ok: <code>{key}</code> тепер: {emoji.e(key)}")


@router.message(Command("emoji_reset"))
async def cmd_emoji_reset(message: Message, command: CommandObject, pool: asyncpg.Pool) -> None:
    key = (command.args or "").strip()
    if key not in emoji.DEFAULTS:
        await message.answer("Невідомий ключ. Список: /emoji")
        return
    await ui_db.set_emoji(pool, key, None)
    emoji.set_override(key, None)
    await message.answer(f":refresh: <code>{key}</code> повернуто: {emoji.e(key)}")


@router.message(Command("emoji_pack"))
async def cmd_emoji_pack(message: Message, command: CommandObject, bot: Bot, pool: asyncpg.Pool) -> None:
    parts = (command.args or "").split()
    if not parts:
        await message.answer("Формат: <code>/emoji_pack НАЗВА</code> (назва з посилання t.me/addemoji/НАЗВА)")
        return
    name = parts[0].rsplit("/", 1)[-1]
    apply = len(parts) > 1 and parts[1] == "apply"
    try:
        sticker_set = await bot.get_sticker_set(name)
    except TelegramAPIError as e:
        await message.answer(f":no: Не вдалося отримати пак: {texts.escape(str(e))}")
        return
    pack = [(s.emoji or "", s.custom_emoji_id) for s in sticker_set.stickers if s.custom_emoji_id]
    if not pack:
        await message.answer("У цьому паку немає custom emoji (це звичайні стікери?).")
        return
    by_char: dict[str, str] = {}
    for ch, cid in pack:
        by_char.setdefault(_norm(ch), cid)
    matches = [(key, by_char[_norm(emo.char)]) for key, emo in emoji.DEFAULTS.items() if _norm(emo.char) in by_char]

    lines = [f":sparkle: <b>{texts.escape(sticker_set.title)}</b> - {len(pack)} емодзі", ""]
    lines += [f'<tg-emoji emoji-id="{cid}">{ch or "❔"}</tg-emoji> <code>{cid}</code>' for ch, cid in pack[:60]]
    if len(pack) > 60:
        lines.append(f"… і ще {len(pack) - 60}")
    lines.append("")
    if not matches:
        lines.append("Збігів із ключами бота немає. Став вручну: <code>/emoji_set КЛЮЧ</code>.")
    elif apply:
        for key, cid in matches:
            await ui_db.set_emoji(pool, key, cid)
            emoji.set_override(key, cid)
        lines.append(f":ok: Застосовано {len(matches)}: " + ", ".join(f"<code>{k}</code>" for k, _ in matches))
    else:
        lines.append(f"Збігів: {len(matches)} - " + ", ".join(f"<code>{k}</code>" for k, _ in matches))
        lines.append(f"Застосувати: <code>/emoji_pack {texts.escape(name)} apply</code>")
    await send_chunks(message, lines)


@router.message(Command("media"))
async def cmd_media(message: Message, command: CommandObject, pool: asyncpg.Pool) -> None:
    slot = (command.args or "").strip()
    if not slot:
        lines = [":sparkle: <b>МЕДІА ДЛЯ СЦЕН</b>", ""]
        for key, title in media.SCENES.items():
            mark = ":ok:" if media.get(key) else "▫️"
            lines.append(f"{mark} <code>{key}</code> - {title}")
        lines += ["", "Щоб задати: відповідай на фото / GIF / відео командою <code>/media СЦЕНА</code>."]
        await send_chunks(message, lines)
        return
    if slot not in media.SCENES:
        await message.answer("Невідома сцена. Список: /media")
        return
    src = message.reply_to_message or message
    if src.photo:
        kind, file_id = "photo", src.photo[-1].file_id
    elif src.animation:
        kind, file_id = "animation", src.animation.file_id
    elif src.video:
        kind, file_id = "video", src.video.file_id
    else:
        await message.answer("Відповідай цією командою на фото, GIF або відео.")
        return
    await ui_db.set_media(pool, slot, kind, file_id)
    media.put(slot, kind, file_id)
    await message.answer(f":ok: Сцена <code>{slot}</code> ({media.SCENES[slot]}) тепер з медіа.")


@router.message(Command("media_clear"))
async def cmd_media_clear(message: Message, command: CommandObject, pool: asyncpg.Pool) -> None:
    slot = (command.args or "").strip()
    if slot not in media.SCENES:
        await message.answer("Невідома сцена. Список: /media")
        return
    await ui_db.set_media(pool, slot, None, None)
    media.put(slot, None, None)
    await message.answer(f":refresh: Сцена <code>{slot}</code> знову без медіа.")
