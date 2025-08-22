#!/usr/bin/env python3
"""
Улучшенный оптимизатор стратегии SBER с фокусом на Trailing Stop
Тестирует различные варианты trailing stop для максимизации прибыли
"""

import asyncio
import logging
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

# Импорты Tinkoff API
from tinkoff.invest import Client, RequestError, CandleInterval, HistoricCandle
from tinkoff.invest.utils import now

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class TrailingStopType(Enum):
    """Типы trailing stop"""
    FIXED = "fixed"                    # Фиксированный %
    ADX_ADAPTIVE = "adx_adaptive"      # Адаптивный под силу тренда
    PROFIT_STEPPED = "profit_stepped"  # Ступенчатый в зависимости от прибыли
    DYNAMIC = "dynamic"                # Динамический на основе волатильности

@dataclass
class TrailingStopConfig:
    """Конфигурация Trailing Stop"""
    type: TrailingStopType
    base_percent: float = 1.0
    
    # Для ADX адаптивного
    adx_strong_threshold: float = 35.0
    adx_weak_threshold: float = 25.0
    strong_trend_percent: float = 1.5
    weak_trend_percent: float = 0.7
    
    # Для ступенчатого
    profit_levels: List[Tuple[float, float]] = None  # [(profit_threshold, trailing_percent)]
    
    # Для динамического
    atr_multiplier: float = 2.0
    
    def __post_init__(self):
        if self.profit_levels is None:
            self.profit_levels = [
                (0.5, 0.5),   # При прибыли 0.5%+ → trailing 0.5%
                (1.0, 0.8),   # При прибыли 1.0%+ → trailing 0.8%
                (2.0, 1.2),   # При прибыли 2.0%+ → trailing 1.2%
                (3.0, 1.8),   # При прибыли 3.0%+ → trailing 1.8%
            ]

@dataclass
class OptimizedParams:
    """Параметры оптимизированной стратегии"""
    ema_period: int = 20
    adx_threshold: float = 23
    di_diff_threshold: float = 5
    volume_multiplier: float = 1.47
    
    # Управление рисками
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    
    # 🎯 Новый Trailing Stop
    trailing_config: Optional[TrailingStopConfig] = None
    
    # Дополнительные фильтры
    rsi_period: Optional[int] = None
    rsi_overbought: Optional[float] = None
    momentum_periods: Optional[int] = None
    
    # Временные фильтры
    avoid_lunch_time: bool = False
    trading_hours_start: int = 10
    trading_hours_end: int = 18
    
    def __str__(self):
        base = f"EMA{self.ema_period}_ADX{self.adx_threshold}_VOL{self.volume_multiplier}"
        
        filters = []
        if self.stop_loss_pct:
            filters.append(f"SL{self.stop_loss_pct}")
        if self.take_profit_pct:
            filters.append(f"TP{self.take_profit_pct}")
        if self.trailing_config:
            filters.append(f"TS_{self.trailing_config.type.value}_{self.trailing_config.base_percent}")
        if self.rsi_period:
            filters.append(f"RSI{self.rsi_period}")
        if self.avoid_lunch_time:
            filters.append("NoLunch")
            
        if filters:
            return f"{base}_{'_'.join(filters)}"
        return base

@dataclass 
class OptimizationResult:
    """Результат оптимизации"""
    params: OptimizedParams
    total_return: float
    win_rate: float
    total_trades: int
    profitable_trades: int
    avg_return_per_trade: float
    max_drawdown: float
    avg_trade_duration_hours: float
    sharpe_ratio: float
    max_consecutive_losses: int
    
    # 🎯 Дополнительные метрики для trailing stop
    max_profit_per_trade: float = 0
    avg_profit_on_winners: float = 0
    trailing_stop_exits: int = 0
    
    def overall_score(self) -> float:
        """Улучшенная комплексная оценка стратегии"""
        return_score = min(self.total_return / 10, 15)
        winrate_score = self.win_rate / 8
        trades_score = min(self.total_trades / 5, 5)
        drawdown_penalty = max(0, abs(self.max_drawdown) / 2)
        
        # 🎯 Бонус за крупные прибыли
        big_profit_bonus = min(self.max_profit_per_trade / 2, 3)
        
        return (return_score * 0.4 + 
                winrate_score * 0.25 + 
                trades_score * 0.15 + 
                big_profit_bonus * 0.2 - 
                drawdown_penalty * 0.1)

class DataProvider:
    """Провайдер данных Tinkoff"""
    
    def __init__(self, token: str):
        self.token = token
        self.figi = "BBG004730N88"  # SBER
    
    async def get_candles(self, hours: int = 300) -> List[HistoricCandle]:
        """Получение свечных данных"""
        try:
            with Client(self.token) as client:
                to_time = now()
                from_time = to_time - timedelta(hours=hours)
                
                logger.info(f"📡 Запрос данных SBER с {from_time.strftime('%d.%m %H:%M')} по {to_time.strftime('%d.%m %H:%M')}")
                
                response = client.market_data.get_candles(
                    figi=self.figi,
                    from_=from_time,
                    to=to_time,
                    interval=CandleInterval.CANDLE_INTERVAL_HOUR
                )
                
                if response.candles:
                    logger.info(f"✅ Получено {len(response.candles)} свечей")
                    return response.candles
                else:
                    logger.warning("⚠️ Пустой ответ от API")
                    return []
                    
        except Exception as e:
            logger.error(f"❌ Ошибка получения данных: {e}")
            return []
    
    def candles_to_dataframe(self, candles: List[HistoricCandle]) -> pd.DataFrame:
        """Преобразование в DataFrame"""
        if not candles:
            return pd.DataFrame()
        
        data = []
        for candle in candles:
            try:
                data.append({
                    'timestamp': candle.time,
                    'open': self.quotation_to_decimal(candle.open),
                    'high': self.quotation_to_decimal(candle.high),
                    'low': self.quotation_to_decimal(candle.low),
                    'close': self.quotation_to_decimal(candle.close),
                    'volume': candle.volume
                })
            except Exception as e:
                continue
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df = df.sort_values('timestamp').reset_index(drop=True)
        df = df.drop_duplicates(subset=['timestamp'], keep='last')
        
        return df
    
    @staticmethod
    def quotation_to_decimal(quotation) -> float:
        """Преобразование quotation в decimal"""
        try:
            return float(quotation.units + quotation.nano / 1e9)
        except (AttributeError, TypeError):
            return 0.0

class TechnicalIndicators:
    """Технические индикаторы"""
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """EMA"""
        if len(prices) < period:
            return [np.nan] * len(prices)
        
        series = pd.Series(prices)
        ema = series.ewm(span=period, adjust=False).mean()
        return ema.tolist()
    
    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
        """RSI индикатор"""
        if len(prices) < period + 1:
            return [np.nan] * len(prices)
        
        df = pd.DataFrame({'price': prices})
        df['change'] = df['price'].diff()
        df['gain'] = df['change'].where(df['change'] > 0, 0)
        df['loss'] = (-df['change']).where(df['change'] < 0, 0)
        
        df['avg_gain'] = df['gain'].ewm(alpha=1/period, adjust=False).mean()
        df['avg_loss'] = df['loss'].ewm(alpha=1/period, adjust=False).mean()
        
        df['rs'] = df['avg_gain'] / df['avg_loss']
        df['rsi'] = 100 - (100 / (1 + df['rs']))
        
        return df['rsi'].fillna(np.nan).tolist()

    @staticmethod
    def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
        """ATR для динамического trailing stop"""
        if len(highs) < period + 1:
            return [np.nan] * len(highs)
        
        df = pd.DataFrame({
            'high': highs,
            'low': lows,
            'close': closes
        })
        
        df['prev_close'] = df['close'].shift(1)
        df['hl'] = df['high'] - df['low']
        df['hc'] = abs(df['high'] - df['prev_close'])
        df['lc'] = abs(df['low'] - df['prev_close'])
        df['tr'] = df[['hl', 'hc', 'lc']].max(axis=1)
        
        df['atr'] = df['tr'].rolling(window=period).mean()
        
        return df['atr'].fillna(np.nan).tolist()
    
    @staticmethod
    def wilder_smoothing(values: pd.Series, period: int) -> pd.Series:
        """Сглаживание Уайлдера"""
        result = pd.Series(index=values.index, dtype=float)
        first_avg = values.iloc[:period].mean()
        result.iloc[period-1] = first_avg
        
        for i in range(period, len(values)):
            result.iloc[i] = (result.iloc[i-1] * (period - 1) + values.iloc[i]) / period
        
        return result
    
    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """ADX расчет"""
        if len(highs) < period * 2:
            return {
                'adx': [np.nan] * len(highs), 
                'plus_di': [np.nan] * len(highs), 
                'minus_di': [np.nan] * len(highs)
            }
        
        df = pd.DataFrame({
            'high': highs,
            'low': lows,
            'close': closes
        })
        
        # True Range
        df['prev_close'] = df['close'].shift(1)
        df['hl'] = df['high'] - df['low']
        df['hc'] = abs(df['high'] - df['prev_close'])
        df['lc'] = abs(df['low'] - df['prev_close'])
        df['tr'] = df[['hl', 'hc', 'lc']].max(axis=1)
        
        # Directional Movement
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
        
        # Сглаживание
        df['atr'] = TechnicalIndicators.wilder_smoothing(df['tr'], period)
        df['plus_dm_smooth'] = TechnicalIndicators.wilder_smoothing(df['plus_dm'], period)
        df['minus_dm_smooth'] = TechnicalIndicators.wilder_smoothing(df['minus_dm'], period)
        
        # DI
        df['plus_di'] = (df['plus_dm_smooth'] / df['atr']) * 100
        df['minus_di'] = (df['minus_dm_smooth'] / df['atr']) * 100
        
        # DX и ADX
        df['di_sum'] = df['plus_di'] + df['minus_di']
        df['di_diff'] = abs(df['plus_di'] - df['minus_di'])
        df['dx'] = np.where(df['di_sum'] != 0, (df['di_diff'] / df['di_sum']) * 100, 0)
        df['adx'] = TechnicalIndicators.wilder_smoothing(df['dx'], period)
        
        return {
            'adx': df['adx'].fillna(np.nan).tolist(),
            'plus_di': df['plus_di'].fillna(np.nan).tolist(),
            'minus_di': df['minus_di'].fillna(np.nan).tolist()
        }

class TrailingStopManager:
    """Менеджер Trailing Stop с различными стратегиями"""
    
    def __init__(self, config: TrailingStopConfig):
        self.config = config
    
    def calculate_trailing_level(self, 
                               current_trade: Dict,
                               current_price: float,
                               current_adx: float = None,
                               current_atr: float = None) -> float:
        """Расчет уровня trailing stop"""
        
        entry_price = current_trade['entry_price']
        highest_price = current_trade['highest_price']
        current_profit = ((current_price - entry_price) / entry_price) * 100
        
        if self.config.type == TrailingStopType.FIXED:
            return highest_price * (1 - self.config.base_percent/100)
        
        elif self.config.type == TrailingStopType.ADX_ADAPTIVE:
            if current_adx is None:
                return highest_price * (1 - self.config.base_percent/100)
            
            if current_adx >= self.config.adx_strong_threshold:
                # Сильный тренд - даем больше свободы
                trailing_pct = self.config.strong_trend_percent
            elif current_adx <= self.config.adx_weak_threshold:
                # Слабый тренд - жестче держим
                trailing_pct = self.config.weak_trend_percent
            else:
                # Промежуточное значение
                ratio = (current_adx - self.config.adx_weak_threshold) / (
                    self.config.adx_strong_threshold - self.config.adx_weak_threshold)
                trailing_pct = (self.config.weak_trend_percent + 
                              (self.config.strong_trend_percent - self.config.weak_trend_percent) * ratio)
            
            return highest_price * (1 - trailing_pct/100)
        
        elif self.config.type == TrailingStopType.PROFIT_STEPPED:
            trailing_pct = self.config.base_percent
            
            # Находим подходящий уровень
            for profit_threshold, step_trailing_pct in sorted(self.config.profit_levels, reverse=True):
                if current_profit >= profit_threshold:
                    trailing_pct = step_trailing_pct
                    break
            
            return highest_price * (1 - trailing_pct/100)
        
        elif self.config.type == TrailingStopType.DYNAMIC:
            if current_atr is None:
                return highest_price * (1 - self.config.base_percent/100)
            
            # ATR-based trailing stop
            atr_distance = current_atr * self.config.atr_multiplier
            return highest_price - atr_distance
        
        else:
            return highest_price * (1 - self.config.base_percent/100)

class EnhancedTrailingOptimizer:
    """Оптимизатор с фокусом на Trailing Stop"""
    
    def __init__(self, tinkoff_token: str):
        self.data_provider = DataProvider(tinkoff_token)
    
    async def run_optimization(self, test_days: int = 90) -> List[OptimizationResult]:
        """Запуск оптимизации с фокусом на trailing stop"""
        logger.info(f"🚀 Запуск оптимизации Trailing Stop для SBER за {test_days} дней...")
        
        # Получаем данные
        hours_needed = test_days * 24 + 200
        
        try:
            candles = await self.data_provider.get_candles(hours=hours_needed)
            
            if len(candles) < 100:
                logger.error("❌ Недостаточно данных для оптимизации")
                return []
                
            df = self.data_provider.candles_to_dataframe(candles)
            
            if df.empty:
                logger.error("❌ Ошибка преобразования данных")
                return []
            
            # Генерируем параметры с фокусом на trailing stop
            parameter_combinations = self._generate_trailing_combinations()
            
            logger.info(f"🧪 Будем тестировать {len(parameter_combinations)} trailing stop комбинаций...")
            
            results = []
            for i, params in enumerate(parameter_combinations, 1):
                try:
                    if i % 5 == 0:
                        logger.info(f"⏳ Прогресс: {i}/{len(parameter_combinations)} ({i/len(parameter_combinations)*100:.1f}%)")
                    
                    result = await self._test_strategy_params(df, params, test_days)
                    if result:
                        results.append(result)
                        
                except Exception as e:
                    continue
            
            results.sort(key=lambda x: x.overall_score(), reverse=True)
            
            logger.info(f"✅ Оптимизация завершена! Найдено {len(results)} результатов")
            return results
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка оптимизации: {e}")
            return []
    
    def _generate_trailing_combinations(self) -> List[OptimizedParams]:
        """Генерация комбинаций с различными trailing stop"""
        combinations = []
        
        # Базовые параметры (из твоих лучших результатов)
        base_params = [
            (20, 23, 1.47),  # Твои оптимальные
            (25, 25, 1.6),   # Альтернативы
            (15, 20, 1.2)
        ]
        
        # 🎯 Различные конфигурации Trailing Stop
        trailing_configs = [
            # Фиксированные
            TrailingStopConfig(TrailingStopType.FIXED, 0.5),
            TrailingStopConfig(TrailingStopType.FIXED, 0.8),
            TrailingStopConfig(TrailingStopType.FIXED, 1.0),
            TrailingStopConfig(TrailingStopType.FIXED, 1.2),
            TrailingStopConfig(TrailingStopType.FIXED, 1.5),
            
            # ADX адаптивные
            TrailingStopConfig(TrailingStopType.ADX_ADAPTIVE, 1.0, 
                             adx_strong_threshold=35, adx_weak_threshold=25, 
                             strong_trend_percent=1.8, weak_trend_percent=0.6),
            TrailingStopConfig(TrailingStopType.ADX_ADAPTIVE, 1.0,
                             adx_strong_threshold=30, adx_weak_threshold=20,
                             strong_trend_percent=1.5, weak_trend_percent=0.8),
            
            # Ступенчатые
            TrailingStopConfig(TrailingStopType.PROFIT_STEPPED, 1.0,
                             profit_levels=[(0.5, 0.5), (1.0, 0.8), (2.0, 1.2), (3.0, 1.8)]),
            TrailingStopConfig(TrailingStopType.PROFIT_STEPPED, 1.0,
                             profit_levels=[(0.8, 0.6), (1.5, 1.0), (2.5, 1.5), (4.0, 2.0)]),
            
            # Динамические (ATR-based)
            TrailingStopConfig(TrailingStopType.DYNAMIC, atr_multiplier=1.5),
            TrailingStopConfig(TrailingStopType.DYNAMIC, atr_multiplier=2.0),
        ]
        
        # Управление рисками
        risk_configs = [
            (None, None),        # Только trailing
            (0.8, None),         # SL + trailing
            (None, 3.0),         # Trailing + высокий TP
            (0.5, 2.5),          # Консервативный
        ]
        
        for ema, adx, vol in base_params:
            for trailing_config in trailing_configs:
                for sl, tp in risk_configs:
                    
                    params = OptimizedParams(
                        ema_period=ema,
                        adx_threshold=adx,
                        volume_multiplier=vol,
                        stop_loss_pct=sl,
                        take_profit_pct=tp,
                        trailing_config=trailing_config,
                        di_diff_threshold=5
                    )
                    combinations.append(params)
                    
                    if len(combinations) >= 120:  # Ограничение для Railway
                        return combinations
        
        return combinations
    
    async def _test_strategy_params(self, df: pd.DataFrame, params: OptimizedParams, test_days: int) -> Optional[OptimizationResult]:
        """Тестирование стратегии с trailing stop"""
        try:
            trades = self._simulate_trading_with_trailing(df, params, test_days)
            
            if not trades:
                return None
            
            return self._calculate_enhanced_metrics(params, trades)
            
        except Exception as e:
            return None
    
    def _simulate_trading_with_trailing(self, df: pd.DataFrame, params: OptimizedParams, test_days: int) -> List[Dict]:
        """Симуляция торговли с улучшенным trailing stop"""
        # Подготовка данных
        closes = df['close'].tolist()
        highs = df['high'].tolist()
        lows = df['low'].tolist()
        volumes = df['volume'].tolist()
        timestamps = df['timestamp'].tolist()
        
        # Расчет индикаторов
        ema = TechnicalIndicators.calculate_ema(closes, params.ema_period)
        adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
        atr = TechnicalIndicators.calculate_atr(highs, lows, closes, 14)
        
        # Дополнительные индикаторы
        rsi = []
        if params.rsi_period:
            rsi = TechnicalIndicators.calculate_rsi(closes, params.rsi_period)
        
        # Средний объем
        df['avg_volume'] = df['volume'].rolling(window=20, min_periods=1).mean()
        avg_volumes = df['avg_volume'].tolist()
        
        # 🎯 Инициализация Trailing Stop менеджера
        trailing_manager = None
        if params.trailing_config:
            trailing_manager = TrailingStopManager(params.trailing_config)
        
        # Определяем тестовый период
        test_start_time = timestamps[-1] - timedelta(days=test_days)
        test_start_idx = max(100, len(timestamps) // 3)
        
        for i in range(len(timestamps)):
            if timestamps[i] >= test_start_time:
                test_start_idx = max(test_start_idx, i)
                break
        
        # Симуляция торговли
        trades = []
        current_trade = None
        trailing_stop_exits = 0
        
        for i in range(test_start_idx, len(timestamps)):
            try:
                price = closes[i]
                timestamp = timestamps[i]
                
                # Проверяем валидность данных
                if (i >= len(ema) or i >= len(adx_data['adx']) or 
                    pd.isna(ema[i]) or pd.isna(adx_data['adx'][i])):
                    continue
                
                # Базовые условия стратегии
                conditions = [
                    price > ema[i],
                    adx_data['adx'][i] > params.adx_threshold,
                    adx_data['plus_di'][i] > adx_data['minus_di'][i],
                    adx_data['plus_di'][i] - adx_data['minus_di'][i] > params.di_diff_threshold,
                    volumes[i] > avg_volumes[i] * params.volume_multiplier
                ]
                
                # RSI фильтр
                if params.rsi_period and i < len(rsi) and not pd.isna(rsi[i]):
                    conditions.append(rsi[i] < params.rsi_overbought)
                
                # Временные фильтры
                if params.avoid_lunch_time:
                    hour = timestamp.hour
                    if 13 <= hour <= 15:
                        conditions.append(False)
                
                hour = timestamp.hour
                if not (params.trading_hours_start <= hour <= params.trading_hours_end):
                    conditions.append(False)
                
                signal_active = all(conditions)
                
                # Логика входа в позицию
                if signal_active and current_trade is None:
                    current_trade = {
                        'entry_time': timestamp,
                        'entry_price': price,
                        'highest_price': price,
                        'trailing_stop_level': None
                    }
                
                # 🎯 Управление позицией с улучшенным trailing stop
                elif current_trade is not None:
                    current_trade['highest_price'] = max(current_trade['highest_price'], price)
                    
                    exit_reasons = []
                    
                    # Обновляем trailing stop уровень
                    if trailing_manager:
                        current_adx = adx_data['adx'][i] if not pd.isna(adx_data['adx'][i]) else None
                        current_atr = atr[i] if i < len(atr) and not pd.isna(atr[i]) else None
                        
                        new_trailing_level = trailing_manager.calculate_trailing_level(
                            current_trade, price, current_adx, current_atr
                        )
                        
                        # Trailing stop может только подниматься
                        if (current_trade['trailing_stop_level'] is None or 
                            new_trailing_level > current_trade['trailing_stop_level']):
                            current_trade['trailing_stop_level'] = new_trailing_level
                    
                    # Проверки выхода
                    
                    # 1. Trailing Stop
                    if (trailing_manager and current_trade['trailing_stop_level'] and 
                        price <= current_trade['trailing_stop_level']):
                        exit_reasons.append('trailing_stop')
                        trailing_stop_exits += 1
                    
                    # 2. Базовый выход (только если нет trailing stop или он не сработал)
                    elif not signal_active:
                        exit_reasons.append('signal_lost')
                    
                    # 3. Stop Loss (жесткий уровень)
                    if params.stop_loss_pct:
                        stop_price = current_trade['entry_price'] * (1 - params.stop_loss_pct/100)
                        if price <= stop_price:
                            exit_reasons = ['stop_loss']  # Перезаписываем, SL приоритетнее
                    
                    # 4. Take Profit (если установлен)
                    if params.take_profit_pct:
                        tp_price = current_trade['entry_price'] * (1 + params.take_profit_pct/100)
                        if price >= tp_price:
                            exit_reasons.append('take_profit')
                    
                    # Выход из позиции
                    if exit_reasons:
                        profit_pct = ((price - current_trade['entry_price']) / current_trade['entry_price']) * 100
                        duration = (timestamp - current_trade['entry_time']).total_seconds() / 3600
                        
                        trades.append({
                            'entry_time': current_trade['entry_time'],
                            'exit_time': timestamp,
                            'entry_price': current_trade['entry_price'],
                            'exit_price': price,
                            'highest_price': current_trade['highest_price'],
                            'profit_pct': profit_pct,
                            'duration_hours': duration,
                            'exit_reason': exit_reasons[0],
                            'trailing_stop_used': trailing_manager is not None,
                            'max_potential_profit': ((current_trade['highest_price'] - current_trade['entry_price']) / current_trade['entry_price']) * 100
                        })
                        
                        current_trade = None
                
            except Exception as e:
                continue
        
        # Закрываем открытую позицию в конце данных
        if current_trade is not None:
            profit_pct = ((closes[-1] - current_trade['entry_price']) / current_trade['entry_price']) * 100
            duration = (timestamps[-1] - current_trade['entry_time']).total_seconds() / 3600
            max_potential = ((current_trade['highest_price'] - current_trade['entry_price']) / current_trade['entry_price']) * 100
            
            trades.append({
                'entry_time': current_trade['entry_time'],
                'exit_time': timestamps[-1],
                'entry_price': current_trade['entry_price'],
                'exit_price': closes[-1],
                'highest_price': current_trade['highest_price'],
                'profit_pct': profit_pct,
                'duration_hours': duration,
                'exit_reason': 'end_of_data',
                'trailing_stop_used': trailing_manager is not None,
                'max_potential_profit': max_potential
            })
        
        return trades
    
    def _calculate_enhanced_metrics(self, params: OptimizedParams, trades: List[Dict]) -> OptimizationResult:
        """Расчет улучшенных метрик с анализом trailing stop"""
        if not trades:
            return OptimizationResult(
                params=params,
                total_return=0, win_rate=0, total_trades=0, profitable_trades=0,
                avg_return_per_trade=0, max_drawdown=0, avg_trade_duration_hours=0,
                sharpe_ratio=0, max_consecutive_losses=0,
                max_profit_per_trade=0, avg_profit_on_winners=0, trailing_stop_exits=0
            )
        
        profits = [t['profit_pct'] for t in trades]
        profitable = [p for p in profits if p > 0]
        durations = [t['duration_hours'] for t in trades]
        max_potentials = [t.get('max_potential_profit', 0) for t in trades]
        
        # Стандартные метрики
        total_return = sum(profits)
        win_rate = len(profitable) / len(profits) * 100 if profits else 0
        avg_return = np.mean(profits) if profits else 0
        max_drawdown = min(profits) if profits else 0
        avg_duration = np.mean(durations) if durations else 0
        
        # Sharpe Ratio
        if len(profits) > 1 and np.std(profits) > 0:
            sharpe_ratio = avg_return / np.std(profits)
        else:
            sharpe_ratio = 0
        
        # Максимальная серия убытков
        consecutive_losses = 0
        max_consecutive_losses = 0
        for profit in profits:
            if profit < 0:
                consecutive_losses += 1
            else:
                max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
                consecutive_losses = 0
        max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
        
        # 🎯 Дополнительные метрики для trailing stop
        max_profit_per_trade = max(profits) if profits else 0
        avg_profit_on_winners = np.mean(profitable) if profitable else 0
        trailing_stop_exits = len([t for t in trades if t.get('exit_reason') == 'trailing_stop'])
        
        # Анализ эффективности trailing stop
        avg_max_potential = np.mean(max_potentials) if max_potentials else 0
        
        return OptimizationResult(
            params=params,
            total_return=total_return,
            win_rate=win_rate,
            total_trades=len(trades),
            profitable_trades=len(profitable),
            avg_return_per_trade=avg_return,
            max_drawdown=max_drawdown,
            avg_trade_duration_hours=avg_duration,
            sharpe_ratio=sharpe_ratio,
            max_consecutive_losses=max_consecutive_losses,
            max_profit_per_trade=max_profit_per_trade,
            avg_profit_on_winners=avg_profit_on_winners,
            trailing_stop_exits=trailing_stop_exits
        )
    
    def print_trailing_results(self, results: List[OptimizationResult], top_n: int = 15):
        """Детальный вывод результатов с анализом trailing stop"""
        if not results:
            print("❌ Нет результатов для отображения")
            return
        
        print(f"\n{'='*90}")
        print(f"🎯 ТОП-{top_n} TRAILING STOP СТРАТЕГИЙ ДЛЯ SBER")
        print(f"{'='*90}")
        print(f"{'Ранг':<4} {'Оценка':<6} {'Доход%':<8} {'ВинРейт':<8} {'Сделок':<7} {'МаксПриб':<9} {'Тип Trailing':<15} {'Детали':<20}")
        print("-" * 90)
        
        for i, result in enumerate(results[:top_n], 1):
            params = result.params
            trailing_type = "None"
            trailing_details = ""
            
            if params.trailing_config:
                trailing_type = params.trailing_config.type.value.title()
                
                if params.trailing_config.type == TrailingStopType.FIXED:
                    trailing_details = f"{params.trailing_config.base_percent}%"
                elif params.trailing_config.type == TrailingStopType.ADX_ADAPTIVE:
                    trailing_details = f"{params.trailing_config.weak_trend_percent}-{params.trailing_config.strong_trend_percent}%"
                elif params.trailing_config.type == TrailingStopType.PROFIT_STEPPED:
                    trailing_details = "Multi-level"
                elif params.trailing_config.type == TrailingStopType.DYNAMIC:
                    trailing_details = f"ATR×{params.trailing_config.atr_multiplier}"
            
            print(f"{i:<4} {result.overall_score():<6.2f} {result.total_return:<8.2f} "
                  f"{result.win_rate:<8.1f} {result.total_trades:<7} "
                  f"{result.max_profit_per_trade:<9.2f} {trailing_type:<15} {trailing_details:<20}")
        
        # Детальный анализ ТОП-3
        print(f"\n{'='*90}")
        print("🔍 ДЕТАЛЬНЫЙ АНАЛИЗ ТОП-3 СТРАТЕГИЙ")
        print(f"{'='*90}")
        
        for i, result in enumerate(results[:3], 1):
            params = result.params
            
            print(f"\n🏆 МЕСТО {i} - ОЦЕНКА: {result.overall_score():.2f}")
            print(f"   📊 Основные показатели:")
            print(f"       • Общая доходность: {result.total_return:+.2f}%")
            print(f"       • Винрейт: {result.win_rate:.1f}% ({result.profitable_trades}/{result.total_trades})")
            print(f"       • Средняя прибыль: {result.avg_return_per_trade:+.3f}%")
            print(f"       • Максимальная сделка: {result.max_profit_per_trade:+.2f}%")
            print(f"       • Средняя на выигрышах: {result.avg_profit_on_winners:+.2f}%")
            print(f"       • Максимальная просадка: {result.max_drawdown:.2f}%")
            print(f"       • Средняя длительность: {result.avg_trade_duration_hours:.1f}ч")
            
            print(f"   ⚙️ Параметры стратегии:")
            print(f"       • EMA период: {params.ema_period}")
            print(f"       • ADX порог: {params.adx_threshold}")
            print(f"       • Объем множитель: {params.volume_multiplier}")
            
            if params.stop_loss_pct:
                print(f"       • Stop Loss: -{params.stop_loss_pct}%")
            if params.take_profit_pct:
                print(f"       • Take Profit: +{params.take_profit_pct}%")
            
            # 🎯 Анализ Trailing Stop
            if params.trailing_config:
                print(f"   🎯 Trailing Stop конфигурация:")
                print(f"       • Тип: {params.trailing_config.type.value.title()}")
                
                if params.trailing_config.type == TrailingStopType.FIXED:
                    print(f"       • Фиксированный процент: {params.trailing_config.base_percent}%")
                
                elif params.trailing_config.type == TrailingStopType.ADX_ADAPTIVE:
                    print(f"       • Слабый тренд (ADX<{params.trailing_config.adx_weak_threshold}): {params.trailing_config.weak_trend_percent}%")
                    print(f"       • Сильный тренд (ADX>{params.trailing_config.adx_strong_threshold}): {params.trailing_config.strong_trend_percent}%")
                
                elif params.trailing_config.type == TrailingStopType.PROFIT_STEPPED:
                    print(f"       • Ступенчатая система:")
                    for profit_thresh, trail_pct in params.trailing_config.profit_levels:
                        print(f"         - При прибыли {profit_thresh}%+ → trailing {trail_pct}%")
                
                elif params.trailing_config.type == TrailingStopType.DYNAMIC:
                    print(f"       • ATR множитель: {params.trailing_config.atr_multiplier}")
                
                print(f"       • Выходов по trailing stop: {result.trailing_stop_exits}")
                if result.total_trades > 0:
                    trailing_ratio = result.trailing_stop_exits / result.total_trades * 100
                    print(f"       • Доля trailing выходов: {trailing_ratio:.1f}%")
            else:
                print(f"   🎯 Trailing Stop: НЕ ИСПОЛЬЗУЕТСЯ")
        
        # Сравнительный анализ
        print(f"\n{'='*90}")
        print("📈 СРАВНИТЕЛЬНЫЙ АНАЛИЗ TRAILING STOP ТИПОВ")
        print(f"{'='*90}")
        
        # Группируем результаты по типам trailing stop
        trailing_types = {}
        no_trailing = []
        
        for result in results:
            if result.params.trailing_config:
                ts_type = result.params.trailing_config.type.value
                if ts_type not in trailing_types:
                    trailing_types[ts_type] = []
                trailing_types[ts_type].append(result)
            else:
                no_trailing.append(result)
        
        print(f"📊 Средние показатели по типам:")
        
        if no_trailing:
            avg_return = np.mean([r.total_return for r in no_trailing])
            avg_winrate = np.mean([r.win_rate for r in no_trailing])
            avg_max_profit = np.mean([r.max_profit_per_trade for r in no_trailing])
            print(f"   • БЕЗ TRAILING: {avg_return:+.2f}% доходность, {avg_winrate:.1f}% винрейт, макс {avg_max_profit:.2f}%")
        
        for ts_type, ts_results in trailing_types.items():
            if ts_results:
                avg_return = np.mean([r.total_return for r in ts_results])
                avg_winrate = np.mean([r.win_rate for r in ts_results])
                avg_max_profit = np.mean([r.max_profit_per_trade for r in ts_results])
                best_score = max([r.overall_score() for r in ts_results])
                print(f"   • {ts_type.upper()}: {avg_return:+.2f}% доходность, {avg_winrate:.1f}% винрейт, макс {avg_max_profit:.2f}%, лучший {best_score:.2f}")
        
        # Рекомендации
        print(f"\n{'='*90}")
        print("💡 РЕКОМЕНДАЦИИ ПО TRAILING STOP")
        print(f"{'='*90}")
        
        best = results[0]
        
        if best.params.trailing_config:
            print(f"🎯 ЛУЧШИЙ TRAILING STOP: {best.params.trailing_config.type.value.title()}")
            
            if best.params.trailing_config.type == TrailingStopType.FIXED:
                print(f"   🔧 Используйте фиксированный trailing stop {best.params.trailing_config.base_percent}%")
                print(f"   💡 Преимущества: Простота, стабильность")
                
            elif best.params.trailing_config.type == TrailingStopType.ADX_ADAPTIVE:
                print(f"   🔧 Используйте ADX-адаптивный trailing stop")
                print(f"       • При слабом тренде: {best.params.trailing_config.weak_trend_percent}%")
                print(f"       • При сильном тренде: {best.params.trailing_config.strong_trend_percent}%")
                print(f"   💡 Преимущества: Адаптация к силе тренда, максимизация прибыли")
                
            elif best.params.trailing_config.type == TrailingStopType.PROFIT_STEPPED:
                print(f"   🔧 Используйте ступенчатый trailing stop")
                print(f"   💡 Преимущества: Защита прибыли на разных уровнях, гибкость")
                
        else:
            print(f"⚠️ Лучший результат БЕЗ trailing stop - возможно, нужна доработка алгоритма")
        
        # Практические советы
        print(f"\n🔧 КОД ДЛЯ ВНЕДРЕНИЯ ЛУЧШЕЙ СТРАТЕГИИ:")
        print("=" * 60)
        best_params = best.params
        
        print("# Основные параметры:")
        print(f"EMA_PERIOD = {best_params.ema_period}")
        print(f"ADX_THRESHOLD = {best_params.adx_threshold}")
        print(f"VOLUME_MULTIPLIER = {best_params.volume_multiplier}")
        print(f"DI_DIFF_THRESHOLD = {best_params.di_diff_threshold}")
        
        if best_params.stop_loss_pct:
            print(f"STOP_LOSS_PCT = {best_params.stop_loss_pct}")
        if best_params.take_profit_pct:
            print(f"TAKE_PROFIT_PCT = {best_params.take_profit_pct}")
            
        # Код trailing stop
        if best_params.trailing_config:
            tc = best_params.trailing_config
            print(f"\n# Trailing Stop конфигурация:")
            print(f"TRAILING_TYPE = '{tc.type.value}'")
            
            if tc.type == TrailingStopType.FIXED:
                print(f"TRAILING_PERCENT = {tc.base_percent}")
                print("\n# Логика trailing stop:")
                print("def update_trailing_stop(highest_price, trailing_percent):")
                print("    return highest_price * (1 - trailing_percent/100)")
                
            elif tc.type == TrailingStopType.ADX_ADAPTIVE:
                print(f"ADX_STRONG_THRESHOLD = {tc.adx_strong_threshold}")
                print(f"ADX_WEAK_THRESHOLD = {tc.adx_weak_threshold}")
                print(f"STRONG_TREND_PERCENT = {tc.strong_trend_percent}")
                print(f"WEAK_TREND_PERCENT = {tc.weak_trend_percent}")
                
                print("\n# Логика ADX-адаптивного trailing:")
                print("def calculate_trailing_percent(current_adx):")
                print("    if current_adx >= ADX_STRONG_THRESHOLD:")
                print("        return STRONG_TREND_PERCENT")
                print("    elif current_adx <= ADX_WEAK_THRESHOLD:")
                print("        return WEAK_TREND_PERCENT")
                print("    else:")
                print("        # Линейная интерполяция")
                print("        ratio = (current_adx - ADX_WEAK_THRESHOLD) / (ADX_STRONG_THRESHOLD - ADX_WEAK_THRESHOLD)")
                print("        return WEAK_TREND_PERCENT + (STRONG_TREND_PERCENT - WEAK_TREND_PERCENT) * ratio")
                
            elif tc.type == TrailingStopType.PROFIT_STEPPED:
                print("PROFIT_LEVELS = [")
                for profit_thresh, trail_pct in tc.profit_levels:
                    print(f"    ({profit_thresh}, {trail_pct}),")
                print("]")
                
                print("\n# Логика ступенчатого trailing:")
                print("def get_trailing_percent(current_profit):")
                print("    for profit_threshold, trailing_pct in sorted(PROFIT_LEVELS, reverse=True):")
                print("        if current_profit >= profit_threshold:")
                print("            return trailing_pct")
                print("    return 1.0  # базовый уровень")
        
        print(f"\n📊 ОЖИДАЕМЫЕ РЕЗУЛЬТАТЫ:")
        print(f"   💰 Доходность: {best.total_return:+.2f}%")
        print(f"   🎲 Винрейт: {best.win_rate:.1f}%")
        print(f"   🚀 Максимальная сделка: {best.max_profit_per_trade:+.2f}%")
        print(f"   📈 Количество сделок: {best.total_trades}")
        print(f"   ⏱️ Средняя длительность: {best.avg_trade_duration_hours:.1f}ч")
        
        if best.trailing_stop_exits > 0:
            trailing_efficiency = best.trailing_stop_exits / best.total_trades * 100
            print(f"   🎯 Эффективность trailing: {trailing_efficiency:.1f}% выходов")

async def main():
    """Главная функция для тестирования trailing stop"""
    print("🎯 ENHANCED SBER TRAILING STOP OPTIMIZER")
    print("=" * 70)
    print("📊 Поиск оптимального trailing stop для максимизации прибыли")
    print("⏱️ Процесс займет 5-7 минут...")
    print("=" * 70)
    
    # Получаем токен
    TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
    
    if not TINKOFF_TOKEN:
        logger.error("❌ TINKOFF_TOKEN не найден в переменных окружения")
        logger.error("🔧 Добавьте токен в Railway: Settings → Variables → TINKOFF_TOKEN")
        sys.exit(1)
    
    logger.info("✅ Токен найден, запускаем оптимизацию trailing stop...")
    
    try:
        # Создаем оптимизатор
        optimizer = EnhancedTrailingOptimizer(TINKOFF_TOKEN)
        
        # Запускаем оптимизацию
        test_days = 90  # Увеличиваем период для лучшего анализа trailing stop
        logger.info(f"🔬 Поиск оптимального trailing stop за {test_days} дней...")
        
        results = await optimizer.run_optimization(test_days=test_days)
        
        if not results:
            print("❌ Не удалось получить результаты оптимизации")
            return
        
        # Выводим результаты с фокусом на trailing stop
        optimizer.print_trailing_results(results, top_n=15)
        
        # Дополнительная статистика
        print(f"\n📈 СТАТИСТИКА ОПТИМИЗАЦИИ:")
        print(f"   🧪 Протестировано стратегий: {len(results)}")
        
        with_trailing = [r for r in results if r.params.trailing_config]
        without_trailing = [r for r in results if not r.params.trailing_config]
        
        print(f"   🎯 С trailing stop: {len(with_trailing)}")
        print(f"   ⚪ Без trailing stop: {len(without_trailing)}")
        
        if with_trailing and without_trailing:
            avg_with = np.mean([r.total_return for r in with_trailing])
            avg_without = np.mean([r.total_return for r in without_trailing])
            improvement = ((avg_with - avg_without) / abs(avg_without)) * 100 if avg_without != 0 else 0
            
            print(f"   📊 Средняя доходность с trailing: {avg_with:+.2f}%")
            print(f"   📊 Средняя доходность без trailing: {avg_without:+.2f}%")
            print(f"   🚀 Улучшение от trailing stop: {improvement:+.1f}%")
        
        profitable = [r for r in results if r.total_return > 0]
        print(f"   💰 Прибыльных стратегий: {len(profitable)} ({len(profitable)/len(results)*100:.1f}%)")
        
        if profitable:
            best_profit = max([r.max_profit_per_trade for r in profitable])
            avg_max_profit = np.mean([r.max_profit_per_trade for r in profitable])
            print(f"   🚀 Максимальная сделка: {best_profit:.2f}%")
            print(f"   📊 Средняя максимальная: {avg_max_profit:.2f}%")
        
        logger.info("✅ Оптимизация trailing stop завершена успешно!")
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Оптимизация прервана пользователем")
    except Exception as e:
        print(f"❌ Фатальная ошибка: {e}")
        sys.exit(1)
