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
            # Это эквивалентно alpha = 1/period в EMA
            for i in range(period, len(values)):
                result.iloc[i] = (result.iloc[i-1] * (period - 1) + values.iloc[i]) / period
        
        return result
    
    @staticmethod
    def calculate_adx_tradingview(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """Расчет ADX точно как в TradingView по их формуле"""
        
        # Минимальные требования для расчета
        if len(highs) < 15:
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
        
        # Формула TradingView: up = change(high), down = -change(low)
        df['up'] = df['high'].diff()
        df['down'] = -df['low'].diff()
        
        # plusDM = na(up) ? na : (up > down and up > 0 ? up : 0)
        df['plus_dm'] = np.where(
            (df['up'] > df['down']) & (df['up'] > 0),
            df['up'],
            0
        )
        
        # minusDM = na(down) ? na : (down > up and down > 0 ? down : 0)  
        df['minus_dm'] = np.where(
            (df['down'] > df['up']) & (df['down'] > 0),
            df['down'],
            0
        )
        
        # True Range (стандартная формула)
        df['prev_close'] = df['close'].shift(1)
        df['hl'] = df['high'] - df['low']
        df['hc'] = abs(df['high'] - df['prev_close'])
        df['lc'] = abs(df['low'] - df['prev_close'])
        df['tr'] = df[['hl', 'hc', 'lc']].max(axis=1)
        
        # TradingView: truerange = rma(tr, len)
        df['atr'] = TechnicalIndicators.rma_smoothing(df['tr'], period)
        df['plus_dm_smooth'] = TechnicalIndicators.rma_smoothing(df['plus_dm'], period)
        df['minus_dm_smooth'] = TechnicalIndicators.rma_smoothing(df['minus_dm'], period)
        
        # TradingView: plus = fixnan(100 * rma(plusDM, len) / truerange)
        # TradingView: minus = fixnan(100 * rma(minusDM, len) / truerange)
        df['plus_di'] = np.where(
            df['atr'] != 0,
            100 * df['plus_dm_smooth'] / df['atr'],
            0
        )
        df['minus_di'] = np.where(
            df['atr'] != 0,
            100 * df['minus_dm_smooth'] / df['atr'],
            0
        )
        
        # TradingView: sum = plus + minus
        # TradingView: adx = 100 * rma(abs(plus - minus) / (sum == 0 ? 1 : sum), adxlen)
        df['di_sum'] = df['plus_di'] + df['minus_di']
        df['di_diff'] = abs(df['plus_di'] - df['minus_di'])
        df['dx'] = np.where(
            df['di_sum'] != 0,
            df['di_diff'] / df['di_sum'],
            0
        )
        
        # ADX = RMA сглаживание DX
        df['adx'] = TechnicalIndicators.rma_smoothing(df['dx'], period) * 100
        
        return {
            'adx': df['adx'].fillna(np.nan).tolist(),
            'plus_di': df['plus_di'].fillna(np.nan).tolist(),
            'minus_di': df['minus_di'].fillna(np.nan).tolist()
        }
    
    @staticmethod
    def wilder_smoothing(values: pd.Series, period: int) -> pd.Series:
        """Сглаживание Уайлдера (оставляем для совместимости)"""
        return TechnicalIndicators.rma_smoothing(values, period)
    
    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """Главный метод расчёта ADX - теперь использует TradingView версию"""
        return TechnicalIndicators.calculate_adx_tradingview(highs, lows, closes, period)
