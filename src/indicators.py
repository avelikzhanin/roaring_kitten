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
    """Класс для расчета технических индикаторов"""
    
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
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """Расчет ADX, +DI, -DI через TA-Lib"""
        
        if len(highs) < period * 2:
            logger.warning(f"Недостаточно данных для ADX{period}")
            return {
                'adx': [np.nan] * len(highs), 
                'plus_di': [np.nan] * len(highs), 
                'minus_di': [np.nan] * len(highs)
            }
        
        try:
            # Конвертируем в numpy arrays
            high_array = np.array(highs, dtype=float)
            low_array = np.array(lows, dtype=float)
            close_array = np.array(closes, dtype=float)
            
            # Рассчитываем через TA-Lib
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
            
            logger.info(f"📊 ADX: {current_adx:.1f} | +DI: {current_plus_di:.1f} | -DI: {current_minus_di:.1f}")
            
            return {
                'adx': adx_values,
                'plus_di': plus_di_values,
                'minus_di': minus_di_values
            }
            
        except Exception as e:
            logger.error(f"Ошибка расчета ADX{period}: {e}")
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
