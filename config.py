import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

if not TELEGRAM_TOKEN:
    raise ValueError("Missing TELEGRAM_TOKEN environment variable")

# MOEX API настройки
MOEX_BASE_URL = "https://iss.moex.com/iss"
MOEX_TIMEOUT = 10

# Технические индикаторы
DEFAULT_ADX_PERIOD = 14
DEFAULT_EMA_PERIOD = 20
HISTORY_DAYS = 10
MAX_CANDLES = 50

# Пороговые значения для сигналов
ADX_STRONG_TREND_THRESHOLD = 25

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
