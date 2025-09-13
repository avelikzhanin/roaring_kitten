import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import pandas as pd
from tinkoff.invest import Client, RequestError, CandleInterval, HistoricCandle
from tinkoff.invest.utils import now

logger = logging.getLogger(__name__)

class TinkoffDataProvider:
    """Класс для получения данных через Tinkoff Invest API"""
    
    def __init__(self, token: str):
        self.token = token
        self._client = None
    
    async def get_candles(self, hours: int = 100) -> List[HistoricCandle]:
        """УСТАРЕВШИЙ: Получение свечных данных для SBER (для совместимости)"""
        logger.warning("⚠️ Используется устаревший метод get_candles(). Используйте get_candles_for_ticker()")
        return await self.get_candles_for_ticker("BBG004730N88", hours)  # SBER FIGI
    
    async def get_candles_for_ticker(self, figi: str, hours: int = 100) -> List[HistoricCandle]:
        """Получение свечных данных для конкретного тикера по FIGI"""
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                with Client(self.token) as client:
                    to_time = now()
                    from_time = to_time - timedelta(hours=hours)
                    
                    logger.info(f"📊 Запрос {hours}ч данных {figi}")
                    
                    response = client.market_data.get_candles(
                        figi=figi,
                        from_=from_time,
                        to=to_time,
                        interval=CandleInterval.CANDLE_INTERVAL_HOUR
                    )
                    
                    if response.candles:
                        logger.info(f"✅ Получено {len(response.candles)} свечей")
                        return response.candles
                    else:
                        logger.warning(f"Пустой ответ от API для {figi}")
                        return []
                        
            except RequestError as e:
                logger.error(f"Ошибка API Tinkoff для {figi} (попытка {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise
            except Exception as e:
                logger.error(f"Ошибка получения данных {figi}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                else:
                    raise
        
        return []
    
    async def get_multiple_candles(self, tickers_figi: List[str], hours: int = 100) -> dict:
        """Получение свечных данных для нескольких тикеров одновременно"""
        results = {}
        
        for figi in tickers_figi:
            try:
                candles = await self.get_candles_for_ticker(figi, hours)
                results[figi] = candles
                await asyncio.sleep(0.5)  # Пауза между запросами
            except Exception as e:
                logger.error(f"Ошибка получения данных для {figi}: {e}")
                results[figi] = []
        
        return results
    
    def candles_to_dataframe(self, candles: List[HistoricCandle]) -> pd.DataFrame:
        """Преобразование свечей в DataFrame"""
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
        
        # Удаляем дубликаты
        df = df.drop_duplicates(subset=['timestamp'], keep='last')
        
        return df
    
    async def get_current_price(self, figi: str) -> Optional[float]:
        """Получение текущей цены для тикера"""
        try:
            candles = await self.get_candles_for_ticker(figi, hours=2)
            if candles:
                df = self.candles_to_dataframe(candles)
                if not df.empty:
                    return float(df.iloc[-1]['close'])
            return None
        except Exception as e:
            logger.error(f"Ошибка получения цены для {figi}: {e}")
            return None
    
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
                        'trading_status': instrument.trading_status
                    }
                
        except Exception as e:
            logger.error(f"Ошибка получения информации о тикере {figi}: {e}")
        
        return None
    
    @staticmethod
    def quotation_to_decimal(quotation) -> float:
        """Преобразование quotation в decimal"""
        try:
            return float(quotation.units + quotation.nano / 1e9)
        except (AttributeError, TypeError):
            return 0.0
    
    async def validate_figis(self, figis: List[str]) -> dict:
        """Проверка валидности FIGI кодов"""
        results = {}
        
        for figi in figis:
            ticker_info = await self.get_ticker_info(figi)
            results[figi] = {
                'valid': ticker_info is not None,
                'info': ticker_info
            }
        
        return results
    
    async def get_market_status(self) -> dict:
        """Получение статуса рынка"""
        try:
            with Client(self.token) as client:
                response = client.instruments.trading_schedules(
                    exchange="MOEX",
                    from_=now() - timedelta(days=1),
                    to=now() + timedelta(days=1)
                )
                
                market_status = {
                    'is_open': False,
                    'next_open': None,
                    'next_close': None
                }
                
                if response.exchanges:
                    for exchange in response.exchanges:
                        if exchange.days:
                            today = exchange.days[0]
                            current_time = now()
                            
                            if today.start_time <= current_time <= today.end_time:
                                market_status['is_open'] = True
                            
                            market_status['next_open'] = today.start_time
                            market_status['next_close'] = today.end_time
                
                return market_status
                
        except Exception as e:
            logger.error(f"Ошибка получения статуса рынка: {e}")
            return {'is_open': None, 'next_open': None, 'next_close': None}
