import numpy as np
import pandas as pd
from typing import List, Dict

class TechnicalIndicators:
    """Класс для расчета технических индикаторов точно как в TradingView"""
    
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
    def rma_smoothing(values: pd.Series, period: int) -> pd.Series:
        """RMA сглаживание как в TradingView (Relative Moving Average = Wilder's MA)"""
        result = pd.Series(index=values.index, dtype=float)
        
        # Первое значение - простое среднее
        if len(values) >= period:
            result.iloc[period-1] = values.iloc[:period].mean()
            
            # RMA формула: RMA = (previous_RMA * (period-1) + current_value) / period
            for i in range(period, len(values)):
                result.iloc[i] = (result.iloc[i-1] * (period - 1) + values.iloc[i]) / period
        
        return result
    
    @staticmethod
    def calculate_adx_tradingview(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """Расчет ADX точно как в TradingView с RMA сглаживанием и фокусом на текущий тренд"""
        
        # ТЕСТ: Минимальные требования для максимальной чувствительности
        if len(highs) < 15:  # Еще меньше требований
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
        
        # True Range (TR) - стандартная формула
        df['prev_close'] = df['close'].shift(1)
        df['hl'] = df['high'] - df['low']
        df['hc'] = abs(df['high'] - df['prev_close'])
        df['lc'] = abs(df['low'] - df['prev_close'])
        df['tr'] = df[['hl', 'hc', 'lc']].max(axis=1)
        
        # Directional Movement (+DM и -DM)
        df['high_diff'] = df['high'] - df['high'].shift(1)
        df['low_diff'] = df['low'].shift(1) - df['low']
        
        # +DM и -DM по классической формуле
        df['plus_dm'] = np.where(
            (df['high_diff'] > df['low_diff']) & (df['high_diff'] > 0),
            df['high_diff'],
            0
        )
        
        df['minus_dm'] = np.where(
            (df['low_diff'] > df['high_diff']) & (df['low_diff'] > 0),
            df['low_diff'],
            0
        )
        
        # КЛЮЧЕВОЕ ОТЛИЧИЕ: используем RMA как в TradingView, а не Wilder smoothing
        df['atr'] = TechnicalIndicators.rma_smoothing(df['tr'], period)
        df['plus_dm_smooth'] = TechnicalIndicators.rma_smoothing(df['plus_dm'], period)
        df['minus_dm_smooth'] = TechnicalIndicators.rma_smoothing(df['minus_dm'], period)
        
        # Расчет +DI и -DI
        df['plus_di'] = (df['plus_dm_smooth'] / df['atr']) * 100
        df['minus_di'] = (df['minus_dm_smooth'] / df['atr']) * 100
        
        # Расчет DX (Directional Index)
        df['di_sum'] = df['plus_di'] + df['minus_di']
        df['di_diff'] = abs(df['plus_di'] - df['minus_di'])
        df['dx'] = np.where(df['di_sum'] != 0, (df['di_diff'] / df['di_sum']) * 100, 0)
        
        # КЛЮЧЕВОЕ ОТЛИЧИЕ: ADX тоже сглаживаем через RMA как в TradingView
        df['adx'] = TechnicalIndicators.rma_smoothing(df['dx'], period)
        
        return {
            'adx': df['adx'].fillna(np.nan).tolist(),
            'plus_di': df['plus_di'].fillna(np.nan).tolist(),
            'minus_di': df['minus_di'].fillna(np.nan).tolist()
        }
    
    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """Главный метод расчёта ADX - теперь использует TradingView версию"""
        return TechnicalIndicators.calculate_adx_tradingview(highs, lows, closes, period)
