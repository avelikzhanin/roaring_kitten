import asyncio
import pandas as pd
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import List, Optional, Tuple
import sys
import os

# Добавляем src в путь
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from data_provider import TinkoffDataProvider
from indicators import TechnicalIndicators

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class Trade:
    """Структура сделки"""
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    signal_data: dict = None

    @property
    def duration_hours(self) -> float:
        """Продолжительность сделки в часах"""
        if self.exit_time is not None:
            return (self.exit_time - self.entry_time).total_seconds() / 3600
        return 0

    @property
    def profit_pct(self) -> float:
        """Прибыль в процентах"""
        if self.exit_price is not None:
            return (self.exit_price - self.entry_price) / self.entry_price * 100
        return 0

    @property
    def profit_rub(self) -> float:
        """Прибыль в рублях на 1 акцию"""
        if self.exit_price is not None:
            return self.exit_price - self.entry_price
        return 0

class BacktestEngine:
    """Движок для бэктестинга торговой стратегии"""
    
    def __init__(self, data_provider: TinkoffDataProvider):
        self.data_provider = data_provider
        self.trades: List[Trade] = []
        self.current_position: Optional[Trade] = None
        
    async def run_backtest(self, hours_back: int = 2000) -> dict:
        """Запуск бэктеста"""
        logger.info(f"🚀 Запуск бэктеста за последние {hours_back} часов")
        
        # Получаем данные
        candles = await self.data_provider.get_candles(hours=hours_back)
        
        if len(candles) < 100:
            logger.error("Недостаточно данных для бэктеста")
            return {}
        
        df = self.data_provider.candles_to_dataframe(candles)
        logger.info(f"📊 Получено {len(df)} часовых свечей")
        
        # Рассчитываем индикаторы
        self.calculate_indicators(df)
        
        # Симулируем торговлю
        self.simulate_trading(df)
        
        # Анализируем результаты
        return self.analyze_results(df)
    
    def calculate_indicators(self, df: pd.DataFrame):
        """Расчет технических индикаторов"""
        logger.info("📈 Расчет технических индикаторов...")
        
        # EMA20
        ema20_list = TechnicalIndicators.calculate_ema(df['close'].tolist(), 20)
        df['ema20'] = ema20_list
        
        # ADX, +DI, -DI
        adx_data = TechnicalIndicators.calculate_adx(
            df['high'].tolist(), 
            df['low'].tolist(), 
            df['close'].tolist(), 
            14
        )
        
        df['adx'] = adx_data['adx']
        df['plus_di'] = adx_data['plus_di']
        df['minus_di'] = adx_data['minus_di']
        
        # Средний объем за 20 часов
        df['avg_volume_20'] = df['volume'].rolling(window=20, min_periods=1).mean()
        df['volume_ratio'] = df['volume'] / df['avg_volume_20']
        
        # Условия стратегии
        df['price_above_ema'] = df['close'] > df['ema20']
        df['strong_trend'] = df['adx'] > 23
        df['positive_direction'] = df['plus_di'] > df['minus_di']
        df['di_difference'] = (df['plus_di'] - df['minus_di']) > 5
        df['high_volume'] = df['volume_ratio'] > 1.47
        
        # Общий сигнал
        df['buy_signal'] = (
            df['price_above_ema'] & 
            df['strong_trend'] & 
            df['positive_direction'] & 
            df['di_difference'] & 
            df['high_volume']
        ).fillna(False)
        
        logger.info(f"✅ Индикаторы рассчитаны. Найдено {df['buy_signal'].sum()} сигналов покупки")
    
    def simulate_trading(self, df: pd.DataFrame):
        """Симуляция торговли"""
        logger.info("🎯 Симуляция торговых сигналов...")
        
        for i in range(1, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i-1]
            
            # Проверка сигнала входа
            if not self.current_position and row['buy_signal'] and not prev_row['buy_signal']:
                # Новый сигнал покупки
                self.current_position = Trade(
                    entry_time=row['timestamp'],
                    entry_price=row['close'],
                    signal_data={
                        'ema20': row['ema20'],
                        'adx': row['adx'],
                        'plus_di': row['plus_di'],
                        'minus_di': row['minus_di'],
                        'volume_ratio': row['volume_ratio']
                    }
                )
                logger.debug(f"📈 Вход в позицию: {row['timestamp']}, цена: {row['close']:.2f}")
            
            # Проверка сигнала выхода
            elif self.current_position and not row['buy_signal'] and prev_row['buy_signal']:
                # Условия перестали выполняться - выходим
                self.current_position.exit_time = row['timestamp']
                self.current_position.exit_price = row['close']
                
                self.trades.append(self.current_position)
                logger.debug(f"📉 Выход из позиции: {row['timestamp']}, цена: {row['close']:.2f}, прибыль: {self.current_position.profit_pct:.2f}%")
                
                self.current_position = None
        
        # Закрываем последнюю позицию, если она еще открыта
        if self.current_position:
            last_row = df.iloc[-1]
            self.current_position.exit_time = last_row['timestamp']
            self.current_position.exit_price = last_row['close']
            self.trades.append(self.current_position)
        
        logger.info(f"✅ Симуляция завершена. Всего сделок: {len(self.trades)}")
    
    def analyze_results(self, df: pd.DataFrame) -> dict:
        """Анализ результатов бэктеста"""
        if not self.trades:
            logger.warning("Нет сделок для анализа")
            return {}
        
        # Статистика по сделкам
        profits_pct = [trade.profit_pct for trade in self.trades]
        profits_rub = [trade.profit_rub for trade in self.trades]
        durations = [trade.duration_hours for trade in self.trades]
        
        # Прибыльные и убыточные сделки
        profitable_trades = [p for p in profits_pct if p > 0]
        losing_trades = [p for p in profits_pct if p < 0]
        
        # Основная статистика
        total_return_pct = sum(profits_pct)
        win_rate = len(profitable_trades) / len(self.trades) * 100
        avg_profit_pct = sum(profits_pct) / len(profits_pct)
        avg_duration = sum(durations) / len(durations)
        
        # Максимальные значения
        max_profit = max(profits_pct) if profits_pct else 0
        max_loss = min(profits_pct) if profits_pct else 0
        
        # Расчет просадки
        cumulative_returns = []
        running_return = 0
        for profit in profits_pct:
            running_return += profit
            cumulative_returns.append(running_return)
        
        # Максимальная просадка
        peak = cumulative_returns[0]
        max_drawdown = 0
        for value in cumulative_returns:
            if value > peak:
                peak = value
            drawdown = (peak - value)
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        results = {
            'total_trades': len(self.trades),
            'profitable_trades': len(profitable_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'total_return_pct': total_return_pct,
            'avg_return_pct': avg_profit_pct,
            'max_profit_pct': max_profit,
            'max_loss_pct': max_loss,
            'avg_duration_hours': avg_duration,
            'max_drawdown_pct': max_drawdown,
            'avg_profit_when_win': sum(profitable_trades) / len(profitable_trades) if profitable_trades else 0,
            'avg_loss_when_lose': sum(losing_trades) / len(losing_trades) if losing_trades else 0,
            'profit_factor': abs(sum(profitable_trades) / sum(losing_trades)) if losing_trades else float('inf'),
            'period_start': df.iloc[0]['timestamp'],
            'period_end': df.iloc[-1]['timestamp'],
            'total_hours': (df.iloc[-1]['timestamp'] - df.iloc[0]['timestamp']).total_seconds() / 3600
        }
        
        return results
    
    def print_results(self, results: dict):
        """Вывод результатов бэктеста"""
        if not results:
            print("❌ Нет результатов для отображения")
            return
        
        print("\n" + "="*60)
        print("📊 РЕЗУЛЬТАТЫ БЭКТЕСТА СТРАТЕГИИ SBER")
        print("="*60)
        
        # Период тестирования
        print(f"🗓️  Период: {results['period_start'].strftime('%d.%m.%Y %H:%M')} - {results['period_end'].strftime('%d.%m.%Y %H:%M')}")
        print(f"⏱️  Общая продолжительность: {results['total_hours']:.0f} часов ({results['total_hours']/24:.1f} дней)")
        
        print("\n" + "-"*40)
        print("📈 ОСНОВНЫЕ ПОКАЗАТЕЛИ")
        print("-"*40)
        print(f"💼 Всего сделок: {results['total_trades']}")
        print(f"✅ Прибыльных: {results['profitable_trades']} ({results['win_rate']:.1f}%)")
        print(f"❌ Убыточных: {results['losing_trades']} ({100-results['win_rate']:.1f}%)")
        
        print(f"\n💰 Общая доходность: {results['total_return_pct']:+.2f}%")
        print(f"📊 Средняя доходность за сделку: {results['avg_return_pct']:+.2f}%")
        print(f"⏳ Среднее время в позиции: {results['avg_duration_hours']:.1f} часа")
        
        print("\n" + "-"*40)  
        print("📊 ДЕТАЛЬНАЯ СТАТИСТИКА")
        print("-"*40)
        print(f"🚀 Лучшая сделка: +{results['max_profit_pct']:.2f}%")
        print(f"💥 Худшая сделка: {results['max_loss_pct']:+.2f}%")
        print(f"📈 Средняя прибыль (при выигрыше): +{results['avg_profit_when_win']:.2f}%")
        
        if results['avg_loss_when_lose'] != 0:
            print(f"📉 Средний убыток (при проигрыше): {results['avg_loss_when_lose']:+.2f}%")
        
        print(f"🎯 Profit Factor: {results['profit_factor']:.2f}")
        print(f"📉 Максимальная просадка: -{results['max_drawdown_pct']:.2f}%")
        
        print("\n" + "-"*40)
        print("📋 ДЕТАЛИ СДЕЛОК")
        print("-"*40)
        
        for i, trade in enumerate(self.trades[:10], 1):  # Показываем первые 10 сделок
            entry_str = trade.entry_time.strftime('%d.%m %H:%M')
            
            # Безопасное форматирование exit_time и exit_price
            if trade.exit_time:
                exit_str = trade.exit_time.strftime('%d.%m %H:%M')
            else:
                exit_str = '---'
                
            if trade.exit_price is not None:
                exit_price_str = f"{trade.exit_price:.2f}"
            else:
                exit_price_str = "---"
            
            # Безопасное форматирование процентов и часов
            profit_str = f"{trade.profit_pct:+6.2f}" if trade.exit_price is not None else "  ---"
            duration_str = f"{trade.duration_hours:5.1f}" if trade.exit_time is not None else " ---"
            
            print(f"{i:2d}. {entry_str} | {trade.entry_price:.2f} ₽ → {exit_price_str} ₽ | "
                  f"{profit_str}% | {duration_str}ч")
        
        if len(self.trades) > 10:
            print(f"... и еще {len(self.trades) - 10} сделок")
        
        print("\n" + "="*60)
        
        # Оценка стратегии
        if results['win_rate'] >= 60 and results['total_return_pct'] > 0:
            print("✅ СТРАТЕГИЯ ПОКАЗЫВАЕТ ХОРОШИЕ РЕЗУЛЬТАТЫ")
        elif results['total_return_pct'] > 0:
            print("🟡 СТРАТЕГИЯ ПРИБЫЛЬНАЯ, НО ТРЕБУЕТ ДОРАБОТКИ") 
        else:
            print("❌ СТРАТЕГИЯ УБЫТОЧНАЯ, НУЖНА ЗНАЧИТЕЛЬНАЯ ДОРАБОТКА")
        
        print("="*60)

async def main():
    """Главная функция бэктеста"""
    
    # Получаем токен Tinkoff
    tinkoff_token = os.getenv('TINKOFF_TOKEN')
    if not tinkoff_token:
        logger.error("Не задан TINKOFF_TOKEN в переменных окружения")
        return
    
    try:
        # Создаем провайдер данных
        data_provider = TinkoffDataProvider(tinkoff_token)
        
        # Создаем движок бэктеста
        backtest_engine = BacktestEngine(data_provider)
        
        # Запускаем бэктест (за последние 30 дней = 720 часов)
        results = await backtest_engine.run_backtest(hours_back=720)
        
        # Выводим результаты
        backtest_engine.print_results(results)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
