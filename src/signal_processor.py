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
    """Структура торгового сигнала с комплексными данными"""
    symbol: str
    timestamp: datetime
    price: float
    ema20: float
    
    # ADX данные (могут быть None если GPT не смог рассчитать)
    adx: float = 0.0
    plus_di: float = 0.0
    minus_di: float = 0.0
    
    # GPT данные
    gpt_recommendation: Optional[str] = None
    gpt_confidence: Optional[int] = None
    gpt_full_advice: Optional[object] = None  # Полный GPT объект

class SignalProcessor:
    """Обработчик сигналов с комплексным анализом всех факторов"""
    
    def __init__(self, tinkoff_provider, database, gpt_analyzer=None):
        self.tinkoff_provider = tinkoff_provider
        self.db = database
        self.gpt_analyzer = gpt_analyzer
        self.moscow_tz = pytz.timezone('Europe/Moscow')
        
        analysis_type = "✅ Комплексный анализ с GPT" if gpt_analyzer else "❌ Только базовый фильтр"
        logger.info(f"🔄 SignalProcessor инициализирован ({analysis_type})")
    
    def is_market_open(self) -> bool:
        """Проверка торгового времени"""
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
    
    def get_market_status_text(self) -> Dict[str, str]:
        """Получение статуса рынка с эмодзи и описанием"""
        is_open = self.is_market_open()
        session = self.get_current_session()
        time_quality = self.get_time_quality()
        
        if is_open:
            if time_quality == 'premium':
                return {
                    'emoji': '🟢',
                    'status': 'ОТКРЫТ',
                    'description': f'Премиум время ({session})',
                    'data_freshness': 'Данные актуальны'
                }
            elif time_quality in ['normal', 'evening']:
                return {
                    'emoji': '🟢',
                    'status': 'ОТКРЫТ', 
                    'description': f'Торговая сессия ({session})',
                    'data_freshness': 'Данные актуальны'
                }
            else:
                return {
                    'emoji': '🟠',
                    'status': 'ОТКРЫТ',
                    'description': f'Выходная сессия ({session})',
                    'data_freshness': 'Данные актуальны'
                }
        else:
            return {
                'emoji': '🔴',
                'status': 'ЗАКРЫТ',
                'description': f'Внеторговое время ({session})',
                'data_freshness': 'Данные могут быть не самыми свежими'
            }
    
    async def analyze_market(self, symbol: str) -> Optional[TradingSignal]:
        """Комплексный анализ рынка: базовый фильтр + GPT анализ всех факторов (работает в любое время)"""
        try:
            logger.info(f"🔍 КОМПЛЕКСНЫЙ АНАЛИЗ {symbol} - все факторы через GPT")
            
            # Получаем информацию о тикере
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                logger.error(f"Тикер {symbol} не найден в БД")
                return None
            
            # Получаем свечи (УМЕНЬШИЛИ до 70 часов вместо 120)
            candles = await self.tinkoff_provider.get_candles_for_ticker(
                ticker_info['figi'], hours=70
            )
            
            if len(candles) < 20:  # Снизили минимум
                logger.warning(f"Недостаточно данных для {symbol}: {len(candles)} свечей")
                return None
            
            logger.info(f"📈 Получено {len(candles)} свечей для комплексного анализа")
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                logger.error(f"Пустой DataFrame для {symbol}")
                return None
            
            # ЭТАП 1: БАЗОВЫЙ ФИЛЬТР (теперь БЕЗ проверки торгового времени)
            if not await self._check_basic_filter(df, symbol):
                logger.info(f"⏳ Базовый фильтр не пройден для {symbol}")
                return None
            
            logger.info(f"✅ Базовый фильтр пройден для {symbol}")
            
            # ЭТАП 2: ПОДГОТОВКА КОМПЛЕКСНЫХ ДАННЫХ
            market_data = self._prepare_comprehensive_data(df, symbol)
            
            # ЭТАП 3: КОМПЛЕКСНЫЙ АНАЛИЗ ЧЕРЕЗ GPT
            if self.gpt_analyzer:
                gpt_advice = await self._get_comprehensive_decision(market_data, symbol)
                
                if gpt_advice and gpt_advice.recommendation in ['BUY', 'WEAK_BUY']:
                    # GPT рекомендует покупку - создаём сигнал
                    signal = TradingSignal(
                        symbol=symbol,
                        timestamp=df.iloc[-1]['timestamp'],
                        price=market_data['current_price'],
                        ema20=market_data['ema20'],
                        # ADX данные из GPT (могут быть 0 если не рассчитал)
                        adx=gpt_advice.calculated_adx or 0.0,
                        plus_di=gpt_advice.calculated_plus_di or 0.0,
                        minus_di=gpt_advice.calculated_minus_di or 0.0,
                        # GPT данные
                        gpt_recommendation=gpt_advice.recommendation,
                        gpt_confidence=gpt_advice.confidence,
                        gpt_full_advice=gpt_advice
                    )
                    
                    adx_info = f", ADX: {signal.adx:.1f}" if signal.adx > 0 else ", ADX: не рассчитан"
                    logger.info(f"🎉 GPT РЕКОМЕНДУЕТ {gpt_advice.recommendation} для {symbol} (уверенность {gpt_advice.confidence}%{adx_info})")
                    return signal
                else:
                    rec = gpt_advice.recommendation if gpt_advice else 'НЕИЗВЕСТНО'
                    conf = f" ({gpt_advice.confidence}%)" if gpt_advice else ""
                    logger.info(f"⏳ GPT не рекомендует покупку {symbol}: {rec}{conf}")
                    return None
            else:
                # Работаем без GPT - создаём базовый сигнал
                logger.warning("🤖 GPT недоступен, работаем только по базовому фильтру (не рекомендуется)")
                signal = TradingSignal(
                    symbol=symbol,
                    timestamp=df.iloc[-1]['timestamp'],
                    price=market_data['current_price'],
                    ema20=market_data['ema20']
                )
                return signal
            
        except Exception as e:
            logger.error(f"Ошибка комплексного анализа {symbol}: {e}")
            return None
    
    async def _check_basic_filter(self, df: pd.DataFrame, symbol: str) -> bool:
        """Базовый фильтр: ТОЛЬКО цена > EMA20 (убрана проверка торгового времени)"""
        try:
            # Рассчитываем EMA20
            closes = df['close'].tolist()
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
            
            current_price = closes[-1]
            current_ema20 = ema20[-1]
            
            if pd.isna(current_ema20):
                logger.warning(f"EMA20 не рассчитана для {symbol}")
                return False
            
            # Проверяем: цена > EMA20
            price_above_ema = current_price > current_ema20
            
            # Получаем информацию о статусе рынка
            market_status = self.get_market_status_text()
            
            # Логирование
            logger.info(f"🔍 БАЗОВЫЙ ФИЛЬТР {symbol}:")
            logger.info(f"   💰 Цена: {current_price:.2f} ₽")
            logger.info(f"   📈 EMA20: {current_ema20:.2f} ₽")
            logger.info(f"   📊 Цена > EMA20: {'✅' if price_above_ema else '❌'}")
            logger.info(f"   {market_status['emoji']} Рынок: {market_status['status']} ({market_status['description']})")
            
            return price_above_ema
            
        except Exception as e:
            logger.error(f"Ошибка базового фильтра {symbol}: {e}")
            return False
    
    def _prepare_comprehensive_data(self, df: pd.DataFrame, symbol: str) -> Dict:
        """Подготовка ВСЕХ данных для комплексного GPT анализа"""
        try:
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            volumes = df['volume'].tolist()
            
            # Основные показатели
            current_price = closes[-1]
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
            current_ema20 = ema20[-1]
            
            # Детальный анализ объёмов
            volume_analysis = self._analyze_volumes_detailed(volumes)
            
            # Детальный анализ уровней
            price_levels = self._analyze_price_levels_detailed(df)
            
            # Детальное ценовое движение
            price_movement = self._analyze_price_movement_detailed(closes)
            
            # Свечные данные для GPT (ОГРАНИЧИВАЕМ до 50)
            max_candles = 50
            start_idx = max(0, len(df) - max_candles)
            
            candles_data = []
            for i in range(start_idx, len(df)):
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
                # Основные данные
                'symbol': symbol,
                'current_price': current_price,
                'ema20': current_ema20,
                'price_above_ema': current_price > current_ema20,
                
                # Свечные данные (максимум 50)
                'candles_data': candles_data,
                
                # Детальный анализ объёмов
                'volume_analysis': volume_analysis,
                
                # Детальные уровни
                'price_levels': price_levels,
                
                # Детальное движение цены
                'price_movement': price_movement,
                
                # Контекст времени (теперь без ограничений)
                'trading_session': self.get_current_session(),
                'time_quality': self.get_time_quality(),
                'market_status': self.get_market_status_text(),
                
                # Флаг что базовый фильтр пройден
                'conditions_met': True
            }
            
            logger.info(f"📊 Подготовлены комплексные данные для {symbol} ({len(candles_data)} свечей)")
            return market_data
            
        except Exception as e:
            logger.error(f"Ошибка подготовки комплексных данных для {symbol}: {e}")
            return {}
    
    def _analyze_volumes_detailed(self, volumes: List[int]) -> Dict:
        """Детальный анализ объёмов"""
        try:
            if len(volumes) < 10:
                return {'trend': 'insufficient_data'}
            
            current_volume = volumes[-1]
            
            # Разные периоды сравнения
            avg_5 = np.mean(volumes[-5:]) if len(volumes) >= 5 else current_volume
            avg_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else current_volume  
            avg_50 = np.mean(volumes[-50:]) if len(volumes) >= 50 else current_volume
            
            # Тренды
            recent_vs_medium = avg_5 / avg_20 if avg_20 > 0 else 1.0
            recent_vs_long = avg_5 / avg_50 if avg_50 > 0 else 1.0
            current_vs_avg = current_volume / avg_20 if avg_20 > 0 else 1.0
            
            # Определение тренда
            if recent_vs_medium > 1.3:
                trend = 'strong_increase'
            elif recent_vs_medium > 1.1:
                trend = 'increase'
            elif recent_vs_medium < 0.7:
                trend = 'strong_decrease'
            elif recent_vs_medium < 0.9:
                trend = 'decrease'
            else:
                trend = 'stable'
            
            return {
                'current_volume': current_volume,
                'avg_5': int(avg_5),
                'avg_20': int(avg_20),
                'avg_50': int(avg_50),
                'current_vs_avg': round(current_vs_avg, 2),
                'recent_vs_medium': round(recent_vs_medium, 2),
                'recent_vs_long': round(recent_vs_long, 2),
                'trend': trend,
                'volume_ratio': round(current_vs_avg, 2)  # Для обратной совместимости
            }
            
        except Exception as e:
            logger.error(f"Ошибка анализа объёмов: {e}")
            return {'trend': 'error'}
    
    def _analyze_price_levels_detailed(self, df: pd.DataFrame) -> Dict:
        """Детальный анализ уровней поддержки/сопротивления"""
        try:
            # Используем максимум 50 последних свечей
            recent_data = df.tail(50) if len(df) > 50 else df
            
            highs = recent_data['high'].tolist()
            lows = recent_data['low'].tolist()
            closes = recent_data['close'].tolist()
            
            current_price = closes[-1]
            
            # Поиск локальных максимумов (сопротивления)
            resistances = []
            for i in range(3, len(highs) - 3):  # Увеличили окно
                if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i-3] and
                    highs[i] > highs[i+1] and highs[i] > highs[i+2] and highs[i] > highs[i+3]):
                    if highs[i] > current_price * 1.001:  # Минимум 0.1% выше
                        resistances.append(highs[i])
            
            # Поиск локальных минимумов (поддержки)
            supports = []
            for i in range(3, len(lows) - 3):
                if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i-3] and
                    lows[i] < lows[i+1] and lows[i] < lows[i+2] and lows[i] < lows[i+3]):
                    if lows[i] < current_price * 0.999:  # Минимум 0.1% ниже
                        supports.append(lows[i])
            
            # Сортируем и берем ближайшие
            resistances = sorted(resistances)[:5]  # Ближайшие 5
            supports = sorted(supports, reverse=True)[:5]  # Ближайшие 5
            
            # Общие характеристики диапазона
            recent_high = max(highs)
            recent_low = min(lows)
            range_size = ((recent_high - recent_low) / recent_low) * 100
            
            # Позиция в диапазоне
            position_pct = ((current_price - recent_low) / (recent_high - recent_low)) * 100 if recent_high > recent_low else 50
            
            return {
                'current_price': current_price,
                'nearest_resistance': resistances[0] if resistances else None,
                'nearest_support': supports[0] if supports else None,
                'all_resistances': resistances,
                'all_supports': supports,
                'recent_high': recent_high,
                'recent_low': recent_low,
                'range_size_pct': round(range_size, 2),
                'position_in_range_pct': round(position_pct, 1)
            }
            
        except Exception as e:
            logger.error(f"Ошибка анализа уровней: {e}")
            return {}
    
    def _analyze_price_movement_detailed(self, closes: List[float]) -> Dict:
        """Детальный анализ ценового движения"""
        try:
            if len(closes) < 5:
                return {}
            
            current_price = closes[-1]
            
            # Изменения за разные периоды
            changes = {}
            periods = {'1h': 2, '4h': 5, '12h': 13, '1d': 25, '3d': 75}
            
            for period_name, idx_back in periods.items():
                if len(closes) >= idx_back:
                    old_price = closes[-idx_back]
                    change = ((current_price - old_price) / old_price * 100)
                    changes[f'change_{period_name}'] = round(change, 2)
            
            # Волатильность за разные периоды
            volatilities = {}
            vol_periods = {'1d': 25, '3d': 75, '5d': 125}
            
            for vol_name, vol_back in vol_periods.items():
                if len(closes) >= vol_back:
                    recent_changes = [abs(closes[i] - closes[i-1]) / closes[i-1] * 100 
                                    for i in range(-vol_back, -1)]
                    volatilities[f'volatility_{vol_name}'] = round(np.mean(recent_changes), 2)
            
            # Объединяем результаты
            result = {**changes, **volatilities}
            
            # Дополнительные характеристики
            if len(closes) >= 10:
                # Тренд направленность (сколько из последних 10 свечей растущие)
                up_candles = sum(1 for i in range(-10, -1) if closes[i] > closes[i-1])
                result['trend_strength_pct'] = round((up_candles / 9) * 100, 1)
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка анализа движения: {e}")
            return {}
    
    async def _get_comprehensive_decision(self, market_data: Dict, symbol: str):
        """Получение комплексного решения от GPT"""
        try:
            logger.info(f"🤖 Запрашиваем комплексное GPT решение для {symbol}...")
            
            # Подготавливаем все данные для GPT
            signal_data = {
                # Основные данные
                'price': market_data['current_price'],
                'ema20': market_data['ema20'],
                'price_above_ema': market_data['price_above_ema'],
                'conditions_met': market_data['conditions_met'],
                
                # Детальные данные для анализа
                'volume_analysis': market_data.get('volume_analysis', {}),
                'price_levels': market_data.get('price_levels', {}),
                'trading_session': market_data.get('trading_session', 'unknown'),
                'time_quality': market_data.get('time_quality', 'unknown'),
                'market_status': market_data.get('market_status', {})
            }
            
            # Добавляем движение цены
            if 'price_movement' in market_data:
                signal_data.update(market_data['price_movement'])
            
            # Запрашиваем комплексный анализ у GPT
            gpt_advice = await self.gpt_analyzer.analyze_signal(
                signal_data=signal_data,
                candles_data=market_data.get('candles_data'),
                is_manual_check=False,
                symbol=symbol
            )
            
            if gpt_advice:
                factors_info = f" (факторы: {gpt_advice.key_factors})" if hasattr(gpt_advice, 'key_factors') and gpt_advice.key_factors else ""
                logger.info(f"🤖 GPT комплексное решение для {symbol}: {gpt_advice.recommendation} ({gpt_advice.confidence}%){factors_info}")
                return gpt_advice
            else:
                logger.warning(f"🤖 GPT не дал комплексного решения для {symbol}")
                return None
                
        except Exception as e:
            logger.error(f"Ошибка получения комплексного GPT решения для {symbol}: {e}")
            return None
    
    async def get_detailed_market_status(self, symbol: str) -> str:
        """Получение детального статуса с комплексным анализом (работает в любое время)"""
        try:
            logger.info(f"🔄 Получаем комплексный статус для {symbol}...")
            
            # Получаем статус рынка
            market_status = self.get_market_status_text()
            
            # Получаем информацию о тикере
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                return f"❌ <b>Акция {symbol} не поддерживается</b>"
            
            candles = await asyncio.wait_for(
                self.tinkoff_provider.get_candles_for_ticker(ticker_info['figi'], hours=70),
                timeout=30
            )
            
            if len(candles) < 20:
                return f"""❌ <b>Недостаточно данных для анализа {symbol}</b>

{market_status['emoji']} <b>Статус рынка:</b> {market_status['status']}
📊 {market_status['description']}
💾 {market_status['data_freshness']}

Попробуйте позже."""
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                return f"❌ <b>Ошибка получения данных {symbol}</b>"
            
            # Подготавливаем комплексные данные
            market_data = self._prepare_comprehensive_data(df, symbol)
            
            # Проверяем базовый фильтр
            basic_filter_passed = await self._check_basic_filter(df, symbol)
            
            # Формируем базовое сообщение
            current_price = market_data['current_price']
            current_ema20 = market_data['ema20']
            price_above_ema = current_price > current_ema20
            
            # Получаем время последней свечи
            last_candle_time = df.iloc[-1]['timestamp']
            moscow_time = last_candle_time.astimezone(self.moscow_tz)
            data_age = (datetime.now(self.moscow_tz) - moscow_time).total_seconds() / 3600
            
            data_freshness = ""
            if data_age < 1:
                data_freshness = "✅ Данные свежие"
            elif data_age < 3:
                data_freshness = f"⚠️ Данные {data_age:.1f}ч назад"
            else:
                data_freshness = f"🔴 Данные {data_age:.1f}ч назад"
            
            message = f"""📊 <b>КОМПЛЕКСНЫЙ АНАЛИЗ {symbol}</b>

{market_status['emoji']} <b>Статус рынка:</b> {market_status['status']}
📊 {market_status['description']}
🕐 <b>Последние данные:</b> {moscow_time.strftime('%d.%m %H:%M')} МСК
💾 {data_freshness}

💰 <b>Цена:</b> {current_price:.2f} ₽
📈 <b>EMA20:</b> {current_ema20:.2f} ₽ {'✅' if price_above_ema else '❌'}

🔍 <b>Базовый фильтр:</b> {'✅ Пройден' if basic_filter_passed else '❌ Не пройден'}"""
            
            # Добавляем комплексный GPT анализ
            if self.gpt_analyzer:
                try:
                    logger.info(f"🤖 Запрашиваем комплексный GPT анализ для {symbol}...")
                    
                    gpt_advice = await self._get_comprehensive_decision(market_data, symbol)
                    if gpt_advice:
                        message += f"\n{self.gpt_analyzer.format_advice_for_telegram(gpt_advice, symbol)}"
                    else:
                        message += "\n\n🤖 <i>Комплексный GPT анализ недоступен</i>"
                        
                except Exception as e:
                    logger.error(f"❌ Ошибка GPT анализа для {symbol}: {e}")
                    message += "\n\n🤖 <i>Комплексный GPT анализ недоступен</i>"
            else:
                if basic_filter_passed:
                    message += "\n\n📊 <b>Базовый фильтр пройден</b>\n🤖 <i>GPT анализ недоступен</i>"
                else:
                    message += "\n\n⏳ <b>Ожидаем улучшения условий...</b>"
            
            # Добавляем предупреждение если рынок закрыт
            if not self.is_market_open():
                message += f"\n\n⚠️ <b>Внимание:</b> {market_status['data_freshness']}"
            
            return message
                
        except asyncio.TimeoutError:
            logger.error(f"⏰ Таймаут при получении данных для {symbol}")
            return f"❌ <b>Таймаут при получении данных {symbol}</b>\n\nПопробуйте позже."
        except Exception as e:
            logger.error(f"💥 Ошибка комплексного анализа {symbol}: {e}")
            return f"❌ <b>Ошибка получения данных для анализа {symbol}</b>"
    
    async def check_peak_trend(self, symbol: str) -> Optional[float]:
        """Проверка пика тренда через комплексный GPT анализ (работает в любое время)"""
        try:
            # Получаем данные
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                return None
                
            candles = await self.tinkoff_provider.get_candles_for_ticker(
                ticker_info['figi'], hours=70
            )
            
            if len(candles) < 20:
                return None
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                return None
            
            # Подготавливаем данные для комплексного анализа
            market_data = self._prepare_comprehensive_data(df, symbol)
            current_price = market_data['current_price']
            
            # Специальный анализ для проверки пика
            if self.gpt_analyzer:
                try:
                    signal_data = {
                        # Основные данные
                        'price': current_price,
                        'ema20': market_data['ema20'],
                        'price_above_ema': market_data['price_above_ema'],
                        'conditions_met': True,
                        'check_peak': True,  # Флаг проверки пика
                        
                        # Все данные для комплексного анализа
                        'volume_analysis': market_data.get('volume_analysis', {}),
                        'price_levels': market_data.get('price_levels', {}),
                        'trading_session': market_data.get('trading_session', 'unknown'),
                        'market_status': market_data.get('market_status', {})
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
                    
                    # Проверяем признаки пика
                    is_peak = False
                    
                    # 1. ADX > 45 (если рассчитан)
                    if (gpt_advice and gpt_advice.calculated_adx is not None and 
                        gpt_advice.calculated_adx > 45):
                        is_peak = True
                        logger.info(f"🔥 Пик по ADX {symbol}: {gpt_advice.calculated_adx:.1f} > 45")
                    
                    # 2. GPT рекомендует AVOID из-за пика
                    elif (gpt_advice and gpt_advice.recommendation == 'AVOID' and 
                          gpt_advice.reasoning and 
                          ('пик' in gpt_advice.reasoning.lower() or 'peak' in gpt_advice.reasoning.lower())):
                        is_peak = True
                        logger.info(f"🔥 Пик по GPT анализу {symbol}")
                    
                    # 3. Низкая уверенность + высокая волатильность
                    elif (gpt_advice and gpt_advice.confidence < 40 and 
                          'price_movement' in market_data and 
                          market_data['price_movement'].get('volatility_1d', 0) > 4):
                        is_peak = True
                        logger.info(f"🔥 Пик по волатильности {symbol}")
                    
                    if is_peak:
                        return current_price
                    
                except Exception as e:
                    logger.error(f"Ошибка GPT анализа пика {symbol}: {e}")
                
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
