from vkbottle.bot import Bot, Message
from vkbottle import API
import vk_config
import asyncio


bot = Bot(token=vk_config.token_test)
api = API(token=vk_config.token_test) 

@bot.on.message(text=["Привет"])
def handler(message: Message):
    print(f"УРА! Сообщение пришло: {message.text}")
    message.answer("Че?")

print("Тестовый бот запущен. Напиши ему в ЛС группы!")
bot.run_forever()