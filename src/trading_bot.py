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
        self._signal_task = None  # Для отслеживания задачи проверки сигналов
        
    async def start(self):
        """Запуск бота"""
        try:
            # Создаем приложение Telegram
            self.app = Application.builder().token(self.telegram_token).build()
            
            # Добавляем обработчики команд (без /status)
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
                    # Получаем данные для детального
