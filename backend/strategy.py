import pandas as pd
import numpy as np
from typing import List, Tuple, Optional, Dict
from datetime import datetime, timedelta
import ta
from models import StrategySettings, MarketLevel, StrategySignal
import math

class Level:
    """Класс для представления уровня поддержки/сопротивления"""
    def __init__(self, time: datetime, price: float, strength: float, is_resistance: bool):
        self.time = time
        self.price = price
        self.strength = strength
        self.is_resistance = is_resistance

class Potential:
    """Класс для представления потенциала"""
    def __init__(self):
        self.v_level = 0.0
        self.v_trend = 0.0
        self.v_rsi = 0.0
        self.v_total = 0.0

class FinancialPotentialStrategy:
    """Основная логика стратегии Financial Potential"""
    
    def __init__(self, settings: StrategySettings):
        self.settings = settings
        self.levels: List[Level] = []
        self.last_build_time = None
        
    def calculate_indicators(self, df: pd.DataFrame) -> Dict:
        """Расчет технических индикаторов"""
        if len(df) < max(self.settings.atr_period, self.settings.rsi_period, self.settings.ema_period):
            return {}
        
        # ATR
        atr = ta.volatility.AverageTrueRange(
            high=df['high'], 
            low=df['low'], 
            close=df['close'], 
            window=self.settings.atr_period
        ).average_true_range()
        
        # RSI
        rsi = ta.momentum.RSIIndicator(
            close=df['close'], 
            window=self.settings.rsi_period
        ).rsi()
        
        # EMA
        ema = ta.trend.EMAIndicator(
            close=df['close'], 
            window=self.settings.ema_period
        ).ema_indicator()
        
        # Объемы
        volume_sma = df['volume'].rolling(window=20).mean()
        
        return {
            'atr': atr.iloc[-1] if not atr.empty else 0.0,
            'rsi': rsi.iloc[-1] if not rsi.empty else 50.0,
            'ema': ema.iloc[-1] if not ema.empty else df['close'].iloc[-1],
            'volume_ratio': df['volume'].iloc[-1] / volume_sma.iloc[-1] if not volume_sma.empty else 1.0,
            'avg_atr': atr.tail(50).mean() if len(atr) >= 50 else atr.mean()
        }
    
    def build_levels_zigzag(self, df: pd.DataFrame, depth: int = 12, deviation: float = 5.0) -> List[Level]:
        """Построение уровней методом ZigZag (упрощенная версия)"""
        if len(df) < 20:
            return []
        
        levels = []
        
        # Упрощенный алгоритм поиска локальных экстремумов
        highs = df['high'].values
        lows = df['low'].values
        times = df['datetime'].values
        
        # Поиск локальных максимумов и минимумов
        for i in range(depth, len(df) - depth):
            # Локальный максимум
            is_high = True
            for j in range(i - depth, i + depth + 1):
                if j != i and highs[j] >= highs[i]:
                    is_high = False
                    break
            
            if is_high:
                strength = 0.0
                # Вычисляем силу уровня как расстояние до ближайших экстремумов
                for j in range(max(0, i - 50), min(len(df), i + 50)):
                    if j != i:
                        strength = max(strength, abs(highs[i] - lows[j]))
                
                if strength >= self.settings.threshold_level:
                    levels.append(Level(
                        time=times[i],
                        price=highs[i],
                        strength=strength,
                        is_resistance=True
                    ))
            
            # Локальный минимум
            is_low = True
            for j in range(i - depth, i + depth + 1):
                if j != i and lows[j] <= lows[i]:
                    is_low = False
                    break
            
            if is_low:
                strength = 0.0
                # Вычисляем силу уровня
                for j in range(max(0, i - 50), min(len(df), i + 50)):
                    if j != i:
                        strength = max(strength, abs(lows[i] - highs[j]))
                
                if strength >= self.settings.threshold_level:
                    levels.append(Level(
                        time=times[i],
                        price=lows[i],
                        strength=strength,
                        is_resistance=False
                    ))
        
        return levels
    
    def build_levels_fractals(self, df: pd.DataFrame) -> List[Level]:
        """Построение уровней методом фракталов"""
        if len(df) < 10:
            return []
        
        levels = []
        period = 5  # Период для поиска фракталов
        
        for i in range(period, len(df) - period):
            # Фрактал вверх (сопротивление)
            is_up_fractal = True
            for j in range(i - period, i + period + 1):
                if j != i and df['high'].iloc[j] >= df['high'].iloc[i]:
                    is_up_fractal = False
                    break
            
            if is_up_fractal:
                strength = 0.0
                for j in range(max(0, i - 20), min(len(df), i + 20)):
                    if j != i:
                        strength = max(strength, abs(df['high'].iloc[i] - df['low'].iloc[j]))
                
                if strength >= self.settings.threshold_level:
                    levels.append(Level(
                        time=df['datetime'].iloc[i],
                        price=df['high'].iloc[i],
                        strength=strength,
                        is_resistance=True
                    ))
            
            # Фрактал вниз (поддержка)
            is_down_fractal = True
            for j in range(i - period, i + period + 1):
                if j != i and df['low'].iloc[j] <= df['low'].iloc[i]:
                    is_down_fractal = False
                    break
            
            if is_down_fractal:
                strength = 0.0
                for j in range(max(0, i - 20), min(len(df), i + 20)):
                    if j != i:
                        strength = max(strength, abs(df['low'].iloc[i] - df['high'].iloc[j]))
                
                if strength >= self.settings.threshold_level:
                    levels.append(Level(
                        time=df['datetime'].iloc[i],
                        price=df['low'].iloc[i],
                        strength=strength,
                        is_resistance=False
                    ))
        
        return levels
    
    def apply_age_decay(self, levels: List[Level], decay_days: float = 25.0) -> List[Level]:
        """Применение затухания силы уровней по времени"""
        now = datetime.now()
        lambda_decay = 1.0 / max(1.0, decay_days)
        
        for level in levels:
            age_days = (now - level.time).total_seconds() / 86400.0
            decay = math.exp(-lambda_decay * age_days)
            level.strength *= decay
        
        return levels
    
    def build_levels(self, df: pd.DataFrame):
        """Построение всех уровней"""
        if len(df) < 50:
            return
        
        all_levels = []
        
        # ZigZag уровни
        zigzag_levels = self.build_levels_zigzag(df)
        all_levels.extend(zigzag_levels)
        
        # Фрактальные уровни
        fractal_levels = self.build_levels_fractals(df)
        all_levels.extend(fractal_levels)
        
        # Применяем затухание по времени
        all_levels = self.apply_age_decay(all_levels, 25.0)
        
        # Сортируем по силе
        all_levels.sort(key=lambda x: x.strength, reverse=True)
        
        # Ограничиваем количество уровней
        max_levels = 60
        if len(all_levels) > max_levels:
            all_levels = all_levels[:max_levels]
        
        self.levels = all_levels
        self.last_build_time = datetime.now()
    
    def calculate_potential(self, price: float, h_fin: float, ema: float, rsi: float) -> Potential:
        """Расчет потенциала цены (портированная логика из MQ5)"""
        potential = Potential()
        
        if h_fin <= 0.0:
            h_fin = 0.0001  # Минимальное значение
        
        radius = self.settings.level_radius_factor * h_fin
        
        # Потенциал от уровней
        for level in self.levels:
            dist = abs(price - level.price)
            if dist <= radius:
                A = level.strength
                exponent = -(dist ** 2) / (2.0 * (h_fin ** 2))
                contrib = A * math.exp(exponent)
                
                if level.is_resistance:
                    if price < level.price:
                        potential.v_level += contrib
                    else:
                        potential.v_level += contrib * 0.15
                else:
                    if price > level.price:
                        potential.v_level -= contrib
                    else:
                        potential.v_level -= contrib * 0.15
        
        # Потенциал тренда
        potential.v_trend = -(price - ema)
        
        # Потенциал RSI
        potential.v_rsi = rsi - 50.0
        
        # Общий потенциал (улучшенные веса)
        w_level = 1.0
        w_trend = 0.05
        w_rsi = 0.03
        
        potential.v_total = (potential.v_level * w_level + 
                           potential.v_trend * w_trend + 
                           potential.v_rsi * w_rsi)
        
        return potential
    
    def check_filters(self, indicators: Dict, current_time: datetime = None) -> Dict[str, bool]:
        """Проверка всех фильтров"""
        if current_time is None:
            current_time = datetime.now()
        
        filters = {
            'volatility': True,
            'time': True,
            'volume': True
        }
        
        # Фильтр волатильности
        if self.settings.use_volatility_filter:
            current_atr = indicators.get('atr', 0)
            avg_atr = indicators.get('avg_atr', current_atr)
            if avg_atr > 0:
                filters['volatility'] = current_atr <= avg_atr * self.settings.max_atr_multiplier
        
        # Фильтр времени (избегаем новостные времена)
        hour = current_time.hour
        minute = current_time.minute
        time_int = hour * 100 + minute
        
        # Избегаем 9:50-10:10 и 17:00-17:15 (время новостей)
        if (950 <= time_int <= 1010) or (1700 <= time_int <= 1715):
            filters['time'] = False
        
        # Фильтр объемов
        if self.settings.use_volume_filter:
            volume_ratio = indicators.get('volume_ratio', 1.0)
            filters['volume'] = volume_ratio >= self.settings.min_volume_ratio
        
        return filters
    
    def generate_signal(self, df: pd.DataFrame, current_price: float) -> StrategySignal:
        """Генерация торгового сигнала"""
        if len(df) < 50:
            return self._no_signal(current_price)
        
        # Пересчитываем уровни если нужно
        if (self.last_build_time is None or 
            (datetime.now() - self.last_build_time).total_seconds() > 3600):  # 1 час
            self.build_levels(df)
        
        # Расчет индикаторов
        indicators = self.calculate_indicators(df)
        if not indicators:
            return self._no_signal(current_price)
        
        h_fin = indicators['atr']
        rsi = indicators['rsi']
        ema = indicators['ema']
        
        # Проверка фильтров
        filters = self.check_filters(indicators)
        if not all(filters.values()):
            return self._no_signal(current_price, f"Filters failed: {filters}")
        
        # Расчет потенциала для bid и ask (эмулируем спред)
        spread = h_fin * 0.001  # Примерный спред
        ask_price = current_price + spread
        bid_price = current_price - spread
        
        ask_potential = self.calculate_potential(ask_price, h_fin, ema, rsi)
        bid_potential = self.calculate_potential(bid_price, h_fin, ema, rsi)
        
        # Улучшенные сигналы
        buy_signal = (ask_potential.v_level < 0.0 and 
                     ask_potential.v_total < -self.settings.min_potential_strength * self.settings.buy_threshold_multiplier and
                     rsi < self.settings.buy_rsi_threshold)
        
        sell_signal = (bid_potential.v_level > 0.0 and 
                      bid_potential.v_total > self.settings.min_potential_strength * self.settings.sell_threshold_multiplier and
                      rsi > self.settings.sell_rsi_threshold)
        
        # Генерируем сигнал
        if buy_signal:
            direction = "BUY"
            confidence = min(1.0, abs(ask_potential.v_total) / 2.0)
            entry_price = ask_price if self.settings.mode == "BREAKOUT" else bid_price
            potential = ask_potential
        elif sell_signal:
            direction = "SELL"
            confidence = min(1.0, abs(bid_potential.v_total) / 2.0)
            entry_price = bid_price if self.settings.mode == "BREAKOUT" else ask_price
            potential = bid_potential
        else:
            return self._no_signal(current_price)
        
        # Расчет SL и TP
        if direction == "BUY":
            stop_loss = entry_price - self.settings.stop_loss_atr * h_fin
            take_profit = entry_price + self.settings.take_profit_atr * h_fin
        else:
            stop_loss = entry_price + self.settings.stop_loss_atr * h_fin
            take_profit = entry_price - self.settings.take_profit_atr * h_fin
        
        # Расчет размера лота
        lot_size = self._calculate_lot_size(abs(entry_price - stop_loss))
        
        return StrategySignal(
            symbol=self.settings.symbol,
            direction=direction,
            confidence=confidence,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            lot_size=lot_size,
            h_fin=h_fin,
            rsi=rsi,
            v_level=potential.v_level,
            v_trend=potential.v_trend,
            v_rsi=potential.v_rsi,
            v_total=potential.v_total,
            timestamp=datetime.now()
        )
    
    def _no_signal(self, current_price: float, reason: str = "No conditions met") -> StrategySignal:
        """Создание пустого сигнала"""
        return StrategySignal(
            symbol=self.settings.symbol,
            direction="NONE",
            confidence=0.0,
            entry_price=current_price,
            stop_loss=current_price,
            take_profit=current_price,
            lot_size=0.0,
            h_fin=0.0,
            rsi=50.0,
            v_level=0.0,
            v_trend=0.0,
            v_rsi=0.0,
            v_total=0.0,
            timestamp=datetime.now()
        )
    
    def _calculate_lot_size(self, sl_distance: float) -> float:
        """Расчет размера лота с учетом риска"""
        if not self.settings.dynamic_lot or sl_distance <= 0:
            return self.settings.base_lot
        
        # Предполагаем баланс 100,000 и стоимость пункта 1 рубль
        balance = 100000.0
        risk_money = balance * (self.settings.risk_percent / 100.0)
        
        # Упрощенный расчет (для реального использования нужно знать стоимость пункта)
        ticks = sl_distance * 100  # Предполагаем, что 1 пункт = 0.01
        if ticks <= 0:
            return self.settings.base_lot
        
        tick_value = 1.0  # 1 рубль за пункт
        loss_per_lot = ticks * tick_value
        
        if loss_per_lot <= 0:
            return self.settings.base_lot
        
        lot = risk_money / loss_per_lot
        lot = max(self.settings.min_lot, min(10.0, lot))  # Ограничиваем лот
        
        return round(lot, 2)
    
    def get_levels_for_chart(self) -> List[Dict]:
        """Получение уровней для отображения на графике"""
        levels_data = []
        for i, level in enumerate(self.levels[:20]):  # Показываем только топ-20
            levels_data.append({
                'price': level.price,
                'strength': level.strength,
                'is_resistance': level.is_resistance,
                'time': level.time.isoformat(),
                'color': 'red' if level.is_resistance else 'green'
            })
        return levels_data

# Тестирование стратегии
if __name__ == "__main__":
    from models import StrategySettings
    
    # Создаем тестовые настройки
    settings = StrategySettings(symbol="SBER")
    strategy = FinancialPotentialStrategy(settings)
    
    # Создаем тестовые данные
    dates = pd.date_range(start='2024-01-01', periods=100, freq='H')
    test_data = pd.DataFrame({
        'datetime': dates,
        'open': np.random.randn(100).cumsum() + 100,
        'high': np.random.randn(100).cumsum() + 101,
        'low': np.random.randn(100).cumsum() + 99,
        'close': np.random.randn(100).cumsum() + 100,
        'volume': np.random.randint(1000, 10000, 100)
    })
    
    # Тестируем стратегию
    signal = strategy.generate_signal(test_data, 100.0)
    print(f"Сигнал: {signal.direction}")
    print(f"Уверенность: {signal.confidence:.2f}")
    print(f"Цена входа: {signal.entry_price:.2f}")
    print(f"V_total: {signal.v_total:.4f}")
    
    levels = strategy.get_levels_for_chart()
    print(f"Найдено уровней: {len(levels)}")
