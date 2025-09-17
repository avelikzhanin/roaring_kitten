import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

class UserInterface:
    """Пользовательский интерфейс с РЕАЛЬНЫМИ ADX от GPT"""
    
    def __init__(self, database, signal_processor, gpt_analyzer=None):
        self.db = database
        self.signal_processor = signal_processor
        self.gpt_analyzer = gpt_analyzer
        self.app = None
    
    def set_app(self, app):
        """Установка Telegram приложения"""
        self.app = app
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start с описанием РЕАЛЬНЫХ ADX"""
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
            
            gpt_status = "🤖 <b>GPT с РЕАЛЬНЫМ ADX:</b> включен" if self.gpt_analyzer else "📊 <b>Режим:</b> только EMA20"
            
            await update.message.reply_text(
                "🐱 <b>Добро пожаловать в Ревущего котёнка!</b>\n\n"
                "📈 Вы подписаны на торговые сигналы\n"
                "🔔 Котёнок сообщит о сигналах покупки/продажи\n\n"
                f"{gpt_status}\n\n"
                "<b>🎯 УМНАЯ СТРАТЕГИЯ:</b>\n"
                "• 📊 <b>EMA20</b> - базовый фильтр тренда\n"
                "• 🤖 <b>GPT рассчитывает РЕАЛЬНЫЙ ADX</b>\n"
                "• ✅ <b>ADX > 25</b> - сильный тренд\n"
                "• ✅ <b>+DI > -DI</b> - восходящее движение\n"
                "• ✅ <b>Разница DI > 1</b> - достаточная сила\n"
                "• 🔥 <b>ADX > 45</b> - пик тренда, продавать!\n\n"
                "<b>📱 Команды:</b>\n"
                "/stop - отписаться\n"
                "/signal - проверить сигналы с ADX\n"
                "/portfolio - управление подписками",
                parse_mode='HTML'
            )
            logger.info(f"👤 Подписчик: {chat_id}")
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
        """Обработчик команды /signal с РЕАЛЬНЫМИ ADX от GPT"""
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
                
                await update.message.reply_text(f"🔍 Анализирую {symbol} ({name}) с расчетом РЕАЛЬНОГО ADX...")
                
                signal = await self.signal_processor.analyze_market(symbol)
                
                if signal:
                    # Формируем сообщение с РЕАЛЬНЫМИ ADX значениями
                    message = f"""✅ <b>АКТИВНЫЙ СИГНАЛ {symbol}</b>

💰 <b>Цена:</b> {signal.price:.2f} ₽
📈 <b>EMA20:</b> {signal.ema20:.2f} ₽

⏰ <b>Время:</b> {signal.timestamp.strftime('%H:%M %d.%m.%Y')}"""
                    
                    # Добавляем РЕАЛЬНЫЕ ADX значения если есть
                    if hasattr(signal, 'adx') and signal.adx > 0:
                        adx_status = "🟢 Сильный" if signal.adx >= 25 else "🔴 Слабый"
                        di_status = "🟢 Восходящий" if signal.plus_di > signal.minus_di else "🔴 Нисходящий"
                        
                        message += f"""

📊 <b>РЕАЛЬНЫЙ ADX ОТ GPT:</b>
• <b>ADX:</b> {signal.adx:.1f} {adx_status} тренд
• <b>+DI:</b> {signal.plus_di:.1f}
• <b>-DI:</b> {signal.minus_di:.1f} {di_status}
• <b>Разница:</b> {signal.plus_di - signal.minus_di:+.1f}"""
                    
                    # Добавляем GPT анализ
                    if self.gpt_analyzer:
                        try:
                            gpt_advice = await self._get_gpt_analysis_for_signal(signal)
                            if gpt_advice:
                                message += f"\n{self.gpt_analyzer.format_advice_for_telegram(gpt_advice, signal.symbol)}"
                            else:
                                message += "\n\n🤖 <i>Детальный GPT анализ недоступен</i>"
                        except Exception as e:
                            logger.error(f"Ошибка GPT анализа: {e}")
                            message += "\n\n🤖 <i>Детальный GPT анализ недоступен</i>"
                else:
                    message = await self.signal_processor.get_detailed_market_status(symbol)
                
                await update.message.reply_text(message, parse_mode='HTML')
                return
            
            # Если несколько подписок - показываем меню
            message = f"🔍 <b>АНАЛИЗ СИГНАЛОВ С РЕАЛЬНЫМ ADX</b>\n\n📊 <b>Подписки ({len(subscriptions)}):</b>\nВыберите акцию для ADX анализа:"
            
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
        """Анализ одной акции с РЕАЛЬНЫМИ ADX от GPT"""
        try:
            await query.answer()
            
            ticker_info = await self.db.get_ticker_info(symbol)
            name = ticker_info['name'] if ticker_info else symbol
            
            loading_message = await query.message.reply_text(f"🔍 Анализирую {symbol} ({name}) с расчетом РЕАЛЬНОГО ADX...")
            
            signal = await self.signal_processor.analyze_market(symbol)
            
            if signal:
                message = f"""✅ <b>АКТИВНЫЙ СИГНАЛ {symbol}</b>

💰 <b>Цена:</b> {signal.price:.2f} ₽
📈 <b>EMA20:</b> {signal.ema20:.2f} ₽

⏰ <b>Время:</b> {signal.timestamp.strftime('%H:%M %d.%m.%Y')}"""
                
                # Добавляем РЕАЛЬНЫЕ ADX значения
                if hasattr(signal, 'adx') and signal.adx > 0:
                    adx_status = "🟢 Сильный" if signal.adx >= 25 else "🔴 Слабый" 
                    di_status = "🟢 Восходящий" if signal.plus_di > signal.minus_di else "🔴 Нисходящий"
                    
                    message += f"""

📊 <b>РЕАЛЬНЫЙ ADX ОТ GPT:</b>
• <b>ADX:</b> {signal.adx:.1f} {adx_status} тренд
• <b>+DI:</b> {signal.plus_di:.1f}
• <b>-DI:</b> {signal.minus_di:.1f} {di_status}
• <b>Разница:</b> {signal.plus_di - signal.minus_di:+.1f}"""
                
                # Добавляем детальный GPT анализ
                if self.gpt_analyzer:
                    try:
                        gpt_advice = await self._get_gpt_analysis_for_signal(signal)
                        if gpt_advice:
                            message += f"\n{self.gpt_analyzer.format_advice_for_telegram(gpt_advice, signal.symbol)}"
                    except Exception as e:
                        logger.error(f"Ошибка GPT анализа для {symbol}: {e}")
            else:
                message = await self.signal_processor.get_detailed_market_status(symbol)
            
            try:
                await loading_message.delete()
            except:
                pass
            
            await query.message.reply_text(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Ошибка анализа {symbol}: {e}")
            try:
                await loading_message.delete()
            except:
                pass
            await query.message.reply_text(f"❌ <b>Ошибка анализа {symbol}</b>", parse_mode='HTML')
    
    async def _get_gpt_analysis_for_signal(self, signal):
        """Получение GPT анализа для сигнала с РЕАЛЬНЫМИ ADX"""
        if not self.gpt_analyzer:
            return None
        
        # Если у нас уже есть полный GPT анализ - используем его
        if hasattr(signal, 'gpt_full_advice') and signal.gpt_full_advice:
            return signal.gpt_full_advice
        
        # Иначе формируем базовые данные для GPT
        signal_data = {
            'price': signal.price,
            'ema20': signal.ema20,
            'price_above_ema': signal.price > signal.ema20,
            'conditions_met': True,  # Если у нас есть сигнал, базовые условия выполнены
        }
        
        # Добавляем РЕАЛЬНЫЕ ADX если есть
        if hasattr(signal, 'adx') and signal.adx > 0:
            signal_data.update({
                'calculated_adx': signal.adx,
                'calculated_plus_di': signal.plus_di,
                'calculated_minus_di': signal.minus_di
            })
        
        try:
            return await self.gpt_analyzer.analyze_signal(
                signal_data, None, is_manual_check=True, symbol=signal.symbol
            )
        except Exception as e:
            logger.error(f"Ошибка запроса GPT анализа: {e}")
            return None
    
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
