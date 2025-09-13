import asyncio
import logging
from datetime import datetime
from typing import Optional
import pandas as pd
from dataclasses import dataclass

from .indicators import TechnicalIndicators

logger = logging.getLogger(__name__)

@dataclass
class TradingSignal:
    """Структура торгового сигнала"""
    symbol: str
    timestamp: datetime
    price: float
    ema20: float
    adx: float
    plus_di: float
    minus_di: float

class SignalProcessor:
    """Обработчик торговых сигналов с подробной отладкой"""
    
    def __init__(self, tinkoff_provider, database, gpt_analyzer=None):
        self.tinkoff_provider = tinkoff_provider
        self.db = database
        self.gpt_analyzer = gpt_analyzer
    
    async def analyze_market(self, symbol: str) -> Optional[TradingSignal]:
        """Анализ рынка для конкретной акции с подробной отладкой"""
        try:
            logger.info(f"🔍 НАЧИНАЕМ АНАЛИЗ {symbol}")
            
            # Получаем информацию о тикере
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                logger.error(f"Тикер {symbol} не найден в БД")
                return None
            
            logger.info(f"📊 Тикер найден: {ticker_info['name']} (FIGI: {ticker_info['figi']})")
            
            # Получаем свечи
            candles = await self.tinkoff_provider.get_candles_for_ticker(
                ticker_info['figi'], hours=120
            )
            
            if len(candles) < 50:
                logger.warning(f"Недостаточно данных для {symbol}: {len(candles)} свечей")
                return None
            
            logger.info(f"📈 Получено {len(candles)} свечей для анализа")
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                logger.error(f"Пустой DataFrame для {symbol}")
                return None
            
            # Подробное логирование последних свечей
            logger.info(f"📊 ПОСЛЕДНИЕ 5 СВЕЧЕЙ {symbol}:")
            for i, (_, row) in enumerate(df.tail().iterrows()):
                logger.info(f"  {i+1}. {row['timestamp'].strftime('%H:%M %d.%m')} | "
                           f"O:{row['open']:.2f} H:{row['high']:.2f} L:{row['low']:.2f} C:{row['close']:.2f} V:{row['volume']}")
            
            # Рассчитываем индикаторы
            signal = self._calculate_indicators_with_debug(df, symbol)
            
            return signal
            
        except Exception as e:
            logger.error(f"Ошибка анализа рынка {symbol}: {e}")
            return None
    
    def _calculate_indicators_with_debug(self, df, symbol: str) -> Optional[TradingSignal]:
        """Расчет технических индикаторов с подробной отладкой"""
        try:
            logger.info(f"🧮 РАСЧЕТ ИНДИКАТОРОВ ДЛЯ {symbol}")
            
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            logger.info(f"📊 Данные для расчета:")
            logger.info(f"   Всего свечей: {len(closes)}")
            logger.info(f"   Последняя цена: {closes[-1]:.2f}")
            logger.info(f"   Диапазон цен: {min(closes):.2f} - {max(closes):.2f}")
            
            # Рассчитываем EMA20
            logger.info(f"📈 Расчет EMA20...")
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
            
            # Рассчитываем ADX (ИСПРАВЛЕННЫЙ)
            logger.info(f"📊 Расчет ADX через pandas-ta...")
            adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            
            # Текущие значения
            current_price = closes[-1]
            current_ema20 = ema20[-1]
            current_adx = adx_data['adx'][-1]
            current_plus_di = adx_data['plus_di'][-1]
            current_minus_di = adx_data['minus_di'][-1]
            
            # Проверяем на NaN
            if any(pd.isna(val) for val in [current_ema20, current_adx, current_plus_di, current_minus_di]):
                logger.warning(f"Индикаторы содержат NaN для {symbol}")
                logger.warning(f"EMA20: {current_ema20}, ADX: {current_adx}, +DI: {current_plus_di}, -DI: {current_minus_di}")
                return None
            
            # ПОДРОБНОЕ ЛОГИРОВАНИЕ РЕЗУЛЬТАТОВ
            logger.info(f"")
            logger.info(f"🎯 РЕЗУЛЬТАТЫ РАСЧЕТОВ {symbol}:")
            logger.info(f"   💰 Текущая цена: {current_price:.2f} ₽")
            logger.info(f"   📈 EMA20: {current_ema20:.2f} ₽")
            logger.info(f"   📊 ADX: {current_adx:.1f}")
            logger.info(f"   📈 +DI: {current_plus_di:.1f}")
            logger.info(f"   📉 -DI: {current_minus_di:.1f}")
            logger.info(f"   🔄 Разница DI: {current_plus_di - current_minus_di:.1f}")
            logger.info(f"")
            
            # Проверка условий сигнала
            condition_1 = current_price > current_ema20
            condition_2 = current_adx > 25
            condition_3 = current_plus_di > current_minus_di
            condition_4 = current_plus_di - current_minus_di > 1
            
            logger.info(f"🧐 ПРОВЕРКА УСЛОВИЙ СИГНАЛА {symbol}:")
            logger.info(f"   1. Цена > EMA20 ({current_price:.2f} > {current_ema20:.2f}): {'✅' if condition_1 else '❌'}")
            logger.info(f"   2. ADX > 25 ({current_adx:.1f} > 25): {'✅' if condition_2 else '❌'}")
            logger.info(f"   3. +DI > -DI ({current_plus_di:.1f} > {current_minus_di:.1f}): {'✅' if condition_3 else '❌'}")
            logger.info(f"   4. Разница DI > 1 ({current_plus_di - current_minus_di:.1f} > 1): {'✅' if condition_4 else '❌'}")
            
            conditions = [condition_1, condition_2, condition_3, condition_4]
            conditions_met = sum(conditions)
            
            logger.info(f"")
            logger.info(f"📊 ИТОГ: {conditions_met}/4 условия выполнены")
            
            if all(conditions):
                logger.info(f"🎉 ВСЕ УСЛОВИЯ ВЫПОЛНЕНЫ ДЛЯ {symbol} - ГЕНЕРИРУЕМ СИГНАЛ!")
                
                signal = TradingSignal(
                    symbol=symbol,
                    timestamp=df.iloc[-1]['timestamp'],
                    price=current_price,
                    ema20=current_ema20,
                    adx=current_adx,
                    plus_di=current_plus_di,
                    minus_di=current_minus_di
                )
                
                logger.info(f"✅ Сигнал создан: {signal}")
                return signal
            else:
                logger.info(f"⏳ Условия не выполнены для {symbol} ({conditions_met}/4)")
                logger.info(f"   Ждем улучшения показателей...")
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка расчета индикаторов {symbol}: {e}")
            import traceback
            logger.error(f"Подробности ошибки: {traceback.format_exc()}")
            return None
    
    # Остальные методы остаются без изменений...
    async def check_peak_trend(self, symbol: str) -> Optional[float]:
        """Проверка пика тренда (ADX > 45)"""
        try:
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                return None
                
            candles = await self.tinkoff_provider.get_candles_for_ticker(
                ticker_info['figi'], hours=120
            )
            
            if len(candles) < 50:
                return None
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                return None
            
            # Рассчитываем ADX
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            current_adx = adx_data['adx'][-1]
            current_price = closes[-1]
            
            if pd.isna(current_adx):
                return None
                
            if current_adx > 45:
                logger.info(f"🔥 Пик тренда {symbol}: ADX {current_adx:.1f}")
                return current_price
                
            return None
            
        except Exception as e:
            logger.error(f"Ошибка проверки пика тренда {symbol}: {e}")
            return None
    
    async def get_current_price(self, symbol: str) -> float:
        """Получение текущей цены"""
        try:
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                return 0
                
            candles = await self.tinkoff_provider.get_candles_for_ticker(
                ticker_info['figi'], hours=2
            )
            if candles:
                df = self.tinkoff_provider.candles_to_dataframe(candles)
                return df.iloc[-1]['close'] if not df.empty else 0
            return 0
        except:
            return 0
