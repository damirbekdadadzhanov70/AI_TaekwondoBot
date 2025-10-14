# config.py — загрузка секретов из .env и настройки модели

import os
from dotenv import load_dotenv

load_dotenv()  # ищет .env в корне проекта

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")

# Модель для OpenAI (если используешь OpenAI)
# Можно заменить на ту, которая доступна в твоём аккаунте.
MODEL_NAME  = os.getenv("MODEL_NAME", "gpt-4o-mini")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.6"))