#!/usr/bin/env python3
"""
Бэктестинг торговой стратегии SBER для Railway
Запуск: python backtest.py
"""

import asyncio
import logging
import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd
from dataclasses import dataclass

from src.data_provider import TinkoffDataProvider
from src.indicators import TechnicalIndicators

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

@dataclass
class BacktestSignal:
    """Структура сигнала для бэктеста"""
    timestamp: datetime
    signal_type: str  # 'BUY' или 'SELL'
    price: float
    ema20: float
    adx: float
    plus_di: float
    minus_di: float
    volume: int
    volume_ratio: float

@dataclass
class Trade:
    """Структура сделки"""
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    profit_pct: Optional[float] = None
    duration_hours: Optional[int] = None

class StrategyBacktest:
    """Класс для бэктестинга торговой стратегии"""
    
    def __init__(self, tinkoff_token: str):
        self.provider = TinkoffDataProvider(tinkoff_token)
        self.signals: List[BacktestSignal] = []
        self.trades: List[Trade] = []
        
    async def run_backtest(self, days: int = 60) -> Dict:
        """Запуск бэктеста за указанное количество дней"""
        logger.info(f"🔄 Начинаем бэктестинг за последние {days} дней...")
        
        try:
            # Получаем данные за нужный период + запас для индикаторов
            hours_needed = days * 24 + 200  # +200 часов для расчета индикаторов
            candles = await self.provider.get_candles(hours=hours_needed)
            
            if len(candles) < 100:
                raise Exception("Недостаточно исторических данных")
                
            df = self.provider.candles_to_dataframe(candles)
            
            if df.empty:
                raise Exception("Не удалось получить данные")
            
            logger.info(f"📊 Получено {len(candles)} свечей для анализа")
            
            # Анализируем каждую свечу
            await self._analyze_data(df, days)
            
            # Генерируем сделки
            self._generate_trades()
            
            # Рассчитываем статистику
            stats = self._calculate_statistics(days)
            
            return stats
            
        except Exception as e:
            logger.error(f"Ошибка бэктестинга: {e}")
            return {}
    
    async def _analyze_data(self, df: pd.DataFrame, test_days: int):
        """Анализ данных и поиск сигналов"""
        logger.info("🔍 Анализируем исторические данные...")
        
        # Ограничиваем период тестирования
        test_start = datetime.now() - timedelta(days=test_days)
        
        # Подготавливаем данные для расчета индикаторов
        closes = df['close'].tolist()
        highs = df['high'].tolist()
        lows = df['low'].tolist()
        volumes = df['volume'].tolist()
        
        # Рассчитываем индикаторы
        logger.info("📈 Рассчитываем технические индикаторы...")
        ema20 = TechnicalIndicators.calculate_ema(closes, 20)
        adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
        
        # Рассчитываем средний объем
        df['avg_volume_20'] = df['volume'].rolling(window=20, min_periods=1).mean()
        
        # Добавляем индикаторы в DataFrame
        df['ema20'] = ema20
        df['adx'] = adx_data['adx']
        df['plus_di'] = adx_data['plus_di']
        df['minus_di'] = adx_data['minus_di']
        
        # Фильтруем данные по тестовому периоду
        df_test = df[df['timestamp'] >= test_start].copy()
        logger.info(f"🎯 Тестовый период: {len(df_test)} свечей с {test_start.strftime('%d.%m.%Y')}")
        
        # Анализируем каждую строку в тестовом периоде
        current_signal_active = False
        signals_count = 0
        
        for i in range(len(df_test)):
            row = df_test.iloc[i]
            
            # Пропускаем если есть NaN
            if pd.isna(row['adx']) or pd.isna(row['ema20']) or pd.isna(row['plus_di']) or pd.isna(row['minus_di']):
                continue
            
            # Проверяем условия сигнала покупки (точно как в боте)
            conditions = [
                row['close'] > row['ema20'],                    # Цена выше EMA20
                row['adx'] > 23,                               # ADX больше 23
                row['plus_di'] > row['minus_di'],              # +DI больше -DI
                row['plus_di'] - row['minus_di'] > 5,          # Существенная разница
                row['volume'] > row['avg_volume_20'] * 1.47    # Объем на 47% выше среднего
            ]
            
            conditions_met = all(conditions)
            
            # Логика сигналов (точно как в боте)
            if conditions_met and not current_signal_active:
                # Новый сигнал покупки
                signal = BacktestSignal(
                    timestamp=row['timestamp'],
                    signal_type='BUY',
                    price=row['close'],
                    ema20=row['ema20'],
                    adx=row['adx'],
                    plus_di=row['plus_di'],
                    minus_di=row['minus_di'],
                    volume=int(row['volume']),
                    volume_ratio=row['volume'] / row['avg_volume_20']
                )
                self.signals.append(signal)
                current_signal_active = True
                signals_count += 1
                logger.info(f"📈 BUY сигнал #{signals_count}: {row['timestamp'].strftime('%d.%m %H:%M')} по цене {row['close']:.2f} ₽")
                
            elif not conditions_met and current_signal_active:
                # Сигнал отмены/продажи
                signal = BacktestSignal(
                    timestamp=row['timestamp'],
                    signal_type='SELL',
                    price=row['close'],
                    ema20=row['ema20'],
                    adx=row['adx'],
                    plus_di=row['plus_di'],
                    minus_di=row['minus_di'],
                    volume=int(row['volume']),
                    volume_ratio=row['volume'] / row['avg_volume_20']
                )
                self.signals.append(signal)
                current_signal_active = False
                logger.info(f"📉 SELL сигнал: {row['timestamp'].strftime('%d.%m %H:%M')} по цене {row['close']:.2f} ₽")
        
        logger.info(f"🎯 Всего найдено сигналов: {len(self.signals)} (BUY: {signals_count})")
    
    def _generate_trades(self):
        """Генерация сделок из сигналов"""
        logger.info("💼 Генерируем сделки из сигналов...")
        
        current_trade: Optional[Trade] = None
        
        for signal in self.signals:
            if signal.signal_type == 'BUY' and current_trade is None:
                # Открываем новую сделку
                current_trade = Trade(
                    entry_time=signal.timestamp,
                    entry_price=signal.price
                )
                
            elif signal.signal_type == 'SELL' and current_trade is not None:
                # Закрываем сделку
                current_trade.exit_time = signal.timestamp
                current_trade.exit_price = signal.price
                current_trade.duration_hours = int((signal.timestamp - current_trade.entry_time).total_seconds() / 3600)
                current_trade.profit_pct = ((signal.price - current_trade.entry_price) / current_trade.entry_price) * 100
                
                self.trades.append(current_trade)
                current_trade = None
        
        # Если есть незакрытая сделка, считаем ее открытой
        if current_trade is not None:
            logger.info("⚠️ Есть незакрытая позиция на конец периода")
        
        logger.info(f"💰 Создано завершенных сделок: {len(self.trades)}")
    
    def _calculate_statistics(self, days: int) -> Dict:
        """Расчет статистики стратегии"""
        if not self.trades:
            return {
                'period_days': days,
                'total_signals': len(self.signals),
                'buy_signals': len([s for s in self.signals if s.signal_type == 'BUY']),
                'sell_signals': len([s for s in self.signals if s.signal_type == 'SELL']),
                'total_trades': 0,
                'profitable_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'total_return': 0,
                'avg_profit': 0,
                'max_profit': 0,
                'max_loss': 0,
                'avg_duration_hours': 0,
                'trades_detail': []
            }
        
        profits = [trade.profit_pct for trade in self.trades if trade.profit_pct is not None]
        profitable_trades = [p for p in profits if p > 0]
        losing_trades = [p for p in profits if p <= 0]
        durations = [trade.duration_hours for trade in self.trades if trade.duration_hours is not None]
        
        total_return = sum(profits) if profits else 0
        annual_return = (total_return / days) * 365 if days > 0 else 0
        
        stats = {
            'period_days': days,
            'total_signals': len(self.signals),
            'buy_signals': len([s for s in self.signals if s.signal_type == 'BUY']),
            'sell_signals': len([s for s in self.signals if s.signal_type == 'SELL']),
            'total_trades': len(self.trades),
            'profitable_trades': len(profitable_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(profitable_trades) / len(profits) * 100 if profits else 0,
            'total_return': total_return,
            'annual_return_estimate': annual_return,
            'avg_profit': sum(profits) / len(profits) if profits else 0,
            'max_profit': max(profits) if profits else 0,
            'max_loss': min(profits) if profits else 0,
            'avg_duration_hours': sum(durations) / len(durations) if durations else 0,
            'trades_detail': self.trades
        }
        
        return stats
    
    def print_results(self, stats: Dict):
        """Красивый вывод результатов"""
        print("\n" + "="*70)
        print(f"🎯 БЭКТЕСТИНГ СТРАТЕГИИ SBER ЗА {stats['period_days']} ДНЕЙ")
        print("="*70)
        
        print(f"📊 СИГНАЛЫ:")
        print(f"   • Всего сигналов: {stats['total_signals']}")
        print(f"   • Сигналы покупки: {stats['buy_signals']}")
        print(f"   • Сигналы продажи: {stats['sell_signals']}")
        print(f"   • Частота: {stats['buy_signals']/(stats['period_days']/7):.1f} сигналов в неделю")
        
        print(f"\n💼 СДЕЛКИ:")
        print(f"   • Общее количество: {stats['total_trades']}")
        print(f"   • Прибыльные: {stats['profitable_trades']}")
        print(f"   • Убыточные: {stats['losing_trades']}")
        print(f"   • Винрейт: {stats['win_rate']:.1f}%")
        
        print(f"\n💰 ДОХОДНОСТЬ:")
        print(f"   • Общая доходность: {stats['total_return']:.2f}%")
        print(f"   • Средняя доходность на сделку: {stats['avg_profit']:.2f}%")
        print(f"   • Максимальная прибыль: {stats['max_profit']:.2f}%")
        print(f"   • Максимальный убыток: {stats['max_loss']:.2f}%")
        print(f"   • Годовая доходность (оценка): {stats['annual_return_estimate']:.1f}%")
        
        print(f"\n⏰ ВРЕМЯ:")
        print(f"   • Средняя длительность сделки: {stats['avg_duration_hours']:.1f} часов")
        
        if stats['trades_detail'] and len(stats['trades_detail']) > 0:
            print(f"\n📋 ДЕТАЛИ СДЕЛОК:")
            for i, trade in enumerate(stats['trades_detail'][:10], 1):  # Показываем первые 10
                profit_str = f"{trade.profit_pct:+.2f}%" if trade.profit_pct else "Открыта"
                duration_str = f"{trade.duration_hours}ч" if trade.duration_hours else "---"
                print(f"   {i:2d}. {trade.entry_time.strftime('%d.%m %H:%M')} → "
                      f"{trade.exit_time.strftime('%d.%m %H:%M') if trade.exit_time else '  Открыта  '} | "
                      f"{trade.entry_price:.2f} → {trade.exit_price:.2f if trade.exit_price else '  ---  '} | "
                      f"{profit_str:>8} | {duration_str:>5}")
            
            if len(stats['trades_detail']) > 10:
                print(f"   ... и еще {len(stats['trades_detail']) - 10} сделок")
        
        print("="*70)

async def main():
    """Главная функция"""
    print("🚀 SBER Trading Bot - Бэктестинг стратегии на Railway")
    print("-" * 60)
    
    # Получаем токен из переменных окружения
    TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
    
    if not TINKOFF_TOKEN:
        logger.error("❌ Не найден TINKOFF_TOKEN в переменных окружения")
        sys.exit(1)
    
    try:
        # Создаем бэктестер
        backtest = StrategyBacktest(TINKOFF_TOKEN)
        
        # Тестируем разные периоды
        periods = [30, 60, 90]  # 1, 2, 3 месяца
        
        for days in periods:
            logger.info(f"🔄 Запускаем анализ за {days} дней...")
            
            stats = await backtest.run_backtest(days=days)
            
            if stats:
                backtest.print_results(stats)
                
                # Интерпретация результатов
                print(f"\n🎯 ИНТЕРПРЕТАЦИЯ за {days} дней:")
                if stats['total_trades'] > 0:
                    if stats['win_rate'] >= 60:
                        print("   ✅ Отличная стратегия (винрейт ≥60%)")
                    elif stats['win_rate'] >= 40:
                        print("   ⚠️ Средняя стратегия (винрейт 40-60%)")
                    else:
                        print("   ❌ Слабая стратегия (винрейт <40%)")
                    
                    if stats['total_return'] > 0:
                        print(f"   💰 Прибыльная стратегия (+{stats['total_return']:.2f}%)")
                    else:
                        print(f"   📉 Убыточная стратегия ({stats['total_return']:.2f}%)")
                        
                    if stats['avg_duration_hours'] < 24:
                        print("   ⚡ Быстрые сигналы (< 1 дня)")
                    else:
                        print(f"   🐌 Медленные сигналы ({stats['avg_duration_hours']:.0f}ч)")
                else:
                    print("   ℹ️ За этот период сигналов не было")
            else:
                logger.error(f"❌ Не удалось выполнить анализ за {days} дней")
            
            # Очищаем данные для следующего периода
            backtest.signals.clear()
            backtest.trades.clear()
            
            print("\n" + "-"*60)
        
        print("\n✅ Бэктестинг завершен!")
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
