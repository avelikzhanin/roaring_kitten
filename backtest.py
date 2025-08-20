#!/usr/bin/env python3
"""
Окончательно исправленный бэктестинг SBER Trading Bot
Исправлена ошибка форматирования f-string
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
import pandas as pd
import numpy as np
from dataclasses import dataclass

# Добавляем путь к нашим модулям
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from src.data_provider import TinkoffDataProvider
    from src.indicators import TechnicalIndicators
except ImportError as e:
    print(f"❌ Ошибка импорта модулей: {e}")
    print("Убедитесь, что файлы находятся в папке src/")
    sys.exit(1)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

@dataclass
class Trade:
    """Структура сделки"""
    entry_time: datetime
    exit_time: Optional[datetime] = None
    entry_price: float = 0.0
    exit_price: float = 0.0
    profit_pct: float = 0.0
    duration_hours: int = 0
    
    def is_closed(self) -> bool:
        return self.exit_time is not None
    
    def is_profitable(self) -> bool:
        return self.profit_pct > 0

@dataclass
class BacktestResults:
    """Результаты бэктестинга"""
    total_signals: int = 0
    buy_signals: int = 0
    sell_signals: int = 0
    total_trades: int = 0
    profitable_trades: int = 0
    winrate: float = 0.0
    total_return: float = 0.0
    avg_return_per_trade: float = 0.0
    max_profit: float = 0.0
    max_loss: float = 0.0
    avg_duration_hours: float = 0.0
    annual_return_estimate: float = 0.0
    trades: List[Trade] = None
    
    def __post_init__(self):
        if self.trades is None:
            self.trades = []

class SBERBacktester:
    """Класс для бэктестинга стратегии SBER"""
    
    def __init__(self, tinkoff_token: str):
        self.data_provider = TinkoffDataProvider(tinkoff_token)
        
    async def run_backtest(self, days: int = 30) -> BacktestResults:
        """Запуск бэктестинга"""
        logger.info(f"🔄 Запуск бэктестинга за {days} дней...")
        
        try:
            # Получаем данные
            hours = days * 24 + 160  # Добавляем буфер для расчета индикаторов
            candles = await self.data_provider.get_candles(hours=hours)
            
            if len(candles) < 100:
                raise ValueError(f"Недостаточно данных: {len(candles)} свечей")
            
            # Создаем DataFrame
            df = self.data_provider.candles_to_dataframe(candles)
            if df.empty:
                raise ValueError("Пустой DataFrame")
            
            logger.info(f"✅ Получено {len(candles)} свечей")
            logger.info(f"🔍 Анализ данных и поиск сигналов...")
            
            # Расчет индикаторов
            results = self._analyze_data(df, days)
            
            logger.info(f"🎯 Всего сигналов: {results.total_signals} (BUY: {results.buy_signals})")
            logger.info(f"💰 Создано сделок: {results.total_trades}")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Ошибка бэктестинга: {e}")
            raise
    
    def _analyze_data(self, df: pd.DataFrame, target_days: int) -> BacktestResults:
        """Анализ данных и генерация сигналов"""
        logger.info("📊 Расчет индикаторов...")
        
        # Подготовка данных
        closes = df['close'].tolist()
        highs = df['high'].tolist()
        lows = df['low'].tolist()
        volumes = df['volume'].tolist()
        timestamps = df['timestamp'].tolist()
        
        # Расчет индикаторов
        ema20 = TechnicalIndicators.calculate_ema(closes, 20)
        adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
        
        # Средний объем за 20 периодов
        df['avg_volume_20'] = df['volume'].rolling(window=20, min_periods=1).mean()
        avg_volumes = df['avg_volume_20'].tolist()
        
        # Определяем период тестирования (исключаем первые 160 свечей для прогрева индикаторов)
        start_idx = 160
        
        # Ограничиваем период target_days днями от конца
        end_time = timestamps[-1]
        start_time = end_time - timedelta(days=target_days)
        
        # Находим начальный индекс для тестового периода
        test_start_idx = start_idx
        for i in range(start_idx, len(timestamps)):
            if timestamps[i] >= start_time:
                test_start_idx = i
                break
        
        logger.info(f"📈 Тестовый период: {len(timestamps) - test_start_idx} свечей")
        
        # Поиск сигналов
        results = BacktestResults()
        trades = []
        current_trade = None
        
        signal_count = 0
        buy_count = 0
        sell_count = 0
        
        for i in range(test_start_idx, len(timestamps)):
            try:
                # Текущие значения
                price = closes[i]
                ema_val = ema20[i] if i < len(ema20) else np.nan
                adx_val = adx_data['adx'][i] if i < len(adx_data['adx']) else np.nan
                plus_di = adx_data['plus_di'][i] if i < len(adx_data['plus_di']) else np.nan
                minus_di = adx_data['minus_di'][i] if i < len(adx_data['minus_di']) else np.nan
                volume = volumes[i]
                avg_volume = avg_volumes[i]
                
                # Проверяем на NaN
                if any(pd.isna(val) for val in [ema_val, adx_val, plus_di, minus_di]):
                    continue
                
                # Условия сигнала покупки
                conditions = [
                    price > ema_val,                            # Цена выше EMA20
                    adx_val > 23,                              # ADX больше 23
                    plus_di > minus_di,                        # +DI больше -DI
                    plus_di - minus_di > 5,                    # Существенная разница
                    volume > avg_volume * 1.47                 # Объем на 47% выше среднего
                ]
                
                buy_signal = all(conditions)
                
                if buy_signal and current_trade is None:
                    # Новый сигнал покупки
                    current_trade = Trade(
                        entry_time=timestamps[i],
                        entry_price=price
                    )
                    
                    signal_count += 1
                    buy_count += 1
                    
                    logger.info(f"📈 BUY #{buy_count}: {timestamps[i].strftime('%d.%m %H:%M')} = {price:.2f}₽")
                    
                elif not buy_signal and current_trade is not None:
                    # Закрываем позицию
                    current_trade.exit_time = timestamps[i]
                    current_trade.exit_price = price
                    current_trade.profit_pct = ((price - current_trade.entry_price) / current_trade.entry_price) * 100
                    current_trade.duration_hours = int((current_trade.exit_time - current_trade.entry_time).total_seconds() / 3600)
                    
                    trades.append(current_trade)
                    current_trade = None
                    
                    signal_count += 1
                    sell_count += 1
                    
                    logger.info(f"📉 SELL: {timestamps[i].strftime('%d.%m %H:%M')} = {price:.2f}₽")
                    
            except Exception as e:
                logger.error(f"Ошибка обработки индекса {i}: {e}")
                continue
        
        # Закрываем последнюю позицию если она открыта
        if current_trade is not None:
            current_trade.exit_time = timestamps[-1]
            current_trade.exit_price = closes[-1]
            current_trade.profit_pct = ((closes[-1] - current_trade.entry_price) / current_trade.entry_price) * 100
            current_trade.duration_hours = int((current_trade.exit_time - current_trade.entry_time).total_seconds() / 3600)
            trades.append(current_trade)
        
        # Расчет статистики
        results.total_signals = signal_count
        results.buy_signals = buy_count
        results.sell_signals = sell_count
        results.total_trades = len(trades)
        results.trades = trades
        
        if trades:
            completed_trades = [t for t in trades if t.is_closed()]
            
            if completed_trades:
                results.profitable_trades = sum(1 for t in completed_trades if t.is_profitable())
                results.winrate = (results.profitable_trades / len(completed_trades)) * 100
                
                profits = [t.profit_pct for t in completed_trades]
                results.total_return = sum(profits)
                results.avg_return_per_trade = np.mean(profits)
                results.max_profit = max(profits)
                results.max_loss = min(profits)
                
                durations = [t.duration_hours for t in completed_trades if t.duration_hours > 0]
                results.avg_duration_hours = np.mean(durations) if durations else 0
                
                # Оценка годовой доходности
                if target_days > 0:
                    results.annual_return_estimate = (results.total_return / target_days) * 365
        
        return results
    
    def print_results(self, results: BacktestResults, days: int):
        """Красивый вывод результатов с исправленным форматированием"""
        print("\n" + "="*70)
        print(f"🎯 БЭКТЕСТИНГ SBER ЗА {days} ДНЕЙ")
        print("="*70)
        
        print(f"📊 СИГНАЛЫ:")
        print(f" • Всего: {results.total_signals}")
        print(f" • Покупки: {results.buy_signals}")
        print(f" • Продажи: {results.sell_signals}")
        
        print(f"\n💼 СДЕЛКИ:")
        print(f" • Количество: {results.total_trades}")
        print(f" • Прибыльные: {results.profitable_trades}")
        print(f" • Винрейт: {results.winrate:.1f}%")
        
        print(f"\n💰 ДОХОДНОСТЬ:")
        print(f" • Общая: {results.total_return:.2f}%")
        print(f" • Средняя на сделку: {results.avg_return_per_trade:.2f}%")
        print(f" • Макс прибыль: {results.max_profit:.2f}%")
        print(f" • Макс убыток: {results.max_loss:.2f}%")
        print(f" • Годовая (оценка): {results.annual_return_estimate:.1f}%")
        
        print(f"\n⏰ ВРЕМЯ:")
        print(f" • Средняя длительность: {results.avg_duration_hours:.1f}ч")
        
        if results.trades and len(results.trades) <= 20:  # Показываем детали только если сделок не много
            print(f"\n📋 СДЕЛКИ:")
            try:
                for i, trade in enumerate(results.trades, 1):
                    if trade.is_closed():
                        # ИСПРАВЛЕНО: Убрано условное форматирование внутри f-string
                        entry_str = trade.entry_time.strftime("%d.%m %H:%M")
                        exit_str = trade.exit_time.strftime("%d.%m %H:%M") if trade.exit_time else "N/A"
                        entry_price_str = f"{trade.entry_price:.2f}₽"
                        exit_price_str = f"{trade.exit_price:.2f}₽"
                        profit_str = f"{trade.profit_pct:+.2f}%"
                        
                        print(f" {i:2d}. {entry_str} → {exit_str} | "
                              f"{entry_price_str} → {exit_price_str} | "
                              f"{profit_str} | {trade.duration_hours}ч")
                    else:
                        entry_str = trade.entry_time.strftime("%d.%m %H:%M")
                        entry_price_str = f"{trade.entry_price:.2f}₽"
                        
                        print(f" {i:2d}. {entry_str} → [открыта] | "
                              f"{entry_price_str} → [текущая] | "
                              f"[в процессе]")
            except Exception as e:
                logger.error(f"Ошибка вывода деталей сделок: {e}")
                print(" [Ошибка при выводе деталей сделок]")
        
        print("\n" + "="*70)
        print()

async def main():
    """Главная функция"""
    print("🚀 SBER Trading Bot - Независимый бэктестинг")
    print("-" * 60)
    
    # Получаем токен
    tinkoff_token = os.getenv('TINKOFF_TOKEN')
    
    if not tinkoff_token:
        print("❌ Не найден TINKOFF_TOKEN в переменных окружения")
        print("Установите переменную окружения: export TINKOFF_TOKEN='your_token'")
        return
    
    logger.info("✅ Токен найден, запускаем бэктестинг...")
    
    try:
        backtester = SBERBacktester(tinkoff_token)
        
        # Бэктест за 30 дней
        logger.info("🔄 Анализ за 30 дней...")
        results = await backtester.run_backtest(days=30)
        backtester.print_results(results, 30)
        
        # Дополнительно - за 7 дней для сравнения
        logger.info("🔄 Анализ за 7 дней...")
        results_week = await backtester.run_backtest(days=7)
        backtester.print_results(results_week, 7)
        
    except KeyboardInterrupt:
        logger.info("❌ Бэктестинг прерван пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"❌ Ошибка запуска: {e}")
        sys.exit(1)
