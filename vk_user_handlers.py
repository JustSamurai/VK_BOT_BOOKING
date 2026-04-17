#VK_USER_HANDLERS.PY
import asyncio
import re

from vkbottle import (Keyboard, Callback, Text, OpenLink)
from vkbottle.bot import Bot, Message
from vkbottle import API, VKAPIError, BaseStateGroup
from vkbottle.dispatch.rules import ABCRule

from datetime import datetime
from typing import Dict, List, Any, Optional
from vk_keyboards import (get_locations_keyboard, get_rooms_keyboard, get_equipment_keyboard, get_equipment_for_room)
from vk_database import ( load_cabinets_data)
from vk_database import ( get_user, save_user)
from vk_database import (get_user_state, save_user_state)

import vk_config  
import logging

# TODO: Разделить ввод ДАТЫ, ВРЕМЕНИ НАЧАЛА, ВРЕМЕНИ КОНЦА мероприятия                                      + + +
# TODO: Сделать маски для проверки ФИО (введены Фамилия, Имя, Отчество), номера телефона, даты, времени.    + + +
# TODO: Создать новую таблицу для записи всех заявок с сохранением информации: кто, что, когда              + + +
    # TODO: Выводить номер сохраненной заявки модератору                                                    + + +

# TODO: Сделать отмену определенной брони в одной заявке                                                    + +
# TODO: Начать переносить функции модератора из старых исходников                                           + +

# FIXME: Бот не отвечает на сообщения на версии 3.14 и выше. Файл vk_bot                                    +
# FIXME: Поменять логику комментария, чтобы он был в конце цепочки после броинрования всех помещений.       + + +
# FIXME: Заменить функционал кнопки Отмена на функционал кнопки Назад                                       + +
# FIXME: Мой мозг                                                                                           + + + + + +

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(name)s:%(lineno)d | %(message)s'
)

def validate_phone(phone: str) -> bool:
    # Удаляем всё, кроме цифр
    digits = re.sub(r'\D', '', phone)
    # Проверяем: 11 цифр, начинается на 7 или 8
    return bool(re.match(r'^(7|8)\d{10}$', digits))

class ModerationStates(BaseStateGroup):
    WAITING_FOR_COMMENT = "waiting_for_comment"

CABINETS_DATA = load_cabinets_data()

LOCATION_CODES = {}       # "loc_1" → "Коворкинг"
LOCATION_BY_CODE = {}     # "Коворкинг" → "loc_1"

loc_index = 1
for loc_name in sorted(CABINETS_DATA.keys()):
    code = f"loc_{loc_index}"
    LOCATION_CODES[code] = loc_name
    LOCATION_BY_CODE[loc_name] = code
    loc_index += 1

# 2. Кабинеты (аудитории) — уникальный код по всему боту
ROOM_CODES = {}           # "room_5" → ("Коворкинг", "№202")
ROOM_BY_CODE = {}         # ("Коворкинг", "№202") → "room_5"

room_index = 1
for loc_name, rooms in CABINETS_DATA.items():
    for room_info in rooms:
        room_name = room_info.get("Аудитория", "").strip()
        if room_name:
            code = f"room_{room_index}"
            ROOM_CODES[code] = (loc_name, room_name)
            ROOM_BY_CODE[(loc_name, room_name)] = code
            room_index += 1

# 3. Оборудование — коды уникальны в пределах одной комнаты
#    (можно генерировать динамически при выборе комнаты, но для простоты — тоже глобально)

EQUIPMENT_CODES = {}      # "eq_42" → ("Коворкинг", "№202", "Переносная колонка")
EQUIPMENT_BY_CODE = {}    # ("Коворкинг", "№202", "Переносная колонка") → "eq_42"

eq_index = 1
for loc_name, rooms in CABINETS_DATA.items():
    for room_info in rooms:
        room_name = room_info.get("Аудитория", "").strip()
        if not room_name:
            continue
        for eq_item in room_info.get("Оборудование", []):
            eq_name = eq_item.strip()
            if eq_name and eq_name.lower() not in ("ничего нет", "", "-"):
                code = f"eq_{eq_index}"
                EQUIPMENT_CODES[code] = (loc_name, room_name, eq_name)
                EQUIPMENT_BY_CODE[(loc_name, room_name, eq_name)] = code
                eq_index += 1

print("=== Сгенерированные коды ===")
print(f"Локаций: {len(LOCATION_CODES)}")
for code, name in sorted(LOCATION_CODES.items()):
    print(f"  {code} → {name}")

print(f"\nКабинетов всего: {len(ROOM_CODES)}")
for code, (loc, room) in sorted(ROOM_CODES.items()):
    print(f"  {code} → {loc} | {room}")

print(f"\nУникальных позиций оборудования: {len(EQUIPMENT_CODES)}")
# print для примера первых 10
for code, (loc, room, eq) in list(EQUIPMENT_CODES.items()):
    print(f"  {code} → {loc} | {room} | {eq}")

user_sessions = {}

async def start_booking(message: Message) -> None:
    user_id = message.from_id
    
    # 1. Получаем сессию напрямую (без лишних словарей внутри)
    state_data = await asyncio.to_thread(get_user_state, user_id)
    session = state_data.get("data", {})

    # 2. Загружаем данные из таблицы users (БД)
    existing = await asyncio.to_thread(get_user, user_id)

    # 3. Если сессия совсем пустая (первый раз), создаем структуру
    if not session or "user" not in session:
        session = {
            "user": {
                "vk_id": user_id,
                "name": "",
                "phone": "",
                "student_id": "",
                "group": "",
                "division": "",
            },
            "state": "main_menu",
        }

    # 4. СИНХРОНИЗАЦИЯ: Если в БД данные есть, а в сессии нет — копируем их
    if existing:
        # Синхронизируем данные из БД в сессию
        session["user"]["name"] = existing.get("name") or ""
        session["user"]["phone"] = existing.get("phone") or ""
        session["user"]["division"] = existing.get("division") or ""
        # Берем из БД 'student_group'
        db_group = existing.get("student_group") or ""
        db_inst = existing.get("institute") or ""
        
        if db_group:
            session["user"]["student_id"] = f"{db_group} / {db_inst}"

    # 5. ПРОВЕРКА ЗАПОЛНЕННОСТИ
    required = ["name", "phone", "student_id",]
    is_fully_registered = all(session["user"].get(k) for k in required)

    if is_fully_registered:
        session["state"] = "main_menu" # или "event"
        # Отрисовка меню (с кнопками Бронирование, Правила)
        kb = (
            Keyboard(inline=True)
            .add(Callback("📅 Бронирование", payload={"action": "start_new_booking"}))
            .row()
            .add(Callback("⚙️ Изменить данные", payload={"action": "edit_profile"}))
            .get_json()
        )
        await message.answer(f"С возвращением, {session['user']['name']}!", keyboard=kb)
    else:
        # Запускаем регистрацию
        session["state"] = "name"
        await message.answer("👋 Начнем регистрацию. Введите ФИО:")

    # 6. Сохраняем актуальную сессию обратно в БД
    await asyncio.to_thread(save_user_state, user_id, session["state"], session)


# -----------------------------------------------------------------
# 3️⃣  Обработчики колбэков
# -----------------------------------------------------------------
async def handle_callback(event, api: API) -> None:
    """Обработчик всех нажатий на inline‑кнопки."""
    obj = event.get("object", {})
    payload = obj.get("payload")
    
    if not payload:
        return

    vk_id = obj.get("user_id")
    action = payload.get("action")

    # Текущее состояние пользователя
    state_data = await asyncio.to_thread(get_user_state, vk_id)
    session = state_data.get("data", {})
    current_state = state_data.get("state", "main_menu")

    # ---------- Отмена ----------
    if action == "cancel":
        await api.messages.edit(
            peer_id=vk_id,
            conversation_message_id=obj.get("conversation_message_id"),
            message="❌ Действие отменено.",
            keyboard=None,
        )
        await asyncio.to_thread(save_user_state, vk_id, "main_menu", {})
        return

    # ---------- Показать правила ----------
    if action == "show_rules":
        await api.messages.edit(
            peer_id=vk_id,
            conversation_message_id=obj.get("conversation_message_id"),
            message=vk_config.rules,
            keyboard=(
                Keyboard(inline=True)
                .add(Callback("📅 Начать бронирование", payload={"action": "start_new_booking"}))
                .add(Callback("❌ Закрыть", payload={"action": "cancel"}))
                .get_json()
            ),
        )
        return

    # ---------- Начать новое бронирование ----------
    if action == "start_new_booking":
        session["current_booking"] = None
        session["bookings"] = session.get("bookings", [])
        session["state"] = "location"

        await api.messages.edit(
            peer_id=vk_id,
            conversation_message_id=obj.get("conversation_message_id"),
            message="Выберите корпус / локацию:",
            keyboard=get_locations_keyboard(LOCATION_CODES),
        )
        await asyncio.to_thread(save_user_state, vk_id, "location", session)
        return

    # ---------- Выбор локации ----------
    if action == "select_location":
        print(f"[CALLBACK] select_location от {vk_id}, code={payload.get('code')}")
        code = payload.get("code")
        if code not in LOCATION_CODES:
            await api.messages.send(peer_id=vk_id, message="Ошибка: локация не найдена", random_id=0)
            return

        location = LOCATION_CODES[code]
        session["current_booking"] = {"location": location, "equipment": []}
        session["state"] = "room"

        await api.messages.edit(
            peer_id=vk_id,
            conversation_message_id=obj.get("conversation_message_id"),
            message=f"Выбрана локация: **{location}**\n\nВыберите аудиторию:",
            keyboard=get_rooms_keyboard(location, CABINETS_DATA, ROOM_BY_CODE),
        )
        await asyncio.to_thread(save_user_state, vk_id, "room", session)
        return

    # ---------- Выбор аудитории ----------
    if action == "select_room":
        code = payload.get("code")
        if code not in ROOM_CODES:
            await api.messages.send(peer_id=vk_id, message="Ошибка: аудитория не найдена", random_id=0)
            return

        location, room_name = ROOM_CODES[code]
        session["current_booking"]["room"] = room_name
        session["current_booking"]["equipment"] = []
        session["state"] = "equipment"

        kb = get_equipment_keyboard(location, room_name, selected=[])
        await api.messages.edit(
            peer_id=vk_id,
            conversation_message_id=obj.get("conversation_message_id"),
            message=f"Аудитория: **{room_name}** ({location})\n\nВыберите оборудование:",
            keyboard=kb,
        )
        await asyncio.to_thread(save_user_state, vk_id, "equipment", session)
        return

    # ---------- Переключение оборудования ----------
    if action == "toggle_eq":
        loc = payload.get("loc")
        room = payload.get("room")
        idx = payload.get("idx")

        if not all([loc, room, idx is not None]):
            await api.messages.send(peer_id=vk_id, message="Ошибка данных кнопки", random_id=0)
            return

        if session.get("current_booking") is None:
            session["current_booking"] = {
                "loc": loc,
                "room": room,
                "equipment": []
            }

        try:
            idx = int(idx)
        except (ValueError, TypeError):
            await api.messages.send(peer_id=vk_id, message="Неверный индекс оборудования", random_id=0)
            return

        eq_list = get_equipment_for_room(loc, room)
        if idx < 0 or idx >= len(eq_list):
            await api.messages.send(peer_id=vk_id, message="Оборудование не найдено", random_id=0)
            return

        eq_name = eq_list[idx].strip()
        equipment = session["current_booking"].setdefault("equipment", [])

        if eq_name in equipment:
            equipment.remove(eq_name)
        else:
            equipment.append(eq_name)

        kb = get_equipment_keyboard(loc, room, equipment)

        await api.messages.edit(
            peer_id=vk_id,
            conversation_message_id=obj.get("conversation_message_id"),
            message=f"Аудитория: **{room}** ({loc})\n\nВыберите оборудование:",
            keyboard=kb,
        )
        await asyncio.to_thread(save_user_state, vk_id, "equipment", session)
        return

    # ---------- Подтверждение выбора оборудования ----------
    if action == "confirm_eq":
        current = session.get("current_booking") or {}
        if not current.get("equipment"):
            await api.messages.send(
                peer_id=vk_id,
                message="Выберите хотя бы одно оборудование или нажмите «Отмена»",
                random_id=0,
            )
            return

        session["state"] = "datetime"
        if not session.get("current_booking"):
            session["current_booking"] = current

        await api.messages.edit(
            peer_id=vk_id,
            conversation_message_id=obj.get("conversation_message_id"),
            message="Пожалуйста, введите дату и время в понятном формате.\nПример: 17.03.2026 с 14:00 до 16:30",
            keyboard=None,
        )
        await asyncio.to_thread(save_user_state, vk_id, "datetime", session)
        return

    if action == "finish":
    # Финализация заявки — отправляем в группу на модерацию
        print(f"[FINISH] Завершение брони для {vk_id}")

    # Добавляем текущую бронь в список, если она есть
        if session.get("current_booking") and "datetime_text" in session["current_booking"]:
            session.setdefault("bookings", []).append(session["current_booking"])
            session["current_booking"] = None

        if not session.get("bookings"):
            await api.messages.edit(
            peer_id=vk_id,
            conversation_message_id=obj.get("conversation_message_id"),
            message="У вас нет забронированных помещений. Заявка отменена.",
            keyboard=None,
        )
            await asyncio.to_thread(save_user_state, vk_id, "main_menu", {})
            return

    # Формируем итоговый текст заявки
        summary = format_summary(session["bookings"], session["user"])

        try:
            group_kb = Keyboard(inline=True)
            group_kb.add(
            Callback("✅ Одобрить", payload=
                     {"action": "approve", "user_id": vk_id})
        )
            group_kb.add(
            Callback("❌ Отклонить", payload={"action": "reject", "user_id": vk_id})
        )

            await api.messages.send(
            peer_id=vk_config.peer_id,
            message=summary,
            keyboard=group_kb.get_json(),
            random_id=0
        )

            await api.messages.edit(
            peer_id=vk_id,
            conversation_message_id=obj.get("conversation_message_id"),
            message="✅ Заявка успешно отправлена на рассмотрение!\nОжидайте ответа от администратора.\nДля новой заявки напишите /start",
            keyboard=None,
        )
            user_data = session.get("user", {})
        # Сохраняем пользователя
            await asyncio.to_thread(
                save_user,
                vk_id=vk_id,
                name=str(session["user"].get("name", "")),
                phone=str(session["user"].get("phone", "")),
                student_id=str(session["user"].get("student_id", "")),
                group=str(session["user"].get("group", "")),
                institute=str(session["user"].get("institute", "")),
                position=str(session["user"].get("position", "")),
                division=str(session["user"].get("division", "")),
                link=f"https://vk.com{vk_id}",
            )

        # Очищаем состояние
            await asyncio.to_thread(save_user_state, vk_id, "main_menu", {})

        except Exception as e:
            print(f"Ошибка при отправке заявки: {e}")
            await api.messages.edit(
            peer_id=vk_id,
            conversation_message_id=obj.get("conversation_message_id"),
            message=f"Ошибка при отправке заявки: {str(e)}",
            keyboard=None,
        )

        return

    if action == "add_another":
        # 1. Забираем текущую (заполненную) бронь и кладем в общий список
        current = session.get("current_booking")
        if current:
            # Используем setdefault, чтобы создать список, если его еще нет, и добавляем бронь
            session.setdefault("bookings", []).append(current)
        
        # 2. Теперь очищаем черновик для НОВОЙ брони
        session["current_booking"] = None
        session["state"] = "location"

        # 3. Выводим выбор локации
        await api.messages.edit(
            peer_id=vk_id,
            conversation_message_id=obj.get("conversation_message_id"),
            message="✅ Предыдущая бронь сохранена.\nВыберите корпус / локацию для новой брони:",
            keyboard=get_locations_keyboard(LOCATION_CODES),
        )
        
        await asyncio.to_thread(save_user_state, vk_id, "location", session)
        return

    if action == "back_to_locations":
        session["state"] = "location"
        kb_locations = get_locations_keyboard(LOCATION_CODES) 
    
        await api.messages.edit(
            peer_id=vk_id,
            message="Выберите корпус или локацию:",
            conversation_message_id=obj.get("conversation_message_id"), # Важно для замены кнопок
            keyboard=kb_locations
        )
        return

    if action == "back_to_rooms":
        location = obj.get("loc")

        if location is None:
            location = session.get("current_booking", {}).get("location")

        if not location:
            await api.messages.send(peer_id=vk_id, message="⚠️ Не удалось определить локацию. Вернитесь в начало.", random_id=0)
            return

        session["state"] = "select_room"
        
        kb_rooms = get_rooms_keyboard(location, CABINETS_DATA, ROOM_BY_CODE)
        
        await api.messages.edit(
            peer_id=vk_id,
            message=f"Выберите аудиторию в локации {location}:",
            conversation_message_id=obj.get("conversation_message_id"),
            keyboard=kb_rooms
        )
        
        await asyncio.to_thread(save_user_state, vk_id, "room_selection", session)
        return

    # ---------- Неизвестное действие ----------
    await api.messages.send(
        peer_id=vk_id,
        message="Неизвестная команда или действие устарело.\nПопробуйте /start",
        random_id=0,
    )


# -----------------------------------------------------------------
# 4️⃣  Обработчик текстовых сообщений (диалог)
# -----------------------------------------------------------------
async def handle_text_input(message: Message, api: API) -> None:
    vk_id = message.from_id
    text = message.text.strip()

    # Текущее состояние
    state_data = await asyncio.to_thread(get_user_state, vk_id)
    current_state = state_data.get("state", "main_menu")
    session = state_data.get("data", {})

    # -----------------------------------------------------------------
    # Главное меню – пользователь пишет произвольный текст
    # -----------------------------------------------------------------
    if current_state == "main_menu":
        await message.answer("Напиши /start или нажми кнопку, чтобы начать бронирование.")
        return

    # -----------------------------------------------------------------
    # Ввод персональных данных (регистрация / редактирование)
    # -----------------------------------------------------------------
    personal_states = ("name", "phone", "student_id", "group")
    if current_state in personal_states:
        session["user"][current_state] = text

        if current_state == "group":
            session["user"]["division"] = text  # Записываем в division для базы
        else:
            session["user"][current_state] = text

        if current_state == "phone":
                clean_num = validate_phone(message.text)
                if not clean_num:
                    await message.answer("❌ Ошибка в номере. Введите 11 цифр, начиная с 8 или 7.")
                    return
                session["phone"] = clean_num

        await asyncio.to_thread(
            save_user,
            vk_id=vk_id,
            name=str(session["user"].get("name", "")),
            phone=str(session["user"].get("phone", "")),
            student_id=str(session["user"].get("student_id", "")),
            group=str(session["user"].get("group", "")),
            institute=str(session["user"].get("institute", "")),
            position=str(session["user"].get("position", "")),
            division=str(session["user"].get("division", "")),
            link=f"https://vk.com{vk_id}",
        )

        # Если редактируем профиль и дошли до последнего поля
        if session.get("is_editing") and current_state == "group":
            await asyncio.to_thread(
                save_user,
                vk_id=vk_id,
                name=str(session["user"].get("name", "")),
                phone=str(session["user"].get("phone", "")),
                student_id=str(session["user"].get("student_id", "")),
                group=str(session["user"].get("group", "")),
                institute=str(session["user"].get("institute", "")),
                position=str(session["user"].get("position", "")),
                division=str(session["user"].get("division", "")),
                link=f"https://vk.com{vk_id}",
            )
            await message.answer("✅ Профиль успешно обновлён!")
            session.pop("is_editing", None)
            session["state"] = "main_menu"
            await asyncio.to_thread(save_user_state, vk_id, "main_menu", session)

            await message.answer(
                "Теперь можно бронировать аудитории.\nНапиши /start или нажми кнопку ниже.",
                keyboard=(
                    Keyboard(inline=True)
                    .add(Callback("📅 Начать бронирование", payload={"action": "start_new_booking"}))
                    .get_json()
                ),
            )
            return

        # Обычная последовательная регистрация
        try:
            next_idx = personal_states.index(current_state) + 1
            if next_idx < len(personal_states):
                next_state = personal_states[next_idx]
                prompts = {
                    "phone": "Введите номер телефона (например: 89123456789 или 79123456789)",
                    "student_id": "Введите группу , институт / должность."
                    "\nПример: ТБ25-01, ИИТК или Специалист отдела",
                    "group": "Введите название студенческого объединения / подразделения."
                    "\nПример: Союз студентов или ЦСО или «-»",
                }
                await message.answer(prompts.get(next_state, "Следующий шаг:"))
                session["state"] = next_state
                await asyncio.to_thread(save_user_state, vk_id, next_state, session)
                return
        except ValueError:
            pass

        # После последнего поля – переходим к вводу названия мероприятия
        session["state"] = "event"
        await message.answer("Введите полное название мероприятия (что будете проводить):")
        await asyncio.to_thread(save_user_state, vk_id, "event", session)
        return

    # -----------------------------------------------------------------
    # Информация о мероприятии
    # -----------------------------------------------------------------
    event_states = ("event", "responsible", "list_people")
    if current_state in event_states:
        session["user"][current_state] = text
        idx = event_states.index(current_state)

        if idx + 1 < len(event_states):
            next_state = event_states[idx + 1]
            prompts = {
                "responsible": "ФИО и номер телефона ответственного за мероприятие:",
                "list_people": "Список участников не из университета (если нет — напишите «—»):",
            }
            await message.answer(prompts.get(next_state, "Продолжаем..."))
            session["state"] = next_state
            await asyncio.to_thread(save_user_state, vk_id, next_state, session)
            return

        # После последнего поля → переходим к выбору локации
        session["state"] = "location"
        await message.answer(
            "Теперь выберите корпус / локацию:",
            keyboard=get_locations_keyboard(LOCATION_CODES)
        )
        await asyncio.to_thread(save_user_state, vk_id, "location", session)
        return

    # ───────────────────────────────────────────────
    # Ввод даты и времени
    # ───────────────────────────────────────────────
    if current_state == "datetime":
        # Простая проверка формата (можно усилить регуляркой)
        if not re.search(r"\d{1,2}\.\d{1,2}\.\d{4}.*(с|до|с\s+\d{1,2}:\d{2})", text.lower()):
            await message.answer(
                "Пожалуйста, введите дату и время в понятном формате.\n"
                "Пример: 17.03.2026 с 14:00 до 16:30"
            )
            return

        session["current_booking"]["datetime_text"] = text
        session["state"] = "comment" # Переводим на коммент
        await message.answer("Введите комментарий (или '-')")
        await asyncio.to_thread(save_user_state, vk_id, "comment", session)
        return

    if current_state == "comment":
        session["user"]["comment"] = text if text and text.strip("—- ") else "—"

        # Добавляем последнюю бронь, если она была
        if session.get("current_booking") and "datetime_text" in session["current_booking"]:
            # Формируем предварительный просмотр одной брони
            booking = session["current_booking"]
            session.setdefault("bookings", []).append(session["current_booking"])
            eq_list = ", ".join(booking.get("equipment", [])) or "— ничего не выбрано"
            session["current_booking"] = None

            preview_text = (
                f"Добавлена бронь:\n"
                f"• {booking['location']} — {booking['room']}\n"
                f"• Оборудование: {eq_list}\n"
                f"• {text}\n\n"
                f"Хотите добавить ещё одну аудиторию?"
            )

            kb = Keyboard(inline=True)
            kb.add(Callback("➕ Ещё одно помещение", payload={"action": "add_another"}))
            kb.row()
            kb.add(Callback("✅ Всё, готово", payload={"action": "finish"}))

            await message.answer(preview_text, keyboard=kb)
            session["state"] = "wait_decision"
            await asyncio.to_thread(save_user_state, vk_id, "wait_decision", session)
            return
        
        if not session.get("bookings"):
            message.answer("У вас нет забронированных помещений. Заявка отменена.")
            save_user_state(vk_id, "main_menu", {})
            return

        # Формируем итоговое сообщение
        summary = format_summary(session["bookings"], session["user"])

        try:
            payload = {
                "action": "approve", # или "reject"
                "user_id": vk_id,
                # Если данные очень большие, этот метод не сработает — нужна БД
            }
            # Отправляем заявку в группу
            group_kb = Keyboard(inline=True)
            group_kb.add(Callback("✅ Одобрить", payload={**payload, "action": "approve"}))
            
            group_kb.add(
                Callback("❌ Отклонить", payload={**payload, "action": "reject"}))

            api.messages.send(
                peer_id=vk_config.peer_id,
                message=summary,
                keyboard=group_kb,
                random_id=0
            )
            message.answer(
                "✅ Заявка успешно отправлена на рассмотрение!\n"
                "Ожидайте ответа от администратора.\n"
                "Для новой заявки напишите /start"
            )
            # Сохраняем обновлённые данные пользователя (если изменились)
            await asyncio.to_thread(
                save_user,
                vk_id=vk_id,
                name=str(session["user"].get("name", "")),
                phone=str(session["user"].get("phone", "")),
                student_id=str(session["user"].get("student_id", "")),
                group=str(session["user"].get("group", "")),
                institute=str(session["user"].get("institute", "")),
                position=str(session["user"].get("position", "")),
                division=str(session["user"].get("division", "")),
                link=f"https://vk.com{vk_id}",
            )
            # Очищаем сессию
            save_user_state(vk_id, "main_menu", {})
        except Exception as e:
            message.answer(f"Ошибка при отправке заявки: {str(e)}")
            print(f"Ошибка отправки в группу: {e}")
        return
    # Если состояние неизвестно
    message.answer("Произошла ошибка состояния. Напишите /start для перезапуска.")
    save_user_state(vk_id, "main_menu", {})
    return

def format_summary(bookings: list[dict], user: dict) -> str:
    lines = ["НОВАЯ ЗАЯВКА НА БРОНИРОВАНИЕ\n"]
    
    lines.append(f"ФИО: {user.get('name', '—')}")
    lines.append(f"Телефон: {user.get('phone', '—')}")
    lines.append(f"Группа, институт / должность: {user.get('student_id', '—')}")
    lines.append(f"Объединение / подразделение: {user.get('group', '—')}\n")
    
    lines.append(f"Название мероприятия: {user.get('event', '—')}")
    lines.append(f"Ответственный: {user.get('responsible', '—')}")
    lines.append(f"Участники из других вузов:\n{user.get('list_people', '—')}\n")
    
    for i, b in enumerate(bookings, 1):
        eq = ", ".join(b.get("equipment", [])) or "—"
        lines.append(f"{i}. {b.get('location', '—')} — {b.get('room', '—')}")
        lines.append(f"   Оборудование: {eq}")
        lines.append(f"   Время: {b.get('datetime_text', '—')}\n")
    
    lines.append(f"Комментарий: {user.get('comment', '—')}")
    lines.append(f"\nОтправитель: vk.com/id{user.get('vk_id', '—')}")
    
    return "\n".join(lines)

def format_processed_summary(bookings: list[dict], user: dict, vk_id: str, comment: str, status: str) -> str:
    lines = [f"✅ ЗАЯВКА ОБРАБОТАНА\nРешение: {status}\n"]
    
    # Блок данных пользователя
    lines.append(f"ФИО: {user.get('name', '—')}")
    lines.append(f"Телефон: {user.get('phone', '—')}")
    lines.append(f"Группа, институт / должность: {user.get('student_id', '—')}")
    lines.append(f"Объединение / подразделение: {user.get('group', '—')}\n")
    
    lines.append(f"Название мероприятия: {user.get('event', '—')}")
    lines.append(f"Ответственный: {user.get('responsible', '—')}\n")
    
    # Блок бронирований
    for i, b in enumerate(bookings, 1):
        eq = ", ".join(b.get("equipment", [])) or "—"
        lines.append(f"{i}. {b.get('location', '—')} — {b.get('room', '—')}")
        lines.append(f"   Оборудование: {eq}")
        lines.append(f"   Время: {b.get('datetime_text', '—')}\n")
    
    # Блок модерации
    lines.append(f"Комментарий модератора: {comment}")
    lines.append(f"Модератор: [id{vk_id}|Профиль]")
    lines.append(f"\nОтправитель: ://vk.com{user.get('vk_id', '—')}")
    
    return "\n".join(lines)

class InDialogRule(ABCRule[Message]):
    async def check(self, message: Message) -> bool:
        """Возвращает True, если пользователь уже начал диалог."""
        state_data = await asyncio.to_thread(get_user_state, message.from_id)
        # Если данных нет – считаем, что пользователь в главном меню
        if not state_data:
            return False
        return state_data.get("state") != "main_menu"


def register_user_handlers(bot: Bot) -> None:
    # 1. ТЕКСТ: Обработчик комментария модератора (САМЫЙ ВЫСОКИЙ ПРИОРИТЕТ)
    @bot.on.message(state=ModerationStates.WAITING_FOR_COMMENT)
    async def process_moderator_comment(message: Message):
        state_record = await bot.state_dispenser.get(message.peer_id)
    
        if not state_record:
            return

        state_data = state_record.payload # Данные лежат в .payload
        vk_id = message.from_id
    
        await bot.state_dispenser.delete(message.peer_id)

        target_user_id = state_data["target_user_id"]
        status = state_data["status"]
        orig_peer = state_data["original_peer_id"]
        orig_msg_id = state_data["original_conversation_message_id"]

        comment = message.text.strip()
        if comment == "-": comment = "Без комментария"

        try:
            user_text = f"🔔 **Обновление по вашей заявке**\nСтатус: **{status}**\n💬 Комментарий: {comment}"
            await bot.api.messages.send(peer_id=target_user_id, message=user_text, random_id=0)
        except: pass

        try:
            updated_text = format_processed_summary(
                bookings=state_data.get("bookings", []),
                user=state_data.get("user", {}), 
                vk_id=vk_id,
                comment=comment,
                status=status
            )
            await bot.api.messages.edit(
                peer_id=orig_peer, 
                conversation_message_id=orig_msg_id,
                message=updated_text
            )
        except Exception as e:
            print(f"Ошибка: {e}")

        await message.answer("✅ Решение успешно отправлено.")

    # 2. ТЕКСТ: Стандартные команды
    @bot.on.message(text=["/start", "start", "Начать", "начать"])
    async def start_handler(message: Message) -> None:
        await start_booking(message)

    # 3. ВСЕ CALLBACK-КНОПКИ (ЕДИНЫЙ ОБРАБОТЧИК)
    @bot.on.raw_event("message_event")
    async def common_callback_handler(event: dict) -> None:
        obj = event.get("object", {})
        payload = obj.get("payload") or {}
        action = payload.get("action")
        vk_id = obj.get("user_id")

        # А) Отвечаем ВК сразу, чтобы убрать "загрузку" на кнопке
        try:
            await bot.api.messages.send_message_event_answer(
                event_id=obj.get("event_id"), user_id=vk_id, peer_id=obj.get("peer_id")
            )
        except: pass

        # Б) Логика МОДЕРАЦИИ (approve/reject)
        if action in ("approve", "reject"):
            target_user_id = payload.get("user_id")
            bookings_data = payload.get("bookings", [])
            user_data = payload.get("user", {})
            # peer_id здесь — это ID группы (отрицательное число)
            group_peer_id = obj.get("peer_id") 
            vk_id = obj.get("user_id") # Кто нажал (модератор)
            
            status = "ОДОБРЕНА" if action == "approve" else "ОТКЛОНЕНА"

            # ВАЖНО: ставим стейт на ID БЕСЕДЫ (peer_id)
            await bot.state_dispenser.set(
                obj.get("peer_id"), 
                ModerationStates.WAITING_FOR_COMMENT,
                # Передаем данные напрямую как именованные аргументы
                target_user_id=target_user_id,
                status=status,
                bookings=bookings_data,
                user=user_data,
                original_peer_id=obj.get("peer_id"),
                original_conversation_message_id=obj.get("conversation_message_id")
            )

            await bot.api.messages.send(
                peer_id=obj.get("peer_id"), 
                message=f"📝 [id{vk_id}|Модератор], введите комментарий здесь:",
                random_id=0
            )
            return

        if action == "start_new_booking":
            # 1. Получаем текущую сессию
            state_data = await asyncio.to_thread(get_user_state, vk_id)
            session = state_data.get("data", {})

            # 2. Сбрасываем старое бронирование и ставим стейт "event"
            session["current_booking"] = {}
            session["state"] = "event"
    
            # 3. Сохраняем обновленный стейт в базу
            await asyncio.to_thread(save_user_state, vk_id, "event", session)

            # 4. Отправляем сообщение (то самое, которое идет после регистрации)
            await bot.api.messages.send(
                peer_id=vk_id,
                message="🚀 Начинаем бронирование!\n\nВведите название мероприятия (что будете проводить):",
                random_id=0
            )
            return

        # В) Логика РЕДАКТИРОВАНИЯ ПРОФИЛЯ
        if action == "edit_profile":
            state_data = await asyncio.to_thread(get_user_state, vk_id)
            session = state_data.get("data", {})
            session.update({"state": "name", "is_editing": True})
            await asyncio.to_thread(save_user_state, vk_id, "name", session)
            await bot.api.messages.send(peer_id=vk_id, message="🔄 Введите новое ФИО:", random_id=0)
            return

        # Г) ВСЕ ОСТАЛЬНЫЕ КНОПКИ (через ваш handle_callback)
        try:
            await handle_callback(event, bot.api)
        except Exception as e:
            print(f"Ошибка в handle_callback: {e}")

    # 4. ТЕКСТ: Все остальное (InDialogRule)
    @bot.on.message(InDialogRule())
    async def dialog_text_handler(message: Message) -> None:
        await handle_text_input(message, bot.api)

    print("✅ Все хендлеры успешно зарегистрированы (без дублей)")