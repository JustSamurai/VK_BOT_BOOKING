# VK_KEYBOARDDS.PY

import logging

from vkbottle import Keyboard, Text, Location, Callback, OpenLink
from vkbottle.bot import Message
from vk_database import load_cabinets_data, get_equipment_for_room   # твои функции из DATABASE

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(name)s:%(lineno)d | %(message)s'
)

def get_locations_keyboard(LOCATION_CODES: dict):
    kb = Keyboard(inline=True)
    
    # Сортируем и добавляем кнопки
    for i, (code, name) in enumerate(sorted(LOCATION_CODES.items(), key=lambda x: x[1])):
        # Делаем перенос ряда (row) после каждой второй кнопки для красоты
        if i > 0 and i % 2 == 0:
            kb.row()
            
        kb.add(Callback(name, payload={"action": "select_location", "code": code}))
    
    # Добавляем кнопку отмены в новый ряд
    kb.row()
    kb.add(Callback("❌ Отменить", payload={"action": "cancel"}))
    
    # ОБЯЗАТЕЛЬНО возвращаем JSON-строку
    return kb.get_json()

def get_rooms_keyboard(location: str, CABINETS_DATA: dict, ROOM_BY_CODE: dict):
    kb = Keyboard(inline=True)
    kb.add(Callback("← Назад", payload={"action": "back_to_locations"}))
    kb.row()

    rooms = CABINETS_DATA.get(location, [])
    for i, room_info in enumerate(rooms):
        room_name = room_info.get("Аудитория", "").strip()
        if not room_name:
            continue
        code = ROOM_BY_CODE.get((location, room_name))
        if not code:
            continue

        kb.add(Callback(room_name, payload={"action": "select_room", "code": code}))

        # Размещаем по 2 кнопки в ряд (или 3, если названия короткие)
        if (i + 1) % 2 == 0:
            kb.row()

    # Если последняя строка неполная — добавим row
    if len(rooms) % 2 != 0:
        kb.row()

    kb.add(Callback("❌ Отменить", payload={"action": "cancel"}))
    return kb.get_json()

def get_equipment_keyboard(location: str, room_name: str, selected: list):
    eq_list = get_equipment_for_room(location, room_name)
    kb = Keyboard(inline=True)

    # Кнопка "Назад" — всегда в первой строке, отдельно
    kb.add(Callback("← Назад к комнатам", payload={"action": "back_to_rooms", "loc": location}))
    kb.row()

    # Оборудование — по 2 кнопки в строке
    equipment_buttons = []
    for idx, eq in enumerate(eq_list):
        eq_clean = eq.strip()
        if eq_clean.lower() in ("ничего нет", "", "-"):
            continue
        
        text = f"✅ {eq_clean}" if eq_clean in selected else eq_clean
        if len(text) > 40:
            text = text[:37] + "..."
        button = Callback(text, payload={"action": "toggle_eq", "loc": location, "room": room_name, "idx": idx})
        equipment_buttons.append(button)

    # Добавляем кнопки по 2 в ряд
    for i in range(0, len(equipment_buttons), 2):
        kb.add(equipment_buttons[i])
        if i + 1 < len(equipment_buttons):
            kb.add(equipment_buttons[i + 1])
        kb.row()

    # Последняя строка: Подтвердить + Отменить (по 2 в ряд)
    kb.add(Callback("✅ Подтвердить", payload={"action": "confirm_eq"}))
    kb.add(Callback("❌ Отменить", payload={"action": "cancel"}))

    return kb.get_json()