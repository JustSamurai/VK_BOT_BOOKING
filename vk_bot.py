#VK_BOT.PY
import logging
import asyncio
from datetime import datetime

from vkbottle import API
from vkbottle.bot import Bot, Message
from colorama import init, Fore, Style

import vk_config
from handlers.vk_user_handlers import register_user_handlers

init(autoreset=True)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(name)s:%(lineno)d | %(message)s'
)

bot = Bot(token=vk_config.token_test)
api = API(token=vk_config.token_test) 

def setup_and_run():
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    register_user_handlers(bot)
    # register_admin_handlers(bot)

    print(f"{Fore.GREEN}{Style.BRIGHT}{start_time} --- БОТ ЗАПУЩЕН!!! --- {Style.RESET_ALL}")
    bot.run_forever()

if __name__ == "__main__":
    setup_and_run()