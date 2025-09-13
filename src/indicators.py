import numpy as np
import pandas as pd
from typing import List, Dict
import logging

# Импортируем TA-Lib
try:
    import talib
    logger = logging.getLogger(__name__)
    logger.info("✅ TA-Lib загружен")
except ImportError as e:
    logger = logging.getLogger(__name__)
    logger.error(f"❌ TA-Lib не установлен: {e}")
    raise ImportError("TA-Lib обязателен для работы бота")

class TechnicalIndicators:
    """Класс для расчета технических индикаторов с поддержкой TradingView совместимости"""
    
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
        """
        Точная реплика Wilder's smoothing из TradingView Pine Script
        Formula: prev_value - (prev_value/period) + current_value
        """
        result = [np.nan] * len(values)
        
        # Находим первое валидное значение
        first_valid_idx = None
        for i, val in enumerate(values):
            if not pd.isna(val):
                first_valid_idx = i
                break
        
        if first_valid_idx is None or first_valid_idx + period > len(values):
            return result
        
        # Инициализация - используем первое значение
        smoothed = values[first_valid_idx] if not pd.isna(values[first_valid_idx]) else 0.0
        result[first_valid_idx] = smoothed
        
        # Wilder's smoothing для остальных значений
        for i in range(first_valid_idx + 1, len(values)):
            if not pd.isna(values[i]):
                # Формула из Pine Script: prev - (prev/len) + current
                smoothed = smoothed - (smoothed / period) + values[i]
                result[i] = smoothed
        
        return result
    
    @staticmethod 
    def _simple_moving_average(values: List[float], period: int) -> List[float]:
        """Простое скользящее среднее - точно как в Pine Script sma()"""
        result = [np.nan] * len(values)
        
        for i in range(period - 1, len(values)):
            # Берем последние period значений
            window = values[i - period + 1:i + 1]
            
            # Проверяем что все значения валидны
            valid_values = [v for v in window if not pd.isna(v)]
            
            if len(valid_values) == period:
                result[i] = sum(valid_values) / period
        
        return result
    
    @staticmethod
    def calculate_tradingview_adx(highs: List[float], lows: List[float], 
                                 closes: List[float], period: int = 14) -> Dict:
        """
        ТОЧНАЯ реплика TradingView индикатора "ADX and DI for v4"
        
        Ключевое отличие: использует SMA для сглаживания ADX вместо Wilder's RMA
        """
        
        if len(highs) < period * 2:
            logger.warning(f"Недостаточно данных для TradingView ADX")
            return {
                'adx': [np.nan] * len(highs),
                'plus_di': [np.nan] * len(highs),
                'minus_di': [np.nan] * len(highs)
            }
        
        n = len(highs)
        
        # Шаг 1: Расчет True Range (стандартная формула)
        true_ranges = [np.nan]  # Первое значение NaN
        for i in range(1, n):
            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i-1])
            tr3 = abs(lows[i] - closes[i-1])
            true_ranges.append(max(tr1, tr2, tr3))
        
        # Шаг 2: Расчет Directional Movement (точная логика из Pine Script)
        dm_plus = [np.nan]  
        dm_minus = [np.nan]
        
        for i in range(1, n):
            high_diff = highs[i] - highs[i-1]
            low_diff = lows[i-1] - lows[i]  # Обратите внимание на порядок!
            
            # Точная логика из Pine Script
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
        
        # Шаг 4: Расчет DI
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
        
        # Шаг 5: Расчет DX
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
        
        # Шаг 6: КРИТИЧЕСКОЕ ОТЛИЧИЕ - SMA для ADX (не Wilder's!)
        adx_values = TechnicalIndicators._simple_moving_average(dx_values, period)
        
        return {
            'adx': adx_values,
            'plus_di': plus_di, 
            'minus_di': minus_di
        }
    
    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """
        Основной метод расчета ADX - использует TradingView совместимую версию
        """
        
        logger.info(f"📊 Расчет ADX{period} (TradingView совместимый)")
        
        try:
            # Сначала пробуем TradingView совместимую версию
            result = TechnicalIndicators.calculate_tradingview_adx(highs, lows, closes, period)
            
            # Проверяем качество результата
            current_adx = result['adx'][-1]
            current_plus_di = result['plus_di'][-1]
            current_minus_di = result['minus_di'][-1]
            
            if (not pd.isna(current_adx) and not pd.isna(current_plus_di) and 
                not pd.isna(current_minus_di) and 0 <= current_adx <= 100):
                
                logger.info(f"📊 TradingView ADX: {current_adx:.1f} | +DI: {current_plus_di:.1f} | -DI: {current_minus_di:.1f}")
                return result
            else:
                logger.warning("⚠️ TradingView ADX дал некорректные результаты, переходим к TA-Lib")
        
        except Exception as e:
            logger.warning(f"⚠️ TradingView ADX не удался: {e}")
        
        # Fallback к стандартному TA-Lib
        logger.info(f"📊 Используем стандартный TA-Lib ADX{period}")
        
        try:
            high_array = np.array(highs, dtype=float)
            low_array = np.array(lows, dtype=float)
            close_array = np.array(closes, dtype=float)
            
            adx = talib.ADX(high_array, low_array, close_array, timeperiod=period)
            plus_di = talib.PLUS_DI(high_array, low_array, close_array, timeperiod=period)
            minus_di = talib.MINUS_DI(high_array, low_array, close_array, timeperiod=period)
            
            adx_values = adx.tolist()
            plus_di_values = plus_di.tolist()
            minus_di_values = minus_di.tolist()
            
            current_adx = adx_values[-1] if not pd.isna(adx_values[-1]) else np.nan
            current_plus_di = plus_di_values[-1] if not pd.isna(plus_di_values[-1]) else np.nan
            current_minus_di = minus_di_values[-1] if not pd.isna(minus_di_values[-1]) else np.nan
            
            logger.info(f"📊 TA-Lib ADX: {current_adx:.1f} | +DI: {current_plus_di:.1f} | -DI: {current_minus_di:.1f}")
            
            return {
                'adx': adx_values,
                'plus_di': plus_di_values,
                'minus_di': minus_di_values
            }
            
        except Exception as e:
            logger.error(f"❌ Стандартный TA-Lib ADX тоже не сработал: {e}")
            raise RuntimeError(f"Не удалось рассчитать ADX{period}: {e}")
    
    @staticmethod
    def calculate_rsi(closes: List[float], period: int = 14) -> List[float]:
        """Расчет RSI через TA-Lib"""
        if len(closes) < period + 1:
            logger.warning(f"Недостаточно данных для RSI{period}")
            return [np.nan] * len(closes)
        
        try:
            close_array = np.array(closes, dtype=float)
            rsi = talib.RSI(close_array, timeperiod=period)
            result = rsi.tolist()
            
            current_rsi = result[-1] if not pd.isna(result[-1]) else np.nan
            
            if current_rsi > 70:
                rsi_status = "перекуплен"
            elif current_rsi < 30:
                rsi_status = "перепродан"
            else:
                rsi_status = "нейтрально"
            
            logger.info(f"📊 RSI{period}: {current_rsi:.1f} ({rsi_status})")
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка расчета RSI{period}: {e}")
            raise RuntimeError(f"Не удалось рассчитать RSI{period}: {e}")
    
    @staticmethod
    def calculate_macd(closes: List[float], fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> Dict:
        """Расчет MACD через TA-Lib"""
        if len(closes) < slow_period + signal_period:
            logger.warning(f"Недостаточно данных для MACD")
            return {
                'macd': [np.nan] * len(closes),
                'signal': [np.nan] * len(closes), 
                'histogram': [np.nan] * len(closes)
            }
        
        try:
            close_array = np.array(closes, dtype=float)
            macd, signal, histogram = talib.MACD(close_array, 
                                               fastperiod=fast_period,
                                               slowperiod=slow_period, 
                                               signalperiod=signal_period)
            
            current_macd = macd[-1] if not pd.isna(macd[-1]) else np.nan
            current_signal = signal[-1] if not pd.isna(signal[-1]) else np.nan
            current_histogram = histogram[-1] if not pd.isna(histogram[-1]) else np.nan
            
            logger.info(f"📊 MACD: {current_macd:.3f} | Signal: {current_signal:.3f}")
            
            return {
                'macd': macd.tolist(),
                'signal': signal.tolist(),
                'histogram': histogram.tolist()
            }
            
        except Exception as e:
            logger.error(f"Ошибка расчета MACD: {e}")
            raise RuntimeError(f"Не удалось рассчитать MACD: {e}")
    
    @staticmethod
    def calculate_bollinger_bands(closes: List[float], period: int = 20, std_dev: float = 2.0) -> Dict:
        """Расчет полос Боллинджера через TA-Lib"""
        if len(closes) < period:
            logger.warning(f"Недостаточно данных для Bollinger Bands")
            return {
                'upper': [np.nan] * len(closes),
                'middle': [np.nan] * len(closes),
                'lower': [np.nan] * len(closes)
            }
        
        try:
            close_array = np.array(closes, dtype=float)
            upper, middle, lower = talib.BBANDS(close_array, 
                                               timeperiod=period,
                                               nbdevup=std_dev, 
                                               nbdevdn=std_dev)
            
            current_upper = upper[-1] if not pd.isna(upper[-1]) else np.nan
            current_middle = middle[-1] if not pd.isna(middle[-1]) else np.nan  
            current_lower = lower[-1] if not pd.isna(lower[-1]) else np.nan
            current_price = closes[-1]
            
            if current_price > current_upper:
                bb_position = "выше верхней"
            elif current_price < current_lower:
                bb_position = "ниже нижней"
            else:
                bb_position = "в полосах"
            
            logger.info(f"📊 BB: {current_lower:.2f} < {current_middle:.2f} < {current_upper:.2f} ({bb_position})")
            
            return {
                'upper': upper.tolist(),
                'middle': middle.tolist(),
                'lower': lower.tolist()
            }
            
        except Exception as e:
            logger.error(f"Ошибка расчета Bollinger Bands: {e}")
            raise RuntimeError(f"Не удалось рассчитать Bollinger Bands: {e}")
    
    @staticmethod
    def find_support_resistance_levels(highs: List[float], lows: List[float], period: int = 20) -> Dict:
        """Определение уровней поддержки и сопротивления"""
        try:
            if len(highs) < period:
                logger.warning(f"Недостаточно данных для уровней")
                return {'support': None, 'resistance': None}
            
            # Анализируем последние периоды
            recent_highs = highs[-period:]
            recent_lows = lows[-period:]
            
            # Простые уровни
            resistance = max(recent_highs)
            support = min(recent_lows)
            
            # Ищем локальные экстремумы
            resistance_levels = []
            support_levels = []
            
            for i in range(2, len(recent_highs) - 2):
                # Локальный максимум
                if (recent_highs[i] > recent_highs[i-1] and 
                    recent_highs[i] > recent_highs[i-2] and
                    recent_highs[i] > recent_highs[i+1] and 
                    recent_highs[i] > recent_highs[i+2]):
                    resistance_levels.append(recent_highs[i])
                
                # Локальный минимум
                if (recent_lows[i] < recent_lows[i-1] and 
                    recent_lows[i] < recent_lows[i-2] and
                    recent_lows[i] < recent_lows[i+1] and 
                    recent_lows[i] < recent_lows[i+2]):
                    support_levels.append(recent_lows[i])
            
            # Выбираем лучшие уровни
            if resistance_levels:
                resistance = max(resistance_levels)
            if support_levels:
                support = min(support_levels)
            
            logger.info(f"📊 Поддержка: {support:.2f} | Сопротивление: {resistance:.2f}")
            
            return {
                'support': round(support, 2),
                'resistance': round(resistance, 2)
            }
            
        except Exception as e:
            logger.error(f"Ошибка определения уровней: {e}")
            return {'support': None, 'resistance': None}
