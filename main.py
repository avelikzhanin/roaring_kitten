import logging
from datetime import time as dt_time
from telegram import Update
from telegram.ext import Application

from config import TELEGRAM_TOKEN, MONITOR_INTERVAL_MINUTES
from telegram_handlers import TelegramHandlers
from scheduler import SignalMonitor
from database import db

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def post_init(application: Application):
    """Инициализация после запуска бота"""
    await db.connect()
    logger.info("✅ Database connected")


async def post_shutdown(application: Application):
    """Завершение работы"""
    await db.disconnect()
    logger.info("👋 Database disconnected")


def main():
    """Основная функция запуска бота"""
    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    
    handlers = TelegramHandlers()
    
    for handler in handlers.get_handlers():
        application.add_handler(handler)
    
    application.add_error_handler(handlers.error_handler)
    
    monitor = SignalMonitor()
    
    job_queue = application.job_queue
    
    # Проверка сигналов каждые N минут
    job_queue.run_repeating(
        monitor.check_signals,
        interval=MONITOR_INTERVAL_MINUTES * 60,
        first=60
    )
    
    # Ежедневный расчёт индекса страха и жадности в 19:00 МСК (16:00 UTC)
    job_queue.run_daily(
        monitor.update_fear_greed_index,
        time=dt_time(hour=16, minute=0),
    )
    
    logger.info(f"🤖 Revushiy Kotenok Bot started!")
    logger.info(f"📊 Signal monitoring every {MONITOR_INTERVAL_MINUTES} minutes")
    logger.info(f"📊 Fear & Greed Index: daily update at 19:00 MSK")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
