import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import httpx

from config import MOEX_BASE_URL, MOEX_TIMEOUT, HISTORY_DAYS

logger = logging.getLogger(__name__)


class MoexApiClient:
    """Клиент для работы с MOEX API"""
    
    def __init__(self):
        self.base_url = MOEX_BASE_URL
        self.timeout = MOEX_TIMEOUT
    
    async def get_current_price(self, ticker: str) -> Optional[float]:
        """Получение актуальной цены акции"""
        try:
            url = f"{self.base_url}/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json"
            params = {
                'iss.meta': 'off',
                'iss.only': 'marketdata',
                'marketdata.columns': 'LAST,BID,OFFER,TIME'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
            
            if 'marketdata' in data and 'data' in data['marketdata'] and data['marketdata']['data']:
                columns = data['marketdata']['columns']
                market_data = data['marketdata']['data'][0]
                
                last_price_index = columns.index('LAST') if 'LAST' in columns else None
                time_index = columns.index('TIME') if 'TIME' in columns else None
                
                if last_price_index is not None and market_data[last_price_index]:
                    current_price = float(market_data[last_price_index])
                    time_str = market_data[time_index] if time_index is not None else "неизвестно"
                    logger.info(f"💰 Получена актуальная цена {ticker}: {current_price:.2f} ₽ (время: {time_str})")
                    return current_price
            
            logger.warning(f"Не удалось получить актуальную цену {ticker} из TQBR marketdata endpoint")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching current {ticker} price: {e}")
            return None
    
    async def get_historical_candles(self, ticker: str, days: int = HISTORY_DAYS) -> Optional[List[Dict[str, Any]]]:
        """Получение исторических свечей"""
        try:
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days)
            
            url = f"{self.base_url}/engines/stock/markets/shares/securities/{ticker}/candles.json"
            params = {
                'from': from_date.strftime('%Y-%m-%d'),
                'till': to_date.strftime('%Y-%m-%d'),
                'interval': '60'  # Часовые свечи
            }
            
            logger.info(f"Запрашиваем исторические данные {ticker} с {from_date.strftime('%Y-%m-%d')} по {to_date.strftime('%Y-%m-%d')}")
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
            
            if 'candles' not in data or not data['candles']['data']:
                logger.error(f"No candle data received for {ticker}")
                return None
            
            columns = data['candles']['columns']
            candles_raw = data['candles']['data']
            
            # Преобразуем в удобный формат
            candles_data = []
            for candle in candles_raw:
                candles_data.append({
                    'open': float(candle[0]),
                    'close': float(candle[1]),
                    'high': float(candle[2]),
                    'low': float(candle[3]),
                    'volume': int(candle[5]),
                    'time': candle[6]
                })
            
            logger.info(f"Получено {len(candles_data)} часовых свечей для {ticker}")
            return candles_data
            
        except httpx.HTTPError as e:
            logger.error(f"MOEX API request error for {ticker}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {ticker} historical data: {e}")
            return None
