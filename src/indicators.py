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
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """Расчет ADX, +DI, -DI с улучшенной стабильностью"""
        if len(highs) < period * 2:
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
        
        # True Range
        df['hl'] = df['high'] - df['low']
        df['hc'] = abs(df['high'] - df['close'].shift(1))
        df['lc'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['hl', 'hc', 'lc']].max(axis=1)
        
        # Directional Movement
        df['plus_dm'] = np.where(
            (df['high'] - df['high'].shift(1)) > (df['low'].shift(1) - df['low']),
            np.maximum(df['high'] - df['high'].shift(1), 0),
            0
        )
        
        df['minus_dm'] = np.where(
            (df['low'].shift(1) - df['low']) > (df['high'] - df['high'].shift(1)),
            np.maximum(df['low'].shift(1) - df['low'], 0),
            0
        )
        
        # Smoothed values
        df['atr'] = df['tr'].rolling(window=period).mean()
        df['plus_dm_smooth'] = df['plus_dm'].rolling(window=period).mean()
        df['minus_dm_smooth'] = df['minus_dm'].rolling(window=period).mean()
        
        # DI calculations
        df['plus_di'] = (df['plus_dm_smooth'] / df['atr']) * 100
        df['minus_di'] = (df['minus_dm_smooth'] / df['atr']) * 100
        
        # DX calculation
        df['dx'] = abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di']) * 100
        
        # ADX calculation
        df['adx'] = df['dx'].rolling(window=period).mean()
        
        return {
            'adx': df['adx'].fillna(np.nan).tolist(),
            'plus_di': df['plus_di'].fillna(np.nan).tolist(),
            'minus_di': df['minus_di'].fillna(np.nan).tolist()
        }
