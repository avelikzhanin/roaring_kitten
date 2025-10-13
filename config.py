import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

# PostgreSQL
DATABASE_URL = os.getenv('DATABASE_URL')

# OpenAI
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

if not TELEGRAM_TOKEN:
    raise ValueError("Missing TELEGRAM_TOKEN environment variable")

if not DATABASE_URL:
    raise ValueError("Missing DATABASE_URL environment variable")

if not OPENAI_API_KEY:
    raise ValueError("Missing OPENAI_API_KEY environment variable")

# MOEX API настройки
MOEX_BASE_URL = "https://iss.moex.com/iss"
MOEX_TIMEOUT = 10

# Технические индикаторы
DEFAULT_ADX_PERIOD = 14
DEFAULT_EMA_PERIOD = 20
HISTORY_DAYS = 10
MAX_CANDLES = 50

# Пороговые значения для сигналов
ADX_THRESHOLD = 25
DI_PLUS_THRESHOLD = 25

# Мониторинг
MONITOR_INTERVAL_MINUTES = 20

# Поддерживаемые акции
SUPPORTED_STOCKS = {
    'SBER': {
        'name': 'Сбербанк',
        'emoji': '🏦'
    },
    'GAZP': {
        'name': 'Газпром',
        'emoji': '🛢️'
    },
    'LKOH': {
        'name': 'ЛУКОЙЛ',
        'emoji': '⛽'
    },
    'VTBR': {
        'name': 'ВТБ',
        'emoji': '🏛️'
    },
    'HEAD': {
        'name': 'Headhunter',
        'emoji': '🧑‍💼'
    }
}
