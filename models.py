from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from enum import Enum

import pandas as pd


class SignalType(Enum):
    """Типы сигналов"""
    BUY = "BUY"
    SELL = "SELL"
    SHORT = "SHORT"
    COVER = "COVER"
    NONE = "NONE"


class PositionType(Enum):
    """Типы позиций"""
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class StockPrice:
    """Модель для цены акции"""
    current_price: float
    last_close: float
    time: Optional[str] = None


@dataclass
class TechnicalData:
    """Модель для технических индикаторов"""
    ema20: float
    adx: float
    di_plus: float
    di_minus: float


@dataclass
class StockInfo:
    """Информация об акции"""
    ticker: str
    name: str
    emoji: str


@dataclass
class StockData:
    """Полные данные по акции"""
    info: StockInfo
    price: StockPrice
    technical: TechnicalData
    
    def is_valid(self) -> bool:
        """Проверка на валидность данных"""
        return (
            not pd.isna(self.technical.ema20) and
            not pd.isna(self.technical.adx) and
            not pd.isna(self.technical.di_plus) and
            not pd.isna(self.technical.di_minus)
        )


@dataclass
class Signal:
    """Модель сигнала"""
    ticker: str
    signal_type: SignalType
    adx: float
    di_plus: float
    di_minus: float
    price: float
    timestamp: datetime
    
    def is_buy_signal(self) -> bool:
        """Проверка на сигнал покупки (LONG)"""
        return self.signal_type == SignalType.BUY
    
    def is_sell_signal(self) -> bool:
        """Проверка на сигнал продажи (закрытие LONG)"""
        return self.signal_type == SignalType.SELL
    
    def is_short_signal(self) -> bool:
        """Проверка на сигнал SHORT"""
        return self.signal_type == SignalType.SHORT
    
    def is_cover_signal(self) -> bool:
        """Проверка на сигнал закрытия SHORT"""
        return self.signal_type == SignalType.COVER


@dataclass
class Position:
    """Модель позиции"""
    id: int
    user_id: int
    ticker: str
    position_type: PositionType
    entry_price: float
    entry_time: datetime
    entry_adx: float
    entry_di_plus: float
    entry_di_minus: float
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    profit_percent: Optional[float] = None
    is_open: bool = True
    
    def calculate_profit_percent(self, current_price: float) -> float:
        """Расчет текущей прибыли в процентах с учетом типа позиции"""
        if self.is_open:
            if self.position_type == PositionType.LONG:
                # LONG: прибыль при росте цены
                return ((current_price - self.entry_price) / self.entry_price) * 100
            else:
                # SHORT: прибыль при падении цены
                return ((self.entry_price - current_price) / self.entry_price) * 100
        return self.profit_percent or 0.0
