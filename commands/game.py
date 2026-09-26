from __future__ import annotations

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.deep_linking import create_start_link
from aiogram.filters import Command, CommandStart
from aiogram.exceptions import TelegramBadRequest
from database.database import cursor, conn
import json
from datetime import datetime
import asyncio
import random

# cursor.execute("UPDATE users SET cured = %s WHERE id = %s", (0, 1240754158,))
# conn.commit()

# cursor.execute("UPDATE users SET cured = %s WHERE id = %s", (0, 5588913711,))
# conn.commit()

# cursor.execute("UPDATE users SET killed = %s WHERE id = %s", (0, 1240754158,))
# conn.commit()

# cursor.execute("UPDATE users SET killed = %s WHERE id = %s", (0, 5588913711,))
# conn.commit()

router_game = Router()


def _db_fetchone(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_execute(query: str, params: tuple = ()) -> int:
    cursor.execute(query, params)
    return cursor.rowcount if cursor.rowcount is not None else 0

time = 0
stop = 0
action = 0

members_list = []

roles = ['Аль Капоне', 'Лікар', 'Мирний житель']


names = []
tg_names = []

killed_text = ""

mess_nabir = ""

all_capone_list = []
doctor_list = []
peaceful_resident_list = []
patients_list = []
list_of_text = []

peaceful_list = []

list_question = []

keyboard2 = []

time_game = 0
time_day = 0

# #region agent log
_log_path = r"c:\Users\flime\OneDrive\Desktop\MafiaAllCaponeBot\.cursor\debug.log"
def _log_debug(session_id, run_id, hypothesis_id, location, message, data):
    try:
        os.makedirs(os.path.dirname(_log_path), exist_ok=True)
        with open(_log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                "sessionId": session_id,
                "runId": run_id,
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(datetime.now().timestamp() * 1000)
            }) + "\n")
            f.flush()
    except:
        pass
# #endregion

mess_kill = 0
mess_cured = 0
mess_voiting = 0

async def voting(message: Message, bot: Bot):
    global tg_names, mess_voiting, peaceful_list, doctor_list, all_capone_list, patients_list

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти до бота", url='https://t.me/sicilian_mafia_bot')]
    ])

    await message.answer("Голосування розпозпочато! У тебе є 45 секунд щоб оприділиться кого вішати і пізніше проголосувати!")

    await asyncio.sleep(45)

    await message.answer("Перейди до бота і проголосуй, тільки нікому не кажи 🤫", reply_markup=keyboard)

    
    builder_voting = InlineKeyboardBuilder()

    for id in members_list: 
        name_row = _db_fetchone("SELECT tg_name FROM users WHERE id = %s", (id,))
        name = name_row[0] if name_row else ""
        killed_row = _db_fetchone("SELECT killed FROM users WHERE id = %s", (id,))
        killed = killed_row[0] if killed_row else 0

        if killed == 0:
            callback_text = f"cured_{id}"
            builder_voting.add(InlineKeyboardButton(text=f"{name}", callback_data=callback_text))
            builder_voting.adjust(1, 1)
            tg_names.append(callback_text)

    if builder_voting.buttons is not None:
        for id in members_list:
            mess_voiting = await bot.send_message(chat_id=id, text="Кого будемо вішати?", reply_markup=builder_voting.as_markup())
    else:
        for id in members_list: 
            name_row = _db_fetchone("SELECT tg_name FROM users WHERE id = %s", (id,))
            name = name_row[0] if name_row else ""
            killed_row = _db_fetchone("SELECT killed FROM users WHERE id = %s", (id,))
            killed = killed_row[0] if killed_row else 0

            if killed == 0 and id != message.chat.id:
                callback_text = f"cured_{id}"
                builder_voting.add(InlineKeyboardButton(text=f"{name}", callback_data=callback_text))
                builder_voting.adjust(1, 1)
                tg_names.append(callback_text)
        
    for i in range(len(tg_names)):
        callback_text = tg_names[i]
        @router_game.callback_query(F.data == callback_text)
        async def cured_callback(callback: CallbackQuery, bot: Bot, callback_text=callback_text, action=action):
            global tg_names, mess_cured
            id = int(callback_text[len("cured_"):])

            action += 1
            action=action
            
            name_row = _db_fetchone("SELECT tg_name FROM users WHERE id = %s", (id,))
            name = name_row[0] if name_row else ""

            await callback.message.edit_text(f"Кого будемо вішати?\nТи вибрав <a href='tg://user?id={id}'>{name}</a>", parse_mode="html")


async def day_def(message: Message):
    gif_path = "/Users/flime/Documents/Mafia_All_Capone_bot-Mafia_All_Capone_bot/Media/day.gif"


    with open(gif_path, 'rb') as gif_file:
        await message.answer_animation(animation=FSInputFile(path=gif_path, filename="day.gif"),
                                        caption=f"🌄 День\n\nРанкова тиша порушена не ароматом кави, а...")
        
    await message.answer(f"Жахливою трагедією. Цієї ночі безцінний {killed_text} був жорстоко вбитий. Сорока на хвості принесла звістку, що в нього в гостях був Аль Капоне.")
    players_text = "\n".join([f"{i+1}. {name}" for i, name in enumerate(names)])
    await message.answer(f'Список гравців:\n{players_text}', parse_mode="html") 

    await asyncio.sleep(60)
    await voting(message=message)


async def night_def(message: Message, bot: Bot, action=action):
    gif_path = "/Users/flime/Documents/Mafia_All_Capone_bot-Mafia_All_Capone_bot/Media/night.gif"
    with open(gif_path, 'rb') as gif_file:
        await message.answer_animation(animation=FSInputFile(path=gif_path, filename="night.gif"),
                                    caption=f"🌃Ніч 1\n\nПід покровом ночі за рогом почулися постріли і виє сирена швидкої. Сержант наказав усім тісно зачинити двері. Залишаємось на сторожі. Що ж нам може принести цей світанок....")
    
    players_text = "\n".join([f"{i+1}. {name}" for i, name in enumerate(names)])
    await message.answer(f'Список гравців:\n{players_text}', parse_mode="html") 

    for id in members_list:
        role_row = _db_fetchone("SELECT role FROM users WHERE id = %s", (id,))
        role = role_row[0] if role_row else None

        if role == "Аль Капоне":
            await all_capone(message=message, bot=bot, id=id)
        elif role == "Лікар":
            await doctor(message=message, bot=bot, id=id)                                            
        elif role == "Мирний житель":
            await peaceful_resident(message=message, bot=bot, id=id)
    await asyncio.sleep(30)
    if action < 0:
        await day_def(message=message)


async def doctor(message: Message, bot: Bot, id, action=action):
    global tg_names, mess_cured, peaceful_list, doctor_list, all_capone_list, patients_list
    builder_doctor = InlineKeyboardBuilder()

    for id in members_list: 
        name_row = _db_fetchone("SELECT tg_name FROM users WHERE id = %s", (id,))
        name = name_row[0] if name_row else ""
        cured_row = _db_fetchone("SELECT cured FROM users WHERE id = %s", (id,))
        cured = cured_row[0] if cured_row else 0

        if cured == 0:
            callback_text = f"cured_{id}"
            builder_doctor.add(InlineKeyboardButton(text=f"{name}", callback_data=callback_text))
            builder_doctor.adjust(1, 1)
            tg_names.append(callback_text)

    if builder_doctor.buttons is not None:
        mess_cured = await bot.send_message(chat_id=doctor_list[0], text="Кого будемо лікувати?", reply_markup=builder_doctor.as_markup())
    else:
        for id in members_list: 
            name_row = _db_fetchone("SELECT tg_name FROM users WHERE id = %s", (id,))
            name = name_row[0] if name_row else ""
            cured_row = _db_fetchone("SELECT cured FROM users WHERE id = %s", (id,))
            cured = cured_row[0] if cured_row else 0

            if cured == 0:
                callback_text = f"cured_{id}"
                builder_doctor.add(InlineKeyboardButton(text=f"{name}", callback_data=callback_text))
                builder_doctor.adjust(1, 1)
                tg_names.append(callback_text)
        
    for i in range(len(tg_names)):
        callback_text = tg_names[i]
        @router_game.callback_query(F.data == callback_text)
        async def cured_callback(callback: CallbackQuery, bot: Bot, callback_text=callback_text, action=action):
            global tg_names, mess_cured
            id = int(callback_text[len("cured_"):])

            action += 1
            action=action
            
            name_row = _db_fetchone("SELECT tg_name FROM users WHERE id = %s", (id,))
            name = name_row[0] if name_row else ""

            await callback.message.edit_text(f"Кого будемо лікувати?\nТи вибрав <a href='tg://user?id={id}'>{name}</a>", parse_mode="html")

            _db_execute("UPDATE users SET cured = %s WHERE id = %s", (1, id,))
            conn.commit()
            if id == doctor_list[1]:
                await bot.send_message(chat_id=id, text="Ти вилікував себе!")
            else:
                await bot.send_message(chat_id=id, text="Тебе вилукував лікар!")


async def peaceful_resident(message: Message, bot: Bot, id, list=list_of_text):
    global list_question
    list = [("Чи любиш ти пити каву зранку?", "Так", "Ні"), ("Чи вмієш ти готувати яєчню?", "Так", "Ні"), ("Ти віддаєш перевагу перегляду фільмів вдома, чи кінотеатрі?", "Вдома", "В кінотеатрі"),
            ("Ти полюбляєш вечірні прогулянки?", "Так", "Ні"), ("Ти за паперові чи електронні книги?", "Паперові", "Електронні"), ("Ти слухаєш подкасти?", "Так", "Ні"), ("Ти маєш улюблену музичну групу, чи виконавців?", "Так", "Ні"),
            ("Чи часто ти відвідуєш музеї/виставки?", "Так", "Ні"), ("У тебе є домашні улюбленці?", "Так", "Ні"), ("Любиш подорожі на велосипеді?", "Так", "Ні")]
    list_question = random.choice(list)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=list_question[1], callback_data="answer_1"), InlineKeyboardButton(text=list_question[2], callback_data="answer_2")]
    ])
    mess = await bot.send_message(chat_id=id, text=f"{list_question[0]}", reply_markup=keyboard)
    mess = mess


async def all_capone(message: Message, bot: Bot, id, action=action, killed_text=killed_text):
    global tg_names, mess_kill, peaceful_list, all_capone_list
    builder_all_capone = InlineKeyboardBuilder()
    for id in members_list: 
        name_row = _db_fetchone("SELECT tg_name FROM users WHERE id = %s", (id,))
        name = name_row[0] if name_row else ""
        killed_row = _db_fetchone("SELECT killed FROM users WHERE id = %s", (id,))
        killed = killed_row[0] if killed_row else 0

        if id in peaceful_list and id != int(all_capone_list[0]) and killed != 1:
            callback_text = f"killed_{id}"
            builder_all_capone.add(InlineKeyboardButton(text=f"{name}", callback_data=callback_text))
            builder_all_capone.adjust(1, 1)
            tg_names.append(callback_text)
    if builder_all_capone.buttons:
        mess_kill = await bot.send_message(chat_id=all_capone_list[0], text="Кого будемо вбивати?", reply_markup=builder_all_capone.as_markup())
    else:
        for id in members_list: 
            name_row = _db_fetchone("SELECT tg_name FROM users WHERE id = %s", (id,))
            name = name_row[0] if name_row else ""
            killed_row = _db_fetchone("SELECT killed FROM users WHERE id = %s", (id,))
            killed = killed_row[0] if killed_row else 0

            if id in peaceful_list and id != int(all_capone_list[0]) and killed != 1:
                callback_text = f"killed_{id}"
                builder_all_capone.add(InlineKeyboardButton(text=f"{name}", callback_data=callback_text))
                builder_all_capone.adjust(1, 1)
                tg_names.append(callback_text)

    for i in range(len(tg_names)):
        callback_text = tg_names[i]
        @router_game.callback_query(F.data == callback_text)
        async def kill_callback(callback: CallbackQuery, bot: Bot, callback_text=callback_text, killed_text=killed_text, killed_times=0):
            global tg_names, mess_kill, names
            if killed_times == 0:
                id = int(callback_text[len("killed_"):])

                cured_row = _db_fetchone("SELECT cured FROM users WHERE id = %s", (id,))
                cured = cured_row[0] if cured_row else 0
                if cured == 0:
                    name_row = _db_fetchone("SELECT tg_name FROM users WHERE id = %s", (id,))
                    name = name_row[0] if name_row else ""

                    await callback.message.edit_text(f"Кого будемо вбивати?\nТи вибрав <a href='tg://user?id={id}'>{name}</a>", parse_mode="html")

                    _db_execute("UPDATE users SET killed = %s WHERE id = %s", (1, id,))
                    conn.commit()
                    await bot.send_message(chat_id=id, text="Тебе вбили!")

                    role_row = _db_fetchone("SELECT role FROM users WHERE id = %s", (id,))
                    role = role_row[0] if role_row else None

                    killed_text = f"{name} {role}"
                    killed_text = killed_text

                    members_list.remove(id)
                    peaceful_list.remove(id)
                    tg_names.remove(callback_text)
                    #names.remove(name)
                    day += 1
                    day=day
                else:
                    await bot.send_message(chat_id=id, text="Тебе врятували бинти та скальпель.")
            else:
                pass








@router_game.message(Command("game"))
async def start_cmd(message: Message, bot: Bot, time_game=time_game, members_list=members_list,
                    roles=roles):
    if message.chat.type == "supergroup" or message.chat.type == "group":
        global all_capone_list, doctor_list, peaceful_resident_list, keyboard, peaceful_list, mess_nabir, names
        global MN
        MN = 2
        # #region agent log
        _log_debug('debug-session', 'run1', 'G1', 'game.py:start_cmd', 'Start command (game) called', {
            'chat_id': message.chat.id,
            'MN': MN,
            'members_list_len': len(members_list)
        })
        # #endregion
        time_game = 0
        roles = ['Аль Капоне', 'Лікар', 'Мирний житель']

        mess1 = ""
        mess2 = ""
        try:
            await message.delete()

            link = await create_start_link(bot, f'{message.chat.id}', encode=False)

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Приєднатися до гри!", url=link)]
            ])
            
            mess_nabir = await message.answer("Набір до гри!", reply_markup=keyboard)
            await bot.pin_chat_message(chat_id=message.chat.id, message_id=mess_nabir.message_id)
            
            while True:
                await asyncio.sleep(1)
                time_game += 1
                print(time_game)
                if time_game == 120:
                    if len(members_list) < MN:
                        await message.answer(text="<b>Таймер зупиняється! Гра закінчена</b>", parse_mode="html")
                    else:
                        await message.answer(text="<b>Гра починається!</b>", parse_mode="html")
                        game = True
                    break
                elif time_game == 60:
                    mess1 = await mess_nabir.reply(text="Пройшла хвилина від початку! Після 2 хвилин після початку очікування таймер зупиняється!")
                    mess1 = mess1
                elif time_game == 30:
                    mess2 = await mess_nabir.reply(text="Пройшло 30 секунд від початку! Після 2 хвилин після початку очікування таймер зупиняється!")
                    mess2 = mess2
                elif stop == 1:
                    break
                
                if time_game % 10 == 0:
                    await mess_nabir.edit_text(text=f"Набір до гри!\nГравці:\n<b>{', '.join(names)}</b>\n\nКількість граців: {len(members_list)}\n\nЧас: {time_game}с.", parse_mode="html", reply_markup=keyboard)


        except TelegramBadRequest as ex:
            await message.answer(text=f"Встановіть усі потрібні права!")
        
        list = [mess_nabir, mess1, mess2]
        try:
            for message_to_delete in list:
                await message_to_delete.delete()
        except AttributeError:
            pass



async def start_game(bot, message, members_list, cursor, conn):
    # #region agent log
    _log_debug('debug-session', 'run1', 'G2', 'game.py:start_game:entry', 'start_game called', {
        'members_list_len': len(members_list),
        'MN': MN,
        'conn_is_none': conn is None,
        'cursor_is_none': cursor is None
    })
    # #endregion
    if len(members_list) >= MN:
        print("\n--- Нова гра починається! ---")
        
        # Очистимо ролі перед новою грою
        _db_execute("UPDATE users SET role = NULL")
        conn.commit()
        print("🔄 Всі ролі очищені перед роздачею")
        
        # Генерація списку ролей
        roles = ["Аль Капоне", "Лікар"] + ["Мирний житель"] * (len(members_list) - 2)
        print("До перемішування:", roles)
        random.shuffle(roles)
        print("Після перемішування:", roles)
        # #region agent log
        _log_debug('debug-session', 'run1', 'G3', 'game.py:start_game:roles_built', 'Roles list built', {
            'roles_len': len(roles),
            'members_list_len': len(members_list),
            'roles_preview': roles[:5]
        })
        # #endregion
        
        for id, random_role in zip(members_list, roles):
            # Оновлення ролі в БД
            _db_execute("UPDATE users SET role = %s WHERE id = %s", (random_role, id,))
            conn.commit()
            
            # Перевірка, що запис у БД правильний
            role_row = _db_fetchone("SELECT role FROM users WHERE id = %s", (id,))
            role = role_row[0] if role_row else None
            print(f"✅ {id} отримав роль: {role}")
            # #region agent log
            _log_debug('debug-session', 'run1', 'G4', 'game.py:start_game:assigned', 'Role assigned', {
                'player_id': id,
                'role': role,
                'expected_role': random_role
            })
            # #endregion
            
            if role != random_role:
                print(f"❌ ПОМИЛКА! Очікувалося {random_role}, а в БД записано {role}")
            
            # Відправлення повідомлення гравцю
            if role == "Аль Капоне":
                all_capone_list.append(id)
                patients_list.append(id)
                await bot.send_message(chat_id=id, text="Цієї гри ти - БББ!\nРоби все, щоб твоя сім'я отримала перемогу.")
            elif role == "Лікар":
                doctor_list.append(id)
                peaceful_list.append(id)
                await bot.send_message(chat_id=id, text="Цієї гри ти - УУУ!\nРоби все, щоб врятувати якомога більше мирних людей.")
            elif role == "Мирний житель":
                peaceful_list.append(id)
                patients_list.append(id)
                await bot.send_message(chat_id=id, text="Цієї гри ти - ВВВ!\nРоби все, щоб знищити мафію.")
                
        print("\n✅ Гра розпочата успішно!\n")
        await night_def(bot=bot, message=message)


    else:
     await message.answer(text="Ця команда доступна у групах!")

@router_game.message(CommandStart(deep_link=True))
async def start_cmd_link(message: Message, bot: Bot, names=names):
    global mess_nabir
    if len(members_list) > 4:
        await message.answer("Учасників може бути тільки 4!")
    if message.from_user.id in members_list:
        await message.answer(text="Ти вже приєднався!")
    else:
        await message.answer(f"Ти приєднався до гри!")

        members_list.append(message.from_user.id)
        names.append(message.from_user.mention_html())

        link = await create_start_link(bot, 'foo', encode=True)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Приєднатися до гри!", url=link)]
        ])

        await mess_nabir.edit_text(text=f"Набір до гри!\nГравці:\n<b>{', '.join(names)}</b>\n\nКількість граців: {len(members_list)}", parse_mode="html", reply_markup=keyboard)



@router_game.message(Command("leave_game"))
async def stop_game_cmd(message: Message, bot: Bot):
    global members_list, names

    members_list.remove(message.from_user.id)
    names.remove(message.from_user.mention_html())

    await bot.send_message(chat_id=message.from_user.id, text="Ти покинув гру!")

