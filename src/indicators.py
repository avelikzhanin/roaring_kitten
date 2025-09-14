import numpy as np
import pandas as pd
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

class TechnicalIndicators:
    """Точная копия TradingView с правильной инициализацией"""
    
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
        МАКСИМАЛЬНО ТОЧНАЯ копия TradingView с правильной инициализацией
        """
        
        if len(highs) < period + 1:  # Нужно минимум period + 1 свечей
            logger.warning(f"⚠️ Недостаточно данных для ADX: {len(highs)} < {period + 1}")
            return {
                'adx': [np.nan] * len(highs),
                'plus_di': [np.nan] * len(highs),
                'minus_di': [np.nan] * len(highs)
            }
        
        try:
            n = len(highs)
            logger.info(f"📊 ТОЧНЫЙ TradingView ADX: {n} свечей, период {period}")
            
            # ШАГ 1: True Range - точно как в Pine Script
            true_range = []
            
            for i in range(n):
                if i == 0:
                    # Первая свеча: nz(close[1]) возвращает 0, поэтому TR = high - low
                    tr = highs[i] - lows[i]
                else:
                    # TrueRange = max(max(high-low, abs(high-nz(close[1]))), abs(low-nz(close[1])))
                    tr1 = highs[i] - lows[i]
                    tr2 = abs(highs[i] - closes[i-1])
                    tr3 = abs(lows[i] - closes[i-1])
                    tr = max(tr1, max(tr2, tr3))
                
                true_range.append(tr)
            
            # ШАГ 2: Directional Movement - точно как в Pine Script
            dm_plus = []
            dm_minus = []
            
            for i in range(n):
                if i == 0:
                    # Первая свеча: nz(high[1]) и nz(low[1]) возвращают 0
                    dm_plus.append(0.0)
                    dm_minus.append(0.0)
                else:
                    # DirectionalMovementPlus = high-nz(high[1]) > nz(low[1])-low ? max(high-nz(high[1]), 0): 0
                    high_diff = highs[i] - highs[i-1]
                    low_diff = lows[i-1] - lows[i]
                    
                    if high_diff > low_diff:
                        dm_plus.append(max(high_diff, 0.0))
                    else:
                        dm_plus.append(0.0)
                    
                    # DirectionalMovementMinus = nz(low[1])-low > high-nz(high[1]) ? max(nz(low[1])-low, 0): 0
                    if low_diff > high_diff:
                        dm_minus.append(max(low_diff, 0.0))
                    else:
                        dm_minus.append(0.0)
            
            # ШАГ 3: Сглаживание - ТОЧНО как в Pine Script с правильной инициализацией
            # SmoothedTrueRange = 0.0
            # SmoothedTrueRange := nz(SmoothedTrueRange[1]) - (nz(SmoothedTrueRange[1])/len) + TrueRange
            
            smoothed_tr = []
            smoothed_dm_plus = []
            smoothed_dm_minus = []
            
            for i in range(n):
                if i == 0:
                    # Инициализация: SmoothedTrueRange = 0.0
                    smoothed_tr.append(true_range[i])  # На самом деле в TV первое значение = первый TR
                    smoothed_dm_plus.append(dm_plus[i])
                    smoothed_dm_minus.append(dm_minus[i])
                else:
                    # Формула TradingView: prev - prev/len + current
                    smoothed_tr_val = smoothed_tr[i-1] - (smoothed_tr[i-1] / period) + true_range[i]
                    smoothed_dm_plus_val = smoothed_dm_plus[i-1] - (smoothed_dm_plus[i-1] / period) + dm_plus[i]
                    smoothed_dm_minus_val = smoothed_dm_minus[i-1] - (smoothed_dm_minus[i-1] / period) + dm_minus[i]
                    
                    smoothed_tr.append(smoothed_tr_val)
                    smoothed_dm_plus.append(smoothed_dm_plus_val)
                    smoothed_dm_minus.append(smoothed_dm_minus_val)
            
            # ШАГ 4: DI расчет
            di_plus = []
            di_minus = []
            
            for i in range(n):
                if smoothed_tr[i] > 0:
                    di_plus_val = (smoothed_dm_plus[i] / smoothed_tr[i]) * 100.0
                    di_minus_val = (smoothed_dm_minus[i] / smoothed_tr[i]) * 100.0
                else:
                    di_plus_val = 0.0
                    di_minus_val = 0.0
                
                di_plus.append(di_plus_val)
                di_minus.append(di_minus_val)
            
            # ШАГ 5: DX расчет
            dx = []
            
            for i in range(n):
                di_sum = di_plus[i] + di_minus[i]
                if di_sum > 0:
                    dx_val = abs(di_plus[i] - di_minus[i]) / di_sum * 100.0
                else:
                    dx_val = 0.0
                
                dx.append(dx_val)
            
            # ШАГ 6: ADX = sma(DX, len) - простая скользящая средняя
            adx = []
            
            for i in range(n):
                if i < period - 1:
                    # Недостаточно данных для SMA
                    adx.append(np.nan)
                else:
                    # Простая скользящая средняя последних period значений DX
                    dx_window = dx[i - period + 1:i + 1]
                    sma_val = sum(dx_window) / period
                    adx.append(sma_val)
            
            # Результат в правильном формате
            result = {
                'adx': adx,
                'plus_di': di_plus,
                'minus_di': di_minus
            }
            
            # Логирование с детальной диагностикой
            current_adx = result['adx'][-1] if not pd.isna(result['adx'][-1]) else None
            current_plus_di = result['plus_di'][-1] if not pd.isna(result['plus_di'][-1]) else None
            current_minus_di = result['minus_di'][-1] if not pd.isna(result['minus_di'][-1]) else None
            
            logger.info(f"📊 ФИНАЛЬНЫЙ TradingView ADX:")
            logger.info(f"   ADX: {current_adx:.1f}" if current_adx else "   ADX: NaN")
            logger.info(f"   +DI: {current_plus_di:.1f}" if current_plus_di else "   +DI: NaN")
            logger.info(f"   -DI: {current_minus_di:.1f}" if current_minus_di else "   -DI: NaN")
            
            # Диагностика последних значений
            logger.info(f"🔍 Диагностика последних значений:")
            for i in range(max(0, n-3), n):
                logger.info(f"   [{i}] TR:{true_range[i]:.3f} +DM:{dm_plus[i]:.3f} -DM:{dm_minus[i]:.3f}")
                logger.info(f"       SmoothedTR:{smoothed_tr[i]:.3f} +DI:{di_plus[i]:.1f} -DI:{di_minus[i]:.1f} DX:{dx[i]:.1f}")
            
            # Показываем последние значения DX для расчета SMA
            if n >= period:
                logger.info(f"🔍 Последние {period} значений DX для SMA:")
                dx_for_sma = dx[-period:]
                logger.info(f"   DX: {[f'{x:.1f}' for x in dx_for_sma]}")
                logger.info(f"   SMA(DX): {sum(dx_for_sma) / period:.1f}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Ошибка расчета точного TradingView ADX: {e}")
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
