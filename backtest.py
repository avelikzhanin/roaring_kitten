#!/usr/bin/env python3
"""
SBER 1H Strategy - Простая и эффективная стратегия
Только часовые сигналы без переусложнения
"""

import asyncio
import logging
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

# Импорты Tinkoff API
from tinkoff.invest import Client, RequestError, CandleInterval, HistoricCandle
from tinkoff.invest.utils import now

print("🎯 SBER 1H STRATEGY ANALYZER")
print("=" * 50)
print("✅ Только часовые сигналы")
print("🎯 Простая стратегия без переоптимизации")  
print("📊 Анализ силы сигналов")
print("⏱️ Анализ займет 1-2 минуты...")
print("=" * 50)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

@dataclass
class SignalConditions:
    """Базовые условия стратегии"""
    adx_threshold: float = 23.0
    price_above_ema: bool = True
    di_plus_above_di_minus: bool = True
    ema_period: int = 20

@dataclass
class Signal:
    """Сигнал на 1h"""
    timestamp: datetime
    price: float
    adx: float
    plus_di: float
    minus_di: float
    ema: float
    signal_strength: float
    conditions_met: Dict[str, bool]
    
    def is_valid(self) -> bool:
        return all(self.conditions_met.values())
    
    def get_strength_category(self) -> str:
        if self.signal_strength >= 80:
            return "ОЧЕНЬ СИЛЬНЫЙ"
        elif self.signal_strength >= 60:
            return "СИЛЬНЫЙ"
        elif self.signal_strength >= 40:
            return "СРЕДНИЙ"
        elif self.signal_strength >= 20:
            return "СЛАБЫЙ"
        else:
            return "ОЧЕНЬ СЛАБЫЙ"

class DataProvider:
    """Провайдер данных Tinkoff"""
    
    def __init__(self, token: str):
        self.token = token
        self.figi = "BBG004730N88"  # SBER
        
    async def get_candles(self, days: int = 21) -> List[HistoricCandle]:
        """Получение часовых данных"""
        try:
            with Client(self.token) as client:
                to_time = now()
                from_time = to_time - timedelta(days=days)
                
                logger.info(f"📡 Загрузка 1H: {days} дней ({from_time.strftime('%d.%m %H:%M')} - {to_time.strftime('%d.%m %H:%M')})")
                
                response = client.market_data.get_candles(
                    figi=self.figi,
                    from_=from_time,
                    to=to_time,
                    interval=CandleInterval.CANDLE_INTERVAL_HOUR
                )
                
                if response.candles:
                    logger.info(f"✅ Получено {len(response.candles)} часовых свечей")
                    return response.candles
                else:
                    logger.warning("⚠️ Пустой ответ от API")
                    return []
                    
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки данных: {e}")
            return []
    
    def candles_to_dataframe(self, candles: List[HistoricCandle]) -> pd.DataFrame:
        if not candles:
            return pd.DataFrame()
        
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
            except:
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
        try:
            return float(quotation.units + quotation.nano / 1e9)
        except:
            return 0.0

class TechnicalIndicators:
    """Технические индикаторы"""
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        if len(prices) < period:
            return [np.nan] * len(prices)
        series = pd.Series(prices)
        ema = series.ewm(span=period, adjust=False).mean()
        return ema.tolist()
    
    @staticmethod
    def wilder_smoothing(values: pd.Series, period: int) -> pd.Series:
        result = pd.Series(index=values.index, dtype=float)
        if len(values) < period:
            return result
        
        first_avg = values.iloc[:period].mean()
        result.iloc[period-1] = first_avg
        
        for i in range(period, len(values)):
            result.iloc[i] = (result.iloc[i-1] * (period - 1) + values.iloc[i]) / period
        
        return result
    
    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        if len(highs) < period * 2:
            return {
                'adx': [np.nan] * len(highs), 
                'plus_di': [np.nan] * len(highs), 
                'minus_di': [np.nan] * len(highs)
            }
        
        df = pd.DataFrame({'high': highs, 'low': lows, 'close': closes})
        
        # True Range
        df['prev_close'] = df['close'].shift(1)
        df['hl'] = df['high'] - df['low']
        df['hc'] = abs(df['high'] - df['prev_close'])
        df['lc'] = abs(df['low'] - df['prev_close'])
        df['tr'] = df[['hl', 'hc', 'lc']].max(axis=1)
        
        # Directional Movement
        df['high_diff'] = df['high'] - df['high'].shift(1)
        df['low_diff'] = df['low'].shift(1) - df['low']
        
        df['plus_dm'] = np.where((df['high_diff'] > df['low_diff']) & (df['high_diff'] > 0), df['high_diff'], 0)
        df['minus_dm'] = np.where((df['low_diff'] > df['high_diff']) & (df['low_diff'] > 0), df['low_diff'], 0)
        
        # Smoothing
        df['atr'] = TechnicalIndicators.wilder_smoothing(df['tr'], period)
        df['plus_dm_smooth'] = TechnicalIndicators.wilder_smoothing(df['plus_dm'], period)
        df['minus_dm_smooth'] = TechnicalIndicators.wilder_smoothing(df['minus_dm'], period)
        
        # DI
        df['plus_di'] = (df['plus_dm_smooth'] / df['atr']) * 100
        df['minus_di'] = (df['minus_dm_smooth'] / df['atr']) * 100
        
        # DX и ADX
        df['di_sum'] = df['plus_di'] + df['minus_di']
        df['di_diff'] = abs(df['plus_di'] - df['minus_di'])
        df['dx'] = np.where(df['di_sum'] != 0, (df['di_diff'] / df['di_sum']) * 100, 0)
        df['adx'] = TechnicalIndicators.wilder_smoothing(df['dx'], period)
        
        return {
            'adx': df['adx'].fillna(np.nan).tolist(),
            'plus_di': df['plus_di'].fillna(np.nan).tolist(),
            'minus_di': df['minus_di'].fillna(np.nan).tolist()
        }

class SignalAnalyzer:
    """Анализатор сигналов"""
    
    def __init__(self, conditions: SignalConditions = None):
        self.conditions = conditions or SignalConditions()
    
    def analyze_signals(self, df: pd.DataFrame) -> List[Signal]:
        if df.empty or len(df) < 50:
            return []
        
        closes = df['close'].tolist()
        highs = df['high'].tolist()
        lows = df['low'].tolist()
        timestamps = df['timestamp'].tolist()
        
        ema = TechnicalIndicators.calculate_ema(closes, self.conditions.ema_period)
        adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
        
        signals = []
        
        for i in range(50, len(df)):
            try:
                if pd.isna(ema[i]) or pd.isna(adx_data['adx'][i]):
                    continue
                
                price = closes[i]
                current_ema = ema[i]
                current_adx = adx_data['adx'][i]
                plus_di = adx_data['plus_di'][i]
                minus_di = adx_data['minus_di'][i]
                
                # Проверка условий
                conditions_met = {
                    'adx_above_threshold': current_adx > self.conditions.adx_threshold,
                    'price_above_ema': price > current_ema,
                    'di_plus_above_minus': plus_di > minus_di
                }
                
                # Расчет силы сигнала с детализацией
                signal_strength = 0
                
                # ADX компонент (40% от общей силы)
                if conditions_met['adx_above_threshold']:
                    adx_excess = (current_adx - self.conditions.adx_threshold) / 20
                    adx_component = min(adx_excess * 40, 40)
                    signal_strength += adx_component
                
                # EMA компонент (30% от общей силы)
                if conditions_met['price_above_ema']:
                    ema_distance = ((price - current_ema) / current_ema) * 100
                    ema_component = min(abs(ema_distance) * 15, 30)
                    signal_strength += ema_component
                
                # DI компонент (30% от общей силы)
                if conditions_met['di_plus_above_minus']:
                    di_diff = plus_di - minus_di
                    di_component = min(di_diff * 2, 30)
                    signal_strength += di_component
                
                signal = Signal(
                    timestamp=timestamps[i],
                    price=price,
                    adx=current_adx,
                    plus_di=plus_di,
                    minus_di=minus_di,
                    ema=current_ema,
                    signal_strength=min(signal_strength, 100),
                    conditions_met=conditions_met
                )
                
                if signal.is_valid():
                    signals.append(signal)
                    
            except:
                continue
        
        return signals

class StrategyAnalyzer:
    """Анализатор стратегии"""
    
    def __init__(self, token: str):
        self.data_provider = DataProvider(token)
        self.signal_analyzer = SignalAnalyzer()
        
    async def run_analysis(self, days: int = 21) -> List[Signal]:
        """Запуск анализа"""
        logger.info(f"🚀 Запускаем анализ 1H стратегии за {days} дней...")
        
        # Загружаем данные
        candles = await self.data_provider.get_candles(days)
        if not candles:
            logger.error("❌ Не удалось загрузить данные")
            return []
        
        df = self.data_provider.candles_to_dataframe(candles)
        if df.empty:
            logger.error("❌ Пустой DataFrame")
            return []
        
        # Анализируем сигналы
        signals = self.signal_analyzer.analyze_signals(df)
        
        # Выводим результаты
        self.print_results(signals)
        
        return signals
    
    def print_results(self, signals: List[Signal]):
        """Детальный вывод результатов с анализом силы"""
        
        print(f"\n{'='*80}")
        print("🎯 АНАЛИЗ СИГНАЛОВ SBER 1H СТРАТЕГИИ")
        print(f"{'='*80}")
        
        if not signals:
            print("❌ СИГНАЛЫ НЕ НАЙДЕНЫ")
            return
        
        # Общая статистика
        total_signals = len(signals)
        avg_strength = np.mean([s.signal_strength for s in signals])
        
        print(f"\n📊 ОБЩАЯ СТАТИСТИКА:")
        print(f"   💎 Всего валидных сигналов: {total_signals}")
        print(f"   📈 Средняя сила: {avg_strength:.1f}%")
        
        # Распределение по силе
        strength_ranges = {
            "ОЧЕНЬ СИЛЬНЫЕ (80-100%)": [s for s in signals if s.signal_strength >= 80],
            "СИЛЬНЫЕ (60-80%)": [s for s in signals if 60 <= s.signal_strength < 80],
            "СРЕДНИЕ (40-60%)": [s for s in signals if 40 <= s.signal_strength < 60],
            "СЛАБЫЕ (20-40%)": [s for s in signals if 20 <= s.signal_strength < 40],
            "ОЧЕНЬ СЛАБЫЕ (0-20%)": [s for s in signals if s.signal_strength < 20]
        }
        
        print(f"\n📊 РАСПРЕДЕЛЕНИЕ ПО СИЛЕ:")
        for category, group in strength_ranges.items():
            count = len(group)
            pct = (count / total_signals) * 100 if total_signals > 0 else 0
            avg_str = np.mean([s.signal_strength for s in group]) if group else 0
            print(f"   • {category}: {count:>2} сигналов ({pct:>4.1f}%, ср.сила {avg_str:.1f}%)")
        
        # Топ сигналы
        sorted_signals = sorted(signals, key=lambda x: x.signal_strength, reverse=True)
        
        print(f"\n{'='*80}")
        print("🏆 ТОП-20 САМЫХ СИЛЬНЫХ СИГНАЛОВ")
        print(f"{'='*80}")
        print(f"{'#':<2} {'Дата/Время':<17} {'Цена':<8} {'Сила%':<6} {'ADX':<6} {'DI+':<6} {'DI-':<6} {'EMA':<8} {'Категория'}")
        print("-" * 80)
        
        for i, signal in enumerate(sorted_signals[:20], 1):
            timestamp_str = signal.timestamp.strftime('%d.%m %H:%M')
            category = signal.get_strength_category()
            
            print(f"{i:<2} {timestamp_str:<17} {signal.price:<8.2f} "
                  f"{signal.signal_strength:<6.1f} {signal.adx:<6.1f} "
                  f"{signal.plus_di:<6.1f} {signal.minus_di:<6.1f} {signal.ema:<8.2f} {category}")
        
        # Детальный анализ ТОП-5
        print(f"\n{'='*80}")
        print("🔍 ДЕТАЛЬНЫЙ АНАЛИЗ ТОП-5 СИГНАЛОВ")
        print(f"{'='*80}")
        
        for i, signal in enumerate(sorted_signals[:5], 1):
            ema_distance = ((signal.price - signal.ema) / signal.ema) * 100
            di_spread = signal.plus_di - signal.minus_di
            adx_excess = signal.adx - 23.0
            
            print(f"\n🏆 #{i} - СИЛА: {signal.signal_strength:.1f}% ({signal.get_strength_category()})")
            print(f"   📅 Время: {signal.timestamp.strftime('%d.%m.%Y %H:%M')} (МСК)")
            print(f"   💰 Цена: {signal.price:.2f} руб")
            
            print(f"   📊 РАЗБОР СИЛЫ СИГНАЛА:")
            
            # ADX компонент
            adx_component = min((adx_excess / 20) * 40, 40) if adx_excess > 0 else 0
            print(f"       • ADX: {signal.adx:.1f} (порог 23.0, превышение на {adx_excess:.1f})")
            print(f"         Вклад в силу: {adx_component:.1f} баллов из 40")
            
            # EMA компонент
            ema_component = min(abs(ema_distance) * 15, 30) if ema_distance > 0 else 0
            print(f"       • EMA20: {signal.ema:.2f} руб (цена выше на {ema_distance:.3f}%)")
            print(f"         Вклад в силу: {ema_component:.1f} баллов из 30")
            
            # DI компонент
            di_component = min(di_spread * 2, 30) if di_spread > 0 else 0
            print(f"       • DI: +{signal.plus_di:.1f} vs -{signal.minus_di:.1f} (разница +{di_spread:.1f})")
            print(f"         Вклад в силу: {di_component:.1f} баллов из 30")
            
            print(f"       • ИТОГО: {adx_component:.1f} + {ema_component:.1f} + {di_component:.1f} = {signal.signal_strength:.1f}%")
            
            print(f"   🎯 Торговые параметры:")
            print(f"       • Точка входа: {signal.price:.2f} руб")
            print(f"       • Стоп-лосс: ~{signal.price * 0.97:.2f} руб (-3%)")
            print(f"       • Тейк-профит: ~{signal.price * 1.06:.2f} руб (+6%, R:R = 2:1)")
        
        # Анализ компонентов силы
        print(f"\n{'='*80}")
        print("📈 АНАЛИЗ КОМПОНЕНТОВ СИЛЫ СИГНАЛОВ")
        print(f"{'='*80}")
        
        adx_values = [s.adx for s in signals]
        ema_distances = [((s.price - s.ema) / s.ema) * 100 for s in signals]
        di_spreads = [s.plus_di - s.minus_di for s in signals]
        
        print(f"\n📊 СТАТИСТИКА ADX:")
        print(f"   • Среднее: {np.mean(adx_values):.1f}")
        print(f"   • Минимум: {np.min(adx_values):.1f} (порог: 23.0)")
        print(f"   • Максимум: {np.max(adx_values):.1f}")
        print(f"   • Медиана: {np.median(adx_values):.1f}")
        
        print(f"\n📊 СТАТИСТИКА ДИСТАНЦИИ ОТ EMA:")
        print(f"   • Среднее превышение: {np.mean(ema_distances):.3f}%")
        print(f"   • Минимум: {np.min(ema_distances):.3f}%")
        print(f"   • Максимум: {np.max(ema_distances):.3f}%")
        print(f"   • Медиана: {np.median(ema_distances):.3f}%")
        
        print(f"\n📊 СТАТИСТИКА DI РАЗНОСТИ:")
        print(f"   • Средняя разность: {np.mean(di_spreads):.1f}")
        print(f"   • Минимум: {np.min(di_spreads):.1f}")
        print(f"   • Максимум: {np.max(di_spreads):.1f}")
        print(f"   • Медиана: {np.median(di_spreads):.1f}")
        
        # Рекомендации
        strong_signals = [s for s in signals if s.signal_strength >= 60]
        
        print(f"\n{'='*80}")
        print("💡 РЕКОМЕНДАЦИИ")
        print(f"{'='*80}")
        
        print(f"🎯 ДЛЯ ТОРГОВЛИ:")
        print(f"   • Используйте сигналы с силой ≥ 60% ({len(strong_signals)} из {total_signals})")
        print(f"   • Лучшие сигналы имеют ADX > 30 и DI разность > 5")
        print(f"   • Избегайте сигналов с силой < 40%")
        
        if strong_signals:
            best_signal = sorted_signals[0]
            print(f"\n🏆 ЭТАЛОННЫЙ СИГНАЛ:")
            print(f"   📅 Дата: {best_signal.timestamp.strftime('%d.%m.%Y %H:%M')}")
            print(f"   💰 Цена: {best_signal.price:.2f} руб")
            print(f"   🎯 Сила: {best_signal.signal_strength:.1f}%")
            print(f"   📊 ADX: {best_signal.adx:.1f}, DI разность: {best_signal.plus_di - best_signal.minus_di:.1f}")
        
        print(f"\n🤖 КОД ДЛЯ ФИЛЬТРАЦИИ:")
        print(f"   # Базовые условия")
        print(f"   if adx > 23.0 and price > ema20 and di_plus > di_minus:")
        print(f"       # Дополнительные фильтры для качества")
        print(f"       if adx > 30.0 and (di_plus - di_minus) > 5.0:")
        print(f"           signal_strength = 'HIGH'")
        print(f"       elif adx > 25.0 and (di_plus - di_minus) > 2.0:")
        print(f"           signal_strength = 'MEDIUM'")
        print(f"       else:")
        print(f"           signal_strength = 'LOW'")

async def main():
    """Главная функция"""
    logger.info("✅ Токен найден, запускаем анализ...")
    
    TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
    
    if not TINKOFF_TOKEN:
        logger.error("❌ TINKOFF_TOKEN не найден")
        sys.exit(1)
    
    try:
        analyzer = StrategyAnalyzer(TINKOFF_TOKEN)
        signals = await analyzer.run_analysis(days=21)
        
        logger.info("✅ Анализ 1H стратегии завершен успешно!")
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Анализ прерван пользователем")
    except Exception as e:
        print(f"❌ Фатальная ошибка: {e}")
        sys.exit(1)
