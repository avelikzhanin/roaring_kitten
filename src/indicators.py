import numpy as np
import pandas as pd
from typing import List, Dict
import logging

# Пробуем импортировать TA-Lib
try:
    import talib
    TALIB_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("✅ TA-Lib успешно импортирован")
except ImportError:
    TALIB_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("⚠️ TA-Lib недоступен, используем собственные алгоритмы")

class TechnicalIndicators:
    """Класс для расчета технических индикаторов с TA-Lib и fallback алгоритмами"""
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """Расчет экспоненциальной скользящей средней"""
        if len(prices) < period:
            return [np.nan] * len(prices)
        
        if TALIB_AVAILABLE:
            try:
                # Используем TA-Lib если доступен
                prices_array = np.array(prices, dtype=float)
                ema = talib.EMA(prices_array, timeperiod=period)
                result = ema.tolist()
                
                logger.info(f"EMA{period} (TA-Lib): последние 3 значения: {result[-3:]}")
                return result
                
            except Exception as e:
                logger.error(f"Ошибка TA-Lib EMA: {e}")
        
        # Fallback на pandas
        try:
            series = pd.Series(prices)
            ema = series.ewm(span=period, adjust=False).mean()
            result = ema.tolist()
            logger.info(f"EMA{period} (pandas): последние 3 значения: {result[-3:]}")
            return result
        except Exception as e:
            logger.error(f"Ошибка pandas EMA: {e}")
            return [np.nan] * len(prices)
    
    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """Расчет ADX, +DI, -DI с приоритетом TA-Lib"""
        
        if len(highs) < period * 2:
            logger.warning(f"Недостаточно данных для ADX: {len(highs)} < {period * 2}")
            return {
                'adx': [np.nan] * len(highs), 
                'plus_di': [np.nan] * len(highs), 
                'minus_di': [np.nan] * len(highs)
            }
        
        if TALIB_AVAILABLE:
            try:
                logger.info(f"🧮 Расчет ADX через TA-Lib для {len(highs)} свечей")
                
                # Конвертируем в numpy arrays
                high_array = np.array(highs, dtype=float)
                low_array = np.array(lows, dtype=float)
                close_array = np.array(closes, dtype=float)
                
                # Рассчитываем через TA-Lib
                adx = talib.ADX(high_array, low_array, close_array, timeperiod=period)
                plus_di = talib.PLUS_DI(high_array, low_array, close_array, timeperiod=period)
                minus_di = talib.MINUS_DI(high_array, low_array, close_array, timeperiod=period)
                
                # Конвертируем обратно в списки
                adx_values = adx.tolist()
                plus_di_values = plus_di.tolist()
                minus_di_values = minus_di.tolist()
                
                # Логирование результатов
                current_adx = adx_values[-1] if not pd.isna(adx_values[-1]) else np.nan
                current_plus_di = plus_di_values[-1] if not pd.isna(plus_di_values[-1]) else np.nan
                current_minus_di = minus_di_values[-1] if not pd.isna(minus_di_values[-1]) else np.nan
                
                logger.info(f"🎯 TA-Lib ADX результаты:")
                logger.info(f"   ADX: {current_adx:.1f}")
                logger.info(f"   +DI: {current_plus_di:.1f}")
                logger.info(f"   -DI: {current_minus_di:.1f}")
                logger.info(f"   Разница DI: {current_plus_di - current_minus_di:.1f}")
                
                return {
                    'adx': adx_values,
                    'plus_di': plus_di_values,
                    'minus_di': minus_di_values
                }
                
            except Exception as e:
                logger.error(f"Ошибка TA-Lib ADX: {e}")
                logger.info("Переходим на собственный алгоритм...")
        
        # Fallback на собственный алгоритм
        return TechnicalIndicators._calculate_adx_manual(highs, lows, closes, period)
    
    @staticmethod
    def _calculate_adx_manual(highs: List[float], lows: List[float], closes: List[float], period: int) -> Dict:
        """Собственная реализация ADX по алгоритму Уайлдера"""
        try:
            logger.info(f"🔧 Расчет ADX собственным алгоритмом")
            
            df = pd.DataFrame({
                'high': highs,
                'low': lows,
                'close': closes
            })
            
            # Шаг 1: True Range
            df['prev_close'] = df['close'].shift(1)
            df['hl'] = df['high'] - df['low']
            df['hc'] = abs(df['high'] - df['prev_close'])
            df['lc'] = abs(df['low'] - df['prev_close'])
            df['tr'] = df[['hl', 'hc', 'lc']].max(axis=1)
            
            # Шаг 2: Directional Movement
            df['high_diff'] = df['high'] - df['high'].shift(1)
            df['low_diff'] = df['low'].shift(1) - df['low']
            
            df['plus_dm'] = np.where(
                (df['high_diff'] > df['low_diff']) & (df['high_diff'] > 0),
                df['high_diff'], 0
            )
            
            df['minus_dm'] = np.where(
                (df['low_diff'] > df['high_diff']) & (df['low_diff'] > 0),
                df['low_diff'], 0
            )
            
            # Шаг 3: Сглаживание Уайлдера
            df['atr'] = TechnicalIndicators._wilder_smoothing(df['tr'], period)
            df['plus_dm_smooth'] = TechnicalIndicators._wilder_smoothing(df['plus_dm'], period)
            df['minus_dm_smooth'] = TechnicalIndicators._wilder_smoothing(df['minus_dm'], period)
            
            # Шаг 4: DI
            df['plus_di'] = 100 * (df['plus_dm_smooth'] / df['atr'])
            df['minus_di'] = 100 * (df['minus_dm_smooth'] / df['atr'])
            
            # Шаг 5: DX и ADX
            df['di_sum'] = df['plus_di'] + df['minus_di']
            df['di_diff'] = abs(df['plus_di'] - df['minus_di'])
            df['dx'] = np.where(df['di_sum'] != 0, 100 * (df['di_diff'] / df['di_sum']), 0)
            df['adx'] = TechnicalIndicators._wilder_smoothing(df['dx'], period)
            
            # Результаты
            adx_values = df['adx'].tolist()
            plus_di_values = df['plus_di'].tolist()
            minus_di_values = df['minus_di'].tolist()
            
            current_adx = adx_values[-1] if not pd.isna(adx_values[-1]) else np.nan
            current_plus_di = plus_di_values[-1] if not pd.isna(plus_di_values[-1]) else np.nan
            current_minus_di = minus_di_values[-1] if not pd.isna(minus_di_values[-1]) else np.nan
            
            logger.info(f"🎯 Собственный ADX результаты:")
            logger.info(f"   ADX: {current_adx:.1f}")
            logger.info(f"   +DI: {current_plus_di:.1f}")
            logger.info(f"   -DI: {current_minus_di:.1f}")
            
            return {
                'adx': adx_values,
                'plus_di': plus_di_values,
                'minus_di': minus_di_values
            }
            
        except Exception as e:
            logger.error(f"Ошибка собственного ADX: {e}")
            return {
                'adx': [np.nan] * len(highs), 
                'plus_di': [np.nan] * len(highs), 
                'minus_di': [np.nan] * len(highs)
            }
    
    @staticmethod
    def _wilder_smoothing(values: pd.Series, period: int) -> pd.Series:
        """Сглаживание Уайлдера"""
        result = pd.Series(index=values.index, dtype=float)
        result.iloc[:period-1] = np.nan
        
        if len(values) < period:
            return result
        
        # Первое значение
        first_avg = values.iloc[:period].mean()
        result.iloc[period-1] = first_avg
        
        # Остальные значения
        for i in range(period, len(values)):
            if not pd.isna(values.iloc[i]) and not pd.isna(result.iloc[i-1]):
                result.iloc[i] = (result.iloc[i-1] * (period - 1) + values.iloc[i]) / period
        
        return result
    
    @staticmethod
    def calculate_rsi(closes: List[float], period: int = 14) -> List[float]:
        """Расчет RSI"""
        if len(closes) < period + 1:
            return [np.nan] * len(closes)
        
        if TALIB_AVAILABLE:
            try:
                close_array = np.array(closes, dtype=float)
                rsi = talib.RSI(close_array, timeperiod=period)
                result = rsi.tolist()
                logger.info(f"RSI{period} (TA-Lib): последнее значение: {result[-1]:.1f}")
                return result
            except Exception as e:
                logger.error(f"Ошибка TA-Lib RSI: {e}")
        
        # Fallback
        try:
            deltas = pd.Series(closes).diff()
            gains = deltas.where(deltas > 0, 0.0)
            losses = -deltas.where(deltas < 0, 0.0)
            
            avg_gains = TechnicalIndicators._wilder_smoothing(gains, period)
            avg_losses = TechnicalIndicators._wilder_smoothing(losses, period)
            
            rs = avg_gains / avg_losses
            rsi = 100 - (100 / (1 + rs))
            
            result = rsi.tolist()
            logger.info(f"RSI{period} (manual): последнее значение: {result[-1]:.1f}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка расчета RSI: {e}")
            return [np.nan] * len(closes)
    
    @staticmethod
    def find_support_resistance_levels(highs: List[float], lows: List[float], period: int = 20) -> Dict:
        """Определение уровней поддержки и сопротивления"""
        try:
            if len(highs) < period:
                return {'support': None, 'resistance': None}
            
            recent_highs = highs[-period:]
            recent_lows = lows[-period:]
            
            # Простой алгоритм
            resistance = max(recent_highs)
            support = min(recent_lows)
            
            logger.info(f"Уровни: поддержка {support:.2f}, сопротивление {resistance:.2f}")
            
            return {'support': support, 'resistance': resistance}
            
        except Exception as e:
            logger.error(f"Ошибка расчета уровней: {e}")
            return {'support': None, 'resistance': None}
