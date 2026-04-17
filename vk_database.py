# VK_DATABASE.PY

import logging
import vk_config
import sqlite3
import json

from typing import Dict, Any
from datetime import datetime

def get_db_connection():
    conn = sqlite3.connect(vk_config.database_path)  
    conn.row_factory = sqlite3.Row  
    return conn

def load_cabinets_data():
    conn = get_db_connection()
    cursor = conn.cursor()

    data = {}
    
    cursor.execute("SELECT id, name FROM locations")
    locations = cursor.fetchall()
    
    for loc in locations:
        loc_name = loc['name']
        data[loc_name] = []

        cursor.execute("""
            SELECT r.id, r.name 
            FROM rooms r 
            WHERE r.locations_id = ?
        """, (loc['id'],))
        rooms = cursor.fetchall()
        
        for room in rooms:
            room_dict = {
                "Аудитория": room['name'],
                "Оборудование": []
            }
            cursor.execute("""
                SELECT e.name, re.count 
                FROM rooms_equipment re
                JOIN equipment e ON re.equipment_id = e.id
                WHERE re.room_id = ?
            """, (room['id'],))
            equipment = cursor.fetchall()
            
            for eq in equipment:
                room_dict["Оборудование"].append(f"{eq['name']} (кол-во: {eq['count']})")  # Пример формата
            
            data[loc_name].append(room_dict)
    
    conn.close()
    print("DEBUG: ДАННЫЕ ИЗ БД ЗАГРУЖЕНЫ")
    return data

def get_equipment_for_room(location, room_name):
    data = load_cabinets_data()
    rooms = data.get(location, [])
    for r in rooms:
        if r.get("Аудитория") == room_name:
            return r.get("Оборудование", [])
    print(f"DEBUG: ПОЛУЧЕНИЕ ОБОРУДОВАНИЯ...")
    return []

def get_user(vk_id: int):
    print(f"[DEBUG] Поиск пользователя с vk_id: {vk_id}") # DEBUG
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = """
            SELECT 
                id,
                name,
                phone,
                student_group,
                institute,
                position,
                division,
                link AS profile_link
            FROM users
            WHERE id = ?
        """
        
        cursor.execute(query, (vk_id,))
        row = cursor.fetchone()
        
        if row:
            user_data = dict(row)
            print(f"[DEBUG] Пользователь найден: {user_data}") # DEBUG
            return user_data
        
        print(f"[DEBUG] Пользователь с vk_id {vk_id} не найден в БД.") # DEBUG
        return None

    except Exception as e:
        print(f"[ERROR] Ошибка при выполнении get_user: {e}") # DEBUG
        return None
    finally:
        if 'conn' in locals():
            conn.close()


def save_user(vk_id: int, name: str, student_id: str = "",**kwargs):

    print(f"[DEBUG] Входящие данные для vk_id {vk_id}: name={name}, student_id='{student_id}'")

    phone = kwargs.get('phone', "").strip()    
    division = kwargs.get('division', "").strip()
    link = kwargs.get('link')

    group = kwargs.get('group', "").strip()
    institute = kwargs.get('institute', "").strip()
    position = kwargs.get('position', "").strip()

    # Если в student_id пришла строка со слешами, разбиваем её
    if student_id:

        parts = [p.strip() for p in student_id.replace(",", "/").split("/") if p.strip()]
        for item in parts:
            # 1. Группа: обычно содержит дефис и цифры (БСЦ24-01)
            if "-" in item and any(char.isdigit() for char in item):
                group = item
            
            # 2. Институт: короткое слово капсом (ИИТК, ИХТ, ИСИ)
            elif len(item) <= 6 and item.isupper():
                institute = item
            
            # 3. Должность: всё остальное (Разработчик, Специалист, Председатель)
            else:
                position = item
        print(f"[DEBUG] Распарсили student_id: group='{group}', inst='{institute}', pos='{position}'")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Данные для запросов
        data = (
            vk_id,
            name.strip() if name else None,
            phone.strip() if phone else None,
            group.strip() if group else None,
            institute.strip() if institute else None,
            position.strip() if position else None,
            division.strip() if division else None,
            link
        )

        # Пытаемся обновить
        cursor.execute("""
            INSERT INTO users (id, name, phone, student_group, institute, position, division, link)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                phone=excluded.phone,
                student_group=excluded.student_group,
                institute=excluded.institute,
                position=excluded.position,
                division=excluded.division,
                link=excluded.link
        """, data)
        
        if cursor.rowcount > 0:
            print(f"[DEBUG] Пользователь {vk_id} успешно обновлен (UPDATE)")
        
        conn.commit()
        print(f"[DEBUG] Пользователь {vk_id} успешно сохранен/обновлен")

    except Exception as e:
        print(f"[ERROR] Ошибка в save_user: {e}")
        if 'conn' in locals(): conn.rollback()
    finally:
        if 'conn' in locals(): conn.close()
    
    return get_user(vk_id)


def user_exists(vk_id: int) -> bool:
    """Быстрая проверка существования пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM users WHERE id = ?", (vk_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def get_user_state(vk_id: int) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT state, data FROM user_states WHERE vk_id = ?",
        (vk_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if row:
        try:
            session_data = json.loads(row['data']) if row['data'] else {}
        except json.JSONDecodeError:
            print(f"Ошибка JSON для vk_id {vk_id}: {row['data']}")
            session_data = {}

        return {
            'state': row['state'],
            'data': session_data   # ← здесь уже распарсенный dict сессии
        }

    return {
        'state': 'main_menu',
        'data': {}
    }


def save_user_state(vk_id: int, state: str, data: Dict[str, Any]) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()

    # Преобразуем словарь в JSON-строку
    data_json = json.dumps(data, ensure_ascii=False, indent=None)

    cursor.execute("""
        INSERT OR REPLACE INTO user_states (vk_id, state, data, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """, (vk_id, state, data_json))

    print(f"[SAVE STATE] vk_id={vk_id}, state={state}, session_keys={list(data.keys())}")
    
    conn.commit()
    conn.close()

# сохранение заявки и присваивание номера в базе
def save_order(name: str, responsible: str, book_info: str, data: Dict[str, Any]):
    conn = get_db_connection()
    cursor = conn.cursor()

    book_info_json = json.dumps(data, ensure_ascii=False)

    cursor.execute("""
        INSERT INTO orders (name, respon_person, book_info, date)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """, (name, responsible, book_info_json))
    
    conn.commit()
    
    # Получаем тот самый автоматический номер (id)
    order_id = cursor.lastrowid
    conn.close()
    
    return order_id
