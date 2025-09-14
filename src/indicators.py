import numpy as np
import pandas as pd
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

class TechnicalIndicators:
    """Финальный класс индикаторов с точным ADX для Railway"""
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """Расчет EMA"""
        if len(prices) < period:
            logger.warning(f"⚠️ Недостаточно данных для EMA{period}: {len(prices)} < {period}")
            return [np.nan] * len(prices)
        
        try:
            result = [np.nan] * len(prices)
            multiplier = 2.0 / (period + 1)
            
            # Первое значение = SMA
            sma = np.mean(prices[:period])
            result[period - 1] = sma
            
            # Остальные значения
            for i in range(period, len(prices)):
                ema = (prices[i] * multiplier) + (result[i - 1] * (1 - multiplier))
                result[i] = ema
            
            current_ema = result[-1] if not pd.isna(result[-1]) else None
            logger.info(f"📈 EMA{period}: {current_ema:.2f}" if current_ema else f"📈 EMA{period}: NaN")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Ошибка расчета EMA{period}: {e}")
            return [np.nan] * len(prices)
    
    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """
        Точный расчет ADX по формуле Welles Wilder
        """
        
        if len(highs) < period * 3:
            logger.warning(f"⚠️ Недостаточно данных для ADX: {len(highs)} < {period * 3}")
            return {
                'adx': [np.nan] * len(highs),
                'plus_di': [np.nan] * len(highs),
                'minus_di': [np.nan] * len(highs)
            }
        
        try:
            n = len(highs)
            
            # ШАГ 1: True Range
            tr = [0.0] * n
            
            for i in range(1, n):
                high_low = highs[i] - lows[i]
                high_close = abs(highs[i] - closes[i-1])
                low_close = abs(lows[i] - closes[i-1])
                tr[i] = max(high_low, high_close, low_close)
            
            # ШАГ 2: Directional Movement
            plus_dm = [0.0] * n
            minus_dm = [0.0] * n
            
            for i in range(1, n):
                up_move = highs[i] - highs[i-1]
                down_move = lows[i-1] - lows[i]
                
                if up_move > down_move and up_move > 0:
                    plus_dm[i] = up_move
                else:
                    plus_dm[i] = 0.0
                
                if down_move > up_move and down_move > 0:
                    minus_dm[i] = down_move
                else:
                    minus_dm[i] = 0.0
            
            # ШАГ 3: Сглаживание Wilder
            def wilder_smooth(values, period):
                result = [0.0] * len(values)
                
                # Первое значение = сумма первых period элементов
                first_sum = sum(values[1:period+1])  # Пропускаем первый 0
                result[period] = first_sum
                
                # Формула Wilder: новое = (предыдущее * (n-1) + текущее) / n
                for i in range(period + 1, len(values)):
                    result[i] = (result[i-1] * (period - 1) + values[i]) / period
                
                return result
            
            # Сглаживание TR, +DM, -DM
            atr = wilder_smooth(tr, period)
            plus_dm_smooth = wilder_smooth(plus_dm, period)
            minus_dm_smooth = wilder_smooth(minus_dm, period)
            
            # ШАГ 4: +DI и -DI
            plus_di = [0.0] * n
            minus_di = [0.0] * n
            
            for i in range(period, n):
                if atr[i] > 0:
                    plus_di[i] = 100.0 * plus_dm_smooth[i] / atr[i]
                    minus_di[i] = 100.0 * minus_dm_smooth[i] / atr[i]
            
            # ШАГ 5: DX
            dx = [0.0] * n
            
            for i in range(period, n):
                di_sum = plus_di[i] + minus_di[i]
                if di_sum > 0:
                    dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / di_sum
            
            # ШАГ 6: ADX = сглаженный DX
            adx = wilder_smooth(dx, period)
            
            # Преобразуем в правильный формат (заменяем начальные нули на NaN)
            adx_result = [np.nan] * n
            plus_di_result = [np.nan] * n
            minus_di_result = [np.nan] * n
            
            for i in range(period * 2, n):  # ADX начинается с двойного периода
                adx_result[i] = adx[i] if adx[i] > 0 else np.nan
                plus_di_result[i] = plus_di[i] if plus_di[i] >= 0 else np.nan
                minus_di_result[i] = minus_di[i] if minus_di[i] >= 0 else np.nan
            
            result = {
                'adx': adx_result,
                'plus_di': plus_di_result,
                'minus_di': minus_di_result
            }
            
            # Логирование
            current_adx = result['adx'][-1] if not pd.isna(result['adx'][-1]) else None
            current_plus_di = result['plus_di'][-1] if not pd.isna(result['plus_di'][-1]) else None
            current_minus_di = result['minus_di'][-1] if not pd.isna(result['minus_di'][-1]) else None
            
            if current_adx and current_plus_di is not None and current_minus_di is not None:
                logger.info(f"📊 ADX: {current_adx:.1f} | +DI: {current_plus_di:.1f} | -DI: {current_minus_di:.1f}")
            else:
                logger.warning(f"⚠️ ADX расчет: ADX={current_adx} +DI={current_plus_di} -DI={current_minus_di}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Ошибка расчета ADX: {e}")
            import traceback
            traceback.print_exc()
            return {
                'adx': [np.nan] * len(highs),
                'plus_di': [np.nan] * len(highs),
                'minus_di': [np.nan] * len(highs)
            }
    
    @staticmethod
    def validate_data(highs: List[float], lows: List[float], closes: List[float]) -> bool:
        """Валидация данных"""
        if not (len(highs) == len(lows) == len(closes)):
            logger.error(f"❌ Различная длина массивов: H:{len(highs)} L:{len(lows)} C:{len(closes)}")
            return False
        
        if len(highs) < 50:
            logger.warning(f"⚠️ Мало данных: {len(highs)} < 50")
        
        invalid_count = 0
        for i in range(len(highs)):
            h, l, c = highs[i], lows[i], closes[i]
            if not (l <= c <= h and l <= h and l > 0):
                invalid_count += 1
                if invalid_count <= 3:
                    logger.warning(f"⚠️ [{i}] H:{h:.2f} L:{l:.2f} C:{c:.2f}")
        
        valid_ratio = (len(highs) - invalid_count) / len(highs)
        logger.info(f"📊 Валидность: {len(highs)} свечей, {invalid_count} ошибок ({valid_ratio:.1%})")
        
        return valid_ratio >= 0.9
    
    @staticmethod
    def debug_data(highs: List[float], lows: List[float], closes: List[float], count: int = 5):
        """Отладка данных"""
        logger.info(f"🔍 ПОСЛЕДНИЕ {count} СВЕЧЕЙ:")
        start_idx = max(0, len(closes) - count)
        
        for i in range(start_idx, len(closes)):
            h, l, c = highs[i], lows[i], closes[i]
            range_val = h - l
            logger.info(f"🔍 [{i:2d}] H:{h:7.2f} L:{l:7.2f} C:{c:7.2f} Range:{range_val:5.2f}")
