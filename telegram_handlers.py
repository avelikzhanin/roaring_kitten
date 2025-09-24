import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

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
        """Обработчик команды /stocks - список всех поддерживаемых акций"""
        stocks_message = self.formatter.format_stocks_list()
        await update.message.reply_text(stocks_message, parse_mode='HTML')
    
    async def stock_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Универсальная команда /stock TICKER"""
        if not context.args:
            await update.message.reply_text(
                "❌ Укажите тикер акции.\n\nПример: <code>/stock SBER</code>\n\nДоступные тикеры: /stocks", 
                parse_mode='HTML'
            )
            return
        
        ticker = context.args[0].upper()
        await self._get_stock_data(update, ticker)
    
    async def _get_stock_data(self, update: Update, ticker: str):
        """Универсальный метод получения данных по акции"""
        # Проверяем поддержку тикера
        if ticker not in SUPPORTED_STOCKS:
            supported_tickers = ', '.join(SUPPORTED_STOCKS.keys())
            await update.message.reply_text(
                f"❌ Тикер {ticker} не поддерживается.\n\n"
                f"Доступные тикеры: {supported_tickers}\n\n"
                f"Полный список: /stocks", 
                parse_mode='HTML'
            )
            return
        
        loading_message = await update.message.reply_text(
            self.formatter.format_loading_message(ticker)
        )
        
        try:
            stock_data = await self.stock_service.get_stock_data(ticker)
            
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
            logger.error(f"Error getting {ticker} data: {e}")
            await loading_message.edit_text(
                self.formatter.format_error_message("general")
            )
    
    # Отдельные команды для каждой акции (для удобства)
    async def sber_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /sber"""
        await self._get_stock_data(update, 'SBER')
    
    async def gazp_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /gazp"""
        await self._get_stock_data(update, 'GAZP')
    
    async def lkoh_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /lkoh"""
        await self._get_stock_data(update, 'LKOH')
    
    async def vtbr_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /vtbr"""
        await self._get_stock_data(update, 'VTBR')
    
    async def head_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /head"""
        await self._get_stock_data(update, 'HEAD')
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ошибок"""
        logger.error(f"Update {update} caused error {context.error}")
    
    def get_handlers(self):
        """Возвращает список хендлеров для регистрации в приложении"""
        return [
            CommandHandler("start", self.start_command),
            CommandHandler("stocks", self.stocks_command),
            CommandHandler("stock", self.stock_command),
            # Отдельные команды для каждой акции
            CommandHandler("sber", self.sber_command),
            CommandHandler("gazp", self.gazp_command),
            CommandHandler("lkoh", self.lkoh_command),
            CommandHandler("vtbr", self.vtbr_command),
            CommandHandler("head", self.head_command),
        ]
