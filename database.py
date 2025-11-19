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
                    position_type VARCHAR(10) DEFAULT 'LONG',
                    entry_price DECIMAL(10, 2) NOT NULL,
                    entry_time TIMESTAMP NOT NULL,
                    entry_adx DECIMAL(5, 2),
                    entry_di_plus DECIMAL(5, 2),
                    entry_di_minus DECIMAL(5, 2),
                    exit_price DECIMAL(10, 2),
                    exit_time TIMESTAMP,
                    profit_percent DECIMAL(10, 2),
                    is_open BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Миграция: добавляем position_type если его нет
            try:
                await conn.execute("""
                    ALTER TABLE positions 
                    ADD COLUMN IF NOT EXISTS position_type VARCHAR(10) DEFAULT 'LONG'
                """)
                logger.info("✅ Migration: position_type column added/verified")
            except Exception as e:
                logger.warning(f"Migration warning: {e}")
            
            # Миграция: добавляем entry_di_minus если его нет
            try:
                await conn.execute("""
                    ALTER TABLE positions 
                    ADD COLUMN IF NOT EXISTS entry_di_minus DECIMAL(5, 2)
                """)
                logger.info("✅ Migration: entry_di_minus column added/verified")
            except Exception as e:
                logger.warning(f"Migration warning: {e}")
            
            # 4. Таблица состояний сигналов (теперь отдельно для LONG и SHORT)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS signal_states (
                    ticker VARCHAR(10) NOT NULL,
                    signal_type VARCHAR(10) NOT NULL,
                    last_signal VARCHAR(10) NOT NULL,
                    last_adx DECIMAL(5, 2),
                    last_di_plus DECIMAL(5, 2),
                    last_di_minus DECIMAL(5, 2),
                    last_price DECIMAL(10, 2),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (ticker, signal_type)
                )
            """)
            
            # Миграция: добавляем signal_type в signal_states
            try:
                # Проверяем структуру таблицы
                columns = await conn.fetch("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'signal_states'
                """)
                column_names = [col['column_name'] for col in columns]
                
                if 'signal_type' not in column_names:
                    # Старая структура - нужна миграция
                    logger.info("🔄 Migrating signal_states table...")
                    
                    # Создаем новую таблицу
                    await conn.execute("""
                        CREATE TABLE signal_states_new (
                            ticker VARCHAR(10) NOT NULL,
                            signal_type VARCHAR(10) NOT NULL,
                            last_signal VARCHAR(10) NOT NULL,
                            last_adx DECIMAL(5, 2),
                            last_di_plus DECIMAL(5, 2),
                            last_di_minus DECIMAL(5, 2),
                            last_price DECIMAL(10, 2),
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (ticker, signal_type)
                        )
                    """)
                    
                    # Копируем данные из старой таблицы (для LONG)
                    await conn.execute("""
                        INSERT INTO signal_states_new 
                        (ticker, signal_type, last_signal, last_adx, last_di_plus, last_di_minus, last_price, updated_at)
                        SELECT ticker, 'LONG', last_signal, last_adx, last_di_plus, last_di_minus, last_price, updated_at
                        FROM signal_states
                    """)
                    
                    # Удаляем старую таблицу
                    await conn.execute("DROP TABLE signal_states")
                    
                    # Переименовываем новую таблицу
                    await conn.execute("ALTER TABLE signal_states_new RENAME TO signal_states")
                    
                    logger.info("✅ Migration: signal_states migrated successfully")
                else:
                    logger.info("✅ signal_states already has correct structure")
                    
            except Exception as e:
                logger.warning(f"Migration warning for signal_states: {e}")
            
            # 5. Создаем индексы
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_ticker ON subscriptions(ticker)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_user_id ON positions(user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_is_open ON positions(is_open)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_position_type ON positions(position_type)")
            
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
        position_type: str,
        entry_price: float,
        entry_adx: float,
        entry_di_plus: float,
        entry_di_minus: float
    ) -> int:
        """Открытие позиции. Возвращает ID позиции"""
        async with self.pool.acquire() as conn:
            position_id = await conn.fetchval(
                """
                INSERT INTO positions 
                (user_id, ticker, position_type, entry_price, entry_time, entry_adx, entry_di_plus, entry_di_minus)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                user_id, ticker, position_type, entry_price, datetime.now(), entry_adx, entry_di_plus, entry_di_minus
            )
            return position_id
    
    async def close_position(self, user_id: int, ticker: str, position_type: str, exit_price: float):
        """Закрытие позиции"""
        async with self.pool.acquire() as conn:
            # Для LONG: (exit - entry) / entry * 100
            # Для SHORT: (entry - exit) / entry * 100
            if position_type == 'LONG':
                profit_formula = "(($3 - entry_price) / entry_price * 100)"
            else:  # SHORT
                profit_formula = "((entry_price - $3) / entry_price * 100)"
            
            query = f"""
                UPDATE positions
                SET exit_price = $3,
                    exit_time = $4,
                    profit_percent = ROUND({profit_formula}::numeric, 2),
                    is_open = FALSE
                WHERE user_id = $1 AND ticker = $2 AND position_type = $5 AND is_open = TRUE
            """
            
            await conn.execute(
                query,
                user_id, ticker, exit_price, datetime.now(), position_type
            )
    
    async def get_open_positions(self, user_id: int) -> List[Dict[str, Any]]:
        """Получение открытых позиций пользователя"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, ticker, position_type, entry_price, entry_time, entry_adx, entry_di_plus, entry_di_minus
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
                SELECT ticker, position_type, entry_price, exit_price, profit_percent, entry_time, exit_time
                FROM positions
                WHERE user_id = $1 AND is_open = FALSE
                ORDER BY exit_time DESC
                LIMIT $2
                """,
                user_id, limit
            )
            return [dict(row) for row in rows]
    
    async def has_open_position(self, user_id: int, ticker: str, position_type: str = None) -> bool:
        """Проверка наличия открытой позиции (любого типа или конкретного)"""
        async with self.pool.acquire() as conn:
            if position_type:
                result = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM positions WHERE user_id = $1 AND ticker = $2 AND position_type = $3 AND is_open = TRUE)",
                    user_id, ticker, position_type
                )
            else:
                # Проверяем наличие любой открытой позиции (LONG или SHORT)
                result = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM positions WHERE user_id = $1 AND ticker = $2 AND is_open = TRUE)",
                    user_id, ticker
                )
            return result
    
    # ========== SIGNAL STATES ==========
    
    async def get_signal_state(self, ticker: str, signal_type: str) -> Optional[Dict[str, Any]]:
        """Получение последнего состояния сигнала для конкретного типа (LONG/SHORT)"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM signal_states WHERE ticker = $1 AND signal_type = $2",
                ticker, signal_type
            )
            return dict(row) if row else None
    
    async def update_signal_state(
        self,
        ticker: str,
        signal_type: str,
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
                INSERT INTO signal_states 
                (ticker, signal_type, last_signal, last_adx, last_di_plus, last_di_minus, last_price, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (ticker, signal_type) DO UPDATE
                SET last_signal = $3,
                    last_adx = $4,
                    last_di_plus = $5,
                    last_di_minus = $6,
                    last_price = $7,
                    updated_at = $8
                """,
                ticker, signal_type, signal, adx, di_plus, di_minus, price, datetime.now()
            )
    
    # ========== STATISTICS ==========
    
    async def get_monthly_statistics(self, user_id: int, year: int, month: int, position_type: str = None) -> Dict[str, Any]:
        """Получение статистики за месяц (с фильтром по типу позиции)"""
        async with self.pool.acquire() as conn:
            if position_type:
                rows = await conn.fetch(
                    """
                    SELECT profit_percent
                    FROM positions
                    WHERE user_id = $1 
                      AND is_open = FALSE
                      AND position_type = $4
                      AND EXTRACT(YEAR FROM exit_time) = $2
                      AND EXTRACT(MONTH FROM exit_time) = $3
                    ORDER BY exit_time DESC
                    """,
                    user_id, year, month, position_type
                )
            else:
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
                        COALESCE(u.username, 'unknown') as username,
                        COALESCE(u.first_name, 'Unknown') as first_name,
                        p.ticker,
                        p.position_type,
                        p.entry_price,
                        p.entry_time
                    FROM positions p
                    LEFT JOIN users u ON p.user_id = u.user_id
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
                        COALESCE(u.username, 'unknown') as username,
                        COALESCE(u.first_name, 'Unknown') as first_name,
                        p.ticker,
                        p.position_type,
                        p.entry_price,
                        p.entry_time
                    FROM positions p
                    LEFT JOIN users u ON p.user_id = u.user_id
                    WHERE p.is_open = TRUE
                    ORDER BY p.entry_time DESC
                    """
                )
            return [dict(row) for row in rows]
    
    async def get_all_closed_positions_web(self, limit: int = 50, username: str = None, position_type: str = None) -> List[Dict[str, Any]]:
        """Получение всех закрытых позиций для веб-дашборда (лента сделок)"""
        async with self.pool.acquire() as conn:
            if username:
                if position_type:
                    rows = await conn.fetch(
                        """
                        SELECT 
                            p.user_id,
                            COALESCE(u.username, 'unknown') as username,
                            COALESCE(u.first_name, 'Unknown') as first_name,
                            p.ticker,
                            p.position_type,
                            p.entry_price,
                            p.exit_price,
                            p.profit_percent,
                            p.entry_time,
                            p.exit_time
                        FROM positions p
                        LEFT JOIN users u ON p.user_id = u.user_id
                        WHERE p.is_open = FALSE AND u.username = $1 AND p.position_type = $3
                        ORDER BY p.exit_time DESC
                        LIMIT $2
                        """,
                        username, limit, position_type
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT 
                            p.user_id,
                            COALESCE(u.username, 'unknown') as username,
                            COALESCE(u.first_name, 'Unknown') as first_name,
                            p.ticker,
                            p.position_type,
                            p.entry_price,
                            p.exit_price,
                            p.profit_percent,
                            p.entry_time,
                            p.exit_time
                        FROM positions p
                        LEFT JOIN users u ON p.user_id = u.user_id
                        WHERE p.is_open = FALSE AND u.username = $1
                        ORDER BY p.exit_time DESC
                        LIMIT $2
                        """,
                        username, limit
                    )
            else:
                if position_type:
                    rows = await conn.fetch(
                        """
                        SELECT 
                            p.user_id,
                            COALESCE(u.username, 'unknown') as username,
                            COALESCE(u.first_name, 'Unknown') as first_name,
                            p.ticker,
                            p.position_type,
                            p.entry_price,
                            p.exit_price,
                            p.profit_percent,
                            p.entry_time,
                            p.exit_time
                        FROM positions p
                        LEFT JOIN users u ON p.user_id = u.user_id
                        WHERE p.is_open = FALSE AND p.position_type = $2
                        ORDER BY p.exit_time DESC
                        LIMIT $1
                        """,
                        limit, position_type
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT 
                            p.user_id,
                            COALESCE(u.username, 'unknown') as username,
                            COALESCE(u.first_name, 'Unknown') as first_name,
                            p.ticker,
                            p.position_type,
                            p.entry_price,
                            p.exit_price,
                            p.profit_percent,
                            p.entry_time,
                            p.exit_time
                        FROM positions p
                        LEFT JOIN users u ON p.user_id = u.user_id
                        WHERE p.is_open = FALSE
                        ORDER BY p.exit_time DESC
                        LIMIT $1
                        """,
                        limit
                    )
            return [dict(row) for row in rows]
    
    async def get_global_monthly_statistics(self, year: int, month: int, username: str = None, position_type: str = None) -> Dict[str, Any]:
        """Получение глобальной статистики за месяц (все пользователи или конкретный, с фильтром по типу)"""
        async with self.pool.acquire() as conn:
            # Формируем WHERE условия
            where_conditions = ["p.is_open = FALSE"]
            params = [year, month]
            param_idx = 3
            
            if username:
                where_conditions.append(f"u.username = ${param_idx}")
                params.append(username)
                param_idx += 1
            
            if position_type:
                where_conditions.append(f"p.position_type = ${param_idx}")
                params.append(position_type)
                param_idx += 1
            
            where_clause = " AND ".join(where_conditions)
            
            query = f"""
                SELECT profit_percent
                FROM positions p
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE {where_clause}
                  AND EXTRACT(YEAR FROM p.exit_time) = $1
                  AND EXTRACT(MONTH FROM p.exit_time) = $2
                ORDER BY p.exit_time DESC
            """
            
            rows = await conn.fetch(query, *params)
            
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
    
    async def get_statistics_by_ticker(self, username: str = None, position_type: str = None) -> List[Dict[str, Any]]:
        """Получение статистики по каждой акции (за все время, с фильтром по типу)"""
        async with self.pool.acquire() as conn:
            # Формируем WHERE условия
            where_conditions = ["p.is_open = FALSE"]
            params = []
            param_idx = 1
            
            if username:
                where_conditions.append(f"u.username = ${param_idx}")
                params.append(username)
                param_idx += 1
            
            if position_type:
                where_conditions.append(f"p.position_type = ${param_idx}")
                params.append(position_type)
                param_idx += 1
            
            where_clause = " AND ".join(where_conditions)
            
            query = f"""
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
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE {where_clause}
                GROUP BY p.ticker
                ORDER BY total_profit DESC
            """
            
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
    
    async def get_best_and_worst_trades(self, username: str = None, position_type: str = None) -> Dict[str, Any]:
        """Получение лучшей и худшей сделки (с фильтром по типу)"""
        async with self.pool.acquire() as conn:
            # Формируем WHERE условия
            where_conditions = ["p.is_open = FALSE"]
            params = []
            param_idx = 1
            
            if username:
                where_conditions.append(f"u.username = ${param_idx}")
                params.append(username)
                param_idx += 1
            
            if position_type:
                where_conditions.append(f"p.position_type = ${param_idx}")
                params.append(position_type)
                param_idx += 1
            
            where_clause = " AND ".join(where_conditions)
            
            # Лучшая сделка
            best_query = f"""
                SELECT 
                    p.ticker,
                    p.position_type,
                    p.profit_percent,
                    p.exit_time,
                    COALESCE(u.username, 'unknown') as username,
                    COALESCE(u.first_name, 'Unknown') as first_name
                FROM positions p
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE {where_clause}
                ORDER BY p.profit_percent DESC
                LIMIT 1
            """
            
            best_row = await conn.fetchrow(best_query, *params)
            
            # Худшая сделка
            worst_query = f"""
                SELECT 
                    p.ticker,
                    p.position_type,
                    p.profit_percent,
                    p.exit_time,
                    COALESCE(u.username, 'unknown') as username,
                    COALESCE(u.first_name, 'Unknown') as first_name
                FROM positions p
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE {where_clause}
                ORDER BY p.profit_percent ASC
                LIMIT 1
            """
            
            worst_row = await conn.fetchrow(worst_query, *params)
            
            return {
                'best': dict(best_row) if best_row else None,
                'worst': dict(worst_row) if worst_row else None
            }
    
    async def get_average_trade_duration(self, username: str = None, position_type: str = None) -> Optional[float]:
        """Получение средней продолжительности сделки в часах (с фильтром по типу)"""
        async with self.pool.acquire() as conn:
            # Формируем WHERE условия
            where_conditions = ["p.is_open = FALSE"]
            params = []
            param_idx = 1
            
            if username:
                where_conditions.append(f"u.username = ${param_idx}")
                params.append(username)
                param_idx += 1
            
            if position_type:
                where_conditions.append(f"p.position_type = ${param_idx}")
                params.append(position_type)
                param_idx += 1
            
            where_clause = " AND ".join(where_conditions)
            
            query = f"""
                SELECT AVG(EXTRACT(EPOCH FROM (p.exit_time - p.entry_time)) / 3600)
                FROM positions p
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE {where_clause}
            """
            
            result = await conn.fetchval(query, *params)
            return float(result) if result else None
    
    async def get_top_trades(self, username: str = None, limit: int = 10, best: bool = True, position_type: str = None) -> List[Dict[str, Any]]:
        """Получение топ лучших или худших сделок (с фильтром по типу)"""
        async with self.pool.acquire() as conn:
            order = "DESC" if best else "ASC"
            
            # Формируем WHERE условия
            where_conditions = ["p.is_open = FALSE"]
            params = []
            param_idx = 1
            
            if username:
                where_conditions.append(f"u.username = ${param_idx}")
                params.append(username)
                param_idx += 1
            
            if position_type:
                where_conditions.append(f"p.position_type = ${param_idx}")
                params.append(position_type)
                param_idx += 1
            
            # Добавляем limit
            params.append(limit)
            limit_param = f"${len(params)}"
            
            where_clause = " AND ".join(where_conditions)
            
            query = f"""
                SELECT 
                    p.ticker,
                    p.position_type,
                    p.profit_percent,
                    p.exit_time,
                    COALESCE(u.username, 'unknown') as username,
                    COALESCE(u.first_name, 'Unknown') as first_name
                FROM positions p
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE {where_clause}
                ORDER BY p.profit_percent {order}
                LIMIT {limit_param}
            """
            
            rows = await conn.fetch(query, *params)
            
            return [dict(row) for row in rows]
    
    async def get_statistics_by_ticker_filtered(self, username: str = None, year: int = None, month: int = None, position_type: str = None) -> List[Dict[str, Any]]:
        """Получение статистики по каждой акции за конкретный месяц"""
        async with self.pool.acquire() as conn:
            # Формируем WHERE условия
            where_conditions = ["p.is_open = FALSE"]
            params = []
            param_idx = 1
            
            if username:
                where_conditions.append(f"u.username = ${param_idx}")
                params.append(username)
                param_idx += 1
            
            if year and month:
                where_conditions.append(f"EXTRACT(YEAR FROM p.exit_time) = ${param_idx}")
                params.append(year)
                param_idx += 1
                where_conditions.append(f"EXTRACT(MONTH FROM p.exit_time) = ${param_idx}")
                params.append(month)
                param_idx += 1
            
            if position_type:
                where_conditions.append(f"p.position_type = ${param_idx}")
                params.append(position_type)
                param_idx += 1
            
            where_clause = " AND ".join(where_conditions)
            
            query = f"""
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
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE {where_clause}
                GROUP BY p.ticker
                ORDER BY total_profit DESC
            """
            
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
    
    async def get_closed_positions_filtered(
        self, 
        username: str = None, 
        year: int = None, 
        month: int = None, 
        position_type: str = None, 
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Получение закрытых позиций с фильтрами по месяцу и типу"""
        async with self.pool.acquire() as conn:
            # Формируем WHERE условия
            where_conditions = ["p.is_open = FALSE"]
            params = []
            param_idx = 1
            
            if username:
                where_conditions.append(f"u.username = ${param_idx}")
                params.append(username)
                param_idx += 1
            
            if year and month:
                where_conditions.append(f"EXTRACT(YEAR FROM p.exit_time) = ${param_idx}")
                params.append(year)
                param_idx += 1
                where_conditions.append(f"EXTRACT(MONTH FROM p.exit_time) = ${param_idx}")
                params.append(month)
                param_idx += 1
            
            if position_type and position_type != 'all':
                where_conditions.append(f"p.position_type = ${param_idx}")
                params.append(position_type)
                param_idx += 1
            
            # Добавляем limit
            params.append(limit)
            limit_param = f"${len(params)}"
            
            where_clause = " AND ".join(where_conditions)
            
            query = f"""
                SELECT 
                    p.user_id,
                    COALESCE(u.username, 'unknown') as username,
                    COALESCE(u.first_name, 'Unknown') as first_name,
                    p.ticker,
                    p.position_type,
                    p.entry_price,
                    p.exit_price,
                    p.profit_percent,
                    p.entry_time,
                    p.exit_time
                FROM positions p
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE {where_clause}
                ORDER BY p.exit_time DESC
                LIMIT {limit_param}
            """
            
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
    
    async def get_cumulative_profit_data(
        self, 
        username: str = None, 
        year: int = None, 
        month: int = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Получение данных для графика накопленной прибыли по акциям
        
        Returns:
            Dict с ключами-тикерами, значения - список точек [{date, cumulative_profit}]
        """
        async with self.pool.acquire() as conn:
            # Формируем WHERE условия
            where_conditions = ["p.is_open = FALSE"]
            params = []
            param_idx = 1
            
            if username:
                where_conditions.append(f"u.username = ${param_idx}")
                params.append(username)
                param_idx += 1
            
            if year and month:
                where_conditions.append(f"EXTRACT(YEAR FROM p.exit_time) = ${param_idx}")
                params.append(year)
                param_idx += 1
                where_conditions.append(f"EXTRACT(MONTH FROM p.exit_time) = ${param_idx}")
                params.append(month)
                param_idx += 1
            
            where_clause = " AND ".join(where_conditions)
            
            query = f"""
                SELECT 
                    p.ticker,
                    p.exit_time,
                    p.profit_percent
                FROM positions p
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE {where_clause}
                ORDER BY p.ticker, p.exit_time ASC
            """
            
            rows = await conn.fetch(query, *params)
            
            # Группируем по тикерам и вычисляем накопленную прибыль
            result = {}
            for row in rows:
                ticker = row['ticker']
                
                # Для первой сделки акции добавляем начальную точку с нулевой прибылью
                if ticker not in result:
                    result[ticker] = []
                    # Добавляем начальную точку (0) в момент первой сделки
                    result[ticker].append({
                        'date': row['exit_time'],
                        'cumulative_profit': 0
                    })
                
                # Вычисляем накопленную прибыль
                previous_cumulative = result[ticker][-1]['cumulative_profit']
                cumulative_profit = previous_cumulative + float(row['profit_percent'])
                
                result[ticker].append({
                    'date': row['exit_time'],
                    'cumulative_profit': cumulative_profit
                })
            
            return result


# Глобальный экземпляр базы данных
db = Database()
