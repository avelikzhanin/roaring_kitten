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
        """Обработчик команды /signal"""
        try:
            chat_id = update.effective_chat.id
            subscriptions = await self.db.get_user_subscriptions(chat_id)
            
            if not subscriptions:
                await update.message.reply_text(
                    "📊 <b>У вас нет подписок</b>\n\n"
                    "Используйте /portfolio для управления",
                    parse_mode='HTML'
                )
                return
            
            # Если одна подписка - сразу анализируем
            if len(subscriptions) == 1:
                symbol = subscriptions[0]['symbol']
                name = subscriptions[0]['name']
                
                await update.message.reply_text(f"🔍 Анализирую {symbol} ({name})...")
                
                signal = await self.signal_processor.analyze_market(symbol)
                
                if signal:
                    message = f"""✅ <b>АКТИВНЫЙ СИГНАЛ {symbol}</b>

💰 <b>Цена:</b> {signal.price:.2f} ₽
📈 <b>EMA20:</b> {signal.ema20:.2f} ₽
📊 <b>ADX:</b> {signal.adx:.1f} | <b>+DI:</b> {signal.plus_di:.1f} | <b>-DI:</b> {signal.minus_di:.1f}

⏰ <b>Время:</b> {signal.timestamp.strftime('%H:%M %d.%m.%Y')}"""
                    
                    # Добавляем GPT анализ
                    if self.gpt_analyzer:
                        try:
                            gpt_advice = await self._get_gpt_analysis_for_signal(signal)
                            if gpt_advice:
                                # ИСПРАВЛЕНИЕ: передаем symbol в форматтер
                                message += f"\n{self.gpt_analyzer.format_advice_for_telegram(gpt_advice, signal.symbol)}"
                            else:
                                message += "\n\n🤖 <i>GPT анализ недоступен</i>"
                        except:
                            message += "\n\n🤖 <i>GPT анализ недоступен</i>"
                else:
                    message = await self.signal_processor.get_detailed_market_status(symbol)
                
                await update.message.reply_text(message, parse_mode='HTML')
                return
            
            # Если несколько подписок - показываем меню
            message = f"🔍 <b>АНАЛИЗ СИГНАЛОВ</b>\n\n📊 <b>Подписки ({len(subscriptions)}):</b>\nВыберите акцию:"
            
            keyboard = []
            for sub in subscriptions:
                symbol = sub['symbol']
                name = sub['name']
                keyboard.append([InlineKeyboardButton(f"📊 {symbol} ({name})", callback_data=f"analyze_{symbol}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(message, parse_mode='HTML', reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Ошибка /signal: {e}")
            await update.message.reply_text(
                "❌ <b>Ошибка проверки сигналов</b>\n\nПопробуйте позже.",
                parse_mode='HTML'
            )

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик inline кнопок"""
        query = update.callback_query
        chat_id = query.message.chat_id
        data = query.data
        
        if data.startswith("sub_"):
            symbol = data[4:]
            success = await self.db.subscribe_user_to_ticker(chat_id, symbol)
            
            if success:
                await query.answer(f"✅ Подписка на {symbol} активирована!")
                await self._update_portfolio_message(query)
            else:
                await query.answer("❌ Ошибка подписки", show_alert=True)
        
        elif data.startswith("unsub_"):
            symbol = data[6:]
            success = await self.db.unsubscribe_user_from_ticker(chat_id, symbol)
            
            if success:
                await query.answer(f"❌ Отписка от {symbol}")
                await self._update_portfolio_message(query)
            else:
                await query.answer("❌ Ошибка отписки", show_alert=True)
        
        elif data.startswith("analyze_"):
            symbol = data[8:]
            await self._analyze_single_ticker(query, symbol)
    
    async def _analyze_single_ticker(self, query, symbol: str):
        """Анализ одной акции"""
        try:
            await query.answer()
            
            ticker_info = await self.db.get_ticker_info(symbol)
            name = ticker_info['name'] if ticker_info else symbol
            
            loading_message = await query.message.reply_text(f"🔍 Анализирую {symbol} ({name})...")
            
            signal = await self.signal_processor.analyze_market(symbol)
            
            if signal:
                message = f"""✅ <b>АКТИВНЫЙ СИГНАЛ {symbol}</b>

💰 <b>Цена:</b> {signal.price:.2f} ₽
📈 <b>EMA20:</b> {signal.ema20:.2f} ₽
📊 <b>ADX:</b> {signal.adx:.1f} | <b>+DI:</b> {signal.plus_di:.1f} | <b>-DI:</b> {signal.minus_di:.1f}

⏰ <b>Время:</b> {signal.timestamp.strftime('%H:%M %d.%m.%Y')}"""
                
                if self.gpt_analyzer:
                    try:
                        gpt_advice = await self._get_gpt_analysis_for_signal(signal)
                        if gpt_advice:
                            # ИСПРАВЛЕНИЕ: передаем symbol в форматтер
                            message += f"\n{self.gpt_analyzer.format_advice_for_telegram(gpt_advice, signal.symbol)}"
                    except:
                        pass
            else:
                message = await self.signal_processor.get_detailed_market_status(symbol)
            
            try:
                await loading_message.delete()
            except:
                pass
            
            await query.message.reply_text(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Ошибка анализа {symbol}: {e}")
            await query.message.reply_text(f"❌ <b>Ошибка анализа {symbol}</b>", parse_mode='HTML')
    
    async def _get_gpt_analysis_for_signal(self, signal):
        """Получение GPT анализа для сигнала"""
        if not self.gpt_analyzer:
            return None
        
        signal_data = {
            'price': signal.price,
            'ema20': signal.ema20,
            'adx': signal.adx,
            'plus_di': signal.plus_di,
            'minus_di': signal.minus_di
        }
        
        # ИСПРАВЛЕНИЕ: передаем symbol в GPT анализатор
        return await self.gpt_analyzer.analyze_signal(
            signal_data, None, is_manual_check=True, symbol=signal.symbol
        )
    
    async def _update_portfolio_message(self, query):
        """Обновление сообщения портфеля"""
        try:
            chat_id = query.message.chat_id
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
            await query.edit_message_text(message, parse_mode='HTML', reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Ошибка обновления портфеля: {e}")
