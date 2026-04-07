import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import httpx

from config import MOEX_BASE_URL, MOEX_TIMEOUT

logger = logging.getLogger(__name__)

# Топ-30 акций IMOEX для расчёта breadth
IMOEX_TICKERS = [
    'SBER', 'GAZP', 'LKOH', 'GMKN', 'NVTK', 'ROSN', 'PLZL', 'YDEX',
    'MGNT', 'CHMF', 'SNGS', 'MTSS', 'ALRS', 'IRAO', 'NLMK', 'PHOR',
    'RUAL', 'TATN', 'MOEX', 'MAGN', 'PIKK', 'POLY', 'AFLT', 'VTBR',
    'RTKM', 'FEES', 'HYDR', 'TRNFP', 'SNGSP', 'FIVE'
]

# Веса компонентов
WEIGHTS = {
    'volatility': 0.25,
    'momentum': 0.25,
    'sma_deviation': 0.15,
    'breadth': 0.15,
    'safe_haven': 0.10,
    'rsi': 0.10,
}


class FearGreedIndex:
    """Расчёт индекса страха и жадности для MOEX"""

    def __init__(self):
        self.base_url = MOEX_BASE_URL
        self.timeout = MOEX_TIMEOUT

    async def calculate(self) -> Optional[Dict[str, Any]]:
        """
        Рассчитать индекс страха и жадности.
        
        Returns:
            Dict с ключами:
            - value: int (0-100)
            - label: str (текстовая категория)
            - emoji: str
            - components: dict со скорами каждого компонента
        """
        try:
            # Загружаем все данные
            imoex_candles = await self._get_imoex_daily_candles(days=200)
            usdrub_candles = await self._get_usdrub_daily_candles(days=30)
            breadth_data = await self._get_market_breadth()

            if not imoex_candles or len(imoex_candles) < 130:
                logger.error(
                    f"Insufficient IMOEX data: "
                    f"{len(imoex_candles) if imoex_candles else 0} candles (need 130+)"
                )
                return None

            # 1. Волатильность (25%)
            volatility_score = self._calc_volatility_score(imoex_candles)

            # 2. Моментум / объёмы (25%)
            momentum_score = self._calc_momentum_score(imoex_candles)

            # 3. Отклонение от SMA-125 (15%)
            sma_score = self._calc_sma_deviation_score(imoex_candles)

            # 4. Breadth — ширина рынка (15%)
            breadth_score = self._calc_breadth_score(breadth_data)

            # 5. Safe Haven — USD/RUB (10%)
            safe_haven_score = self._calc_safe_haven_score(usdrub_candles)

            # 6. RSI индекса IMOEX (10%)
            rsi_score = self._calc_rsi_score(imoex_candles)

            # Взвешенная сумма
            value = (
                volatility_score * WEIGHTS['volatility']
                + momentum_score * WEIGHTS['momentum']
                + sma_score * WEIGHTS['sma_deviation']
                + breadth_score * WEIGHTS['breadth']
                + safe_haven_score * WEIGHTS['safe_haven']
                + rsi_score * WEIGHTS['rsi']
            )

            value = max(0, min(100, round(value)))

            result = {
                'value': value,
                'label': self._get_label(value),
                'emoji': self._get_emoji(value),
                'components': {
                    'volatility': round(volatility_score, 1),
                    'momentum': round(momentum_score, 1),
                    'sma_deviation': round(sma_score, 1),
                    'breadth': round(breadth_score, 1),
                    'safe_haven': round(safe_haven_score, 1),
                    'rsi': round(rsi_score, 1),
                },
            }

            logger.info(
                f"📊 Fear & Greed Index: {value} ({result['label']}) | "
                f"Vol={volatility_score:.0f} Mom={momentum_score:.0f} "
                f"SMA={sma_score:.0f} Breadth={breadth_score:.0f} "
                f"SafeH={safe_haven_score:.0f} RSI={rsi_score:.0f}"
            )

            return result

        except Exception as e:
            logger.error(f"Error calculating Fear & Greed Index: {e}", exc_info=True)
            return None

    # ========== ЗАГРУЗКА ДАННЫХ ==========

    async def _get_imoex_daily_candles(self, days: int = 200) -> Optional[List[Dict]]:
        """Дневные свечи индекса IMOEX"""
        try:
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days)

            url = f"{self.base_url}/engines/stock/markets/index/securities/IMOEX/candles.json"
            params = {
                'from': from_date.strftime('%Y-%m-%d'),
                'till': to_date.strftime('%Y-%m-%d'),
                'interval': 24,
                'iss.meta': 'off',
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()

            if 'candles' not in data or not data['candles']['data']:
                logger.error("No IMOEX candle data received")
                return None

            columns = data['candles']['columns']
            candles = []
            for row in data['candles']['data']:
                candle = dict(zip(columns, row))
                candles.append({
                    'open': float(candle['open']),
                    'close': float(candle['close']),
                    'high': float(candle['high']),
                    'low': float(candle['low']),
                    'volume': float(candle['value']),
                    'date': candle['begin'][:10],
                })

            logger.info(f"IMOEX: loaded {len(candles)} daily candles")
            return candles

        except Exception as e:
            logger.error(f"Error fetching IMOEX candles: {e}")
            return None

    async def _get_usdrub_daily_candles(self, days: int = 30) -> Optional[List[Dict]]:
        """Дневные свечи USD/RUB"""
        try:
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days)

            url = (
                f"{self.base_url}/engines/currency/markets/selt/boards/CETS/"
                f"securities/USD000UTSTOM/candles.json"
            )
            params = {
                'from': from_date.strftime('%Y-%m-%d'),
                'till': to_date.strftime('%Y-%m-%d'),
                'interval': 24,
                'iss.meta': 'off',
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()

            if 'candles' not in data or not data['candles']['data']:
                logger.error("No USD/RUB candle data received")
                return None

            columns = data['candles']['columns']
            candles = []
            for row in data['candles']['data']:
                candle = dict(zip(columns, row))
                candles.append({
                    'open': float(candle['open']),
                    'close': float(candle['close']),
                    'high': float(candle['high']),
                    'low': float(candle['low']),
                    'date': candle['begin'][:10],
                })

            logger.info(f"USD/RUB: loaded {len(candles)} daily candles")
            return candles

        except Exception as e:
            logger.error(f"Error fetching USD/RUB candles: {e}")
            return None

    async def _get_market_breadth(self) -> Optional[Dict[str, float]]:
        """
        Получить % изменения цены за день для топ-30 акций IMOEX.
        Один запрос вместо 30 отдельных.
        """
        try:
            url = f"{self.base_url}/engines/stock/markets/shares/boards/TQBR/securities.json"
            params = {
                'iss.meta': 'off',
                'iss.only': 'marketdata',
                'marketdata.columns': 'SECID,LASTCHANGEPRC',
            }

            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()

            if 'marketdata' not in data or not data['marketdata']['data']:
                return None

            result = {}
            for row in data['marketdata']['data']:
                secid = row[0]
                change_prc = row[1]
                if secid in IMOEX_TICKERS and change_prc is not None:
                    result[secid] = float(change_prc)

            logger.info(f"Breadth: got data for {len(result)}/{len(IMOEX_TICKERS)} stocks")
            return result

        except Exception as e:
            logger.error(f"Error fetching breadth data: {e}")
            return None

    # ========== РАСЧЁТ КОМПОНЕНТОВ ==========

    def _calc_volatility_score(self, candles: List[Dict]) -> float:
        """
        Волатильность (0-100, 100 = жадность/низкая вол, 0 = страх/высокая вол).
        Сравнение 20-дневной волатильности с 90-дневной.
        """
        closes = [c['close'] for c in candles]
        returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

        if len(returns) < 90:
            return 50.0

        def std(values):
            mean = sum(values) / len(values)
            return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5

        vol_20 = std(returns[-20:])
        vol_90 = std(returns[-90:])

        if vol_90 == 0:
            return 50.0

        ratio = vol_20 / vol_90

        # ratio 0.5 → 100 (спокойно = жадность)
        # ratio 1.0 → 50  (норма)
        # ratio 2.0 → 0   (паника = страх)
        score = 100 - (ratio - 0.5) * (100 / 1.5)
        return max(0.0, min(100.0, score))

    def _calc_momentum_score(self, candles: List[Dict]) -> float:
        """
        Моментум / объёмы (0-100).
        Высокий объём на росте = жадность, на падении = страх.
        """
        if len(candles) < 90:
            return 50.0

        closes = [c['close'] for c in candles]
        volumes = [c['volume'] for c in candles]

        avg_vol_5 = sum(volumes[-5:]) / 5
        avg_vol_90 = sum(volumes[-90:]) / 90

        if avg_vol_90 == 0:
            return 50.0

        vol_ratio = avg_vol_5 / avg_vol_90

        # 5-дневная доходность
        price_return = (closes[-1] - closes[-6]) / closes[-6]

        # Комбинируем направление цены с объёмом
        # price_return ±2% при нормальном объёме → ±50 от нейтрали
        score = 50 + price_return * 500 * min(vol_ratio, 2.0)
        return max(0.0, min(100.0, score))

    def _calc_sma_deviation_score(self, candles: List[Dict]) -> float:
        """
        Отклонение от SMA-125 (0-100).
        Выше SMA = жадность, ниже = страх.
        """
        closes = [c['close'] for c in candles]

        if len(closes) < 125:
            return 50.0

        sma_125 = sum(closes[-125:]) / 125
        current_price = closes[-1]
        deviation = (current_price - sma_125) / sma_125 * 100

        # -10% → 0, 0% → 50, +10% → 100
        score = 50 + deviation * 5
        return max(0.0, min(100.0, score))

    def _calc_breadth_score(self, breadth_data: Optional[Dict[str, float]]) -> float:
        """
        Ширина рынка (0-100).
        Доля растущих акций из топ-30.
        """
        if not breadth_data:
            return 50.0

        total = len(breadth_data)
        if total == 0:
            return 50.0

        rising = sum(1 for change in breadth_data.values() if change > 0)
        return (rising / total) * 100

    def _calc_safe_haven_score(self, usdrub_candles: Optional[List[Dict]]) -> float:
        """
        Safe Haven — USD/RUB (0-100).
        Рубль слабеет (USD растёт) = страх, укрепляется = жадность.
        """
        if not usdrub_candles or len(usdrub_candles) < 6:
            return 50.0

        current = usdrub_candles[-1]['close']
        past = usdrub_candles[-6]['close']
        change = (current - past) / past * 100

        # +5% (рубль упал) → 0 (страх)
        #  0%              → 50
        # -5% (рубль вырос) → 100 (жадность)
        score = 50 - change * 10
        return max(0.0, min(100.0, score))

    def _calc_rsi_score(self, candles: List[Dict]) -> float:
        """
        RSI(14) индекса IMOEX (0-100).
        RSI < 30 → 0 (страх), RSI > 70 → 100 (жадность).
        """
        closes = [c['close'] for c in candles]

        if len(closes) < 15:
            return 50.0

        # Дневные изменения
        gains = []
        losses = []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gains.append(max(0, diff))
            losses.append(max(0, -diff))

        period = 14
        if len(gains) < period:
            return 50.0

        # Wilder's smoothing
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        # Маппинг RSI → score
        if rsi <= 30:
            return 0.0
        elif rsi >= 70:
            return 100.0
        else:
            return (rsi - 30) / 40 * 100

    # ========== ВСПОМОГАТЕЛЬНЫЕ ==========

    @staticmethod
    def _get_label(value: int) -> str:
        if value <= 24:
            return 'Экстремальный страх'
        elif value <= 44:
            return 'Страх'
        elif value <= 55:
            return 'Нейтрально'
        elif value <= 74:
            return 'Жадность'
        else:
            return 'Экстремальная жадность'

    @staticmethod
    def _get_emoji(value: int) -> str:
        if value <= 24:
            return '😱'
        elif value <= 44:
            return '😰'
        elif value <= 55:
            return '😐'
        elif value <= 74:
            return '😀'
        else:
            return '🤑'


# Глобальный экземпляр
fear_greed = FearGreedIndex()
