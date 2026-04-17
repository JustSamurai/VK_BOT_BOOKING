import pytest
from unittest.mock import MagicMock, patch
# Замените 'your_module' на имя вашего файла
from src.handlers.vk_user_handlers import start_booking

def test_start_booking_new_user():
    # 1. Создаем имитацию (Mock) объекта сообщения
    message = MagicMock()
    message.from_id = 123456
    # В некоторых библиотеках ВК используется message.user_id или message.from_id
    # Подстройте под вашу библиотеку
    message.from_user.id = 123456
    message.from_user.username = "test_user"

    # 2. Мокаем функции базы данных, чтобы они не лезли в реальные файлы/БД
    with patch("your_module.get_user_state") as mock_get_state, \
         patch("your_module.get_user") as mock_get_user:
        
        # Ситуация: пользователь новый, данных нет
        mock_get_state.return_value = {}
        mock_get_user.return_value = None
        
        # 3. Вызываем функцию
        start_booking(message)
        
        # 4. Проверяем результат
        # Проверяем, что была вызвана отправка сообщения
        message.answer.assert_called_once()
        
        # Проверяем, что текст сообщения содержит "Введите ФИО"
        args, kwargs = message.answer.call_args
        assert "Введите ФИО (полностью)" in kwargs["message"]
        # Проверяем, что клавиатура передана
        assert "keyboard" in kwargs

def test_start_booking_existing_user():
    message = MagicMock()
    message.from_user.id = 777
    message.from_user.username = "ivan_ivanov"

    with patch("your_module.get_user_state") as mock_get_state, \
         patch("your_module.get_user") as mock_get_user:
        
        # Имитируем существующего пользователя
        mock_get_state.return_value = {}
        mock_get_user.return_value = {
            "name": "Иван Иванов",
            "phone": "8999",
            "student_id": "123",
            "group": "ИВТ-1"
        }
        
        start_booking(message)
        
        # Проверяем приветствие (помним про split)
        args, kwargs = message.answer.call_args
        assert "Привет, Иванов!" in kwargs["message"]
        assert "Бронирование" in kwargs["keyboard"]