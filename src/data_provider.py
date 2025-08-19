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
        self.figi = "BBG004730N88"  # SBER
        self._client = None
    
    async def get_candles(self, hours: int = 100) -> List[HistoricCandle]:
        """Получение свечных данных за последние N часов"""
        max_retries = 3
        retry_delay = 5  # секунд
        
        for attempt in range(max_retries):
            try:
                # Используем синхронный Client вместо async
                with Client(self.token) as client:
                    to_time = now()
                    from_time = to_time - timedelta(hours=hours)
                    
                    logger.info(f"Запрос данных SBER с {from_time} по {to_time}")
                    
                    response = client.market_data.get_candles(
                        figi=self.figi,
                        from_=from_time,
                        to=to_time,
                        interval=CandleInterval.CANDLE_INTERVAL_HOUR
                    )
                    
                    if response.candles:
                        logger.info(f"Получено {len(response.candles)} свечей")
                        return response.candles
                    else:
                        logger.warning("Получен пустой ответ от API")
                        return []
                        
            except RequestError as e:
                logger.error(f"Ошибка API Tinkoff (попытка {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    raise
            except Exception as e:
                logger.error(f"Неожиданная ошибка при получении данных: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                else:
                    raise
        
        return []
    
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
        
        # Удаляем возможные дубликаты
        df = df.drop_duplicates(subset=['timestamp'], keep='last')
        
        return df
    
    @staticmethod
    def quotation_to_decimal(quotation) -> float:
        """Преобразование quotation в decimal"""
        try:
            return float(quotation.units + quotation.nano / 1e9)
        except (AttributeError, TypeError):
            return 0.0
