import asyncio
import pandas as pd
import logging
import sys
import os

# Добавляем src в путь
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from data_provider import TinkoffDataProvider
from indicators import TechnicalIndicators

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MinimalBacktest:
    def __init__(self, token):
        self.provider = TinkoffDataProvider(token)
        self.trades = []
        
    async def run(self):
        print("🚀 МИНИМАЛЬНЫЙ БЭКТЕСТ SBER")
        print("-" * 40)
        
        # Получаем данные
        candles = await self.provider.get_candles(hours=720)  # 30 дней
        df = self.provider.candles_to_dataframe(candles)
        
        if len(df) < 100:
            print("❌ Недостаточно данных")
            return
            
        print(f"✅ Загружено {len(df)} свечей")
        
        # Расчет индикаторов
        closes = df['close'].tolist()
        highs = df['high'].tolist()
        lows = df['low'].tolist()
        
        # EMA20
        ema20 = TechnicalIndicators.calculate_ema(closes, 20)
        df['ema20'] = ema20
        
        # ADX
        adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
        df['adx'] = adx_data['adx']
        df['plus_di'] = adx_data['plus_di']
        df['minus_di'] = adx_data['minus_di']
        
        # Объемы
        df['vol_avg'] = df['volume'].rolling(20).mean()
        df['vol_ratio'] = df['volume'] / df['vol_avg']
        
        print("✅ Индикаторы рассчитаны")
        
        # Поиск сигналов
        in_position = False
        entry_price = 0
        total_trades = 0
        wins = 0
        total_profit = 0
        
        # Тестируем с 160-й свечи
        for i in range(160, len(df)):
            row = df.iloc[i]
            
            # Проверяем условия
            try:
                conditions = [
                    row['close'] > row['ema20'],  # Цена выше EMA
                    row['adx'] > 23,              # Сильный тренд
                    row['plus_di'] > row['minus_di'],  # Положительное направление
                    (row['plus_di'] - row['minus_di']) > 5,  # Разница > 5
                    row['vol_ratio'] > 1.47       # Высокий объем
                ]
                
                signal = all(pd.notna(c) and c for c in conditions)
            except:
                signal = False
            
            # Логика торговли
            if signal and not in_position:
                # Покупаем
                in_position = True
                entry_price = row['close']
                entry_time = row['timestamp']
                total_trades += 1
                
                date_str = entry_time.strftime('%d.%m %H:%M')
                price_str = str(round(entry_price, 2))
                print(f"📈 BUY #{total_trades}: {date_str} = {price_str}₽")
                
            elif not signal and in_position:
                # Продаем
                exit_price = row['close']
                exit_time = row['timestamp']
                
                # Считаем прибыль
                profit_pct = (exit_price - entry_price) / entry_price * 100
                total_profit += profit_pct
                
                if profit_pct > 0:
                    wins += 1
                    
                date_str = exit_time.strftime('%d.%m %H:%M')
                price_str = str(round(exit_price, 2))
                profit_str = str(round(profit_pct, 2))
                print(f"📉 SELL: {date_str} = {price_str}₽ ({profit_str}%)")
                
                in_position = False
        
        # Закрываем последнюю позицию если нужно
        if in_position:
            exit_price = df.iloc[-1]['close']
            profit_pct = (exit_price - entry_price) / entry_price * 100
            total_profit += profit_pct
            if profit_pct > 0:
                wins += 1
                
        print("\n" + "="*40)
        print("📊 РЕЗУЛЬТАТЫ")
        print("="*40)
        
        if total_trades > 0:
            win_rate = (wins / total_trades) * 100
            avg_profit = total_profit / total_trades
            annual_return = (total_profit / 30) * 365
            
            print(f"💼 Сделок: {total_trades}")
            print(f"✅ Прибыльных: {wins}")
            print(f"📈 Винрейт: {round(win_rate, 1)}%")
            print(f"💰 Общая прибыль: {round(total_profit, 2)}%")
            print(f"📊 Средняя прибыль: {round(avg_profit, 2)}%")
            print(f"🚀 Годовая (оценка): {round(annual_return, 1)}%")
            
            if win_rate >= 60 and total_profit > 0:
                print("\n✅ ХОРОШАЯ СТРАТЕГИЯ")
            elif total_profit > 0:
                print("\n🟡 ПРИБЫЛЬНАЯ СТРАТЕГИЯ")
            else:
                print("\n❌ УБЫТОЧНАЯ СТРАТЕГИЯ")
        else:
            print("❌ Сделок не найдено")
            
        print("="*40)

async def main():
    token = os.getenv('TINKOFF_TOKEN')
    if not token:
        print("❌ Нет токена TINKOFF_TOKEN")
        return
        
    try:
        backtest = MinimalBacktest(token)
        await backtest.run()
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
