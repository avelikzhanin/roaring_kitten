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
    """Обработчик торговых сигналов с TradingView алгоритмом"""
    
    def __init__(self, tinkoff_provider, database, gpt_analyzer=None):
        self.tinkoff_provider = tinkoff_provider
        self.db = database
        self.gpt_analyzer = gpt_analyzer
    
    async def analyze_market(self, symbol: str) -> Optional[TradingSignal]:
        """Анализ рынка для конкретной акции с 15 часами данных"""
        try:
            logger.info(f"🔍 Анализ {symbol}")
            
            # Получаем информацию о тикере
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                logger.error(f"Тикер {symbol} не найден")
                return None
            
            logger.info(f"📋 {symbol}: FIGI = {ticker_info['figi']}")
            
            # ТЕСТ: Максимальный фокус на текущем движении - 15 часов!
            candles = await self.tinkoff_provider.get_candles_for_ticker(
                ticker_info['figi'], hours=15
            )
            
            logger.info(f"📊 Получено {len(candles)} свечей для {symbol} (15 часов)")
            
            if len(candles) < 15:
                logger.warning(f"Недостаточно данных для {symbol}: {len(candles)} < 15")
                return None
            
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
        """Расчет технических индикаторов с TradingView алгоритмом"""
        try:
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            logger.info(f"📊 Расчет индикаторов для {symbol}: {len(closes)} свечей (TradingView)")
            
            # Минимальная проверка данных
            if len(closes) < 15:
                logger.warning(f"Мало данных для {symbol}: {len(closes)} свечей (нужно 15+)")
                return None
            
            # Расчет EMA с адаптивным периодом
            if len(closes) >= 20:
                ema20 = TechnicalIndicators.calculate_ema(closes, 20)
                ema_period = 20
            else:
                ema_period = max(5, len(closes) // 2)
                ema20 = TechnicalIndicators.calculate_ema(closes, ema_period)
                logger.info(f"⚠️ Используем EMA{ema_period} вместо EMA20 для {symbol} (мало данных)")
            
            # Расчет ADX с TradingView алгоритмом
            adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            
            # Текущие значения
            current_price = closes[-1]
            current_ema20 = ema20[-1] if not pd.isna(ema20[-1]) else None
            current_adx = adx_data['adx'][-1] if not pd.isna(adx_data['adx'][-1]) else None
            current_plus_di = adx_data['plus_di'][-1] if not pd.isna(adx_data['plus_di'][-1]) else None
            current_minus_di = adx_data['minus_di'][-1] if not pd.isna(adx_data['minus_di'][-1]) else None
            
            # Логируем результаты с указанием алгоритма
            logger.info(f"💰 {symbol}: {current_price:.2f} ₽ | EMA{ema_period}: {current_ema20:.2f if current_ema20 else 'NaN'}")
            logger.info(f"📊 ADX(TradingView-15ч): {current_adx:.1f if current_adx else 'NaN'} | +DI: {current_plus_di:.1f if current_plus_di else 'NaN'} | -DI: {current_minus_di:.1f if current_minus_di else 'NaN'}")
            
            # Сравнение с эталоном TradingView для GAZP
            if symbol == 'GAZP' and current_adx is not None:
                expected_adx = 58.96
                expected_plus_di = 18.41
                expected_minus_di = 29.35
                
                adx_diff = abs(current_adx - expected_adx)
                plus_di_diff = abs(current_plus_di - expected_plus_di)
                minus_di_diff = abs(current_minus_di - expected_minus_di)
                total_diff = adx_diff + plus_di_diff + minus_di_diff
                
                logger.info(f"🎯 ТЕСТ vs TradingView GAZP (15ч):")
                logger.info(f"   ADX: {current_adx:.1f} vs {expected_adx} (откл: {adx_diff:.1f})")
                logger.info(f"   +DI: {current_plus_di:.1f} vs {expected_plus_di} (откл: {plus_di_diff:.1f})")
                logger.info(f"   -DI: {current_minus_di:.1f} vs {expected_minus_di} (откл: {minus_di_diff:.1f})")
                logger.info(f"   Общее отклонение: {total_diff:.1f}")
                
                if total_diff < 10:
                    logger.info("🎉 ОТЛИЧНАЯ ТОЧНОСТЬ с 15 часами!")
                elif total_diff < 20:
                    logger.info("✅ ХОРОШАЯ ТОЧНОСТЬ с 15 часами!")
                elif total_diff < 40:
                    logger.info("⚠️ СРЕДНЯЯ ТОЧНОСТЬ - попробуем настроить алгоритм")
                else:
                    logger.info("❌ ПЛОХАЯ ТОЧНОСТЬ - нужна другая стратегия")
            
            # Проверяем на NaN и выводим детальную диагностику
            if any(val is None or pd.isna(val) for val in [current_ema20, current_adx, current_plus_di, current_minus_di]):
                logger.warning(f"Индикаторы содержат NaN для {symbol} (свечей: {len(closes)})")
                
                # Детальная диагностика
                if current_ema20 is None or pd.isna(current_ema20):
                    logger.error(f"❌ EMA{ema_period} не рассчитан для {symbol}")
                if current_adx is None or pd.isna(current_adx):
                    logger.error(f"❌ ADX не рассчитан для {symbol}")
                    # Проверяем сколько валидных ADX значений
                    valid_adx = [x for x in adx_data['adx'] if not pd.isna(x)]
                    logger.error(f"   Валидных ADX: {len(valid_adx)}/{len(adx_data['adx'])}")
                if current_plus_di is None or pd.isna(current_plus_di):
                    logger.error(f"❌ +DI не рассчитан для {symbol}")
                if current_minus_di is None or pd.isna(current_minus_di):
                    logger.error(f"❌ -DI не рассчитан для {symbol}")
                
                return None
            
            # Проверка условий сигнала
            condition_1 = current_price > current_ema20
            condition_2 = current_adx > 25
            condition_3 = current_plus_di > current_minus_di
            condition_4 = current_plus_di - current_minus_di > 1
            
            conditions = [condition_1, condition_2, condition_3, condition_4]
            conditions_met = sum(conditions)
            
            logger.info(f"🧐 {symbol} условия: {conditions_met}/4 | "
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
        """Получение детального статуса рынка с 15 часами данных"""
        try:
            logger.info(f"🔄 Детальный статус {symbol} (15 часов)")
            
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                return f"❌ <b>Акция {symbol} не поддерживается</b>"
            
            # ТЕСТ: 15 часов для максимальной чувствительности
            candles = await asyncio.wait_for(
                self.tinkoff_provider.get_candles_for_ticker(ticker_info['figi'], hours=15),
                timeout=45
            )
            
            logger.info(f"📊 Получено {len(candles)} свечей для детального анализа {symbol} (15ч)")
            
            if len(candles) < 15:
                return f"❌ <b>Недостаточно данных для анализа {symbol}</b>\nПолучено {len(candles)} свечей, нужно минимум 15."
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                return f"❌ <b>Ошибка получения данных {symbol}</b>"
            
            # Получаем текущие значения индикаторов
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            # Расчет индикаторов с адаптивным EMA
            if len(closes) >= 20:
                ema20 = TechnicalIndicators.calculate_ema(closes, 20)
                ema_period = 20
            else:
                ema_period = max(5, len(closes) // 2)
                ema20 = TechnicalIndicators.calculate_ema(closes, ema_period)
            
            adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            
            current_price = closes[-1]
            current_ema20 = ema20[-1]
            current_adx = adx_data['adx'][-1]
            current_plus_di = adx_data['plus_di'][-1]
            current_minus_di = adx_data['minus_di'][-1]
            
            # Проверяем на NaN и логируем для отладки
            nan_indicators = []
            if pd.isna(current_ema20):
                nan_indicators.append("EMA20")
            if pd.isna(current_adx):
                nan_indicators.append("ADX")
            if pd.isna(current_plus_di):
                nan_indicators.append("+DI")
            if pd.isna(current_minus_di):
                nan_indicators.append("-DI")
            
            if nan_indicators:
                logger.error(f"NaN индикаторы для {symbol}: {nan_indicators}")
                return f"❌ <b>Ошибка расчета индикаторов {symbol}</b>\n\nНе удалось рассчитать: {', '.join(nan_indicators)}\nДанных: {len(closes)} свечей (15ч)"
            
            # Проверяем условия
            price_above_ema = current_price > current_ema20
            strong_trend = current_adx > 25
            positive_direction = current_plus_di > current_minus_di
            di_difference = (current_plus_di - current_minus_di) > 1
            peak_trend = current_adx > 45
            
            all_conditions_met = all([price_above_ema, strong_trend, positive_direction, di_difference])
            
            # Проверяем активные позиции
            active_positions = await self.db.get_active_positions_count(symbol)
            peak_warning = ""
            if peak_trend and active_positions > 0:
                peak_warning = f"\n🔥 <b>ВНИМАНИЕ: ADX > 45 - пик тренда {symbol}! Время продавать!</b>"
            elif peak_trend:
                peak_warning = f"\n🔥 <b>ADX > 45 - пик тренда {symbol}</b>"
            
            ema_text = f"EMA{ema_period}" if ema_period != 20 else "EMA20"
            
            message = f"""📊 <b>ТЕКУЩЕЕ СОСТОЯНИЕ АКЦИЙ {symbol}</b>
<i>ТЕСТ: Анализ на {len(closes)} свечах (15ч - максимальная чувствительность)</i>

💰 <b>Цена:</b> {current_price:.2f} ₽
📈 <b>{ema_text}:</b> {current_ema20:.2f} ₽ {'✅' if price_above_ema else '❌'}

📊 <b>Индикаторы:</b>
• <b>ADX:</b> {current_adx:.1f} {'✅' if strong_trend else '❌'} (нужно >25)
• <b>+DI:</b> {current_plus_di:.1f}
• <b>-DI:</b> {current_minus_di:.1f} {'✅' if positive_direction else '❌'}
• <b>Разница DI:</b> {current_plus_di - current_minus_di:.1f} {'✅' if di_difference else '❌'} (нужно >1){peak_warning}

{'🔔 <b>Все условия выполнены - ожидайте сигнал!</b>' if all_conditions_met else '⏳ <b>Ожидаем улучшения показателей...</b>'}"""

            # Добавляем сравнение с TradingView для GAZP (тест с 15ч)
            if symbol == 'GAZP' and not pd.isna(current_adx):
                expected_adx = 58.96
                expected_plus_di = 18.41
                expected_minus_di = 29.35
                
                adx_diff = abs(current_adx - expected_adx)
                plus_di_diff = abs(current_plus_di - expected_plus_di)
                minus_di_diff = abs(current_minus_di - expected_minus_di)
                total_diff = adx_diff + plus_di_diff + minus_di_diff
                
                message += f"\n\n🎯 <b>ТЕСТ vs TradingView (15ч):</b>\n"
                message += f"ADX: {current_adx:.1f} vs эталон {expected_adx} (откл: {adx_diff:.1f})\n"
                message += f"+DI: {current_plus_di:.1f} vs эталон {expected_plus_di} (откл: {plus_di_diff:.1f})\n"
                message += f"-DI: {current_minus_di:.1f} vs эталон {expected_minus_di} (откл: {minus_di_diff:.1f})\n"
                message += f"Общее отклонение: <b>{total_diff:.1f}</b>"
                
                if total_diff < 10:
                    message += " 🎉 СУПЕР!"
                elif total_diff < 20:
                    message += " ✅ ХОРОШО!"
                elif total_diff < 40:
                    message += " ⚠️ СРЕДНЕ"
                else:
                    message += " ❌ ПЛОХО"
            
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
            return f"❌ <b>Ошибка получения данных {symbol}</b>\n\nДетали: {str(e)}"
    
    async def check_peak_trend(self, symbol: str) -> Optional[float]:
        """Проверка пика тренда с 15 часами данных"""
        try:
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                return None
                
            # ТЕСТ: 15 часов для максимальной чувствительности к пикам
            candles = await self.tinkoff_provider.get_candles_for_ticker(
                ticker_info['figi'], hours=15
            )
            
            if len(candles) < 15:
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
                logger.warning(f"ADX не рассчитан для проверки пика {symbol}")
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
                ticker_info['figi'], hours=5  # Для цены хватит 5 часов
            )
            if candles:
                df = self.tinkoff_provider.candles_to_dataframe(candles)
                return df.iloc[-1]['close'] if not df.empty else 0
            return 0
        except:
            return 0
