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
    volume: int
    avg_volume: float
    volume_ratio: float

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
        
    async def start(self):
        """Запуск бота"""
        # Создаем приложение Telegram
        self.app = Application.builder().token(self.telegram_token).build()
        
        # Добавляем обработчики команд
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("stop", self.stop_command))
        self.app.add_handler(CommandHandler("signal", self.signal_command))
        
        logger.info("🚀 Запуск торгового бота SBER...")
        
        # Запускаем периодическую проверку в отдельной задаче
        self.is_running = True
        asyncio.create_task(self.check_signals_periodically())
        
        # Запускаем Telegram бота
        await self.app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        chat_id = update.effective_chat.id
        
        if chat_id not in self.subscribers:
            self.subscribers.append(chat_id)
            await update.message.reply_text(
                "🤖 <b>Добро пожаловать в торгового бота SBER!</b>\n\n"
                "📈 Вы подписаны на торговые сигналы\n"
                "🔔 Бот будет уведомлять о сигналах покупки\n\n"
                "<b>Параметры стратегии:</b>\n"
                "• EMA20 - цена выше средней\n"
                "• ADX > 23 - сильный тренд\n"
                "• +DI > -DI - восходящее движение\n"
                "• Объем > среднего × 1.47\n\n"
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
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /status"""
        try:
            # Получаем последние данные для статуса
            candles = await self.tinkoff_provider.get_candles(hours=50)
            
            if candles:
                df = self.tinkoff_provider.candles_to_dataframe(candles)
                last_price = df.iloc[-1]['close'] if not df.empty else 0
                last_time = df.iloc[-1]['timestamp'] if not df.empty else None
                
                status_msg = (
                    f"🤖 <b>Статус бота SBER</b>\n\n"
                    f"📊 <b>Текущая цена:</b> {last_price:.2f} ₽\n"
                    f"⏰ <b>Последнее обновление:</b> {last_time.strftime('%H:%M %d.%m') if last_time else 'н/д'}\n"
                    f"👥 <b>Подписчиков:</b> {len(self.subscribers)}\n"
                    f"🔄 <b>Бот работает:</b> {'✅ Да' if self.is_running else '❌ Нет'}\n"
                    f"📈 <b>Последний сигнал:</b> {self.last_signal_time.strftime('%H:%M %d.%m') if self.last_signal_time else 'Еще не было'}"
                )
            else:
                status_msg = "❌ Не удалось получить данные для статуса"
                
        except Exception as e:
            logger.error(f"Ошибка получения статуса: {e}")
            status_msg = "❌ Ошибка получения статуса"
        
        await update.message.reply_text(status_msg, parse_mode='HTML')
    
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
            volumes = df['volume'].tolist()
            
            # EMA20
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
            
            # ADX, +DI, -DI
            adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            
            # Средний объем за 20 часов
            df['avg_volume_20'] = df['volume'].rolling(window=20, min_periods=1).mean()
            
            # Проверка последней свечи
            last_idx = -1
            current_price = closes[last_idx]
            current_ema20 = ema20[last_idx]
            current_adx = adx_data['adx'][last_idx]
            current_plus_di = adx_data['plus_di'][last_idx]
            current_minus_di = adx_data['minus_di'][last_idx]
            current_volume = volumes[last_idx]
            current_avg_volume = df.iloc[last_idx]['avg_volume_20']
            
            # Проверка на NaN
            if any(pd.isna(val) for val in [current_ema20, current_adx, current_plus_di, current_minus_di]):
                logger.warning("Не все индикаторы рассчитаны")
                return None
            
            # Логирование текущих значений для отладки
            logger.info(
                f"Анализ: цена={current_price:.2f}, EMA20={current_ema20:.2f}, "
                f"ADX={current_adx:.1f}, +DI={current_plus_di:.1f}, -DI={current_minus_di:.1f}, "
                f"объем={current_volume}, ср.объем={current_avg_volume:.0f}"
            )
            
            # Проверка условий сигнала
            conditions = [
                current_price > current_ema20,              # Цена выше EMA20
                current_adx > 23,                          # ADX больше 23
                current_plus_di > current_minus_di,        # +DI больше -DI
                current_plus_di - current_minus_di > 5,    # Существенная разница
                current_volume > current_avg_volume * 1.47 # Объем на 47% выше среднего
            ]
            
            logger.info(f"Условия сигнала: {conditions}")
            
            if all(conditions):
                return TradingSignal(
                    timestamp=df.iloc[last_idx]['timestamp'],
                    price=current_price,
                    ema20=current_ema20,
                    adx=current_adx,
                    plus_di=current_plus_di,
                    minus_di=current_minus_di,
                    volume=current_volume,
                    avg_volume=current_avg_volume,
                    volume_ratio=current_volume / current_avg_volume
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
- <b>ADX:</b> {signal.adx:.1f} (сильный тренд)
- <b>+DI:</b> {signal.plus_di:.1f}
- <b>-DI:</b> {signal.minus_di:.1f}

📈 <b>Объем (час):</b>
- <b>Текущий:</b> {signal.volume:,} (↑{signal.volume_ratio:.0%} от среднего)
- <b>Средний (20ч):</b> {signal.avg_volume:,.0f}"""
    
    async def check_signals_periodically(self):
        """Периодическая проверка сигналов"""
        logger.info("🔄 Запущена периодическая проверка сигналов")
        
        while self.is_running:
            try:
                logger.info("🔍 Выполняется анализ рынка...")
                signal = await self.analyze_market()
                conditions_met = signal is not None
                
                # Логика отправки сигналов с отменой
                if conditions_met and not self.current_signal_active:
                    # Новый сигнал покупки
                    if self.should_send_signal(signal):
                        await self.send_signal_to_subscribers(signal)
                        self.last_signal_time = signal.timestamp
                        self.current_signal_active = True
                        logger.info(f"✅ Отправлен сигнал ПОКУПКИ по цене {signal.price:.2f}")
                
                elif not conditions_met and self.current_signal_active:
                    # Условия перестали выполняться - отправляем сигнал отмены
                    await self.send_cancel_signal()
                    self.current_signal_active = False
                    logger.info("❌ Отправлен сигнал ОТМЕНЫ")
                
                elif conditions_met and self.current_signal_active:
                    logger.info("✅ Сигнал покупки остается актуальным")
                
                else:
                    logger.info("📊 Ожидаем сигнал...")
                
                self.last_conditions_met = conditions_met
                
                # Ждем 5 минут для тестирования (в продакшене можно изменить на 3600 для 1 часа)
                await asyncio.sleep(300)  # 5 минут = 300 секунд
                
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
- Цена может быть ниже EMA20
- ADX снизился < 23
- Изменилось соотношение +DI/-DI
- Объемы торгов упали

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

    def should_send_signal(self, signal: TradingSignal) -> bool:
        """Проверка, нужно ли отправлять сигнал покупки"""
        if self.last_signal_time is None:
            return True
        
        # Не отправляем повторные сигналы покупки в течение 4 часов
        # (достаточно времени, чтобы не спамить)
        time_diff = signal.timestamp - self.last_signal_time
        return time_diff > timedelta(hours=4)
