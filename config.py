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

# OpenAI GPT настройки
GPT_MODEL = "gpt-5-mini"
GPT_MAX_TOKENS = 2000  # Увеличено для reasoning
GPT_TEMPERATURE = 0.7

# Мани-менеджмент
DEPOSIT = 10_000_000  # Депозит в рублях
RISK_PERCENT = 5.0  # Риск на сделку в процентах от депозита
STOP_LOSS_PERCENT = 5.0  # Stop Loss в процентах от цены входа
AVERAGING_LEVEL_1 = 2.0  # Первая доливка при -2% от входа
AVERAGING_LEVEL_2 = 4.0  # Вторая доливка при -4% от входа

# Поддерживаемые акции
SUPPORTED_STOCKS = {
    'SBER': {
        'name': 'Сбербанк',
        'emoji': '🏦',
        'lot_size': 10  # 1 лот = 10 акций
    },
    'GAZP': {
        'name': 'Газпром',
        'emoji': '🛢️',
        'lot_size': 10
    },
    'LKOH': {
        'name': 'ЛУКОЙЛ',
        'emoji': '⛽',
        'lot_size': 1
    },
    'VTBR': {
        'name': 'ВТБ',
        'emoji': '🏛️',
        'lot_size': 100
    },
    'HEAD': {
        'name': 'Headhunter',
        'emoji': '🧑‍💼',
        'lot_size': 1
    }
}
