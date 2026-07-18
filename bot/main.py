from aiogram import Bot
import os
from dotenv import load_dotenv

from aiogram.client.default import DefaultBotProperties


load_dotenv()

bot = Bot(token=os.getenv("telegram_bot_token"), default=DefaultBotProperties(parse_mode="HTML"))