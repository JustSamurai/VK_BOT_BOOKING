import os
from vkbottle import BuiltinStateDispenser
from vkbottle.bot import BotLabeler

token_test = "" #токен группы ВК CALL-BACK

group_id = 0 # ID группы
peer_id = 0 # ID чувачка

rules = "" # на будущее

database_path = os.path.join(os.path.dirname(__file__), 'booking.db')

labeler = BotLabeler()
state_dispenser = BuiltinStateDispenser()
