#!/usr/bin/env python3
"""
Тестовий скрипт для перевірки налаштування allow_skip_night_action
"""
import sys
import os
sys.path.append(os.path.dirname(__file__))

from database.database import cursor, conn

def check_skip_setting(group_id):
    """Перевірити налаштування пропуску нічної дії для групи"""
    cursor.execute(
        "SELECT allow_skip_night_action FROM admin_panel WHERE group_id = %s LIMIT 1",
        (group_id,)
    )
    row = cursor.fetchone()

    if row:
        value = bool(row[0]) if row[0] is not None else False
        print(f"✅ Знайдено налаштування для group_id={group_id}")
        print(f"   allow_skip_night_action = {row[0]} (bool: {value})")
        return value
    else:
        print(f"❌ Не знайдено запис в admin_panel для group_id={group_id}")
        return None

def enable_skip_setting(group_id):
    """Увімкнути налаштування пропуску нічної дії"""
    cursor.execute(
        "UPDATE admin_panel SET allow_skip_night_action = TRUE WHERE group_id = %s",
        (group_id,)
    )
    conn.commit()
    print(f"✅ Увімкнено allow_skip_night_action для group_id={group_id}")

def list_all_groups():
    """Показати всі групи в admin_panel"""
    cursor.execute("SELECT group_id, allow_skip_night_action FROM admin_panel")
    rows = cursor.fetchall()

    if rows:
        print(f"\n📋 Всього груп в admin_panel: {len(rows)}")
        for row in rows:
            group_id, allow_skip = row
            print(f"   group_id={group_id}, allow_skip_night_action={allow_skip}")
    else:
        print("❌ Немає записів в admin_panel")

if __name__ == "__main__":
    print("🔍 Перевірка налаштування allow_skip_night_action\n")

    # Показати всі групи
    list_all_groups()

    # Якщо передано group_id як аргумент
    if len(sys.argv) > 1:
        group_id = int(sys.argv[1])
        print(f"\n🔍 Перевірка для group_id={group_id}")
        result = check_skip_setting(group_id)

        if result is False:
            print("\n💡 Налаштування вимкнене. Увімкнути? (y/n)")
            answer = input().strip().lower()
            if answer == 'y':
                enable_skip_setting(group_id)
                check_skip_setting(group_id)
    else:
        print("\n💡 Використання: python test_skip_setting.py <group_id>")
        print("   Наприклад: python test_skip_setting.py -1001234567890")
