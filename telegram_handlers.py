import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from stock_service import StockService
from formatters import MessageFormatter
from config import SUPPORTED_STOCKS

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
    
    async def stocks_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stocks - показываем inline кнопки с акциями"""
        keyboard = []
        
        # Создаем кнопки для каждой акции
        for ticker, info in SUPPORTED_STOCKS.items():
            button = InlineKeyboardButton(
                text=f"{info['emoji']} {ticker} - {info['name']}",
                callback_data=f"stock:{ticker}"
            )
            keyboard.append([button])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = self.formatter.format_stocks_selection()
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на inline кнопки"""
        query = update.callback_query
        await query.answer()
        
        # Парсим callback_data
        if query.data.startswith("stock:"):
            ticker = query.data.split(":")[1]
            await self._get_stock_data(query, ticker)
    
    async def _get_stock_data(self, query, ticker: str):
        """Универсальный метод получения данных по акции"""
        loading_message = await query.edit_message_text(
            self.formatter.format_loading_message(ticker)
        )
        
        try:
            stock_data = await self.stock_service.get_stock_data(ticker)
            
            if not stock_data:
                await query.edit_message_text(
                    self.formatter.format_error_message("no_data")
                )
                return
            
            if not stock_data.is_valid():
                await query.edit_message_text(
                    self.formatter.format_error_message("insufficient_data")
                )
                return
            
            message = self.formatter.format_stock_message(stock_data)
            await query.edit_message_text(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Error getting {ticker} data: {e}")
            await query.edit_message_text(
                self.formatter.format_error_message("general")
            )
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ошибок"""
        logger.error(f"Update {update} caused error {context.error}")
    
    def get_handlers(self):
        """Возвращает список хендлеров для регистрации в приложении"""
        return [
            CommandHandler("start", self.start_command),
            CommandHandler("stocks", self.stocks_command),
            CallbackQueryHandler(self.button_callback),
        ]
