import asyncio
import logging
from datetime import datetime, time
import pytz
from typing import Optional, Dict, List
import pandas as pd
import numpy as np
from dataclasses import dataclass

from .indicators import TechnicalIndicators

logger = logging.getLogger(__name__)

@dataclass
class TradingSignal:
    """Структура торгового сигнала с РЕАЛЬНЫМИ ADX значениями от GPT"""
    symbol: str
    timestamp: datetime
    price: float
    ema20: float
    
    # РЕАЛЬНЫЕ ADX значения рассчитанные GPT
    adx: float = 0.0
    plus_di: float = 0.0
    minus_di: float = 0.0
    
    # GPT данные
    gpt_recommendation: Optional[str] = None
    gpt_confidence: Optional[int] = None
    gpt_full_advice: Optional[object] = None  # Полный GPT объект

class SignalProcessor:
    """Обработчик сигналов: базовый фильтр + GPT с РЕАЛЬНЫМИ ADX расчетами"""
    
    def __init__(self, tinkoff_provider, database, gpt_analyzer=None):
        self.tinkoff_provider = tinkoff_provider
        self.db = database
        self.gpt_analyzer = gpt_analyzer
        self.moscow_tz = pytz.timezone('Europe/Moscow')
        
        adx_status = "✅ РЕАЛЬНЫЙ ADX от GPT" if gpt_analyzer else "❌ Без ADX"
        logger.info(f"🔄 SignalProcessor инициализирован ({adx_status})")
    
    def is_market_open(self) -> bool:
        """Проверка торгового времени (все сессии включая выходные)"""
        now_moscow = datetime.now(self.moscow_tz)
        current_time = now_moscow.time()
        current_weekday = now_moscow.weekday()  # 0=пн, 6=вс
        
        if current_weekday < 5:  # Пн-Пт
            # Основная сессия: 09:50 - 18:50 МСК
            main_session = time(9, 50) <= current_time <= time(18, 50)
            # Вечерняя сессия: 19:00 - 23:49 МСК  
            evening_session = time(19, 0) <= current_time <= time(23, 49)
            return main_session or evening_session
        else:  # Сб-Вс
            # Дополнительная сессия: 10:00 - 19:00 МСК
            weekend_session = time(10, 0) <= current_time <= time(19, 0)
            return weekend_session
    
    def get_current_session(self) -> str:
        """Определение текущей торговой сессии"""
        now_moscow = datetime.now(self.moscow_tz)
        current_time = now_moscow.time()
        current_weekday = now_moscow.weekday()
        
        if current_weekday < 5:  # Пн-Пт
            if time(9, 50) <= current_time <= time(18, 50):
                return 'main'
            elif time(19, 0) <= current_time <= time(23, 49):
                return 'evening'
        else:  # Сб-Вс
            if time(10, 0) <= current_time <= time(19, 0):
                return 'weekend'
        
        return 'closed'
    
    def get_time_quality(self) -> str:
        """Оценка качества торгового времени"""
        now_moscow = datetime.now(self.moscow_tz)
        current_time = now_moscow.time()
        current_weekday = now_moscow.weekday()
        
        if current_weekday < 5:  # Пн-Пт
            if time(11, 0) <= current_time <= time(16, 0):
                return 'premium'  # Лучшее время
            elif time(9, 50) <= current_time <= time(18, 50):
                return 'normal'   # Основная сессия
            elif time(19, 0) <= current_time <= time(23, 49):
                return 'evening'  # Вечерняя сессия
        else:  # Выходные
            return 'weekend'
        
        return 'closed'
    
    async def analyze_market(self, symbol: str) -> Optional[TradingSignal]:
        """Анализ рынка: базовый фильтр + GPT с РЕАЛЬНЫМИ ADX расчетами"""
        try:
            logger.info(f"🔍 АНАЛИЗ {symbol} с РЕАЛЬНЫМИ ADX от GPT")
            
            # Получаем информацию о тикере
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                logger.error(f"Тикер {symbol} не найден в БД")
                return None
            
            # Получаем свечи для анализа
            candles = await self.tinkoff_provider.get_candles_for_ticker(
                ticker_info['figi'], hours=120
            )
            
            if len(candles) < 30:
                logger.warning(f"Недостаточно данных для {symbol}: {len(candles)} свечей")
                return None
            
            logger.info(f"📈 Получено {len(candles)} свечей для анализа")
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                logger.error(f"Пустой DataFrame для {symbol}")
                return None
            
            # ЭТАП 1: БАЗОВЫЙ ФИЛЬТР (простые технические условия)
            if not await self._check_basic_filter(df, symbol):
                logger.info(f"⏳ Базовый фильтр не пройден для {symbol}")
                return None
            
            logger.info(f"✅ Базовый фильтр пройден для {symbol}")
            
            # ЭТАП 2: ПОДГОТОВКА ДАННЫХ ДЛЯ GPT
            market_data = self._prepare_market_data(df, symbol)
            
            # ЭТАП 3: GPT РАССЧИТЫВАЕТ РЕАЛЬНЫЕ ADX И ПРИНИМАЕТ РЕШЕНИЕ
            if self.gpt_analyzer:
                gpt_advice = await self._get_gpt_decision(market_data, symbol)
                
                if gpt_advice and gpt_advice.recommendation in ['BUY', 'WEAK_BUY']:
                    # GPT рекомендует покупку - создаём сигнал с РЕАЛЬНЫМИ ADX
                    signal = TradingSignal(
                        symbol=symbol,
                        timestamp=df.iloc[-1]['timestamp'],
                        price=market_data['current_price'],
                        ema20=market_data['ema20'],
                        # РЕАЛЬНЫЕ ADX значения от GPT
                        adx=gpt_advice.calculated_adx or 0.0,
                        plus_di=gpt_advice.calculated_plus_di or 0.0,
                        minus_di=gpt_advice.calculated_minus_di or 0.0,
                        # GPT данные
                        gpt_recommendation=gpt_advice.recommendation,
                        gpt_confidence=gpt_advice.confidence,
                        gpt_full_advice=gpt_advice  # Полный GPT объект
                    )
                    
                    logger.info(f"🎉 GPT РЕКОМЕНДУЕТ {gpt_advice.recommendation} для {symbol}")
                    logger.info(f"📊 РЕАЛЬНЫЕ ADX от GPT: ADX={signal.adx:.1f}, +DI={signal.plus_di:.1f}, -DI={signal.minus_di:.1f}")
                    return signal
                else:
                    rec = gpt_advice.recommendation if gpt_advice else 'UNKNOWN'
                    logger.info(f"⏳ GPT не рекомендует покупку {symbol}: {rec}")
                    return None
            else:
                # Работаем без GPT - создаём базовый сигнал БЕЗ ADX
                logger.warning("🤖 GPT недоступен, работаем только по базовому фильтру (не рекомендуется)")
                signal = TradingSignal(
                    symbol=symbol,
                    timestamp=df.iloc[-1]['timestamp'],
                    price=market_data['current_price'],
                    ema20=market_data['ema20'],
                    # Без ADX значений
                    adx=0.0,
                    plus_di=0.0,
                    minus_di=0.0
                )
                return signal
            
        except Exception as e:
            logger.error(f"Ошибка анализа рынка {symbol}: {e}")
            return None
    
    async def _check_basic_filter(self, df: pd.DataFrame, symbol: str) -> bool:
        """Проверка базового фильтра: цена > EMA20 + торговое время"""
        try:
            # 1. Проверяем торговое время
            if not self.is_market_open():
                session = self.get_current_session()
                logger.info(f"📅 Рынок закрыт для {symbol} (сессия: {session})")
                return False
            
            # 2. Рассчитываем EMA20
            closes = df['close'].tolist()
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
            
            current_price = closes[-1]
            current_ema20 = ema20[-1]
            
            if pd.isna(current_ema20):
                logger.warning(f"EMA20 не рассчитана для {symbol}")
                return False
            
            # 3. Проверяем основное условие: цена > EMA20
            price_above_ema = current_price > current_ema20
            
            # Логирование результатов
            session = self.get_current_session()
            time_quality = self.get_time_quality()
            
            logger.info(f"🔍 БАЗОВЫЙ ФИЛЬТР {symbol}:")
            logger.info(f"   💰 Цена: {current_price:.2f} ₽")
            logger.info(f"   📈 EMA20: {current_ema20:.2f} ₽")
            logger.info(f"   📊 Цена > EMA20: {'✅' if price_above_ema else '❌'}")
            logger.info(f"   ⏰ Сессия: {session} ({time_quality})")
            
            return price_above_ema
            
        except Exception as e:
            logger.error(f"Ошибка базового фильтра {symbol}: {e}")
            return False
    
    def _prepare_market_data(self, df: pd.DataFrame, symbol: str) -> Dict:
        """Подготовка данных для GPT анализа с РЕАЛЬНЫМИ ADX расчетами"""
        try:
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            volumes = df['volume'].tolist()
            
            # Основные показатели
            current_price = closes[-1]
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
            current_ema20 = ema20[-1]
            
            # Анализ объёмов
            avg_volume_5d = np.mean(volumes[-120:]) if len(volumes) >= 120 else np.mean(volumes)
            current_volume = volumes[-1]
            volume_ratio = current_volume / avg_volume_5d if avg_volume_5d > 0 else 1.0
            
            # Анализ уровней поддержки/сопротивления
            price_levels = self._analyze_price_levels(df)
            
            # Ценовое движение
            price_movement = self._analyze_price_movement(closes)
            
            # Свечные данные для GPT (последние 50 свечей)
            candles_data = []
            for i in range(max(0, len(df) - 50), len(df)):
                row = df.iloc[i]
                candles_data.append({
                    'timestamp': row['timestamp'],
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': int(row['volume'])
                })
            
            market_data = {
                # Базовые данные
                'symbol': symbol,
                'current_price': current_price,
                'ema20': current_ema20,
                'price_above_ema': current_price > current_ema20,
                
                # Свечные данные для расчета РЕАЛЬНЫХ ADX
                'candles_data': candles_data,
                
                # Анализ объёмов
                'volume_analysis': {
                    'current_volume': current_volume,
                    'avg_volume_5d': avg_volume_5d,
                    'volume_ratio': volume_ratio,
                    'volume_trend': self._get_volume_trend(volumes)
                },
                
                # Уровни поддержки/сопротивления
                'price_levels': price_levels,
                
                # Ценовое движение
                'price_movement': price_movement,
                
                # Контекст времени
                'trading_session': self.get_current_session(),
                'time_quality': self.get_time_quality(),
                
                # Технические показатели для GPT
                'conditions_met': True  # Базовый фильтр уже пройден
            }
            
            logger.info(f"📊 Подготовлены данные для GPT расчета РЕАЛЬНЫХ ADX {symbol}")
            return market_data
            
        except Exception as e:
            logger.error(f"Ошибка подготовки данных для {symbol}: {e}")
            return {}
    
    def _analyze_price_levels(self, df: pd.DataFrame) -> Dict:
        """Анализ уровней поддержки и сопротивления"""
        try:
            # Последние 50 свечей для анализа уровней
            recent_data = df.tail(50) if len(df) > 50 else df
            
            highs = recent_data['high'].tolist()
            lows = recent_data['low'].tolist()
            closes = recent_data['close'].tolist()
            
            current_price = closes[-1]
            
            # Поиск уровней сопротивления (локальные максимумы)
            resistances = []
            for i in range(2, len(highs) - 2):
                if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and 
                    highs[i] > highs[i+1] and highs[i] > highs[i+2]):
                    if highs[i] > current_price:
                        resistances.append(highs[i])
            
            # Поиск уровней поддержки (локальные минимумы)
            supports = []
            for i in range(2, len(lows) - 2):
                if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and 
                    lows[i] < lows[i+1] and lows[i] < lows[i+2]):
                    if lows[i] < current_price:
                        supports.append(lows[i])
            
            resistances = sorted(list(set(resistances)))[:3]  # Ближайшие 3
            supports = sorted(list(set(supports)), reverse=True)[:3]  # Ближайшие 3
            
            return {
                'current_price': current_price,
                'nearest_resistance': resistances[0] if resistances else None,
                'nearest_support': supports[0] if supports else None,
                'all_resistances': resistances,
                'all_supports': supports,
                'recent_high': max(highs),
                'recent_low': min(lows)
            }
            
        except Exception as e:
            logger.error(f"Ошибка анализа уровней: {e}")
            return {}
    
    def _analyze_price_movement(self, closes: List[float]) -> Dict:
        """Анализ ценового движения"""
        try:
            if len(closes) < 5:
                return {}
            
            current_price = closes[-1]
            
            # Изменения за разные периоды
            change_1h = ((current_price - closes[-2]) / closes[-2] * 100) if len(closes) >= 2 else 0
            change_4h = ((current_price - closes[-5]) / closes[-5] * 100) if len(closes) >= 5 else 0
            change_1d = ((current_price - closes[-25]) / closes[-25] * 100) if len(closes) >= 25 else 0
            
            # Волатильность за 5 дней
            if len(closes) >= 25:
                recent_changes = [abs(closes[i] - closes[i-1]) / closes[i-1] * 100 
                                for i in range(-25, -1)]
                volatility_5d = np.mean(recent_changes)
            else:
                volatility_5d = 0
            
            return {
                'change_1h': round(change_1h, 2),
                'change_4h': round(change_4h, 2),
                'change_1d': round(change_1d, 2),
                'volatility_5d': round(volatility_5d, 2)
            }
            
        except Exception as e:
            logger.error(f"Ошибка анализа движения: {e}")
            return {}
    
    def _get_volume_trend(self, volumes: List[int]) -> str:
        """Определение тренда объёмов"""
        try:
            if len(volumes) < 10:
                return 'unknown'
            
            recent_avg = np.mean(volumes[-5:])
            previous_avg = np.mean(volumes[-10:-5])
            
            if recent_avg > previous_avg * 1.1:
                return 'increasing'
            elif recent_avg < previous_avg * 0.9:
                return 'decreasing'
            else:
                return 'stable'
                
        except Exception:
            return 'unknown'
    
    async def _get_gpt_decision(self, market_data: Dict, symbol: str):
        """Получение решения от GPT с расчетом РЕАЛЬНЫХ ADX"""
        try:
            logger.info(f"🤖 Запрашиваем GPT для расчета РЕАЛЬНЫХ ADX {symbol}...")
            
            # Подготавливаем данные для GPT с акцентом на ADX расчеты
            signal_data = {
                # Основные данные
                'price': market_data['current_price'],
                'ema20': market_data['ema20'],
                'price_above_ema': market_data['price_above_ema'],
                'conditions_met': market_data['conditions_met'],
                
                # Данные для анализа (без ADX - GPT их рассчитает)
                'volume_analysis': market_data.get('volume_analysis', {}),
                'price_levels': market_data.get('price_levels', {}),
                
                # Контекст времени
                'trading_session': market_data.get('trading_session', 'unknown'),
                'time_quality': market_data.get('time_quality', 'unknown')
            }
            
            # Добавляем движение цены если есть
            if 'price_movement' in market_data:
                signal_data.update(market_data['price_movement'])
            
            # Запрашиваем анализ у GPT с расчетом РЕАЛЬНЫХ ADX
            gpt_advice = await self.gpt_analyzer.analyze_signal(
                signal_data=signal_data,
                candles_data=market_data.get('candles_data'),
                is_manual_check=False,
                symbol=symbol
            )
            
            if gpt_advice:
                adx_info = ""
                if gpt_advice.calculated_adx is not None:
                    adx_info = f" (РЕАЛЬНЫЙ ADX: {gpt_advice.calculated_adx:.1f})"
                
                logger.info(f"🤖 GPT ответ для {symbol}: {gpt_advice.recommendation} ({gpt_advice.confidence}%){adx_info}")
                return gpt_advice
            else:
                logger.warning(f"🤖 GPT не дал ответа для {symbol}")
                return None
                
        except Exception as e:
            logger.error(f"Ошибка GPT анализа для {symbol}: {e}")
            return None
    
    async def get_detailed_market_status(self, symbol: str) -> str:
        """Получение детального статуса рынка с РЕАЛЬНЫМИ ADX от GPT"""
        try:
            logger.info(f"🔄 Получаем детальный статус для {symbol} с РЕАЛЬНЫМИ ADX...")
            
            # Проверяем торговое время
            if not self.is_market_open():
                session = self.get_current_session()
                return f"⏰ <b>Рынок закрыт</b>\n\nТекущая сессия: {session}\n\nПопробуйте в торговое время."
            
            # Получаем информацию о тикере
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                return f"❌ <b>Акция {symbol} не поддерживается</b>"
            
            candles = await asyncio.wait_for(
                self.tinkoff_provider.get_candles_for_ticker(ticker_info['figi'], hours=120),
                timeout=30
            )
            
            if len(candles) < 30:
                logger.warning(f"⚠️ Недостаточно данных для анализа {symbol}")
                return f"❌ <b>Недостаточно данных для анализа {symbol}</b>\n\nПопробуйте позже."
            
            logger.info(f"📊 Получено {len(candles)} свечей для {symbol}, обрабатываем...")
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            
            if df.empty:
                logger.warning(f"⚠️ Пустой DataFrame для {symbol}")
                return f"❌ <b>Ошибка получения данных {symbol}</b>"
            
            # Подготавливаем данные
            market_data = self._prepare_market_data(df, symbol)
            
            # Проверяем базовый фильтр
            basic_filter_passed = await self._check_basic_filter(df, symbol)
            
            # Формируем базовое сообщение
            current_price = market_data['current_price']
            current_ema20 = market_data['ema20']
            price_above_ema = current_price > current_ema20
            
            session = self.get_current_session()
            time_quality = self.get_time_quality()
            
            message = f"""📊 <b>СОСТОЯНИЕ {symbol}</b>

💰 <b>Цена:</b> {current_price:.2f} ₽
📈 <b>EMA20:</b> {current_ema20:.2f} ₽ {'✅' if price_above_ema else '❌'}

⏰ <b>Торговая сессия:</b> {session} ({time_quality})

🔍 <b>Базовый фильтр:</b> {'✅ Пройден' if basic_filter_passed else '❌ Не пройден'}"""
            
            # Добавляем GPT анализ с расчетом РЕАЛЬНЫХ ADX
            if self.gpt_analyzer and basic_filter_passed:
                try:
                    logger.info(f"🤖 Запрашиваем GPT для расчета РЕАЛЬНЫХ ADX {symbol}...")
                    
                    gpt_advice = await self._get_gpt_decision(market_data, symbol)
                    if gpt_advice:
                        message += f"\n{self.gpt_analyzer.format_advice_for_telegram(gpt_advice, symbol)}"
                        logger.info(f"✅ GPT рассчитал РЕАЛЬНЫЕ ADX для {symbol}")
                    else:
                        message += "\n\n🤖 <i>GPT анализ ADX недоступен</i>"
                        logger.warning(f"⚠️ GPT анализ недоступен для {symbol}")
                        
                except Exception as e:
                    logger.error(f"❌ Ошибка GPT анализа для {symbol}: {e}")
                    message += "\n\n🤖 <i>GPT анализ ADX недоступен</i>"
            elif not basic_filter_passed:
                message += "\n\n⏳ <b>Ожидаем улучшения условий...</b>"
            else:
                message += "\n\n📊 <b>Базовый фильтр пройден</b>\n🤖 <i>GPT с ADX недоступен</i>"
            
            return message
                
        except asyncio.TimeoutError:
            logger.error(f"⏰ Таймаут при получении данных рынка для {symbol}")
            return f"❌ <b>Таймаут при получении данных {symbol}</b>\n\nПопробуйте позже."
        except Exception as e:
            logger.error(f"💥 Ошибка в детальном анализе {symbol}: {e}")
            return f"❌ <b>Ошибка получения данных для анализа {symbol}</b>\n\nВозможны временные проблемы."
    
    async def check_peak_trend(self, symbol: str) -> Optional[float]:
        """Проверка пика тренда через GPT с РЕАЛЬНЫМИ ADX (>45)"""
        try:
            # Получаем данные
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                return None
                
            candles = await self.tinkoff_provider.get_candles_for_ticker(
                ticker_info['figi'], hours=120
            )
            
            if len(candles) < 30:
                return None
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                return None
            
            # Подготавливаем данные для GPT
            market_data = self._prepare_market_data(df, symbol)
            current_price = market_data['current_price']
            
            # Специальный GPT анализ для проверки пика (РЕАЛЬНЫЙ ADX > 45)
            if self.gpt_analyzer:
                try:
                    signal_data = {
                        # Основные данные
                        'price': current_price,
                        'ema20': market_data['ema20'],
                        'price_above_ema': market_data['price_above_ema'],
                        'conditions_met': True,
                        'check_peak': True,  # Специальный флаг для пика
                        
                        # Данные для расчета РЕАЛЬНЫХ ADX
                        'volume_analysis': market_data.get('volume_analysis', {}),
                        'price_levels': market_data.get('price_levels', {}),
                        'trading_session': market_data.get('trading_session', 'unknown')
                    }
                    
                    # Добавляем движение цены
                    if 'price_movement' in market_data:
                        signal_data.update(market_data['price_movement'])
                    
                    gpt_advice = await self.gpt_analyzer.analyze_signal(
                        signal_data=signal_data,
                        candles_data=market_data.get('candles_data'),
                        is_manual_check=False,
                        symbol=symbol
                    )
                    
                    # Проверяем РЕАЛЬНЫЙ ADX > 45 от GPT
                    if (gpt_advice and 
                        gpt_advice.calculated_adx is not None and 
                        gpt_advice.calculated_adx > 45):
                        
                        logger.info(f"🔥 GPT определил пик тренда {symbol}: РЕАЛЬНЫЙ ADX {gpt_advice.calculated_adx:.1f} > 45")
                        return current_price
                    
                    # Или если GPT прямо рекомендует AVOID из-за пика
                    if (gpt_advice and 
                        gpt_advice.recommendation == 'AVOID' and 
                        ('пик' in gpt_advice.reasoning.lower() or 'peak' in gpt_advice.reasoning.lower())):
                        
                        logger.info(f"🔥 GPT определил пик тренда {symbol} по анализу: {current_price:.1f}")
                        return current_price
                    
                except Exception as e:
                    logger.error(f"Ошибка GPT анализа пика {symbol}: {e}")
            
            # Fallback: простая проверка высокой волатильности без ADX
            if 'price_movement' in market_data:
                volatility = market_data['price_movement'].get('volatility_5d', 0)
                if volatility > 5.0:  # Высокая волатильность может быть пиком
                    logger.info(f"🔥 Высокая волатильность {symbol}: {volatility:.1f}%")
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
