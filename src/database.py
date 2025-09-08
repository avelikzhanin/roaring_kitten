# src/database.py
import asyncio
import asyncpg
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class User:
    id: int
    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]
    is_active: bool
    created_at: datetime

@dataclass
class Ticker:
    id: int
    symbol: str
    figi: str
    name: str
    is_active: bool

@dataclass
class Signal:
    id: int
    ticker_id: int
    signal_type: str
    price: float
    ema20: float
    adx: float
    plus_di: float
    minus_di: float
    created_at: datetime

@dataclass
class Trade:
    id: int
    user_id: int
    ticker_id: int
    buy_price: float
    sell_price: Optional[float]
    profit_percent: Optional[float]
    status: str

class DatabaseManager:
    """Менеджер базы данных для торгового бота"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool: Optional[asyncpg.Pool] = None
    
    async def initialize(self):
        """Инициализация подключения к БД"""
        try:
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=1,
                max_size=10,
                command_timeout=60
            )
            await self.create_tables()
            logger.info("✅ База данных инициализирована")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации БД: {e}")
            raise
    
    async def close(self):
        """Закрытие подключения"""
        if self.pool:
            await self.pool.close()
    
    async def create_tables(self):
        """Создание таблиц если их нет"""
        async with self.pool.acquire() as conn:
            # Таблица пользователей
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    created_at TIMESTAMP DEFAULT NOW(),
                    is_active BOOLEAN DEFAULT TRUE,
                    last_activity TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Таблица тикеров
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tickers (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) UNIQUE NOT NULL,
                    figi VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(255),
                    is_active BOOLEAN DEFAULT TRUE
                )
            ''')
            
            # Таблица подписок
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    ticker_id INTEGER REFERENCES tickers(id) ON DELETE CASCADE,
                    subscribed_at TIMESTAMP DEFAULT NOW(),
                    is_active BOOLEAN DEFAULT TRUE,
                    UNIQUE(user_id, ticker_id)
                )
            ''')
            
            # Таблица сигналов
            await conn.execute('''
                CREATE TYPE signal_type AS ENUM ('BUY', 'SELL', 'PEAK', 'CANCEL');
            ''' if not await conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'signal_type')") else '')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id SERIAL PRIMARY KEY,
                    ticker_id INTEGER REFERENCES tickers(id),
                    signal_type signal_type NOT NULL,
                    price DECIMAL(10, 2),
                    ema20 DECIMAL(10, 2),
                    adx DECIMAL(5, 2),
                    plus_di DECIMAL(5, 2),
                    minus_di DECIMAL(5, 2),
                    gpt_recommendation VARCHAR(20),
                    gpt_confidence INTEGER,
                    gpt_take_profit DECIMAL(10, 2),
                    gpt_stop_loss DECIMAL(10, 2),
                    gpt_reasoning TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Таблица сделок
            await conn.execute('''
                CREATE TYPE trade_status AS ENUM ('OPEN', 'CLOSED', 'CANCELLED');
            ''' if not await conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'trade_status')") else '')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    ticker_id INTEGER REFERENCES tickers(id),
                    buy_signal_id INTEGER REFERENCES signals(id),
                    sell_signal_id INTEGER REFERENCES signals(id),
                    buy_price DECIMAL(10, 2),
                    sell_price DECIMAL(10, 2),
                    profit_percent DECIMAL(5, 2),
                    profit_rub DECIMAL(10, 2),
                    opened_at TIMESTAMP,
                    closed_at TIMESTAMP,
                    status trade_status DEFAULT 'OPEN'
                )
            ''')
            
            # Таблица уведомлений
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_notifications (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    signal_id INTEGER REFERENCES signals(id) ON DELETE CASCADE,
                    sent_at TIMESTAMP DEFAULT NOW(),
                    delivered BOOLEAN DEFAULT TRUE,
                    error_message TEXT
                )
            ''')
            
            # Создаем индексы для оптимизации
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_signals_ticker_created ON signals(ticker_id, created_at DESC)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_trades_user_status ON trades(user_id, status)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_active ON subscriptions(ticker_id, is_active)')
    
    # === Методы для пользователей ===
    
    async def add_user(self, telegram_id: int, username: str = None, first_name: str = None) -> int:
        """Добавление нового пользователя"""
        async with self.pool.acquire() as conn:
            user_id = await conn.fetchval('''
                INSERT INTO users (telegram_id, username, first_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (telegram_id) 
                DO UPDATE SET 
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_activity = NOW(),
                    is_active = TRUE
                RETURNING id
            ''', telegram_id, username, first_name)
            return user_id
    
    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Получение пользователя по Telegram ID"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM users WHERE telegram_id = $1',
                telegram_id
            )
            if row:
                return User(**dict(row))
            return None
    
    async def deactivate_user(self, telegram_id: int):
        """Деактивация пользователя"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                'UPDATE users SET is_active = FALSE WHERE telegram_id = $1',
                telegram_id
            )
    
    # === Методы для тикеров ===
    
    async def add_ticker(self, symbol: str, figi: str, name: str) -> int:
        """Добавление нового тикера"""
        async with self.pool.acquire() as conn:
            ticker_id = await conn.fetchval('''
                INSERT INTO tickers (symbol, figi, name)
                VALUES ($1, $2, $3)
                ON CONFLICT (symbol) DO NOTHING
                RETURNING id
            ''', symbol, figi, name)
            return ticker_id
    
    async def get_active_tickers(self) -> List[Ticker]:
        """Получение активных тикеров"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT * FROM tickers WHERE is_active = TRUE'
            )
            return [Ticker(**dict(row)) for row in rows]
    
    async def get_ticker_by_symbol(self, symbol: str) -> Optional[Ticker]:
        """Получение тикера по символу"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM tickers WHERE symbol = $1',
                symbol
            )
            if row:
                return Ticker(**dict(row))
            return None
    
    # === Методы для подписок ===
    
    async def add_subscription(self, user_id: int, ticker_id: int):
        """Добавление подписки"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO subscriptions (user_id, ticker_id)
                VALUES ($1, $2)
                ON CONFLICT (user_id, ticker_id) 
                DO UPDATE SET is_active = TRUE
            ''', user_id, ticker_id)
    
    async def remove_subscription(self, user_id: int, ticker_id: int):
        """Удаление подписки"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                UPDATE subscriptions 
                SET is_active = FALSE 
                WHERE user_id = $1 AND ticker_id = $2
            ''', user_id, ticker_id)
    
    async def get_user_subscriptions(self, user_id: int) -> List[Dict]:
        """Получение подписок пользователя"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT t.* FROM tickers t
                JOIN subscriptions s ON t.id = s.ticker_id
                WHERE s.user_id = $1 AND s.is_active = TRUE
            ''', user_id)
            return [dict(row) for row in rows]
    
    async def get_ticker_subscribers(self, ticker_id: int) -> List[int]:
        """Получение подписчиков на тикер"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT u.telegram_id FROM users u
                JOIN subscriptions s ON u.id = s.user_id
                WHERE s.ticker_id = $1 AND s.is_active = TRUE AND u.is_active = TRUE
            ''', ticker_id)
            return [row['telegram_id'] for row in rows]
    
    # === Методы для сигналов ===
    
    async def save_signal(self, ticker_id: int, signal_type: str, 
                         price: float, ema20: float, adx: float,
                         plus_di: float, minus_di: float,
                         gpt_data: Dict = None) -> int:
        """Сохранение сигнала"""
        async with self.pool.acquire() as conn:
            signal_id = await conn.fetchval('''
                INSERT INTO signals (
                    ticker_id, signal_type, price, ema20, adx, 
                    plus_di, minus_di, gpt_recommendation, 
                    gpt_confidence, gpt_take_profit, gpt_stop_loss, gpt_reasoning
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                RETURNING id
            ''', 
                ticker_id, signal_type, price, ema20, adx, plus_di, minus_di,
                gpt_data.get('recommendation') if gpt_data else None,
                gpt_data.get('confidence') if gpt_data else None,
                gpt_data.get('take_profit') if gpt_data else None,
                gpt_data.get('stop_loss') if gpt_data else None,
                gpt_data.get('reasoning') if gpt_data else None
            )
            return signal_id
    
    async def get_last_signal(self, ticker_id: int) -> Optional[Signal]:
        """Получение последнего сигнала для тикера"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT * FROM signals 
                WHERE ticker_id = $1 
                ORDER BY created_at DESC 
                LIMIT 1
            ''', ticker_id)
            if row:
                return Signal(**dict(row))
            return None
    
    # === Методы для сделок ===
    
    async def open_trade(self, user_id: int, ticker_id: int, 
                         buy_signal_id: int, buy_price: float) -> int:
        """Открытие сделки"""
        async with self.pool.acquire() as conn:
            trade_id = await conn.fetchval('''
                INSERT INTO trades (
                    user_id, ticker_id, buy_signal_id, 
                    buy_price, opened_at, status
                ) VALUES ($1, $2, $3, $4, NOW(), 'OPEN')
                RETURNING id
            ''', user_id, ticker_id, buy_signal_id, buy_price)
            return trade_id
    
    async def close_trade(self, user_id: int, ticker_id: int, 
                         sell_signal_id: int, sell_price: float):
        """Закрытие сделки"""
        async with self.pool.acquire() as conn:
            # Находим открытую сделку
            trade = await conn.fetchrow('''
                SELECT id, buy_price FROM trades
                WHERE user_id = $1 AND ticker_id = $2 AND status = 'OPEN'
                ORDER BY opened_at DESC
                LIMIT 1
            ''', user_id, ticker_id)
            
            if trade:
                profit_percent = ((sell_price - trade['buy_price']) / trade['buy_price']) * 100
                profit_rub = sell_price - trade['buy_price']
                
                await conn.execute('''
                    UPDATE trades SET
                        sell_signal_id = $1,
                        sell_price = $2,
                        profit_percent = $3,
                        profit_rub = $4,
                        closed_at = NOW(),
                        status = 'CLOSED'
                    WHERE id = $5
                ''', sell_signal_id, sell_price, profit_percent, profit_rub, trade['id'])
    
    async def get_user_open_trades(self, user_id: int) -> List[Dict]:
        """Получение открытых сделок пользователя"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT t.*, tk.symbol FROM trades t
                JOIN tickers tk ON t.ticker_id = tk.id
                WHERE t.user_id = $1 AND t.status = 'OPEN'
                ORDER BY t.opened_at DESC
            ''', user_id)
            return [dict(row) for row in rows]
    
    async def get_user_stats(self, user_id: int) -> Dict:
        """Получение статистики пользователя"""
        async with self.pool.acquire() as conn:
            stats = await conn.fetchrow('''
                SELECT 
                    COUNT(*) as total_trades,
                    COUNT(CASE WHEN profit_percent > 0 THEN 1 END) as profitable_trades,
                    AVG(profit_percent) as avg_profit,
                    SUM(profit_rub) as total_profit,
                    MAX(profit_percent) as best_trade,
                    MIN(profit_percent) as worst_trade
                FROM trades
                WHERE user_id = $1 AND status = 'CLOSED'
            ''', user_id)
            
            return dict(stats) if stats else {}
    
    # === Методы для уведомлений ===
    
    async def log_notification(self, user_id: int, signal_id: int, 
                              delivered: bool = True, error_message: str = None):
        """Логирование отправки уведомления"""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO user_notifications (user_id, signal_id, delivered, error_message)
                VALUES ($1, $2, $3, $4)
            ''', user_id, signal_id, delivered, error_message)
    
    async def get_notification_stats(self, days: int = 7) -> Dict:
        """Статистика по уведомлениям"""
        async with self.pool.acquire() as conn:
            stats = await conn.fetchrow('''
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN delivered THEN 1 END) as delivered,
                    COUNT(CASE WHEN NOT delivered THEN 1 END) as failed
                FROM user_notifications
                WHERE sent_at > NOW() - INTERVAL '%s days'
            ''', days)
            
            return dict(stats) if stats else {}
