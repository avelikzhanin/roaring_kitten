#!/usr/bin/env python3
"""
Оптимизатор стратегии SBER Trading Bot
Тестирует разные параметры для улучшения результатов
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
import pandas as pd
import numpy as np
from dataclasses import dataclass
import itertools

# Предполагаем, что модули уже импортированы
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class StrategyParams:
    """Параметры стратегии"""
    ema_period: int = 20
    adx_period: int = 14
    adx_threshold: float = 23
    di_diff_threshold: float = 5
    volume_multiplier: float = 1.47
    stop_loss_pct: float = None  # Новый параметр
    take_profit_pct: float = None  # Новый параметр
    rsi_period: int = None  # Для RSI фильтра
    rsi_threshold: float = None  # RSI < этого значения
    
    def __str__(self):
        return f"EMA{self.ema_period}_ADX{self.adx_threshold}_VOL{self.volume_multiplier}"

@dataclass 
class OptimizationResult:
    """Результат оптимизации"""
    params: StrategyParams
    total_return: float
    win_rate: float
    total_trades: int
    avg_return: float
    max_drawdown: float
    sharpe_ratio: float
    
    def score(self) -> float:
        """Комплексная оценка стратегии"""
        # Учитываем доходность, винрейт и количество сделок
        return (self.total_return * 0.4 + 
                self.win_rate * 0.3 + 
                min(self.total_trades/10, 5) * 0.2 +
                max(0, self.sharpe_ratio) * 0.1)

class RSIIndicator:
    """RSI индикатор"""
    
    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
        """Расчет RSI"""
        if len(prices) < period + 1:
            return [np.nan] * len(prices)
        
        df = pd.DataFrame({'price': prices})
        df['change'] = df['price'].diff()
        df['gain'] = df['change'].where(df['change'] > 0, 0)
        df['loss'] = (-df['change']).where(df['change'] < 0, 0)
        
        # Сглаживание по Wilder
        df['avg_gain'] = df['gain'].ewm(alpha=1/period, adjust=False).mean()
        df['avg_loss'] = df['loss'].ewm(alpha=1/period, adjust=False).mean()
        
        df['rs'] = df['avg_gain'] / df['avg_loss']
        df['rsi'] = 100 - (100 / (1 + df['rs']))
        
        return df['rsi'].fillna(np.nan).tolist()

class EnhancedStrategyBacktester:
    """Расширенный бэктестер с дополнительными фильтрами"""
    
    def __init__(self, data_provider):
        self.data_provider = data_provider
        
    async def test_strategy(self, params: StrategyParams, days: int = 60) -> OptimizationResult:
        """Тестирование стратегии с заданными параметрами"""
        try:
            # Получаем данные (как в основном коде)
            hours = days * 24 + 200
            candles = await self.data_provider.get_candles(hours=hours)
            
            if len(candles) < 100:
                return self._empty_result(params)
                
            df = self.data_provider.candles_to_dataframe(candles)
            if df.empty:
                return self._empty_result(params)
            
            # Применяем стратегию
            signals, trades = self._apply_enhanced_strategy(df, params, days)
            
            # Рассчитываем метрики
            return self._calculate_metrics(params, trades, days)
            
        except Exception as e:
            logger.error(f"Ошибка тестирования {params}: {e}")
            return self._empty_result(params)
    
    def _apply_enhanced_strategy(self, df: pd.DataFrame, params: StrategyParams, days: int) -> Tuple[List, List]:
        """Применение улучшенной стратегии"""
        from src.indicators import TechnicalIndicators
        
        # Подготовка данных
        closes = df['close'].tolist()
        highs = df['high'].tolist()
        lows = df['low'].tolist()
        volumes = df['volume'].tolist()
        timestamps = df['timestamp'].tolist()
        
        # Расчет основных индикаторов
        ema = TechnicalIndicators.calculate_ema(closes, params.ema_period)
        adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, params.adx_period)
        
        # RSI если нужен
        rsi = []
        if params.rsi_period:
            rsi = RSIIndicator.calculate_rsi(closes, params.rsi_period)
        
        # Средний объем
        df['avg_volume'] = df['volume'].rolling(window=20, min_periods=1).mean()
        avg_volumes = df['avg_volume'].tolist()
        
        # Определяем тестовый период
        end_time = timestamps[-1]
        start_time = end_time - timedelta(days=days)
        test_start_idx = 200  # Минимум для прогрева индикаторов
        
        for i in range(test_start_idx, len(timestamps)):
            if timestamps[i] >= start_time:
                test_start_idx = i
                break
        
        # Поиск сигналов
        signals = []
        trades = []
        current_trade = None
        
        for i in range(test_start_idx, len(timestamps)):
            try:
                price = closes[i]
                
                # Проверяем базовые индикаторы
                if (i >= len(ema) or i >= len(adx_data['adx']) or 
                    pd.isna(ema[i]) or pd.isna(adx_data['adx'][i])):
                    continue
                
                # Базовые условия
                conditions = [
                    price > ema[i],  # EMA фильтр
                    adx_data['adx'][i] > params.adx_threshold,  # ADX фильтр
                    adx_data['plus_di'][i] > adx_data['minus_di'][i],  # Направление
                    adx_data['plus_di'][i] - adx_data['minus_di'][i] > params.di_diff_threshold,  # Разница DI
                    volumes[i] > avg_volumes[i] * params.volume_multiplier  # Объем
                ]
                
                # RSI фильтр (если включен)
                if params.rsi_period and i < len(rsi) and not pd.isna(rsi[i]):
                    conditions.append(rsi[i] < params.rsi_threshold)
                
                # Временной фильтр (избегаем обеденное время)
                hour = timestamps[i].hour
                if hour >= 13 and hour <= 15:  # Обеденный флет
                    conditions.append(False)
                
                signal_active = all(conditions)
                
                # Логика входа/выхода
                if signal_active and current_trade is None:
                    # Вход в позицию
                    current_trade = {
                        'entry_time': timestamps[i],
                        'entry_price': price,
                        'highest_price': price
                    }
                    signals.append(('BUY', timestamps[i], price))
                
                elif current_trade is not None:
                    # Обновляем максимальную цену для трейлинга
                    current_trade['highest_price'] = max(current_trade['highest_price'], price)
                    
                    # Условия выхода
                    exit_conditions = [
                        not signal_active,  # Базовые условия не выполняются
                    ]
                    
                    # Stop Loss
                    if params.stop_loss_pct:
                        stop_loss_price = current_trade['entry_price'] * (1 - params.stop_loss_pct/100)
                        exit_conditions.append(price <= stop_loss_price)
                    
                    # Take Profit
                    if params.take_profit_pct:
                        take_profit_price = current_trade['entry_price'] * (1 + params.take_profit_pct/100)
                        exit_conditions.append(price >= take_profit_price)
                    
                    if any(exit_conditions):
                        # Выход из позиции
                        profit_pct = ((price - current_trade['entry_price']) / current_trade['entry_price']) * 100
                        duration_hours = int((timestamps[i] - current_trade['entry_time']).total_seconds() / 3600)
                        
                        trades.append({
                            'entry_time': current_trade['entry_time'],
                            'exit_time': timestamps[i],
                            'entry_price': current_trade['entry_price'],
                            'exit_price': price,
                            'profit_pct': profit_pct,
                            'duration_hours': duration_hours
                        })
                        
                        signals.append(('SELL', timestamps[i], price))
                        current_trade = None
                
            except Exception as e:
                continue
        
        # Закрываем открытую позицию
        if current_trade is not None:
            price = closes[-1]
            profit_pct = ((price - current_trade['entry_price']) / current_trade['entry_price']) * 100
            duration_hours = int((timestamps[-1] - current_trade['entry_time']).total_seconds() / 3600)
            
            trades.append({
                'entry_time': current_trade['entry_time'],
                'exit_time': timestamps[-1],
                'entry_price': current_trade['entry_price'],
                'exit_price': price,
                'profit_pct': profit_pct,
                'duration_hours': duration_hours
            })
        
        return signals, trades
    
    def _calculate_metrics(self, params: StrategyParams, trades: List[Dict], days: int) -> OptimizationResult:
        """Расчет метрик стратегии"""
        if not trades:
            return self._empty_result(params)
        
        profits = [t['profit_pct'] for t in trades]
        profitable = [p for p in profits if p > 0]
        
        total_return = sum(profits)
        win_rate = len(profitable) / len(profits) * 100
        avg_return = np.mean(profits)
        max_drawdown = min(profits) if profits else 0
        
        # Sharpe ratio (упрощенный)
        if len(profits) > 1:
            sharpe_ratio = np.mean(profits) / np.std(profits) if np.std(profits) > 0 else 0
        else:
            sharpe_ratio = 0
        
        return OptimizationResult(
            params=params,
            total_return=total_return,
            win_rate=win_rate,
            total_trades=len(trades),
            avg_return=avg_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio
        )
    
    def _empty_result(self, params: StrategyParams) -> OptimizationResult:
        """Пустой результат для неудачных тестов"""
        return OptimizationResult(
            params=params,
            total_return=0,
            win_rate=0,
            total_trades=0,
            avg_return=0,
            max_drawdown=0,
            sharpe_ratio=0
        )

class StrategyOptimizer:
    """Оптимизатор параметров стратегии"""
    
    def __init__(self, data_provider):
        self.backtester = EnhancedStrategyBacktester(data_provider)
    
    async def optimize_parameters(self, days: int = 60) -> List[OptimizationResult]:
        """Оптимизация параметров стратегии"""
        logger.info("🔧 Запуск оптимизации параметров...")
        
        # Определяем диапазоны параметров для тестирования
        parameter_ranges = {
            'ema_period': [15, 20, 25],
            'adx_threshold': [20, 23, 25, 28],
            'volume_multiplier': [1.3, 1.47, 1.6, 1.8],
            'stop_loss_pct': [None, 0.5, 1.0],
            'take_profit_pct': [None, 1.5, 2.0],
            'rsi_filter': [
                (None, None),  # Без RSI
                (14, 70),      # RSI 14, порог 70
                (14, 65),      # RSI 14, порог 65
            ]
        }
        
        results = []
        total_combinations = (len(parameter_ranges['ema_period']) * 
                            len(parameter_ranges['adx_threshold']) * 
                            len(parameter_ranges['volume_multiplier']) * 
                            len(parameter_ranges['stop_loss_pct']) * 
                            len(parameter_ranges['take_profit_pct']) * 
                            len(parameter_ranges['rsi_filter']))
        
        logger.info(f"🧪 Тестируем {total_combinations} комбинаций параметров...")
        
        tested = 0
        for ema_period in parameter_ranges['ema_period']:
            for adx_threshold in parameter_ranges['adx_threshold']:
                for volume_multiplier in parameter_ranges['volume_multiplier']:
                    for stop_loss in parameter_ranges['stop_loss_pct']:
                        for take_profit in parameter_ranges['take_profit_pct']:
                            for rsi_period, rsi_threshold in parameter_ranges['rsi_filter']:
                                
                                params = StrategyParams(
                                    ema_period=ema_period,
                                    adx_threshold=adx_threshold,
                                    volume_multiplier=volume_multiplier,
                                    stop_loss_pct=stop_loss,
                                    take_profit_pct=take_profit,
                                    rsi_period=rsi_period,
                                    rsi_threshold=rsi_threshold
                                )
                                
                                result = await self.backtester.test_strategy(params, days)
                                results.append(result)
                                
                                tested += 1
                                if tested % 10 == 0:
                                    logger.info(f"⏳ Протестировано {tested}/{total_combinations}...")
        
        # Сортируем по комплексной оценке
        results.sort(key=lambda x: x.score(), reverse=True)
        
        logger.info(f"✅ Оптимизация завершена! Найдено {len(results)} результатов")
        return results
    
    def print_top_results(self, results: List[OptimizationResult], top_n: int = 10):
        """Вывод лучших результатов"""
        print(f"\n🏆 ТОП-{top_n} ЛУЧШИХ СТРАТЕГИЙ:")
        print("="*100)
        
        for i, result in enumerate(results[:top_n], 1):
            print(f"\n{i:2d}. ОЦЕНКА: {result.score():.2f}")
            print(f"    📊 Доходность: {result.total_return:.2f}% | Винрейт: {result.win_rate:.1f}% | Сделок: {result.total_trades}")
            
            params = result.params
            print(f"    ⚙️ EMA: {params.ema_period} | ADX: {params.adx_threshold} | Объем: {params.volume_multiplier}")
            
            extras = []
            if params.stop_loss_pct:
                extras.append(f"SL: {params.stop_loss_pct}%")
            if params.take_profit_pct:
                extras.append(f"TP: {params.take_profit_pct}%")
            if params.rsi_period:
                extras.append(f"RSI({params.rsi_period})<{params.rsi_threshold}")
            
            if extras:
                print(f"    🎯 Доп. фильтры: {' | '.join(extras)}")
            
            print(f"    📈 Средняя прибыль: {result.avg_return:.3f}% | Макс просадка: {result.max_drawdown:.2f}%")

async def main():
    """Главная функция оптимизации"""
    print("🚀 SBER Strategy Optimizer")
    print("-" * 60)
    
    tinkoff_token = os.getenv('TINKOFF_TOKEN')
    if not tinkoff_token:
        print("❌ Не найден TINKOFF_TOKEN")
        return
    
    try:
        # Импортируем провайдер данных
        from src.data_provider import TinkoffDataProvider
        
        data_provider = TinkoffDataProvider(tinkoff_token)
        optimizer = StrategyOptimizer(data_provider)
        
        # Запускаем оптимизацию
        results = await optimizer.optimize_parameters(days=60)
        
        # Выводим результаты
        optimizer.print_top_results(results, top_n=15)
        
        print(f"\n💡 РЕКОМЕНДАЦИИ:")
        best = results[0]
        print(f"✅ Лучшая стратегия показала доходность {best.total_return:.2f}% за 60 дней")
        print(f"🎯 Винрейт: {best.win_rate:.1f}% ({best.total_trades} сделок)")
        print(f"⚙️ Параметры: EMA{best.params.ema_period}, ADX>{best.params.adx_threshold}, Volume×{best.params.volume_multiplier}")
        
        if best.params.stop_loss_pct or best.params.take_profit_pct:
            print(f"🛡️ Управление рисками улучшило результат!")
        
    except Exception as e:
        logger.error(f"❌ Ошибка оптимизации: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
