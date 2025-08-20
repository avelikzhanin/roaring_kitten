#!/usr/bin/env python3
"""
Независимый бэктестинг торговой стратегии SBER для Railway
Не зависит от основного бота
ИСПРАВЛЕНЫ ВСЕ ОШИБКИ ФОРМАТИРОВАНИЯ
"""

import asyncio
import logging
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from dataclasses import dataclass

# Для работы с Tinkoff API
from tinkoff.invest import Client, RequestError, CandleInterval, HistoricCandle
from tinkoff.invest.utils import now

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

@dataclass
class BacktestSignal:
    timestamp: datetime
    signal_type: str
    price: float
    ema20: float
    adx: float
    plus_di: float
    minus_di: float
    volume: int
    volume_ratio: float

@dataclass
class Trade:
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    profit_pct: Optional[float] = None
    duration_hours: Optional[int] = None

class TinkoffDataProvider:
    """Упрощенный провайдер данных Tinkoff"""
    
    def __init__(self, token: str):
        self.token = token
        self.figi = "BBG004730N88"  # SBER
    
    async def get_candles(self, hours: int = 100) -> List[HistoricCandle]:
        """Получение свечных данных"""
        try:
            with Client(self.token) as client:
                to_time = now()
                from_time = to_time - timedelta(hours=hours)
                
                logger.info(f"📡 Запрос данных SBER с {from_time.strftime('%d.%m %H:%M')} по {to_time.strftime('%d.%m %H:%M')}")
                
                response = client.market_data.get_candles(
                    figi=self.figi,
                    from_=from_time,
                    to=to_time,
                    interval=CandleInterval.CANDLE_INTERVAL_HOUR
                )
                
                if response.candles:
                    logger.info(f"✅ Получено {len(response.candles)} свечей")
                    return response.candles
                else:
                    logger.warning("⚠️ Получен пустой ответ от API")
                    return []
                    
        except Exception as e:
            logger.error(f"❌ Ошибка получения данных: {e}")
            return []
    
    def candles_to_dataframe(self, candles: List[HistoricCandle]) -> pd.DataFrame:
        """Преобразование в DataFrame"""
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

class TechnicalIndicators:
    """Технические индикаторы"""
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """EMA"""
        if len(prices) < period:
            return [np.nan] * len(prices)
        
        series = pd.Series(prices)
        ema = series.ewm(span=period, adjust=False).mean()
        return ema.tolist()
    
    @staticmethod
    def wilder_smoothing(values: pd.Series, period: int) -> pd.Series:
        """Сглаживание Уайлдера"""
        result = pd.Series(index=values.index, dtype=float)
        first_avg = values.iloc[:period].mean()
        result.iloc[period-1] = first_avg
        
        for i in range(period, len(values)):
            result.iloc[i] = (result.iloc[i-1] * (period - 1) + values.iloc[i]) / period
        
        return result
    
    @staticmethod
    def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """ADX расчет"""
        if len(highs) < period * 2:
            return {
                'adx': [np.nan] * len(highs), 
                'plus_di': [np.nan] * len(highs), 
                'minus_di': [np.nan] * len(highs)
            }
        
        df = pd.DataFrame({
            'high': highs,
            'low': lows,
            'close': closes
        })
        
        # True Range
        df['prev_close'] = df['close'].shift(1)
        df['hl'] = df['high'] - df['low']
        df['hc'] = abs(df['high'] - df['prev_close'])
        df['lc'] = abs(df['low'] - df['prev_close'])
        df['tr'] = df[['hl', 'hc', 'lc']].max(axis=1)
        
        # Directional Movement
        df['high_diff'] = df['high'] - df['high'].shift(1)
        df['low_diff'] = df['low'].shift(1) - df['low']
        
        df['plus_dm'] = np.where(
            (df['high_diff'] > df['low_diff']) & (df['high_diff'] > 0),
            df['high_diff'],
            0
        )
        
        df['minus_dm'] = np.where(
            (df['low_diff'] > df['high_diff']) & (df['low_diff'] > 0),
            df['low_diff'],
            0
        )
        
        # Сглаживание
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

class StrategyBacktest:
    """Бэктестер стратегии"""
    
    def __init__(self, tinkoff_token: str):
        self.provider = TinkoffDataProvider(tinkoff_token)
        self.signals: List[BacktestSignal] = []
        self.trades: List[Trade] = []
        
    async def run_backtest(self, days: int = 60) -> Dict:
        """Запуск бэктеста"""
        logger.info(f"🔄 Запуск бэктестинга за {days} дней...")
        
        try:
            # Получаем данные
            hours_needed = days * 24 + 200
            candles = await self.provider.get_candles(hours=hours_needed)
            
            if len(candles) < 100:
                raise Exception("Недостаточно данных")
                
            df = self.provider.candles_to_dataframe(candles)
            
            if df.empty:
                raise Exception("Пустые данные")
            
            # Анализируем
            await self._analyze_data(df, days)
            self._generate_trades()
            stats = self._calculate_statistics(days)
            
            return stats
            
        except Exception as e:
            logger.error(f"Ошибка бэктестинга: {e}")
            return {}
    
    async def _analyze_data(self, df: pd.DataFrame, test_days: int):
        """Анализ данных"""
        logger.info("🔍 Анализ данных и поиск сигналов...")
        
        # Фильтр по времени
        test_start = datetime.now(timezone.utc) - timedelta(days=test_days)
        
        # Расчет индикаторов
        closes = df['close'].tolist()
        highs = df['high'].tolist()
        lows = df['low'].tolist()
        
        logger.info("📊 Расчет индикаторов...")
        ema20 = TechnicalIndicators.calculate_ema(closes, 20)
        adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
        
        df['avg_volume_20'] = df['volume'].rolling(window=20, min_periods=1).mean()
        df['ema20'] = ema20
        df['adx'] = adx_data['adx']
        df['plus_di'] = adx_data['plus_di']
        df['minus_di'] = adx_data['minus_di']
        
        # Тестовые данные
        df_test = df[df['timestamp'] >= test_start].copy()
        logger.info(f"📈 Тестовый период: {len(df_test)} свечей")
        
        # Поиск сигналов
        current_signal_active = False
        buy_signals = 0
        
        for i in range(len(df_test)):
            row = df_test.iloc[i]
            
            # Проверяем на NaN
            if pd.isna(row['adx']) or pd.isna(row['ema20']) or pd.isna(row['plus_di']) or pd.isna(row['minus_di']):
                continue
            
            # Условия стратегии
            conditions = [
                row['close'] > row['ema20'],                    # Цена > EMA20
                row['adx'] > 23,                               # ADX > 23
                row['plus_di'] > row['minus_di'],              # +DI > -DI
                row['plus_di'] - row['minus_di'] > 5,          # Разница > 5
                row['volume'] > row['avg_volume_20'] * 1.47    # Объем > 1.47
            ]
            
            conditions_met = all(conditions)
            
            if conditions_met and not current_signal_active:
                # BUY сигнал
                signal = BacktestSignal(
                    timestamp=row['timestamp'],
                    signal_type='BUY',
                    price=row['close'],
                    ema20=row['ema20'],
                    adx=row['adx'],
                    plus_di=row['plus_di'],
                    minus_di=row['minus_di'],
                    volume=int(row['volume']),
                    volume_ratio=row['volume'] / row['avg_volume_20']
                )
                self.signals.append(signal)
                current_signal_active = True
                buy_signals += 1
                logger.info(f"📈 BUY #{buy_signals}: {row['timestamp'].strftime('%d.%m %H:%M')} = {row['close']:.2f}₽")
                
            elif not conditions_met and current_signal_active:
                # SELL сигнал
                signal = BacktestSignal(
                    timestamp=row['timestamp'],
                    signal_type='SELL',
                    price=row['close'],
                    ema20=row['ema20'],
                    adx=row['adx'],
                    plus_di=row['plus_di'],
                    minus_di=row['minus_di'],
                    volume=int(row['volume']),
                    volume_ratio=row['volume'] / row['avg_volume_20']
                )
                self.signals.append(signal)
                current_signal_active = False
                logger.info(f"📉 SELL: {row['timestamp'].strftime('%d.%m %H:%M')} = {row['close']:.2f}₽")
        
        logger.info(f"🎯 Всего сигналов: {len(self.signals)} (BUY: {buy_signals})")
    
    def _generate_trades(self):
        """Генерация сделок"""
        current_trade = None
        
        for signal in self.signals:
            if signal.signal_type == 'BUY' and current_trade is None:
                current_trade = Trade(
                    entry_time=signal.timestamp,
                    entry_price=signal.price
                )
                
            elif signal.signal_type == 'SELL' and current_trade is not None:
                current_trade.exit_time = signal.timestamp
                current_trade.exit_price = signal.price
                current_trade.duration_hours = int((signal.timestamp - current_trade.entry_time).total_seconds() / 3600)
                current_trade.profit_pct = ((signal.price - current_trade.entry_price) / current_trade.entry_price) * 100
                
                self.trades.append(current_trade)
                current_trade = None
        
        logger.info(f"💰 Создано сделок: {len(self.trades)}")
    
    def _calculate_statistics(self, days: int) -> Dict:
        """Статистика"""
        if not self.trades:
            return {
                'period_days': days,
                'total_signals': len(self.signals),
                'buy_signals': len([s for s in self.signals if s.signal_type == 'BUY']),
                'sell_signals': len([s for s in self.signals if s.signal_type == 'SELL']),
                'total_trades': 0,
                'win_rate': 0,
                'total_return': 0,
                'trades_detail': []
            }
        
        profits = [t.profit_pct for t in self.trades if t.profit_pct is not None]
        profitable = [p for p in profits if p > 0]
        
        total_return = sum(profits) if profits else 0
        annual_return = (total_return / days) * 365 if days > 0 else 0
        
        return {
            'period_days': days,
            'total_signals': len(self.signals),
            'buy_signals': len([s for s in self.signals if s.signal_type == 'BUY']),
            'sell_signals': len([s for s in self.signals if s.signal_type == 'SELL']),
            'total_trades': len(self.trades),
            'profitable_trades': len(profitable),
            'win_rate': len(profitable) / len(profits) * 100 if profits else 0,
            'total_return': total_return,
            'annual_return_estimate': annual_return,
            'avg_profit': sum(profits) / len(profits) if profits else 0,
            'max_profit': max(profits) if profits else 0,
            'max_loss': min(profits) if profits else 0,
            'avg_duration_hours': sum(t.duration_hours for t in self.trades if t.duration_hours) / len(self.trades) if self.trades else 0,
            'trades_detail': self.trades
        }
    
    def print_results(self, stats: Dict):
        """ИСПРАВЛЕННЫЙ вывод результатов"""
        print("\n" + "="*70)
        print(f"🎯 БЭКТЕСТИНГ SBER ЗА {stats['period_days']} ДНЕЙ")
        print("="*70)
        
        print(f"📊 СИГНАЛЫ:")
        print(f"   • Всего: {stats['total_signals']}")
        print(f"   • Покупки: {stats['buy_signals']}")
        print(f"   • Продажи: {stats['sell_signals']}")
        
        print(f"\n💼 СДЕЛКИ:")
        print(f"   • Количество: {stats['total_trades']}")
        print(f"   • Прибыльные: {stats['profitable_trades']}")
        print(f"   • Винрейт: {stats['win_rate']:.1f}%")
        
        print(f"\n💰 ДОХОДНОСТЬ:")
        print(f"   • Общая: {stats['total_return']:.2f}%")
        print(f"   • Средняя на сделку: {stats['avg_profit']:.2f}%")
        print(f"   • Макс прибыль: {stats['max_profit']:.2f}%")
        print(f"   • Макс убыток: {stats['max_loss']:.2f}%")
        print(f"   • Годовая (оценка): {stats['annual_return_estimate']:.1f}%")
        
        print(f"\n⏰ ВРЕМЯ:")
        print(f"   • Средняя длительность: {stats['avg_duration_hours']:.1f}ч")
        
        # ИСПРАВЛЕНО: Упрощен вывод сделок
        if stats['trades_detail']:
            print(f"\n📋 СДЕЛКИ:")
            for i, trade in enumerate(stats['trades_detail'][:10], 1):
                # Форматируем каждую часть отдельно
                entry_date = trade.entry_time.strftime('%d.%m %H:%M')
                entry_price_formatted = f"{trade.entry_price:.2f}"
                
                if trade.exit_time:
                    exit_date = trade.exit_time.strftime('%d.%m %H:%M')
                    exit_price_formatted = f"{trade.exit_price:.2f}"
                    profit_formatted = f"{trade.profit_pct:+.2f}%"
                    
                    print(f"   {i:2d}. {entry_date} → {exit_date} | {entry_price_formatted} → {exit_price_formatted} | {profit_formatted}")
                else:
                    print(f"   {i:2d}. {entry_date} → Открыта | {entry_price_formatted} → --- | ---")
        
        print("="*70)

async def main():
    """Главная функция"""
    print("🚀 SBER Trading Bot - Независимый бэктестинг")
    print("-" * 60)
    
    # Проверяем токен
    TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
    
    if not TINKOFF_TOKEN:
        logger.error("❌ Переменная TINKOFF_TOKEN не найдена!")
        logger.error("🔧 Добавьте в Railway: Settings → Variables → TINKOFF_TOKEN")
        sys.exit(1)
    
    logger.info("✅ Токен найден, запускаем бэктестинг...")
    
    try:
        backtest = StrategyBacktest(TINKOFF_TOKEN)
        
        # Тестируем разные периоды
        for days in [30, 60, 90]:
            logger.info(f"🔄 Анализ за {days} дней...")
            
            stats = await backtest.run_backtest(days=days)
            
            if stats:
                backtest.print_results(stats)
                
                # Интерпретация
                print(f"\n💡 ОЦЕНКА за {days} дней:")
                if stats['total_trades'] > 0:
                    if stats['win_rate'] >= 60:
                        print("   ✅ Отличная стратегия!")
                    elif stats['win_rate'] >= 40:
                        print("   ⚠️ Средняя стратегия")
                    else:
                        print("   ❌ Слабая стратегия")
                        
                    if stats['total_return'] > 0:
                        print(f"   💰 Прибыльная: +{stats['total_return']:.2f}%")
                    else:
                        print(f"   📉 Убыточная: {stats['total_return']:.2f}%")
                else:
                    print("   ℹ️ Сигналов не было")
            else:
                logger.error(f"❌ Ошибка анализа за {days} дней")
            
            # Очистка для следующего периода
            backtest.signals.clear()
            backtest.trades.clear()
            print("-" * 60)
        
        logger.info("✅ Бэктестинг завершен!")
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
