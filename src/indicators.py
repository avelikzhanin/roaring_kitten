import numpy as np
import pandas as pd
from typing import List, Dict
import logging

# Импортируем TA-Lib только для EMA
try:
    import talib
    logger = logging.getLogger(__name__)
    logger.info("✅ TA-Lib загружен")
except ImportError as e:
    logger = logging.getLogger(__name__)
    logger.error(f"❌ TA-Lib не установлен: {e}")
    raise ImportError("TA-Lib обязателен для работы бота")

class TechnicalIndicators:
    """Минимальный класс индикаторов - только EMA и TradingView совместимый ADX"""
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """Расчет EMA через TA-Lib"""
        if len(prices) < period:
            logger.warning(f"Недостаточно данных для EMA{period}")
            return [np.nan] * len(prices)
        
        try:
            prices_array = np.array(prices, dtype=float)
            ema = talib.EMA(prices_array, timeperiod=period)
            result = ema.tolist()
            
            current_ema = result[-1] if not pd.isna(result[-1]) else np.nan
            logger.info(f"📈 EMA{period}: {current_ema:.2f}")
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка расчета EMA{period}: {e}")
            raise RuntimeError(f"Не удалось рассчитать EMA{period}: {e}")
    
    @staticmethod
    def _wilder_smoothing(values: List[float], period: int) -> List[float]:
        """Wilder's smoothing для ADX - точно как в TradingView Pine Script"""
        result = [np.nan] * len(values)
        
        # Находим первое валидное значение
        first_valid_idx = None
        for i, val in enumerate(values):
            if not pd.isna(val):
                first_valid_idx = i
                break
        
        if first_valid_idx is None or first_valid_idx + period > len(values):
            return result
        
        # Инициализация
        smoothed = values[first_valid_idx] if not pd.isna(values[first_valid_idx]) else 0.0
        result[first_valid_idx] = smoothed
        
        # Wilder's smoothing: prev - (prev/len) + current
        for i in range(first_valid_idx + 1, len(values)):
            if not pd.isna(values[i]):
                smoothed = smoothed - (smoothed / period) + values[i]
                result[i] = smoothed
        
        return result
    
    @staticmethod 
    def _simple_moving_average(values: List[float], period: int) -> List[float]:
        """SMA для ADX - точно как в Pine Script sma()"""
        result = [np.nan] * len(values)
        
        for i in range(period - 1, len(values)):
            window = values[i - period + 1:i + 1]
            valid_values = [v for v in window if not pd.isna(v)]
            
            if len(valid_values) == period:
                result[i] = sum(valid_values) / period
        
        return result
    
    @staticmethod
    def calculate_tradingview_adx(highs: List[float], lows: List[float], 
                                 closes: List[float], period: int = 14) -> Dict:
        """Точная реплика TradingView индикатора "ADX and DI for v4" """
        
        if len(highs) < period * 2:
            logger.warning(f"Недостаточно данных для TradingView ADX")
            return {
                'adx': [np.nan] * len(highs),
                'plus_di': [np.nan] * len(highs),
                'minus_di': [np.nan] * len(highs)
            }
        
        n = len(highs)
        
        # Шаг 1: True Range
        true_ranges = [np.nan]
        for i in range(1, n):
            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i-1])
            tr3 = abs(lows[i] - closes[i-1])
            true_ranges.append(max(tr1, tr2, tr3))
        
        # Шаг 2: Directional Movement
        dm_plus = [np.nan]  
        dm_minus = [np.nan]
        
        for i in range(1, n):
            high_diff = highs[i] - highs[i-1]
            low_diff = lows[i-1] - lows[i]
            
            if high_diff > low_diff:
                plus_dm = max(high_diff, 0)
                minus_dm = 0.0
            elif low_diff > high_diff:
                plus_dm = 0.0
                minus_dm = max(low_diff, 0)
            else:
                plus_dm = 0.0
                minus_dm = 0.0
            
            dm_plus.append(plus_dm)
            dm_minus.append(minus_dm)
        
        # Шаг 3: Wilder's Smoothing для TR и DM
        smoothed_tr = TechnicalIndicators._wilder_smoothing(true_ranges, period)
        smoothed_dm_plus = TechnicalIndicators._wilder_smoothing(dm_plus, period) 
        smoothed_dm_minus = TechnicalIndicators._wilder_smoothing(dm_minus, period)
        
        # Шаг 4: DI
        plus_di = []
        minus_di = []
        
        for i in range(n):
            if pd.isna(smoothed_tr[i]) or smoothed_tr[i] == 0:
                plus_di.append(np.nan)
                minus_di.append(np.nan)
            else:
                plus_di_val = (smoothed_dm_plus[i] / smoothed_tr[i]) * 100
                minus_di_val = (smoothed_dm_minus[i] / smoothed_tr[i]) * 100
                plus_di.append(plus_di_val)
                minus_di.append(minus_di_val)
        
        # Шаг 5: DX
        dx_values = []
        for i in range(n):
            if pd.isna(plus_di[i]) or pd.isna(minus_di[i]):
                dx_values.append(np.nan)
            else:
                di_sum = plus_di[i] + minus_di[i]
                if di_sum == 0:
                    dx_values.append(0.0)
                else:
                    dx_val = abs(plus_di[i] - minus_di[i]) / di_sum * 100
                    dx_values.append(dx_val)
        
        # Шаг 6: ADX через SMA (не Wilder's!)
        adx_values = TechnicalIndicators._simple_moving_average(dx_values, period)
        
        return {
            'adx': adx_values,
            'plus_di': plus_di, 
            'minus_di': minus_di
        }
    
    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """Расчет ADX точно как в TradingView индикаторе "ADX and DI for v4" """
        
        result = TechnicalIndicators.calculate_tradingview_adx(highs, lows, closes, period)
        
        # Логируем результат
        current_adx = result['adx'][-1] if not pd.isna(result['adx'][-1]) else np.nan
        current_plus_di = result['plus_di'][-1] if not pd.isna(result['plus_di'][-1]) else np.nan
        current_minus_di = result['minus_di'][-1] if not pd.isna(result['minus_di'][-1]) else np.nan
        
        logger.info(f"📊 ADX: {current_adx:.1f} | +DI: {current_plus_di:.1f} | -DI: {current_minus_di:.1f}")
        
        return result
