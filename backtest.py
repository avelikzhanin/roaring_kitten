#!/usr/bin/env python3
"""
Простой бэктест поиска сигналов SBER для Railway
Только реальные данные через Tinkoff API за весь август
Анализ сигналов с 15 по 26 августа
"""

import os
import sys
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from dataclasses import dataclass
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
    force_print(f"❌ tinkoff-investments НЕ доступен: {e}")
    force_print("❌ КРИТИЧЕСКАЯ ОШИБКА: Без Tinkoff API работа невозможна!")
    sys.exit(1)

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
    """Классический расчет ADX по формуле Уайлдера"""
    try:
        n = len(highs)
        if n < period * 2:
            return [np.nan] * n, [np.nan] * n, [np.nan] * n
        
        # 1. True Range
        tr_list = []
        for i in range(n):
            if i == 0:
                tr = highs[i] - lows[i]
            else:
                hl = highs[i] - lows[i]
                hc = abs(highs[i] - closes[i-1])
                lc = abs(lows[i] - closes[i-1])
                tr = max(hl, hc, lc)
            tr_list.append(tr)
        
        # 2. Directional Movement
        plus_dm = []
        minus_dm = []
        
        for i in range(n):
            if i == 0:
                plus_dm.append(0)
                minus_dm.append(0)
            else:
                up_move = highs[i] - highs[i-1]
                down_move = lows[i-1] - lows[i]
                
                if up_move > down_move and up_move > 0:
                    plus_dm.append(up_move)
                    minus_dm.append(0)
                elif down_move > up_move and down_move > 0:
                    plus_dm.append(0)
                    minus_dm.append(down_move)
                else:
                    plus_dm.append(0)
                    minus_dm.append(0)
        
        # 3. Сглаживание Уайлдера
        def smooth_wilder(values, period):
            result = [np.nan] * len(values)
            
            if len(values) >= period:
                result[period-1] = sum(values[:period]) / period
                
                for i in range(period, len(values)):
                    result[i] = (result[i-1] * (period-1) + values[i]) / period
            
            return result
        
        # Сглаживаем TR, +DM, -DM
        atr_smooth = smooth_wilder(tr_list, period)
        plus_dm_smooth = smooth_wilder(plus_dm, period)
        minus_dm_smooth = smooth_wilder(minus_dm, period)
        
        # 4. Расчет +DI и -DI
        plus_di = []
        minus_di = []
        dx_values = []
        
        for i in range(n):
            if i < period-1 or atr_smooth[i] == 0 or np.isnan(atr_smooth[i]):
                plus_di.append(np.nan)
                minus_di.append(np.nan)
                dx_values.append(np.nan)
            else:
                pdi = (plus_dm_smooth[i] / atr_smooth[i]) * 100
                mdi = (minus_dm_smooth[i] / atr_smooth[i]) * 100
                plus_di.append(pdi)
                minus_di.append(mdi)
                
                if (pdi + mdi) == 0:
                    dx_values.append(0)
                else:
                    dx = abs(pdi - mdi) / (pdi + mdi) * 100
                    dx_values.append(dx)
        
        # 5. ADX - сглаживание DX
        adx_values = [np.nan] * len(dx_values)
        
        first_valid_idx = None
        for i in range(len(dx_values)):
            if not np.isnan(dx_values[i]):
                first_valid_idx = i
                break
        
        if first_valid_idx is not None and first_valid_idx + period <= len(dx_values):
            valid_dx = []
            start_idx = first_valid_idx
            
            for i in range(start_idx, min(start_idx + period, len(dx_values))):
                if not np.isnan(dx_values[i]):
                    valid_dx.append(dx_values[i])
            
            if len(valid_dx) >= period:
                first_adx = sum(valid_dx[:period]) / period
                adx_idx = start_idx + period - 1
                if adx_idx < len(adx_values):
                    adx_values[adx_idx] = first_adx
                    
                    for i in range(adx_idx + 1, len(dx_values)):
                        if not np.isnan(dx_values[i]):
                            adx_values[i] = (adx_values[i-1] * (period-1) + dx_values[i]) / period
                        else:
                            adx_values[i] = adx_values[i-1] if i > 0 else np.nan
        
        return adx_values, plus_di, minus_di
        
    except Exception as e:
        force_print(f"❌ Ошибка расчета ADX: {e}")
        traceback.print_exc()
        n = len(highs)
        return [np.nan] * n, [np.nan] * n, [np.nan] * n

async def get_real_data() -> pd.DataFrame:
    """Получение реальных данных за весь август через Tinkoff API"""
    token = os.getenv('TINKOFF_TOKEN')
    
    if not token:
        force_print("❌ TINKOFF_TOKEN не найден в переменных окружения!")
        return pd.DataFrame()
    
    try:
        force_print("📡 Получение реальных данных за весь август 2025...")
        
        with Client(token) as client:
            # Получаем данные за весь август для точного расчета индикаторов
            moscow_tz = timezone(timedelta(hours=3))
            from_time = datetime(2025, 8, 1, 0, 0, tzinfo=moscow_tz).astimezone(timezone.utc)
            to_time = datetime(2025, 8, 31, 23, 59, tzinfo=moscow_tz).astimezone(timezone.utc)
            
            force_print(f"📅 Запрос данных: весь август 2025")
            
            response = client.market_data.get_candles(
                figi="BBG004730N88",  # SBER
                from_=from_time,
                to=to_time,
                interval=CandleInterval.CANDLE_INTERVAL_HOUR
            )
            
            if not response.candles:
                force_print("❌ Нет данных от Tinkoff API")
                return pd.DataFrame()
            
            data = []
            for candle in response.candles:
                try:
                    price = float(candle.close.units + candle.close.nano / 1e9)
                    high = float(candle.high.units + candle.high.nano / 1e9)
                    low = float(candle.low.units + candle.low.nano / 1e9)
                    open_price = float(candle.open.units + candle.open.nano / 1e9)
                    
                    data.append({
                        'timestamp': candle.time,
                        'open': open_price,
                        'high': high,
                        'low': low,
                        'close': price,
                        'volume': candle.volume
                    })
                except Exception as e:
                    force_print(f"⚠️ Ошибка обработки свечи: {e}")
                    continue
            
            if not data:
                force_print("❌ Не удалось обработать данные от API")
                return pd.DataFrame()
            
            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
            df['timestamp'] = df['timestamp'].dt.tz_convert('Europe/Moscow')
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            force_print(f"✅ Получено {len(df)} свечей за август")
            force_print(f"📅 Период данных: {df['timestamp'].min()} - {df['timestamp'].max()}")
            return df
            
    except Exception as e:
        force_print(f"❌ Ошибка получения данных от Tinkoff API: {e}")
        traceback.print_exc()
        return pd.DataFrame()

def find_signals(df: pd.DataFrame) -> List[SignalData]:
    """Поиск сигналов в период с 15 по 26 августа"""
    try:
        force_print("🔍 Начинаем анализ сигналов...")
        
        if df.empty:
            force_print("❌ Пустой DataFrame")
            return []
        
        force_print("📊 Расчет индикаторов...")
        closes = df['close'].tolist()
        ema20_list = calculate_ema(closes, 20)
        
        highs = df['high'].tolist()
        lows = df['low'].tolist()
        adx_list, plus_di_list, minus_di_list = calculate_adx_simple(highs, lows, closes, 14)
        
        df['ema20'] = ema20_list
        df['adx'] = adx_list
        df['plus_di'] = plus_di_list
        df['minus_di'] = minus_di_list
        
        # Фильтруем данные только за период анализа (15-26 августа)
        analysis_start = datetime(2025, 8, 15, 0, 0, tzinfo=timezone(timedelta(hours=3)))
        analysis_end = datetime(2025, 8, 26, 23, 59, tzinfo=timezone(timedelta(hours=3)))
        
        # Конвертируем timestamp в timezone-aware если нужно
        if df['timestamp'].dt.tz is None:
            df['timestamp'] = df['timestamp'].dt.tz_localize('Europe/Moscow')
        
        analysis_df = df[
            (df['timestamp'] >= analysis_start) & 
            (df['timestamp'] <= analysis_end)
        ].copy()
        
        force_print(f"🎯 Анализируем период 15-26 августа: {len(analysis_df)} свечей")
        
        signals = []
        
        for i, row in analysis_df.iterrows():
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
                        timestamp=row['timestamp'].strftime('%Y-%m-%d %H:%M MSK'),
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
        
        force_print(f"🎯 Найдено {len(signals)} сигналов за период 15-26 августа")
        return signals
        
    except Exception as e:
        force_print(f"❌ Критическая ошибка поиска сигналов: {e}")
        traceback.print_exc()
        return []

def print_results(signals: List[SignalData], df: pd.DataFrame):
    """Вывод результатов в логи"""
    try:
        force_print("\n" + "="*80)
        force_print("🎯 РЕЗУЛЬТАТЫ АНАЛИЗА SBER (15-26 АВГУСТА 2025)")
        force_print("="*80)
        
        if not df.empty:
            # Общий период данных
            force_print(f"📊 Получено данных за: {df['timestamp'].min().strftime('%Y-%m-%d %H:%M')} - {df['timestamp'].max().strftime('%Y-%m-%d %H:%M')} MSK")
            force_print(f"📈 Всего свечей: {len(df)}")
            
            # Период анализа
            analysis_start = datetime(2025, 8, 15, 0, 0, tzinfo=timezone(timedelta(hours=3)))
            analysis_end = datetime(2025, 8, 26, 23, 59, tzinfo=timezone(timedelta(hours=3)))
            
            if df['timestamp'].dt.tz is None:
                df_temp = df.copy()
                df_temp['timestamp'] = df_temp['timestamp'].dt.tz_localize('Europe/Moscow')
            else:
                df_temp = df
                
            analysis_candles = len(df_temp[
                (df_temp['timestamp'] >= analysis_start) & 
                (df_temp['timestamp'] <= analysis_end)
            ])
            
            force_print(f"🎯 Анализируемый период: 15-26 августа 2025")
            force_print(f"🕐 Свечей в периоде анализа: {analysis_candles}")
        
        if len(signals) == 0:
            force_print(f"\n❌ СИГНАЛЫ НЕ НАЙДЕНЫ")
            force_print("💡 В период 15-26 августа не было условий для генерации сигналов")
            return
        
        force_print(f"\n✅ НАЙДЕНО СИГНАЛОВ: {len(signals)}")
        force_print("="*80)
        
        for i, signal in enumerate(signals, 1):
            force_print(f"\n🚀 СИГНАЛ #{i}")
            force_print(f"📅 Время: {signal.timestamp}")
            force_print(f"💰 Цена: {signal.price} ₽")
            force_print(f"📊 EMA20: {signal.ema20} ₽")
            force_print(f"📈 ADX: {signal.adx}")
            force_print(f"📊 +DI: {signal.plus_di} | -DI: {signal.minus_di}")
            force_print(f"💪 Сила сигнала: {signal.signal_strength}%")
        
        force_print("\n" + "="*80)
        force_print(f"📋 ИТОГО: {len(signals)} сигналов найдено")
        force_print("="*80)
        
    except Exception as e:
        force_print(f"❌ Ошибка вывода результатов: {e}")
        traceback.print_exc()

async def main():
    """Главная функция"""
    try:
        force_print("🚀 ЗАПУСК SBER BACKTEST")
        force_print("📊 Получение данных за весь август для точных расчетов")
        force_print("🎯 Анализ сигналов: 15-26 августа 2025")
        force_print(f"⏰ Время запуска: {datetime.now()}")
        force_print("-"*60)
        
        railway_env = os.getenv('RAILWAY_ENVIRONMENT')
        if railway_env:
            force_print(f"🚂 Railway окружение: {railway_env}")
        else:
            force_print("🏠 Локальное окружение")
        
        # Получение данных через Tinkoff API
        df = await get_real_data()
        
        if df.empty:
            force_print("❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось получить данные от Tinkoff API")
            force_print("🔧 Проверьте:")
            force_print("   1. Переменную окружения TINKOFF_TOKEN")
            force_print("   2. Подключение к интернету")
            force_print("   3. Статус Tinkoff API")
            return
        
        # Поиск сигналов
        signals = find_signals(df)
        
        # Вывод результатов в логи
        print_results(signals, df)
        
        force_print(f"\n✅ АНАЛИЗ ЗАВЕРШЕН УСПЕШНО!")
        
    except KeyboardInterrupt:
        force_print("\n👋 Процесс остановлен пользователем")
    except Exception as e:
        force_print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    force_print("🎯 SBER BACKTEST - ТОЛЬКО РЕАЛЬНЫЕ ДАННЫЕ")
    force_print(f"🐍 Python: {sys.executable}")
    force_print(f"📁 Рабочая папка: {os.getcwd()}")
    
    token_status = "✅ Установлен" if os.getenv('TINKOFF_TOKEN') else "❌ Отсутствует"
    force_print(f"🔑 TINKOFF_TOKEN: {token_status}")
    
    if not os.getenv('TINKOFF_TOKEN'):
        force_print("❌ ОСТАНОВ: Необходимо установить TINKOFF_TOKEN!")
        sys.exit(1)
    
    try:
        asyncio.run(main())
    except Exception as e:
        force_print(f"❌ Ошибка asyncio.run: {e}")
        traceback.print_exc()
        sys.exit(1)
