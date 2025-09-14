import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import pandas as pd
import pytz
from tinkoff.invest import Client, RequestError, CandleInterval, HistoricCandle
from tinkoff.invest.utils import now

logger = logging.getLogger(__name__)

class TinkoffDataProvider:
    """Исправленный data_provider с правильной обработкой времени"""
    
    def __init__(self, token: str):
        self.token = token
        self._client = None
        # Московская временная зона
        self.moscow_tz = pytz.timezone('Europe/Moscow')
    
    async def get_candles_for_ticker(self, figi: str, hours: int = 100) -> List[HistoricCandle]:
        """Получение свечных данных с правильным временем"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                with Client(self.token) as client:
                    # ИСПРАВЛЕНО: используем текущее время для запроса самых свежих данных
                    to_time = now()  # Текущее время UTC
                    from_time = to_time - timedelta(hours=hours)
                    
                    # Логируем время запроса в московском часовом поясе
                    moscow_from = from_time.astimezone(self.moscow_tz)
                    moscow_to = to_time.astimezone(self.moscow_tz)
                    
                    logger.info(f"📊 Запрос данных {figi} за {hours}ч (попытка {attempt + 1})")
                    logger.info(f"🕐 Период МСК: {moscow_from.strftime('%d.%m %H:%M')} - {moscow_to.strftime('%d.%m %H:%M')}")
                    
                    response = client.market_data.get_candles(
                        figi=figi,
                        from_=from_time,
                        to=to_time,
                        interval=CandleInterval.CANDLE_INTERVAL_HOUR
                    )
                    
                    if response.candles:
                        logger.info(f"✅ Получено {len(response.candles)} свечей для {figi}")
                        
                        # Логируем время первой и последней свечи
                        if response.candles:
                            first_candle_moscow = response.candles[0].time.astimezone(self.moscow_tz)
                            last_candle_moscow = response.candles[-1].time.astimezone(self.moscow_tz)
                            logger.info(f"📅 Свечи МСК: {first_candle_moscow.strftime('%d.%m %H:%M')} - {last_candle_moscow.strftime('%d.%m %H:%M')}")
                        
                        return response.candles
                    else:
                        logger.warning(f"⚠️ Пустой ответ от API для {figi}")
                        return []
                        
            except RequestError as e:
                logger.error(f"❌ Ошибка API Tinkoff для {figi} (попытка {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error(f"💥 Все попытки исчерпаны для {figi}")
                    raise
            except Exception as e:
                logger.error(f"💥 Неожиданная ошибка для {figi}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                else:
                    raise
        
        return []
    
    def candles_to_dataframe(self, candles: List[HistoricCandle]) -> pd.DataFrame:
        """Преобразование свечей в DataFrame с улучшенным логированием времени"""
        if not candles:
            logger.warning("📊 Пустой список свечей")
            return pd.DataFrame()
        
        data = []
        valid_candles = 0
        
        logger.info(f"🔍 Обрабатываю {len(candles)} свечей...")
        
        for i, candle in enumerate(candles):
            try:
                # Исправленное преобразование Quotation в float
                open_price = self._quotation_to_float(candle.open)
                high_price = self._quotation_to_float(candle.high)
                low_price = self._quotation_to_float(candle.low)
                close_price = self._quotation_to_float(candle.close)
                
                # Проверка на валидность цен
                if all(price > 0 for price in [open_price, high_price, low_price, close_price]):
                    if low_price <= open_price <= high_price and low_price <= close_price <= high_price:
                        data.append({
                            'timestamp': candle.time,
                            'open': open_price,
                            'high': high_price,
                            'low': low_price,
                            'close': close_price,
                            'volume': candle.volume
                        })
                        valid_candles += 1
                    else:
                        logger.warning(f"🔍 Свеча {i}: неверная логика цен O:{open_price:.2f} H:{high_price:.2f} L:{low_price:.2f} C:{close_price:.2f}")
                else:
                    logger.warning(f"🔍 Свеча {i}: нулевые/отрицательные цены")
                    
            except Exception as e:
                logger.warning(f"🔍 Ошибка обработки свечи {i}: {e}")
                continue
        
        if not data:
            logger.error("❌ Все свечи оказались невалидными!")
            return pd.DataFrame()
        
        logger.info(f"✅ Обработано {valid_candles}/{len(candles)} валидных свечей")
        
        # Создаем DataFrame
        df = pd.DataFrame(data)
        
        # Преобразуем timestamp в datetime с UTC
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        
        # Сортируем по времени
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        # Удаляем дубликаты по времени
        original_len = len(df)
        df = df.drop_duplicates(subset=['timestamp'], keep='last').reset_index(drop=True)
        
        if len(df) < original_len:
            logger.info(f"🔄 Удалено {original_len - len(df)} дубликатов")
        
        # Улучшенное логирование с московским временем
        if not df.empty:
            first_moscow = df.iloc[0]['timestamp'].astimezone(self.moscow_tz)
            last_moscow = df.iloc[-1]['timestamp'].astimezone(self.moscow_tz)
            current_moscow = datetime.now(self.moscow_tz)
            
            logger.info(f"📊 Итоговый DataFrame: {len(df)} записей")
            logger.info(f"📅 Период МСК: {first_moscow.strftime('%d.%m %H:%M')} - {last_moscow.strftime('%d.%m %H:%M')}")
            logger.info(f"🕐 Текущее время МСК: {current_moscow.strftime('%d.%m %H:%M')}")
            logger.info(f"💰 Текущая цена: {df.iloc[-1]['close']:.2f} ₽")
            logger.info(f"📈 Диапазон: {df['close'].min():.2f} - {df['close'].max():.2f} ₽")
            
            # Проверяем актуальность данных
            time_diff = (current_moscow.replace(tzinfo=None) - last_moscow.replace(tzinfo=None)).total_seconds() / 3600
            
            if time_diff > 2:
                logger.warning(f"⚠️ ВНИМАНИЕ: Данные устарели на {time_diff:.1f} часов!")
                logger.warning(f"   Последняя свеча: {last_moscow.strftime('%d.%m %H:%M')} МСК")
                logger.warning(f"   Текущее время: {current_moscow.strftime('%d.%m %H:%M')} МСК")
            else:
                logger.info(f"✅ Данные свежие (задержка {time_diff:.1f}ч)")
            
            # Показываем последние 3 свечи с московским временем
            logger.info("🔍 ПОСЛЕДНИЕ 3 СВЕЧИ (МСК):")
            for i in range(max(0, len(df) - 3), len(df)):
                row = df.iloc[i]
                moscow_time = row['timestamp'].astimezone(self.moscow_tz)
                logger.info(f"🔍 [{i:2d}] {moscow_time.strftime('%d.%m %H:%M')} "
                           f"O:{row['open']:6.2f} H:{row['high']:6.2f} L:{row['low']:6.2f} C:{row['close']:6.2f} "
                           f"V:{row['volume']:,}")
        
        return df
    
    def _quotation_to_float(self, quotation) -> float:
        """Преобразование Quotation в float"""
        try:
            if quotation is None:
                return 0.0
            
            if hasattr(quotation, 'units') and hasattr(quotation, 'nano'):
                result = float(quotation.units) + float(quotation.nano) / 1_000_000_000
                
                if 0.01 <= result <= 100_000:
                    return result
                else:
                    logger.warning(f"🔍 Подозрительная цена: {result}")
                    return result
            else:
                try:
                    return float(quotation) if quotation else 0.0
                except (ValueError, TypeError):
                    logger.error(f"🔍 Не могу преобразовать в float: {quotation}")
                    return 0.0
                
        except Exception as e:
            logger.warning(f"🔍 Ошибка преобразования quotation: {e}")
            try:
                return float(quotation) if quotation else 0.0
            except:
                return 0.0
    
    async def get_current_price(self, figi: str) -> Optional[float]:
        """Получение текущей цены"""
        try:
            logger.info(f"💰 Запрос текущей цены для {figi}")
            candles = await self.get_candles_for_ticker(figi, hours=3)
            
            if candles:
                df = self.candles_to_dataframe(candles)
                if not df.empty:
                    current_price = float(df.iloc[-1]['close'])
                    logger.info(f"✅ Текущая цена {figi}: {current_price:.2f} ₽")
                    return current_price
            
            logger.warning(f"⚠️ Не удалось получить текущую цену для {figi}")
            return None
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения цены для {figi}: {e}")
            return None
    
    # Метод для обратной совместимости
    async def get_candles(self, hours: int = 100) -> List[HistoricCandle]:
        """УСТАРЕВШИЙ: Получение свечных данных для SBER"""
        logger.warning("⚠️ Используется устаревший метод get_candles()")
        return await self.get_candles_for_ticker("BBG004730N88", hours)
    
    async def test_connection(self) -> bool:
        """Тест подключения к API с проверкой времени"""
        try:
            logger.info("🔗 Тестирую подключение к Tinkoff API...")
            
            with Client(self.token) as client:
                accounts = client.users.get_accounts()
                logger.info(f"✅ Подключение успешно, аккаунтов: {len(accounts.accounts)}")
                
                # Проверяем время сервера
                current_time_utc = now()
                current_time_moscow = current_time_utc.astimezone(self.moscow_tz)
                logger.info(f"🕐 Время сервера Tinkoff (МСК): {current_time_moscow.strftime('%d.%m.%Y %H:%M:%S')}")
                
                # Тест получения данных
                test_candles = await self.get_candles_for_ticker("BBG004730N88", hours=5)
                logger.info(f"✅ Тестовые данные: {len(test_candles)} свечей")
                
                return True
                
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Tinkoff API: {e}")
            return False
    
    async def get_ticker_info(self, figi: str) -> Optional[dict]:
        """Получение информации о тикере"""
        try:
            with Client(self.token) as client:
                response = client.instruments.share_by(
                    id_type=1,
                    class_code="",
                    id=figi
                )
                
                if response.instrument:
                    instrument = response.instrument
                    return {
                        'figi': instrument.figi,
                        'ticker': instrument.ticker,
                        'name': instrument.name,
                        'currency': instrument.currency,
                        'lot': instrument.lot,
                        'trading_status': instrument.trading_status.name if hasattr(instrument.trading_status, 'name') else str(instrument.trading_status)
                    }
                
        except Exception as e:
            logger.error(f"❌ Ошибка получения информации о тикере {figi}: {e}")
        
        return None
