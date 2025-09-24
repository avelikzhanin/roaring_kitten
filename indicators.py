import logging
from typing import Dict, List, Any

import pandas as pd
import pandas_ta as ta

from config import DEFAULT_ADX_PERIOD, DEFAULT_EMA_PERIOD

logger = logging.getLogger(__name__)


class TechnicalIndicators:
    """Класс для расчета технических индикаторов"""
    
    @staticmethod
    def calculate_ema(df: pd.DataFrame, period: int = DEFAULT_EMA_PERIOD) -> pd.Series:
        """Расчет экспоненциальной скользящей средней"""
        return ta.ema(df['close'], length=period)
    
    @staticmethod
    def calculate_adx_standard(df: pd.DataFrame, period: int = DEFAULT_ADX_PERIOD) -> Dict[str, float]:
        """Стандартный расчет ADX через pandas-ta с RMA сглаживанием"""
        adx_data = ta.adx(df['high'], df['low'], df['close'], length=period, mamode='rma')
        
        return {
            'adx': adx_data['ADX_14'].iloc[-1] if not adx_data['ADX_14'].empty else 0,
            'di_plus': adx_data['DMP_14'].iloc[-1] if not adx_data['DMP_14'].empty else 0,
            'di_minus': adx_data['DMN_14'].iloc[-1] if not adx_data['DMN_14'].empty else 0
        }
    
    @staticmethod
    def calculate_adx_pinescript(df: pd.DataFrame, period: int = DEFAULT_ADX_PERIOD) -> Dict[str, float]:
        """
        Точная копия Pine Script кода TradingView:
        ADX = sma(DX, len) - простая скользящая средняя!
        """
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        
        # Расчет True Range
        tr = []
        dm_plus = []
        dm_minus = []
        
        for i in range(1, len(high)):
            # True Range (точно как в Pine Script)
            tr1 = high[i] - low[i]
            tr2 = abs(high[i] - close[i-1])
            tr3 = abs(low[i] - close[i-1])
            tr.append(max(tr1, tr2, tr3))
            
            # Directional Movement (точно как в Pine Script)
            up_move = high[i] - high[i-1]
            down_move = low[i-1] - low[i]
            
            dm_p = max(up_move, 0) if up_move > down_move else 0
            dm_m = max(down_move, 0) if down_move > up_move else 0
            
            dm_plus.append(dm_p)
            dm_minus.append(dm_m)
        
        # Wilder's Smoothing (точно как в Pine Script)
        def wilders_smoothing_exact(data, period):
            if not data:
                return []
            
            smoothed = []
            # Первое значение - простая средняя
            first_smooth = sum(data[:period]) / period if len(data) >= period else sum(data) / len(data)
            smoothed.append(first_smooth)
            
            # Остальные по формуле: new = previous - (previous/period) + current
            start_idx = period if len(data) >= period else len(data)
            for i in range(start_idx, len(data)):
                prev_smooth = smoothed[-1]
                new_smooth = prev_smooth - (prev_smooth / period) + data[i]
                smoothed.append(new_smooth)
            
            return smoothed
        
        # Сглаженные значения
        str_values = wilders_smoothing_exact(tr, period)
        sdm_plus = wilders_smoothing_exact(dm_plus, period)
        sdm_minus = wilders_smoothing_exact(dm_minus, period)
        
        if not str_values or not sdm_plus or not sdm_minus:
            return {'adx': 0, 'di_plus': 0, 'di_minus': 0}
        
        # DI+ и DI-
        di_plus = [(sdm_plus[i] / str_values[i]) * 100 if str_values[i] > 0 else 0 
                   for i in range(min(len(str_values), len(sdm_plus)))]
        di_minus = [(sdm_minus[i] / str_values[i]) * 100 if str_values[i] > 0 else 0
                    for i in range(min(len(str_values), len(sdm_minus)))]
        
        # DX
        dx = []
        for i in range(min(len(di_plus), len(di_minus))):
            if (di_plus[i] + di_minus[i]) > 0:
                dx_val = abs(di_plus[i] - di_minus[i]) / (di_plus[i] + di_minus[i]) * 100
                dx.append(dx_val)
            else:
                dx.append(0)
        
        # ADX - ПРОСТАЯ СКОЛЬЗЯЩАЯ СРЕДНЯЯ (как в Pine Script!)
        if len(dx) >= period:
            adx = sum(dx[-period:]) / period
        else:
            adx = sum(dx) / len(dx) if dx else 0
        
        return {
            'adx': adx,
            'di_plus': di_plus[-1] if di_plus else 0,
            'di_minus': di_minus[-1] if di_minus else 0
        }
    
    @classmethod
    def calculate_all_indicators(cls, candles_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Расчет всех индикаторов для свечных данных"""
        if len(candles_data) < 30:
            logger.error(f"Insufficient data: {len(candles_data)} candles (need at least 30)")
            return None
        
        # Преобразуем в DataFrame
        df = pd.DataFrame(candles_data)
        
        # Расчет EMA20
        df['ema20'] = cls.calculate_ema(df)
        
        # Два варианта расчета ADX
        adx_standard = cls.calculate_adx_standard(df)
        adx_pinescript = cls.calculate_adx_pinescript(df)
        
        last_row = df.iloc[-1]
        
        # Логируем сравнение
        logger.info("📊 СРАВНЕНИЕ ДВУХ ФОРМУЛ ADX:")
        logger.info(f"   🔧 pandas-ta (RMA): ADX={adx_standard['adx']:.2f}, DI+={adx_standard['di_plus']:.2f}, DI-={adx_standard['di_minus']:.2f}")
        logger.info(f"   📈 Pine Script: ADX={adx_pinescript['adx']:.2f}, DI+={adx_pinescript['di_plus']:.2f}, DI-={adx_pinescript['di_minus']:.2f}")
        
        return {
            'ema20': last_row['ema20'],
            'adx_standard': adx_standard['adx'],
            'di_plus_standard': adx_standard['di_plus'],
            'di_minus_standard': adx_standard['di_minus'],
            'adx_pinescript': adx_pinescript['adx'],
            'di_plus_pinescript': adx_pinescript['di_plus'],
            'di_minus_pinescript': adx_pinescript['di_minus']
        }
