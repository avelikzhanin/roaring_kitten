#!/usr/bin/env python3
"""
ИСПРАВЛЕННЫЙ оптимизатор SBER с правильной логикой Trailing Stop
Фикс: Trailing Stop работает БЕЗ конфликта с Take Profit
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

class ExitStrategy(Enum):
    """Стратегии выхода из позиций"""
    TRAILING_ONLY = "trailing_only"           # Только trailing stop
    TRAILING_WITH_HIGH_TP = "trailing_high_tp" # Trailing + высокий TP (защита)
    ADAPTIVE_EXIT = "adaptive_exit"           # Адаптивный выход
    SIGNAL_LOSS_BACKUP = "signal_backup"     # Trailing + signal loss как backup

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
    profit_levels: List[Tuple[float, float]] = None
    
    # Для динамического
    atr_multiplier: float = 2.0
    
    def __post_init__(self):
        if self.profit_levels is None:
            self.profit_levels = [
                (0.5, 0.4),   # При прибыли 0.5%+ → trailing 0.4%
                (1.0, 0.6),   # При прибыли 1.0%+ → trailing 0.6%
                (1.5, 0.8),   # При прибыли 1.5%+ → trailing 0.8%
                (2.5, 1.2),   # При прибыли 2.5%+ → trailing 1.2%
                (4.0, 1.8),   # При прибыли 4.0%+ → trailing 1.8%
            ]

@dataclass
class OptimizedParams:
    """Параметры оптимизированной стратегии"""
    ema_period: int = 20
    adx_threshold: float = 23
    di_diff_threshold: float = 5
    volume_multiplier: float = 1.47
    
    # 🎯 ИСПРАВЛЕНО: Четкая стратегия выхода
    exit_strategy: ExitStrategy = ExitStrategy.TRAILING_ONLY
    
    # Управление рисками
    stop_loss_pct: Optional[float] = None
    emergency_take_profit_pct: Optional[float] = None  # Только для защиты от аномалий
    
    # Trailing Stop конфигурация
    trailing_config: Optional[TrailingStopConfig] = None
    
    # Дополнительные фильтры
    rsi_period: Optional[int] = None
    rsi_overbought: Optional[float] = None
    momentum_periods: Optional[int] = None
    
    # Временные фильтры
    avoid_lunch_time: bool = False
    trading_hours_start: int = 10
    trading_hours_end: int = 18

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
    
    # Дополнительные метрики для trailing stop
    max_profit_per_trade: float = 0
    avg_profit_on_winners: float = 0
    trailing_stop_exits: int = 0
    signal_loss_exits: int = 0
    emergency_tp_exits: int = 0
    
    def overall_score(self) -> float:
        """Улучшенная комплексная оценка"""
        return_score = min(self.total_return / 8, 20)  # Больший вес доходности
        winrate_score = self.win_rate / 8
        trades_score = min(self.total_trades / 4, 6)
        drawdown_penalty = max(0, abs(self.max_drawdown) / 3)
        
        # Бонус за крупные прибыли
        big_profit_bonus = min(self.max_profit_per_trade / 1.5, 5)
        
        # Бонус за эффективность trailing stop
        if self.total_trades > 0:
            trailing_efficiency = self.trailing_stop_exits / self.total_trades
            trailing_bonus = trailing_efficiency * 3
        else:
            trailing_bonus = 0
        
        return (return_score * 0.35 + 
                winrate_score * 0.25 + 
                trades_score * 0.15 + 
                big_profit_bonus * 0.15 + 
                trailing_bonus * 0.1 - 
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
        if len(prices) < period:
            return [np.nan] * len(prices)
        series = pd.Series(prices)
        ema = series.ewm(span=period, adjust=False).mean()
        return ema.tolist()
    
    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
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
        if len(highs) < period + 1:
            return [np.nan] * len(highs)
        
        df = pd.DataFrame({'high': highs, 'low': lows, 'close': closes})
        df['prev_close'] = df['close'].shift(1)
        df['hl'] = df['high'] - df['low']
        df['hc'] = abs(df['high'] - df['prev_close'])
        df['lc'] = abs(df['low'] - df['prev_close'])
        df['tr'] = df[['hl', 'hc', 'lc']].max(axis=1)
        df['atr'] = df['tr'].rolling(window=period).mean()
        
        return df['atr'].fillna(np.nan).tolist()
    
    @staticmethod
    def wilder_smoothing(values: pd.Series, period: int) -> pd.Series:
        result = pd.Series(index=values.index, dtype=float)
        first_avg = values.iloc[:period].mean()
        result.iloc[period-1] = first_avg
        
        for i in range(period, len(values)):
            result.iloc[i] = (result.iloc[i-1] * (period - 1) + values.iloc[i]) / period
        
        return result
    
    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        if len(highs) < period * 2:
            return {'adx': [np.nan] * len(highs), 'plus_di': [np.nan] * len(highs), 'minus_di': [np.nan] * len(highs)}
        
        df = pd.DataFrame({'high': highs, 'low': lows, 'close': closes})
        
        # True Range
        df['prev_close'] = df['close'].shift(1)
        df['hl'] = df['high'] - df['low']
        df['hc'] = abs(df['high'] - df['prev_close'])
        df['lc'] = abs(df['low'] - df['prev_close'])
        df['tr'] = df[['hl', 'hc', 'lc']].max(axis=1)
        
        # Directional Movement
        df['high_diff'] = df['high'] - df['high'].shift(1)
        df['low_diff'] = df['low'].shift(1) - df['low']
        
        df['plus_dm'] = np.where((df['high_diff'] > df['low_diff']) & (df['high_diff'] > 0), df['high_diff'], 0)
        df['minus_dm'] = np.where((df['low_diff'] > df['high_diff']) & (df['low_diff'] > 0), df['low_diff'], 0)
        
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
    """Менеджер Trailing Stop"""
    
    def __init__(self, config: TrailingStopConfig):
        self.config = config
    
    def calculate_trailing_level(self, current_trade: Dict, current_price: float, 
                               current_adx: float = None, current_atr: float = None) -> float:
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
                trailing_pct = self.config.strong_trend_percent
            elif current_adx <= self.config.adx_weak_threshold:
                trailing_pct = self.config.weak_trend_percent
            else:
                ratio = (current_adx - self.config.adx_weak_threshold) / (self.config.adx_strong_threshold - self.config.adx_weak_threshold)
                trailing_pct = self.config.weak_trend_percent + (self.config.strong_trend_percent - self.config.weak_trend_percent) * ratio
            
            return highest_price * (1 - trailing_pct/100)
        
        elif self.config.type == TrailingStopType.PROFIT_STEPPED:
            trailing_pct = self.config.base_percent
            
            for profit_threshold, step_trailing_pct in sorted(self.config.profit_levels, reverse=True):
                if current_profit >= profit_threshold:
                    trailing_pct = step_trailing_pct
                    break
            
            return highest_price * (1 - trailing_pct/100)
        
        elif self.config.type == TrailingStopType.DYNAMIC:
            if current_atr is None:
                return highest_price * (1 - self.config.base_percent/100)
            
            atr_distance = current_atr * self.config.atr_multiplier
            return highest_price - atr_distance
        
        else:
            return highest_price * (1 - self.config.base_percent/100)

class FixedTrailingOptimizer:
    """Исправленный оптимизатор с правильной логикой trailing stop"""
    
    def __init__(self, tinkoff_token: str):
        self.data_provider = DataProvider(tinkoff_token)
    
    async def run_optimization(self, test_days: int = 90) -> List[OptimizationResult]:
        """Запуск оптимизации с исправленной логикой"""
        logger.info(f"🎯 Запуск ИСПРАВЛЕННОЙ оптимизации Trailing Stop за {test_days} дней...")
        
        hours_needed = test_days * 24 + 200
        
        try:
            candles = await self.data_provider.get_candles(hours=hours_needed)
            
            if len(candles) < 100:
                logger.error("❌ Недостаточно данных")
                return []
                
            df = self.data_provider.candles_to_dataframe(candles)
            
            if df.empty:
                logger.error("❌ Ошибка преобразования данных")
                return []
            
            parameter_combinations = self._generate_fixed_combinations()
            
            logger.info(f"🧪 Тестируем {len(parameter_combinations)} ИСПРАВЛЕННЫХ комбинаций...")
            
            results = []
            for i, params in enumerate(parameter_combinations, 1):
                try:
                    if i % 8 == 0:
                        logger.info(f"⏳ Прогресс: {i}/{len(parameter_combinations)} ({i/len(parameter_combinations)*100:.1f}%)")
                    
                    result = await self._test_strategy_params(df, params, test_days)
                    if result:
                        results.append(result)
                        
                except Exception as e:
                    continue
            
            results.sort(key=lambda x: x.overall_score(), reverse=True)
            
            logger.info(f"✅ Исправленная оптимизация завершена! Найдено {len(results)} результатов")
            return results
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
            return []
    
    def _generate_fixed_combinations(self) -> List[OptimizedParams]:
        """Генерация исправленных комбинаций"""
        combinations = []
        
        # Базовые параметры (твои лучшие + вариации)
        base_configs = [
            (20, 23, 1.47),  # Твои оптимальные
            (25, 25, 1.6),
            (15, 20, 1.2),
            (20, 20, 1.3),
        ]
        
        # 🎯 ИСПРАВЛЕНО: Разные стратегии выхода
        exit_strategies = [
            ExitStrategy.TRAILING_ONLY,           # Только trailing
            ExitStrategy.TRAILING_WITH_HIGH_TP,   # Trailing + защитный TP
            ExitStrategy.ADAPTIVE_EXIT,           # Адаптивный
        ]
        
        # Trailing stop конфигурации
        trailing_configs = [
            # Фиксированные (разные уровни)
            TrailingStopConfig(TrailingStopType.FIXED, 0.4),
            TrailingStopConfig(TrailingStopType.FIXED, 0.6),
            TrailingStopConfig(TrailingStopType.FIXED, 0.8),
            TrailingStopConfig(TrailingStopType.FIXED, 1.0),
            TrailingStopConfig(TrailingStopType.FIXED, 1.2),
            TrailingStopConfig(TrailingStopType.FIXED, 1.5),
            
            # ADX адаптивные
            TrailingStopConfig(TrailingStopType.ADX_ADAPTIVE, 1.0,
                             adx_strong_threshold=35, adx_weak_threshold=25,
                             strong_trend_percent=1.5, weak_trend_percent=0.5),
            TrailingStopConfig(TrailingStopType.ADX_ADAPTIVE, 1.0,
                             adx_strong_threshold=30, adx_weak_threshold=20,
                             strong_trend_percent=1.8, weak_trend_percent=0.6),
            TrailingStopConfig(TrailingStopType.ADX_ADAPTIVE, 1.0,
                             adx_strong_threshold=40, adx_weak_threshold=25,
                             strong_trend_percent=2.0, weak_trend_percent=0.8),
            
            # Ступенчатые
            TrailingStopConfig(TrailingStopType.PROFIT_STEPPED, 1.0,
                             profit_levels=[(0.5, 0.4), (1.0, 0.6), (2.0, 1.0), (3.0, 1.5)]),
            TrailingStopConfig(TrailingStopType.PROFIT_STEPPED, 1.0,
                             profit_levels=[(0.8, 0.5), (1.5, 0.8), (2.5, 1.2), (4.0, 1.8)]),
        ]
        
        # Stop Loss варианты
        stop_losses = [None, 0.5, 0.8]
        
        # Emergency TP (только для защиты от аномалий)
        emergency_tps = {
            ExitStrategy.TRAILING_ONLY: [None],
            ExitStrategy.TRAILING_WITH_HIGH_TP: [7.0, 10.0],  # Очень высокие
            ExitStrategy.ADAPTIVE_EXIT: [8.0],
        }
        
        for ema, adx, vol in base_configs:
            for exit_strategy in exit_strategies:
                for trailing_config in trailing_configs:
                    for sl in stop_losses:
                        for emergency_tp in emergency_tps[exit_strategy]:
                            
                            params = OptimizedParams(
                                ema_period=ema,
                                adx_threshold=adx,
                                volume_multiplier=vol,
                                exit_strategy=exit_strategy,
                                stop_loss_pct=sl,
                                emergency_take_profit_pct=emergency_tp,
                                trailing_config=trailing_config,
                                di_diff_threshold=5
                            )
                            combinations.append(params)
                            
                            if len(combinations) >= 150:  # Лимит для Railway
                                return combinations
        
        return combinations
    
    async def _test_strategy_params(self, df: pd.DataFrame, params: OptimizedParams, test_days: int) -> Optional[OptimizationResult]:
        """Тестирование с исправленной логикой"""
        try:
            trades = self._simulate_fixed_trading(df, params, test_days)
            
            if not trades:
                return None
            
            return self._calculate_enhanced_metrics(params, trades)
            
        except Exception as e:
            return None
    
    def _simulate_fixed_trading(self, df: pd.DataFrame, params: OptimizedParams, test_days: int) -> List[Dict]:
        """🎯 ИСПРАВЛЕННАЯ симуляция торговли"""
        
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
        
        # Средний объем
        df['avg_volume'] = df['volume'].rolling(window=20, min_periods=1).mean()
        avg_volumes = df['avg_volume'].tolist()
        
        # Trailing Stop менеджер
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
        
        # Счетчики выходов
        trailing_stops = 0
        signal_losses = 0
        emergency_tps = 0
        
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
                
                # Временные фильтры
                if params.avoid_lunch_time:
                    hour = timestamp.hour
                    if 13 <= hour <= 15:
                        conditions.append(False)
                
                hour = timestamp.hour
                if not (params.trading_hours_start <= hour <= params.trading_hours_end):
                    conditions.append(False)
                
                signal_active = all(conditions)
                
                # Вход в позицию
                if signal_active and current_trade is None:
                    current_trade = {
                        'entry_time': timestamp,
                        'entry_price': price,
                        'highest_price': price,
                        'trailing_stop_level': None,
                        'profit_milestone_reached': 0  # Для адаптивного выхода
                    }
                
                # 🎯 ИСПРАВЛЕННОЕ управление позицией
                elif current_trade is not None:
                    current_trade['highest_price'] = max(current_trade['highest_price'], price)
                    current_profit = ((price - current_trade['entry_price']) / current_trade['entry_price']) * 100
                    
                    exit_reason = None
                    
                    # 1. STOP LOSS (жесткий уровень - всегда приоритет)
                    if params.stop_loss_pct:
                        stop_price = current_trade['entry_price'] * (1 - params.stop_loss_pct/100)
                        if price <= stop_price:
                            exit_reason = 'stop_loss'
                    
                    # 2. EMERGENCY TAKE PROFIT (защита от аномалий)
                    if not exit_reason and params.emergency_take_profit_pct:
                        emergency_tp_price = current_trade['entry_price'] * (1 + params.emergency_take_profit_pct/100)
                        if price >= emergency_tp_price:
                            exit_reason = 'emergency_take_profit'
                            emergency_tps += 1
                    
                    # 3. TRAILING STOP (основной механизм выхода)
                    if not exit_reason:
                        current_adx = adx_data['adx'][i] if not pd.isna(adx_data['adx'][i]) else None
                        current_atr = atr[i] if i < len(atr) and not pd.isna(atr[i]) else None
                        
                        new_trailing_level = trailing_manager.calculate_trailing_level(
                            current_trade, price, current_adx, current_atr
                        )
                        
                        # Trailing stop может только подниматься
                        if (current_trade['trailing_stop_level'] is None or 
                            new_trailing_level > current_trade['trailing_stop_level']):
                            current_trade['trailing_stop_level'] = new_trailing_level
                        
                        # Проверяем срабатывание trailing stop
                        if (current_trade['trailing_stop_level'] and 
                            price <= current_trade['trailing_stop_level']):
                            exit_reason = 'trailing_stop'
                            trailing_stops += 1
                    
                    # 4. SIGNAL LOSS (резервный выход для некоторых стратегий)
                    if not exit_reason:
                        if params.exit_strategy == ExitStrategy.SIGNAL_LOSS_BACKUP:
                            if not signal_active and current_profit > 0.3:  # Минимальная прибыль для выхода
                                exit_reason = 'signal_loss'
                                signal_losses += 1
                        
                        elif params.exit_strategy == ExitStrategy.ADAPTIVE_EXIT:
                            # Адаптивный выход: после достижения определенной прибыли становимся более консервативными
                            if current_profit >= 1.5 and not signal_active:
                                exit_reason = 'adaptive_signal_loss'
                                signal_losses += 1
                    
                    # Выход из позиции
                    if exit_reason:
                        duration = (timestamp - current_trade['entry_time']).total_seconds() / 3600
                        max_potential = ((current_trade['highest_price'] - current_trade['entry_price']) / current_trade['entry_price']) * 100
                        
                        trades.append({
                            'entry_time': current_trade['entry_time'],
                            'exit_time': timestamp,
                            'entry_price': current_trade['entry_price'],
                            'exit_price': price,
                            'highest_price': current_trade['highest_price'],
                            'profit_pct': current_profit,
                            'duration_hours': duration,
                            'exit_reason': exit_reason,
                            'trailing_stop_used': True,
                            'max_potential_profit': max_potential,
                            'trailing_level_at_exit': current_trade.get('trailing_stop_level')
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
                'trailing_stop_used': True,
                'max_potential_profit': max_potential,
                'trailing_level_at_exit': current_trade.get('trailing_stop_level')
            })
        
        # Добавляем статистику выходов к результатам
        for trade in trades:
            trade['total_trailing_stops'] = trailing_stops
            trade['total_signal_losses'] = signal_losses
            trade['total_emergency_tps'] = emergency_tps
        
        return trades
    
    def _calculate_enhanced_metrics(self, params: OptimizedParams, trades: List[Dict]) -> OptimizationResult:
        """Расчет метрик с правильным учетом trailing stop"""
        if not trades:
            return OptimizationResult(
                params=params, total_return=0, win_rate=0, total_trades=0, profitable_trades=0,
                avg_return_per_trade=0, max_drawdown=0, avg_trade_duration_hours=0,
                sharpe_ratio=0, max_consecutive_losses=0,
                max_profit_per_trade=0, avg_profit_on_winners=0, trailing_stop_exits=0,
                signal_loss_exits=0, emergency_tp_exits=0
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
        
        # Метрики trailing stop
        max_profit_per_trade = max(profits) if profits else 0
        avg_profit_on_winners = np.mean(profitable) if profitable else 0
        
        # Подсчет выходов по типам
        trailing_stop_exits = len([t for t in trades if 'trailing_stop' in t.get('exit_reason', '')])
        signal_loss_exits = len([t for t in trades if 'signal_loss' in t.get('exit_reason', '')])
        emergency_tp_exits = len([t for t in trades if t.get('exit_reason') == 'emergency_take_profit'])
        
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
            trailing_stop_exits=trailing_stop_exits,
            signal_loss_exits=signal_loss_exits,
            emergency_tp_exits=emergency_tp_exits
        )
    
    def print_fixed_results(self, results: List[OptimizationResult], top_n: int = 12):
        """Детальный вывод ИСПРАВЛЕННЫХ результатов"""
        if not results:
            print("❌ Нет результатов для отображения")
            return
        
        print(f"\n{'='*100}")
        print(f"🎯 ТОП-{top_n} ИСПРАВЛЕННЫХ TRAILING STOP СТРАТЕГИЙ SBER")
        print(f"{'='*100}")
        print(f"{'№':<3} {'Оценка':<7} {'Доход%':<8} {'ВинР%':<6} {'Сделок':<7} {'Средн%':<7} {'Макс%':<7} {'TrailExit':<9} {'Стратегия':<20}")
        print("-" * 100)
        
        for i, result in enumerate(results[:top_n], 1):
            trail_exits = result.trailing_stop_exits
            trail_pct = f"{trail_exits/result.total_trades*100:.0f}%" if result.total_trades > 0 else "0%"
            exit_strategy = result.params.exit_strategy.value.replace('_', ' ').title()[:18]
            
            print(f"{i:<3} {result.overall_score():<7.2f} {result.total_return:<8.2f} "
                  f"{result.win_rate:<6.1f} {result.total_trades:<7} "
                  f"{result.avg_return_per_trade:<7.3f} {result.max_profit_per_trade:<7.2f} "
                  f"{trail_exits}({trail_pct})<9 {exit_strategy:<20}")
        
        # Детальный анализ ТОП-5
        print(f"\n{'='*100}")
        print("🔍 ДЕТАЛЬНЫЙ АНАЛИЗ ТОП-5 ИСПРАВЛЕННЫХ СТРАТЕГИЙ")
        print(f"{'='*100}")
        
        for i, result in enumerate(results[:5], 1):
            params = result.params
            
            print(f"\n🏆 МЕСТО {i} - ИТОГОВАЯ ОЦЕНКА: {result.overall_score():.2f}")
            print(f"   📊 ОСНОВНЫЕ ПОКАЗАТЕЛИ:")
            print(f"       💰 Общая доходность: {result.total_return:+.2f}%")
            print(f"       🎯 Винрейт: {result.win_rate:.1f}% ({result.profitable_trades}/{result.total_trades})")
            print(f"       📈 Средняя прибыль: {result.avg_return_per_trade:+.3f}% (было +0.137%)")
            print(f"       🚀 Максимальная сделка: {result.max_profit_per_trade:+.2f}% (было +2.72%)")
            print(f"       💎 Средняя на выигрышах: {result.avg_profit_on_winners:+.2f}%")
            print(f"       📉 Максимальная просадка: {result.max_drawdown:.2f}%")
            print(f"       ⏱️ Средняя длительность: {result.avg_trade_duration_hours:.1f}ч")
            print(f"       📊 Sharpe Ratio: {result.sharpe_ratio:.2f}")
            
            print(f"   ⚙️ ПАРАМЕТРЫ СТРАТЕГИИ:")
            print(f"       • EMA период: {params.ema_period}")
            print(f"       • ADX порог: {params.adx_threshold}")
            print(f"       • Объем множитель: {params.volume_multiplier}")
            print(f"       • Стратегия выхода: {params.exit_strategy.value.replace('_', ' ').title()}")
            
            if params.stop_loss_pct:
                print(f"       • Stop Loss: -{params.stop_loss_pct}%")
            if params.emergency_take_profit_pct:
                print(f"       • Emergency TP: +{params.emergency_take_profit_pct}% (защита)")
            
            # Детализация Trailing Stop
            print(f"   🎯 TRAILING STOP АНАЛИЗ:")
            tc = params.trailing_config
            print(f"       • Тип: {tc.type.value.replace('_', ' ').title()}")
            
            if tc.type == TrailingStopType.FIXED:
                print(f"       • Фиксированный процент: {tc.base_percent}%")
            elif tc.type == TrailingStopType.ADX_ADAPTIVE:
                print(f"       • Слабый тренд (ADX<{tc.adx_weak_threshold}): {tc.weak_trend_percent}%")
                print(f"       • Сильный тренд (ADX>{tc.adx_strong_threshold}): {tc.strong_trend_percent}%")
            elif tc.type == TrailingStopType.PROFIT_STEPPED:
                print(f"       • Ступенчатая система:")
                for profit_thresh, trail_pct in tc.profit_levels[:3]:  # Показываем первые 3
                    print(f"         - При прибыли {profit_thresh}%+ → trailing {trail_pct}%")
            
            # Статистика выходов
            print(f"   📊 СТАТИСТИКА ВЫХОДОВ:")
            if result.total_trades > 0:
                trail_ratio = result.trailing_stop_exits / result.total_trades * 100
                signal_ratio = result.signal_loss_exits / result.total_trades * 100
                emergency_ratio = result.emergency_tp_exits / result.total_trades * 100
                
                print(f"       🎯 Trailing Stop: {result.trailing_stop_exits} ({trail_ratio:.1f}%)")
                print(f"       📡 Signal Loss: {result.signal_loss_exits} ({signal_ratio:.1f}%)")
                if result.emergency_tp_exits > 0:
                    print(f"       🚨 Emergency TP: {result.emergency_tp_exits} ({emergency_ratio:.1f}%)")
                print(f"       🛑 Stop Loss: оставшиеся")
        
        # Сравнительный анализ по стратегиям выхода
        print(f"\n{'='*100}")
        print("📈 СРАВНЕНИЕ СТРАТЕГИЙ ВЫХОДА")
        print(f"{'='*100}")
        
        exit_strategies = {}
        for result in results:
            strategy = result.params.exit_strategy.value
            if strategy not in exit_strategies:
                exit_strategies[strategy] = []
            exit_strategies[strategy].append(result)
        
        print(f"📊 Средние показатели по стратегиям выхода:")
        for strategy, strategy_results in exit_strategies.items():
            if strategy_results:
                avg_return = np.mean([r.total_return for r in strategy_results])
                avg_winrate = np.mean([r.win_rate for r in strategy_results])
                avg_max_profit = np.mean([r.max_profit_per_trade for r in strategy_results])
                avg_trail_ratio = np.mean([r.trailing_stop_exits/r.total_trades*100 if r.total_trades > 0 else 0 for r in strategy_results])
                best_score = max([r.overall_score() for r in strategy_results])
                
                strategy_name = strategy.replace('_', ' ').title()
                print(f"   • {strategy_name}:")
                print(f"     - Доходность: {avg_return:+.2f}%, Винрейт: {avg_winrate:.1f}%")
                print(f"     - Макс прибыль: {avg_max_profit:.2f}%, Trailing выходы: {avg_trail_ratio:.1f}%")
                print(f"     - Лучшая оценка: {best_score:.2f}")
        
        # Анализ Trailing Stop типов
        print(f"\n📊 Анализ Trailing Stop типов:")
        trailing_types = {}
        for result in results:
            if result.params.trailing_config:
                ts_type = result.params.trailing_config.type.value
                if ts_type not in trailing_types:
                    trailing_types[ts_type] = []
                trailing_types[ts_type].append(result)
        
        for ts_type, ts_results in trailing_types.items():
            if ts_results:
                avg_return = np.mean([r.total_return for r in ts_results])
                avg_trail_exits = np.mean([r.trailing_stop_exits/r.total_trades*100 if r.total_trades > 0 else 0 for r in ts_results])
                best_max_profit = max([r.max_profit_per_trade for r in ts_results])
                
                ts_name = ts_type.replace('_', ' ').title()
                print(f"   • {ts_name}: {avg_return:+.2f}% доходность, {avg_trail_exits:.1f}% trailing выходы, макс {best_max_profit:.2f}%")
        
        # Главные выводы
        print(f"\n{'='*100}")
        print("💡 ГЛАВНЫЕ ВЫВОДЫ И РЕКОМЕНДАЦИИ")
        print(f"{'='*100}")
        
        best = results[0]
        
        print(f"🏆 ЛУЧШАЯ СТРАТЕГИЯ:")
        print(f"   📈 Улучшение средней прибыли: {best.avg_return_per_trade:+.3f}% (было +0.137%)")
        improvement = ((best.avg_return_per_trade - 0.137) / 0.137) * 100 if 0.137 != 0 else 0
        print(f"   🚀 Улучшение в {improvement:+.0f}%!")
        
        print(f"   💎 Максимальная сделка: {best.max_profit_per_trade:+.2f}% (было +2.72%)")
        if best.max_profit_per_trade > 2.72:
            profit_improvement = ((best.max_profit_per_trade - 2.72) / 2.72) * 100
            print(f"   ⬆️ Рост максимальной прибыли на {profit_improvement:+.0f}%!")
        
        if best.trailing_stop_exits > 0:
            trail_efficiency = best.trailing_stop_exits / best.total_trades * 100
            print(f"   🎯 Эффективность trailing stop: {trail_efficiency:.1f}% всех выходов")
            print(f"   ✅ Trailing stop РАБОТАЕТ правильно!")
        else:
            print(f"   ⚠️ Trailing stop все еще не срабатывает - нужна дальнейшая настройка")
        
        print(f"\n🔧 КОД ДЛЯ ВНЕДРЕНИЯ ЛУЧШЕЙ СТРАТЕГИИ:")
        print("=" * 60)
        best_params = best.params
        
        print("# Основные параметры стратегии:")
        print(f"EMA_PERIOD = {best_params.ema_period}")
        print(f"ADX_THRESHOLD = {best_params.adx_threshold}")
        print(f"VOLUME_MULTIPLIER = {best_params.volume_multiplier}")
        print(f"DI_DIFF_THRESHOLD = {best_params.di_diff_threshold}")
        
        print(f"\n# Стратегия выхода:")
        print(f"EXIT_STRATEGY = '{best_params.exit_strategy.value}'")
        
        if best_params.stop_loss_pct:
            print(f"STOP_LOSS_PCT = {best_params.stop_loss_pct}")
        
        if best_params.emergency_take_profit_pct:
            print(f"EMERGENCY_TAKE_PROFIT_PCT = {best_params.emergency_take_profit_pct}")
            print("# ☝️ Emergency TP - только защита от аномалий, НЕ основной выход!")
        
        # Код trailing stop
        tc = best_params.trailing_config
        print(f"\n# Trailing Stop конфигурация:")
        print(f"TRAILING_TYPE = '{tc.type.value}'")
        
        if tc.type == TrailingStopType.FIXED:
            print(f"TRAILING_PERCENT = {tc.base_percent}")
            print("\ndef calculate_trailing_stop(highest_price):")
            print(f"    return highest_price * (1 - {tc.base_percent}/100)")
            
        elif tc.type == TrailingStopType.ADX_ADAPTIVE:
            print(f"ADX_STRONG_THRESHOLD = {tc.adx_strong_threshold}")
            print(f"ADX_WEAK_THRESHOLD = {tc.adx_weak_threshold}")
            print(f"STRONG_TREND_PERCENT = {tc.strong_trend_percent}")
            print(f"WEAK_TREND_PERCENT = {tc.weak_trend_percent}")
            
            print("\ndef calculate_adaptive_trailing(highest_price, current_adx):")
            print("    if current_adx >= ADX_STRONG_THRESHOLD:")
            print("        trailing_pct = STRONG_TREND_PERCENT")
            print("    elif current_adx <= ADX_WEAK_THRESHOLD:")
            print("        trailing_pct = WEAK_TREND_PERCENT")
            print("    else:")
            print("        ratio = (current_adx - ADX_WEAK_THRESHOLD) / (ADX_STRONG_THRESHOLD - ADX_WEAK_THRESHOLD)")
            print("        trailing_pct = WEAK_TREND_PERCENT + (STRONG_TREND_PERCENT - WEAK_TREND_PERCENT) * ratio")
            print("    return highest_price * (1 - trailing_pct/100)")
            
        elif tc.type == TrailingStopType.PROFIT_STEPPED:
            print("PROFIT_LEVELS = [")
            for profit_thresh, trail_pct in tc.profit_levels:
                print(f"    ({profit_thresh}, {trail_pct}),")
            print("]")
            
            print("\ndef calculate_stepped_trailing(highest_price, current_profit):")
            print("    trailing_pct = 1.0  # базовый")
            print("    for profit_threshold, step_trailing_pct in sorted(PROFIT_LEVELS, reverse=True):")
            print("        if current_profit >= profit_threshold:")
            print("            trailing_pct = step_trailing_pct")
            print("            break")
            print("    return highest_price * (1 - trailing_pct/100)")
        
        print(f"\n📊 ОЖИДАЕМЫЕ РЕЗУЛЬТАТЫ С НОВОЙ СТРАТЕГИЕЙ:")
        print(f"   💰 Общая доходность: {best.total_return:+.2f}%")
        print(f"   🎯 Винрейт: {best.win_rate:.1f}%")
        print(f"   📈 Средняя прибыль: {best.avg_return_per_trade:+.3f}%")
        print(f"   🚀 Максимальная сделка: {best.max_profit_per_trade:+.2f}%")
        print(f"   📊 Количество сделок: {best.total_trades}")
        print(f"   ⏱️ Средняя длительность: {best.avg_trade_duration_hours:.1f}ч")
        
        if best.trailing_stop_exits > 0:
            efficiency = best.trailing_stop_exits / best.total_trades * 100
            print(f"   🎯 Trailing stop эффективность: {efficiency:.1f}%")
        
        print(f"\n⚠️ ВАЖНЫЕ ЗАМЕЧАНИЯ:")
        print("• Исправлена логика приоритета выходов")
        print("• Trailing stop теперь работает БЕЗ конфликта с Take Profit")
        print("• Emergency TP используется только как защита от аномалий")
        print("• Тестируйте стратегию на малых объемах перед полным внедрением")

async def main():
    """Главная функция исправленного оптимизатора"""
    print("🎯 FIXED SBER TRAILING STOP OPTIMIZER")
    print("=" * 80)
    print("✅ Исправлена логика приоритета выходов")
    print("🚀 Trailing Stop теперь работает БЕЗ конфликта с Take Profit")
    print("⏱️ Процесс займет 4-6 минут...")
    print("=" * 80)
    
    # Получаем токен
    TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
    
    if not TINKOFF_TOKEN:
        logger.error("❌ TINKOFF_TOKEN не найден в переменных окружения")
        logger.error("🔧 Добавьте токен в Railway: Settings → Variables → TINKOFF_TOKEN")
        sys.exit(1)
    
    logger.info("✅ Токен найден, запускаем ИСПРАВЛЕННУЮ оптимизацию...")
    
    try:
        # Создаем исправленный оптимизатор
        optimizer = FixedTrailingOptimizer(TINKOFF_TOKEN)
        
        # Запускаем оптимизацию
        test_days = 90
        logger.info(f"🔬 Поиск оптимального trailing stop с ИСПРАВЛЕННОЙ логикой за {test_days} дней...")
        
        results = await optimizer.run_optimization(test_days=test_days)
        
        if not results:
            print("❌ Не удалось получить результаты оптимизации")
            return
        
        # Выводим исправленные результаты
        optimizer.print_fixed_results(results, top_n=12)
        
        # Дополнительная статистика
        print(f"\n📈 СТАТИСТИКА ИСПРАВЛЕННОЙ ОПТИМИЗАЦИИ:")
        print(f"   🧪 Протестировано стратегий: {len(results)}")
        
        # Анализ работы trailing stop
        working_trailing = [r for r in results if r.trailing_stop_exits > 0]
        print(f"   🎯 Стратегий с работающим trailing stop: {len(working_trailing)} ({len(working_trailing)/len(results)*100:.1f}%)")
        
        if working_trailing:
            avg_trailing_efficiency = np.mean([r.trailing_stop_exits/r.total_trades*100 for r in working_trailing if r.total_trades > 0])
            print(f"   📊 Средняя эффективность trailing stop: {avg_trailing_efficiency:.1f}%")
            
            best_trailing = max(working_trailing, key=lambda x: x.trailing_stop_exits/x.total_trades if x.total_trades > 0 else 0)
            best_efficiency = best_trailing.trailing_stop_exits/best_trailing.total_trades*100 if best_trailing.total_trades > 0 else 0
            print(f"   🏆 Лучшая эффективность trailing: {best_efficiency:.1f}% ({best_trailing.trailing_stop_exits}/{best_trailing.total_trades})")
        
        profitable = [r for r in results if r.total_return > 0]
        print(f"   💰 Прибыльных стратегий: {len(profitable)} ({len(profitable)/len(results)*100:.1f}%)")
        
        if profitable:
            best_return = max([r.total_return for r in profitable])
            avg_return = np.mean([r.total_return for r in profitable])
            best_max_profit = max([r.max_profit_per_trade for r in profitable])
            
            print(f"   🚀 Лучшая доходность: {best_return:.2f}%")
            print(f"   📊 Средняя доходность прибыльных: {avg_return:.2f}%")
            print(f"   💎 Максимальная сделка: {best_max_profit:.2f}%")
            
            # Сравнение с исходными результатами
            print(f"\n🔍 СРАВНЕНИЕ С ИСХОДНЫМИ РЕЗУЛЬТАТАМИ:")
            print(f"   📈 Средняя прибыль БЫЛО: +0.137%")
            print(f"   📈 Средняя прибыль СТАЛО: {results[0].avg_return_per_trade:+.3f}%")
            improvement = ((results[0].avg_return_per_trade - 0.137) / 0.137) * 100 if 0.137 != 0 else 0
            print(f"   🚀 УЛУЧШЕНИЕ: {improvement:+.0f}%!")
            
            print(f"   💎 Максимальная БЫЛО: +2.72%")
            print(f"   💎 Максимальная СТАЛО: {best_max_profit:+.2f}%")
            if best_max_profit > 2.72:
                max_improvement = ((best_max_profit - 2.72) / 2.72) * 100
                print(f"   ⬆️ РОСТ МАКСИМАЛЬНОЙ: {max_improvement:+.0f}%!")
        
        logger.info("✅ ИСПРАВЛЕННАЯ оптимизация trailing stop завершена успешно!")
        
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
