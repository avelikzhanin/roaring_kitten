#!/usr/bin/env python3
"""
Бэктест поиска сигналов: цена > EMA20, ADX > 25, +DI > -DI
Для развертывания на Railway без Dockerfile
"""

import os
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import json
from dataclasses import dataclass, asdict
import logging

# Для работы с Tinkoff API
try:
    from tinkoff.invest import Client, RequestError, CandleInterval, HistoricCandle
    from tinkoff.invest.utils import now
    TINKOFF_AVAILABLE = True
except ImportError:
    print("⚠️ tinkoff-investments не установлен, используем симулированные данные")
    TINKOFF_AVAILABLE = False

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class SignalData:
    """Структура данных сигнала"""
    timestamp: str
    symbol: str
    price: float
    ema20: float
    adx: float
    plus_di: float
    minus_di: float
    volume: int
    price_vs_ema_pct: float
    di_diff: float
    signal_strength: float

class TechnicalIndicators:
    """Класс для расчета технических индикаторов"""
    
    @staticmethod
    def ema(data: pd.Series, period: int) -> pd.Series:
        """Экспоненциальная скользящая средняя"""
        return data.ewm(span=period, adjust=False).mean()
    
    @staticmethod
    def wilder_smoothing(values: pd.Series, period: int) -> pd.Series:
        """Сглаживание Уайлдера для ADX"""
        result = pd.Series(index=values.index, dtype=float)
        
        # Первое значение - среднее за период
        if len(values) >= period:
            first_avg = values.iloc[:period].mean()
            result.iloc[period-1] = first_avg
            
            # Остальные по формуле Уайлдера
            for i in range(period, len(values)):
                result.iloc[i] = (result.iloc[i-1] * (period - 1) + values.iloc[i]) / period
        
        return result
    
    @staticmethod
    def adx_calculation(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
        """Расчет ADX и Directional Indicators"""
        
        # True Range
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Directional Movement
        high_diff = high - high.shift(1)
        low_diff = low.shift(1) - low
        
        plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
        minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)
        
        plus_dm = pd.Series(plus_dm, index=high.index)
        minus_dm = pd.Series(minus_dm, index=high.index)
        
        # Сглаживание по Уайлдеру
        atr = TechnicalIndicators.wilder_smoothing(tr, period)
        plus_dm_smooth = TechnicalIndicators.wilder_smoothing(plus_dm, period)
        minus_dm_smooth = TechnicalIndicators.wilder_smoothing(minus_dm, period)
        
        # DI calculation
        plus_di = (plus_dm_smooth / atr) * 100
        minus_di = (minus_dm_smooth / atr) * 100
        
        # DX и ADX calculation
        di_sum = plus_di + minus_di
        di_diff = abs(plus_di - minus_di)
        dx = np.where(di_sum != 0, (di_diff / di_sum) * 100, 0)
        dx_series = pd.Series(dx, index=high.index)
        
        adx = TechnicalIndicators.wilder_smoothing(dx_series, period)
        
        return adx, plus_di, minus_di

class TinkoffDataProvider:
    """Провайдер данных Tinkoff (если доступен)"""
    
    def __init__(self, token: str):
        self.token = token
        self.figi = "BBG004730N88"  # SBER
    
    async def get_real_data(self, hours: int = 200) -> pd.DataFrame:
        """Получение реальных данных через API"""
        if not TINKOFF_AVAILABLE or not self.token:
            return pd.DataFrame()
        
        try:
            with Client(self.token) as client:
                to_time = now()
                from_time = to_time - timedelta(hours=hours)
                
                logger.info(f"📡 Запрос реальных данных SBER с {from_time.strftime('%d.%m %H:%M')} по {to_time.strftime('%d.%m %H:%M')}")
                
                response = client.market_data.get_candles(
                    figi=self.figi,
                    from_=from_time,
                    to=to_time,
                    interval=CandleInterval.CANDLE_INTERVAL_HOUR
                )
                
                if response.candles:
                    logger.info(f"✅ Получено {len(response.candles)} реальных свечей")
                    return self.candles_to_dataframe(response.candles)
                else:
                    logger.warning("⚠️ Получен пустой ответ от API")
                    return pd.DataFrame()
                    
        except Exception as e:
            logger.error(f"❌ Ошибка получения данных: {e}")
            return pd.DataFrame()
    
    def candles_to_dataframe(self, candles) -> pd.DataFrame:
        """Преобразование в DataFrame"""
        data = []
        for candle in candles:
            try:
                data.append({
                    'timestamp': candle.time,
                    'open': self.quotation_to_decimal(candle.open),
                    'high': self.quotation_to_decimal(candle.high),
                    'low': self.quotation_to_decimal(candle.low),
                    'close': self.quotation_to_decimal(candle.close),
                    'volume': candle.volume
                })
            except Exception as e:
                logger.error(f"Ошибка обработки свечи: {e}")
                continue
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df = df.sort_values('timestamp').reset_index(drop=True)
        df = df.drop_duplicates(subset=['timestamp'], keep='last')
        
        return df
    
    @staticmethod
    def quotation_to_decimal(quotation) -> float:
        """Преобразование quotation в decimal"""
        try:
            return float(quotation.units + quotation.nano / 1e9)
        except (AttributeError, TypeError):
            return 0.0

class DataGenerator:
    """Генератор данных для бэктеста"""
    
    def __init__(self, symbol: str = "SBER"):
        self.symbol = symbol
    
    def generate_sample_data(self, days: int = 90) -> pd.DataFrame:
        """Генерация образцов данных для тестирования"""
        logger.info(f"🔧 Генерация симулированных данных для {self.symbol} на {days} дней...")
        
        # Создаем временной индекс (каждый час торговых дней)
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)
        
        # Генерируем временные метки для торговых часов (10:00-18:30 МСК)
        timestamps = []
        current_date = start_date
        
        while current_date <= end_date:
            # Пропускаем выходные
            if current_date.weekday() < 5:  # 0-4 это понедельник-пятница
                for hour in range(10, 19):  # 10:00-18:00
                    timestamps.append(current_date.replace(hour=hour, minute=0, second=0))
                # Добавляем 18:30
                timestamps.append(current_date.replace(hour=18, minute=30, second=0))
            current_date += timedelta(days=1)
        
        n_points = len(timestamps)
        
        # Генерируем реалистичные данные SBER
        np.random.seed(42)  # Для воспроизводимости
        
        # Базовая цена SBER ~280 руб
        base_price = 280.0
        
        # Генерируем случайные изменения цены с трендами
        returns = np.random.normal(0, 0.008, n_points)  # Волатильность ~0.8%
        trend = np.sin(np.linspace(0, 4*np.pi, n_points)) * 0.015  # Циклические тренды
        returns += trend
        
        # Рассчитываем цены
        prices = [base_price]
        for i in range(1, n_points):
            new_price = prices[-1] * (1 + returns[i])
            prices.append(max(new_price, 250))  # Минимальная цена 250
        
        # Генерируем OHLC данные
        high_prices = [p * np.random.uniform(1.001, 1.015) for p in prices]
        low_prices = [p * np.random.uniform(0.985, 0.999) for p in prices]
        volumes = np.random.randint(800000, 5000000, n_points)
        
        df = pd.DataFrame({
            'timestamp': timestamps,
            'open': prices,
            'high': high_prices,
            'low': low_prices,
            'close': prices,
            'volume': volumes
        })
        
        logger.info(f"✅ Сгенерировано {len(df)} свечей")
        return df

class SignalScanner:
    """Сканер торговых сигналов"""
    
    def __init__(self, symbol: str = "SBER"):
        self.symbol = symbol
        self.indicators = TechnicalIndicators()
    
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Расчет всех технических индикаторов"""
        logger.info("📊 Расчет технических индикаторов...")
        
        # EMA20
        df['ema20'] = self.indicators.ema(df['close'], 20)
        
        # ADX и DI
        adx, plus_di, minus_di = self.indicators.adx_calculation(
            df['high'], df['low'], df['close'], 14
        )
        
        df['adx'] = adx
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di
        
        # Дополнительные метрики
        df['price_vs_ema_pct'] = ((df['close'] - df['ema20']) / df['ema20'] * 100)
        df['di_diff'] = df['plus_di'] - df['minus_di']
        
        logger.info("✅ Индикаторы рассчитаны")
        return df
    
    def find_signals(self, df: pd.DataFrame) -> List[SignalData]:
        """Поиск торговых сигналов по условиям: цена > EMA20, ADX > 25, +DI > -DI"""
        logger.info("🔍 Поиск сигналов по условиям...")
        
        signals = []
        
        # Фильтруем данные по условиям
        conditions = (
            (df['close'] > df['ema20']) &      # Цена выше EMA20
            (df['adx'] > 25) &                 # ADX > 25
            (df['plus_di'] > df['minus_di']) & # +DI > -DI
            (df['ema20'].notna()) &            # Есть данные для EMA
            (df['adx'].notna())                # Есть данные для ADX
        )
        
        filtered_df = df[conditions].copy()
        
        logger.info(f"📈 Найдено {len(filtered_df)} точек, удовлетворяющих условиям")
        
        # Создаем объекты сигналов
        for idx, row in filtered_df.iterrows():
            
            # Расчет силы сигнала (0-100%)
            signal_strength = self.calculate_signal_strength(row)
            
            signal = SignalData(
                timestamp=row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                symbol=self.symbol,
                price=round(row['close'], 2),
                ema20=round(row['ema20'], 2),
                adx=round(row['adx'], 2),
                plus_di=round(row['plus_di'], 2),
                minus_di=round(row['minus_di'], 2),
                volume=int(row['volume']),
                price_vs_ema_pct=round(row['price_vs_ema_pct'], 2),
                di_diff=round(row['di_diff'], 2),
                signal_strength=round(signal_strength, 1)
            )
            
            signals.append(signal)
        
        logger.info(f"🎯 Создано {len(signals)} сигналов")
        return signals
    
    def calculate_signal_strength(self, row) -> float:
        """Расчет силы сигнала (0-100%)"""
        strength = 0
        
        # 1. Сила тренда по ADX (0-30 баллов)
        if row['adx'] >= 50:
            adx_strength = 30
        elif row['adx'] >= 40:
            adx_strength = 25
        elif row['adx'] >= 30:
            adx_strength = 20
        else:
            adx_strength = max(0, (row['adx'] - 25) / 25 * 15)
        
        strength += adx_strength
        
        # 2. Доминирование покупателей по DI (0-25 баллов)
        di_dominance = min(row['di_diff'] / 20 * 25, 25)
        strength += di_dominance
        
        # 3. Превышение EMA (0-25 баллов)
        ema_distance = abs(row['price_vs_ema_pct'])
        if ema_distance < 0.5:
            ema_strength = 25  # Очень близко к EMA
        elif ema_distance < 1.0:
            ema_strength = 20
        elif ema_distance < 2.0:
            ema_strength = 15
        elif ema_distance < 5.0:
            ema_strength = 10
        else:
            ema_strength = 5  # Далеко от EMA
        
        strength += ema_strength
        
        # 4. Объем торгов (0-20 баллов)
        if row['volume'] > 4000000:
            volume_strength = 20
        elif row['volume'] > 3000000:
            volume_strength = 15
        elif row['volume'] > 2000000:
            volume_strength = 12
        elif row['volume'] > 1500000:
            volume_strength = 8
        else:
            volume_strength = 5
        
        strength += volume_strength
        
        return min(strength, 100)

class BacktestEngine:
    """Основной движок бэктеста"""
    
    def __init__(self, symbol: str = "SBER", use_real_data: bool = True):
        self.symbol = symbol
        self.use_real_data = use_real_data
        
        # Инициализируем провайдеры данных
        token = os.getenv('TINKOFF_TOKEN')
        self.tinkoff_provider = TinkoffDataProvider(token) if token else None
        self.data_generator = DataGenerator(symbol)
        self.scanner = SignalScanner(symbol)
    
    async def run_backtest(self, days: int = 90) -> Dict:
        """Запуск полного бэктеста"""
        logger.info(f"🚀 Запуск бэктеста для {self.symbol}")
        logger.info("=" * 80)
        
        try:
            # 1. Получение данных
            if self.use_real_data and self.tinkoff_provider and TINKOFF_AVAILABLE:
                df = await self.tinkoff_provider.get_real_data(days * 24 + 100)
                if df.empty:
                    logger.warning("⚠️ Не удалось получить реальные данные, используем симулированные")
                    df = self.data_generator.generate_sample_data(days)
            else:
                df = self.data_generator.generate_sample_data(days)
            
            if df.empty:
                raise Exception("Не удалось получить данные")
            
            # 2. Расчет индикаторов
            df_with_indicators = self.scanner.calculate_indicators(df)
            
            # 3. Поиск сигналов
            signals = self.scanner.find_signals(df_with_indicators)
            
            # 4. Анализ результатов
            analysis = self.analyze_signals(signals, df_with_indicators)
            
            return {
                'signals': signals,
                'analysis': analysis,
                'total_candles': len(df),
                'data_period': f"{df['timestamp'].min()} - {df['timestamp'].max()}",
                'data_source': 'real' if (self.use_real_data and self.tinkoff_provider) else 'simulated'
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка в бэктесте: {e}")
            return {}
    
    def analyze_signals(self, signals: List[SignalData], df: pd.DataFrame) -> Dict:
        """Анализ найденных сигналов"""
        if not signals:
            return {"error": "Сигналы не найдены"}
        
        # Статистика по силе сигналов
        strengths = [s.signal_strength for s in signals]
        
        # Распределение по времени
        timestamps = [datetime.strptime(s.timestamp, '%Y-%m-%d %H:%M:%S') for s in signals]
        hours = [ts.hour for ts in timestamps]
        hour_distribution = {}
        for hour in hours:
            hour_distribution[hour] = hour_distribution.get(hour, 0) + 1
        
        # Распределение по дням недели
        weekdays = [ts.weekday() for ts in timestamps]  # 0=понедельник
        weekday_names = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
        weekday_distribution = {}
        for wd in weekdays:
            name = weekday_names[wd]
            weekday_distribution[name] = weekday_distribution.get(name, 0) + 1
        
        # Статистика ADX
        adx_values = [s.adx for s in signals]
        
        # Статистика DI
        di_diffs = [s.di_diff for s in signals]
        
        # Статистика превышения EMA
        ema_distances = [s.price_vs_ema_pct for s in signals]
        
        analysis = {
            'total_signals': len(signals),
            'signal_strength': {
                'min': min(strengths),
                'max': max(strengths),
                'average': sum(strengths) / len(strengths),
                'median': sorted(strengths)[len(strengths)//2]
            },
            'adx_stats': {
                'min': min(adx_values),
                'max': max(adx_values),
                'average': sum(adx_values) / len(adx_values),
                'above_35': len([x for x in adx_values if x > 35]),
                'above_50': len([x for x in adx_values if x > 50])
            },
            'di_dominance': {
                'min': min(di_diffs),
                'max': max(di_diffs),
                'average': sum(di_diffs) / len(di_diffs),
                'above_10': len([x for x in di_diffs if x > 10]),
                'above_20': len([x for x in di_diffs if x > 20])
            },
            'ema_distance': {
                'min': min(ema_distances),
                'max': max(ema_distances),
                'average': sum(ema_distances) / len(ema_distances)
            },
            'time_distribution': hour_distribution,
            'weekday_distribution': weekday_distribution,
            'signals_per_day': len(signals) / 90  # За период
        }
        
        return analysis

def print_results(results: Dict):
    """Вывод результатов бэктеста"""
    if not results:
        print("❌ Результаты не получены")
        return
    
    signals = results['signals']
    analysis = results['analysis']
    
    print(f"\n{'='*80}")
    print(f"📊 РЕЗУЛЬТАТЫ ПОИСКА СИГНАЛОВ - {results.get('data_period', 'Неизвестный период')}")
    print(f"📡 Источник данных: {'РЕАЛЬНЫЕ' if results.get('data_source') == 'real' else 'СИМУЛИРОВАННЫЕ'}")
    print(f"{'='*80}")
    
    print(f"\n🎯 УСЛОВИЯ ПОИСКА:")
    print(f"   • Цена > EMA20")
    print(f"   • ADX > 25")
    print(f"   • +DI > -DI")
    
    print(f"\n🔍 ОБЩАЯ СТАТИСТИКА:")
    print(f"   • Всего свечей проанализировано: {results['total_candles']:,}")
    print(f"   • Найдено сигналов: {analysis['total_signals']}")
    print(f"   • Процент времени в сигнале: {(analysis['total_signals'] / results['total_candles'] * 100):.2f}%")
    print(f"   • Сигналов в день: {analysis['signals_per_day']:.1f}")
    
    print(f"\n📈 СИЛА СИГНАЛОВ:")
    strength_stats = analysis['signal_strength']
    print(f"   • Средняя сила: {strength_stats['average']:.1f}%")
    print(f"   • Медиана: {strength_stats['median']:.1f}%")
    print(f"   • Диапазон: {strength_stats['min']:.1f}% - {strength_stats['max']:.1f}%")
    
    # Распределение по силе
    strong_signals = [s for s in signals if s.signal_strength >= 80]
    medium_signals = [s for s in signals if 60 <= s.signal_strength < 80]
    weak_signals = [s for s in signals if s.signal_strength < 60]
    
    print(f"\n🔥 РАСПРЕДЕЛЕНИЕ ПО СИЛЕ:")
    print(f"   • Сильные (≥80%): {len(strong_signals)} ({len(strong_signals)/len(signals)*100:.1f}%)")
    print(f"   • Средние (60-80%): {len(medium_signals)} ({len(medium_signals)/len(signals)*100:.1f}%)")
    print(f"   • Слабые (<60%): {len(weak_signals)} ({len(weak_signals)/len(signals)*100:.1f}%)")
    
    print(f"\n📊 ADX СТАТИСТИКА:")
    adx_stats = analysis['adx_stats']
    print(f"   • Средний ADX: {adx_stats['average']:.1f}")
    print(f"   • Диапазон: {adx_stats['min']:.1f} - {adx_stats['max']:.1f}")
    print(f"   • ADX > 35: {adx_stats['above_35']} сигналов ({adx_stats['above_35']/len(signals)*100:.1f}%)")
    print(f"   • ADX > 50: {adx_stats['above_50']} сигналов ({adx_stats['above_50']/len(signals)*100:.1f}%)")
    
    print(f"\n🎯 ДОМИНИРОВАНИЕ ПОКУПАТЕЛЕЙ (+DI > -DI):")
    di_stats = analysis['di_dominance']
    print(f"   • Средняя разность: {di_stats['average']:.1f}")
    print(f"   • Диапазон: {di_stats['min']:.1f} - {di_stats['max']:.1f}")
    print(f"   • Разность > 10: {di_stats['above_10']} сигналов ({di_stats['above_10']/len(signals)*100:.1f}%)")
    print(f"   • Разность > 20: {di_stats['above_20']} сигналов ({di_stats['above_20']/len(signals)*100:.1f}%)")
    
    print(f"\n📏 ПРЕВЫШЕНИЕ EMA20:")
    ema_stats = analysis['ema_distance']
    print(f"   • Среднее превышение: {ema_stats['average']:.2f}%")
    print(f"   • Диапазон: {ema_stats['min']:.2f}% - {ema_stats['max']:.2f}%")
    
    print(f"\n⏰ РАСПРЕДЕЛЕНИЕ ПО ВРЕМЕНИ (часы):")
    time_dist = analysis['time_distribution']
    for hour in sorted(time_dist.keys()):
        count = time_dist[hour]
        percentage = (count / analysis['total_signals'] * 100)
        bar = "█" * int(percentage / 3)  # Масштабированная гистограмма
        print(f"   {hour:02d}:00 | {count:3d} сигналов ({percentage:4.1f}%) {bar}")
    
    print(f"\n📅 РАСПРЕДЕЛЕНИЕ ПО ДНЯМ НЕДЕЛИ:")
    weekday_dist = analysis['weekday_distribution']
    for day in ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']:
        count = weekday_dist.get(day, 0)
        if count > 0:
            percentage = (count / analysis['total_signals'] * 100)
            bar = "█" * int(percentage / 3)
            print(f"   {day} | {count:3d} сигналов ({percentage:4.1f}%) {bar}")
    
    # Топ-10 сильнейших сигналов
    print(f"\n🏆 ТОП-10 СИЛЬНЕЙШИХ СИГНАЛОВ:")
    sorted_signals = sorted(signals, key=lambda x: x.signal_strength, reverse=True)[:10]
    
    for i, signal in enumerate(sorted_signals, 1):
        dt = datetime.strptime(signal.timestamp, '%Y-%m-%d %H:%M:%S')
        weekday = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][dt.weekday()]
        
        print(f"\n   {i:2d}. {dt.strftime('%d.%m.%Y %H:%M')} ({weekday})")
        print(f"       💪 Сила: {signal.signal_strength:.1f}%")
        print(f"       💰 Цена: {signal.price} ₽ (EMA20: {signal.ema20} ₽)")
        print(f"       📈 ADX: {signal.adx:.1f}, +DI: {signal.plus_di:.1f}, -DI: {signal.minus_di:.1f}")
        print(f"       📊 Превышение EMA: +{signal.price_vs_ema_pct:.2f}%, DI разность: {signal.di_diff:.1f}")
        print(f"       📦 Объем: {signal.volume:,}")
    
    # Сохранение в JSON
    output_data = {
        'summary': analysis,
        'signals': [asdict(signal) for signal in signals],
        'search_conditions': {
            'price_above_ema20': True,
            'adx_above': 25,
            'plus_di_above_minus_di': True
        },
        'metadata': {
            'total_candles': results['total_candles'],
            'data_period': results['data_period'],
            'data_source': results.get('data_source', 'unknown')
        }
    }
    
    with open('sber_signals_backtest.json', 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 Результаты сохранены в sber_signals_backtest.json")
    print(f"{'='*80}")

async def main():
    """Основная функция"""
    print("🎯 БЭКТЕСТ ПОИСКА СИГНАЛОВ SBER")
    print("Условия: цена > EMA20, ADX > 25, +DI > -DI")
    print("="*80)
    
    # Проверяем токен Tinkoff
    tinkoff_token = os.getenv('TINKOFF_TOKEN')
    use_real_data = bool(tinkoff_token and TINKOFF_AVAILABLE)
    
    if use_real_data:
        print("📡 Будем использовать РЕАЛЬНЫЕ данные через Tinkoff API")
    else:
        print("🔧 Будем использовать СИМУЛИРОВАННЫЕ данные")
        if not TINKOFF_AVAILABLE:
            print("   (tinkoff-investments не установлен)")
        if not tinkoff_token:
            print("   (TINKOFF_TOKEN не найден в переменных окружения)")
    
    print("-" * 80)
    
    # Проверяем переменные окружения для Railway
    port = os.getenv('PORT', '8000')
    railway_env = os.getenv('RAILWAY_ENVIRONMENT')
    
    if railway_env:
        print(f"🚂 Запуск на Railway в окружении: {railway_env}")
        print(f"🔌 Порт: {port}")
    
    try:
        # Создаем движок бэктеста
        engine = BacktestEngine("SBER", use_real_data=use_real_data)
        
        # Запускаем бэктест на 90 дней
        print("\n🔄 Запуск анализа за 90 дней...")
        results = await engine.run_backtest(days=90)
        
        # Выводим результаты
        if results:
            print_results(results)
            
            # Краткие выводы
            analysis = results['analysis']
            if analysis.get('total_signals', 0) > 0:
                print(f"\n💡 КРАТКИЕ ВЫВОДЫ:")
                
                strong_pct = len([s for s in results['signals'] if s.signal_strength >= 80]) / len(results['signals']) * 100
                avg_adx = analysis['adx_stats']['average']
                avg_di_diff = analysis['di_dominance']['average']
                signals_per_day = analysis['signals_per_day']
                
                print(f"   📈 Сигналы появляются {signals_per_day:.1f} раз в день")
                print(f"   🔥 {strong_pct:.1f}% сигналов имеют силу ≥80%")
                print(f"   📊 Средний ADX: {avg_adx:.1f} (тренд {'сильный' if avg_adx > 35 else 'умеренный'})")
                print(f"   🎯 Средняя разность DI: {avg_di_diff:.1f} (доминирование {'сильное' if avg_di_diff > 15 else 'умеренное'})")
                
                # Лучшее время для торговли
                time_dist = analysis['time_distribution']
                if time_dist:
                    best_hour = max(time_dist.items(), key=lambda x: x[1])
                    print(f"   ⏰ Больше всего сигналов в {best_hour[0]:02d}:00 ({best_hour[1]} сигналов)")
                
                # Рекомендации
                print(f"\n🎯 РЕКОМЕНДАЦИИ:")
                if strong_pct >= 30:
                    print(f"   ✅ Качество сигналов хорошее - много сильных сигналов")
                else:
                    print(f"   ⚠️ Рассмотрите дополнительные фильтры для улучшения качества")
                
                if avg_adx >= 35:
                    print(f"   ✅ ADX показывает сильные тренды")
                else:
                    print(f"   ⚠️ ADX умеренный - возможны ложные сигналы в боковике")
                
                if signals_per_day >= 3:
                    print(f"   ⚠️ Много сигналов в день - рассмотрите дополнительную фильтрацию")
                elif signals_per_day >= 1:
                    print(f"   ✅ Оптимальная частота сигналов")
                else:
                    print(f"   ⚠️ Мало сигналов - возможно, стоит смягчить условия")
            
            else:
                print(f"\n❌ Сигналы не найдены!")
                print(f"   Попробуйте изменить параметры:")
                print(f"   • Уменьшить ADX с 25 до 20-23")
                print(f"   • Добавить объемный фильтр")
                print(f"   • Изменить период анализа")
        
        else:
            print("❌ Не удалось получить результаты бэктеста")
        
        print(f"\n✅ Анализ завершен!")
        
        # Для Railway - простой веб-сервер
        if railway_env:
            await serve_web_results(port, results)
    
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        print(f"❌ Ошибка выполнения: {e}")

async def serve_web_results(port: str, results: Dict):
    """Простой веб-сервер для Railway"""
    print(f"\n🌐 Запуск веб-сервера на порту {port}...")
    
    import http.server
    import socketserver
    from urllib.parse import parse_qs
    
    class CustomHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/':
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                
                if results and results.get('analysis'):
                    analysis = results['analysis']
                    signals_count = analysis.get('total_signals', 0)
                    avg_strength = analysis.get('signal_strength', {}).get('average', 0)
                    signals_per_day = analysis.get('signals_per_day', 0)
                    data_source = results.get('data_source', 'unknown')
                    
                    # Топ-3 сигнала для отображения
                    top_signals = sorted(results['signals'], key=lambda x: x.signal_strength, reverse=True)[:3]
                    
                    signals_html = ""
                    for i, signal in enumerate(top_signals, 1):
                        signals_html += f"""
                        <div class="signal">
                            <h4>#{i} Сигнал - Сила: {signal.signal_strength}%</h4>
                            <p><strong>Время:</strong> {signal.timestamp}</p>
                            <p><strong>Цена:</strong> {signal.price} ₽ (EMA20: {signal.ema20} ₽)</p>
                            <p><strong>ADX:</strong> {signal.adx} | <strong>+DI:</strong> {signal.plus_di} | <strong>-DI:</strong> {signal.minus_di}</p>
                            <p><strong>Превышение EMA:</strong> +{signal.price_vs_ema_pct}%</p>
                        </div>
                        """
                    
                else:
                    signals_count = 0
                    avg_strength = 0
                    signals_per_day = 0
                    data_source = 'none'
                    signals_html = "<p>Данные не найдены</p>"
                
                html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>SBER Signals Backtest Results</title>
                    <meta charset="utf-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <style>
                        body {{ 
                            font-family: 'Segoe UI', Arial, sans-serif; 
                            margin: 0; 
                            padding: 20px; 
                            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                            color: #333;
                            min-height: 100vh;
                        }}
                        .container {{
                            max-width: 1000px;
                            margin: 0 auto;
                            background: white;
                            border-radius: 15px;
                            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
                            padding: 30px;
                        }}
                        h1 {{ 
                            color: #2c3e50; 
                            text-align: center;
                            margin-bottom: 10px;
                            font-size: 2.5em;
                        }}
                        .subtitle {{
                            text-align: center;
                            color: #7f8c8d;
                            margin-bottom: 30px;
                            font-size: 1.1em;
                        }}
                        .stats {{ 
                            display: grid;
                            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                            gap: 20px;
                            margin-bottom: 30px;
                        }}
                        .stat-card {{
                            background: linear-gradient(135deg, #74b9ff, #0984e3);
                            color: white;
                            padding: 20px;
                            border-radius: 10px;
                            text-align: center;
                            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                        }}
                        .stat-value {{
                            font-size: 2.5em;
                            font-weight: bold;
                            margin-bottom: 5px;
                        }}
                        .stat-label {{
                            font-size: 1em;
                            opacity: 0.9;
                        }}
                        .signals-section {{
                            margin-top: 30px;
                        }}
                        .signal {{ 
                            border: 2px solid #74b9ff;
                            margin: 15px 0; 
                            padding: 20px; 
                            border-radius: 10px;
                            background: #f8f9fa;
                            transition: transform 0.2s;
                        }}
                        .signal:hover {{
                            transform: translateY(-2px);
                            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                        }}
                        .signal h4 {{
                            color: #2c3e50;
                            margin: 0 0 15px 0;
                            font-size: 1.3em;
                        }}
                        .signal p {{
                            margin: 8px 0;
                            color: #555;
                        }}
                        .conditions {{
                            background: #e8f5e8;
                            padding: 20px;
                            border-radius: 10px;
                            margin: 20px 0;
                            border-left: 5px solid #27ae60;
                        }}
                        .footer {{
                            text-align: center;
                            margin-top: 30px;
                            padding-top: 20px;
                            border-top: 2px solid #eee;
                            color: #7f8c8d;
                        }}
                        .data-source {{
                            display: inline-block;
                            padding: 5px 15px;
                            background: {'#27ae60' if data_source == 'real' else '#f39c12'};
                            color: white;
                            border-radius: 20px;
                            font-size: 0.9em;
                            margin: 10px 5px;
                        }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>🎯 SBER Signals Backtest</h1>
                        <div class="subtitle">Поиск сигналов: цена > EMA20, ADX > 25, +DI > -DI</div>
                        
                        <div class="conditions">
                            <h3>📋 Условия поиска:</h3>
                            <ul>
                                <li><strong>Цена выше EMA20</strong> - восходящий тренд</li>
                                <li><strong>ADX > 25</strong> - достаточная сила тренда</li>  
                                <li><strong>+DI > -DI</strong> - доминирование покупателей</li>
                            </ul>
                        </div>
                        
                        <div class="stats">
                            <div class="stat-card">
                                <div class="stat-value">{signals_count}</div>
                                <div class="stat-label">Найдено сигналов</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-value">{avg_strength:.1f}%</div>
                                <div class="stat-label">Средняя сила</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-value">{signals_per_day:.1f}</div>
                                <div class="stat-label">Сигналов в день</div>
                            </div>
                        </div>
                        
                        <div class="data-source">
                            📡 Источник: {{'Реальные данные Tinkoff' if data_source == 'real' else 'Симулированные данные'}}
                        </div>
                        
                        <div class="signals-section">
                            <h2>🏆 Топ сильнейших сигналов:</h2>
                            {signals_html}
                        </div>
                        
                        <div class="footer">
                            <p>Полные результаты доступны в логах приложения и файле sber_signals_backtest.json</p>
                            <p>Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')} UTC</p>
                        </div>
                    </div>
                </body>
                </html>
                """
                self.wfile.write(html.encode('utf-8'))
            
            elif self.path == '/json':
                # API endpoint для получения данных в JSON
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                
                if results:
                    json_data = json.dumps(results, default=str, ensure_ascii=False, indent=2)
                    self.wfile.write(json_data.encode('utf-8'))
                else:
                    self.wfile.write(b'{"error": "No results available"}')
            
            else:
                super().do_GET()
    
    # Запускаем сервер
    try:
        with socketserver.TCPServer(("", int(port)), CustomHandler) as httpd:
            print(f"🌐 Сервер запущен на http://0.0.0.0:{port}")
            print(f"📊 Веб-интерфейс: http://0.0.0.0:{port}")
            print(f"📁 JSON API: http://0.0.0.0:{port}/json")
            print("Нажмите Ctrl+C для остановки...")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Сервер остановлен")
    except Exception as e:
        print(f"❌ Ошибка веб-сервера: {e}")

if __name__ == "__main__":
    asyncio.run(main())
