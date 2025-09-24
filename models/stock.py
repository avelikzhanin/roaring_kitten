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
    
    # pandas-ta версия
    adx_standard: float
    di_plus_standard: float
    di_minus_standard: float
    
    # Pine Script версия
    adx_pinescript: float
    di_plus_pinescript: float
    di_minus_pinescript: float


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
            not pd.isna(self.technical.adx_standard) and
            not pd.isna(self.technical.adx_pinescript) and
            not pd.isna(self.technical.di_plus_standard) and
            not pd.isna(self.technical.di_plus_pinescript) and
            not pd.isna(self.technical.di_minus_standard) and
            not pd.isna(self.technical.di_minus_pinescript)
        )
