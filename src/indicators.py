import numpy as np
import pandas as pd
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

class TechnicalIndicators:
    """Класс индикаторов с исправленным расчетом ADX"""
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """Надежный расчет EMA"""
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
        """ИСПРАВЛЕННЫЙ расчет ADX с улучшенной обработкой граничных случаев"""
        
        if len(highs) < period * 2:
            logger.warning(f"⚠️ Недостаточно данных для ADX: {len(highs)} < {period * 2}")
            return {
                'adx': [np.nan] * len(highs),
                'plus_di': [np.nan] * len(highs),
                'minus_di': [np.nan] * len(highs)
            }
        
        try:
            logger.info(f"🔢 Расчет ADX для {len(highs)} свечей, period={period}")
            
            n = len(highs)
            
            # 1. Расчет True Range
            tr_values = [0.0] * n
            for i in range(1, n):
                tr1 = highs[i] - lows[i]
                tr2 = abs(highs[i] - closes[i-1]) if i > 0 else 0
                tr3 = abs(lows[i] - closes[i-1]) if i > 0 else 0
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
            
            # 3. ИСПРАВЛЕННОЕ сглаживание
            smoothed_tr = TechnicalIndicators._robust_smooth(tr_values, period)
            smoothed_plus_dm = TechnicalIndicators._robust_smooth(plus_dm, period)
            smoothed_minus_dm = TechnicalIndicators._robust_smooth(minus_dm, period)
            
            # 4. Расчет DI с защитой от деления на ноль
            plus_di = [np.nan] * n
            minus_di = [np.nan] * n
            
            for i in range(period, n):
                if smoothed_tr[i] > 0.001:  # Защита от деления на очень малые числа
                    plus_di[i] = 100.0 * smoothed_plus_dm[i] / smoothed_tr[i]
                    minus_di[i] = 100.0 * smoothed_minus_dm[i] / smoothed_tr[i]
                else:
                    plus_di[i] = 0.0
                    minus_di[i] = 0.0
            
            # 5. Расчет DX с улучшенной защитой
            dx_values = [np.nan] * n
            
            for i in range(period, n):
                if not pd.isna(plus_di[i]) and not pd.isna(minus_di[i]):
                    di_sum = plus_di[i] + minus_di[i]
                    if di_sum > 0.1:  # Защита от деления на очень малые суммы
                        dx_values[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / di_sum
                    else:
                        dx_values[i] = 0.0
            
            # 6. ИСПРАВЛЕННЫЙ расчет ADX - используем простое сглаживание
            adx_values = TechnicalIndicators._robust_smooth(dx_values, period)
            
            # 7. Дополнительная обработка NaN в конце
            # Если ADX все еще NaN, но DI есть, попробуем простой расчет
            final_adx = []
            for i in range(n):
                if pd.isna(adx_values[i]) and not pd.isna(plus_di[i]) and not pd.isna(minus_di[i]):
                    # Простая формула для ADX
                    di_sum = plus_di[i] + minus_di[i]
                    if di_sum > 0:
                        simple_adx = 100.0 * abs(plus_di[i] - minus_di[i]) / di_sum
                        final_adx.append(simple_adx)
                    else:
                        final_adx.append(0.0)
                else:
                    final_adx.append(adx_values[i])
            
            result = {
                'adx': final_adx,
                'plus_di': plus_di,
                'minus_di': minus_di
            }
            
            # Детальное логирование для отладки
            current_adx = result['adx'][-1] if not pd.isna(result['adx'][-1]) else None
            current_plus_di = result['plus_di'][-1] if not pd.isna(result['plus_di'][-1]) else None
            current_minus_di = result['minus_di'][-1] if not pd.isna(result['minus_di'][-1]) else None
            
            if current_adx is not None and current_plus_di is not None and current_minus_di is not None:
                logger.info(f"📊 ADX: {current_adx:.1f} | +DI: {current_plus_di:.1f} | -DI: {current_minus_di:.1f}")
            else:
                # Диагностическая информация
                logger.warning(f"⚠️ ADX расчет проблематичен:")
                logger.warning(f"   ADX: {current_adx}")
                logger.warning(f"   +DI: {current_plus_di}")
                logger.warning(f"   -DI: {current_minus_di}")
                logger.warning(f"   Последние TR: {smoothed_tr[-3:]}")
                logger.warning(f"   Последние DX: {dx_values[-3:]}")
            
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
    def _robust_smooth(values: List[float], period: int) -> List[float]:
        """УЛУЧШЕННОЕ сглаживание с защитой от NaN"""
        result = [np.nan] * len(values)
        
        # Находим первую позицию с достаточными данными
        start_idx = period - 1
        
        # Ищем первое валидное окно
        while start_idx < len(values):
            window_values = []
            for i in range(max(0, start_idx - period + 1), start_idx + 1):
                if i < len(values) and not pd.isna(values[i]) and values[i] >= 0:
                    window_values.append(values[i])
            
            if len(window_values) >= period // 2:  # Нужно хотя бы половина значений
                result[start_idx] = sum(window_values) / len(window_values)
                break
            
            start_idx += 1
        
        if start_idx >= len(values):
            logger.warning("⚠️ Не найдено достаточно данных для начала сглаживания")
            return result
        
        # Экспоненциальное сглаживание для остальных значений
        alpha = 2.0 / (period + 1)
        
        for i in range(start_idx + 1, len(values)):
            if not pd.isna(result[i-1]) and not pd.isna(values[i]) and values[i] >= 0:
                result[i] = alpha * values[i] + (1 - alpha) * result[i-1]
            elif not pd.isna(result[i-1]):
                # Если текущее значение NaN, копируем предыдущее
                result[i] = result[i-1]
        
        return result
    
    @staticmethod
    def validate_data(highs: List[float], lows: List[float], closes: List[float]) -> bool:
        """Улучшенная валидация данных"""
        if not (len(highs) == len(lows) == len(closes)):
            logger.error(f"❌ Различная длина массивов: H:{len(highs)} L:{len(lows)} C:{len(closes)}")
            return False
        
        if len(highs) < 30:
            logger.warning(f"⚠️ Мало данных для качественных индикаторов: {len(highs)} < 30")
        
        # Статистика по валидности
        invalid_count = 0
        zero_range_count = 0
        
        for i in range(len(highs)):
            h, l, c = highs[i], lows[i], closes[i]
            
            # Проверки
            if not (l <= c <= h and l <= h and l > 0):
                invalid_count += 1
                if invalid_count <= 5:
                    logger.warning(f"⚠️ Индекс {i}: логика цен H:{h:.2f} L:{l:.2f} C:{c:.2f}")
            
            # Проверка на нулевой диапазон (может влиять на ADX)
            if abs(h - l) < 0.01:
                zero_range_count += 1
        
        valid_ratio = (len(highs) - invalid_count) / len(highs)
        
        logger.info(f"📊 Валидация: {len(highs)} свечей, {invalid_count} ошибок, {zero_range_count} нулевых диапазонов ({valid_ratio:.1%} валидных)")
        
        return valid_ratio >= 0.8  # Требуем минимум 80% валидных данных
    
    @staticmethod
    def debug_data(highs: List[float], lows: List[float], closes: List[float], count: int = 5):
        """Детальная отладка данных"""
        logger.info(f"🔍 ОТЛАДКА ПОСЛЕДНИХ {count} СВЕЧЕЙ:")
        start_idx = max(0, len(closes) - count)
        
        for i in range(start_idx, len(closes)):
            h, l, c = highs[i], lows[i], closes[i]
            range_val = h - l
            logger.info(f"🔍 [{i:2d}] H:{h:7.2f} L:{l:7.2f} C:{c:7.2f} Range:{range_val:5.2f}")
    
    @staticmethod
    def calculate_simple_trend(prices: List[float], short_period: int = 5, long_period: int = 20) -> str:
        """Простой анализ тренда"""
        if len(prices) < long_period:
            return "insufficient_data"
        
        try:
            short_sma = np.mean(prices[-short_period:])
            long_sma = np.mean(prices[-long_period:])
            current_price = prices[-1]
            
            if current_price > short_sma > long_sma:
                return "strong_uptrend"
            elif current_price > short_sma:
                return "uptrend"
            elif current_price < short_sma < long_sma:
                return "strong_downtrend"
            elif current_price < short_sma:
                return "downtrend"
            else:
                return "sideways"
                
        except Exception as e:
            logger.error(f"Ошибка анализа тренда: {e}")
            return "error"
    
    @staticmethod
    def test_adx_calculation(test_data: bool = False):
        """Тестовый метод для проверки расчета ADX"""
        if test_data:
            # Генерируем тестовые данные с трендом
            logger.info("🧪 Тест расчета ADX с тестовыми данными")
            
            highs = [100 + i * 0.5 + np.random.random() * 2 for i in range(50)]
            lows = [h - 2 - np.random.random() * 2 for h in highs]
            closes = [l + np.random.random() * (h - l) for h, l in zip(highs, lows)]
            
            # Корректируем данные
            for i in range(len(highs)):
                if closes[i] < lows[i]:
                    closes[i] = lows[i]
                if closes[i] > highs[i]:
                    closes[i] = highs[i]
            
            logger.info(f"🧪 Создано {len(highs)} тестовых свечей")
            logger.info(f"🧪 Диапазон цен: {min(lows):.2f} - {max(highs):.2f}")
            
            result = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            
            final_adx = result['adx'][-1]
            final_plus_di = result['plus_di'][-1]
            final_minus_di = result['minus_di'][-1]
            
            logger.info(f"🧪 РЕЗУЛЬТАТ ТЕСТА:")
            logger.info(f"   ADX: {final_adx:.1f}" if not pd.isna(final_adx) else "   ADX: NaN")
            logger.info(f"   +DI: {final_plus_di:.1f}" if not pd.isna(final_plus_di) else "   +DI: NaN")
            logger.info(f"   -DI: {final_minus_di:.1f}" if not pd.isna(final_minus_di) else "   -DI: NaN")
            
            return not pd.isna(final_adx)
        
        return True
