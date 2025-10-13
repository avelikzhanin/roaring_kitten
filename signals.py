import logging
from datetime import datetime

from models import Signal, SignalType, StockData
from config import ADX_THRESHOLD, DI_PLUS_THRESHOLD

logger = logging.getLogger(__name__)


class SignalDetector:
    """Класс для определения торговых сигналов"""
    
    @staticmethod
    def detect_signal(stock_data: StockData) -> Signal:
        """
        Определение сигнала на основе данных акции
        
        BUY:  ADX > 25 AND DI+ > 25
        SELL: ADX ≤ 25 OR DI+ ≤ 25
        """
        adx = stock_data.technical.adx
        di_plus = stock_data.technical.di_plus
        di_minus = stock_data.technical.di_minus
        price = stock_data.price.current_price
        
        # Определяем тип сигнала
        if adx > ADX_THRESHOLD and di_plus > DI_PLUS_THRESHOLD:
            signal_type = SignalType.BUY
        elif adx <= ADX_THRESHOLD or di_plus <= DI_PLUS_THRESHOLD:
            signal_type = SignalType.SELL
        else:
            signal_type = SignalType.NONE
        
        signal = Signal(
            ticker=stock_data.info.ticker,
            signal_type=signal_type,
            adx=adx,
            di_plus=di_plus,
            di_minus=di_minus,
            price=price,
            timestamp=datetime.now()
        )
        
        logger.info(
            f"🎯 {stock_data.info.ticker} | Signal: {signal_type.value} | "
            f"ADX: {adx:.2f}, DI+: {di_plus:.2f}, DI-: {di_minus:.2f}, Price: {price:.2f}"
        )
        
        return signal
    
    @staticmethod
    def has_signal_changed(old_signal: str, new_signal: SignalType) -> bool:
        """Проверка изменения сигнала"""
        if old_signal is None:
            return True
        
        return old_signal != new_signal.value
    
    @staticmethod
    def is_buy_to_sell_transition(old_signal: str, new_signal: SignalType) -> bool:
        """Проверка перехода BUY → SELL"""
        return old_signal == SignalType.BUY.value and new_signal == SignalType.SELL
    
    @staticmethod
    def is_sell_to_buy_transition(old_signal: str, new_signal: SignalType) -> bool:
        """Проверка перехода SELL → BUY или NONE → BUY"""
        return (
            (old_signal == SignalType.SELL.value or old_signal == SignalType.NONE.value) 
            and new_signal == SignalType.BUY
        )
