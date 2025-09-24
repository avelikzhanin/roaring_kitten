import logging
from telegram import Update
from telegram.ext import ContextTypes

from services.stock_service import StockService
from utils.formatters import MessageFormatter

logger = logging.getLogger(__name__)


class TelegramHandlers:
    """Обработчики команд Telegram"""
    
    def __init__(self):
        self.stock_service = StockService()
        self.formatter = MessageFormatter()
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        welcome_message = self.formatter.format_welcome_message()
        await update.message.reply_text(welcome_message, parse_mode='HTML')
    
    async def sber_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /sber"""
        loading_message = await update.message.reply_text(
            self.formatter.format_loading_message()
        )
        
        try:
            stock_data = await self.stock_service.get_stock_data('SBER')
            
            if not stock_data:
                await loading_message.edit_text(
                    self.formatter.format_error_message("no_data")
                )
                return
            
            if not stock_data.is_valid():
                await loading_message.edit_text(
                    self.formatter.format_error_message("insufficient_data")
                )
                return
            
            message = self.formatter.format_stock_message(stock_data)
            await loading_message.edit_text(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Error in sber_command: {e}")
            await loading_message.edit_text(
                self.formatter.format_error_message("general")
            )
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ошибок"""
        logger.error(f"Update {update} caused error {context.error}")
    
    def get_handlers(self):
        """Возвращает список хендлеров для регистрации в приложении"""
        from telegram.ext import CommandHandler
        
        return [
            CommandHandler("start", self.start_command),
            CommandHandler("sber", self.sber_command)
        ]
