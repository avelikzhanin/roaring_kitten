#!/usr/bin/env python3
"""
Простой бэктест поиска сигналов SBER для Railway
Исправленная версия с принудительным выводом логов
"""

import os
import sys
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import json
from dataclasses import dataclass, asdict
import logging
import traceback

# КРИТИЧЕСКИ ВАЖНО: Принудительный вывод без буферизации
os.environ['PYTHONUNBUFFERED'] = '1'
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

def force_print(msg: str):
    """Принудительный вывод с немедленным флешем"""
    print(msg)
    sys.stdout.flush()
    sys.stderr.flush()

# Настройка логирования для Railway
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
    force=True
)

# Принудительное отключение буферизации для логгера
for handler in logging.root.handlers:
    handler.setStream(sys.stdout)
    if hasattr(handler.stream, 'reconfigure'):
        handler.stream.reconfigure(line_buffering=True)

logger = logging.getLogger(__name__)

# Проверка импортов с принудительным выводом
force_print("🔍 НАЧАЛО ПРОВЕРКИ ИМПОРТОВ...")
force_print(f"Python версия: {sys.version}")
force_print(f"Pandas версия: {pd.__version__}")
force_print(f"Numpy версия: {np.__version__}")

try:
    from tinkoff.invest import Client, RequestError, CandleInterval, HistoricCandle
    from tinkoff.invest.utils import now
    TINKOFF_AVAILABLE = True
    force_print("✅ tinkoff-investments импортирован успешно")
except ImportError as e:
    force_print(f"⚠️ tinkoff-investments НЕ доступен: {e}")
    TINKOFF_AVAILABLE = False

@dataclass
class SignalData:
    """Простая структура сигнала"""
    timestamp: str
    price: float
    ema20: float
    adx: float
    plus_di: float
    minus_di: float
    di_diff: float
    signal_strength: float

def calculate_ema(prices: List[float], period: int = 20) -> List[float]:
    """Простой расчет EMA"""
    try:
        if len(prices) < period:
            return [np.nan] * len(prices)
        
        series = pd.Series(prices)
        ema = series.ewm(span=period, adjust=False).mean()
        return ema.fillna(np.nan).tolist()
    except Exception as e:
        force_print(f"❌ Ошибка расчета EMA: {e}")
        return [np.nan] * len(prices)

def calculate_adx_simple(highs: List[float], lows: List[float], closes: List[float], period: int = 14):
    """Упрощенный расчет ADX"""
    try:
        n = len(highs)
        if n < period * 2:
            return [np.nan] * n, [np.nan] * n, [np.nan] * n
        
        # True Range
        tr_list = []
        for i in range(1, n):
            hl = highs[i] - lows[i]
            hc = abs(highs[i] - closes[i-1])
            lc = abs(lows[i] - closes[i-1])
            tr = max(hl, hc, lc)
            tr_list.append(tr)
        
        tr_list = [0] + tr_list
        
        # Directional Movement
        plus_dm = []
        minus_dm = []
        
        for i in range(1, n):
            up_move = highs[i] - highs[i-1]
            down_move = lows[i-1] - lows[i]
            
            if up_move > down_move and up_move > 0:
                plus_dm.append(up_move)
            else:
                plus_dm.append(0)
                
            if down_move > up_move and down_move > 0:
                minus_dm.append(down_move)
            else:
                minus_dm.append(0)
        
        plus_dm = [0] + plus_dm
        minus_dm = [0] + minus_dm
        
        # Простое сглаживание
        atr = []
        plus_dm_smooth = []
        minus_dm_smooth = []
        
        for i in range(n):
            if i < period:
                atr.append(np.nan)
                plus_dm_smooth.append(np.nan)
                minus_dm_smooth.append(np.nan)
            else:
                start_idx = max(0, i - period + 1)
                atr.append(sum(tr_list[start_idx:i+1]) / period)
                plus_dm_smooth.append(sum(plus_dm[start_idx:i+1]) / period)
                minus_dm_smooth.append(sum(minus_dm[start_idx:i+1]) / period)
        
        # DI calculation
        plus_di = []
        minus_di = []
        adx = []
        
        for i in range(n):
            if np.isnan(atr[i]) or atr[i] == 0:
                plus_di.append(np.nan)
                minus_di.append(np.nan)
                adx.append(np.nan)
            else:
                pdi = (plus_dm_smooth[i] / atr[i]) * 100
                mdi = (minus_dm_smooth[i] / atr[i]) * 100
                plus_di.append(pdi)
                minus_di.append(mdi)
                
                # Простой ADX
                if pdi + mdi == 0:
                    adx.append(0)
                else:
                    dx = abs(pdi - mdi) / (pdi + mdi) * 100
                    
                    if i < period * 2:
                        adx.append(np.nan)
                    else:
                        start_idx = max(0, i - period + 1)
                        adx_values = []
                        for j in range(start_idx, i + 1):
                            if j < len(plus_di) and not np.isnan(plus_di[j]) and not np.isnan(minus_di[j]):
                                if plus_di[j] + minus_di[j] != 0:
                                    dx_j = abs(plus_di[j] - minus_di[j]) / (plus_di[j] + minus_di[j]) * 100
                                    adx_values.append(dx_j)
                        
                        if adx_values:
                            adx.append(sum(adx_values) / len(adx_values))
                        else:
                            adx.append(np.nan)
        
        return adx, plus_di, minus_di
        
    except Exception as e:
        force_print(f"❌ Ошибка расчета ADX: {e}")
        n = len(highs)
        return [np.nan] * n, [np.nan] * n, [np.nan] * n

def generate_test_data(days: int = 30) -> pd.DataFrame:
    """Генерация простых тестовых данных"""
    try:
        force_print(f"🔧 Генерация тестовых данных на {days} дней...")
        
        hours = days * 8
        timestamps = []
        base_time = datetime.now(timezone.utc) - timedelta(days=days)
        
        for i in range(hours):
            timestamps.append(base_time + timedelta(hours=i))
        
        np.random.seed(42)
        base_price = 280.0
        prices = []
        
        for i in range(hours):
            if i == 0:
                prices.append(base_price)
            else:
                change = np.random.normal(0, 2)
                new_price = max(prices[-1] + change, 250)
                prices.append(new_price)
        
        highs = [p + np.random.uniform(0.5, 3) for p in prices]
        lows = [p - np.random.uniform(0.5, 3) for p in prices]
        volumes = [np.random.randint(1000000, 5000000) for _ in range(hours)]
        
        df = pd.DataFrame({
            'timestamp': timestamps,
            'open': prices,
            'high': highs,
            'low': lows,
            'close': prices,
            'volume': volumes
        })
        
        force_print(f"✅ Создано {len(df)} тестовых свечей")
        return df
        
    except Exception as e:
        force_print(f"❌ Ошибка генерации данных: {e}")
        traceback.print_exc()
        return pd.DataFrame()

async def get_real_data() -> pd.DataFrame:
    """Получение реальных данных"""
    token = os.getenv('TINKOFF_TOKEN')
    
    if not token or not TINKOFF_AVAILABLE:
        force_print("📝 Токен не найден или tinkoff-investments недоступен")
        return pd.DataFrame()
    
    try:
        force_print("📡 Попытка получить реальные данные...")
        
        with Client(token) as client:
            to_time = now()
            from_time = to_time - timedelta(hours=200)
            
            response = client.market_data.get_candles(
                figi="BBG004730N88",  # SBER
                from_=from_time,
                to=to_time,
                interval=CandleInterval.CANDLE_INTERVAL_HOUR
            )
            
            if not response.candles:
                force_print("⚠️ Нет данных от API")
                return pd.DataFrame()
            
            data = []
            for candle in response.candles:
                try:
                    price = float(candle.close.units + candle.close.nano / 1e9)
                    high = float(candle.high.units + candle.high.nano / 1e9)
                    low = float(candle.low.units + candle.low.nano / 1e9)
                    
                    data.append({
                        'timestamp': candle.time,
                        'open': price,
                        'high': high,
                        'low': low,
                        'close': price,
                        'volume': candle.volume
                    })
                except Exception as e:
                    force_print(f"⚠️ Ошибка обработки свечи: {e}")
                    continue
            
            if not data:
                force_print("❌ Не удалось обработать данные")
                return pd.DataFrame()
            
            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            force_print(f"✅ Получено {len(df)} реальных свечей")
            return df
            
    except Exception as e:
        force_print(f"❌ Ошибка получения реальных данных: {e}")
        traceback.print_exc()
        return pd.DataFrame()

def find_signals(df: pd.DataFrame) -> List[SignalData]:
    """Поиск сигналов"""
    try:
        force_print("🔍 Начинаем поиск сигналов...")
        
        if df.empty:
            force_print("❌ Пустой DataFrame")
            return []
        
        force_print("📊 Расчет EMA20...")
        closes = df['close'].tolist()
        ema20_list = calculate_ema(closes, 20)
        
        force_print("📊 Расчет ADX...")
        highs = df['high'].tolist()
        lows = df['low'].tolist()
        adx_list, plus_di_list, minus_di_list = calculate_adx_simple(highs, lows, closes, 14)
        
        df['ema20'] = ema20_list
        df['adx'] = adx_list
        df['plus_di'] = plus_di_list
        df['minus_di'] = minus_di_list
        
        force_print("🎯 Поиск условий сигналов...")
        signals = []
        
        for i, row in df.iterrows():
            try:
                if (pd.isna(row['ema20']) or pd.isna(row['adx']) or 
                    pd.isna(row['plus_di']) or pd.isna(row['minus_di'])):
                    continue
                
                price_above_ema = row['close'] > row['ema20']
                adx_strong = row['adx'] > 25
                bullish_di = row['plus_di'] > row['minus_di']
                
                if price_above_ema and adx_strong and bullish_di:
                    strength = 0
                    strength += min(row['adx'] / 50 * 40, 40)
                    strength += min((row['plus_di'] - row['minus_di']) / 20 * 30, 30)
                    strength += min(((row['close'] - row['ema20']) / row['ema20'] * 100) / 2 * 20, 20)
                    strength += 10
                    
                    signal = SignalData(
                        timestamp=row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                        price=round(row['close'], 2),
                        ema20=round(row['ema20'], 2),
                        adx=round(row['adx'], 2),
                        plus_di=round(row['plus_di'], 2),
                        minus_di=round(row['minus_di'], 2),
                        di_diff=round(row['plus_di'] - row['minus_di'], 2),
                        signal_strength=round(min(strength, 100), 1)
                    )
                    signals.append(signal)
                    
            except Exception as e:
                force_print(f"⚠️ Ошибка обработки строки {i}: {e}")
                continue
        
        force_print(f"🎯 Найдено {len(signals)} сигналов")
        return signals
        
    except Exception as e:
        force_print(f"❌ Критическая ошибка поиска сигналов: {e}")
        traceback.print_exc()
        return []

def print_results(signals: List[SignalData], total_candles: int, df: pd.DataFrame):
    """Вывод результатов - только период и все сигналы"""
    try:
        force_print("\n" + "="*80)
        force_print("🎯 СИГНАЛЫ SBER")
        force_print("="*80)
        
        # Период данных
        if not df.empty:
            start_time = df['timestamp'].min().strftime('%Y-%m-%d %H:%M')
            end_time = df['timestamp'].max().strftime('%Y-%m-%d %H:%M')
            force_print(f"\n📅 ПЕРИОД: {start_time} - {end_time}")
            force_print(f"📊 Всего свечей: {total_candles}")
        
        if len(signals) == 0:
            force_print(f"📈 Найдено сигналов: 0")
            force_print("\n❌ СИГНАЛЫ НЕ НАЙДЕНЫ")
            return
        
        force_print(f"📈 Найдено сигналов: {len(signals)}")
        force_print(f"\n🎯 ВСЕ СИГНАЛЫ:")
        force_print("="*80)
        
        # Выводим все сигналы в хронологическом порядке
        for i, signal in enumerate(signals, 1):
            force_print(f"\n{i:2d}. {signal.timestamp}")
            force_print(f"    💰 Цена: {signal.price:7.2f} ₽  |  EMA20: {signal.ema20:7.2f} ₽")
            force_print(f"    📊 ADX: {signal.adx:5.1f}  |  +DI: {signal.plus_di:5.1f}  |  -DI: {signal.minus_di:5.1f}")
            force_print(f"    💪 Сила сигнала: {signal.signal_strength:5.1f}%")
        
        # Сохранение результатов
        results_data = {
            'period_start': df['timestamp'].min().isoformat() if not df.empty else None,
            'period_end': df['timestamp'].max().isoformat() if not df.empty else None,
            'total_signals': len(signals),
            'total_candles': total_candles,
            'analysis_timestamp': datetime.now().isoformat(),
            'signals': [asdict(signal) for signal in signals]
        }
        
        with open('backtest_results.json', 'w', encoding='utf-8') as f:
            json.dump(results_data, f, ensure_ascii=False, indent=2)
        
        force_print(f"\n💾 Результаты сохранены в backtest_results.json")
        force_print("="*80)
        
    except Exception as e:
        force_print(f"❌ Ошибка вывода результатов: {e}")
        traceback.print_exc()

async def main():
    """Главная функция"""
    try:
        force_print("🚀 ЗАПУСК SBER BACKTEST")
        force_print(f"⏰ Время запуска: {datetime.now()}")
        force_print("-"*60)
        
        railway_env = os.getenv('RAILWAY_ENVIRONMENT')
        port = os.getenv('PORT', '8000')
        
        if railway_env:
            force_print(f"🚂 Railway окружение: {railway_env}")
            force_print(f"🔌 Порт: {port}")
        else:
            force_print("🏠 Локальное окружение")
        
        force_print("🔄 Получение данных...")
        
        # Пробуем получить реальные данные
        df = await get_real_data()
        
        # Если не получилось - используем тестовые
        if df.empty:
            force_print("🔧 Используем тестовые данные...")
            df = generate_test_data(30)
        
        if df.empty:
            force_print("❌ Не удалось получить данные")
            return
        
        force_print(f"✅ Данные получены: {len(df)} свечей")
        force_print(f"📅 Период: {df['timestamp'].min()} - {df['timestamp'].max()}")
        
        # Поиск сигналов
        signals = find_signals(df)
        
        # Вывод результатов
        print_results(signals, len(df), df)
        
        force_print(f"\n✅ Анализ завершен успешно!")
        
        # Для Railway - остаемся живыми
        if railway_env:
            force_print(f"\n🚂 Держим процесс живым для Railway...")
            
            count = 0
            while True:
                await asyncio.sleep(300)  # 5 минут
                count += 1
                force_print(f"💓 Heartbeat #{count}: {datetime.now().strftime('%H:%M:%S')}")
                
                # Каждые 30 минут показываем статистику
                if count % 6 == 0:
                    force_print(f"📊 Статистика: найдено {len(signals)} сигналов из {len(df)} свечей")
        
    except KeyboardInterrupt:
        force_print("\n👋 Процесс остановлен пользователем")
    except Exception as e:
        force_print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        traceback.print_exc()
        
        # Даже при ошибке пытаемся остаться живыми для Railway
        railway_env = os.getenv('RAILWAY_ENVIRONMENT')
        if railway_env:
            force_print("🚂 Пытаемся остаться живыми несмотря на ошибку...")
            try:
                while True:
                    await asyncio.sleep(600)  # 10 минут
                    force_print(f"💔 Процесс с ошибкой жив: {datetime.now().strftime('%H:%M:%S')}")
            except:
                pass

if __name__ == "__main__":
    force_print("🎯 SBER BACKTEST - СТАРТ")
    force_print(f"🐍 Python: {sys.executable}")
    force_print(f"📁 Рабочая папка: {os.getcwd()}")
    force_print(f"🔧 Переменные: PORT={os.getenv('PORT')}, RAILWAY={os.getenv('RAILWAY_ENVIRONMENT')}")
    
    try:
        asyncio.run(main())
    except Exception as e:
        force_print(f"❌ Ошибка asyncio.run: {e}")
        traceback.print_exc()
        sys.exit(1)
