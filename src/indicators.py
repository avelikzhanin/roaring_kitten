import numpy as np
import pandas as pd
from typing import List, Dict

class TechnicalIndicators:
    """Класс для расчета технических индикаторов"""
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """Расчет экспоненциальной скользящей средней"""
        if len(prices) < period:
            return [np.nan] * len(prices)
        
        # Используем pandas для более стабильного расчета
        series = pd.Series(prices)
        ema = series.ewm(span=period, adjust=False).mean()
        return ema.tolist()
    
    @staticmethod
    def wilder_smoothing(values: pd.Series, period: int) -> pd.Series:
        """Сглаживание Уайлдера (используется в ADX)"""
        result = pd.Series(index=values.index, dtype=float)
        
        # Первое значение - простое среднее за период
        first_avg = values.iloc[:period].mean()
        result.iloc[period-1] = first_avg
        
        # Остальные значения по формуле Уайлдера: 
        # новое_значение = (предыдущее * (период-1) + текущее) / период
        for i in range(period, len(values)):
            result.iloc[i] = (result.iloc[i-1] * (period - 1) + values.iloc[i]) / period
        
        return result
    
  @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """
        Расчет ADX, +DI, -DI точно как в TradingView
        Использует RMA (Relative Moving Average) с alpha=1/period
        """
        if len(highs) < period * 2:
            logger.warning(f"Недостаточно данных для ADX: {len(highs)} < {period * 2}")
            return {
                'adx': [np.nan] * len(highs), 
                'plus_di': [np.nan] * len(highs), 
                'minus_di': [np.nan] * len(highs)
            }
        
        df = pd.DataFrame({
            'high': highs,
            'low': lows,
            'close': closes
        })
        
        # True Range (TR)
        df['prev_close'] = df['close'].shift(1)
        df['hl'] = df['high'] - df['low']
        df['hc'] = abs(df['high'] - df['prev_close'])
        df['lc'] = abs(df['low'] - df['prev_close'])
        df['tr'] = df[['hl', 'hc', 'lc']].max(axis=1)
        
        # Directional Movement (+DM и -DM)
        df['high_diff'] = df['high'] - df['high'].shift(1)
        df['low_diff'] = df['low'].shift(1) - df['low']
        
        # +DM: если high_diff > low_diff и high_diff > 0, то +DM = high_diff, иначе 0
        df['plus_dm'] = np.where(
            (df['high_diff'] > df['low_diff']) & (df['high_diff'] > 0),
            df['high_diff'],
            0
        )
        
        # -DM: если low_diff > high_diff и low_diff > 0, то -DM = low_diff, иначе 0
        df['minus_dm'] = np.where(
            (df['low_diff'] > df['high_diff']) & (df['low_diff'] > 0),
            df['low_diff'],
            0
        )
        
        # Сглаживание по методу Уайлдера
        df['atr'] = TechnicalIndicators.wilder_smoothing(df['tr'], period)
        df['plus_dm_smooth'] = TechnicalIndicators.wilder_smoothing(df['plus_dm'], period)
        df['minus_dm_smooth'] = TechnicalIndicators.wilder_smoothing(df['minus_dm'], period)
        
        # Расчет +DI и -DI
        df['plus_di'] = (df['plus_dm_smooth'] / df['atr']) * 100
        df['minus_di'] = (df['minus_dm_smooth'] / df['atr']) * 100
        
        # Расчет DX (Directional Index)
        df['di_sum'] = df['plus_di'] + df['minus_di']
        df['di_diff'] = abs(df['plus_di'] - df['minus_di'])
        df['dx'] = np.where(df['di_sum'] != 0, (df['di_diff'] / df['di_sum']) * 100, 0)
        
        # ADX = сглаженное значение DX
        df['adx'] = TechnicalIndicators.wilder_smoothing(df['dx'], period)
        
        return {
            'adx': df['adx'].fillna(np.nan).tolist(),
            'plus_di': df['plus_di'].fillna(np.nan).tolist(),
            'minus_di': df['minus_di'].fillna(np.nan).tolist()
        }
