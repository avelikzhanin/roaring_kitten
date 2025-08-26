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
    """Основной класс торгового бота"""
    
    def __init__(self, telegram_token: str, tinkoff_token: str):
        self.telegram_token = telegram_token
        self.tinkoff_provider = TinkoffDataProvider(tinkoff_token)
        self.subscribers: List[int] = []
        self.last_signal_time: Optional[datetime] = None
        self.app: Optional[Application] = None
        self.is_running = False
        self.current_signal_active = False  # Трекинг активного сигнала
        self.last_conditions_met = False    # Последнее состояние условий
        self._signal_task = None  # Для отслеживания задачи проверки сигналов
        
    async def start(self):
        """Запуск бота"""
        try:
            # Создаем приложение Telegram
            self.app = Application.builder().token(self.telegram_token).build()
            
            # Добавляем обработчики команд
            self.app.add_handler(CommandHandler("start", self.start_command))
            self.app.add_handler(CommandHandler("stop", self.stop_command))
            self.app.add_handler(CommandHandler("signal", self.signal_command))
            
            logger.info("🚀 Запуск торгового бота SBER...")
            
            # Запускаем периодическую проверку в отдельной задаче
            self.is_running = True
            self._signal_task = asyncio.create_task(self.check_signals_periodically())
            
            # Инициализируем и запускаем Telegram бота
            await self.app.initialize()
            await self.app.start()
            
            # Запускаем polling
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
    
    async def shutdown(self):
        """Корректная остановка бота"""
        logger.info("Начинаем остановку бота...")
        
        self.is_running = False
        
        # Отменяем задачу проверки сигналов
        if self._signal_task and not self._signal_task.done():
            self._signal_task.cancel()
            try:
                await self._signal_task
            except asyncio.CancelledError:
                pass
        
        # Останавливаем Telegram приложение
        if self.app:
            try:
                if self.app.updater and self.app.updater.running:
                    await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()
            except Exception as e:
                logger.error(f"Ошибка при остановке Telegram приложения: {e}")
        
        logger.info("Бот остановлен")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        chat_id = update.effective_chat.id
        
        if chat_id not in self.subscribers:
            self.subscribers.append(chat_id)
            await update.message.reply_text(
                "🤖 <b>Добро пожаловать в торгового бота SBER!</b>\n\n"
                "📈 Вы подписаны на торговые сигналы\n"
                "🔔 Бот будет уведомлять о сигналах покупки и их отмене\n\n"
                "<b>Параметры стратегии:</b>\n"
                "• EMA20 - цена выше средней\n"
                "• ADX > 25 - сильный тренд\n"
                "• +DI > -DI (разница > 1) - восходящее движение\n\n"
                "<b>Команды:</b>\n"
                "/stop - отписаться от сигналов\n"
                "/signal - проверить текущий сигнал",
                parse_mode='HTML'
            )
            logger.info(f"Новый подписчик: {chat_id}")
        else:
            await update.message.reply_text("✅ Вы уже подписаны на сигналы!")
    
    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stop"""
        chat_id = update.effective_chat.id
        
        if chat_id in self.subscribers:
            self.subscribers.remove(chat_id)
            await update.message.reply_text("❌ Вы отписались от торговых сигналов")
            logger.info(f"Пользователь отписался: {chat_id}")
        else:
            await update.message.reply_text("ℹ️ Вы не были подписаны на сигналы")
    
    async def signal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /signal - проверка текущего сигнала"""
        try:
            await update.message.reply_text("🔍 Анализирую текущую ситуацию на рынке...")
            
            # Выполняем анализ рынка
            signal = await self.analyze_market()
            
            if signal:
                # Есть активный сигнал
                message = f"""✅ <b>АКТИВНЫЙ СИГНАЛ ПОКУПКИ SBER</b>

{self.format_signal_message(signal)}

⏰ <b>Время сигнала:</b> {signal.timestamp.strftime('%H:%M %d.%m.%Y')}
"""
            else:
                # Анализируем почему нет сигнала
                try:
                    # Получаем данные для детального анализа
                    candles = await self.tinkoff_provider.get_candles(hours=120)
                    
                    if len(candles) < 50:
                        message = "❌ <b>Недостаточно данных для анализа</b>\n\nПопробуйте позже."
                    else:
                        df = self.tinkoff_provider.candles_to_dataframe(candles)
                        
                        if df.empty:
                            message = "❌ <b>Ошибка получения данных</b>"
                        else:
                            # Получаем текущие значения индикаторов
                            closes = df['close'].tolist()
                            highs = df['high'].tolist()
                            lows = df['low'].tolist()
                            
                            # Расчет индикаторов
                            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
                            adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
                            
                            # Последние значения
                            current_price = closes[-1]
                            current_ema20 = ema20[-1]
                            current_adx = adx_data['adx'][-1]
                            current_plus_di = adx_data['plus_di'][-1]
                            current_minus_di = adx_data['minus_di'][-1]
                            
                            # Проверяем условия
                            price_above_ema = current_price > current_ema20 if not pd.isna(current_ema20) else False
                            strong_trend = current_adx > 25 if not pd.isna(current_adx) else False
                            positive_direction = current_plus_di > current_minus_di if not pd.isna(current_plus_di) and not pd.isna(current_minus_di) else False
                            di_difference = (current_plus_di - current_minus_di) > 1 if not pd.isna(current_plus_di) and not pd.isna(current_minus_di) else False
                            
                            # Формируем сообщение с текущим состоянием
                            message = f"""📊 <b>ТЕКУЩЕЕ СОСТОЯНИЕ РЫНКА SBER</b>

💰 <b>Цена:</b> {current_price:.2f} ₽
📈 <b>EMA20:</b> {current_ema20:.2f} ₽ {'✅' if price_above_ema else '❌'}

📊 <b>Индикаторы:</b>
• <b>ADX:</b> {current_adx:.1f} {'✅' if strong_trend else '❌'} (нужно >25)
• <b>+DI:</b> {current_plus_di:.1f}
• <b>-DI:</b> {current_minus_di:.1f} {'✅' if positive_direction else '❌'}
• <b>Разница DI:</b> {current_plus_di - current_minus_di:.1f} {'✅' if di_difference else '❌'} (нужно >1)

{'🔔 <b>Все условия выполнены - ожидайте сигнал!</b>' if all([price_above_ema, strong_trend, positive_direction, di_difference]) else '⏳ <b>Ожидаем улучшения показателей...</b>'}"""
                
                except Exception as e:
                    logger.error(f"Ошибка в детальном анализе: {e}")
                    message = "❌ <b>Ошибка получения данных для анализа</b>\n\nПопробуйте позже."
            
            await update.message.reply_text(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Ошибка в команде /signal: {e}")
            await update.message.reply_text(
                "❌ <b>Ошибка при проверке сигнала</b>\n\n"
                "Попробуйте позже или обратитесь к администратору.",
                parse_mode='HTML'
            )
    
    async def analyze_market(self) -> Optional[TradingSignal]:
        """Анализ рынка и генерация сигнала"""
        try:
            # Получаем данные за последние 100 часов для расчета индикаторов
            candles = await self.tinkoff_provider.get_candles(hours=120)
            
            if len(candles) < 50:  # Минимум данных для расчетов
                logger.warning("Недостаточно данных для анализа")
                return None
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            
            if df.empty:
                logger.warning("Пустой DataFrame")
                return None
            
            # Расчет технических индикаторов
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            # EMA20
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
            
            # ADX, +DI, -DI
            adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            
            # Проверка последней свечи
            last_idx = -1
            current_price = closes[last_idx]
            current_ema20 = ema20[last_idx]
            current_adx = adx_data['adx'][last_idx]
            current_plus_di = adx_data['plus_di'][last_idx]
            current_minus_di = adx_data['minus_di'][last_idx]
            
            # Проверка на NaN
            if any(pd.isna(val) for val in [current_ema20, current_adx, current_plus_di, current_minus_di]):
                logger.warning("Не все индикаторы рассчитаны")
                return None
            
            # Расширенное логирование для отладки
            logger.info(
                f"🔍 ОТЛАДКА ИНДИКАТОРОВ:"
            )
            logger.info(
                f"💰 Цена: {current_price:.2f} ₽ | EMA20: {current_ema20:.2f} ₽"
            )
            logger.info(
                f"📊 ADX: {current_adx:.2f} | +DI: {current_plus_di:.2f} | -DI: {current_minus_di:.2f}"
            )
            
            # Показываем последние несколько значений ADX для отладки
            adx_last_5 = adx_data['adx'][-5:]
            logger.info(f"🔢 Последние 5 значений ADX: {[f'{x:.2f}' if not pd.isna(x) else 'NaN' for x in adx_last_5]}")
            
            # Проверка условий сигнала (ОБНОВЛЕННЫЕ)
            conditions = [
                current_price > current_ema20,              # Цена выше EMA20
                current_adx > 25,                           # ADX больше 25 (было 23)
                current_plus_di > current_minus_di,         # +DI больше -DI
                current_plus_di - current_minus_di > 1      # Разница больше 1 (было 5)
                # Убрали условие по объему
            ]
            
            logger.info(f"Условия сигнала: {conditions}")
            
            if all(conditions):
                return TradingSignal(
                    timestamp=df.iloc[last_idx]['timestamp'],
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
    
    async def send_signal_to_subscribers(self, signal: TradingSignal):
        """Отправка сигнала всем подписчикам"""
        if not self.app:
            logger.error("Telegram приложение не инициализировано")
            return
            
        message = self.format_signal_message(signal)
        
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
                await asyncio.sleep(0.1)  # Небольшая задержка между отправками
                
            except (TelegramError, TimedOut, NetworkError) as e:
                logger.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")
                failed_chats.append(chat_id)
                
        # Удаляем недоступные чаты
        for chat_id in failed_chats:
            if chat_id in self.subscribers:
                self.subscribers.remove(chat_id)
                logger.info(f"Удален недоступный чат: {chat_id}")
        
        logger.info(f"Сигнал отправлен: {successful_sends} получателей, {len(failed_chats)} ошибок")
    
    def format_signal_message(self, signal: TradingSignal) -> str:
        """Форматирование сообщения с сигналом"""
        return f"""🔔 <b>СИГНАЛ ПОКУПКИ SBER</b>

💰 <b>Цена:</b> {signal.price:.2f} ₽
📈 <b>EMA20:</b> {signal.ema20:.2f} ₽ (цена выше)

📊 <b>Индикаторы:</b>
• <b>ADX:</b> {signal.adx:.1f} (сильный тренд >25)
• <b>+DI:</b> {signal.plus_di:.1f}
• <b>-DI:</b> {signal.minus_di:.1f}
• <b>Разница DI:</b> {signal.plus_di - signal.minus_di:.1f}"""
    
    async def check_signals_periodically(self):
        """Периодическая проверка сигналов"""
        logger.info("🔄 Запущена периодическая проверка сигналов")
        
        while self.is_running:
            try:
                logger.info("🔍 Выполняется анализ рынка...")
                signal = await self.analyze_market()
                conditions_met = signal is not None
                
                # Улучшенная логика отправки сигналов
                if conditions_met and not self.current_signal_active:
                    # Новый сигнал покупки - отправляем сразу без ограничений по времени
                    await self.send_signal_to_subscribers(signal)
                    self.last_signal_time = signal.timestamp
                    self.current_signal_active = True
                    logger.info(f"✅ Отправлен сигнал ПОКУПКИ по цене {signal.price:.2f}")
                
                elif not conditions_met and self.current_signal_active:
                    # Условия перестали выполняться - отправляем сигнал отмены немедленно
                    await self.send_cancel_signal()
                    self.current_signal_active = False
                    logger.info("❌ Отправлен сигнал ОТМЕНЫ")
                
                elif conditions_met and self.current_signal_active:
                    logger.info("✅ Сигнал покупки остается актуальным")
                
                else:
                    logger.info("📊 Ожидаем сигнал...")
                
                self.last_conditions_met = conditions_met
                
                # Оптимизированная частота проверки - каждые 20 минут для часовых свечей
                await asyncio.sleep(1200)  # 20 минут = 1200 секунд
                
            except asyncio.CancelledError:
                logger.info("Задача проверки сигналов отменена")
                break
            except Exception as e:
                logger.error(f"Ошибка в периодической проверке: {e}")
                await asyncio.sleep(60)  # Ждем минуту при ошибке
    
    async def send_cancel_signal(self):
        """Отправка сигнала отмены всем подписчикам"""
        if not self.app:
            logger.error("Telegram приложение не инициализировано")
            return
        
        # Получаем текущие данные для сигнала отмены
        try:
            candles = await self.tinkoff_provider.get_candles(hours=50)
            if candles:
                df = self.tinkoff_provider.candles_to_dataframe(candles)
                current_price = df.iloc[-1]['close'] if not df.empty else 0
            else:
                current_price = 0
        except:
            current_price = 0
        
        message = f"""❌ <b>СИГНАЛ ОТМЕНЕН SBER</b>

💰 <b>Текущая цена:</b> {current_price:.2f} ₽

⚠️ <b>Причина отмены:</b>
Условия покупки больше не выполняются:
• Цена может быть ниже EMA20
• ADX снизился < 25
• Изменилось соотношение +DI/-DI
• Разница DI стала < 1

🔍 <b>Продолжаем мониторинг...</b>"""
        
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
                logger.error(f"Не удалось отправить сообщение отмены в чат {chat_id}: {e}")
                failed_chats.append(chat_id)
                
        # Удаляем недоступные чаты
        for chat_id in failed_chats:
            if chat_id in self.subscribers:
                self.subscribers.remove(chat_id)
        
        logger.info(f"Сигнал отмены отправлен: {successful_sends} получателей, {len(failed_chats)} ошибок")
