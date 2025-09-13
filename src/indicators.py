import numpy as np
import pandas as pd
from typing import List, Dict
import logging

# Импортируем TA-Lib (обязательно должен быть установлен)
try:
    import talib
    logger = logging.getLogger(__name__)
    logger.info("✅ TA-Lib импортирован успешно")
except ImportError as e:
    logger = logging.getLogger(__name__)
    logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: TA-Lib не установлен! {e}")
    logger.error("Установите TA-Lib: pip install TA-Lib")
    raise ImportError("TA-Lib обязателен для работы бота")

class TechnicalIndicators:
    """Класс для расчета технических индикаторов через TA-Lib (ТОЛЬКО TA-Lib)"""
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """Расчет EMA через TA-Lib"""
        if len(prices) < period:
            logger.warning(f"Недостаточно данных для EMA{period}: {len(prices)} < {period}")
            return [np.nan] * len(prices)
        
        try:
            logger.info(f"📈 Расчет EMA{period} через TA-Lib...")
            
            # Конвертируем в numpy array
            prices_array = np.array(prices, dtype=float)
            
            # Рассчитываем через TA-Lib
            ema = talib.EMA(prices_array, timeperiod=period)
            result = ema.tolist()
            
            # Логирование результата
            current_ema = result[-1] if not pd.isna(result[-1]) else np.nan
            logger.info(f"   ✅ EMA{period} рассчитан: текущее значение = {current_ema:.2f}")
            logger.info(f"   📊 Последние 3 значения: {[round(x, 2) if not pd.isna(x) else 'NaN' for x in result[-3:]]}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Ошибка расчета EMA{period} через TA-Lib: {e}")
            raise RuntimeError(f"Не удалось рассчитать EMA{period}: {e}")
    
    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """Расчет ADX, +DI, -DI ТОЛЬКО через TA-Lib"""
        
        if len(highs) < period * 2:
            logger.warning(f"Недостаточно данных для ADX{period}: {len(highs)} < {period * 2}")
            return {
                'adx': [np.nan] * len(highs), 
                'plus_di': [np.nan] * len(highs), 
                'minus_di': [np.nan] * len(highs)
            }
        
        try:
            logger.info(f"📊 Расчет ADX{period} через TA-Lib для {len(highs)} свечей...")
            
            # Конвертируем в numpy arrays
            high_array = np.array(highs, dtype=float)
            low_array = np.array(lows, dtype=float)
            close_array = np.array(closes, dtype=float)
            
            logger.info(f"   📊 Входные данные подготовлены:")
            logger.info(f"      Всего свечей: {len(high_array)}")
            logger.info(f"      Последние цены: H={high_array[-1]:.2f}, L={low_array[-1]:.2f}, C={close_array[-1]:.2f}")
            
            # Рассчитываем все индикаторы через TA-Lib
            logger.info(f"   🧮 Вызываем TA-Lib функции...")
            
            adx = talib.ADX(high_array, low_array, close_array, timeperiod=period)
            plus_di = talib.PLUS_DI(high_array, low_array, close_array, timeperiod=period)
            minus_di = talib.MINUS_DI(high_array, low_array, close_array, timeperiod=period)
            
            # Конвертируем в списки
            adx_values = adx.tolist()
            plus_di_values = plus_di.tolist()
            minus_di_values = minus_di.tolist()
            
            # Получаем текущие значения
            current_adx = adx_values[-1] if not pd.isna(adx_values[-1]) else np.nan
            current_plus_di = plus_di_values[-1] if not pd.isna(plus_di_values[-1]) else np.nan
            current_minus_di = minus_di_values[-1] if not pd.isna(minus_di_values[-1]) else np.nan
            current_di_diff = current_plus_di - current_minus_di
            
            # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ
            logger.info(f"")
            logger.info(f"🎯 TA-LIB ADX РЕЗУЛЬТАТЫ:")
            logger.info(f"   📊 ADX: {current_adx:.1f}")
            logger.info(f"   📈 +DI: {current_plus_di:.1f}")
            logger.info(f"   📉 -DI: {current_minus_di:.1f}")
            logger.info(f"   🔄 Разница DI: {current_di_diff:.1f}")
            logger.info(f"   💪 Сила тренда: {'ОЧЕНЬ СИЛЬНЫЙ' if current_adx > 45 else 'СИЛЬНЫЙ' if current_adx > 25 else 'СЛАБЫЙ'}")
            logger.info(f"   📈 Направление: {'ВВЕРХ' if current_plus_di > current_minus_di else 'ВНИЗ'}")
            logger.info(f"")
            
            # Проверяем качество данных
            nan_adx = sum(1 for x in adx_values[-10:] if pd.isna(x))
            nan_plus_di = sum(1 for x in plus_di_values[-10:] if pd.isna(x))  
            nan_minus_di = sum(1 for x in minus_di_values[-10:] if pd.isna(x))
            
            if nan_adx > 0 or nan_plus_di > 0 or nan_minus_di > 0:
                logger.warning(f"⚠️ Найдены NaN значения в последних 10 периодах:")
                logger.warning(f"   ADX NaN: {nan_adx}/10, +DI NaN: {nan_plus_di}/10, -DI NaN: {nan_minus_di}/10")
            else:
                logger.info(f"✅ Все значения рассчитаны корректно (нет NaN в последних 10 периодах)")
            
            return {
                'adx': adx_values,
                'plus_di': plus_di_values,
                'minus_di': minus_di_values
            }
            
        except Exception as e:
            logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА TA-Lib ADX: {e}")
            logger.error(f"   Тип ошибки: {type(e).__name__}")
            logger.error(f"   Параметры: highs={len(highs)}, lows={len(lows)}, closes={len(closes)}, period={period}")
            raise RuntimeError(f"Не удалось рассчитать ADX через TA-Lib: {e}")
    
    @staticmethod
    def calculate_rsi(closes: List[float], period: int = 14) -> List[float]:
        """Расчет RSI через TA-Lib"""
        if len(closes) < period + 1:
            logger.warning(f"Недостаточно данных для RSI{period}: {len(closes)} < {period + 1}")
            return [np.nan] * len(closes)
        
        try:
            logger.info(f"📊 Расчет RSI{period} через TA-Lib...")
            
            close_array = np.array(closes, dtype=float)
            rsi = talib.RSI(close_array, timeperiod=period)
            result = rsi.tolist()
            
            current_rsi = result[-1] if not pd.isna(result[-1]) else np.nan
            
            # Интерпретация RSI
            if current_rsi > 70:
                rsi_status = "ПЕРЕКУПЛЕН"
            elif current_rsi < 30:
                rsi_status = "ПЕРЕПРОДАН"
            else:
                rsi_status = "НЕЙТРАЛЬНАЯ ЗОНА"
            
            logger.info(f"   ✅ RSI{period}: {current_rsi:.1f} ({rsi_status})")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Ошибка расчета RSI{period} через TA-Lib: {e}")
            raise RuntimeError(f"Не удалось рассчитать RSI{period}: {e}")
    
    @staticmethod
    def calculate_macd(closes: List[float], fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> Dict:
        """Расчет MACD через TA-Lib"""
        if len(closes) < slow_period + signal_period:
            logger.warning(f"Недостаточно данных для MACD: {len(closes)} < {slow_period + signal_period}")
            return {
                'macd': [np.nan] * len(closes),
                'signal': [np.nan] * len(closes), 
                'histogram': [np.nan] * len(closes)
            }
        
        try:
            logger.info(f"📊 Расчет MACD({fast_period},{slow_period},{signal_period}) через TA-Lib...")
            
            close_array = np.array(closes, dtype=float)
            macd, signal, histogram = talib.MACD(close_array, 
                                               fastperiod=fast_period,
                                               slowperiod=slow_period, 
                                               signalperiod=signal_period)
            
            current_macd = macd[-1] if not pd.isna(macd[-1]) else np.nan
            current_signal = signal[-1] if not pd.isna(signal[-1]) else np.nan
            current_histogram = histogram[-1] if not pd.isna(histogram[-1]) else np.nan
            
            logger.info(f"   ✅ MACD: {current_macd:.2f}, Signal: {current_signal:.2f}, Histogram: {current_histogram:.2f}")
            
            return {
                'macd': macd.tolist(),
                'signal': signal.tolist(),
                'histogram': histogram.tolist()
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка расчета MACD через TA-Lib: {e}")
            raise RuntimeError(f"Не удалось рассчитать MACD: {e}")
    
    @staticmethod
    def calculate_bollinger_bands(closes: List[float], period: int = 20, std_dev: float = 2.0) -> Dict:
        """Расчет полос Боллинджера через TA-Lib"""
        if len(closes) < period:
            logger.warning(f"Недостаточно данных для Bollinger Bands: {len(closes)} < {period}")
            return {
                'upper': [np.nan] * len(closes),
                'middle': [np.nan] * len(closes),
                'lower': [np.nan] * len(closes)
            }
        
        try:
            logger.info(f"📊 Расчет Bollinger Bands({period}, {std_dev}) через TA-Lib...")
            
            close_array = np.array(closes, dtype=float)
            upper, middle, lower = talib.BBANDS(close_array, 
                                               timeperiod=period,
                                               nbdevup=std_dev, 
                                               nbdevdn=std_dev)
            
            current_upper = upper[-1] if not pd.isna(upper[-1]) else np.nan
            current_middle = middle[-1] if not pd.isna(middle[-1]) else np.nan  
            current_lower = lower[-1] if not pd.isna(lower[-1]) else np.nan
            current_price = closes[-1]
            
            # Позиция цены относительно полос
            if current_price > current_upper:
                bb_position = "ВЫШЕ ВЕРХНЕЙ ПОЛОСЫ"
            elif current_price < current_lower:
                bb_position = "НИЖЕ НИЖНЕЙ ПОЛОСЫ"
            else:
                bb_position = "ВНУТРИ ПОЛОС"
            
            logger.info(f"   ✅ BB: Upper={current_upper:.2f}, Middle={current_middle:.2f}, Lower={current_lower:.2f}")
            logger.info(f"   📍 Позиция цены: {bb_position}")
            
            return {
                'upper': upper.tolist(),
                'middle': middle.tolist(),
                'lower': lower.tolist()
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка расчета Bollinger Bands через TA-Lib: {e}")
            raise RuntimeError(f"Не удалось рассчитать Bollinger Bands: {e}")
    
    @staticmethod
    def find_support_resistance_levels(highs: List[float], lows: List[float], period: int = 20) -> Dict:
        """Простое определение уровней поддержки и сопротивления"""
        try:
            if len(highs) < period:
                logger.warning(f"Недостаточно данных для уровней: {len(highs)} < {period}")
                return {'support': None, 'resistance': None}
            
            logger.info(f"📊 Определение уровней поддержки/сопротивления за {period} периодов...")
            
            # Анализируем последние периоды
            recent_highs = highs[-period:]
            recent_lows = lows[-period:]
            current_price = highs[-1]  # Приблизительно текущая цена
            
            # Простые уровни
            resistance = max(recent_highs)
            support = min(recent_lows)
            
            # Более умные уровни через локальные экстремумы
            resistance_levels = []
            support_levels = []
            
            # Ищем локальные максимумы и минимумы
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
            
            # Выбираем ближайшие значимые уровни
            if resistance_levels:
                # Ближайшее сопротивление выше текущей цены
                resistance_above = [r for r in resistance_levels if r > current_price]
                if resistance_above:
                    resistance = min(resistance_above)
                else:
                    resistance = max(resistance_levels)
            
            if support_levels:
                # Ближайшая поддержка ниже текущей цены
                support_below = [s for s in support_levels if s < current_price]
                if support_below:
                    support = max(support_below)
                else:
                    support = min(support_levels)
            
            logger.info(f"   ✅ Поддержка: {support:.2f}, Сопротивление: {resistance:.2f}")
            
            return {
                'support': round(support, 2),
                'resistance': round(resistance, 2)
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка определения уровней: {e}")
            return {'support': None, 'resistance': None}
