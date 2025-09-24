import logging
from telegram import Update
from telegram.ext import Application

from config import TELEGRAM_TOKEN
from handlers.telegram_handlers import TelegramHandlers

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    """Основная функция запуска бота"""
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Создаем обработчики команд
    handlers = TelegramHandlers()
    
    # Регистрируем обработчики команд
    for handler in handlers.get_handlers():
        application.add_handler(handler)
    
    # Регистрируем обработчик ошибок
    application.add_error_handler(handlers.error_handler)
    
    logger.info("🤖 SBER Telegram Bot started with MOEX API...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
