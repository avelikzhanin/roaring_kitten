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
    """Обработчик торговых сигналов"""
    
    def __init__(self, tinkoff_provider, database, gpt_analyzer=None):
        self.tinkoff_provider = tinkoff_provider
        self.db = database
        self.gpt_analyzer = gpt_analyzer
    
    async def analyze_market(self, symbol: str) -> Optional[TradingSignal]:
        """Анализ рынка для конкретной акции"""
        try:
            logger.info(f"🔍 Анализ {symbol}")
            
            # Получаем информацию о тикере
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                logger.error(f"Тикер {symbol} не найден")
                return None
            
            # Получаем свечи (100 часов для стабильного ADX)
            candles = await self.tinkoff_provider.get_candles_for_ticker(
                ticker_info['figi'], hours=300
            )
            
            if len(candles) < 100:
                logger.warning(f"Недостаточно данных для {symbol}: {len(candles)} свечей")
                return None
            
            logger.info(f"📊 Получено {len(candles)} свечей")
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                logger.error(f"Пустой DataFrame для {symbol}")
                return None
            
            # Рассчитываем индикаторы
            signal = self._calculate_indicators(df, symbol)
            
            return signal
            
        except Exception as e:
            logger.error(f"Ошибка анализа {symbol}: {e}")
            return None
    
    def _calculate_indicators(self, df, symbol: str) -> Optional[TradingSignal]:
        """Расчет технических индикаторов"""
        try:
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            # Рассчитываем индикаторы
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
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
                return None
            
            # Логируем результаты компактно
            logger.info(f"💰 {symbol}: {current_price:.2f} ₽ | EMA20: {current_ema20:.2f}")
            logger.info(f"📊 ADX: {current_adx:.1f} | +DI: {current_plus_di:.1f} | -DI: {current_minus_di:.1f}")
            
            # Проверка условий сигнала
            condition_1 = current_price > current_ema20
            condition_2 = current_adx > 25
            condition_3 = current_plus_di > current_minus_di
            condition_4 = current_plus_di - current_minus_di > 1
            
            conditions = [condition_1, condition_2, condition_3, condition_4]
            conditions_met = sum(conditions)
            
            logger.info(f"🧐 Условия: {conditions_met}/4 | "
                       f"Цена>EMA: {'✅' if condition_1 else '❌'} | "
                       f"ADX>25: {'✅' if condition_2 else '❌'} | "
                       f"+DI>-DI: {'✅' if condition_3 else '❌'} | "
                       f"Разница>1: {'✅' if condition_4 else '❌'}")
            
            if all(conditions):
                logger.info(f"🎉 СИГНАЛ ПОКУПКИ {symbol}!")
                
                signal = TradingSignal(
                    symbol=symbol,
                    timestamp=df.iloc[-1]['timestamp'],
                    price=current_price,
                    ema20=current_ema20,
                    adx=current_adx,
                    plus_di=current_plus_di,
                    minus_di=current_minus_di
                )
                
                return signal
            else:
                logger.info(f"⏳ Ожидаем сигнал {symbol}")
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка расчета индикаторов {symbol}: {e}")
            return None
    
    async def get_detailed_market_status(self, symbol: str) -> str:
        """Получение детального статуса рынка"""
        try:
            logger.info(f"🔄 Статус {symbol}")
            
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                return f"❌ <b>Акция {symbol} не поддерживается</b>"
            
            candles = await asyncio.wait_for(
                self.tinkoff_provider.get_candles_for_ticker(ticker_info['figi'], hours=300),
                timeout=45
            )
            
            if len(candles) < 100:
                return f"❌ <b>Недостаточно данных для анализа {symbol}</b>\nПолучено {len(candles)} свечей."
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                return f"❌ <b>Ошибка получения данных {symbol}</b>"
            
            # Получаем текущие значения индикаторов
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
            adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            
            current_price = closes[-1]
            current_ema20 = ema20[-1]
            current_adx = adx_data['adx'][-1]
            current_plus_di = adx_data['plus_di'][-1]
            current_minus_di = adx_data['minus_di'][-1]
            
            # Проверяем условия
            price_above_ema = current_price > current_ema20 if not pd.isna(current_ema20) else False
            strong_trend = current_adx > 25 if not pd.isna(current_adx) else False
            positive_direction = current_plus_di > current_minus_di if not pd.isna(current_plus_di) and not pd.isna(current_minus_di) else False
            di_difference = (current_plus_di - current_minus_di) > 1 if not pd.isna(current_plus_di) and not pd.isna(current_minus_di) else False
            peak_trend = current_adx > 45 if not pd.isna(current_adx) else False
            
            all_conditions_met = all([price_above_ema, strong_trend, positive_direction, di_difference])
            
            # Проверяем активные позиции
            active_positions = await self.db.get_active_positions_count(symbol)
            peak_warning = ""
            if peak_trend and active_positions > 0:
                peak_warning = f"\n🔥 <b>ВНИМАНИЕ: ADX > 45 - пик тренда {symbol}! Время продавать!</b>"
            elif peak_trend:
                peak_warning = f"\n🔥 <b>ADX > 45 - пик тренда {symbol}</b>"
            
            message = f"""📊 <b>ТЕКУЩЕЕ СОСТОЯНИЕ АКЦИЙ {symbol}</b>

💰 <b>Цена:</b> {current_price:.2f} ₽
📈 <b>EMA20:</b> {current_ema20:.2f} ₽ {'✅' if price_above_ema else '❌'}

📊 <b>Индикаторы:</b>
• <b>ADX:</b> {current_adx:.1f} {'✅' if strong_trend else '❌'} (нужно >25)
• <b>+DI:</b> {current_plus_di:.1f}
• <b>-DI:</b> {current_minus_di:.1f} {'✅' if positive_direction else '❌'}
• <b>Разница DI:</b> {current_plus_di - current_minus_di:.1f} {'✅' if di_difference else '❌'} (нужно >1){peak_warning}

{'🔔 <b>Все условия выполнены - ожидайте сигнал!</b>' if all_conditions_met else '⏳ <b>Ожидаем улучшения показателей...</b>'}"""
            
            # Добавляем GPT анализ
            if self.gpt_analyzer:
                try:
                    candles_data = []
                    for _, row in df.iterrows():
                        candles_data.append({
                            'timestamp': row['timestamp'],
                            'open': float(row['open']),
                            'high': float(row['high']),
                            'low': float(row['low']),
                            'close': float(row['close']),
                            'volume': int(row['volume'])
                        })
                    
                    signal_data = {
                        'price': current_price,
                        'ema20': current_ema20,
                        'adx': current_adx,
                        'plus_di': current_plus_di,
                        'minus_di': current_minus_di,
                        'conditions_met': all_conditions_met
                    }
                    
                    gpt_advice = await self.gpt_analyzer.analyze_signal(
                        signal_data, candles_data, is_manual_check=True, symbol=symbol
                    )
                    if gpt_advice:
                        message += f"\n{self.gpt_analyzer.format_advice_for_telegram(gpt_advice, symbol)}"
                    else:
                        message += "\n\n🤖 <i>GPT анализ временно недоступен</i>"
                except Exception as e:
                    logger.error(f"Ошибка GPT анализа {symbol}: {e}")
                    message += "\n\n🤖 <i>GPT анализ временно недоступен</i>"
            
            return message
                
        except asyncio.TimeoutError:
            logger.error(f"Таймаут получения данных {symbol}")
            return f"❌ <b>Таймаут при получении данных {symbol}</b>"
        except Exception as e:
            logger.error(f"Ошибка анализа {symbol}: {e}")
            return f"❌ <b>Ошибка получения данных {symbol}</b>"
    
    async def check_peak_trend(self, symbol: str) -> Optional[float]:
        """Проверка пика тренда (ADX > 45)"""
        try:
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                return None
                
            candles = await self.tinkoff_provider.get_candles_for_ticker(
                ticker_info['figi'], hours=300
            )
            
            if len(candles) < 100:
                return None
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                return None
            
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
            logger.error(f"Ошибка проверки пика {symbol}: {e}")
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
