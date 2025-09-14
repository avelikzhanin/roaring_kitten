import numpy as np
import pandas as pd
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

class TechnicalIndicators:
    """Класс индикаторов для Railway - только ручной расчет, без TA-Lib"""
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """Ручной расчет EMA (для Railway без TA-Lib)"""
        if len(prices) < period:
            logger.warning(f"⚠️ Недостаточно данных для EMA{period}: {len(prices)} < {period}")
            return [np.nan] * len(prices)
        
        try:
            result = [np.nan] * len(prices)
            
            # Коэффициент сглаживания
            multiplier = 2.0 / (period + 1)
            
            # Первое значение EMA = SMA
            sma = np.mean(prices[:period])
            result[period - 1] = sma
            
            # Рассчитываем остальные значения
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
        """Упрощенный расчет ADX для Railway"""
        
        if len(highs) < period * 2:
            logger.warning(f"⚠️ Недостаточно данных для ADX: {len(highs)} < {period * 2}")
            return {
                'adx': [np.nan] * len(highs),
                'plus_di': [np.nan] * len(highs),
                'minus_di': [np.nan] * len(highs)
            }
        
        try:
            n = len(highs)
            
            # 1. Расчет True Range
            tr_values = [0.0] * n
            for i in range(1, n):
                tr1 = highs[i] - lows[i]
                tr2 = abs(highs[i] - closes[i-1])
                tr3 = abs(lows[i] - closes[i-1])
                tr_values[i] = max(tr1, tr2, tr3)
            
            # 2. Расчет Directional Movement
            plus_dm = [0.0] * n
            minus_dm = [0.0] * n
            
            for i in range(1, n):
                high_diff = highs[i] - highs[i-1]
                low_diff = lows[i-1] - lows[i]
                
                if high_diff > low_diff and high_diff > 0:
                    plus_dm[i] = high_diff
                else:
                    plus_dm[i] = 0.0
                
                if low_diff > high_diff and low_diff > 0:
                    minus_dm[i] = low_diff
                else:
                    minus_dm[i] = 0.0
            
            # 3. Сглаживание (упрощенная версия Wilder)
            smoothed_tr = TechnicalIndicators._simple_smooth(tr_values, period)
            smoothed_plus_dm = TechnicalIndicators._simple_smooth(plus_dm, period)
            smoothed_minus_dm = TechnicalIndicators._simple_smooth(minus_dm, period)
            
            # 4. Расчет DI
            plus_di = [np.nan] * n
            minus_di = [np.nan] * n
            
            for i in range(period, n):
                if smoothed_tr[i] > 0:
                    plus_di[i] = 100.0 * smoothed_plus_dm[i] / smoothed_tr[i]
                    minus_di[i] = 100.0 * smoothed_minus_dm[i] / smoothed_tr[i]
                else:
                    plus_di[i] = 0.0
                    minus_di[i] = 0.0
            
            # 5. Расчет DX
            dx_values = [np.nan] * n
            
            for i in range(period, n):
                if not pd.isna(plus_di[i]) and not pd.isna(minus_di[i]):
                    di_sum = plus_di[i] + minus_di[i]
                    if di_sum > 0:
                        dx_values[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / di_sum
                    else:
                        dx_values[i] = 0.0
            
            # 6. ADX = простая скользящая средняя от DX
            adx_values = TechnicalIndicators._simple_smooth(dx_values, period)
            
            result = {
                'adx': adx_values,
                'plus_di': plus_di,
                'minus_di': minus_di
            }
            
            # Логируем результат
            current_adx = result['adx'][-1] if not pd.isna(result['adx'][-1]) else None
            current_plus_di = result['plus_di'][-1] if not pd.isna(result['plus_di'][-1]) else None
            current_minus_di = result['minus_di'][-1] if not pd.isna(result['minus_di'][-1]) else None
            
            if current_adx and current_plus_di and current_minus_di:
                logger.info(f"📊 ADX: {current_adx:.1f} | +DI: {current_plus_di:.1f} | -DI: {current_minus_di:.1f}")
            else:
                logger.warning("📊 ADX индикаторы содержат NaN")
            
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
    def _simple_smooth(values: List[float], period: int) -> List[float]:
        """Упрощенное сглаживание для Railway"""
        result = [np.nan] * len(values)
        
        # Находим первую позицию для начала расчета
        start_idx = period - 1
        
        # Первое значение = простая средняя
        if start_idx < len(values):
            window_values = []
            for i in range(max(0, start_idx - period + 1), start_idx + 1):
                if not pd.isna(values[i]) and values[i] != 0:
                    window_values.append(values[i])
            
            if len(window_values) > 0:
                result[start_idx] = sum(window_values) / len(window_values)
        
        # Остальные значения - экспоненциальное сглаживание
        alpha = 2.0 / (period + 1)  # Коэффициент сглаживания
        
        for i in range(start_idx + 1, len(values)):
            if not pd.isna(result[i-1]) and not pd.isna(values[i]):
                result[i] = alpha * values[i] + (1 - alpha) * result[i-1]
        
        return result
    
    @staticmethod
    def validate_data(highs: List[float], lows: List[float], closes: List[float]) -> bool:
        """Валидация данных перед расчетом"""
        if not (len(highs) == len(lows) == len(closes)):
            logger.error(f"❌ Различная длина массивов: H:{len(highs)} L:{len(lows)} C:{len(closes)}")
            return False
        
        if len(highs) < 30:
            logger.warning(f"⚠️ Мало данных: {len(highs)} < 30")
        
        # Проверяем валидность цен
        invalid_count = 0
        for i in range(len(highs)):
            h, l, c = highs[i], lows[i], closes[i]
            if not (l <= c <= h and l <= h and l > 0):
                invalid_count += 1
                if invalid_count <= 5:  # Показываем только первые 5 ошибок
                    logger.warning(f"⚠️ Индекс {i}: H:{h:.2f} L:{l:.2f} C:{c:.2f}")
        
        valid_ratio = (len(highs) - invalid_count) / len(highs)
        
        if valid_ratio < 0.8:  # Если меньше 80% валидных данных
            logger.error(f"❌ Слишком много невалидных данных: {invalid_count}/{len(highs)} ({valid_ratio:.1%})")
            return False
        
        logger.info(f"✅ Данные валидны: {len(highs)} свечей, {invalid_count} предупреждений ({valid_ratio:.1%})")
        return True
    
    @staticmethod
    def debug_data(highs: List[float], lows: List[float], closes: List[float], count: int = 5):
        """Отладка данных"""
        logger.info(f"🔍 ОТЛАДКА ПОСЛЕДНИХ {count} СВЕЧЕЙ:")
        start_idx = max(0, len(closes) - count)
        
        for i in range(start_idx, len(closes)):
            logger.info(f"🔍 [{i:2d}] H:{highs[i]:7.2f} L:{lows[i]:7.2f} C:{closes[i]:7.2f}")
    
    @staticmethod
    def calculate_simple_trend(prices: List[float], short_period: int = 5, long_period: int = 20) -> str:
        """Простой анализ тренда для дополнительной проверки"""
        if len(prices) < long_period:
            return "insufficient_data"
        
        try:
            # Короткая и длинная средние
            short_sma = np.mean(prices[-short_period:])
            long_sma = np.mean(prices[-long_period:])
            current_price = prices[-1]
            
            # Определяем тренд
            if current_price > short_sma > long_sma:
                return "strong_uptrend"
            elif current_price > short_sma and short_sma > long_sma * 1.001:  # Небольшая погрешность
                return "uptrend"
            elif current_price < short_sma < long_sma:
                return "strong_downtrend"
            elif current_price < short_sma and short_sma < long_sma * 0.999:
                return "downtrend"
            else:
                return "sideways"
                
        except Exception as e:
            logger.error(f"Ошибка анализа тренда: {e}")
            return "error"
