import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List
import asyncio
import aiohttp
import json

class MOEXClient:
    """Клиент для получения данных с Московской биржи"""
    
    BASE_URL = "https://iss.moex.com/iss"
    
    def __init__(self):
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def get_candles(self, symbol: str, period: str = "1", 
                         start_date: Optional[str] = None, 
                         end_date: Optional[str] = None) -> pd.DataFrame:
        """
        Получить свечи для инструмента
        
        Args:
            symbol: Тикер (SBER, GAZP, LKOH, VTBR)
            period: Период (1, 10, 60, D, W, M)
            start_date: Дата начала в формате YYYY-MM-DD
            end_date: Дата окончания в формате YYYY-MM-DD
        """
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        # Определяем интервал для MOEX API
        interval_map = {
            "1": "1",      # 1 минута
            "5": "5",      # 5 минут  
            "10": "10",    # 10 минут
            "60": "60",    # 1 час
            "D": "24",     # день
            "W": "7",      # неделя
            "M": "31"      # месяц
        }
        
        interval = interval_map.get(period, "60")
        
        url = f"{self.BASE_URL}/engines/stock/markets/shares/securities/{symbol}/candles.json"
        params = {
            "from": start_date,
            "till": end_date,
            "interval": interval,
            "iss.meta": "off"
        }
        
        async with self.session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                
                if "candles" in data and "data" in data["candles"]:
                    df = pd.DataFrame(
                        data["candles"]["data"], 
                        columns=data["candles"]["columns"]
                    )
                    
                    if not df.empty:
                        # Преобразуем колонки в нужные типы
                        df["begin"] = pd.to_datetime(df["begin"])
                        df["open"] = pd.to_numeric(df["open"])
                        df["close"] = pd.to_numeric(df["close"])
                        df["high"] = pd.to_numeric(df["high"])
                        df["low"] = pd.to_numeric(df["low"])
                        df["volume"] = pd.to_numeric(df["volume"])
                        
                        # Переименовываем колонки для совместимости
                        df = df.rename(columns={
                            "begin": "datetime",
                            "open": "open",
                            "high": "high", 
                            "low": "low",
                            "close": "close",
                            "volume": "volume"
                        })
                        
                        return df[["datetime", "open", "high", "low", "close", "volume"]]
                
                return pd.DataFrame()
            else:
                raise Exception(f"MOEX API error: {response.status}")
    
    async def get_current_price(self, symbol: str) -> Optional[float]:
        """Получить текущую цену инструмента"""
        url = f"{self.BASE_URL}/engines/stock/markets/shares/securities/{symbol}.json"
        params = {"iss.meta": "off"}
        
        async with self.session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                
                if ("securities" in data and 
                    "data" in data["securities"] and 
                    len(data["securities"]["data"]) > 0):
                    
                    columns = data["securities"]["columns"]
                    row = data["securities"]["data"][0]
                    
                    # Ищем индекс колонки с ценой
                    price_idx = None
                    for idx, col in enumerate(columns):
                        if col.lower() in ["prevprice", "last", "close"]:
                            price_idx = idx
                            break
                    
                    if price_idx is not None and row[price_idx] is not None:
                        return float(row[price_idx])
                
                return None
            else:
                raise Exception(f"MOEX API error: {response.status}")
    
    async def get_market_data(self, symbols: List[str]) -> dict:
        """Получить рыночные данные для списка инструментов"""
        results = {}
        
        for symbol in symbols:
            try:
                # Получаем свечи за последние 2 дня (для расчета индикаторов)
                candles = await self.get_candles(
                    symbol, 
                    period="60",  # часовые свечи
                    start_date=(datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
                )
                
                # Получаем текущую цену
                current_price = await self.get_current_price(symbol)
                
                results[symbol] = {
                    "candles": candles,
                    "current_price": current_price,
                    "last_update": datetime.now().isoformat()
                }
                
            except Exception as e:
                print(f"Ошибка получения данных для {symbol}: {e}")
                results[symbol] = {
                    "candles": pd.DataFrame(),
                    "current_price": None,
                    "error": str(e)
                }
        
        return results

# Функции для синхронного использования
async def get_moex_data_async(symbols: List[str]) -> dict:
    """Асинхронная функция для получения данных MOEX"""
    async with MOEXClient() as client:
        return await client.get_market_data(symbols)

def get_moex_data(symbols: List[str]) -> dict:
    """Синхронная функция для получения данных MOEX"""
    try:
        # Пытаемся получить текущий event loop
        loop = asyncio.get_running_loop()
        # Если event loop уже запущен, создаем task
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, get_moex_data_async(symbols))
            return future.result()
    except RuntimeError:
        # Если нет running event loop, используем asyncio.run
        return asyncio.run(get_moex_data_async(symbols))

async def get_moex_candles_async(symbol: str, period: str = "60", days: int = 30) -> pd.DataFrame:
    """Асинхронная функция для получения свечей"""
    async with MOEXClient() as client:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return await client.get_candles(symbol, period, start_date)

def get_moex_candles(symbol: str, period: str = "60", days: int = 30) -> pd.DataFrame:
    """Синхронная функция для получения свечей"""
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, get_moex_candles_async(symbol, period, days))
            return future.result()
    except RuntimeError:
        return asyncio.run(get_moex_candles_async(symbol, period, days))

# Тестирование
if __name__ == "__main__":
    import asyncio
    
    async def test():
        symbols = ["SBER", "GAZP", "LKOH", "VTBR"]
        
        async with MOEXClient() as client:
            print("Тестирование MOEX API...")
            
            # Тест получения данных
            market_data = await client.get_market_data(symbols)
            
            for symbol, data in market_data.items():
                print(f"\n{symbol}:")
                print(f"Текущая цена: {data.get('current_price')}")
                print(f"Свечей получено: {len(data.get('candles', []))}")
                
                if not data.get('candles', pd.DataFrame()).empty:
                    df = data['candles']
                    print(f"Последняя свеча: {df.iloc[-1]['datetime']} - Close: {df.iloc[-1]['close']}")
    
    asyncio.run(test())
