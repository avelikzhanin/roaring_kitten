#!/usr/bin/env python3
"""
БЭКТЕСТ АНАЛИЗАТОР - SBER 1H СТРАТЕГИЯ
Полный анализ 80 сигналов с разными стратегиями входа/выхода
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from enum import Enum
import asyncio

# Импорты из оригинального кода
from tinkoff.invest import Client, CandleInterval
from tinkoff.invest.utils import now

class TradeResult(Enum):
    WIN_TARGET = "🎯 ЦЕЛЬ"
    WIN_PARTIAL = "📈 ЧАСТИЧНО" 
    LOSS_STOP = "🛑 СТОП"
    LOSS_TECHNICAL = "⚡ ТЕХНИЧЕСКИЙ"
    TIMEOUT = "⏰ ТАЙМАУТ"

@dataclass
class TradeSetup:
    """Настройки торговой стратегии"""
    stop_loss_pct: float = -3.0          # Стоп-лосс в %
    take_profit_pct: float = 6.0         # Тейк-профит в %
    partial_profit_pct: float = 3.0      # Частичная фиксация в %
    partial_close_pct: float = 0.3       # Сколько закрывать частично (30%)
    max_hold_hours: int = 48             # Макс время удержания
    trailing_stop_pct: float = 2.0       # Трейлинг стоп
    commission_pct: float = 0.05         # Комиссия в %

@dataclass 
class Trade:
    """Информация о сделке"""
    signal_timestamp: datetime
    entry_price: float
    entry_time: datetime
    signal_strength: float
    adx: float
    di_diff: float
    
    # Результаты
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    result: Optional[TradeResult] = None
    profit_pct: Optional[float] = None
    profit_rub: Optional[float] = None
    hold_hours: Optional[int] = None
    max_profit_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None

@dataclass
class BacktestResults:
    """Результаты бэктеста"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    
    total_return_pct: float
    total_return_rub: float
    average_trade_pct: float
    average_win_pct: float
    average_loss_pct: float
    
    max_consecutive_wins: int
    max_consecutive_losses: int
    max_drawdown: float
    sharpe_ratio: float
    
    trades_by_result: Dict[TradeResult, int]
    monthly_returns: List[float]
    
    best_trade: Trade
    worst_trade: Trade

class BacktestEngine:
    """Движок бэктестирования"""
    
    def __init__(self, token: str, setup: TradeSetup = None):
        self.token = token
        self.setup = setup or TradeSetup()
        self.figi = "BBG004730N88"  # SBER
        
    async def get_detailed_candles(self, days: int = 30) -> pd.DataFrame:
        """Получение детальных данных для бэктеста"""
        try:
            with Client(self.token) as client:
                to_time = now()
                from_time = to_time - timedelta(days=days)
                
                print(f"📡 Загрузка детальных данных: {days} дней...")
                
                response = client.market_data.get_candles(
                    figi=self.figi,
                    from_=from_time,
                    to=to_time,
                    interval=CandleInterval.CANDLE_INTERVAL_HOUR
                )
                
                if not response.candles:
                    return pd.DataFrame()
                
                data = []
                for candle in response.candles:
                    data.append({
                        'timestamp': candle.time,
                        'open': self.quotation_to_decimal(candle.open),
                        'high': self.quotation_to_decimal(candle.high),
                        'low': self.quotation_to_decimal(candle.low),
                        'close': self.quotation_to_decimal(candle.close),
                        'volume': candle.volume
                    })
                
                df = pd.DataFrame(data)
                df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
                df = df.sort_values('timestamp').reset_index(drop=True)
                
                print(f"✅ Загружено {len(df)} часовых свечей")
                return df
                
        except Exception as e:
            print(f"❌ Ошибка загрузки: {e}")
            return pd.DataFrame()
    
    @staticmethod
    def quotation_to_decimal(quotation) -> float:
        return float(quotation.units + quotation.nano / 1e9)
    
    def simulate_trade(self, entry_signal: Dict, price_data: pd.DataFrame) -> Trade:
        """Симуляция одной сделки"""
        
        # Создаем объект сделки
        trade = Trade(
            signal_timestamp=entry_signal['timestamp'],
            entry_price=entry_signal['price'],
            entry_time=entry_signal['timestamp'],
            signal_strength=entry_signal['strength'],
            adx=entry_signal['adx'],
            di_diff=entry_signal['di_diff']
        )
        
        # Уровни для выхода
        stop_price = trade.entry_price * (1 + self.setup.stop_loss_pct / 100)
        target_price = trade.entry_price * (1 + self.setup.take_profit_pct / 100)
        partial_price = trade.entry_price * (1 + self.setup.partial_profit_pct / 100)
        
        # Ищем данные после входа
        entry_idx = price_data[price_data['timestamp'] >= trade.entry_time].index
        if len(entry_idx) == 0:
            return trade
        
        entry_idx = entry_idx[0]
        max_profit = 0
        max_drawdown = 0
        
        # Проверяем каждую свечу после входа
        for i in range(entry_idx, min(entry_idx + self.setup.max_hold_hours, len(price_data))):
            candle = price_data.iloc[i]
            current_time = candle['timestamp']
            
            # Текущая прибыль/убыток
            high_profit = ((candle['high'] - trade.entry_price) / trade.entry_price) * 100
            low_profit = ((candle['low'] - trade.entry_price) / trade.entry_price) * 100
            close_profit = ((candle['close'] - trade.entry_price) / trade.entry_price) * 100
            
            # Обновляем максимумы/минимумы
            max_profit = max(max_profit, high_profit)
            max_drawdown = min(max_drawdown, low_profit)
            
            # Проверка стоп-лосса
            if candle['low'] <= stop_price:
                trade.exit_price = stop_price
                trade.exit_time = current_time
                trade.result = TradeResult.LOSS_STOP
                trade.profit_pct = self.setup.stop_loss_pct
                break
            
            # Проверка тейк-профита
            if candle['high'] >= target_price:
                trade.exit_price = target_price
                trade.exit_time = current_time
                trade.result = TradeResult.WIN_TARGET
                trade.profit_pct = self.setup.take_profit_pct
                break
            
            # Проверка частичной фиксации (упрощенно - как полный выход)
            if candle['high'] >= partial_price and self.setup.partial_profit_pct > 0:
                trade.exit_price = partial_price
                trade.exit_time = current_time
                trade.result = TradeResult.WIN_PARTIAL
                trade.profit_pct = self.setup.partial_profit_pct
                break
        
        # Если не закрылись - таймаут
        if trade.exit_price is None:
            last_candle = price_data.iloc[min(entry_idx + self.setup.max_hold_hours - 1, len(price_data) - 1)]
            trade.exit_price = last_candle['close']
            trade.exit_time = last_candle['timestamp']
            trade.result = TradeResult.TIMEOUT
            trade.profit_pct = ((trade.exit_price - trade.entry_price) / trade.entry_price) * 100
        
        # Финальные расчеты
        trade.profit_rub = (trade.exit_price - trade.entry_price)
        trade.hold_hours = int((trade.exit_time - trade.entry_time).total_seconds() / 3600)
        trade.max_profit_pct = max_profit
        trade.max_drawdown_pct = max_drawdown
        
        # Вычитаем комиссию
        trade.profit_pct -= self.setup.commission_pct
        trade.profit_rub -= trade.entry_price * (self.setup.commission_pct / 100)
        
        return trade
    
    def generate_sample_signals(self) -> List[Dict]:
        """Генерация тестовых сигналов на основе ваших данных"""
        # Используем параметры из ваших реальных сигналов
        base_date = datetime(2025, 8, 5)
        signals = []
        
        # Топ сигналы из ваших логов
        top_signals = [
            {'price': 324.28, 'adx': 39.1, 'di_diff': 52.0, 'strength': 91.0, 'hours_offset': 0},
            {'price': 322.46, 'adx': 45.9, 'di_diff': 36.0, 'strength': 86.1, 'hours_offset': 24},
            {'price': 315.56, 'adx': 41.2, 'di_diff': 26.4, 'strength': 85.1, 'hours_offset': 48},
            {'price': 322.72, 'adx': 44.2, 'di_diff': 28.9, 'strength': 84.8, 'hours_offset': 72},
        ]
        
        # Добавляем топ сигналы
        for i, sig in enumerate(top_signals):
            signals.append({
                'timestamp': base_date + timedelta(hours=sig['hours_offset']),
                'price': sig['price'],
                'adx': sig['adx'],
                'di_diff': sig['di_diff'],
                'strength': sig['strength']
            })
        
        # Генерируем остальные 76 сигналов с реальными параметрами
        np.random.seed(42)
        for i in range(76):
            # Используем статистику из ваших логов
            adx = np.random.normal(36.7, 5.0)  # Среднее 36.7 из логов
            adx = max(23.1, min(46.8, adx))    # Границы из логов
            
            di_diff = np.random.gamma(2, 9)    # Медиана 16.0, макс 52.0
            di_diff = min(52.0, di_diff)
            
            # Цена с учетом EMA дистанции (0.005-1.973%)
            base_price = 320.0 + np.random.normal(0, 8)
            ema_dist_pct = np.random.lognormal(-2, 0.8) # Медиана 0.25%
            ema_dist_pct = min(1.973, max(0.005, ema_dist_pct))
            price = base_price * (1 + ema_dist_pct / 100)
            
            # Сила сигнала (корреляция с параметрами)
            strength = min(100, max(20, 
                (adx - 23) * 1.5 + 
                di_diff * 1.2 + 
                ema_dist_pct * 10 +
                np.random.normal(0, 5)
            ))
            
            signals.append({
                'timestamp': base_date + timedelta(hours=96 + i * 6 + np.random.randint(-2, 3)),
                'price': round(price, 2),
                'adx': round(adx, 1),
                'di_diff': round(di_diff, 1),
                'strength': round(strength, 1)
            })
        
        return sorted(signals, key=lambda x: x['timestamp'])
    
    async def run_backtest(self, signals: List[Dict] = None) -> BacktestResults:
        """Запуск полного бэктеста"""
        
        print("🚀 ЗАПУСК БЭКТЕСТА SBER 1H СТРАТЕГИИ")
        print("=" * 60)
        
        if signals is None:
            signals = self.generate_sample_signals()
        
        # Загружаем исторические данные
        price_data = await self.get_detailed_candles(days=30)
        if price_data.empty:
            print("❌ Не удалось загрузить данные для бэктеста")
            return None
        
        print(f"📊 Анализируем {len(signals)} сигналов...")
        print(f"📈 Период данных: {price_data['timestamp'].min()} - {price_data['timestamp'].max()}")
        print(f"⚙️ Стоп-лосс: {self.setup.stop_loss_pct}%, Тейк-профит: {self.setup.take_profit_pct}%")
        print()
        
        # Симулируем все сделки
        trades = []
        for i, signal in enumerate(signals):
            if i < 10 or i % 10 == 0:  # Прогресс
                print(f"📈 Обрабатываем сигнал {i+1}/{len(signals)}...")
            
            trade = self.simulate_trade(signal, price_data)
            if trade.exit_price is not None:
                trades.append(trade)
        
        if not trades:
            print("❌ Не удалось выполнить ни одной сделки")
            return None
        
        # Анализируем результаты
        return self.analyze_results(trades)
    
    def analyze_results(self, trades: List[Trade]) -> BacktestResults:
        """Анализ результатов бэктеста"""
        
        winning_trades = [t for t in trades if t.profit_pct > 0]
        losing_trades = [t for t in trades if t.profit_pct <= 0]
        
        # Базовая статистика
        total_return_pct = sum(t.profit_pct for t in trades)
        total_return_rub = sum(t.profit_rub for t in trades)
        
        # Результаты по типам
        results_count = {}
        for result_type in TradeResult:
            results_count[result_type] = len([t for t in trades if t.result == result_type])
        
        # Серии побед/поражений
        consecutive_wins = 0
        consecutive_losses = 0
        max_consec_wins = 0
        max_consec_losses = 0
        
        for trade in trades:
            if trade.profit_pct > 0:
                consecutive_wins += 1
                consecutive_losses = 0
                max_consec_wins = max(max_consec_wins, consecutive_wins)
            else:
                consecutive_losses += 1
                consecutive_wins = 0
                max_consec_losses = max(max_consec_losses, consecutive_losses)
        
        # Максимальная просадка
        cumulative_return = 0
        peak = 0
        max_drawdown = 0
        
        for trade in trades:
            cumulative_return += trade.profit_pct
            peak = max(peak, cumulative_return)
            drawdown = peak - cumulative_return
            max_drawdown = max(max_drawdown, drawdown)
        
        # Коэффициент Шарпа (упрощенно)
        returns = [t.profit_pct for t in trades]
        sharpe_ratio = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0
        
        # Лучшая/худшая сделки
        best_trade = max(trades, key=lambda t: t.profit_pct)
        worst_trade = min(trades, key=lambda t: t.profit_pct)
        
        results = BacktestResults(
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=len(winning_trades) / len(trades) * 100,
            
            total_return_pct=total_return_pct,
            total_return_rub=total_return_rub,
            average_trade_pct=total_return_pct / len(trades),
            average_win_pct=np.mean([t.profit_pct for t in winning_trades]) if winning_trades else 0,
            average_loss_pct=np.mean([t.profit_pct for t in losing_trades]) if losing_trades else 0,
            
            max_consecutive_wins=max_consec_wins,
            max_consecutive_losses=max_consec_losses,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            
            trades_by_result=results_count,
            monthly_returns=[],  # Для простоты пропускаем
            
            best_trade=best_trade,
            worst_trade=worst_trade
        )
        
        self.print_results(results, trades)
        return results
    
    def print_results(self, results: BacktestResults, trades: List[Trade]):
        """Детальный вывод результатов"""
        
        print(f"\n{'='*80}")
        print("🎯 РЕЗУЛЬТАТЫ БЭКТЕСТА SBER 1H СТРАТЕГИИ")
        print(f"{'='*80}")
        
        print(f"\n📊 ОБЩАЯ СТАТИСТИКА:")
        print(f"   💼 Всего сделок: {results.total_trades}")
        print(f"   ✅ Прибыльных: {results.winning_trades} ({results.win_rate:.1f}%)")
        print(f"   ❌ Убыточных: {results.losing_trades} ({100-results.win_rate:.1f}%)")
        
        print(f"\n💰 ФИНАНСОВЫЕ РЕЗУЛЬТАТЫ:")
        print(f"   📈 Общая доходность: {results.total_return_pct:+.1f}%")
        print(f"   💵 Прибыль в рублях: {results.total_return_rub:+,.0f} руб (на 1 акцию)")
        print(f"   📊 Средняя сделка: {results.average_trade_pct:+.2f}%")
        print(f"   🎯 Средняя прибыль: {results.average_win_pct:+.2f}%")
        print(f"   🛑 Средний убыток: {results.average_loss_pct:.2f}%")
        
        print(f"\n🎲 СТАТИСТИКА СЕРИЙ:")
        print(f"   🔥 Макс. победы подряд: {results.max_consecutive_wins}")
        print(f"   💀 Макс. убытки подряд: {results.max_consecutive_losses}")
        print(f"   📉 Максимальная просадка: {results.max_drawdown:.1f}%")
        print(f"   📊 Коэффициент Шарпа: {results.sharpe_ratio:.2f}")
        
        print(f"\n🎯 РЕЗУЛЬТАТЫ ПО ТИПАМ:")
        for result_type, count in results.trades_by_result.items():
            pct = (count / results.total_trades) * 100
            print(f"   {result_type.value}: {count:>2} сделок ({pct:>4.1f}%)")
        
        # Анализ по силе сигналов
        print(f"\n📊 АНАЛИЗ ПО СИЛЕ СИГНАЛОВ:")
        
        strength_ranges = {
            "90-100%": [t for t in trades if t.signal_strength >= 90],
            "80-90%":  [t for t in trades if 80 <= t.signal_strength < 90],
            "70-80%":  [t for t in trades if 70 <= t.signal_strength < 80],
            "60-70%":  [t for t in trades if 60 <= t.signal_strength < 70],
            "50-60%":  [t for t in trades if 50 <= t.signal_strength < 60],
            "<50%":    [t for t in trades if t.signal_strength < 50]
        }
        
        for range_name, group in strength_ranges.items():
            if not group:
                continue
                
            win_rate = len([t for t in group if t.profit_pct > 0]) / len(group) * 100
            avg_return = np.mean([t.profit_pct for t in group])
            
            print(f"   {range_name:>8}: {len(group):>2} сделок, "
                  f"винрейт {win_rate:>4.0f}%, "
                  f"средний результат {avg_return:>+5.1f}%")
        
        print(f"\n🏆 ЛУЧШИЕ/ХУДШИЕ СДЕЛКИ:")
        
        # Топ-5 лучших
        best_trades = sorted(trades, key=lambda t: t.profit_pct, reverse=True)[:5]
        print(f"\n🥇 ТОП-5 ЛУЧШИХ:")
        for i, trade in enumerate(best_trades, 1):
            print(f"   #{i} {trade.entry_time.strftime('%d.%m %H:%M')}: "
                  f"{trade.profit_pct:+.1f}% "
                  f"(сила {trade.signal_strength:.0f}%, "
                  f"держали {trade.hold_hours}ч)")
        
        # Топ-5 худших  
        worst_trades = sorted(trades, key=lambda t: t.profit_pct)[:5]
        print(f"\n💀 ТОП-5 ХУДШИХ:")
        for i, trade in enumerate(worst_trades, 1):
            print(f"   #{i} {trade.entry_time.strftime('%d.%m %H:%M')}: "
                  f"{trade.profit_pct:+.1f}% "
                  f"(сила {trade.signal_strength:.0f}%, "
                  f"держали {trade.hold_hours}ч)")
        
        # Расчет на разные суммы
        print(f"\n💼 РАСЧЕТ ПРИБЫЛИ НА РАЗНЫЕ СУММЫ:")
        for capital in [100_000, 500_000, 1_000_000]:
            shares = capital // 320  # Примерная цена акции
            total_profit = results.total_return_rub * shares
            print(f"   💰 Капитал {capital:,} руб → "
                  f"{shares:,} акций → "
                  f"прибыль {total_profit:+,.0f} руб "
                  f"({(total_profit/capital)*100:+.1f}%)")
        
        print(f"\n🎯 ВЫВОДЫ И РЕКОМЕНДАЦИИ:")
        
        if results.win_rate >= 60:
            print("   ✅ Отличный винрейт! Стратегия работает стабильно")
        elif results.win_rate >= 50:
            print("   ⚖️ Приемлемый винрейт, нужна оптимизация")
        else:
            print("   ⚠️ Низкий винрейт, требуется доработка фильтров")
        
        if results.average_trade_pct > 0.5:
            print("   💰 Хорошая средняя прибыль на сделку")
        else:
            print("   📉 Низкая средняя прибыль, увеличить тейк-профит")
        
        if results.max_drawdown < 10:
            print("   🛡️ Низкая просадка, хорошее управление рисками")
        else:
            print("   ⚠️ Высокая просадка, ужесточить стоп-лоссы")
        
        print(f"\n🤖 ОПТИМАЛЬНЫЕ НАСТРОЙКИ:")
        
        # Анализ лучших параметров
        profitable_trades = [t for t in trades if t.profit_pct > 0]
        if profitable_trades:
            avg_strength = np.mean([t.signal_strength for t in profitable_trades])
            min_good_strength = np.percentile([t.signal_strength for t in profitable_trades], 25)
            
            print(f"   📊 Торговать сигналы с силой ≥ {min_good_strength:.0f}%")
            print(f"   🎯 Средняя сила прибыльных: {avg_strength:.1f}%")
            print(f"   ⏰ Среднее время удержания: {np.mean([t.hold_hours for t in profitable_trades]):.0f}ч")

# Запуск бэктеста
async def run_full_backtest():
    """Запуск полного бэктеста с разными настройками"""
    
    import os
    token = os.getenv('TINKOFF_TOKEN')
    if not token:
        print("❌ TINKOFF_TOKEN не найден")
        return
    
    print("🎯 ТЕСТИРУЕМ РАЗНЫЕ СТРАТЕГИИ")
    print("=" * 60)
    
    # Стратегия 1: Консервативная
    print("\n🛡️ СТРАТЕГИЯ 1: КОНСЕРВАТИВНАЯ")
    setup1 = TradeSetup(
        stop_loss_pct=-2.0,
        take_profit_pct=4.0,
        partial_profit_pct=2.0,
        max_hold_hours=24
    )
    
    engine1 = BacktestEngine(token, setup1)
    results1 = await engine1.run_backtest()
    
    # Стратегия 2: Агрессивная  
    print(f"\n⚡ СТРАТЕГИЯ 2: АГРЕССИВНАЯ")
    setup2 = TradeSetup(
        stop_loss_pct=-4.0,
        take_profit_pct=8.0,
        partial_profit_pct=4.0,
        max_hold_hours=72
    )
    
    engine2 = BacktestEngine(token, setup2)
    results2 = await engine2.run_backtest()
    
    # Стратегия 3: Ваша оригинальная
    print(f"\n🎯 СТРАТЕГИЯ 3: ОРИГИНАЛЬНАЯ")
    setup3 = TradeSetup(
        stop_loss_pct=-3.0,
        take_profit_pct=6.0,
        partial_profit_pct=3.0,
        max_hold_hours=48
    )
    
    engine3 = BacktestEngine(token, setup3)
    results3 = await engine3.run_backtest()
    
    # Стратегия 4: Только лучшие сигналы
    print(f"\n🔥 СТРАТЕГИЯ 4: ТОЛЬКО ПРЕМИУМ СИГНАЛЫ (≥75%)")
    setup4 = TradeSetup(
        stop_loss_pct=-3.0,
        take_profit_pct=6.0,
        partial_profit_pct=3.0,
        max_hold_hours=48
    )
    
    engine4 = BacktestEngine(token, setup4)
    # Фильтруем только сильные сигналы
    all_signals = engine4.generate_sample_signals()
    premium_signals = [s for s in all_signals if s['strength'] >= 75.0]
    print(f"   📊 Отобрано {len(premium_signals)} премиум сигналов из {len(all_signals)}")
    
    results4 = await engine4.run_backtest(premium_signals)
    
    # Сравнение
    print(f"\n{'='*80}")
    print("📊 СРАВНЕНИЕ СТРАТЕГИЙ")
    print(f"{'='*80}")
    
    strategies = [
        ("🛡️ Консервативная", results1),
        ("⚡ Агрессивная", results2), 
        ("🎯 Оригинальная", results3),
        ("🔥 Только премиум", results4)
    ]
    
    print(f"{'Стратегия':<15} {'Винрейт':<8} {'Доходность':<12} {'Сред.сделка':<12} {'Просадка':<10}")
    print("-" * 65)
    
    for name, results in strategies:
        if results:
            print(f"{name:<15} {results.win_rate:<7.1f}% "
                  f"{results.total_return_pct:<11.1f}% "
                  f"{results.average_trade_pct:<11.2f}% "
                  f"{results.max_drawdown:<9.1f}%")

if __name__ == "__main__":
    asyncio.run(run_full_backtest())
