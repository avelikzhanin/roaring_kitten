import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import pandas as pd
from tinkoff.invest import Client, RequestError, CandleInterval, HistoricCandle
from tinkoff.invest.utils import now

logger = logging.getLogger(__name__)

class TinkoffDataProvider:
    """Класс для получения данных через Tinkoff Invest API - исправленная версия"""
    
    def __init__(self, token: str):
        self.token = token
        self._client = None
    
    async def get_candles_for_ticker(self, figi: str, hours: int = 100) -> List[HistoricCandle]:
        """Получение свечных данных для конкретного тикера по FIGI"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                with Client(self.token) as client:
                    to_time = now()
                    from_time = to_time - timedelta(hours=hours)
                    
                    logger.info(f"📊 Запрос данных {figi} за {hours}ч (попытка {attempt + 1})")
                    
                    response = client.market_data.get_candles(
                        figi=figi,
                        from_=from_time,
                        to=to_time,
                        interval=CandleInterval.CANDLE_INTERVAL_HOUR
                    )
                    
                    if response.candles:
                        logger.info(f"✅ Получено {len(response.candles)} свечей для {figi}")
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
    
    # Метод для обратной совместимости со старым кодом
    async def get_candles(self, hours: int = 100) -> List[HistoricCandle]:
        """УСТАРЕВШИЙ: Получение свечных данных для SBER (для совместимости)"""
        logger.warning("⚠️ Используется устаревший метод get_candles(). Используйте get_candles_for_ticker()")
        return await self.get_candles_for_ticker("BBG004730N88", hours)  # SBER FIGI
    
    def candles_to_dataframe(self, candles: List[HistoricCandle]) -> pd.DataFrame:
        """Преобразование свечей в DataFrame - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        if not candles:
            logger.warning("📊 Пустой список свечей")
            return pd.DataFrame()
        
        data = []
        valid_candles = 0
        
        logger.info(f"🔍 Обрабатываю {len(candles)} свечей...")
        
        for i, candle in enumerate(candles):
            try:
                # ИСПРАВЛЕННОЕ преобразование Quotation в float
                open_price = self._quotation_to_float(candle.open)
                high_price = self._quotation_to_float(candle.high)
                low_price = self._quotation_to_float(candle.low)
                close_price = self._quotation_to_float(candle.close)
                
                # Проверка на валидность цен
                if all(price > 0 for price in [open_price, high_price, low_price, close_price]):
                    # Проверка логики цен (low <= open,close <= high)
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
                    logger.warning(f"🔍 Свеча {i}: нулевые/отрицательные цены O:{open_price:.2f} H:{high_price:.2f} L:{low_price:.2f} C:{close_price:.2f}")
                    
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
        
        # Удаляем дубликаты по времени, оставляя последний
        original_len = len(df)
        df = df.drop_duplicates(subset=['timestamp'], keep='last').reset_index(drop=True)
        
        if len(df) < original_len:
            logger.info(f"🔄 Удалено {original_len - len(df)} дубликатов")
        
        # Логируем финальную информацию
        if not df.empty:
            logger.info(f"📊 Итоговый DataFrame: {len(df)} записей")
            logger.info(f"📅 Период: {df.iloc[0]['timestamp'].strftime('%H:%M %d.%m')} - {df.iloc[-1]['timestamp'].strftime('%H:%M %d.%m')}")
            logger.info(f"💰 Текущая цена: {df.iloc[-1]['close']:.2f} ₽")
            logger.info(f"📈 Диапазон: {df['close'].min():.2f} - {df['close'].max():.2f} ₽")
            
            # Показываем последние 3 свечи для контроля
            logger.info("🔍 ПОСЛЕДНИЕ 3 СВЕЧИ:")
            for i in range(max(0, len(df) - 3), len(df)):
                row = df.iloc[i]
                logger.info(f"🔍 [{i:2d}] {row['timestamp'].strftime('%H:%M %d.%m')} "
                           f"O:{row['open']:6.2f} H:{row['high']:6.2f} L:{row['low']:6.2f} C:{row['close']:6.2f} "
                           f"V:{row['volume']:,}")
        
        return df
    
    def _quotation_to_float(self, quotation) -> float:
        """ИСПРАВЛЕННОЕ преобразование Quotation в float"""
        try:
            if quotation is None:
                logger.warning("🔍 Quotation is None")
                return 0.0
            
            # Проверяем наличие атрибутов units и nano
            if hasattr(quotation, 'units') and hasattr(quotation, 'nano'):
                units = quotation.units
                nano = quotation.nano
                
                # Основная формула: units + nano/10^9
                result = float(units) + float(nano) / 1_000_000_000
                
                # Проверка на разумность значения для российских акций
                if 0.01 <= result <= 100_000:  # от копейки до 100к рублей
                    return result
                else:
                    logger.warning(f"🔍 Подозрительная цена: units={units}, nano={nano}, result={result}")
                    # Возвращаем все равно, может это валютная цена
                    return result
            else:
                # Fallback: пытаемся привести к float напрямую
                logger.warning(f"🔍 Quotation без units/nano: {type(quotation)}, value={quotation}")
                try:
                    return float(quotation) if quotation else 0.0
                except (ValueError, TypeError):
                    logger.error(f"🔍 Не могу преобразовать в float: {quotation}")
                    return 0.0
                
        except (AttributeError, TypeError, ValueError) as e:
            logger.warning(f"🔍 Ошибка преобразования quotation: {e}")
            logger.warning(f"🔍 Тип quotation: {type(quotation)}")
            logger.warning(f"🔍 Значение: {quotation}")
            
            # Последняя попытка
            try:
                return float(quotation) if quotation else 0.0
            except:
                return 0.0
    
    # Для обратной совместимости со старым кодом
    @staticmethod
    def quotation_to_decimal(quotation) -> float:
        """УСТАРЕВШИЙ метод - используйте _quotation_to_float"""
        logger.warning("⚠️ Используется устаревший метод quotation_to_decimal")
        provider = TinkoffDataProvider("dummy")
        return provider._quotation_to_float(quotation)
    
    async def get_current_price(self, figi: str) -> Optional[float]:
        """Получение текущей цены для тикера"""
        try:
            logger.info(f"💰 Запрос текущей цены для {figi}")
            candles = await self.get_candles_for_ticker(figi, hours=3)  # Последние 3 часа
            
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
    
    async def get_multiple_candles(self, tickers_figi: List[str], hours: int = 100) -> dict:
        """Получение свечных данных для нескольких тикеров одновременно"""
        results = {}
        
        for figi in tickers_figi:
            try:
                logger.info(f"📊 Запрос данных для {figi}")
                candles = await self.get_candles_for_ticker(figi, hours)
                results[figi] = candles
                
                # Небольшая пауза между запросами
                await asyncio.sleep(0.3)
                
            except Exception as e:
                logger.error(f"❌ Ошибка получения данных для {figi}: {e}")
                results[figi] = []
        
        return results
    
    async def test_connection(self) -> bool:
        """Тест подключения к API"""
        try:
            logger.info("🔗 Тестирую подключение к Tinkoff API...")
            
            with Client(self.token) as client:
                # Получаем информацию об аккаунте
                accounts = client.users.get_accounts()
                logger.info(f"✅ Подключение успешно, аккаунтов: {len(accounts.accounts)}")
                
                # Тестируем получение данных по SBER
                test_candles = await self.get_candles_for_ticker("BBG004730N88", hours=5)
                logger.info(f"✅ Тестовые данные: {len(test_candles)} свечей")
                
                # Проверяем преобразование
                if test_candles:
                    df = self.candles_to_dataframe(test_candles)
                    logger.info(f"✅ Тестовый DataFrame: {len(df)} записей")
                
                return True
                
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Tinkoff API: {e}")
            return False
    
    async def get_ticker_info(self, figi: str) -> Optional[dict]:
        """Получение информации о тикере через API"""
        try:
            with Client(self.token) as client:
                response = client.instruments.share_by(
                    id_type=1,  # По FIGI
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
    
    async def validate_figis(self, figis: List[str]) -> dict:
        """Проверка валидности FIGI кодов"""
        results = {}
        
        for figi in figis:
            ticker_info = await self.get_ticker_info(figi)
            results[figi] = {
                'valid': ticker_info is not None,
                'info': ticker_info
            }
            await asyncio.sleep(0.1)  # Небольшая пауза
        
        return results
