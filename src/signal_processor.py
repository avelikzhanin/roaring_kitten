import asyncio
import logging
from datetime import datetime, time
import pytz
from typing import Optional, Dict, List
import pandas as pd
import numpy as np
from dataclasses import dataclass

from .indicators import TechnicalIndicators, quick_market_summary

logger = logging.getLogger(__name__)

@dataclass
class TradingSignal:
    """Структура торгового сигнала с точными ADX данными"""
    symbol: str
    timestamp: datetime
    price: float
    ema20: float
    
    # ТОЧНЫЕ ADX данные как в Tinkoff терминале
    adx: float = 0.0
    plus_di: float = 0.0
    minus_di: float = 0.0
    
    # GPT данные
    gpt_recommendation: Optional[str] = None
    gpt_confidence: Optional[int] = None
    gpt_full_advice: Optional[object] = None  # Полный GPT объект

class SignalProcessor:
    """Обработчик сигналов с точными ADX расчетами как в Tinkoff"""
    
    def __init__(self, tinkoff_provider, database, gpt_analyzer=None):
        self.tinkoff_provider = tinkoff_provider
        self.db = database
        self.gpt_analyzer = gpt_analyzer
        self.moscow_tz = pytz.timezone('Europe/Moscow')
        
        analysis_type = "✅ Комплексный анализ с GPT + точные ADX" if gpt_analyzer else "❌ Только базовый фильтр + точные ADX"
        logger.info(f"🔄 SignalProcessor инициализирован ({analysis_type})")
        logger.info("📊 ADX настройки: DI период=14, ADX сглаживание=20 (как в Tinkoff)")
    
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
        """Комплексный анализ с ТОЧНЫМИ ADX как в Tinkoff терминале"""
        try:
            logger.info(f"🔍 КОМПЛЕКСНЫЙ АНАЛИЗ {symbol} - точные ADX + GPT")
            
            # Получаем информацию о тикере
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                logger.error(f"Тикер {symbol} не найден в БД")
                return None
            
            # Получаем свечи (увеличиваем до 100 часов для точных ADX расчетов)
            candles = await self.tinkoff_provider.get_candles_for_ticker(
                ticker_info['figi'], hours=100
            )
            
            if len(candles) < 50:  # Нужно больше данных для точного ADX
                logger.warning(f"Недостаточно данных для точного ADX {symbol}: {len(candles)} свечей")
                return None
            
            logger.info(f"📈 Получено {len(candles)} свечей для точного ADX анализа")
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                logger.error(f"Пустой DataFrame для {symbol}")
                return None
            
            # ЭТАП 1: ТОЧНЫЙ РАСЧЕТ ИНДИКАТОРОВ
            logger.info(f"📊 Рассчитываем точные индикаторы для {symbol}...")
            market_summary = quick_market_summary(df.to_dict('records'))
            
            if 'error' in market_summary:
                logger.error(f"Ошибка расчета индикаторов для {symbol}: {market_summary['error']}")
                return None
            
            # Отладочная информация ADX
            if 'adx_debug' in market_summary:
                debug = market_summary['adx_debug']
                logger.info(f"🔍 ADX отладка {symbol}: данных={debug['data_length']}, ADX массив={debug['adx_array_length']}")
                logger.info(f"🔍 Сырые значения: ADX={debug['raw_adx']}, +DI={debug['raw_plus_di']}, -DI={debug['raw_minus_di']}")
                logger.info(f"🔍 Итоговые: ADX={market_summary['adx']:.1f}, рассчитан={market_summary['adx_calculated']}")
            
            # ЭТАП 2: БАЗОВЫЙ ФИЛЬТР с точными ADX
            if not await self._check_basic_filter_with_adx(market_summary, symbol):
                logger.info(f"⏳ Базовый фильтр не пройден для {symbol}")
                return None
            
            logger.info(f"✅ Базовый фильтр пройден для {symbol}")
            
            # ЭТАП 3: ПОДГОТОВКА ДАННЫХ ДЛЯ GPT
            market_data = self._prepare_comprehensive_data_with_adx(df, market_summary, symbol)
            
            # ЭТАП 4: КОМПЛЕКСНЫЙ АНАЛИЗ ЧЕРЕЗ GPT (с готовыми ADX)
            if self.gpt_analyzer:
                gpt_advice = await self._get_comprehensive_decision(market_data, symbol)
                
                if gpt_advice and gpt_advice.recommendation in ['BUY', 'WEAK_BUY']:
                    # GPT рекомендует покупку - создаём сигнал с ТОЧНЫМИ ADX
                    signal = TradingSignal(
                        symbol=symbol,
                        timestamp=df.iloc[-1]['timestamp'],
                        price=market_summary['current_price'],
                        ema20=market_summary['ema20'],
                        # ТОЧНЫЕ ADX значения как в терминале
                        adx=market_summary['adx'],
                        plus_di=market_summary['plus_di'],
                        minus_di=market_summary['minus_di'],
                        # GPT данные
                        gpt_recommendation=gpt_advice.recommendation,
                        gpt_confidence=gpt_advice.confidence,
                        gpt_full_advice=gpt_advice
                    )
                    
                    logger.info(f"🎉 GPT РЕКОМЕНДУЕТ {gpt_advice.recommendation} для {symbol}")
                    logger.info(f"📊 ТОЧНЫЕ ADX: {signal.adx:.1f}, +DI: {signal.plus_di:.1f}, -DI: {signal.minus_di:.1f}")
                    return signal
                else:
                    rec = gpt_advice.recommendation if gpt_advice else 'НЕИЗВЕСТНО'
                    conf = f" ({gpt_advice.confidence}%)" if gpt_advice else ""
                    logger.info(f"⏳ GPT не рекомендует покупку {symbol}: {rec}{conf}")
                    return None
            else:
                # Работаем без GPT - создаём сигнал только по техническим условиям
                logger.warning("🤖 GPT недоступен, используем только технические индикаторы")
                signal = TradingSignal(
                    symbol=symbol,
                    timestamp=df.iloc[-1]['timestamp'],
                    price=market_summary['current_price'],
                    ema20=market_summary['ema20'],
                    # ТОЧНЫЕ ADX значения
                    adx=market_summary['adx'],
                    plus_di=market_summary['plus_di'],
                    minus_di=market_summary['minus_di']
                )
                return signal
            
        except Exception as e:
            logger.error(f"Ошибка комплексного анализа {symbol}: {e}")
            return None
    
    async def _check_basic_filter_with_adx(self, market_summary: Dict, symbol: str) -> bool:
        """Базовый фильтр: цена > EMA20 + ADX условия"""
        try:
            current_price = market_summary.get('current_price', 0)
            current_ema20 = market_summary.get('ema20', 0)
            current_adx = market_summary.get('adx', 0)
            current_plus_di = market_summary.get('plus_di', 0)
            current_minus_di = market_summary.get('minus_di', 0)
            adx_calculated = market_summary.get('adx_calculated', False)
            
            # Получаем информацию о статусе рынка
            market_status = self.get_market_status_text()
            
            # Проверяем основные условия
            price_above_ema = current_price > current_ema20
            strong_trend = current_adx > 25 if adx_calculated else False
            positive_direction = current_plus_di > current_minus_di if adx_calculated else False
            di_difference = (current_plus_di - current_minus_di) > 1 if adx_calculated else False
            
            # Логирование
            logger.info(f"🔍 БАЗОВЫЙ ФИЛЬТР {symbol} (точные ADX как в Tinkoff):")
            logger.info(f"   💰 Цена: {current_price:.2f} ₽")
            logger.info(f"   📈 EMA20: {current_ema20:.2f} ₽")
            logger.info(f"   📊 Цена > EMA20: {'✅' if price_above_ema else '❌'}")
            
            if adx_calculated:
                logger.info(f"   📊 ADX: {current_adx:.1f} {'✅' if strong_trend else '❌'} (норма >25)")
                logger.info(f"   📊 +DI: {current_plus_di:.1f}")
                logger.info(f"   📊 -DI: {current_minus_di:.1f} {'✅' if positive_direction else '❌'}")
                logger.info(f"   📊 Разница DI: {current_plus_di - current_minus_di:+.1f} {'✅' if di_difference else '❌'} (норма >1)")
            else:
                logger.warning(f"   📊 ADX не рассчитан (недостаточно данных)")
            
            logger.info(f"   {market_status['emoji']} Рынок: {market_status['status']} ({market_status['description']})")
            
            # Для генерации сигнала нужны ВСЕ условия (включая ADX)
            if adx_calculated:
                all_conditions = price_above_ema and strong_trend and positive_direction and di_difference
                logger.info(f"   🎯 Все условия: {'✅' if all_conditions else '❌'} ({sum([price_above_ema, strong_trend, positive_direction, di_difference])}/4)")
                return all_conditions
            else:
                # Если ADX не рассчитан, проверяем только цену > EMA20
                logger.info(f"   🎯 Базовое условие: {'✅' if price_above_ema else '❌'} (только EMA20, ADX недоступен)")
                return price_above_ema
            
        except Exception as e:
            logger.error(f"Ошибка базового фильтра {symbol}: {e}")
            return False
    
    def _prepare_comprehensive_data_with_adx(self, df: pd.DataFrame, market_summary: Dict, symbol: str) -> Dict:
        """Подготовка данных для GPT с готовыми ТОЧНЫМИ ADX"""
        try:
            # Свечные данные для GPT (ограничиваем до 50)
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
            
            # Детальный анализ объёмов
            volumes = df['volume'].tolist()
            volume_analysis = self._analyze_volumes_detailed(volumes)
            
            # Детальный анализ уровней
            price_levels = self._analyze_price_levels_detailed(df)
            
            # Детальное ценовое движение
            closes = df['close'].tolist()
            price_movement = self._analyze_price_movement_detailed(closes)
            
            market_data = {
                # Основные данные
                'symbol': symbol,
                'current_price': market_summary['current_price'],
                'ema20': market_summary['ema20'],
                'price_above_ema': market_summary['price_above_ema'],
                
                # ГОТОВЫЕ ТОЧНЫЕ ADX значения (не для расчета GPT!)
                'calculated_adx': market_summary['adx'],
                'calculated_plus_di': market_summary['plus_di'],
                'calculated_minus_di': market_summary['minus_di'],
                'adx_calculated': market_summary['adx_calculated'],
                
                # Свечные данные (максимум 50)
                'candles_data': candles_data,
                
                # Детальный анализ
                'volume_analysis': volume_analysis,
                'price_levels': price_levels,
                'price_movement': price_movement,
                
                # Контекст времени
                'trading_session': self.get_current_session(),
                'time_quality': self.get_time_quality(),
                'market_status': self.get_market_status_text(),
                
                # Флаг что базовый фильтр пройден
                'conditions_met': True
            }
            
            logger.info(f"📊 Подготовлены данные для GPT с точными ADX {symbol} ({len(candles_data)} свечей)")
            return market_data
            
        except Exception as e:
            logger.error(f"Ошибка подготовки данных для {symbol}: {e}")
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
                'volume_ratio': round(current_vs_avg, 2)
            }
            
        except Exception as e:
            logger.error(f"Ошибка анализа объёмов: {e}")
            return {'trend': 'error'}
    
    def _analyze_price_levels_detailed(self, df: pd.DataFrame) -> Dict:
        """Детальный анализ уровней поддержки/сопротивления"""
        try:
            recent_data = df.tail(50) if len(df) > 50 else df
            
            highs = recent_data['high'].tolist()
            lows = recent_data['low'].tolist()
            closes = recent_data['close'].tolist()
            
            current_price = closes[-1]
            
            # Поиск уровней
            resistances = []
            supports = []
            
            for i in range(3, len(highs) - 3):
                if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i-3] and
                    highs[i] > highs[i+1] and highs[i] > highs[i+2] and highs[i] > highs[i+3]):
                    if highs[i] > current_price * 1.001:
                        resistances.append(highs[i])
            
            for i in range(3, len(lows) - 3):
                if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i-3] and
                    lows[i] < lows[i+1] and lows[i] < lows[i+2] and lows[i] < lows[i+3]):
                    if lows[i] < current_price * 0.999:
                        supports.append(lows[i])
            
            resistances = sorted(resistances)[:5]
            supports = sorted(supports, reverse=True)[:5]
            
            recent_high = max(highs)
            recent_low = min(lows)
            range_size = ((recent_high - recent_low) / recent_low) * 100
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
            changes = {}
            periods = {'1h': 2, '4h': 5, '12h': 13, '1d': 25, '3d': 75}
            
            for period_name, idx_back in periods.items():
                if len(closes) >= idx_back:
                    old_price = closes[-idx_back]
                    change = ((current_price - old_price) / old_price * 100)
                    changes[f'change_{period_name}'] = round(change, 2)
            
            volatilities = {}
            vol_periods = {'1d': 25, '3d': 75, '5d': 125}
            
            for vol_name, vol_back in vol_periods.items():
                if len(closes) >= vol_back:
                    recent_changes = [abs(closes[i] - closes[i-1]) / closes[i-1] * 100 
                                    for i in range(-vol_back, -1)]
                    volatilities[f'volatility_{vol_name}'] = round(np.mean(recent_changes), 2)
            
            result = {**changes, **volatilities}
            
            if len(closes) >= 10:
                up_candles = sum(1 for i in range(-10, -1) if closes[i] > closes[i-1])
                result['trend_strength_pct'] = round((up_candles / 9) * 100, 1)
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка анализа движения: {e}")
            return {}
    
    async def _get_comprehensive_decision(self, market_data: Dict, symbol: str):
        """Получение решения от GPT с готовыми точными ADX"""
        try:
            logger.info(f"🤖 Запрашиваем GPT решение для {symbol} с готовыми ADX...")
            
            signal_data = {
                # Основные данные
                'price': market_data['current_price'],
                'ema20': market_data['ema20'],
                'price_above_ema': market_data['price_above_ema'],
                'conditions_met': market_data['conditions_met'],
                
                # ГОТОВЫЕ точные ADX (не для расчета!)
                'ready_adx': market_data['calculated_adx'],
                'ready_plus_di': market_data['calculated_plus_di'],
                'ready_minus_di': market_data['calculated_minus_di'],
                'adx_available': market_data['adx_calculated'],
                
                # Детальные данные
                'volume_analysis': market_data.get('volume_analysis', {}),
                'price_levels': market_data.get('price_levels', {}),
                'trading_session': market_data.get('trading_session', 'unknown'),
                'time_quality': market_data.get('time_quality', 'unknown'),
                'market_status': market_data.get('market_status', {})
            }
            
            if 'price_movement' in market_data:
                signal_data.update(market_data['price_movement'])
            
            # Запрашиваем анализ у GPT
            gpt_advice = await self.gpt_analyzer.analyze_signal(
                signal_data=signal_data,
                candles_data=market_data.get('candles_data'),
                is_manual_check=False,
                symbol=symbol
            )
            
            if gpt_advice:
                factors_info = f" (факторы: {gpt_advice.key_factors})" if hasattr(gpt_advice, 'key_factors') and gpt_advice.key_factors else ""
                logger.info(f"🤖 GPT решение для {symbol}: {gpt_advice.recommendation} ({gpt_advice.confidence}%){factors_info}")
                return gpt_advice
            else:
                logger.warning(f"🤖 GPT не дал решения для {symbol}")
                return None
                
        except Exception as e:
            logger.error(f"Ошибка получения GPT решения для {symbol}: {e}")
            return None
    
    async def get_detailed_market_status(self, symbol: str) -> str:
        """Получение детального статуса с точными ADX"""
        try:
            logger.info(f"🔄 Получаем статус {symbol} с точными ADX...")
            
            market_status = self.get_market_status_text()
            
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                return f"❌ <b>Акция {symbol} не поддерживается</b>"
            
            candles = await asyncio.wait_for(
                self.tinkoff_provider.get_candles_for_ticker(ticker_info['figi'], hours=100),
                timeout=30
            )
            
            if len(candles) < 50:
                return f"""❌ <b>Недостаточно данных для точного ADX анализа {symbol}</b>

{market_status['emoji']} <b>Статус рынка:</b> {market_status['status']}
📊 {market_status['description']}
💾 {market_status['data_freshness']}

Нужно минимум 50 свечей для расчета ADX."""
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                return f"❌ <b>Ошибка получения данных {symbol}</b>"
            
            # Рассчитываем точные индикаторы
            logger.info(f"📊 Рассчитываем индикаторы для {symbol}...")
            market_summary = quick_market_summary(df.to_dict('records'))
            
            if 'error' in market_summary:
                logger.error(f"Ошибка расчета индикаторов для {symbol}: {market_summary['error']}")
                return f"❌ <b>Ошибка расчета индикаторов {symbol}</b>"
            
            # Выводим отладочную информацию ADX
            if 'adx_debug' in market_summary:
                debug = market_summary['adx_debug']
                logger.info(f"🔍 ADX отладка для {symbol}:")
                logger.info(f"   Длина данных: {debug['data_length']}")
                logger.info(f"   Длина ADX массива: {debug['adx_array_length']}")
                logger.info(f"   Сырой ADX: {debug['raw_adx']}")
                logger.info(f"   Последние 5 ADX: {debug['last_5_adx']}")
                logger.info(f"   ADX рассчитан: {market_summary['adx_calculated']}")
                logger.info(f"   Итоговый ADX: {market_summary['adx']}")
            
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
            
            # Формируем сообщение с точными ADX
            current_price = market_summary['current_price']
            current_ema20 = market_summary['ema20']
            price_above_ema = current_price > current_ema20
            
            current_adx = market_summary['adx']
            current_plus_di = market_summary['plus_di']
            current_minus_di = market_summary['minus_di']
            adx_calculated = market_summary['adx_calculated']
            
            # Проверяем базовый фильтр с ADX
            basic_filter_passed = await self._check_basic_filter_with_adx(market_summary, symbol)
            
            message = f"""📊 <b>КОМПЛЕКСНЫЙ АНАЛИЗ {symbol}</b>

{market_status['emoji']} <b>Статус рынка:</b> {market_status['status']}
📊 {market_status['description']}
🕐 <b>Последние данные:</b> {moscow_time.strftime('%d.%m %H:%M')} МСК
💾 {data_freshness}

💰 <b>Цена:</b> {current_price:.2f} ₽
📈 <b>EMA20:</b> {current_ema20:.2f} ₽ {'✅' if price_above_ema else '❌'}"""

            if adx_calculated:
                adx_status = "🟢 Сильный" if current_adx > 25 else "🔴 Слабый"
                di_diff = current_plus_di - current_minus_di
                di_status = "🟢 Восходящий" if di_diff > 1 else "🔴 Нисходящий"
                
                message += f"""

📊 <b>ТОЧНЫЕ ADX (как в Tinkoff):</b>
• <b>ADX:</b> {current_adx:.1f} {adx_status} тренд
• <b>+DI:</b> {current_plus_di:.1f}
• <b>-DI:</b> {current_minus_di:.1f}
• <b>Направление:</b> {di_status} (разница: {di_diff:+.1f})"""
            else:
                message += f"""

📊 <b>ADX:</b> ❌ Не рассчитан (недостаточно данных)"""
            
            message += f"""

🔍 <b>Базовый фильтр:</b> {'✅ Пройден' if basic_filter_passed else '❌ Не пройден'}"""
            
            # Добавляем GPT анализ
            if self.gpt_analyzer:
                try:
                    market_data = self._prepare_comprehensive_data_with_adx(df, market_summary, symbol)
                    gpt_advice = await self._get_comprehensive_decision(market_data, symbol)
                    if gpt_advice:
                        message += f"\n{self.gpt_analyzer.format_advice_for_telegram(gpt_advice, symbol)}"
                    else:
                        message += "\n\n🤖 <i>GPT анализ недоступен</i>"
                        
                except Exception as e:
                    logger.error(f"❌ Ошибка GPT анализа для {symbol}: {e}")
                    message += "\n\n🤖 <i>GPT анализ недоступен</i>"
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
            logger.error(f"💥 Ошибка анализа {symbol}: {e}")
            return f"❌ <b>Ошибка получения данных для анализа {symbol}</b>"
    
    async def check_peak_trend(self, symbol: str) -> Optional[float]:
        """Проверка пика тренда с точными ADX"""
        try:
            ticker_info = await self.db.get_ticker_info(symbol)
            if not ticker_info:
                return None
                
            candles = await self.tinkoff_provider.get_candles_for_ticker(
                ticker_info['figi'], hours=100
            )
            
            if len(candles) < 50:
                return None
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            if df.empty:
                return None
            
            # Рассчитываем точные ADX
            market_summary = quick_market_summary(df.to_dict('records'))
            current_price = market_summary['current_price']
            current_adx = market_summary['adx']
            adx_calculated = market_summary['adx_calculated']
            
            # Проверяем пик по точному ADX
            if adx_calculated and current_adx > 45:
                logger.info(f"🔥 Пик тренда {symbol}: точный ADX {current_adx:.1f} > 45")
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
