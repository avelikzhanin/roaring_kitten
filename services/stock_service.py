import logging
from typing import Optional

from api.moex_api import MoexApiClient
from indicators.technical_indicators import TechnicalIndicators
from models.stock import StockData, StockPrice, TechnicalData, StockInfo
from config import SUPPORTED_STOCKS, MAX_CANDLES

logger = logging.getLogger(__name__)


class StockService:
    """Сервис для работы с данными акций"""
    
    def __init__(self):
        self.moex_client = MoexApiClient()
        self.indicators = TechnicalIndicators()
    
    async def get_stock_data(self, ticker: str) -> Optional[StockData]:
        """Получение полных данных по акции"""
        ticker = ticker.upper()
        
        # Проверяем поддержку тикера
        if ticker not in SUPPORTED_STOCKS:
            logger.error(f"Unsupported ticker: {ticker}")
            return None
        
        try:
            # Получаем актуальную цену
            current_price = await self.moex_client.get_current_price(ticker)
            
            # Получаем исторические данные
            candles_data = await self.moex_client.get_historical_candles(ticker)
            if not candles_data:
                return None
            
            # Ограничиваем количество свечей
            if len(candles_data) > MAX_CANDLES:
                candles_data = candles_data[-MAX_CANDLES:]
            
            # Диагностика данных
            self._log_candles_info(ticker, candles_data)
            
            # Расчет технических индикаторов
            technical_data = self.indicators.calculate_all_indicators(candles_data)
            if not technical_data:
                return None
            
            # Собираем все данные
            stock_info = StockInfo(
                ticker=ticker,
                name=SUPPORTED_STOCKS[ticker]['name'],
                emoji=SUPPORTED_STOCKS[ticker]['emoji']
            )
            
            price_data = StockPrice(
                current_price=current_price if current_price else candles_data[-1]['close'],
                last_close=candles_data[-1]['close']
            )
            
            technical = TechnicalData(
                ema20=technical_data['ema20'],
                adx_standard=technical_data['adx_standard'],
                di_plus_standard=technical_data['di_plus_standard'],
                di_minus_standard=technical_data['di_minus_standard'],
                adx_pinescript=technical_data['adx_pinescript'],
                di_plus_pinescript=technical_data['di_plus_pinescript'],
                di_minus_pinescript=technical_data['di_minus_pinescript']
            )
            
            stock_data = StockData(
                info=stock_info,
                price=price_data,
                technical=technical
            )
            
            # Проверяем валидность данных
            if not stock_data.is_valid():
                logger.error(f"Invalid technical data for {ticker}")
                return None
            
            return stock_data
            
        except Exception as e:
            logger.error(f"Error getting stock data for {ticker}: {e}")
            return None
    
    def _log_candles_info(self, ticker: str, candles_data: list):
        """Логирование информации о свечах для диагностики"""
        if candles_data:
            logger.info(f"🔍 ПОСЛЕДНИЕ 3 СВЕЧИ {ticker} (для диагностики индикаторов):")
            for i, candle in enumerate(candles_data[-3:]):
                logger.info(f"   {i+1}. {candle['time']} | O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f}")
            
            first_time = candles_data[0]['time']
            last_time = candles_data[-1]['time']
            logger.info(f"Диапазон времени (МСК): {first_time} → {last_time}")
            logger.info(f"Цена последней свечи: {candles_data[-1]['close']:.2f} ₽")
