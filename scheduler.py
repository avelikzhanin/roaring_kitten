import logging
from telegram.ext import ContextTypes
from telegram import Bot

from database import db
from stock_service import StockService
from signals import SignalDetector
from formatters import MessageFormatter
from models import SignalType
from config import SUPPORTED_STOCKS

logger = logging.getLogger(__name__)


class SignalMonitor:
    """Класс для мониторинга сигналов"""
    
    def __init__(self):
        self.stock_service = StockService()
        self.signal_detector = SignalDetector()
        self.formatter = MessageFormatter()
    
    async def check_signals(self, context: ContextTypes.DEFAULT_TYPE):
        """Периодическая проверка сигналов для всех подписок"""
        logger.info("🔍 Starting signal check...")
        
        try:
            # Получаем список всех акций с активными подписками
            subscribed_tickers = await db.get_all_subscribed_tickers()
            
            if not subscribed_tickers:
                logger.info("No active subscriptions. Skipping check.")
                return
            
            logger.info(f"Checking signals for: {', '.join(subscribed_tickers)}")
            
            for ticker in subscribed_tickers:
                await self._check_ticker_signal(ticker, context.bot)
            
            logger.info("✅ Signal check completed")
            
        except Exception as e:
            logger.error(f"Error in check_signals: {e}", exc_info=True)
    
    async def _check_ticker_signal(self, ticker: str, bot: Bot):
        """Проверка сигнала для конкретной акции"""
        try:
            # Получаем данные акции
            stock_data = await self.stock_service.get_stock_data(ticker)
            
            if not stock_data or not stock_data.is_valid():
                logger.warning(f"Invalid data for {ticker}, skipping")
                return
            
            # Определяем текущий сигнал
            current_signal = self.signal_detector.detect_signal(stock_data)
            
            # Получаем предыдущее состояние сигнала
            previous_state = await db.get_signal_state(ticker)
            previous_signal = previous_state['last_signal'] if previous_state else None
            
            # Проверяем изменение сигнала
            if not self.signal_detector.has_signal_changed(previous_signal, current_signal.signal_type):
                logger.info(f"No signal change for {ticker}")
                # Обновляем состояние без отправки уведомлений
                await db.update_signal_state(
                    ticker,
                    current_signal.signal_type.value,
                    current_signal.adx,
                    current_signal.di_plus,
                    current_signal.di_minus,
                    current_signal.price
                )
                return
            
            logger.info(f"🎯 Signal changed for {ticker}: {previous_signal} → {current_signal.signal_type.value}")
            
            # Получаем подписчиков акции
            subscribers = await db.get_ticker_subscribers(ticker)
            
            if not subscribers:
                logger.info(f"No subscribers for {ticker}")
                return
            
            # Обрабатываем переход SELL/NONE → BUY
            if self.signal_detector.is_sell_to_buy_transition(previous_signal, current_signal.signal_type):
                await self._handle_buy_signal(ticker, current_signal, subscribers, bot)
            
            # Обрабатываем переход BUY → SELL
            elif self.signal_detector.is_buy_to_sell_transition(previous_signal, current_signal.signal_type):
                await self._handle_sell_signal(ticker, current_signal, subscribers, bot)
            
            # Обновляем состояние сигнала
            await db.update_signal_state(
                ticker,
                current_signal.signal_type.value,
                current_signal.adx,
                current_signal.di_plus,
                current_signal.di_minus,
                current_signal.price
            )
            
        except Exception as e:
            logger.error(f"Error checking signal for {ticker}: {e}", exc_info=True)
    
    async def _handle_buy_signal(self, ticker: str, signal, subscribers: list, bot: Bot):
        """Обработка BUY сигнала"""
        logger.info(f"🟢 BUY signal for {ticker}")
        
        stock_info = SUPPORTED_STOCKS.get(ticker, {})
        stock_name = stock_info.get('name', ticker)
        stock_emoji = stock_info.get('emoji', '📊')
        
        # Формируем сообщение
        message = self.formatter.format_buy_signal_notification(
            signal, stock_name, stock_emoji
        )
        
        # Отправляем уведомления всем подписчикам
        for user_id in subscribers:
            try:
                # Проверяем, есть ли уже открытая позиция
                has_position = await db.has_open_position(user_id, ticker)
                
                if not has_position:
                    # Открываем позицию
                    await db.open_position(
                        user_id, 
                        ticker, 
                        signal.price,
                        signal.adx,
                        signal.di_plus
                    )
                    
                    # Отправляем уведомление
                    await bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode='HTML'
                    )
                    logger.info(f"Sent BUY notification to user {user_id} for {ticker}")
                else:
                    logger.info(f"User {user_id} already has open position for {ticker}")
                    
            except Exception as e:
                logger.error(f"Error sending BUY notification to user {user_id}: {e}")
    
    async def _handle_sell_signal(self, ticker: str, signal, subscribers: list, bot: Bot):
        """Обработка SELL сигнала"""
        logger.info(f"🔴 SELL signal for {ticker}")
        
        stock_info = SUPPORTED_STOCKS.get(ticker, {})
        stock_name = stock_info.get('name', ticker)
        stock_emoji = stock_info.get('emoji', '📊')
        
        # Отправляем уведомления всем подписчикам
        for user_id in subscribers:
            try:
                # Проверяем, есть ли открытая позиция
                has_position = await db.has_open_position(user_id, ticker)
                
                if has_position:
                    # Получаем данные позиции
                    positions = await db.get_open_positions(user_id)
                    position = next((p for p in positions if p['ticker'] == ticker), None)
                    
                    if position:
                        entry_price = float(position['entry_price'])
                        profit_percent = ((signal.price - entry_price) / entry_price) * 100
                        
                        # Закрываем позицию
                        await db.close_position(user_id, ticker, signal.price)
                        
                        # Формируем и отправляем сообщение
                        message = self.formatter.format_sell_signal_notification(
                            signal, stock_name, stock_emoji, entry_price, profit_percent
                        )
                        
                        await bot.send_message(
                            chat_id=user_id,
                            text=message,
                            parse_mode='HTML'
                        )
                        logger.info(f"Sent SELL notification to user {user_id} for {ticker}, P/L: {profit_percent:.2f}%")
                else:
                    logger.info(f"User {user_id} has no open position for {ticker}")
                    
            except Exception as e:
                logger.error(f"Error sending SELL notification to user {user_id}: {e}")
