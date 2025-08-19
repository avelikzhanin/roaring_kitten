import asyncio
import logging
import signal
import sys
from src.trading_bot import TradingBot
import os

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Graceful shutdown для Railway
def signal_handler(sig, frame):
    logger.info('Бот получил сигнал остановки')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

async def main():
    """Главная функция запуска бота"""
    
    # Получаем токены из переменных окружения
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
    
    if not TELEGRAM_TOKEN or not TINKOFF_TOKEN:
        logger.error("Не заданы токены в переменных окружения")
        return
    
    # Создаем и запускаем бота
    trading_bot = TradingBot(TELEGRAM_TOKEN, TINKOFF_TOKEN)
    
    try:
        await trading_bot.start()
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
        sys.exit(1)
