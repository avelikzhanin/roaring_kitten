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

# Глобальная переменная для бота
trading_bot = None

# Graceful shutdown для Railway
def signal_handler(sig, frame):
    logger.info('Бот получил сигнал остановки')
    if trading_bot:
        # Создаем новый event loop для shutdown, если текущий закрыт
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            loop.run_until_complete(trading_bot.shutdown())
        except Exception as e:
            logger.error(f"Ошибка при остановке: {e}")
    
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

async def main():
    """Главная функция запуска бота"""
    global trading_bot
    
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
        await trading_bot.shutdown()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        if trading_bot:
            await trading_bot.shutdown()
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
        sys.exit(1)
