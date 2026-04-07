import logging
from datetime import datetime
from telegram.ext import ContextTypes
from telegram import Bot

from database import db
from stock_service import StockService
from signals import SignalDetector
from formatters import MessageFormatter
from models import SignalType
from config import (
    SUPPORTED_STOCKS, 
    DEPOSIT, 
    RISK_PERCENT, 
    STOP_LOSS_PERCENT,
    AVERAGING_LEVEL_1,
    AVERAGING_LEVEL_2
)
from gpt_analyst import gpt_analyst
from fear_greed_index import fear_greed

logger = logging.getLogger(__name__)


class SignalMonitor:
    """Класс для мониторинга сигналов"""
    
    def __init__(self):
        self.stock_service = StockService()
        self.signal_detector = SignalDetector()
        self.formatter = MessageFormatter()
    
    def _is_market_open(self) -> bool:
        """Проверка работает ли биржа (MOEX: 06:50 - 23:50 МСК)"""
        now = datetime.now()
        hour = now.hour
        minute = now.minute
        
        if hour == 23 and minute >= 50:
            return False
        if 0 <= hour < 6:
            return False
        if hour == 6 and minute < 50:
            return False
        
        return True
    
    def _calculate_lots(self, ticker: str, entry_price: float) -> int:
        """Расчет количества лотов на основе риска"""
        stock_info = SUPPORTED_STOCKS.get(ticker, {})
        lot_size = stock_info.get('lot_size', 1)
        
        risk_amount = DEPOSIT * (RISK_PERCENT / 100)
        loss_per_share = entry_price * (STOP_LOSS_PERCENT / 100)
        shares_count = risk_amount / loss_per_share
        lots = int(shares_count / lot_size)
        
        logger.info(
            f"💰 Расчет позиции {ticker}: "
            f"Цена={entry_price:.2f} ₽, "
            f"Риск={risk_amount:,.0f} ₽, "
            f"Убыток на акцию={loss_per_share:.2f} ₽, "
            f"Акций={shares_count:,.0f}, "
            f"Размер лота={lot_size}, "
            f"Лотов={lots:,}"
        )
        
        return lots
    
    async def check_signals(self, context: ContextTypes.DEFAULT_TYPE):
        """Периодическая проверка сигналов для всех подписок"""
        
        if not self._is_market_open():
            logger.info("⏰ Биржа закрыта (работает 06:50-23:50 МСК), пропускаем проверку сигналов")
            return
        
        logger.info("🔍 Starting signal check...")
        
        try:
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
    
    async def update_fear_greed_index(self, context: ContextTypes.DEFAULT_TYPE):
        """Ежедневный расчёт индекса страха и жадности (запуск в 19:00 МСК)"""
        logger.info("📊 Calculating Fear & Greed Index...")
        
        try:
            result = await fear_greed.calculate()
            if result:
                await db.save_fear_greed(result)
                logger.info(f"✅ Fear & Greed Index saved: {result['value']} ({result['label']})")
            else:
                logger.warning("⚠️ Failed to calculate Fear & Greed Index")
        except Exception as e:
            logger.error(f"❌ Error updating Fear & Greed Index: {e}", exc_info=True)
    
    async def _check_ticker_signal(self, ticker: str, bot: Bot):
        """Проверка сигнала для конкретной акции"""
        try:
            stock_data = await self.stock_service.get_stock_data(ticker)
            
            if not stock_data or not stock_data.is_valid():
                logger.warning(f"Invalid data for {ticker}, skipping")
                return
            
            signals = self.signal_detector.detect_signals(stock_data)
            long_signal = signals['LONG']
            
            await self._check_stop_loss(ticker, long_signal, stock_data, bot)
            await self._check_averaging(ticker, long_signal, stock_data, bot)
            await self._process_long_signals(ticker, long_signal, stock_data, bot)
            
        except Exception as e:
            logger.error(f"Error checking signal for {ticker}: {e}", exc_info=True)
    
    async def _check_stop_loss(self, ticker: str, signal, stock_data, bot: Bot):
        """Проверка Stop Loss для всех открытых позиций"""
        try:
            subscribers = await db.get_ticker_subscribers(ticker)
            
            if not subscribers:
                return
            
            current_price = signal.price
            
            for user_id in subscribers:
                has_long_position = await db.has_open_position(user_id, ticker, 'LONG')
                
                if not has_long_position:
                    continue
                
                positions = await db.get_open_positions(user_id)
                position = next((p for p in positions if p['ticker'] == ticker and p['position_type'] == 'LONG'), None)
                
                if not position:
                    continue
                
                entry_price = float(position['entry_price'])
                lots = position['lots']
                average_price = float(position['average_price'])
                averaging_count = position['averaging_count']
                
                stop_loss_price = entry_price * (1 - STOP_LOSS_PERCENT / 100)
                
                if current_price <= stop_loss_price:
                    profit_percent = ((current_price - average_price) / average_price) * 100
                    
                    logger.info(
                        f"🛑 STOP LOSS triggered for {ticker} | "
                        f"User: {user_id} | "
                        f"Entry: {entry_price:.2f} | "
                        f"Average: {average_price:.2f} | "
                        f"Current: {current_price:.2f} | "
                        f"SL: {stop_loss_price:.2f} | "
                        f"Loss: {profit_percent:.2f}% | "
                        f"Lots: {lots:,} | "
                        f"Averagings: {averaging_count}"
                    )
                    
                    await db.close_position(user_id, ticker, 'LONG', current_price)
                    
                    stock_info = SUPPORTED_STOCKS.get(ticker, {})
                    stock_name = stock_info.get('name', ticker)
                    stock_emoji = stock_info.get('emoji', '📊')
                    
                    message = self.formatter.format_stop_loss_notification(
                        signal, stock_name, stock_emoji, entry_price, average_price, 
                        profit_percent, stop_loss_price, lots, averaging_count
                    )
                    
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=message,
                            parse_mode='HTML'
                        )
                        logger.info(f"Sent STOP LOSS notification to user {user_id} for {ticker}")
                    except Exception as e:
                        logger.error(f"Error sending STOP LOSS notification to user {user_id}: {e}")
        
        except Exception as e:
            logger.error(f"Error checking stop loss for {ticker}: {e}", exc_info=True)
    
    async def _check_averaging(self, ticker: str, signal, stock_data, bot: Bot):
        """Проверка уровней для доливки позиций"""
        try:
            subscribers = await db.get_ticker_subscribers(ticker)
            
            if not subscribers:
                return
            
            current_price = signal.price
            
            for user_id in subscribers:
                has_long_position = await db.has_open_position(user_id, ticker, 'LONG')
                
                if not has_long_position:
                    continue
                
                positions = await db.get_open_positions(user_id)
                position = next((p for p in positions if p['ticker'] == ticker and p['position_type'] == 'LONG'), None)
                
                if not position:
                    continue
                
                entry_price = float(position['entry_price'])
                averaging_count = position['averaging_count']
                
                averaging_price_1 = entry_price * (1 - AVERAGING_LEVEL_1 / 100)
                averaging_price_2 = entry_price * (1 - AVERAGING_LEVEL_2 / 100)
                
                if averaging_count == 0 and current_price <= averaging_price_1:
                    await self._execute_averaging(
                        user_id, ticker, signal, stock_data, bot, 
                        entry_price, current_price, 1
                    )
                
                elif averaging_count == 1 and current_price <= averaging_price_2:
                    await self._execute_averaging(
                        user_id, ticker, signal, stock_data, bot, 
                        entry_price, current_price, 2
                    )
        
        except Exception as e:
            logger.error(f"Error checking averaging for {ticker}: {e}", exc_info=True)
    
    async def _execute_averaging(
        self, 
        user_id: int, 
        ticker: str, 
        signal, 
        stock_data, 
        bot: Bot,
        entry_price: float,
        current_price: float,
        averaging_number: int
    ):
        """Выполнение доливки"""
        try:
            add_lots = self._calculate_lots(ticker, entry_price)
            
            if add_lots <= 0:
                logger.warning(f"Cannot add to position {ticker}: calculated lots = {add_lots}")
                return
            
            await db.add_to_position(user_id, ticker, 'LONG', current_price, add_lots)
            
            positions = await db.get_open_positions(user_id)
            position = next((p for p in positions if p['ticker'] == ticker and p['position_type'] == 'LONG'), None)
            
            if not position:
                return
            
            total_lots = position['lots']
            new_average_price = float(position['average_price'])
            
            logger.info(
                f"📊 AVERAGING #{averaging_number} for {ticker} | "
                f"User: {user_id} | "
                f"Entry: {entry_price:.2f} | "
                f"Add price: {current_price:.2f} | "
                f"Add lots: {add_lots:,} | "
                f"Total lots: {total_lots:,} | "
                f"New average: {new_average_price:.2f}"
            )
            
            stock_info = SUPPORTED_STOCKS.get(ticker, {})
            stock_name = stock_info.get('name', ticker)
            stock_emoji = stock_info.get('emoji', '📊')
            
            gpt_analysis = await self._get_gpt_analysis(ticker, stock_data, f"AVERAGING #{averaging_number}")
            
            message = self.formatter.format_averaging_notification(
                signal, stock_name, stock_emoji, entry_price, current_price,
                add_lots, total_lots, new_average_price, averaging_number, gpt_analysis
            )
            
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode='HTML'
                )
                logger.info(f"Sent AVERAGING notification to user {user_id} for {ticker}")
            except Exception as e:
                logger.error(f"Error sending AVERAGING notification to user {user_id}: {e}")
        
        except Exception as e:
            logger.error(f"Error executing averaging for {ticker}: {e}", exc_info=True)
    
    async def _process_long_signals(self, ticker: str, signal, stock_data, bot: Bot):
        """Обработка LONG сигналов"""
        previous_state = await db.get_signal_state(ticker, 'LONG')
        previous_signal = previous_state['last_signal'] if previous_state else None
        
        if not self.signal_detector.has_signal_changed(previous_signal, signal.signal_type):
            logger.info(f"No LONG signal change for {ticker}")
            await db.update_signal_state(
                ticker, 'LONG', signal.signal_type.value,
                signal.adx, signal.di_plus, signal.di_minus, signal.price
            )
            return
        
        logger.info(f"🎯 LONG signal changed for {ticker}: {previous_signal} → {signal.signal_type.value}")
        
        subscribers = await db.get_ticker_subscribers(ticker)
        
        if not subscribers:
            logger.info(f"No subscribers for {ticker}")
            return
        
        if self.signal_detector.is_sell_to_buy_transition(previous_signal, signal.signal_type):
            await self._handle_long_buy_signal(ticker, signal, stock_data, subscribers, bot)
        
        elif self.signal_detector.is_buy_to_sell_transition(previous_signal, signal.signal_type):
            await self._handle_long_sell_signal(ticker, signal, stock_data, subscribers, bot)
        
        await db.update_signal_state(
            ticker, 'LONG', signal.signal_type.value,
            signal.adx, signal.di_plus, signal.di_minus, signal.price
        )
    
    async def _handle_long_buy_signal(self, ticker: str, signal, stock_data, subscribers: list, bot: Bot):
        """Обработка BUY сигнала (открытие LONG)"""
        logger.info(f"🟢 LONG BUY signal for {ticker}")
        
        stock_info = SUPPORTED_STOCKS.get(ticker, {})
        stock_name = stock_info.get('name', ticker)
        stock_emoji = stock_info.get('emoji', '📊')
        
        lots = self._calculate_lots(ticker, signal.price)
        
        if lots <= 0:
            logger.warning(f"Cannot open position for {ticker}: calculated lots = {lots}")
            return
        
        gpt_analysis = await self._get_gpt_analysis(ticker, stock_data, "LONG BUY")
        
        message = self.formatter.format_long_buy_signal_notification(
            signal, stock_name, stock_emoji, lots, gpt_analysis
        )
        
        for user_id in subscribers:
            try:
                has_any_position = await db.has_open_position(user_id, ticker)
                
                if not has_any_position:
                    await db.open_position(
                        user_id, ticker, 'LONG', signal.price,
                        signal.adx, signal.di_plus, signal.di_minus, lots
                    )
                    
                    await bot.send_message(
                        chat_id=user_id, text=message, parse_mode='HTML'
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
        
        gpt_analysis = await self._get_gpt_analysis(ticker, stock_data, "LONG SELL")
        
        for user_id in subscribers:
            try:
                has_long_position = await db.has_open_position(user_id, ticker, 'LONG')
                
                if has_long_position:
                    positions = await db.get_open_positions(user_id)
                    position = next((p for p in positions if p['ticker'] == ticker and p['position_type'] == 'LONG'), None)
                    
                    if position:
                        entry_price = float(position['entry_price'])
                        average_price = float(position['average_price'])
                        lots = position['lots']
                        averaging_count = position['averaging_count']
                        
                        profit_percent = ((signal.price - average_price) / average_price) * 100
                        
                        await db.close_position(user_id, ticker, 'LONG', signal.price)
                        
                        message = self.formatter.format_long_sell_signal_notification(
                            signal, stock_name, stock_emoji, entry_price, average_price,
                            profit_percent, lots, averaging_count, gpt_analysis
                        )
                        
                        await bot.send_message(
                            chat_id=user_id, text=message, parse_mode='HTML'
                        )
                        logger.info(f"Sent LONG SELL notification to user {user_id} for {ticker}, P/L: {profit_percent:.2f}%")
                else:
                    logger.info(f"User {user_id} has no open LONG position for {ticker}")
                    
            except Exception as e:
                logger.error(f"Error sending LONG SELL notification to user {user_id}: {e}")
    
    async def _get_gpt_analysis(self, ticker: str, stock_data, signal_type: str) -> str:
        """Получение GPT анализа"""
        try:
            logger.info(f"🤖 Получаем GPT анализ для {signal_type} {ticker}...")
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
