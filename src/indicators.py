import numpy as np
import pandas as pd
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

class TechnicalIndicators:
    """Точная копия индикатора ADX из TradingView"""
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """Расчет EMA"""
        if len(prices) < period:
            logger.warning(f"⚠️ Недостаточно данных для EMA{period}: {len(prices)} < {period}")
            return [np.nan] * len(prices)
        
        try:
            result = [np.nan] * len(prices)
            multiplier = 2.0 / (period + 1)
            
            sma = np.mean(prices[:period])
            result[period - 1] = sma
            
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
        ТОЧНАЯ КОПИЯ TradingView "ADX and DI for v4"
        """
        
        if len(highs) < period * 2:
            logger.warning(f"⚠️ Недостаточно данных для ADX: {len(highs)} < {period * 2}")
            return {
                'adx': [np.nan] * len(highs),
                'plus_di': [np.nan] * len(highs),
                'minus_di': [np.nan] * len(highs)
            }
        
        try:
            n = len(highs)
            logger.info(f"📊 TradingView ADX расчет для {n} свечей, период {period}")
            
            # Инициализация массивов
            true_range = [0.0] * n
            dm_plus = [0.0] * n
            dm_minus = [0.0] * n
            
            # ШАГ 1: True Range (точно как в TradingView)
            for i in range(n):
                if i == 0:
                    # Первая свеча
                    true_range[i] = highs[i] - lows[i]
                else:
                    # TradingView формула
                    tr1 = highs[i] - lows[i]
                    tr2 = abs(highs[i] - closes[i-1])
                    tr3 = abs(lows[i] - closes[i-1])
                    true_range[i] = max(tr1, max(tr2, tr3))
            
            # ШАГ 2: Directional Movement (точно как в Pine Script)
            for i in range(n):
                if i == 0:
                    dm_plus[i] = 0.0
                    dm_minus[i] = 0.0
                else:
                    # DirectionalMovementPlus = high-nz(high[1]) > nz(low[1])-low ? max(high-nz(high[1]), 0): 0
                    high_diff = highs[i] - highs[i-1]
                    low_diff = lows[i-1] - lows[i]
                    
                    if high_diff > low_diff:
                        dm_plus[i] = max(high_diff, 0.0)
                    else:
                        dm_plus[i] = 0.0
                    
                    # DirectionalMovementMinus = nz(low[1])-low > high-nz(high[1]) ? max(nz(low[1])-low, 0): 0
                    if low_diff > high_diff:
                        dm_minus[i] = max(low_diff, 0.0)
                    else:
                        dm_minus[i] = 0.0
            
            # ШАГ 3: TradingView сглаживание (НЕ Wilder!)
            # SmoothedTrueRange := nz(SmoothedTrueRange[1]) - (nz(SmoothedTrueRange[1])/len) + TrueRange
            
            smoothed_tr = [0.0] * n
            smoothed_dm_plus = [0.0] * n
            smoothed_dm_minus = [0.0] * n
            
            # Инициализация первых значений
            smoothed_tr[0] = true_range[0]
            smoothed_dm_plus[0] = dm_plus[0]
            smoothed_dm_minus[0] = dm_minus[0]
            
            # TradingView сглаживание: prev - prev/len + current
            for i in range(1, n):
                smoothed_tr[i] = smoothed_tr[i-1] - (smoothed_tr[i-1] / period) + true_range[i]
                smoothed_dm_plus[i] = smoothed_dm_plus[i-1] - (smoothed_dm_plus[i-1] / period) + dm_plus[i]
                smoothed_dm_minus[i] = smoothed_dm_minus[i-1] - (smoothed_dm_minus[i-1] / period) + dm_minus[i]
            
            # ШАГ 4: DI расчет
            di_plus = [0.0] * n
            di_minus = [0.0] * n
            
            for i in range(n):
                if smoothed_tr[i] != 0:
                    di_plus[i] = (smoothed_dm_plus[i] / smoothed_tr[i]) * 100.0
                    di_minus[i] = (smoothed_dm_minus[i] / smoothed_tr[i]) * 100.0
                else:
                    di_plus[i] = 0.0
                    di_minus[i] = 0.0
            
            # ШАГ 5: DX расчет
            dx = [0.0] * n
            
            for i in range(n):
                di_sum = di_plus[i] + di_minus[i]
                if di_sum != 0:
                    dx[i] = abs(di_plus[i] - di_minus[i]) / di_sum * 100.0
                else:
                    dx[i] = 0.0
            
            # ШАГ 6: ADX = SMA(DX, period) - ВАЖНО! Не Wilder, а простая SMA!
            adx = [np.nan] * n
            
            for i in range(period - 1, n):
                # Простая скользящая средняя
                window_sum = sum(dx[i - period + 1:i + 1])
                adx[i] = window_sum / period
            
            # Преобразуем в правильный формат с NaN для начальных значений
            adx_result = [np.nan] * n
            plus_di_result = [np.nan] * n
            minus_di_result = [np.nan] * n
            
            # Заполняем значения начиная с period-1
            for i in range(period - 1, n):
                adx_result[i] = adx[i]
                plus_di_result[i] = di_plus[i]
                minus_di_result[i] = di_minus[i]
            
            result = {
                'adx': adx_result,
                'plus_di': plus_di_result,
                'minus_di': minus_di_result
            }
            
            # Логирование результата
            current_adx = result['adx'][-1] if not pd.isna(result['adx'][-1]) else None
            current_plus_di = result['plus_di'][-1] if not pd.isna(result['plus_di'][-1]) else None
            current_minus_di = result['minus_di'][-1] if not pd.isna(result['minus_di'][-1]) else None
            
            logger.info(f"📊 TradingView ADX:")
            logger.info(f"   ADX: {current_adx:.1f}" if current_adx else "   ADX: NaN")
            logger.info(f"   +DI: {current_plus_di:.1f}" if current_plus_di else "   +DI: NaN")
            logger.info(f"   -DI: {current_minus_di:.1f}" if current_minus_di else "   -DI: NaN")
            
            if current_adx and current_plus_di and current_minus_di:
                # Сравнение с эталоном
                expected_adx = 61.14
                expected_plus_di = 15.48
                expected_minus_di = 29.62
                
                adx_diff = abs(current_adx - expected_adx)
                plus_di_diff = abs(current_plus_di - expected_plus_di)
                minus_di_diff = abs(current_minus_di - expected_minus_di)
                total_diff = adx_diff + plus_di_diff + minus_di_diff
                
                logger.info(f"🎯 Сравнение с эталоном:")
                logger.info(f"   ADX: {current_adx:.1f} vs {expected_adx} (отклонение: {adx_diff:.1f})")
                logger.info(f"   +DI: {current_plus_di:.1f} vs {expected_plus_di} (отклонение: {plus_di_diff:.1f})")
                logger.info(f"   -DI: {current_minus_di:.1f} vs {expected_minus_di} (отклонение: {minus_di_diff:.1f})")
                logger.info(f"   Общее отклонение: {total_diff:.1f}")
                
                if total_diff < 10:
                    logger.info("🎉 ОТЛИЧНАЯ ТОЧНОСТЬ!")
                elif total_diff < 20:
                    logger.info("✅ ХОРОШАЯ ТОЧНОСТЬ")
                elif total_diff < 40:
                    logger.info("⚠️ СРЕДНЯЯ ТОЧНОСТЬ")
                else:
                    logger.info("❌ НИЗКАЯ ТОЧНОСТЬ - возможно проблема с данными")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Ошибка расчета TradingView ADX: {e}")
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
        
        if len(highs) < 30:
            logger.warning(f"⚠️ Мало данных: {len(highs)} < 30")
        
        invalid_count = 0
        for i in range(len(highs)):
            h, l, c = highs[i], lows[i], closes[i]
            if not (l <= c <= h and l <= h and l > 0):
                invalid_count += 1
                if invalid_count <= 3:
                    logger.warning(f"⚠️ [{i}] H:{h:.2f} L:{l:.2f} C:{c:.2f}")
        
        valid_ratio = (len(highs) - invalid_count) / len(highs)
        logger.info(f"📊 Валидность: {len(highs)} свечей, {invalid_count} ошибок ({valid_ratio:.1%})")
        
        return valid_ratio >= 0.8
    
    @staticmethod
    def debug_data(highs: List[float], lows: List[float], closes: List[float], count: int = 5):
        """Отладка данных"""
        logger.info(f"🔍 ПОСЛЕДНИЕ {count} СВЕЧЕЙ:")
        start_idx = max(0, len(closes) - count)
        
        for i in range(start_idx, len(closes)):
            h, l, c = highs[i], lows[i], closes[i]
            logger.info(f"🔍 [{i:2d}] H:{h:7.2f} L:{l:7.2f} C:{c:7.2f}")
