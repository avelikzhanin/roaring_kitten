# src/trading_bot.py (ИСПРАВЛЕННАЯ ВЕРСИЯ)
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import pandas as pd
from dataclasses import dataclass

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError, TimedOut, NetworkError

from .data_provider import TinkoffDataProvider
from .indicators import TechnicalIndicators
from .gpt_analyzer import GPTMarketAnalyzer, GPTAdvice  # ИСПРАВЛЕН ИМПОРТ

logger = logging.getLogger(__name__)

@dataclass
class TradingSignal:
    """Структура торгового сигнала"""
    timestamp: datetime
    price: float
    ema20: float
    adx: float
    plus_di: float
    minus_di: float

class TradingBot:
    """Основной класс торгового бота с GPT интеграцией"""
    
    def __init__(self, telegram_token: str, tinkoff_token: str, openai_token: str = None):
        self.telegram_token = telegram_token
        self.tinkoff_provider = TinkoffDataProvider(tinkoff_token)
        
        # GPT анализатор (опциональный)
        self.gpt_analyzer = GPTMarketAnalyzer(openai_token) if openai_token else None
        
        self.subscribers: List[int] = []
        self.last_signal_time: Optional[datetime] = None
        self.app: Optional[Application] = None
        self.is_running = False
        self.current_signal_active = False
        self.last_conditions_met = False
        self._signal_task = None
        self.buy_price: Optional[float] = None

    async def shutdown(self):
        """Graceful shutdown бота"""
        logger.info("Начинаем остановку бота...")
        self.is_running = False
        
        # Отменяем задачу проверки сигналов
        if self._signal_task and not self._signal_task.done():
            self._signal_task.cancel()
            try:
                await self._signal_task
            except asyncio.CancelledError:
                pass
        
        # Останавливаем Telegram бота
        if self.app:
            try:
                await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()
                logger.info("Telegram бот остановлен")
            except Exception as e:
                logger.error(f"Ошибка при остановке Telegram бота: {e}")
        
        logger.info("Бот успешно остановлен")

    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stop"""
        chat_id = update.effective_chat.id
        
        if chat_id in self.subscribers:
            self.subscribers.remove(chat_id)
            await update.message.reply_text("❌ Вы отписались от торговых сигналов")
            logger.info(f"Пользователь отписался: {chat_id}")
        else:
            await update.message.reply_text("ℹ️ Вы не были подписаны на сигналы")
        
    async def start(self):
        """Запуск бота"""
        try:
            # Создаем приложение Telegram
            self.app = Application.builder().token(self.telegram_token).build()
            
            # Добавляем обработчики команд
            self.app.add_handler(CommandHandler("start", self.start_command))
            self.app.add_handler(CommandHandler("stop", self.stop_command))
            self.app.add_handler(CommandHandler("signal", self.signal_command))
            
            gpt_status = "с ИИ анализом" if self.gpt_analyzer else "базовая версия"
            logger.info(f"🚀 Запуск котёнка ({gpt_status})...")
            
            # Запускаем периодическую проверку
            self.is_running = True
            self._signal_task = asyncio.create_task(self.check_signals_periodically())
            
            # Инициализируем и запускаем Telegram бота
            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling(drop_pending_updates=True)
            
            # Ждем до остановки
            try:
                await asyncio.gather(self._signal_task)
            except asyncio.CancelledError:
                logger.info("Задача проверки сигналов отменена")
                
        except Exception as e:
            logger.error(f"Ошибка в start(): {e}")
            await self.shutdown()
            raise
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start с информацией о GPT"""
        chat_id = update.effective_chat.id
        
        if chat_id not in self.subscribers:
            self.subscribers.append(chat_id)
            
            gpt_info = ""
            if self.gpt_analyzer:
                gpt_info = """
🧠 <b>Новинка: ИИ анализ!</b>
• Каждый сигнал проверяется ИИ
• Получайте экспертные рекомендации
• Понимайте ПОЧЕМУ стоит покупать
"""
            
            await update.message.reply_text(
                f"""🐱 <b>Добро пожаловать в Торгового котёнка!</b>

📈 Вы подписаны на торговые сигналы по SBER{gpt_info}

<b>Параметры стратегии:</b>
• EMA20 - цена выше средней
• ADX > 25 - сильный тренд
• +DI > -DI (разница > 1) - восходящее движение
• 🔥 ADX > 45 - пик тренда, время продавать!

<b>Команды:</b>
/stop - отписаться от сигналов
/signal - проверить текущий сигнал""",
                parse_mode='HTML'
            )
            logger.info(f"Новый подписчик: {chat_id}")
        else:
            await update.message.reply_text("✅ Вы уже подписаны на сигналы!")
    
    async def signal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /signal с GPT анализом"""
        try:
            await update.message.reply_text("🔍 Анализирую рынок...")
            
            # Выполняем технический анализ
            signal = await self.analyze_market()
            
            if signal:
                # Получаем совет от GPT
                gpt_advice = None
                if self.gpt_analyzer:
                    await update.message.reply_text("🧠 Запрашиваю мнение ИИ...")
                    
                    signal_data = {
                        'ticker': 'SBER',
                        'price': signal.price,
                        'ema20': signal.ema20,
                        'adx': signal.adx,
                        'plus_di': signal.plus_di,
                        'minus_di': signal.minus_di
                    }
                    
                    gpt_advice = await self.gpt_analyzer.get_signal_advice(signal_data)
                
                # Форматируем сообщение с GPT анализом
                message = self.format_signal_with_gpt(signal, gpt_advice)
            else:
                # Детальный анализ почему нет сигнала
                message = await self._format_no_signal_analysis()
            
            await update.message.reply_text(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Ошибка в команде /signal: {e}")
            await update.message.reply_text("❌ Ошибка анализа. Попробуйте позже.")
    
    def format_signal_with_gpt(self, signal: TradingSignal, gpt_advice: Optional[GPTAdvice] = None) -> str:
        """Форматирование сигнала с GPT анализом"""
        
        # Базовое сообщение
        base_message = f"""🔔 <b>СИГНАЛ ПОКУПКИ SBER</b>

💰 <b>Цена:</b> {signal.price:.2f} ₽
📈 <b>EMA20:</b> {signal.ema20:.2f} ₽ (цена выше)

📊 <b>Индикаторы:</b>
• <b>ADX:</b> {signal.adx:.1f} (сильный тренд >25)
• <b>+DI:</b> {signal.plus_di:.1f}
• <b>-DI:</b> {signal.minus_di:.1f}
• <b>Разница DI:</b> {signal.plus_di - signal.minus_di:.1f}"""

        # Добавляем GPT анализ если доступен
        if gpt_advice:
            # Эмодзи на основе рекомендации
            recommendation_emoji = {
                "BUY": "🟢",
                "WEAK_BUY": "🟡", 
                "AVOID": "🔴"
            }
            
            emoji = recommendation_emoji.get(gpt_advice.recommendation, "🤖")
            
            # Переводим рекомендации на русский
            recommendation_text = {
                "BUY": "ПОКУПАТЬ",
                "WEAK_BUY": "ОСТОРОЖНО ПОКУПАТЬ",
                "AVOID": "НЕ ПОКУПАТЬ"
            }
            
            rec_text = recommendation_text.get(gpt_advice.recommendation, gpt_advice.recommendation)
            
            gpt_section = f"""

🤖 <b>МНЕНИЕ ИИ:</b>
{emoji} <b>{rec_text}</b> (уверенность {gpt_advice.confidence}%)

💭 <b>Объяснение:</b>
{gpt_advice.reasoning}"""
            
            if gpt_advice.risk_warning:
                gpt_section += f"""

⚠️ <b>Риск:</b> {gpt_advice.risk_warning}"""
            
            base_message += gpt_section
        else:
            # Если GPT недоступен
            base_message += f"""

🤖 <b>ИИ анализ:</b> временно недоступен
📊 Решение принимайте на основе технического анализа"""
        
        return base_message
    
    async def send_signal_to_subscribers(self, signal: TradingSignal):
        """Отправка сигнала с GPT анализом всем подписчикам"""
        if not self.app:
            logger.error("Telegram приложение не инициализировано")
            return
        
        # Получаем GPT совет
        gpt_advice = None
        if self.gpt_analyzer:
            try:
                signal_data = {
                    'ticker': 'SBER',
                    'price': signal.price,
                    'ema20': signal.ema20,
                    'adx': signal.adx,
                    'plus_di': signal.plus_di,
                    'minus_di': signal.minus_di
                }
                gpt_advice = await self.gpt_analyzer.get_signal_advice(signal_data)
                logger.info(f"GPT совет получен: {gpt_advice.recommendation if gpt_advice else 'Нет'}")
            except Exception as e:
                logger.error(f"Ошибка получения GPT совета: {e}")
        
        # Форматируем сообщение
        message = self.format_signal_with_gpt(signal, gpt_advice)
        
        # Отправляем всем подписчикам
        failed_chats = []
        successful_sends = 0
        
        for chat_id in self.subscribers.copy():
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id, 
                    text=message, 
                    parse_mode='HTML'
                )
                successful_sends += 1
                await asyncio.sleep(0.1)
                
            except (TelegramError, TimedOut, NetworkError) as e:
                logger.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")
                failed_chats.append(chat_id)
        
        # Удаляем недоступные чаты
        for chat_id in failed_chats:
            if chat_id in self.subscribers:
                self.subscribers.remove(chat_id)
        
        logger.info(f"Умный сигнал отправлен: {successful_sends} получателей, {len(failed_chats)} ошибок")

    async def analyze_market(self) -> Optional[TradingSignal]:
        """Анализ рынка и генерация сигнала"""
        try:
            # Получаем данные
            candles = await self.tinkoff_provider.get_candles(hours=100)
            if len(candles) < 50:
                logger.warning(f"Недостаточно данных: {len(candles)} свечей")
                return None
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty or len(df) < 50:
                logger.warning("Пустой или недостаточный DataFrame")
                return None
            
            # Рассчитываем индикаторы
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
            adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            
            # Последние значения
            current_price = closes[-1]
            current_ema20 = ema20[-1]
            current_adx = adx_data['adx'][-1]
            current_plus_di = adx_data['plus_di'][-1]
            current_minus_di = adx_data['minus_di'][-1]
            
            # Проверяем условия сигнала
            if (current_price > current_ema20 and
                current_adx > 25 and
                current_plus_di > current_minus_di and
                (current_plus_di - current_minus_di) > 1):
                
                return TradingSignal(
                    timestamp=datetime.now(timezone.utc),
                    price=current_price,
                    ema20=current_ema20,
                    adx=current_adx,
                    plus_di=current_plus_di,
                    minus_di=current_minus_di
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка анализа рынка: {e}")
            return None

    async def check_signals_periodically(self):
        """Периодическая проверка сигналов"""
        while self.is_running:
            try:
                logger.info("🔍 Проверяем рынок...")
                
                signal = await self.analyze_market()
                conditions_met = signal is not None
                
                # Логика отправки сигналов
                if conditions_met and not self.current_signal_active:
                    # Новый сигнал покупки
                    await self.send_signal_to_subscribers(signal)
                    self.current_signal_active = True
                    self.last_signal_time = datetime.now(timezone.utc)
                    self.buy_price = signal.price
                    logger.info(f"✅ Сигнал покупки отправлен по цене {signal.price:.2f}")
                    
                elif not conditions_met and self.current_signal_active:
                    # Сигнал отмены
                    await self.send_cancel_signal()
                    self.current_signal_active = False
                    self.buy_price = None
                    logger.info("❌ Сигнал отмены отправлен")
                
                # Проверяем пик тренда
                if self.current_signal_active and signal:
                    await self.check_peak_trend(signal)
                
                self.last_conditions_met = conditions_met
                
            except Exception as e:
                logger.error(f"Ошибка в периодической проверке: {e}")
            
            # Ждем 20 минут до следующей проверки
            await asyncio.sleep(20 * 60)

    async def send_cancel_signal(self):
        """Отправка сигнала отмены"""
        if not self.app or not self.subscribers:
            return
        
        cancel_message = """🛑 <b>ОТМЕНА СИГНАЛА SBER</b>

❌ Условия стратегии больше не выполняются
⏰ Рекомендуется закрыть позицию"""
        
        for chat_id in self.subscribers.copy():
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id,
                    text=cancel_message,
                    parse_mode='HTML'
                )
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Ошибка отправки отмены в чат {chat_id}: {e}")

    async def check_peak_trend(self, signal: TradingSignal):
        """Проверка пика тренда (ADX > 45)"""
        if signal.adx > 45:
            peak_message = f"""🔥 <b>ПИК ТРЕНДА SBER!</b>

📊 <b>ADX:</b> {signal.adx:.1f} (>45 - очень сильный тренд)
💰 <b>Цена:</b> {signal.price:.2f} ₽

⚠️ <b>ВАЖНО:</b> Рассмотрите фиксацию прибыли!
Сильные тренды часто разворачиваются после пика."""
            
            for chat_id in self.subscribers.copy():
                try:
                    await self.app.bot.send_message(
                        chat_id=chat_id,
                        text=peak_message,
                        parse_mode='HTML'
                    )
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.error(f"Ошибка отправки пикового сигнала в чат {chat_id}: {e}")

    async def _format_no_signal_analysis(self) -> str:
        """Детальный анализ почему нет сигнала"""
        try:
            # Получаем текущие данные
            candles = await self.tinkoff_provider.get_candles(hours=50)
            if not candles:
                return "❌ Не удалось получить данные рынка"
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                return "❌ Данные недоступны"
            
            # Рассчитываем индикаторы
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
            adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            
            current_price = closes[-1]
            current_ema20 = ema20[-1]
            current_adx = adx_data['adx'][-1]
            current_plus_di = adx_data['plus_di'][-1]
            current_minus_di = adx_data['minus_di'][-1]
            
            # Анализируем каждое условие
            conditions = []
            
            price_vs_ema = current_price > current_ema20
            conditions.append(f"• Цена vs EMA20: {'✅' if price_vs_ema else '❌'} {current_price:.2f} vs {current_ema20:.2f}")
            
            strong_trend = current_adx > 25
            conditions.append(f"• Сильный тренд: {'✅' if strong_trend else '❌'} ADX {current_adx:.1f}")
            
            positive_direction = current_plus_di > current_minus_di
            conditions.append(f"• Направление: {'✅' if positive_direction else '❌'} +DI {current_plus_di:.1f} vs -DI {current_minus_di:.1f}")
            
            di_difference = (current_plus_di - current_minus_di) > 1
            difference_value = current_plus_di - current_minus_di
            conditions.append(f"• Разница DI: {'✅' if di_difference else '❌'} {difference_value:.1f}")
            
            message = f"""📊 <b>АНАЛИЗ РЫНКА SBER</b>

💰 <b>Текущая цена:</b> {current_price:.2f} ₽

<b>Проверка условий:</b>
{chr(10).join(conditions)}

<b>Статус:</b> {'🟢 Сигнал покупки' if all([price_vs_ema, strong_trend, positive_direction, di_difference]) else '🔴 Сигнала нет'}"""
            
            return message
            
        except Exception as e:
            logger.error(f"Ошибка в анализе отсутствия сигнала: {e}")
            return "❌ Ошибка анализа рынка"
