#!/usr/bin/env python3
"""
Диагностический тест для выявления проблемы с ADX
Добавьте этот файл в Railway для тестирования
"""

import asyncio
import os
import sys
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

async def diagnose_adx_problem():
    """Диагностика проблемы с ADX"""
    
    print("🔬 ДИАГНОСТИКА ПРОБЛЕМЫ ADX", flush=True)
    print("=" * 50, flush=True)
    
    tinkoff_token = os.getenv("TINKOFF_TOKEN")
    if not tinkoff_token:
        print("❌ TINKOFF_TOKEN не найден!", flush=True)
        return
    
    try:
        from src.data_provider import TinkoffDataProvider
        from src.indicators import TechnicalIndicators
        import pandas as pd
        import numpy as np
        
        # 1. ТЕСТ РАЗНЫХ ПЕРИОДОВ ДАННЫХ
        print("\n1️⃣ ТЕСТ РАЗНЫХ ПЕРИОДОВ ДАННЫХ:", flush=True)
        
        provider = TinkoffDataProvider(tinkoff_token)
        
        periods_to_test = [50, 100, 150, 200]
        
        for hours in periods_to_test:
            print(f"\n📊 Тест с {hours} часами данных:", flush=True)
            
            candles = await provider.get_candles_for_ticker("BBG004730N88", hours=hours)
            if len(candles) < 30:
                print(f"   ❌ Мало данных: {len(candles)}", flush=True)
                continue
            
            df = provider.candles_to_dataframe(candles)
            if df.empty:
                print(f"   ❌ Пустой DataFrame", flush=True)
                continue
            
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            result = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            
            current_adx = result['adx'][-1] if not pd.isna(result['adx'][-1]) else None
            current_plus_di = result['plus_di'][-1] if not pd.isna(result['plus_di'][-1]) else None
            current_minus_di = result['minus_di'][-1] if not pd.isna(result['minus_di'][-1]) else None
            
            print(f"   ADX: {current_adx:.1f} | +DI: {current_plus_di:.1f} | -DI: {current_minus_di:.1f}", flush=True)
        
        # 2. ТЕСТ ПОСЛЕДНИХ N СВЕЧЕЙ
        print(f"\n2️⃣ ВЛИЯНИЕ КОЛИЧЕСТВА СВЕЧЕЙ НА РЕЗУЛЬТАТ:", flush=True)
        
        # Берем максимум данных
        candles = await provider.get_candles_for_ticker("BBG004730N88", hours=200)
        df = provider.candles_to_dataframe(candles)
        
        if not df.empty:
            full_closes = df['close'].tolist()
            full_highs = df['high'].tolist()
            full_lows = df['low'].tolist()
            
            test_sizes = [50, 75, 100, len(full_closes)]
            
            for size in test_sizes:
                if size <= len(full_closes):
                    test_closes = full_closes[-size:]
                    test_highs = full_highs[-size:]
                    test_lows = full_lows[-size:]
                    
                    result = TechnicalIndicators.calculate_adx(test_highs, test_lows, test_closes, 14)
                    
                    current_adx = result['adx'][-1] if not pd.isna(result['adx'][-1]) else None
                    current_plus_di = result['plus_di'][-1] if not pd.isna(result['plus_di'][-1]) else None
                    current_minus_di = result['minus_di'][-1] if not pd.isna(result['minus_di'][-1]) else None
                    
                    if current_adx:
                        error_from_target = abs(current_adx - 60.68)
                        print(f"   {size:3d} свечей: ADX:{current_adx:5.1f} +DI:{current_plus_di:5.1f} -DI:{current_minus_di:5.1f} (отклонение от 60.68: {error_from_target:4.1f})", flush=True)
        
        # 3. РУЧНАЯ ПРОВЕРКА ПОСЛЕДНИХ СВЕЧЕЙ
        print(f"\n3️⃣ РУЧНАЯ ПРОВЕРКА ДАННЫХ:", flush=True)
        
        if not df.empty and len(df) >= 10:
            print("   Последние 10 свечей:", flush=True)
            for i in range(len(df) - 10, len(df)):
                row = df.iloc[i]
                print(f"   [{i:2d}] {row['timestamp'].strftime('%d.%m %H:%M')} "
                      f"O:{row['open']:6.2f} H:{row['high']:6.2f} L:{row['low']:6.2f} C:{row['close']:6.2f}", flush=True)
            
            # Ручной расчет компонентов для последних 3 свечей
            print(f"\n   Ручной расчет TR и DM для последних 3 свечей:", flush=True)
            
            for i in range(len(df) - 3, len(df)):
                if i > 0:
                    curr_h, curr_l, curr_c = df.iloc[i]['high'], df.iloc[i]['low'], df.iloc[i]['close']
                    prev_h, prev_l, prev_c = df.iloc[i-1]['high'], df.iloc[i-1]['low'], df.iloc[i-1]['close']
                    
                    # True Range
                    tr1 = curr_h - curr_l
                    tr2 = abs(curr_h - prev_c)
                    tr3 = abs(curr_l - prev_c)
                    tr = max(tr1, tr2, tr3)
                    
                    # Directional Movement
                    high_diff = curr_h - prev_h
                    low_diff = prev_l - curr_l
                    
                    plus_dm = max(high_diff, 0) if high_diff > low_diff else 0
                    minus_dm = max(low_diff, 0) if low_diff > high_diff else 0
                    
                    print(f"   [{i:2d}] TR:{tr:5.2f} +DM:{plus_dm:5.2f} -DM:{minus_dm:5.2f}", flush=True)
        
        # 4. ПРОВЕРКА ВРЕМЕНИ ДАННЫХ
        print(f"\n4️⃣ ПРОВЕРКА ВРЕМЕНИ ДАННЫХ:", flush=True)
        
        if not df.empty:
            first_candle = df.iloc[0]
            last_candle = df.iloc[-1]
            
            print(f"   Первая свеча: {first_candle['timestamp']}", flush=True)
            print(f"   Последняя свеча: {last_candle['timestamp']}", flush=True)
            print(f"   Текущее время: {datetime.now()}", flush=True)
            
            # Проверка, насколько свежие данные
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            last_candle_time = pd.to_datetime(last_candle['timestamp'], utc=True)
            time_diff = (now - last_candle_time).total_seconds() / 3600  # в часах
            
            print(f"   Задержка данных: {time_diff:.1f} часов", flush=True)
            
            if time_diff > 2:
                print(f"   ⚠️ ВНИМАНИЕ: Данные могут быть устаревшими!", flush=True)
        
        # 5. ЭКСПЕРИМЕНТ С РАЗНЫМИ ПЕРИОДАМИ ADX
        print(f"\n5️⃣ ЭКСПЕРИМЕНТ С РАЗНЫМИ ПЕРИОДАМИ ADX:", flush=True)
        
        if not df.empty:
            test_periods = [10, 14, 18, 21]
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            for period in test_periods:
                result = TechnicalIndicators.calculate_adx(highs, lows, closes, period)
                
                current_adx = result['adx'][-1] if not pd.isna(result['adx'][-1]) else None
                current_plus_di = result['plus_di'][-1] if not pd.isna(result['plus_di'][-1]) else None
                current_minus_di = result['minus_di'][-1] if not pd.isna(result['minus_di'][-1]) else None
                
                if current_adx:
                    error_from_target = abs(current_adx - 60.68)
                    print(f"   Период {period:2d}: ADX:{current_adx:5.1f} +DI:{current_plus_di:5.1f} -DI:{current_minus_di:5.1f} (отклонение: {error_from_target:4.1f})", flush=True)
        
        print(f"\n" + "=" * 50, flush=True)
        print("🎯 ВЫВОДЫ:", flush=True)
        print("1. Проверьте какой тест дал результат ближе к 60.68", flush=True)
        print("2. Возможно нужно изменить количество часов данных", flush=True)
        print("3. Или использовать другой период для расчета ADX", flush=True)
        print("=" * 50, flush=True)
        
    except Exception as e:
        print(f"💥 Ошибка диагностики: {e}", flush=True)
        import traceback
        traceback.print_exc()

async def main():
    await diagnose_adx_problem()

if __name__ == "__main__":
    asyncio.run(main())
