from dataclasses import dataclass
from typing import Optional
import pandas as pd


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
