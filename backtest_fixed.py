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

    def get_duration_hours(self) -> float:
        """Продолжительность сделки в часах"""
        if self.exit_time is not None:
            return (self.exit_time - self.entry_time).total_seconds() / 3600
        return 0

    def get_profit_pct(self) -> float:
        """Прибыль в процентах"""
        if self.exit_price is not None:
            return (self.exit_price - self.entry_price) / self.entry_price * 100
        return 0

    def get_profit_rub(self) -> float:
        """Прибыль в рублях на 1 акцию"""
        if self.exit_price is not None:
            return self.exit_price - self.entry_price
        return 0

class SimpleBacktest:
    """Простой бэктестер без проблематичного форматирования"""
    
    def __init__(self, token: str):
        self.provider = TinkoffDataProvider(token)
        self.trades = []
        
    async def run(self, days: int = 30):
        """Запуск бэктеста"""
        print("🚀 SBER Trading Bot - Независимый бэктестинг")
        print("-" * 60)
        
        logger.info("✅ Токен найден, запускаем бэктестинг...")
        logger.info(f"🔄 Анализ за {days} дней...")
        logger.info(f"🔄 Запуск бэктестинга за {days} дней...")
        
        # Получаем данные
        hours = days * 24
        candles = await self.provider.get_candles(hours=hours)
        
        if len(candles) < 100:
            logger.error("❌ Недостаточно данных")
            return
            
        df = self.provider.candles_to_dataframe(candles)
        logger.info("🔍 Анализ данных и поиск сигналов...")
        
        # Расчет индикаторов
        self.calculate_indicators(df)
        
        # Поиск сигналов
        self.find_signals(df)
        
        # Показ результатов
        self.show_results()
        
    def calculate_indicators(self, df):
        """Расчет индикаторов"""
        logger.info("📊 Расчет индикаторов...")
        
        # EMA20
        closes = df['close'].tolist()
        ema20_list = TechnicalIndicators.calculate_ema(closes, 20)
        df['ema20'] = ema20_list
        
        # ADX
        highs = df['high'].tolist()
        lows = df['low'].tolist()
        adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
        
        df['adx'] = adx_data['adx']
        df['plus_di'] = adx_data['plus_di'] 
        df['minus_di'] = adx_data['minus_di']
        
        # Объемы
        df['avg_volume'] = df['volume'].rolling(20, min_periods=1).mean()
        df['vol_ratio'] = df['volume'] / df['avg_volume']
        
        return df
        
    def find_signals(self, df):
        """Поиск торговых сигналов"""
        buy_signals = 0
        sell_signals = 0
        current_trade = None
        
        # Убираем первые 160 свечей для стабилизации индикаторов
        test_df = df.iloc[160:].copy().reset_index(drop=True)
        logger.info(f"📈 Тестовый период: {len(test_df)} свечей")
        
        for i in range(1, len(test_df)):
            row = test_df.iloc[i]
            prev_row = test_df.iloc[i-1]
            
            # Проверяем условия сигнала
            conditions = self.check_conditions(row)
            prev_conditions = self.check_conditions(prev_row)
            
            # Новый сигнал покупки
            if conditions and not prev_conditions and current_trade is None:
                buy_signals += 1
                current_trade = Trade(
                    entry_time=row['timestamp'],
                    entry_price=row['close']
                )
                
                date_str = row['timestamp'].strftime('%d.%m %H:%M')
                logger.info(f"📈 BUY #{buy_signals}: {date_str} = {row['close']:.2f}₽")
                
            # Сигнал продажи (условия перестали выполняться)
            elif not conditions and prev_conditions and current_trade is not None:
                sell_signals += 1
                current_trade.exit_time = row['timestamp']
                current_trade.exit_price = row['close']
                
                self.trades.append(current_trade)
                
                date_str = row['timestamp'].strftime('%d.%m %H:%M')
                logger.info(f"📉 SELL: {date_str} = {row['close']:.2f}₽")
                
                current_trade = None
        
        # Закрываем последнюю сделку если нужно
        if current_trade is not None:
            last_row = test_df.iloc[-1]
            current_trade.exit_time = last_row['timestamp']
            current_trade.exit_price = last_row['close']
            self.trades.append(current_trade)
            sell_signals += 1
            
        total_signals = buy_signals + sell_signals
        logger.info(f"🎯 Всего сигналов: {total_signals} (BUY: {buy_signals})")
        logger.info(f"💰 Создано сделок: {len(self.trades)}")
        
    def check_conditions(self, row):
        """Проверка условий стратегии"""
        try:
            price_above_ema = row['close'] > row['ema20']
            strong_trend = row['adx'] > 23
            positive_dir = row['plus_di'] > row['minus_di']
            di_diff = (row['plus_di'] - row['minus_di']) > 5
            high_volume = row['vol_ratio'] > 1.47
            
            # Проверяем на NaN
            conditions = [price_above_ema, strong_trend, positive_dir, di_diff, high_volume]
            return all(pd.notna(c) and c for c in conditions)
            
        except:
            return False
            
    def show_results(self):
        """Показ результатов без проблематичного форматирования"""
        print("\n" + "="*70)
        print("🎯 БЭКТЕСТИНГ SBER ЗА 30 ДНЕЙ")
        print("="*70)
        
        if not self.trades:
            print("❌ Сделок не найдено")
            return
            
        # Статистика
        total_trades = len(self.trades)
        profits = []
        durations = []
        
        profitable_count = 0
        
        for trade in self.trades:
            profit_pct = trade.get_profit_pct()
            profits.append(profit_pct)
            durations.append(trade.get_duration_hours())
            
            if profit_pct > 0:
                profitable_count += 1
                
        # Базовая статистика
        total_return = sum(profits)
        avg_return = total_return / len(profits)
        win_rate = (profitable_count / total_trades) * 100
        max_profit = max(profits)
        max_loss = min(profits)
        avg_duration = sum(durations) / len(durations)
        
        # Годовая доходность (приблизительная)
        annual_return = (total_return / 30) * 365
        
        print(f"📊 СИГНАЛЫ:")
        print(f" • Всего: {total_trades * 2}")  # Каждая сделка = вход + выход
        print(f" • Покупки: {total_trades}")
        print(f" • Продажи: {total_trades}")
        print()
        
        print(f"💼 СДЕЛКИ:")
        print(f" • Количество: {total_trades}")
        print(f" • Прибыльные: {profitable_count}")
        print(f" • Винрейт: {win_rate:.1f}%")
        print()
        
        print(f"💰 ДОХОДНОСТЬ:")
        print(f" • Общая: {total_return:.2f}%")
        print(f" • Средняя на сделку: {avg_return:.2f}%")
        print(f" • Макс прибыль: {max_profit:.2f}%") 
        print(f" • Макс убыток: {max_loss:.2f}%")
        print(f" • Годовая (оценка): {annual_return:.1f}%")
        print()
        
        print(f"⏰ ВРЕМЯ:")
        print(f" • Средняя длительность: {avg_duration:.1f}ч")
        print()
        
        print("📋 СДЕЛКИ:")
        self.print_trades_safe()
        
        print("\n" + "="*70)
        
        # Оценка
        if win_rate >= 60 and total_return > 0:
            print("✅ СТРАТЕГИЯ ПОКАЗЫВАЕТ ХОРОШИЕ РЕЗУЛЬТАТЫ")
        elif total_return > 0:
            print("🟡 СТРАТЕГИЯ ПРИБЫЛЬНАЯ, НО ТРЕБУЕТ ДОРАБОТКИ")
        else:
            print("❌ СТРАТЕГИЯ УБЫТОЧНАЯ")
            
        print("="*70)
        
    def print_trades_safe(self):
        """Безопасный вывод сделок без проблематичного форматирования"""
        for i, trade in enumerate(self.trades, 1):
            entry_date = trade.entry_time.strftime('%d.%m %H:%M')
            entry_price = trade.entry_price
            
            if trade.exit_time is not None:
                exit_date = trade.exit_time.strftime('%d.%m %H:%M')
            else:
                exit_date = "---"
                
            if trade.exit_price is not None:
                exit_price = trade.exit_price
                exit_price_str = f"{exit_price:.2f}"
                profit = trade.get_profit_pct()
                profit_str = f"{profit:+.2f}%"
            else:
                exit_price_str = "---"
                profit_str = "---"
                
            duration = trade.get_duration_hours()
            duration_str = f"{duration:.1f}ч" if duration > 0 else "---"
            
            print(f"{i:2d}. {entry_date} | {entry_price:.2f}₽ → {exit_price_str}₽ | {profit_str} | {duration_str}")

async def main():
    """Главная функция"""
    token = os.getenv('TINKOFF_TOKEN')
    if not token:
        logger.error("❌ Нет токена TINKOFF_TOKEN")
        return
        
    try:
        backtest = SimpleBacktest(token)
        await backtest.run(days=30)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
