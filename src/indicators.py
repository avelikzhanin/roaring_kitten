import numpy as np
import pandas as pd
import pandas_ta as ta
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

class TechnicalIndicators:
    """Класс для расчета технических индикаторов с использованием проверенной библиотеки pandas-ta"""
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """Расчет экспоненциальной скользящей средней"""
        if len(prices) < period:
            return [np.nan] * len(prices)
        
        try:
            df = pd.DataFrame({'close': prices})
            ema = ta.ema(df['close'], length=period)
            result = ema.fillna(method='bfill').tolist()
            
            logger.info(f"EMA{period} calculated: последние 5 значений: {result[-5:]}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка расчета EMA: {e}")
            # Fallback на старый метод
            series = pd.Series(prices)
            ema = series.ewm(span=period, adjust=False).mean()
            return ema.tolist()
    
    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """
        ИСПРАВЛЕННЫЙ расчет ADX, +DI, -DI с использованием pandas-ta
        Это должно дать результаты идентичные TradingView
        """
        if len(highs) < period * 2:
            logger.warning(f"Недостаточно данных для ADX: {len(highs)} < {period * 2}")
            return {
                'adx': [np.nan] * len(highs), 
                'plus_di': [np.nan] * len(highs), 
                'minus_di': [np.nan] * len(highs)
            }
        
        try:
            # Создаем DataFrame
            df = pd.DataFrame({
                'high': highs,
                'low': lows,
                'close': closes
            })
            
            logger.info(f"Расчет ADX для {len(df)} свечей, период {period}")
            logger.info(f"Последние 5 свечей: {df.tail().to_dict('records')}")
            
            # Используем pandas-ta для расчета ADX
            adx_data = ta.adx(
                high=df['high'], 
                low=df['low'], 
                close=df['close'], 
                length=period
            )
            
            if adx_data is None or adx_data.empty:
                logger.error("pandas-ta вернул пустой результат для ADX")
                return {
                    'adx': [np.nan] * len(highs), 
                    'plus_di': [np.nan] * len(highs), 
                    'minus_di': [np.nan] * len(highs)
                }
            
            # Извлекаем колонки (pandas-ta использует специальные имена)
            adx_col = f'ADX_{period}'
            plus_di_col = f'DMP_{period}'  # Directional Movement Positive
            minus_di_col = f'DMN_{period}'  # Directional Movement Negative
            
            # Проверяем что колонки существуют
            available_cols = list(adx_data.columns)
            logger.info(f"Доступные колонки ADX: {available_cols}")
            
            if adx_col not in available_cols:
                logger.error(f"Колонка {adx_col} не найдена в результате pandas-ta")
                return {
                    'adx': [np.nan] * len(highs), 
                    'plus_di': [np.nan] * len(highs), 
                    'minus_di': [np.nan] * len(highs)
                }
            
            # Заполняем NaN значениями и конвертируем в списки
            adx_values = adx_data[adx_col].fillna(method='bfill').tolist()
            plus_di_values = adx_data[plus_di_col].fillna(method='bfill').tolist()
            minus_di_values = adx_data[minus_di_col].fillna(method='bfill').tolist()
            
            # Логируем результаты для отладки
            logger.info(f"ADX рассчитан успешно:")
            logger.info(f"  Последние ADX: {adx_values[-5:]}")
            logger.info(f"  Последние +DI: {plus_di_values[-5:]}")
            logger.info(f"  Последние -DI: {minus_di_values[-5:]}")
            
            # Текущие значения (последняя свеча)
            current_adx = adx_values[-1] if not pd.isna(adx_values[-1]) else np.nan
            current_plus_di = plus_di_values[-1] if not pd.isna(plus_di_values[-1]) else np.nan
            current_minus_di = minus_di_values[-1] if not pd.isna(minus_di_values[-1]) else np.nan
            
            logger.info(f"🔍 ТЕКУЩИЕ ЗНАЧЕНИЯ ИНДИКАТОРОВ:")
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
            logger.error(f"Ошибка расчета ADX через pandas-ta: {e}")
            logger.error(f"Тип ошибки: {type(e).__name__}")
            
            # Возвращаем пустые значения при ошибке
            return {
                'adx': [np.nan] * len(highs), 
                'plus_di': [np.nan] * len(highs), 
                'minus_di': [np.nan] * len(highs)
            }
    
    @staticmethod
    def calculate_rsi(closes: List[float], period: int = 14) -> List[float]:
        """Расчет RSI с использованием pandas-ta"""
        if len(closes) < period + 1:
            return [np.nan] * len(closes)
        
        try:
            df = pd.DataFrame({'close': closes})
            rsi = ta.rsi(df['close'], length=period)
            result = rsi.fillna(method='bfill').tolist()
            
            logger.info(f"RSI{period} calculated: последнее значение: {result[-1]:.1f}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка расчета RSI: {e}")
            return [np.nan] * len(closes)
    
    @staticmethod
    def find_support_resistance_levels(highs: List[float], lows: List[float], period: int = 20) -> Dict:
        """Простое определение уровней поддержки и сопротивления"""
        try:
            if len(highs) < period:
                return {'support': None, 'resistance': None}
            
            # Берем последние N периодов
            recent_highs = highs[-period:]
            recent_lows = lows[-period:]
            
            # Находим локальные экстремумы
            resistance = max(recent_highs)
            support = min(recent_lows)
            
            logger.info(f"Уровни: поддержка {support:.2f}, сопротивление {resistance:.2f}")
            
            return {
                'support': support,
                'resistance': resistance
            }
            
        except Exception as e:
            logger.error(f"Ошибка расчета уровней: {e}")
            return {'support': None, 'resistance': None}
    
    @staticmethod
    def analyze_volume_trend(volumes: List[int], period: int = 20) -> Dict:
        """Анализ тренда объемов"""
        try:
            if len(volumes) < period:
                return {'volume_ratio': 1.0, 'volume_trend': 'unknown'}
            
            recent_volume = np.mean(volumes[-5:])  # Последние 5 периодов
            avg_volume = np.mean(volumes[-period:])  # Средние за период
            
            volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1.0
            
            if volume_ratio > 1.5:
                volume_trend = 'high'
            elif volume_ratio < 0.7:
                volume_trend = 'low'
            else:
                volume_trend = 'normal'
            
            logger.info(f"Объемы: соотношение {volume_ratio:.1f}x, тренд {volume_trend}")
            
            return {
                'volume_ratio': volume_ratio,
                'volume_trend': volume_trend
            }
            
        except Exception as e:
            logger.error(f"Ошибка анализа объемов: {e}")
            return {'volume_ratio': 1.0, 'volume_trend': 'unknown'}
