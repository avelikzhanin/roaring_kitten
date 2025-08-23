#!/usr/bin/env python3
"""
Railway запуск многотаймфреймового анализа SBER
Возврат к основам - простая и эффективная стратегия
ИСПРАВЛЕНЫ ТОЛЬКО ЛИМИТЫ API
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

print("Starting Multi-Timeframe Analysis Container")
print("🎯 SBER MULTI-TIMEFRAME STRATEGY ANALYZER")
print("=" * 60)
print("✅ Простая стратегия без переоптимизации")
print("🎯 Многотаймфреймовый анализ для точных входов")  
print("🔧 ИСПРАВЛЕНЫ API ЛИМИТЫ для коротких ТФ")
print("⏱️ Анализ займет 3-4 минуты...")
print("=" * 60)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class TimeFrame(Enum):
    """Таймфреймы для анализа"""
    HOUR_1 = "1h"
    MIN_30 = "30m" 
    MIN_15 = "15m"
    MIN_5 = "5m"

@dataclass
class SignalConditions:
    """Базовые условия стратегии"""
    adx_threshold: float = 23.0
    price_above_ema: bool = True
    di_plus_above_di_minus: bool = True
    ema_period: int = 20

@dataclass
class TimeFrameSignal:
    """Сигнал на таймфрейме"""
    timeframe: TimeFrame
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

@dataclass
class MultiTimeFrameEntry:
    """Точка входа с подтверждениями"""
    main_signal: TimeFrameSignal
    confirmation_signals: List[TimeFrameSignal]
    entry_time: datetime
    entry_price: float
    confidence_score: float
    
    def get_confirmation_count(self) -> int:
        return len([s for s in self.confirmation_signals if s.is_valid()])

class DataProvider:
    """Провайдер данных Tinkoff - ИСПРАВЛЕНЫ ЛИМИТЫ API"""
    
    def __init__(self, token: str):
        self.token = token
        self.figi = "BBG004730N88"  # SBER
        
    def get_interval_for_timeframe(self, timeframe: TimeFrame) -> CandleInterval:
        mapping = {
            TimeFrame.HOUR_1: CandleInterval.CANDLE_INTERVAL_HOUR,
            TimeFrame.MIN_30: CandleInterval.CANDLE_INTERVAL_30_MIN,
            TimeFrame.MIN_15: CandleInterval.CANDLE_INTERVAL_15_MIN,
            TimeFrame.MIN_5: CandleInterval.CANDLE_INTERVAL_5_MIN
        }
        return mapping[timeframe]
    
    async def get_candles(self, timeframe: TimeFrame, days: int = 21) -> List[HistoricCandle]:
        """Получение данных - ИСПРАВЛЕНЫ ЛИМИТЫ"""
        try:
            with Client(self.token) as client:
                to_time = now()
                
                # ИСПРАВЛЕНИЕ: Правильные лимиты для API
                if timeframe == TimeFrame.MIN_5:
                    days = min(days, 1)  # 5м - максимум 1 день
                elif timeframe == TimeFrame.MIN_15:
                    days = min(days, 3)  # 15м - максимум 3 дня  
                elif timeframe == TimeFrame.MIN_30:
                    days = min(days, 7)  # 30м - максимум 7 дней
                # 1h остается 21 день
                
                from_time = to_time - timedelta(days=days)
                interval = self.get_interval_for_timeframe(timeframe)
                
                logger.info(f"📡 Загрузка {timeframe.value}: {days} дней ({from_time.strftime('%d.%m %H:%M')} - {to_time.strftime('%d.%m %H:%M')})")
                
                response = client.market_data.get_candles(
                    figi=self.figi,
                    from_=from_time,
                    to=to_time,
                    interval=interval
                )
                
                if response.candles:
                    logger.info(f"✅ {timeframe.value}: получено {len(response.candles)} свечей")
                    return response.candles
                else:
                    logger.warning(f"⚠️ {timeframe.value}: пустой ответ")
                    return []
                    
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки {timeframe.value}: {e}")
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
    """Технические индикаторы - БЕЗ ИЗМЕНЕНИЙ"""
    
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
    """Анализатор сигналов - БЕЗ ИЗМЕНЕНИЙ"""
    
    def __init__(self, conditions: SignalConditions = None):
        self.conditions = conditions or SignalConditions()
    
    def analyze_timeframe(self, df: pd.DataFrame, timeframe: TimeFrame) -> List[TimeFrameSignal]:
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
                
                # Расчет силы сигнала
                signal_strength = 0
                if conditions_met['adx_above_threshold']:
                    adx_excess = (current_adx - self.conditions.adx_threshold) / 20
                    signal_strength += min(adx_excess * 40, 40)
                
                if conditions_met['price_above_ema']:
                    ema_distance = ((price - current_ema) / current_ema) * 100
                    signal_strength += min(abs(ema_distance) * 15, 30)
                
                if conditions_met['di_plus_above_minus']:
                    di_diff = plus_di - minus_di
                    signal_strength += min(di_diff * 2, 30)
                
                signal = TimeFrameSignal(
                    timeframe=timeframe,
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

class MultiTimeFrameAnalyzer:
    """Главный анализатор - ИСПРАВЛЕНА ТОЛЬКО ЗАГРУЗКА ДАННЫХ"""
    
    def __init__(self, token: str):
        self.data_provider = DataProvider(token)
        self.signal_analyzer = SignalAnalyzer()
        
    async def run_analysis(self, days: int = 21) -> None:
        """Запуск полного анализа"""
        logger.info(f"🚀 Запускаем многотаймфреймовый анализ за {days} дней...")
        
        timeframes = [TimeFrame.HOUR_1, TimeFrame.MIN_30, TimeFrame.MIN_15, TimeFrame.MIN_5]
        all_signals = {}
        
        # Загружаем данные по всем таймфреймам
        for timeframe in timeframes:
            try:
                candles = await self.data_provider.get_candles(timeframe, days)
                if not candles:
                    all_signals[timeframe] = []
                    continue
                
                df = self.data_provider.candles_to_dataframe(candles)
                if df.empty:
                    all_signals[timeframe] = []
                    continue
                
                signals = self.signal_analyzer.analyze_timeframe(df, timeframe)
                all_signals[timeframe] = signals
                
                await asyncio.sleep(0.5)  # Небольшая пауза
                
            except Exception as e:
                logger.error(f"❌ Ошибка {timeframe.value}: {e}")
                all_signals[timeframe] = []
        
        # Ищем точки входа
        entries = self.find_multi_timeframe_entries(all_signals)
        
        # Выводим результаты
        self.print_results(all_signals, entries)
        
        return entries
    
    def find_multi_timeframe_entries(self, all_signals: Dict[TimeFrame, List[TimeFrameSignal]]) -> List[MultiTimeFrameEntry]:
        entries = []
        main_signals = all_signals.get(TimeFrame.HOUR_1, [])
        
        logger.info(f"🎯 Анализ {len(main_signals)} основных сигналов на 1h...")
        
        for main_signal in main_signals:
            confirmation_window_start = main_signal.timestamp
            confirmation_window_end = main_signal.timestamp + timedelta(hours=1)
            
            confirmations = []
            
            for timeframe in [TimeFrame.MIN_30, TimeFrame.MIN_15, TimeFrame.MIN_5]:
                timeframe_signals = all_signals.get(timeframe, [])
                
                for signal in timeframe_signals:
                    if confirmation_window_start <= signal.timestamp <= confirmation_window_end:
                        confirmations.append(signal)
                        break
            
            confirmation_count = len([c for c in confirmations if c.is_valid()])
            base_confidence = main_signal.signal_strength
            confirmation_bonus = confirmation_count * 15
            confidence_score = min(base_confidence + confirmation_bonus, 100)
            
            if confirmations:
                entry = MultiTimeFrameEntry(
                    main_signal=main_signal,
                    confirmation_signals=confirmations,
                    entry_time=main_signal.timestamp,
                    entry_price=main_signal.price,
                    confidence_score=confidence_score
                )
                entries.append(entry)
        
        entries.sort(key=lambda x: x.confidence_score, reverse=True)
        logger.info(f"✅ Найдено {len(entries)} точек входа")
        return entries
    
    def print_results(self, all_signals: Dict[TimeFrame, List[TimeFrameSignal]], 
                     entries: List[MultiTimeFrameEntry]):
        """Вывод результатов - БЕЗ ИЗМЕНЕНИЙ"""
        
        print(f"\n{'='*90}")
        print("🎯 РЕЗУЛЬТАТЫ МНОГОТАЙМФРЕЙМОВОГО АНАЛИЗА SBER")
        print(f"{'='*90}")
        
        # Статистика по таймфреймам
        print("\n📊 СИГНАЛЫ ПО ТАЙМФРЕЙМАМ:")
        total_signals = 0
        for timeframe, signals in all_signals.items():
            valid = len([s for s in signals if s.is_valid()])
            avg_strength = np.mean([s.signal_strength for s in signals]) if signals else 0
            total_signals += valid
            
            print(f"   {timeframe.value:>6}: {valid:>3} валидных сигналов (средняя сила: {avg_strength:.1f}%)")
        
        print(f"\n📈 ОБЩАЯ СТАТИСТИКА:")
        print(f"   💎 Всего сигналов: {total_signals}")
        print(f"   🎯 Точек входа с подтверждениями: {len(entries)}")
        
        if not entries:
            print("\n❌ ТОЧКИ ВХОДА НЕ НАЙДЕНЫ")
            print("Возможные причины:")
            print("• Период неподходящий для стратегии")
            print("• Нужно снизить пороги или расширить окно")
            return
        
        # ТОП точек входа
        print(f"\n{'='*90}")
        print("🏆 ТОП-15 ЛУЧШИХ ТОЧЕК ВХОДА С ПАРАМЕТРАМИ")
        print(f"{'='*90}")
        print(f"{'#':<2} {'Дата/Время':<17} {'Цена':<8} {'Увер%':<5} {'Подт':<4} {'ADX':<6} {'DI+':<6} {'DI-':<6} {'EMA':<8}")
        print("-" * 90)
        
        for i, entry in enumerate(entries[:15], 1):
            main = entry.main_signal
            conf_count = entry.get_confirmation_count()
            timestamp_str = main.timestamp.strftime('%d.%m %H:%M')
            
            print(f"{i:<2} {timestamp_str:<17} {main.price:<8.2f} "
                  f"{entry.confidence_score:<5.0f} {conf_count:<4} "
                  f"{main.adx:<6.1f} {main.plus_di:<6.1f} {main.minus_di:<6.1f} {main.ema:<8.2f}")
        
        # Детальный анализ ТОП-5
        print(f"\n{'='*90}")
        print("🔍 ДЕТАЛЬНЫЙ АНАЛИЗ ТОП-5 ТОЧЕК ВХОДА")
        print(f"{'='*90}")
        
        for i, entry in enumerate(entries[:5], 1):
            main = entry.main_signal
            ema_distance = ((main.price - main.ema) / main.ema) * 100
            di_spread = main.plus_di - main.minus_di
            
            print(f"\n🏆 #{i} - УВЕРЕННОСТЬ: {entry.confidence_score:.1f}%")
            print(f"   📅 Время: {main.timestamp.strftime('%d.%m.%Y %H:%M')} (МСК)")
            print(f"   💰 Цена входа: {main.price:.2f} руб")
            print(f"   📊 Параметры сигнала:")
            print(f"       • ADX: {main.adx:.1f} (превышение порога на {main.adx-23:.1f})")
            print(f"       • DI+: {main.plus_di:.1f}, DI-: {main.minus_di:.1f} (спред: +{di_spread:.1f})")
            print(f"       • EMA20: {main.ema:.2f} руб (цена выше на {ema_distance:.2f}%)")
            print(f"       • Сила основного сигнала: {main.signal_strength:.1f}%")
            
            if entry.confirmation_signals:
                print(f"   ✅ Подтверждения ({len(entry.confirmation_signals)} ТФ):")
                for conf in entry.confirmation_signals:
                    time_diff = (conf.timestamp - main.timestamp).total_seconds() / 60
                    conf_ema_dist = ((conf.price - conf.ema) / conf.ema) * 100
                    print(f"       • {conf.timeframe.value}: +{time_diff:.0f}мин, ADX {conf.adx:.1f}, "
                          f"EMA+{conf_ema_dist:.1f}%, сила {conf.signal_strength:.0f}%")
            
            print(f"   🎯 Код для входа:")
            print(f"       if adx > {main.adx:.0f} and price > ema20 and di_plus > di_minus:")
            print(f"           enter_long({main.price:.2f})  # Уверенность {entry.confidence_score:.0f}%")

async def main():
    """Главная функция"""
    logger.info("✅ Токен найден, запускаем анализ...")
    
    TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
    
    if not TINKOFF_TOKEN:
        logger.error("❌ TINKOFF_TOKEN не найден")
        sys.exit(1)
    
    try:
        analyzer = MultiTimeFrameAnalyzer(TINKOFF_TOKEN)
        entries = await analyzer.run_analysis(days=21)
        
        logger.info("✅ Многотаймфреймовый анализ завершен успешно!")
        
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
