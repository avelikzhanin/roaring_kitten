import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

class UserInterface:
    """Пользовательский интерфейс бота"""
    
    def __init__(self, database, signal_processor, gpt_analyzer=None):
        self.db = database
        self.signal_processor = signal_processor
        self.gpt_analyzer = gpt_analyzer
        self.app = None
    
    def set_app(self, app):
        """Установка Telegram приложения"""
        self.app = app
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        chat_id = update.effective_chat.id
        user = update.effective_user
        
        # Добавляем пользователя в БД
        success = await self.db.add_or_update_user(
            telegram_id=chat_id,
            username=user.username if user else None,
            first_name=user.first_name if user else None
        )
        
        if success:
            # Автоматически подписываем на SBER
            await self.db.subscribe_user_to_ticker(chat_id, 'SBER')
            
            gpt_status = "🤖 <b>GPT анализ:</b> включен" if self.gpt_analyzer else "📊 <b>Режим:</b> технический анализ"
            
            await update.message.reply_text(
                "🐱 <b>Добро пожаловать в Ревущего котёнка!</b>\n\n"
                "📈 Вы подписаны на торговые сигналы\n"
                "🔔 Котёнок сообщит о сигналах покупки/продажи\n\n"
                f"{gpt_status}\n\n"
                "<b>Стратегия:</b>\n"
                "• EMA20 - цена выше средней\n"
                "• ADX > 25 - сильный тренд\n"
                "• +DI > -DI (разница > 1)\n"
                "• 🔥 ADX > 45 - пик, продавать!\n\n"
                "<b>Команды:</b>\n"
                "/stop - отписаться\n"
                "/signal - проверить сигналы\n"
                "/portfolio - управление подписками",
                parse_mode='HTML'
            )
            logger.info(f"👤 Подписчик: {chat_id} (@{user.username if user else 'unknown'})")
        else:
            await update.message.reply_text(
                "❌ <b>Ошибка подключения к БД</b>\n\nПопробуйте позже.",
                parse_mode='HTML'
            )
    
    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stop"""
        chat_id = update.effective_chat.id
        await self.db.deactivate_user(chat_id)
        
        await update.message.reply_text(
            "❌ <b>Вы отписались от котёнка</b>\n\n"
            "Все позиции закрыты.\n"
            "Для возврата используйте /start",
            parse_mode='HTML'
        )
        logger.info(f"👤 Отписка: {chat_id}")
    
    async def portfolio_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда управления портфелем"""
        chat_id = update.effective_chat.id
        subscriptions = await self.db.get_user_subscriptions(chat_id)
        available_tickers = await self.db.get_available_tickers()
        
        if subscriptions:
            sub_list = [f"🔔 {sub['symbol']} ({sub['name']})" for sub in subscriptions]
            message = f"📊 <b>ВАШ ПОРТФЕЛЬ</b>\n\n<b>Подписки:</b>\n" + "\n".join(sub_list)
        else:
            message = "📊 <b>ВАШ ПОРТФЕЛЬ</b>\n\n<b>У вас нет подписок</b>"
        
        keyboard = []
        subscribed_symbols = {sub['symbol'] for sub in subscriptions}
        
        for ticker in available_tickers:
            symbol = ticker['symbol']
            name = ticker['name']
            if symbol in subscribed_symbols:
                button_text = f"🔔 {symbol} ({name}) ❌"
                callback_data = f"unsub_{symbol}"
            else:
                button_text = f"⚪ {symbol} ({name}) ➕"
                callback_data = f"sub_{symbol}"
            
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, parse_mode='HTML', reply_markup=reply_markup)
    
    async def signal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
