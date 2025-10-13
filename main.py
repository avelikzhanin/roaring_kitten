import logging
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
    # Подключаемся к базе данных
    await db.connect()
    logger.info("✅ Database connected")


async def post_shutdown(application: Application):
    """Завершение работы"""
    # Отключаемся от базы данных
    await db.disconnect()
    logger.info("👋 Database disconnected")


def main():
    """Основная функция запуска бота"""
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    
    # Создаем обработчики команд
    handlers = TelegramHandlers()
    
    # Регистрируем обработчики команд
    for handler in handlers.get_handlers():
        application.add_handler(handler)
    
    # Регистрируем обработчик ошибок
    application.add_error_handler(handlers.error_handler)
    
    # Создаем монитор сигналов
    monitor = SignalMonitor()
    
    # Добавляем задачу периодической проверки сигналов
    job_queue = application.job_queue
    job_queue.run_repeating(
        monitor.check_signals,
        interval=MONITOR_INTERVAL_MINUTES * 60,  # переводим в секунды
        first=60  # первая проверка через 60 секунд после запуска
    )
    
    logger.info(f"🤖 Revushiy Kotenok Bot started!")
    logger.info(f"📊 Signal monitoring every {MONITOR_INTERVAL_MINUTES} minutes")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
