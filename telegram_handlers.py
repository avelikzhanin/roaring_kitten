import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from stock_service import StockService
from formatters import MessageFormatter
from config import SUPPORTED_STOCKS
from database import db

logger = logging.getLogger(__name__)


class TelegramHandlers:
    """Обработчики команд Telegram"""
    
    def __init__(self):
        self.stock_service = StockService()
        self.formatter = MessageFormatter()
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        
        # Сохраняем пользователя в БД
        await db.add_user(user.id, user.username, user.first_name)
        
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
    
    async def subscriptions_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /subscriptions - показать подписки"""
        user_id = update.effective_user.id
        
        subscriptions = await db.get_user_subscriptions(user_id)
        message = self.formatter.format_subscriptions_list(subscriptions)
        
        await update.message.reply_text(message, parse_mode='HTML')
    
    async def positions_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /positions - показать позиции"""
        user_id = update.effective_user.id
        
        open_positions = await db.get_open_positions(user_id)
        closed_positions = await db.get_closed_positions(user_id, limit=5)
        
        # Получаем текущие цены для открытых позиций
        current_prices = {}
        if open_positions:
            for pos in open_positions:
                ticker = pos['ticker']
                stock_data = await self.stock_service.get_stock_data(ticker)
                if stock_data:
                    current_prices[ticker] = stock_data.price.current_price
        
        message = self.formatter.format_positions_list(
            open_positions, 
            closed_positions,
            current_prices
        )
        
        await update.message.reply_text(message, parse_mode='HTML')
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на inline кнопки"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        # Парсим callback_data
        if query.data.startswith("stock:"):
            ticker = query.data.split(":")[1]
            await self._show_stock_data(query, user_id, ticker)
        
        elif query.data.startswith("subscribe:"):
            ticker = query.data.split(":")[1]
            await self._handle_subscribe(query, user_id, ticker)
        
        elif query.data.startswith("unsubscribe:"):
            ticker = query.data.split(":")[1]
            await self._handle_unsubscribe(query, user_id, ticker)
    
    async def _show_stock_data(self, query, user_id: int, ticker: str):
        """Показать данные акции с кнопками подписки"""
        await query.edit_message_text(self.formatter.format_loading_message(ticker))
        
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
            
            # Проверяем подписку
            is_subscribed = await db.is_subscribed(user_id, ticker)
            
            # Формируем сообщение
            message = self.formatter.format_stock_message(stock_data, is_subscribed)
            
            # Создаем кнопки
            keyboard = []
            
            if is_subscribed:
                keyboard.append([
                    InlineKeyboardButton(
                        text="🔕 Отписаться",
                        callback_data=f"unsubscribe:{ticker}"
                    )
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton(
                        text="🔔 Подписаться",
                        callback_data=f"subscribe:{ticker}"
                    )
                ])
            
            keyboard.append([
                InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data=f"stock:{ticker}"
                )
            ])
            
            keyboard.append([
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data="back_to_stocks"
                )
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message, 
                parse_mode='HTML',
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error getting {ticker} data: {e}")
            await query.edit_message_text(
                self.formatter.format_error_message("general")
            )
    
    async def _handle_subscribe(self, query, user_id: int, ticker: str):
        """Обработка подписки"""
        success = await db.add_subscription(user_id, ticker)
        
        if success:
            message = self.formatter.format_subscription_added(ticker)
        else:
            message = self.formatter.format_error_message("already_subscribed")
        
        await query.answer(message, show_alert=True)
        
        # Обновляем информацию о акции
        await self._show_stock_data(query, user_id, ticker)
    
    async def _handle_unsubscribe(self, query, user_id: int, ticker: str):
        """Обработка отписки"""
        success = await db.remove_subscription(user_id, ticker)
        
        if success:
            message = self.formatter.format_subscription_removed(ticker)
        else:
            message = self.formatter.format_error_message("not_subscribed")
        
        await query.answer(message, show_alert=True)
        
        # Обновляем информацию о акции
        await self._show_stock_data(query, user_id, ticker)
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ошибок"""
        logger.error(f"Update {update} caused error {context.error}")
    
    def get_handlers(self):
        """Возвращает список хендлеров для регистрации в приложении"""
        return [
            CommandHandler("start", self.start_command),
            CommandHandler("stocks", self.stocks_command),
            CommandHandler("subscriptions", self.subscriptions_command),
            CommandHandler("positions", self.positions_command),
            CallbackQueryHandler(self.button_callback),
        ]
