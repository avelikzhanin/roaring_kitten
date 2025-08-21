#!/usr/bin/env python3
"""
Полный оптимизатор стратегии SBER для Railway
Все в одном файле - без внешних импортов
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

# Импорты Tinkoff API
from tinkoff.invest import Client, RequestError, CandleInterval, HistoricCandle
from tinkoff.invest.utils import now

# Настройка логирования для Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

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
    trailing_stop_pct: Optional[float] = None
    
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
    
    def overall_score(self) -> float:
        """Комплексная оценка стратегии"""
        return_score = min(self.total_return / 10, 10)
        winrate_score = self.win_rate / 10
        trades_score = min(self.total_trades / 5, 5)
        drawdown_penalty = max(0, abs(self.max_drawdown) / 2)
        
        return return_score * 0.4 + winrate_score * 0.3 + trades_score * 0.2 - drawdown_penalty * 0.1

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
    def calculate_momentum(prices: List[float], periods: int) -> List[float]:
        """Momentum индикатор"""
        if len(prices) < periods:
            return [np.nan] * len(prices)
        
        momentum = []
        for i in range(len(prices)):
            if i < periods:
                momentum.append(np.nan)
            else:
                mom = (prices[i] - prices[i - periods]) / prices[i - periods] * 100
                momentum.append(mom)
        
        return momentum
    
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

class EnhancedStrategyOptimizer:
    """Основной оптимизатор стратегии"""
    
    def __init__(self, tinkoff_token: str):
        self.data_provider = DataProvider(tinkoff_token)
    
    async def run_optimization(self, test_days: int = 90) -> List[OptimizationResult]:
        """Запуск полной оптимизации"""
        logger.info(f"🚀 Запуск оптимизации стратегии SBER за {test_days} дней...")
        
        # Получаем данные с запасом для индикаторов
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
            
            # Генерируем параметры для тестирования
            parameter_combinations = self._generate_parameter_combinations()
            
            logger.info(f"🧪 Будем тестировать {len(parameter_combinations)} комбинаций...")
            
            # Тестируем каждую комбинацию
            results = []
            for i, params in enumerate(parameter_combinations, 1):
                try:
                    if i % 10 == 0:
                        logger.info(f"⏳ Прогресс: {i}/{len(parameter_combinations)} ({i/len(parameter_combinations)*100:.1f}%)")
                    
                    result = await self._test_strategy_params(df, params, test_days)
                    if result:
                        results.append(result)
                        
                except Exception as e:
                    continue
            
            # Сортируем по комплексной оценке
            results.sort(key=lambda x: x.overall_score(), reverse=True)
            
            logger.info(f"✅ Оптимизация завершена! Найдено {len(results)} результатов")
            return results
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка оптимизации: {e}")
            return []
    
    def _generate_parameter_combinations(self) -> List[OptimizedParams]:
        """Генерация комбинаций параметров"""
        combinations = []
        
        # Основные параметры (сокращено для Railway)
        ema_periods = [15, 20, 25]
        adx_thresholds = [20, 23, 25, 28]
        volume_multipliers = [1.2, 1.47, 1.6, 1.8]
        
        # Управление рисками
        stop_losses = [None, 0.5, 0.8, 1.0]
        take_profits = [None, 1.2, 1.5, 2.0]
        
        # Фильтры (упрощено)
        rsi_configs = [(None, None), (14, 70), (14, 65)]
        momentum_configs = [None, 3, 5]
        lunch_filters = [False, True]
        
        # Ограничиваем комбинации для Railway
        count = 0
        max_combinations = 100
        
        for ema in ema_periods:
            for adx in adx_thresholds[:3]:
                for vol in volume_multipliers[:3]:
                    for sl in stop_losses[:3]:
                        for tp in take_profits[:3]:
                            for rsi_period, rsi_thresh in rsi_configs:
                                for momentum in momentum_configs[:2]:
                                    for lunch_filter in lunch_filters:
                                        
                                        if count >= max_combinations:
                                            return combinations
                                        
                                        params = OptimizedParams(
                                            ema_period=ema,
                                            adx_threshold=adx,
                                            volume_multiplier=vol,
                                            stop_loss_pct=sl,
                                            take_profit_pct=tp,
                                            rsi_period=rsi_period,
                                            rsi_overbought=rsi_thresh,
                                            momentum_periods=momentum,
                                            avoid_lunch_time=lunch_filter
                                        )
                                        combinations.append(params)
                                        count += 1
        
        return combinations
    
    async def _test_strategy_params(self, df: pd.DataFrame, params: OptimizedParams, test_days: int) -> Optional[OptimizationResult]:
        """Тестирование конкретной комбинации параметров"""
        try:
            trades = self._simulate_trading(df, params, test_days)
            
            if not trades:
                return None
            
            return self._calculate_metrics(params, trades)
            
        except Exception as e:
            return None
    
    def _simulate_trading(self, df: pd.DataFrame, params: OptimizedParams, test_days: int) -> List[Dict]:
        """Симуляция торговли"""
        # Подготовка данных
        closes = df['close'].tolist()
        highs = df['high'].tolist()
        lows = df['low'].tolist()
        volumes = df['volume'].tolist()
        timestamps = df['timestamp'].tolist()
        
        # Расчет индикаторов
        ema = TechnicalIndicators.calculate_ema(closes, params.ema_period)
        adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
        
        # Дополнительные индикаторы
        rsi = []
        if params.rsi_period:
            rsi = TechnicalIndicators.calculate_rsi(closes, params.rsi_period)
        
        momentum = []
        if params.momentum_periods:
            momentum = TechnicalIndicators.calculate_momentum(closes, params.momentum_periods)
        
        # Средний объем
        df['avg_volume'] = df['volume'].rolling(window=20, min_periods=1).mean()
        avg_volumes = df['avg_volume'].tolist()
        
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
                
                # Momentum фильтр
                if params.momentum_periods and i < len(momentum) and not pd.isna(momentum[i]):
                    conditions.append(momentum[i] > 0)
                
                # Временной фильтр (обеденное время)
                if params.avoid_lunch_time:
                    hour = timestamp.hour
                    if 13 <= hour <= 15:
                        conditions.append(False)
                
                # Торговые часы
                hour = timestamp.hour
                if not (params.trading_hours_start <= hour <= params.trading_hours_end):
                    conditions.append(False)
                
                signal_active = all(conditions)
                
                # Логика входа в позицию
                if signal_active and current_trade is None:
                    current_trade = {
                        'entry_time': timestamp,
                        'entry_price': price,
                        'highest_price': price
                    }
                
                # Управление позицией
                elif current_trade is not None:
                    current_trade['highest_price'] = max(current_trade['highest_price'], price)
                    
                    exit_reasons = []
                    
                    # Базовый выход
                    if not signal_active:
                        exit_reasons.append('signal_lost')
                    
                    # Stop Loss
                    if params.stop_loss_pct:
                        stop_price = current_trade['entry_price'] * (1 - params.stop_loss_pct/100)
                        if price <= stop_price:
                            exit_reasons.append('stop_loss')
                    
                    # Take Profit
                    if params.take_profit_pct:
                        tp_price = current_trade['entry_price'] * (1 + params.take_profit_pct/100)
                        if price >= tp_price:
                            exit_reasons.append('take_profit')
                    
                    # Trailing Stop
                    if params.trailing_stop_pct:
                        trail_price = current_trade['highest_price'] * (1 - params.trailing_stop_pct/100)
                        if price <= trail_price:
                            exit_reasons.append('trailing_stop')
                    
                    # Выход из позиции
                    if exit_reasons:
                        profit_pct = ((price - current_trade['entry_price']) / current_trade['entry_price']) * 100
                        duration = (timestamp - current_trade['entry_time']).total_seconds() / 3600
                        
                        trades.append({
                            'entry_time': current_trade['entry_time'],
                            'exit_time': timestamp,
                            'entry_price': current_trade['entry_price'],
                            'exit_price': price,
                            'profit_pct': profit_pct,
                            'duration_hours': duration,
                            'exit_reason': exit_reasons[0]
                        })
                        
                        current_trade = None
                
            except Exception as e:
                continue
        
        # Закрываем открытую позицию
        if current_trade is not None:
            profit_pct = ((closes[-1] - current_trade['entry_price']) / current_trade['entry_price']) * 100
            duration = (timestamps[-1] - current_trade['entry_time']).total_seconds() / 3600
            
            trades.append({
                'entry_time': current_trade['entry_time'],
                'exit_time': timestamps[-1],
                'entry_price': current_trade['entry_price'],
                'exit_price': closes[-1],
                'profit_pct': profit_pct,
                'duration_hours': duration,
                'exit_reason': 'end_of_data'
            })
        
        return trades
    
    def _calculate_metrics(self, params: OptimizedParams, trades: List[Dict]) -> OptimizationResult:
        """Расчет метрик результатов"""
        if not trades:
            return OptimizationResult(
                params=params,
                total_return=0, win_rate=0, total_trades=0, profitable_trades=0,
                avg_return_per_trade=0, max_drawdown=0, avg_trade_duration_hours=0,
                sharpe_ratio=0, max_consecutive_losses=0
            )
        
        profits = [t['profit_pct'] for t in trades]
        profitable = [p for p in profits if p > 0]
        durations = [t['duration_hours'] for t in trades]
        
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
            max_consecutive_losses=max_consecutive_losses
        )
    
    def print_results(self, results: List[OptimizationResult], top_n: int = 10):
        """Вывод результатов оптимизации"""
        if not results:
            print("❌ Нет результатов для отображения")
            return
        
        print(f"\n{'='*80}")
        print(f"🏆 ТОП-{top_n} ОПТИМАЛЬНЫХ СТРАТЕГИЙ SBER")
        print(f"{'='*80}")
        
        for i, result in enumerate(results[:top_n], 1):
            params = result.params
            
            print(f"\n{i:2d}. ОЦЕНКА: {result.overall_score():.2f} | ДОХОДНОСТЬ: {result.total_return:+.2f}%")
            print(f"    📊 Винрейт: {result.win_rate:.1f}% | Сделок: {result.total_trades}")
            print(f"    ⚙️ EMA: {params.ema_period} | ADX: {params.adx_threshold} | Объем: ×{params.volume_multiplier}")
            
            # Управление рисками
            risk_params = []
            if params.stop_loss_pct:
                risk_params.append(f"SL: -{params.stop_loss_pct}%")
            if params.take_profit_pct:
                risk_params.append(f"TP: +{params.take_profit_pct}%")
            
            if risk_params:
                print(f"    🛡️ Риски: {' | '.join(risk_params)}")
            
            # Фильтры
            filters = []
            if params.rsi_period:
                filters.append(f"RSI({params.rsi_period})<{params.rsi_overbought}")
            if params.avoid_lunch_time:
                filters.append("Без обеда")
                
            if filters:
                print(f"    🎯 Фильтры: {' | '.join(filters)}")
            
            print(f"    📈 Средняя: {result.avg_return_per_trade:+.2f}% | Просадка: {result.max_drawdown:.2f}%")
        
        # Рекомендации
        print(f"\n{'='*80}")
        print("💡 ПРАКТИЧЕСКИЕ РЕКОМЕНДАЦИИ:")
        
        best = results[0]
        print(f"🎯 ЛУЧШАЯ СТРАТЕГИЯ (оценка: {best.overall_score():.2f}):")
        print(f"   • EMA период: {best.params.ema_period}")
        print(f"   • ADX порог: {best.params.adx_threshold}")  
        print(f"   • Объем множитель: {best.params.volume_multiplier}")
        
        if best.params.stop_loss_pct:
            print(f"   • Stop Loss: -{best.params.stop_loss_pct}%")
        if best.params.take_profit_pct:
            print(f"   • Take Profit: +{best.params.take_profit_pct}%")
        if best.params.rsi_period:
            print(f"   • RSI фильтр: RSI({best.params.rsi_period}) < {best.params.rsi_overbought}")
        if best.params.avoid_lunch_time:
            print(f"   • Временной фильтр: Избегать 13:00-15:00")
        
        print(f"\n📊 ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:")
        print(f"   💰 Доходность: {best.total_return:+.2f}%")
        print(f"   🎲 Винрейт: {best.win_rate:.1f}%")
        print(f"   📈 Количество сделок: {best.total_trades}")
        print(f"   ⏱️ Средняя длительность: {best.avg_trade_duration_hours:.1f}ч")
        
        # Код для внедрения
        print(f"\n🔧 КОД ДЛЯ ВНЕДРЕНИЯ В БОТ:")
        print("=" * 50)
        print("# Замените параметры в вашем коде на:")
        print(f"EMA_PERIOD = {best.params.ema_period}")
        print(f"ADX_THRESHOLD = {best.params.adx_threshold}")
        print(f"VOLUME_MULTIPLIER = {best.params.volume_multiplier}")
        
        if best.params.stop_loss_pct:
            print(f"STOP_LOSS_PCT = {best.params.stop_loss_pct}")
        if best.params.take_profit_pct:
            print(f"TAKE_PROFIT_PCT = {best.params.take_profit_pct}")
        if best.params.rsi_period:
            print(f"RSI_PERIOD = {best.params.rsi_period}")
            print(f"RSI_OVERBOUGHT = {best.params.rsi_overbought}")
        if best.params.avoid_lunch_time:
            print("AVOID_LUNCH_TIME = True  # Избегать 13:00-15:00")
        
        # Предупреждения
        print(f"\n⚠️ ВАЖНО:")
        print("• Результаты основаны на исторических данных")
        print("• Тестируйте стратегию на малых суммах")
        print("• Рыночные условия могут измениться")
        print("• Используйте управление рисками")

async def main():
    """Главная функция для Railway"""
    print("🚀 SBER Strategy Optimizer для Railway")
    print("=" * 60)
    print("📊 Поиск оптимальных параметров торговой стратегии")
    print("⏱️ Процесс займет 3-5 минут...")
    print("=" * 60)
    
    # Получаем токен из переменных окружения
    TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
    
    if not TINKOFF_TOKEN:
        logger.error("❌ TINKOFF_TOKEN не найден в переменных окружения")
        logger.error("🔧 Добавьте токен в Railway: Settings → Variables → TINKOFF_TOKEN")
        sys.exit(1)
    
    logger.info("✅ Токен найден, запускаем оптимизацию...")
    
    try:
        # Создаем оптимизатор
        optimizer = EnhancedStrategyOptimizer(TINKOFF_TOKEN)
        
        # Запускаем оптимизацию (ограничиваем 60 дней для Railway)
        test_days = 60
        logger.info(f"🔬 Поиск оптимальных параметров за {test_days} дней...")
        
        results = await optimizer.run_optimization(test_days=test_days)
        
        if not results:
            print("❌ Не удалось получить результаты оптимизации")
            return
        
        # Выводим результаты
        optimizer.print_results(results, top_n=10)
        
        # Дополнительная статистика
        print(f"\n📈 СТАТИСТИКА ОПТИМИЗАЦИИ:")
        print(f"   🧪 Протестировано стратегий: {len(results)}")
        
        profitable = [r for r in results if r.total_return > 0]
        print(f"   💰 Прибыльных: {len(profitable)} ({len(profitable)/len(results)*100:.1f}%)")
        
        if profitable:
            avg_profitable = np.mean([r.total_return for r in profitable])
            print(f"   📊 Средняя доходность прибыльных: {avg_profitable:.2f}%")
        
        high_winrate = [r for r in results if r.win_rate >= 60]
        print(f"   🎯 С винрейтом ≥60%: {len(high_winrate)}")
        
        logger.info("✅ Оптимизация завершена успешно!")
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    # Для Railway
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Оптимизация прервана пользователем")
    except Exception as e:
        print(f"❌ Фатальная ошибка: {e}")
        sys.exit(1)
