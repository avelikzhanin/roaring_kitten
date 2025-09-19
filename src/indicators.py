import numpy as np
import pandas as pd
from typing import List, Dict, Tuple

class TechnicalIndicators:
    """Класс технических индикаторов с правильными настройками ADX как в Tinkoff"""
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """Расчет экспоненциальной скользящей средней (основной индикатор)"""
        if len(prices) < period:
            return [np.nan] * len(prices)
        
        # Используем pandas для стабильного расчета
        series = pd.Series(prices)
        ema = series.ewm(span=period, adjust=False).mean()
        return ema.tolist()
    
    @staticmethod
    def calculate_sma(prices: List[float], period: int) -> List[float]:
        """Простое скользящее среднее (альтернатива EMA)"""
        if len(prices) < period:
            return [np.nan] * len(prices)
        
        sma = []
        for i in range(len(prices)):
            if i < period - 1:
                sma.append(np.nan)
            else:
                avg = np.mean(prices[i - period + 1:i + 1])
                sma.append(avg)
        
        return sma
    
    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], 
                     di_period: int = 14, adx_smoothing: int = 20) -> Dict[str, List[float]]:
        """
        Расчет ADX с точными настройками как в Tinkoff терминале:
        - DI период: 14 (для расчета +DI и -DI)
        - ADX сглаживание: 20 (для финального ADX)
        """
        if len(highs) < max(di_period, adx_smoothing) + 10:
            # Возвращаем NaN если недостаточно данных
            return {
                'adx': [np.nan] * len(highs),
                'plus_di': [np.nan] * len(highs),
                'minus_di': [np.nan] * len(highs)
            }
        
        try:
            # Преобразуем в numpy arrays для удобства
            highs = np.array(highs)
            lows = np.array(lows)
            closes = np.array(closes)
            
            # 1. Рассчитываем True Range (TR)
            tr_list = []
            for i in range(1, len(highs)):
                high_low = highs[i] - lows[i]
                high_close_prev = abs(highs[i] - closes[i-1])
                low_close_prev = abs(lows[i] - closes[i-1])
                tr = max(high_low, high_close_prev, low_close_prev)
                tr_list.append(tr)
            
            # Добавляем NaN для первого элемента
            tr_array = np.array([np.nan] + tr_list)
            
            # 2. Рассчитываем Directional Movement (+DM и -DM)
            plus_dm = []
            minus_dm = []
            
            for i in range(1, len(highs)):
                move_up = highs[i] - highs[i-1]
                move_down = lows[i-1] - lows[i]
                
                if move_up > move_down and move_up > 0:
                    plus_dm.append(move_up)
                else:
                    plus_dm.append(0)
                
                if move_down > move_up and move_down > 0:
                    minus_dm.append(move_down)
                else:
                    minus_dm.append(0)
            
            # Добавляем NaN для первого элемента
            plus_dm = np.array([np.nan] + plus_dm)
            minus_dm = np.array([np.nan] + minus_dm)
            
            # 3. Сглаживание TR, +DM, -DM с периодом DI (14)
            tr_smooth = TechnicalIndicators._smooth_values(tr_array, di_period)
            plus_dm_smooth = TechnicalIndicators._smooth_values(plus_dm, di_period)
            minus_dm_smooth = TechnicalIndicators._smooth_values(minus_dm, di_period)
            
            # 4. Рассчитываем +DI и -DI
            plus_di = []
            minus_di = []
            
            for i in range(len(tr_smooth)):
                if np.isnan(tr_smooth[i]) or tr_smooth[i] == 0:
                    plus_di.append(np.nan)
                    minus_di.append(np.nan)
                else:
                    plus_di.append((plus_dm_smooth[i] / tr_smooth[i]) * 100)
                    minus_di.append((minus_dm_smooth[i] / tr_smooth[i]) * 100)
            
            plus_di = np.array(plus_di)
            minus_di = np.array(minus_di)
            
            # 5. Рассчитываем DX (Directional Index)
            dx = []
            for i in range(len(plus_di)):
                if np.isnan(plus_di[i]) or np.isnan(minus_di[i]):
                    dx.append(np.nan)
                else:
                    di_sum = plus_di[i] + minus_di[i]
                    if di_sum == 0:
                        dx.append(0)
                    else:
                        di_diff = abs(plus_di[i] - minus_di[i])
                        dx.append((di_diff / di_sum) * 100)
            
            dx = np.array(dx)
            
            # 6. Сглаживание DX для получения ADX с периодом сглаживания (20)
            adx = TechnicalIndicators._smooth_values(dx, adx_smoothing)
            
            return {
                'adx': adx.tolist(),
                'plus_di': plus_di.tolist(),
                'minus_di': minus_di.tolist()
            }
            
        except Exception as e:
            # В случае ошибки возвращаем NaN
            return {
                'adx': [np.nan] * len(highs),
                'plus_di': [np.nan] * len(highs),
                'minus_di': [np.nan] * len(highs)
            }
    
    @staticmethod
    def _smooth_values(values: np.ndarray, period: int) -> np.ndarray:
        """
        Сглаживание значений методом Wilder (как в ADX)
        Формула: Smoothed = (Previous_Smoothed * (period - 1) + Current_Value) / period
        """
        if len(values) < period:
            return np.full(len(values), np.nan)
        
        result = np.full(len(values), np.nan)
        
        # Находим первое не-NaN значение для начала расчета
        start_idx = period - 1
        while start_idx < len(values) and np.isnan(values[start_idx]):
            start_idx += 1
        
        if start_idx >= len(values):
            return result
        
        # Первое сглаженное значение = среднее первых period значений
        valid_values = []
        for i in range(start_idx - period + 1, start_idx + 1):
            if not np.isnan(values[i]):
                valid_values.append(values[i])
        
        if len(valid_values) >= period // 2:  # Требуем хотя бы половину значений
            result[start_idx] = np.mean(valid_values)
            
            # Последующие значения по формуле Wilder
            for i in range(start_idx + 1, len(values)):
                if not np.isnan(values[i]) and not np.isnan(result[i-1]):
                    result[i] = (result[i-1] * (period - 1) + values[i]) / period
        
        return result
    
    @staticmethod
    def calculate_price_change(prices: List[float], periods: int = 1) -> List[float]:
        """Расчёт изменения цены за N периодов в процентах"""
        if len(prices) < periods + 1:
            return [np.nan] * len(prices)
        
        changes = []
        for i in range(len(prices)):
            if i < periods:
                changes.append(np.nan)
            else:
                old_price = prices[i - periods]
                new_price = prices[i]
                if old_price > 0:
                    change = ((new_price - old_price) / old_price) * 100
                    changes.append(change)
                else:
                    changes.append(np.nan)
        
        return changes
    
    @staticmethod
    def calculate_volatility(prices: List[float], period: int = 20) -> List[float]:
        """Расчёт волатильности (стандартное отклонение изменений)"""
        if len(prices) < period + 1:
            return [np.nan] * len(prices)
        
        # Сначала рассчитываем процентные изменения
        pct_changes = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                pct_change = ((prices[i] - prices[i-1]) / prices[i-1]) * 100
                pct_changes.append(pct_change)
            else:
                pct_changes.append(0)
        
        # Теперь считаем скользящее стандартное отклонение
        volatility = [np.nan]  # Первое значение всегда NaN
        
        for i in range(len(pct_changes)):
            if i < period - 1:
                volatility.append(np.nan)
            else:
                window = pct_changes[i - period + 1:i + 1]
                vol = np.std(window) if window else np.nan
                volatility.append(vol)
        
        return volatility
    
    @staticmethod
    def analyze_volume_trend(volumes: List[int], short_period: int = 5, long_period: int = 20) -> Dict:
        """Анализ тренда объёмов"""
        if len(volumes) < long_period:
            return {
                'trend': 'unknown',
                'ratio': 1.0,
                'current_vs_avg': 1.0
            }
        
        try:
            # Средние объёмы
            recent_avg = np.mean(volumes[-short_period:])
            long_avg = np.mean(volumes[-long_period:])
            current_volume = volumes[-1]
            
            # Определяем тренд
            ratio = recent_avg / long_avg if long_avg > 0 else 1.0
            
            if ratio > 1.2:
                trend = 'increasing'
            elif ratio < 0.8:
                trend = 'decreasing'
            else:
                trend = 'stable'
            
            # Текущий объём vs средний
            current_vs_avg = current_volume / long_avg if long_avg > 0 else 1.0
            
            return {
                'trend': trend,
                'ratio': round(ratio, 2),
                'current_vs_avg': round(current_vs_avg, 2),
                'recent_avg': int(recent_avg),
                'long_avg': int(long_avg)
            }
            
        except Exception:
            return {
                'trend': 'unknown',
                'ratio': 1.0,
                'current_vs_avg': 1.0
            }
    
    @staticmethod
    def find_support_resistance(highs: List[float], lows: List[float], 
                               window: int = 5, min_strength: int = 2) -> Dict:
        """Поиск уровней поддержки и сопротивления"""
        if len(highs) < window * 2 + 1 or len(lows) < window * 2 + 1:
            return {'resistances': [], 'supports': []}
        
        try:
            resistances = []
            supports = []
            
            # Поиск локальных максимумов (сопротивления)
            for i in range(window, len(highs) - window):
                is_peak = True
                current_high = highs[i]
                
                # Проверяем, что текущий максимум выше соседних
                for j in range(i - window, i + window + 1):
                    if j != i and highs[j] >= current_high:
                        is_peak = False
                        break
                
                if is_peak:
                    resistances.append(current_high)
            
            # Поиск локальных минимумов (поддержка)
            for i in range(window, len(lows) - window):
                is_trough = True
                current_low = lows[i]
                
                # Проверяем, что текущий минимум ниже соседних
                for j in range(i - window, i + window + 1):
                    if j != i and lows[j] <= current_low:
                        is_trough = False
                        break
                
                if is_trough:
                    supports.append(current_low)
            
            # Убираем дубликаты и сортируем
            resistances = sorted(list(set([round(r, 2) for r in resistances])))
            supports = sorted(list(set([round(s, 2) for s in supports])), reverse=True)
            
            return {
                'resistances': resistances,
                'supports': supports
            }
            
        except Exception:
            return {'resistances': [], 'supports': []}
    
    @staticmethod
    def calculate_price_position(current_price: float, highs: List[float], 
                               lows: List[float], period: int = 50) -> Dict:
        """Определение позиции цены в диапазоне"""
        if len(highs) < period or len(lows) < period:
            return {'position': 0.5, 'status': 'unknown'}
        
        try:
            # Берём последние N периодов
            recent_highs = highs[-period:]
            recent_lows = lows[-period:]
            
            highest = max(recent_highs)
            lowest = min(recent_lows)
            
            if highest == lowest:
                return {'position': 0.5, 'status': 'flat'}
            
            # Позиция в диапазоне (0 = на минимуме, 1 = на максимуме)
            position = (current_price - lowest) / (highest - lowest)
            
            # Определяем статус
            if position >= 0.8:
                status = 'near_high'
            elif position <= 0.2:
                status = 'near_low'
            elif 0.4 <= position <= 0.6:
                status = 'middle'
            elif position > 0.6:
                status = 'upper_range'
            else:
                status = 'lower_range'
            
            return {
                'position': round(position, 2),
                'status': status,
                'range_high': highest,
                'range_low': lowest,
                'range_size': round(((highest - lowest) / lowest) * 100, 2)  # Размер диапазона в %
            }
            
        except Exception:
            return {'position': 0.5, 'status': 'unknown'}
    
    @staticmethod
    def detect_candle_patterns(candles_data: List[Dict], pattern_length: int = 5) -> List[str]:
        """Простое определение свечных паттернов"""
        if len(candles_data) < pattern_length:
            return []
        
        patterns = []
        recent_candles = candles_data[-pattern_length:]
        
        try:
            # Анализируем последние свечи
            green_candles = sum(1 for c in recent_candles if c['close'] > c['open'])
            red_candles = sum(1 for c in recent_candles if c['close'] < c['open'])
            
            # Простые паттерны
            if green_candles >= 4:
                patterns.append('strong_uptrend')
            elif green_candles >= 3:
                patterns.append('uptrend')
            elif red_candles >= 4:
                patterns.append('strong_downtrend')
            elif red_candles >= 3:
                patterns.append('downtrend')
            
            # Проверяем последние 3 свечи на пробой
            if len(recent_candles) >= 3:
                last_3 = recent_candles[-3:]
                highs = [c['high'] for c in last_3]
                
                if all(highs[i] < highs[i+1] for i in range(len(highs)-1)):
                    patterns.append('ascending_highs')
            
            # Высокие объёмы
            if len(recent_candles) >= 2:
                last_volume = recent_candles[-1]['volume']
                prev_volume = recent_candles[-2]['volume'] 
                
                if last_volume > prev_volume * 1.5:
                    patterns.append('volume_surge')
            
            return patterns
            
        except Exception:
            return []
    
    @staticmethod
    def get_trend_strength(prices: List[float], period: int = 20) -> Dict:
        """Простая оценка силы тренда БЕЗ ADX"""
        if len(prices) < period:
            return {'strength': 'unknown', 'direction': 'sideways', 'score': 0}
        
        try:
            recent_prices = prices[-period:]
            first_price = recent_prices[0]
            last_price = recent_prices[-1]
            
            # Общее изменение
            total_change = ((last_price - first_price) / first_price) * 100
            
            # Считаем количество растущих периодов
            up_periods = 0
            for i in range(1, len(recent_prices)):
                if recent_prices[i] > recent_prices[i-1]:
                    up_periods += 1
            
            up_ratio = up_periods / (len(recent_prices) - 1)
            
            # Определяем направление
            if total_change > 2:
                direction = 'uptrend'
            elif total_change < -2:
                direction = 'downtrend'
            else:
                direction = 'sideways'
            
            # Оценка силы БЕЗ ADX
            strength_score = abs(total_change) + (up_ratio * 10 if total_change > 0 else (1-up_ratio) * 10)
            
            if strength_score > 8:
                strength = 'strong'
            elif strength_score > 4:
                strength = 'moderate'
            elif strength_score > 1:
                strength = 'weak'
            else:
                strength = 'very_weak'
            
            return {
                'strength': strength,
                'direction': direction,
                'score': round(strength_score, 1),
                'total_change_pct': round(total_change, 2),
                'up_periods_ratio': round(up_ratio, 2)
            }
            
        except Exception:
            return {'strength': 'unknown', 'direction': 'sideways', 'score': 0}



# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def quick_market_summary(candles_data: List[Dict]) -> Dict:
    """Быстрая сводка по рынку для GPT с ПРАВИЛЬНЫМИ ADX"""
    if not candles_data:
        return {}
    
    try:
        prices = [c['close'] for c in candles_data]
        highs = [c['high'] for c in candles_data]
        lows = [c['low'] for c in candles_data]
        volumes = [c['volume'] for c in candles_data]
        
        current_price = prices[-1]
        
        # EMA20
        ema20 = TechnicalIndicators.calculate_ema(prices, 20)
        current_ema20 = ema20[-1] if not np.isnan(ema20[-1]) else current_price
        
        # ПРАВИЛЬНЫЙ ADX с настройками как в Tinkoff: DI=14, ADX сглаживание=20
        adx_data = TechnicalIndicators.calculate_adx(highs, lows, prices, di_period=14, adx_smoothing=20)
        current_adx = adx_data['adx'][-1] if not np.isnan(adx_data['adx'][-1]) else 0
        current_plus_di = adx_data['plus_di'][-1] if not np.isnan(adx_data['plus_di'][-1]) else 0
        current_minus_di = adx_data['minus_di'][-1] if not np.isnan(adx_data['minus_di'][-1]) else 0
        
        # Анализ без ADX (для обратной совместимости)
        volume_analysis = TechnicalIndicators.analyze_volume_trend(volumes)
        trend_analysis = TechnicalIndicators.get_trend_strength(prices)
        price_position = TechnicalIndicators.calculate_price_position(current_price, highs, lows)
        patterns = TechnicalIndicators.detect_candle_patterns(candles_data)
        
        return {
            'current_price': current_price,
            'ema20': current_ema20,
            'price_above_ema': current_price > current_ema20,
            # ТОЧНЫЕ ADX значения как в терминале
            'adx': current_adx,
            'plus_di': current_plus_di,
            'minus_di': current_minus_di,
            'adx_calculated': not np.isnan(current_adx),
            # Дополнительный анализ
            'volume_analysis': volume_analysis,
            'trend_analysis': trend_analysis,
            'price_position': price_position,
            'patterns': patterns,
            'data_quality': 'good' if len(candles_data) > 50 else 'limited'
        }
        
    except Exception as e:
        return {'error': str(e)}
