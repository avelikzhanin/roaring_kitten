import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

import asyncpg

from config import DATABASE_URL

logger = logging.getLogger(__name__)


class Database:
    """Класс для работы с PostgreSQL"""
    
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
    
    async def connect(self):
        """Создание пула подключений"""
        try:
            self.pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
            logger.info("✅ Connected to PostgreSQL")
            await self._init_schema()
        except Exception as e:
            logger.error(f"❌ Failed to connect to PostgreSQL: {e}")
            raise
    
    async def disconnect(self):
        """Закрытие пула подключений"""
        if self.pool:
            await self.pool.close()
            logger.info("Disconnected from PostgreSQL")
    
    async def _init_schema(self):
        """Инициализация схемы БД"""
        async with self.pool.acquire() as conn:
            # Создаем таблицы по порядку
            
            # 1. Таблица пользователей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 2. Таблица подписок
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    ticker VARCHAR(10) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, ticker)
                )
            """)
            
            # 3. Таблица позиций
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    ticker VARCHAR(10) NOT NULL,
                    entry_price DECIMAL(10, 2) NOT NULL,
                    entry_time TIMESTAMP NOT NULL,
                    entry_adx DECIMAL(5, 2),
                    entry_di_plus DECIMAL(5, 2),
                    exit_price DECIMAL(10, 2),
                    exit_time TIMESTAMP,
                    profit_percent DECIMAL(10, 2),
                    is_open BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 4. Таблица состояний сигналов
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS signal_states (
                    ticker VARCHAR(10) PRIMARY KEY,
                    last_signal VARCHAR(10) NOT NULL,
                    last_adx DECIMAL(5, 2),
                    last_di_plus DECIMAL(5, 2),
                    last_di_minus DECIMAL(5, 2),
                    last_price DECIMAL(10, 2),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 5. Создаем индексы
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_ticker ON subscriptions(ticker)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_user_id ON positions(user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_is_open ON positions(is_open)")
            
            logger.info("✅ Database schema initialized")
    
    # ========== USERS ==========
    
    async def add_user(self, user_id: int, username: str = None, first_name: str = None):
        """Добавление пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (user_id, username, first_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE
                SET username = $2, first_name = $3
                """,
                user_id, username, first_name
            )
    
    # ========== SUBSCRIPTIONS ==========
    
    async def add_subscription(self, user_id: int, ticker: str) -> bool:
        """Добавление подписки. Возвращает True если подписка добавлена"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO subscriptions (user_id, ticker) VALUES ($1, $2)",
                    user_id, ticker
                )
            return True
        except asyncpg.UniqueViolationError:
            return False
    
    async def remove_subscription(self, user_id: int, ticker: str) -> bool:
        """Удаление подписки. Возвращает True если подписка была удалена"""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM subscriptions WHERE user_id = $1 AND ticker = $2",
                user_id, ticker
            )
            return result != "DELETE 0"
    
    async def get_user_subscriptions(self, user_id: int) -> List[str]:
        """Получение списка подписок пользователя"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT ticker FROM subscriptions WHERE user_id = $1 ORDER BY ticker",
                user_id
            )
            return [row['ticker'] for row in rows]
    
    async def is_subscribed(self, user_id: int, ticker: str) -> bool:
        """Проверка подписки"""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM subscriptions WHERE user_id = $1 AND ticker = $2)",
                user_id, ticker
            )
            return result
    
    async def get_ticker_subscribers(self, ticker: str) -> List[int]:
        """Получение списка подписчиков на акцию"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id FROM subscriptions WHERE ticker = $1",
                ticker
            )
            return [row['user_id'] for row in rows]
    
    async def get_all_subscribed_tickers(self) -> List[str]:
        """Получение всех акций, на которые есть подписки"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT ticker FROM subscriptions ORDER BY ticker"
            )
            return [row['ticker'] for row in rows]
    
    # ========== POSITIONS ==========
    
    async def open_position(
        self, 
        user_id: int, 
        ticker: str, 
        entry_price: float,
        entry_adx: float,
        entry_di_plus: float
    ) -> int:
        """Открытие позиции. Возвращает ID позиции"""
        async with self.pool.acquire() as conn:
            position_id = await conn.fetchval(
                """
                INSERT INTO positions (user_id, ticker, entry_price, entry_time, entry_adx, entry_di_plus)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                user_id, ticker, entry_price, datetime.now(), entry_adx, entry_di_plus
            )
            return position_id
    
    async def close_position(self, user_id: int, ticker: str, exit_price: float):
        """Закрытие позиции"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE positions
                SET exit_price = $3,
                    exit_time = $4,
                    profit_percent = ROUND((($3 - entry_price) / entry_price * 100)::numeric, 2),
                    is_open = FALSE
                WHERE user_id = $1 AND ticker = $2 AND is_open = TRUE
                """,
                user_id, ticker, exit_price, datetime.now()
            )
    
    async def get_open_positions(self, user_id: int) -> List[Dict[str, Any]]:
        """Получение открытых позиций пользователя"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, ticker, entry_price, entry_time, entry_adx, entry_di_plus
                FROM positions
                WHERE user_id = $1 AND is_open = TRUE
                ORDER BY entry_time DESC
                """,
                user_id
            )
            return [dict(row) for row in rows]
    
    async def get_closed_positions(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Получение закрытых позиций пользователя"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT ticker, entry_price, exit_price, profit_percent, entry_time, exit_time
                FROM positions
                WHERE user_id = $1 AND is_open = FALSE
                ORDER BY exit_time DESC
                LIMIT $2
                """,
                user_id, limit
            )
            return [dict(row) for row in rows]
    
    async def has_open_position(self, user_id: int, ticker: str) -> bool:
        """Проверка наличия открытой позиции"""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM positions WHERE user_id = $1 AND ticker = $2 AND is_open = TRUE)",
                user_id, ticker
            )
            return result
    
    # ========== SIGNAL STATES ==========
    
    async def get_signal_state(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Получение последнего состояния сигнала"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM signal_states WHERE ticker = $1",
                ticker
            )
            return dict(row) if row else None
    
    async def update_signal_state(
        self,
        ticker: str,
        signal: str,
        adx: float,
        di_plus: float,
        di_minus: float,
        price: float
    ):
        """Обновление состояния сигнала"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO signal_states (ticker, last_signal, last_adx, last_di_plus, last_di_minus, last_price, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (ticker) DO UPDATE
                SET last_signal = $2,
                    last_adx = $3,
                    last_di_plus = $4,
                    last_di_minus = $5,
                    last_price = $6,
                    updated_at = $7
                """,
                ticker, signal, adx, di_plus, di_minus, price, datetime.now()
            )
    
    # ========== STATISTICS ==========
    
    async def get_monthly_statistics(self, user_id: int, year: int, month: int) -> Dict[str, Any]:
        """Получение статистики за месяц"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT profit_percent
                FROM positions
                WHERE user_id = $1 
                  AND is_open = FALSE
                  AND EXTRACT(YEAR FROM exit_time) = $2
                  AND EXTRACT(MONTH FROM exit_time) = $3
                ORDER BY exit_time DESC
                """,
                user_id, year, month
            )
            
            if not rows:
                return {
                    'total_trades': 0,
                    'profitable': 0,
                    'unprofitable': 0,
                    'total_profit': 0.0
                }
            
            profits = [float(row['profit_percent']) for row in rows]
            profitable = [p for p in profits if p > 0]
            unprofitable = [p for p in profits if p <= 0]
            
            return {
                'total_trades': len(profits),
                'profitable': len(profitable),
                'unprofitable': len(unprofitable),
                'total_profit': sum(profits)
            }
    
    # ========== WEB DASHBOARD STATISTICS ==========
    
    async def get_all_open_positions_web(self, username: str = None) -> List[Dict[str, Any]]:
        """Получение всех открытых позиций для веб-дашборда"""
        async with self.pool.acquire() as conn:
            if username:
                rows = await conn.fetch(
                    """
                    SELECT 
                        p.user_id,
                        u.username,
                        u.first_name,
                        p.ticker,
                        p.entry_price,
                        p.entry_time
                    FROM positions p
                    JOIN users u ON p.user_id = u.user_id
                    WHERE p.is_open = TRUE AND u.username = $1
                    ORDER BY p.entry_time DESC
                    """,
                    username
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT 
                        p.user_id,
                        u.username,
                        u.first_name,
                        p.ticker,
                        p.entry_price,
                        p.entry_time
                    FROM positions p
                    JOIN users u ON p.user_id = u.user_id
                    WHERE p.is_open = TRUE
                    ORDER BY p.entry_time DESC
                    """
                )
            return [dict(row) for row in rows]
    
    async def get_all_closed_positions_web(self, limit: int = 50, username: str = None) -> List[Dict[str, Any]]:
        """Получение всех закрытых позиций для веб-дашборда (лента сделок)"""
        async with self.pool.acquire() as conn:
            if username:
                rows = await conn.fetch(
                    """
                    SELECT 
                        p.user_id,
                        u.username,
                        u.first_name,
                        p.ticker,
                        p.entry_price,
                        p.exit_price,
                        p.profit_percent,
                        p.entry_time,
                        p.exit_time
                    FROM positions p
                    JOIN users u ON p.user_id = u.user_id
                    WHERE p.is_open = FALSE AND u.username = $1
                    ORDER BY p.exit_time DESC
                    LIMIT $2
                    """,
                    username, limit
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT 
                        p.user_id,
                        u.username,
                        u.first_name,
                        p.ticker,
                        p.entry_price,
                        p.exit_price,
                        p.profit_percent,
                        p.entry_time,
                        p.exit_time
                    FROM positions p
                    JOIN users u ON p.user_id = u.user_id
                    WHERE p.is_open = FALSE
                    ORDER BY p.exit_time DESC
                    LIMIT $1
                    """,
                    limit
                )
            return [dict(row) for row in rows]
    
    async def get_global_monthly_statistics(self, year: int, month: int, username: str = None) -> Dict[str, Any]:
        """Получение глобальной статистики за месяц (все пользователи или конкретный)"""
        async with self.pool.acquire() as conn:
            if username:
                rows = await conn.fetch(
                    """
                    SELECT profit_percent
                    FROM positions p
                    JOIN users u ON p.user_id = u.user_id
                    WHERE p.is_open = FALSE
                      AND EXTRACT(YEAR FROM p.exit_time) = $1
                      AND EXTRACT(MONTH FROM p.exit_time) = $2
                      AND u.username = $3
                    ORDER BY p.exit_time DESC
                    """,
                    year, month, username
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT profit_percent
                    FROM positions
                    WHERE is_open = FALSE
                      AND EXTRACT(YEAR FROM exit_time) = $1
                      AND EXTRACT(MONTH FROM exit_time) = $2
                    ORDER BY exit_time DESC
                    """,
                    year, month
                )
            
            if not rows:
                return {
                    'total_trades': 0,
                    'profitable': 0,
                    'unprofitable': 0,
                    'total_profit': 0.0,
                    'winrate': 0.0
                }
            
            profits = [float(row['profit_percent']) for row in rows]
            profitable = [p for p in profits if p > 0]
            unprofitable = [p for p in profits if p <= 0]
            
            return {
                'total_trades': len(profits),
                'profitable': len(profitable),
                'unprofitable': len(unprofitable),
                'total_profit': sum(profits),
                'winrate': (len(profitable) / len(profits) * 100) if profits else 0.0
            }
    
    async def get_statistics_by_ticker(self, username: str = None) -> List[Dict[str, Any]]:
        """Получение статистики по каждой акции (за все время)"""
        async with self.pool.acquire() as conn:
            if username:
                rows = await conn.fetch(
                    """
                    SELECT 
                        p.ticker,
                        COUNT(*) as total_trades,
                        SUM(CASE WHEN p.profit_percent > 0 THEN 1 ELSE 0 END) as profitable,
                        ROUND(
                            (SUM(CASE WHEN p.profit_percent > 0 THEN 1 ELSE 0 END)::numeric / COUNT(*)::numeric * 100), 
                            2
                        ) as winrate,
                        ROUND(SUM(p.profit_percent)::numeric, 2) as total_profit
                    FROM positions p
                    JOIN users u ON p.user_id = u.user_id
                    WHERE p.is_open = FALSE AND u.username = $1
                    GROUP BY p.ticker
                    ORDER BY total_profit DESC
                    """,
                    username
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT 
                        ticker,
                        COUNT(*) as total_trades,
                        SUM(CASE WHEN profit_percent > 0 THEN 1 ELSE 0 END) as profitable,
                        ROUND(
                            (SUM(CASE WHEN profit_percent > 0 THEN 1 ELSE 0 END)::numeric / COUNT(*)::numeric * 100), 
                            2
                        ) as winrate,
                        ROUND(SUM(profit_percent)::numeric, 2) as total_profit
                    FROM positions
                    WHERE is_open = FALSE
                    GROUP BY ticker
                    ORDER BY total_profit DESC
                    """
                )
            return [dict(row) for row in rows]
    
    async def get_best_and_worst_trades(self, username: str = None) -> Dict[str, Any]:
        """Получение лучшей и худшей сделки"""
        async with self.pool.acquire() as conn:
            if username:
                # Лучшая сделка
                best_row = await conn.fetchrow(
                    """
                    SELECT 
                        p.ticker,
                        p.profit_percent,
                        p.exit_time,
                        u.username,
                        u.first_name
                    FROM positions p
                    JOIN users u ON p.user_id = u.user_id
                    WHERE p.is_open = FALSE AND u.username = $1
                    ORDER BY p.profit_percent DESC
                    LIMIT 1
                    """,
                    username
                )
                
                # Худшая сделка
                worst_row = await conn.fetchrow(
                    """
                    SELECT 
                        p.ticker,
                        p.profit_percent,
                        p.exit_time,
                        u.username,
                        u.first_name
                    FROM positions p
                    JOIN users u ON p.user_id = u.user_id
                    WHERE p.is_open = FALSE AND u.username = $1
                    ORDER BY p.profit_percent ASC
                    LIMIT 1
                    """,
                    username
                )
            else:
                # Лучшая сделка
                best_row = await conn.fetchrow(
                    """
                    SELECT 
                        p.ticker,
                        p.profit_percent,
                        p.exit_time,
                        u.username,
                        u.first_name
                    FROM positions p
                    JOIN users u ON p.user_id = u.user_id
                    WHERE p.is_open = FALSE
                    ORDER BY p.profit_percent DESC
                    LIMIT 1
                    """
                )
                
                # Худшая сделка
                worst_row = await conn.fetchrow(
                    """
                    SELECT 
                        p.ticker,
                        p.profit_percent,
                        p.exit_time,
                        u.username,
                        u.first_name
                    FROM positions p
                    JOIN users u ON p.user_id = u.user_id
                    WHERE p.is_open = FALSE
                    ORDER BY p.profit_percent ASC
                    LIMIT 1
                    """
                )
            
            return {
                'best': dict(best_row) if best_row else None,
                'worst': dict(worst_row) if worst_row else None
            }
    
    async def get_average_trade_duration(self, username: str = None) -> Optional[float]:
        """Получение средней продолжительности сделки в часах"""
        async with self.pool.acquire() as conn:
            if username:
                result = await conn.fetchval(
                    """
                    SELECT AVG(EXTRACT(EPOCH FROM (p.exit_time - p.entry_time)) / 3600)
                    FROM positions p
                    JOIN users u ON p.user_id = u.user_id
                    WHERE p.is_open = FALSE AND u.username = $1
                    """,
                    username
                )
            else:
                result = await conn.fetchval(
                    """
                    SELECT AVG(EXTRACT(EPOCH FROM (exit_time - entry_time)) / 3600)
                    FROM positions
                    WHERE is_open = FALSE
                    """
                )
            return float(result) if result else None


# Глобальный экземпляр базы данных
db = Database()
