# src/database.py
import asyncio
import asyncpg
from datetime import datetime
from typing import List, Optional, Dict
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Менеджер базы данных для торгового бота - минимальная версия"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool: Optional[asyncpg.Pool] = None
        
    async def initialize(self):
        """Инициализация подключения к БД"""
        try:
            logger.info(f"🔗 Подключаемся к БД...")
            
            # Создаем пул соединений
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=1,
                max_size=5,
                command_timeout=60
            )
            
            # Проверяем подключение
            async with self.pool.acquire() as conn:
                version = await conn.fetchval('SELECT version()')
                logger.info(f"✅ Подключено к PostgreSQL: {version[:50]}...")
            
            # Создаем таблицы
            await self.create_tables()
            
            # Добавляем SBER если его нет
            await self.ensure_sber_ticker()
            
            logger.info("✅ База данных полностью инициализирована")
            
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации БД: {e}")
            logger.error(f"❌ URL БД: {self.database_url[:20]}...")  # Показываем начало URL для отладки
            raise  # Теперь падаем если БД недоступна
    
    async def close(self):
        """Закрытие подключения"""
        if self.pool:
            await self.pool.close()
            logger.info("📊 Соединение с БД закрыто")
    
    async def create_tables(self):
        """Создание минимального набора таблиц"""
        if not self.pool:
            return
            
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
            
            # Индекс для быстрого поиска
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_users_telegram_id 
                ON users(telegram_id)
            ''')
            
            # Таблица тикеров (пока только SBER)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tickers (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) UNIQUE NOT NULL,
                    figi VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(255)
                )
            ''')
            
            # Таблица сигналов для истории
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id SERIAL PRIMARY KEY,
                    ticker_id INTEGER REFERENCES tickers(id),
                    signal_type VARCHAR(20) NOT NULL,
                    price DECIMAL(10, 2),
                    ema20 DECIMAL(10, 2),
                    adx DECIMAL(5, 2),
                    plus_di DECIMAL(5, 2),
                    minus_di DECIMAL(5, 2),
                    gpt_recommendation VARCHAR(20),
                    gpt_confidence INTEGER,
                    gpt_take_profit DECIMAL(10, 2),
                    gpt_stop_loss DECIMAL(10, 2),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Индекс для быстрой выборки последних сигналов
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_signals_created 
                ON signals(created_at DESC)
            ''')
            
            # Простая таблица для отслеживания активных позиций
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS active_positions (
                    id SERIAL PRIMARY KEY,
                    user_telegram_id BIGINT NOT NULL,
                    ticker_id INTEGER REFERENCES tickers(id),
                    buy_signal_id INTEGER REFERENCES signals(id),
                    buy_price DECIMAL(10, 2),
                    opened_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            logger.info("📋 Таблицы созданы/обновлены")
    
    async def ensure_sber_ticker(self):
        """Добавляем SBER в таблицу тикеров если его нет"""
        if not self.pool:
            return
            
        async with self.pool.acquire() as conn:
            ticker_id = await conn.fetchval('''
                INSERT INTO tickers (symbol, figi, name)
                VALUES ($1, $2, $3)
                ON CONFLICT (symbol) DO NOTHING
                RETURNING id
            ''', 'SBER', 'BBG004730N88', 'Сбербанк')
            
            if ticker_id:
                logger.info(f"✅ Добавлен тикер SBER (id={ticker_id})")
    
    # === Методы для пользователей ===
    
    async def add_or_update_user(self, telegram_id: int, username: str = None, first_name: str = None) -> bool:
        """Добавление или обновление пользователя"""
        if not self.pool:
            return False
            
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO users (telegram_id, username, first_name)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (telegram_id) 
                    DO UPDATE SET 
                        username = COALESCE($2, users.username),
                        first_name = COALESCE($3, users.first_name),
                        last_activity = NOW(),
                        is_active = TRUE
                ''', telegram_id, username, first_name)
                
                logger.info(f"👤 Пользователь {telegram_id} добавлен/обновлен в БД")
                return True
                
        except Exception as e:
            logger.error(f"Ошибка добавления пользователя: {e}")
            return False
    
    async def deactivate_user(self, telegram_id: int):
        """Деактивация пользователя (при /stop)"""
        if not self.pool:
            return
            
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE users 
                    SET is_active = FALSE 
                    WHERE telegram_id = $1
                ''', telegram_id)
                
                logger.info(f"❌ Пользователь {telegram_id} деактивирован")
                
        except Exception as e:
            logger.error(f"Ошибка деактивации пользователя: {e}")
    
    async def get_active_users(self) -> List[int]:
        """Получение списка активных пользователей"""
        if not self.pool:
            return []
            
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT telegram_id 
                    FROM users 
                    WHERE is_active = TRUE
                ''')
                
                return [row['telegram_id'] for row in rows]
                
        except Exception as e:
            logger.error(f"Ошибка получения пользователей: {e}")
            return []
    
    # === Методы для сигналов ===
    
    async def save_signal(self, signal_type: str, price: float, 
                         ema20: float, adx: float, plus_di: float, 
                         minus_di: float, gpt_data: Dict = None) -> Optional[int]:
        """Сохранение сигнала в БД"""
        if not self.pool:
            return None
            
        try:
            async with self.pool.acquire() as conn:
                # Получаем ID тикера SBER
                ticker_id = await conn.fetchval(
                    "SELECT id FROM tickers WHERE symbol = 'SBER'"
                )
                
                if not ticker_id:
                    logger.error("Тикер SBER не найден в БД")
                    return None
                
                # Сохраняем сигнал
                signal_id = await conn.fetchval('''
                    INSERT INTO signals (
                        ticker_id, signal_type, price, ema20, adx, 
                        plus_di, minus_di, gpt_recommendation, 
                        gpt_confidence, gpt_take_profit, gpt_stop_loss
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    RETURNING id
                ''', 
                    ticker_id, signal_type, price, ema20, adx, plus_di, minus_di,
                    gpt_data.get('recommendation') if gpt_data else None,
                    gpt_data.get('confidence') if gpt_data else None,
                    float(gpt_data.get('take_profit', 0) or 0) if gpt_data and gpt_data.get('take_profit') else None,
                    float(gpt_data.get('stop_loss', 0) or 0) if gpt_data and gpt_data.get('stop_loss') else None
                )
                
                logger.info(f"💾 Сигнал {signal_type} сохранен (id={signal_id})")
                return signal_id
                
        except Exception as e:
            logger.error(f"Ошибка сохранения сигнала: {e}")
            return None
    
    async def get_last_buy_signal(self) -> Optional[Dict]:
        """Получение последнего сигнала покупки"""
        if not self.pool:
            return None
            
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('''
                    SELECT * FROM signals 
                    WHERE signal_type = 'BUY' 
                    ORDER BY created_at DESC 
                    LIMIT 1
                ''')
                
                return dict(row) if row else None
                
        except Exception as e:
            logger.error(f"Ошибка получения последнего сигнала: {e}")
            return None
    
    # === Методы для позиций ===
    
    async def open_position(self, telegram_id: int, signal_id: int, buy_price: float):
        """Открытие позиции для пользователя"""
        if not self.pool:
            return
            
        try:
            async with self.pool.acquire() as conn:
                # Получаем ID тикера SBER
                ticker_id = await conn.fetchval(
                    "SELECT id FROM tickers WHERE symbol = 'SBER'"
                )
                
                # Закрываем старые позиции если есть
                await conn.execute('''
                    DELETE FROM active_positions 
                    WHERE user_telegram_id = $1 AND ticker_id = $2
                ''', telegram_id, ticker_id)
                
                # Открываем новую
                await conn.execute('''
                    INSERT INTO active_positions 
                    (user_telegram_id, ticker_id, buy_signal_id, buy_price)
                    VALUES ($1, $2, $3, $4)
                ''', telegram_id, ticker_id, signal_id, buy_price)
                
                logger.info(f"📈 Открыта позиция для {telegram_id} по цене {buy_price}")
                
        except Exception as e:
            logger.error(f"Ошибка открытия позиции: {e}")
    
    async def close_positions(self, signal_type: str = 'SELL'):
        """Закрытие всех активных позиций"""
        if not self.pool:
            return
            
        try:
            async with self.pool.acquire() as conn:
                # Получаем все активные позиции для расчета прибыли
                positions = await conn.fetch('SELECT * FROM active_positions')
                
                if positions:
                    logger.info(f"📊 Закрываем {len(positions)} позиций ({signal_type})")
                
                # Удаляем все активные позиции
                await conn.execute('DELETE FROM active_positions')
                
        except Exception as e:
            logger.error(f"Ошибка закрытия позиций: {e}")
    
    async def get_active_positions_count(self) -> int:
        """Получение количества активных позиций"""
        if not self.pool:
            return 0
            
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(
                    'SELECT COUNT(*) FROM active_positions'
                )
                return count or 0
                
        except Exception as e:
            logger.error(f"Ошибка подсчета позиций: {e}")
            return 0
    
    # === Статистика ===
    
    async def get_stats(self) -> Dict:
        """Получение общей статистики"""
        if not self.pool:
            return {}
            
        try:
            async with self.pool.acquire() as conn:
                stats = {}
                
                # Количество пользователей
                stats['total_users'] = await conn.fetchval(
                    'SELECT COUNT(*) FROM users'
                )
                stats['active_users'] = await conn.fetchval(
                    'SELECT COUNT(*) FROM users WHERE is_active = TRUE'
                )
                
                # Количество сигналов
                stats['total_signals'] = await conn.fetchval(
                    'SELECT COUNT(*) FROM signals'
                )
                stats['buy_signals'] = await conn.fetchval(
                    "SELECT COUNT(*) FROM signals WHERE signal_type = 'BUY'"
                )
                stats['sell_signals'] = await conn.fetchval(
                    "SELECT COUNT(*) FROM signals WHERE signal_type IN ('SELL', 'PEAK')"
                )
                
                # Активные позиции
                stats['open_positions'] = await conn.fetchval(
                    'SELECT COUNT(*) FROM active_positions'
                )
                
                return stats
                
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {}
