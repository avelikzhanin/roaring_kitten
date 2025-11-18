import logging
from telegram.ext import ContextTypes
from telegram import Bot

from database import db
from stock_service import StockService
from signals import SignalDetector
from formatters import MessageFormatter
from models import SignalType
from config import SUPPORTED_STOCKS
from gpt_analyst import gpt_analyst

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
            
            # Определяем текущие сигналы (LONG и SHORT отдельно)
            signals = self.signal_detector.detect_signals(stock_data)
            long_signal = signals['LONG']
            short_signal = signals['SHORT']
            
            # Проверяем LONG сигналы
            await self._process_long_signals(ticker, long_signal, stock_data, bot)
            
            # Проверяем SHORT сигналы
            await self._process_short_signals(ticker, short_signal, stock_data, bot)
            
        except Exception as e:
            logger.error(f"Error checking signal for {ticker}: {e}", exc_info=True)
    
    async def _process_long_signals(self, ticker: str, signal, stock_data, bot: Bot):
        """Обработка LONG сигналов"""
        # Получаем предыдущее состояние LONG сигнала
        previous_state = await db.get_signal_state(ticker, 'LONG')
        previous_signal = previous_state['last_signal'] if previous_state else None
        
        # Проверяем изменение сигнала
        if not self.signal_detector.has_signal_changed(previous_signal, signal.signal_type):
            logger.info(f"No LONG signal change for {ticker}")
            # Обновляем состояние без отправки уведомлений
            await db.update_signal_state(
                ticker,
                'LONG',
                signal.signal_type.value,
                signal.adx,
                signal.di_plus,
                signal.di_minus,
                signal.price
            )
            return
        
        logger.info(f"🎯 LONG signal changed for {ticker}: {previous_signal} → {signal.signal_type.value}")
        
        # Получаем подписчиков акции
        subscribers = await db.get_ticker_subscribers(ticker)
        
        if not subscribers:
            logger.info(f"No subscribers for {ticker}")
            return
        
        # Обрабатываем переход SELL/NONE → BUY
        if self.signal_detector.is_sell_to_buy_transition(previous_signal, signal.signal_type):
            await self._handle_long_buy_signal(ticker, signal, stock_data, subscribers, bot)
        
        # Обрабатываем переход BUY → SELL
        elif self.signal_detector.is_buy_to_sell_transition(previous_signal, signal.signal_type):
            await self._handle_long_sell_signal(ticker, signal, stock_data, subscribers, bot)
        
        # Обновляем состояние сигнала
        await db.update_signal_state(
            ticker,
            'LONG',
            signal.signal_type.value,
            signal.adx,
            signal.di_plus,
            signal.di_minus,
            signal.price
        )
    
    async def _process_short_signals(self, ticker: str, signal, stock_data, bot: Bot):
        """Обработка SHORT сигналов"""
        # Получаем предыдущее состояние SHORT сигнала
        previous_state = await db.get_signal_state(ticker, 'SHORT')
        previous_signal = previous_state['last_signal'] if previous_state else None
        
        # Проверяем изменение сигнала
        if not self.signal_detector.has_signal_changed(previous_signal, signal.signal_type):
            logger.info(f"No SHORT signal change for {ticker}")
            # Обновляем состояние без отправки уведомлений
            await db.update_signal_state(
                ticker,
                'SHORT',
                signal.signal_type.value,
                signal.adx,
                signal.di_plus,
                signal.di_minus,
                signal.price
            )
            return
        
        logger.info(f"🎯 SHORT signal changed for {ticker}: {previous_signal} → {signal.signal_type.value}")
        
        # Получаем подписчиков акции
        subscribers = await db.get_ticker_subscribers(ticker)
        
        if not subscribers:
            logger.info(f"No subscribers for {ticker}")
            return
        
        # Обрабатываем переход COVER/NONE → SHORT
        if self.signal_detector.is_cover_to_short_transition(previous_signal, signal.signal_type):
            await self._handle_short_open_signal(ticker, signal, stock_data, subscribers, bot)
        
        # Обрабатываем переход SHORT → COVER
        elif self.signal_detector.is_short_to_cover_transition(previous_signal, signal.signal_type):
            await self._handle_short_close_signal(ticker, signal, stock_data, subscribers, bot)
        
        # Обновляем состояние сигнала
        await db.update_signal_state(
            ticker,
            'SHORT',
            signal.signal_type.value,
            signal.adx,
            signal.di_plus,
            signal.di_minus,
            signal.price
        )
    
    async def _handle_long_buy_signal(self, ticker: str, signal, stock_data, subscribers: list, bot: Bot):
        """Обработка BUY сигнала (открытие LONG)"""
        logger.info(f"🟢 LONG BUY signal for {ticker}")
        
        stock_info = SUPPORTED_STOCKS.get(ticker, {})
        stock_name = stock_info.get('name', ticker)
        stock_emoji = stock_info.get('emoji', '📊')
        
        # Получаем GPT анализ
        gpt_analysis = await self._get_gpt_analysis(ticker, stock_data, "LONG BUY")
        
        # Формируем сообщение с GPT анализом
        message = self.formatter.format_long_buy_signal_notification(
            signal, stock_name, stock_emoji, gpt_analysis
        )
        
        # Отправляем уведомления всем подписчикам
        for user_id in subscribers:
            try:
                # Проверяем, есть ли уже открытая позиция на этой акции
                has_any_position = await db.has_open_position(user_id, ticker)
                
                if not has_any_position:
                    # Открываем LONG позицию
                    await db.open_position(
                        user_id, 
                        ticker,
                        'LONG',
                        signal.price,
                        signal.adx,
                        signal.di_plus,
                        signal.di_minus
                    )
                    
                    # Отправляем уведомление
                    await bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode='HTML'
                    )
                    logger.info(f"Sent LONG BUY notification to user {user_id} for {ticker}")
                else:
                    logger.info(f"User {user_id} already has open position for {ticker}")
                    
            except Exception as e:
                logger.error(f"Error sending LONG BUY notification to user {user_id}: {e}")
    
    async def _handle_long_sell_signal(self, ticker: str, signal, stock_data, subscribers: list, bot: Bot):
        """Обработка SELL сигнала (закрытие LONG)"""
        logger.info(f"🔴 LONG SELL signal for {ticker}")
        
        stock_info = SUPPORTED_STOCKS.get(ticker, {})
        stock_name = stock_info.get('name', ticker)
        stock_emoji = stock_info.get('emoji', '📊')
        
        # Получаем GPT анализ
        gpt_analysis = await self._get_gpt_analysis(ticker, stock_data, "LONG SELL")
        
        # Отправляем уведомления всем подписчикам
        for user_id in subscribers:
            try:
                # Проверяем, есть ли открытая LONG позиция
                has_long_position = await db.has_open_position(user_id, ticker, 'LONG')
                
                if has_long_position:
                    # Получаем данные позиции
                    positions = await db.get_open_positions(user_id)
                    position = next((p for p in positions if p['ticker'] == ticker and p['position_type'] == 'LONG'), None)
                    
                    if position:
                        entry_price = float(position['entry_price'])
                        profit_percent = ((signal.price - entry_price) / entry_price) * 100
                        
                        # Закрываем позицию
                        await db.close_position(user_id, ticker, 'LONG', signal.price)
                        
                        # Формируем и отправляем сообщение
                        message = self.formatter.format_long_sell_signal_notification(
                            signal, stock_name, stock_emoji, entry_price, profit_percent, gpt_analysis
                        )
                        
                        await bot.send_message(
                            chat_id=user_id,
                            text=message,
                            parse_mode='HTML'
                        )
                        logger.info(f"Sent LONG SELL notification to user {user_id} for {ticker}, P/L: {profit_percent:.2f}%")
                else:
                    logger.info(f"User {user_id} has no open LONG position for {ticker}")
                    
            except Exception as e:
                logger.error(f"Error sending LONG SELL notification to user {user_id}: {e}")
    
    async def _handle_short_open_signal(self, ticker: str, signal, stock_data, subscribers: list, bot: Bot):
        """Обработка SHORT сигнала (открытие SHORT)"""
        logger.info(f"🔻 SHORT OPEN signal for {ticker}")
        
        stock_info = SUPPORTED_STOCKS.get(ticker, {})
        stock_name = stock_info.get('name', ticker)
        stock_emoji = stock_info.get('emoji', '📊')
        
        # Получаем GPT анализ
        gpt_analysis = await self._get_gpt_analysis(ticker, stock_data, "SHORT OPEN")
        
        # Формируем сообщение с GPT анализом
        message = self.formatter.format_short_open_signal_notification(
            signal, stock_name, stock_emoji, gpt_analysis
        )
        
        # Отправляем уведомления всем подписчикам
        for user_id in subscribers:
            try:
                # Проверяем, есть ли уже открытая позиция на этой акции
                has_any_position = await db.has_open_position(user_id, ticker)
                
                if not has_any_position:
                    # Открываем SHORT позицию
                    await db.open_position(
                        user_id, 
                        ticker,
                        'SHORT',
                        signal.price,
                        signal.adx,
                        signal.di_plus,
                        signal.di_minus
                    )
                    
                    # Отправляем уведомление
                    await bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode='HTML'
                    )
                    logger.info(f"Sent SHORT OPEN notification to user {user_id} for {ticker}")
                else:
                    logger.info(f"User {user_id} already has open position for {ticker}")
                    
            except Exception as e:
                logger.error(f"Error sending SHORT OPEN notification to user {user_id}: {e}")
    
    async def _handle_short_close_signal(self, ticker: str, signal, stock_data, subscribers: list, bot: Bot):
        """Обработка COVER сигнала (закрытие SHORT)"""
        logger.info(f"🟢 SHORT CLOSE signal for {ticker}")
        
        stock_info = SUPPORTED_STOCKS.get(ticker, {})
        stock_name = stock_info.get('name', ticker)
        stock_emoji = stock_info.get('emoji', '📊')
        
        # Получаем GPT анализ
        gpt_analysis = await self._get_gpt_analysis(ticker, stock_data, "SHORT CLOSE")
        
        # Отправляем уведомления всем подписчикам
        for user_id in subscribers:
            try:
                # Проверяем, есть ли открытая SHORT позиция
                has_short_position = await db.has_open_position(user_id, ticker, 'SHORT')
                
                if has_short_position:
                    # Получаем данные позиции
                    positions = await db.get_open_positions(user_id)
                    position = next((p for p in positions if p['ticker'] == ticker and p['position_type'] == 'SHORT'), None)
                    
                    if position:
                        entry_price = float(position['entry_price'])
                        # SHORT: прибыль при падении цены
                        profit_percent = ((entry_price - signal.price) / entry_price) * 100
                        
                        # Закрываем позицию
                        await db.close_position(user_id, ticker, 'SHORT', signal.price)
                        
                        # Формируем и отправляем сообщение
                        message = self.formatter.format_short_close_signal_notification(
                            signal, stock_name, stock_emoji, entry_price, profit_percent, gpt_analysis
                        )
                        
                        await bot.send_message(
                            chat_id=user_id,
                            text=message,
                            parse_mode='HTML'
                        )
                        logger.info(f"Sent SHORT CLOSE notification to user {user_id} for {ticker}, P/L: {profit_percent:.2f}%")
                else:
                    logger.info(f"User {user_id} has no open SHORT position for {ticker}")
                    
            except Exception as e:
                logger.error(f"Error sending SHORT CLOSE notification to user {user_id}: {e}")
    
    async def _get_gpt_analysis(self, ticker: str, stock_data, signal_type: str) -> str:
        """Получение GPT анализа"""
        try:
            logger.info(f"🤖 Получаем GPT анализ для {signal_type} {ticker}...")
            # Получаем свечи
            candles_data = await self.stock_service.moex_client.get_historical_candles(ticker)
            if candles_data:
                gpt_analysis = await gpt_analyst.analyze_stock(stock_data, candles_data)
                if gpt_analysis:
                    logger.info(f"✅ GPT анализ получен для {signal_type} {ticker}")
                    return gpt_analysis
                else:
                    logger.warning(f"⚠️ GPT вернул пустой анализ для {ticker}")
            else:
                logger.warning(f"⚠️ Не удалось получить свечи для GPT анализа {ticker}")
        except Exception as e:
            logger.error(f"❌ Ошибка получения GPT анализа для {ticker}: {e}")
        
        return None
