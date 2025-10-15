import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from stock_service import StockService
from formatters import MessageFormatter
from config import SUPPORTED_STOCKS
from database import db
from gpt_analyst import gpt_analyst

logger = logging.getLogger(__name__)


class TelegramHandlers:
    """Обработчики команд Telegram"""
    
    def __init__(self):
        self.stock_service = StockService()
        self.formatter = MessageFormatter()
    
    def _create_main_keyboard(self):
        """Создание главной ReplyKeyboard"""
        keyboard = [
            ["📊 Сигналы", "💼 Позиции"]
        ]
        return ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True
        )
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        
        # Сохраняем пользователя в БД
        await db.add_user(user.id, user.username, user.first_name)
        
        welcome_message = self.formatter.format_welcome_message()
        
        # Отправляем приветствие с ReplyKeyboard
        await update.message.reply_text(
            welcome_message,
            parse_mode='HTML',
            reply_markup=self._create_main_keyboard()
        )
    
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений от ReplyKeyboard"""
        text = update.message.text
        user_id = update.effective_user.id
        
        if text == "📊 Сигналы":
            # Показываем список акций
            await self._send_stocks_list(update, user_id)
        
        elif text == "💼 Позиции":
            # Показываем позиции
            await self._send_positions(update, user_id)
    
    async def _send_stocks_list(self, update: Update, user_id: int):
        """Отправить список акций"""
        keyboard = []
        
        # Создаем кнопки для каждой акции с иконками подписки
        for ticker, info in SUPPORTED_STOCKS.items():
            is_subscribed = await db.is_subscribed(user_id, ticker)
            icon = "⭐ " if is_subscribed else ""
            
            button = InlineKeyboardButton(
                text=f"{icon}{info['emoji']} {ticker} - {info['name']}",
                callback_data=f"stock:{ticker}"
            )
            keyboard.append([button])
        
        # Добавляем кнопку "Главное меню"
        keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = self.formatter.format_stocks_selection()
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def _send_positions(self, update: Update, user_id: int):
        """Отправить позиции"""
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
        
        keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, parse_mode='HTML', reply_markup=reply_markup)
    
    async def stocks_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stocks - показываем inline кнопки с акциями"""
        user_id = update.effective_user.id
        await self._send_stocks_list(update, user_id)
    
    async def positions_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /positions - показать позиции"""
        user_id = update.effective_user.id
        await self._send_positions(update, user_id)
    
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
        
        elif query.data.startswith("gpt_analyze:"):
            ticker = query.data.split(":")[1]
            await self._handle_gpt_analysis(query, user_id, ticker)
        
        elif query.data == "back_to_stocks":
            await self._show_stocks_list_inline(query, user_id)
        
        elif query.data == "main_menu":
            await self._show_main_menu(query)
        
        elif query.data == "menu_stocks":
            await self._show_stocks_list_inline(query, user_id)
        
        elif query.data == "menu_positions":
            await self._show_positions_inline(query, user_id)
    
    async def _show_main_menu(self, query):
        """Показать главное меню"""
        welcome_message = self.formatter.format_welcome_message()
        
        await query.edit_message_text(welcome_message, parse_mode='HTML')
    
    async def _show_stocks_list_inline(self, query, user_id: int):
        """Показать список акций (для inline callback)"""
        keyboard = []
        
        # Создаем кнопки для каждой акции с иконками подписки
        for ticker, info in SUPPORTED_STOCKS.items():
            is_subscribed = await db.is_subscribed(user_id, ticker)
            icon = "⭐ " if is_subscribed else ""
            
            button = InlineKeyboardButton(
                text=f"{icon}{info['emoji']} {ticker} - {info['name']}",
                callback_data=f"stock:{ticker}"
            )
            keyboard.append([button])
        
        # Добавляем кнопку "Главное меню"
        keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = self.formatter.format_stocks_selection()
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def _show_positions_inline(self, query, user_id: int):
        """Показать позиции (для inline callback)"""
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
        
        keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, parse_mode='HTML', reply_markup=reply_markup)
    
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
                        text="✖️ Отписаться",
                        callback_data=f"unsubscribe:{ticker}"
                    )
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton(
                        text="⭐ Подписаться",
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
                    text="🤖 GPT анализ",
                    callback_data=f"gpt_analyze:{ticker}"
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
        
        stock_info = SUPPORTED_STOCKS.get(ticker, {})
        emoji = stock_info.get('emoji', '📊')
        name = stock_info.get('name', ticker)
        
        if success:
            message = f"⭐ Вы подписались на {emoji} {ticker} - {name}\n\nВы будете получать уведомления о сигналах!"
        else:
            message = "ℹ️ Вы уже подписаны на эту акцию."
        
        await query.answer(message, show_alert=True)
        
        # Обновляем информацию о акции
        await self._show_stock_data(query, user_id, ticker)
    
    async def _handle_unsubscribe(self, query, user_id: int, ticker: str):
        """Обработка отписки"""
        success = await db.remove_subscription(user_id, ticker)
        
        stock_info = SUPPORTED_STOCKS.get(ticker, {})
        emoji = stock_info.get('emoji', '📊')
        name = stock_info.get('name', ticker)
        
        if success:
            message = f"✖️ Вы отписались от {emoji} {ticker} - {name}"
        else:
            message = "ℹ️ Вы не подписаны на эту акцию."
        
        await query.answer(message, show_alert=True)
        
        # Обновляем информацию о акции
        await self._show_stock_data(query, user_id, ticker)
    
    async def _handle_gpt_analysis(self, query, user_id: int, ticker: str):
        """Обработка запроса GPT анализа"""
        await query.edit_message_text("🤖 GPT анализирует свечи...")
        
        try:
            # Получаем данные акции
            stock_data = await self.stock_service.get_stock_data(ticker)
            
            if not stock_data or not stock_data.is_valid():
                await query.edit_message_text(
                    self.formatter.format_error_message("no_data")
                )
                return
            
            # Получаем свечи для анализа
            candles_data = await self.stock_service.moex_client.get_historical_candles(ticker)
            
            if not candles_data:
                await query.edit_message_text(
                    self.formatter.format_error_message("no_data")
                )
                return
            
            # Запрашиваем GPT анализ
            gpt_analysis = await gpt_analyst.analyze_stock(stock_data, candles_data)
            
            if not gpt_analysis:
                await query.edit_message_text(
                    "❌ Не удалось получить анализ от GPT. Попробуйте позже."
                )
                return
            
            # Формируем и отправляем сообщение
            message = self.formatter.format_gpt_analysis_message(stock_data, gpt_analysis)
            
            # Кнопка назад
            keyboard = [[InlineKeyboardButton("◀️ Назад к акции", callback_data=f"stock:{ticker}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error in GPT analysis for {ticker}: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка при анализе. Попробуйте позже."
            )
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ошибок"""
        logger.error(f"Update {update} caused error {context.error}")
    
    def get_handlers(self):
        """Возвращает список хендлеров для регистрации в приложении"""
        return [
            CommandHandler("start", self.start_command),
            CommandHandler("stocks", self.stocks_command),
            CommandHandler("positions", self.positions_command),
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message),
            CallbackQueryHandler(self.button_callback),
        ]
