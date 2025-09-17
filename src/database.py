# src/database.py
import asyncio
import asyncpg
from datetime import datetime
from typing import List, Optional, Dict, Set
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Менеджер базы данных для торгового бота с поддержкой множественных акций (БЕЗ ADX)"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool: Optional[asyncpg.Pool] = None
        
    async def initialize(self):
        """Инициализация подключения к БД с миграцией ADX"""
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
            
            # Создаем таблицы с миграциями (включая удаление ADX)
            await self.create_tables()
            await self.migrate_remove_adx()  # НОВОЕ: Удаляем ADX колонки
            
            # Добавляем тикеры и мигрируем старых пользователей
            await self.ensure_tickers()
            await self.migrate_existing_users()
            
            logger.info("✅ База данных полностью инициализирована (БЕЗ ADX)")
            
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации БД: {e}")
            logger.error(f"❌ URL БД: {self.database_url[:20]}...")
            raise
    
    async def close(self):
        """Закрытие подключения"""
        if self.pool:
            await self.pool.close()
            logger.info("📊 Соединение с БД закрыто")
    
    async def migrate_remove_adx(self):
        """НОВОЕ: Миграция - удаление ADX, plus_di, minus_di из signals"""
        if not self.pool:
            return
            
        try:
            async with self.pool.acquire() as conn:
                # Проверяем, существуют ли колонки ADX
                adx_exists = await conn.fetchval('''
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'signals' AND column_name = 'adx'
                    )
                ''')
                
                if adx_exists:
                    logger.info("🔄 Удаляем устаревшие ADX колонки из signals...")
                    
                    # Удаляем колонки ADX/DI
                    await conn.execute('ALTER TABLE signals DROP COLUMN IF EXISTS adx')
                    await conn.execute('ALTER TABLE signals DROP COLUMN IF EXISTS plus_di')
                    await conn.execute('ALTER TABLE signals DROP COLUMN IF EXISTS minus_di')
                    
                    logger.info("✅ ADX колонки успешно удалены")
                else:
                    logger.info("✅ ADX колонки уже отсутствуют")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка миграции ADX: {e}")
            # Не останавливаем инициализацию из-за ошибки миграции
    
    async def create_tables(self):
        """Создание всех необходимых таблиц БЕЗ ADX полей"""
        if not self.pool:
            return
            
        async with self.pool.acquire() as conn:
            # Таблица пользователей (без изменений)
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
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_users_telegram_id 
                ON users(telegram_id)
            ''')
            
            # Таблица тикеров - создаем базовую структуру
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tickers (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) UNIQUE NOT NULL,
                    figi VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(255)
                )
            ''')
            
            # Добавляем is_active если его нет
            try:
                await conn.execute('''
                    ALTER TABLE tickers 
                    ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE
                ''')
                logger.info("📋 Добавлена колонка is_active в tickers")
            except Exception as e:
                logger.info(f"📋 Колонка is_active уже существует в tickers: {e}")
            
            # НОВАЯ: Таблица подписок пользователей
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_subscriptions (
                    id SERIAL PRIMARY KEY,
                    user_telegram_id BIGINT NOT NULL,
                    ticker_id INTEGER REFERENCES tickers(id),
                    subscribed_at TIMESTAMP DEFAULT NOW(),
                    is_active BOOLEAN DEFAULT TRUE,
                    UNIQUE(user_telegram_id, ticker_id)
                )
            ''')
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_subscriptions_user 
                ON user_subscriptions(user_telegram_id)
            ''')
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_subscriptions_ticker 
                ON user_subscriptions(ticker_id)
            ''')
            
            # ОБНОВЛЕННАЯ таблица сигналов БЕЗ ADX полей
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id SERIAL PRIMARY KEY,
                    signal_type VARCHAR(20) NOT NULL,
                    price DECIMAL(10, 2),
                    ema20 DECIMAL(10, 2),
                    gpt_recommendation VARCHAR(20),
                    gpt_confidence INTEGER,
                    gpt_take_profit DECIMAL(10, 2),
                    gpt_stop_loss DECIMAL(10, 2),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Добавляем ticker_id в signals если нет
            try:
                await conn.execute('''
                    ALTER TABLE signals 
                    ADD COLUMN IF NOT EXISTS ticker_id INTEGER REFERENCES tickers(id)
                ''')
                logger.info("📋 Добавлена колонка ticker_id в signals")
            except Exception as e:
                logger.info(f"📋 Колонка ticker_id уже существует в signals: {e}")
            
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_signals_created 
                ON signals(created_at DESC)
            ''')
            
            # Обновляем таблицу активных позиций
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS active_positions (
                    id SERIAL PRIMARY KEY,
                    user_telegram_id BIGINT NOT NULL,
                    buy_signal_id INTEGER REFERENCES signals(id),
                    buy_price DECIMAL(10, 2),
                    opened_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Добавляем ticker_id в active_positions если нет
            try:
                await conn.execute('''
                    ALTER TABLE active_positions 
                    ADD COLUMN IF NOT EXISTS ticker_id INTEGER REFERENCES tickers(id)
                ''')
                logger.info("📋 Добавлена колонка ticker_id в active_positions")
            except Exception as e:
                logger.info(f"📋 Колонка ticker_id уже существует в active_positions: {e}")
            
            logger.info("📋 Таблицы созданы/обновлены (БЕЗ ADX полей)")
    
    async def ensure_tickers(self):
        """Добавляем все поддерживаемые тикеры"""
        if not self.pool:
            return
            
        tickers_data = [
            ('SBER', 'BBG004730N88', 'Сбербанк'),
            ('LKOH', 'BBG004731032', 'Лукойл'),
            ('GAZP', 'BBG004730RP0', 'Газпром')
        ]
        
        async with self.pool.acquire() as conn:
            for symbol, figi, name in tickers_data:
                try:
                    # Проверяем, существует ли тикер
                    existing = await conn.fetchval(
                        "SELECT id FROM tickers WHERE symbol = $1", symbol
                    )
                    
                    if existing:
                        # Обновляем существующий
                        await conn.execute('''
                            UPDATE tickers 
                            SET figi = $2, name = $3, is_active = TRUE
                            WHERE symbol = $1
                        ''', symbol, figi, name)
                        logger.info(f"✅ Тикер {symbol} обновлен (id={existing})")
                    else:
                        # Вставляем новый
                        ticker_id = await conn.fetchval('''
                            INSERT INTO tickers (symbol, figi, name, is_active)
                            VALUES ($1, $2, $3, TRUE)
                            RETURNING id
                        ''', symbol, figi, name)
                        logger.info(f"✅ Тикер {symbol} добавлен (id={ticker_id})")
                        
                except Exception as e:
                    logger.error(f"❌ Ошибка обработки тикера {symbol}: {e}")
    
    async def migrate_existing_users(self):
        """Миграция существующих пользователей - подписываем на SBER"""
        if not self.pool:
            return
            
        try:
            async with self.pool.acquire() as conn:
                # Получаем ID тикера SBER
                sber_id = await conn.fetchval(
                    "SELECT id FROM tickers WHERE symbol = 'SBER'"
                )
                
                if not sber_id:
                    logger.error("❌ Тикер SBER не найден для миграции")
                    return
                
                # Подписываем всех активных пользователей на SBER (если еще не подписаны)
                migrated = await conn.execute('''
                    INSERT INTO user_subscriptions (user_telegram_id, ticker_id)
                    SELECT telegram_id, $1 
                    FROM users 
                    WHERE is_active = TRUE
                    ON CONFLICT (user_telegram_id, ticker_id) DO NOTHING
                ''', sber_id)
                
                logger.info(f"🔄 Миграция пользователей завершена: {migrated}")
                
        except Exception as e:
            logger.error(f"❌ Ошибка миграции пользователей: {e}")
    
    # === Методы для работы с подписками (без изменений) ===
    
    async def get_user_subscriptions(self, telegram_id: int) -> List[Dict]:
        """Получение подписок пользователя"""
        if not self.pool:
            return []
            
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT t.id, t.symbol, t.figi, t.name, us.subscribed_at
                    FROM user_subscriptions us
                    JOIN tickers t ON us.ticker_id = t.id
                    WHERE us.user_telegram_id = $1 AND us.is_active = TRUE AND t.is_active = TRUE
                    ORDER BY t.symbol
                ''', telegram_id)
                
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Ошибка получения подписок для {telegram_id}: {e}")
            return []
    
    async def get_available_tickers(self) -> List[Dict]:
        """Получение всех доступных тикеров"""
        if not self.pool:
            return []
            
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT id, symbol, figi, name
                    FROM tickers
                    WHERE is_active = TRUE
                    ORDER BY symbol
                ''')
                
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Ошибка получения тикеров: {e}")
            return []
    
    async def subscribe_user_to_ticker(self, telegram_id: int, symbol: str) -> bool:
        """Подписка пользователя на тикер"""
        if not self.pool:
            return False
            
        try:
            async with self.pool.acquire() as conn:
                # Получаем ID тикера
                ticker_id = await conn.fetchval(
                    "SELECT id FROM tickers WHERE symbol = $1 AND is_active = TRUE",
                    symbol
                )
                
                if not ticker_id:
                    logger.error(f"Тикер {symbol} не найден")
                    return False
                
                # Добавляем подписку
                await conn.execute('''
                    INSERT INTO user_subscriptions (user_telegram_id, ticker_id)
                    VALUES ($1, $2)
                    ON CONFLICT (user_telegram_id, ticker_id) 
                    DO UPDATE SET is_active = TRUE, subscribed_at = NOW()
                ''', telegram_id, ticker_id)
                
                logger.info(f"✅ Пользователь {telegram_id} подписан на {symbol}")
                return True
                
        except Exception as e:
            logger.error(f"Ошибка подписки {telegram_id} на {symbol}: {e}")
            return False
    
    async def unsubscribe_user_from_ticker(self, telegram_id: int, symbol: str) -> bool:
        """Отписка пользователя от тикера"""
        if not self.pool:
            return False
            
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute('''
                    UPDATE user_subscriptions 
                    SET is_active = FALSE
                    FROM tickers t
                    WHERE user_subscriptions.ticker_id = t.id 
                    AND user_subscriptions.user_telegram_id = $1 
                    AND t.symbol = $2
                ''', telegram_id, symbol)
                
                logger.info(f"✅ Пользователь {telegram_id} отписан от {symbol}")
                return True
                
        except Exception as e:
            logger.error(f"Ошибка отписки {telegram_id} от {symbol}: {e}")
            return False
    
    async def get_subscribers_for_ticker(self, symbol: str) -> List[int]:
        """Получение подписчиков конкретного тикера"""
        if not self.pool:
            return []
            
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT DISTINCT us.user_telegram_id
                    FROM user_subscriptions us
                    JOIN tickers t ON us.ticker_id = t.id
                    JOIN users u ON us.user_telegram_id = u.telegram_id
                    WHERE t.symbol = $1 
                    AND us.is_active = TRUE 
                    AND u.is_active = TRUE
                    AND t.is_active = TRUE
                ''', symbol)
                
                return [row['user_telegram_id'] for row in rows]
                
        except Exception as e:
            logger.error(f"Ошибка получения подписчиков {symbol}: {e}")
            return []
    
    async def get_ticker_info(self, symbol: str) -> Optional[Dict]:
        """Получение информации о тикере"""
        if not self.pool:
            return None
            
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('''
                    SELECT id, symbol, figi, name
                    FROM tickers
                    WHERE symbol = $1 AND is_active = TRUE
                ''', symbol)
                
                return dict(row) if row else None
                
        except Exception as e:
            logger.error(f"Ошибка получения информации о {symbol}: {e}")
            return None
    
    # === Обновленные методы для пользователей (без изменений) ===
    
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
                # Деактивируем пользователя
                await conn.execute('''
                    UPDATE users 
                    SET is_active = FALSE 
                    WHERE telegram_id = $1
                ''', telegram_id)
                
                # Деактивируем все его подписки
                await conn.execute('''
                    UPDATE user_subscriptions 
                    SET is_active = FALSE 
                    WHERE user_telegram_id = $1
                ''', telegram_id)
                
                logger.info(f"❌ Пользователь {telegram_id} деактивирован")
                
        except Exception as e:
            logger.error(f"Ошибка деактивации пользователя: {e}")
    
    # === ОБНОВЛЕННЫЕ методы для сигналов БЕЗ ADX ===
    
    async def save_signal(self, symbol: str, signal_type: str, price: float, 
                         ema20: float, gpt_data: Dict = None) -> Optional[int]:
        """Сохранение сигнала в БД БЕЗ ADX полей"""
        if not self.pool:
            return None
            
        try:
            async with self.pool.acquire() as conn:
                # Получаем ID тикера
                ticker_id = await conn.fetchval(
                    "SELECT id FROM tickers WHERE symbol = $1", symbol
                )
                
                if not ticker_id:
                    logger.error(f"Тикер {symbol} не найден в БД")
                    return None
                
                # Сохраняем сигнал БЕЗ ADX полей
                signal_id = await conn.fetchval('''
                    INSERT INTO signals (
                        ticker_id, signal_type, price, ema20, 
                        gpt_recommendation, gpt_confidence, gpt_take_profit, gpt_stop_loss
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING id
                ''', 
                    ticker_id, signal_type, price, ema20,
                    gpt_data.get('recommendation') if gpt_data else None,
                    gpt_data.get('confidence') if gpt_data else None,
                    float(gpt_data.get('take_profit', 0) or 0) if gpt_data and gpt_data.get('take_profit') else None,
                    float(gpt_data.get('stop_loss', 0) or 0) if gpt_data and gpt_data.get('stop_loss') else None
                )
                
                logger.info(f"💾 Сигнал {signal_type} для {symbol} сохранен (id={signal_id}) БЕЗ ADX")
                return signal_id
                
        except Exception as e:
            logger.error(f"Ошибка сохранения сигнала для {symbol}: {e}")
            return None
    
    # === Обновленные методы для позиций (без изменений) ===
    
    async def open_position(self, telegram_id: int, symbol: str, signal_id: int, buy_price: float):
        """Открытие позиции для пользователя"""
        if not self.pool:
            return
            
        try:
            async with self.pool.acquire() as conn:
                # Получаем ID тикера
                ticker_id = await conn.fetchval(
                    "SELECT id FROM tickers WHERE symbol = $1", symbol
                )
                
                if not ticker_id:
                    logger.error(f"Тикер {symbol} не найден")
                    return
                
                # Закрываем старые позиции для этого тикера
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
                
                logger.info(f"📈 Открыта позиция {symbol} для {telegram_id} по цене {buy_price}")
                
        except Exception as e:
            logger.error(f"Ошибка открытия позиции {symbol}: {e}")
    
    async def close_positions(self, symbol: str, signal_type: str = 'SELL'):
        """Закрытие всех активных позиций по тикеру"""
        if not self.pool:
            return
            
        try:
            async with self.pool.acquire() as conn:
                # Получаем ID тикера
                ticker_id = await conn.fetchval(
                    "SELECT id FROM tickers WHERE symbol = $1", symbol
                )
                
                if not ticker_id:
                    logger.error(f"Тикер {symbol} не найден")
                    return
                
                # Получаем все активные позиции для расчета прибыли
                positions = await conn.fetch('''
                    SELECT * FROM active_positions WHERE ticker_id = $1
                ''', ticker_id)
                
                if positions:
                    logger.info(f"📊 Закрываем {len(positions)} позиций {symbol} ({signal_type})")
                
                # Удаляем все активные позиции для этого тикера
                await conn.execute('''
                    DELETE FROM active_positions WHERE ticker_id = $1
                ''', ticker_id)
                
        except Exception as e:
            logger.error(f"Ошибка закрытия позиций {symbol}: {e}")
    
    async def get_active_positions_count(self, symbol: str = None) -> int:
        """Получение количества активных позиций"""
        if not self.pool:
            return 0
            
        try:
            async with self.pool.acquire() as conn:
                if symbol:
                    # Для конкретного тикера
                    ticker_id = await conn.fetchval(
                        "SELECT id FROM tickers WHERE symbol = $1", symbol
                    )
                    if not ticker_id:
                        return 0
                    
                    count = await conn.fetchval(
                        'SELECT COUNT(*) FROM active_positions WHERE ticker_id = $1',
                        ticker_id
                    )
                else:
                    # Общее количество
                    count = await conn.fetchval(
                        'SELECT COUNT(*) FROM active_positions'
                    )
                
                return count or 0
                
        except Exception as e:
            logger.error(f"Ошибка подсчета позиций: {e}")
            return 0
    
    async def get_positions_for_profit_calculation(self, symbol: str) -> List[Dict]:
        """Получение позиций для расчета прибыли"""
        if not self.pool:
            return []
            
        try:
            async with self.pool.acquire() as conn:
                ticker_id = await conn.fetchval(
                    "SELECT id FROM tickers WHERE symbol = $1", symbol
                )
                
                if not ticker_id:
                    return []
                
                rows = await conn.fetch('''
                    SELECT buy_price, COUNT(*) as position_count
                    FROM active_positions
                    WHERE ticker_id = $1
                    GROUP BY buy_price
                ''', ticker_id)
                
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Ошибка получения позиций для {symbol}: {e}")
            return []
    
    # === Методы совместимости (для старого кода) ===
    
    async def get_active_users(self) -> List[int]:
        """УСТАРЕВШИЙ: Получение списка всех активных пользователей (для совместимости)"""
        logger.warning("⚠️ Используется устаревший метод get_active_users(). Используйте get_subscribers_for_ticker()")
        return await self.get_subscribers_for_ticker('SBER')
    
    async def get_last_buy_signal(self, symbol: str = 'SBER') -> Optional[Dict]:
        """Получение последнего сигнала покупки для тикера БЕЗ ADX"""
        if not self.pool:
            return None
            
        try:
            async with self.pool.acquire() as conn:
                ticker_id = await conn.fetchval(
                    "SELECT id FROM tickers WHERE symbol = $1", symbol
                )
                
                if not ticker_id:
                    return None
                
                row = await conn.fetchrow('''
                    SELECT * FROM signals 
                    WHERE ticker_id = $1 AND signal_type = 'BUY' 
                    ORDER BY created_at DESC 
                    LIMIT 1
                ''', ticker_id)
                
                return dict(row) if row else None
                
        except Exception as e:
            logger.error(f"Ошибка получения последнего сигнала для {symbol}: {e}")
            return None
    
    # === Статистика ===
    
    async def get_stats(self) -> Dict:
        """Получение общей статистики"""
        if not self.pool:
            return {}
            
        try:
            async with self.pool.acquire() as conn:
                stats = {}
                
                # Пользователи
                stats['total_users'] = await conn.fetchval(
                    'SELECT COUNT(*) FROM users'
                )
                stats['active_users'] = await conn.fetchval(
                    'SELECT COUNT(*) FROM users WHERE is_active = TRUE'
                )
                
                # Подписки
                stats['total_subscriptions'] = await conn.fetchval(
                    'SELECT COUNT(*) FROM user_subscriptions WHERE is_active = TRUE'
                )
                
                # Сигналы (БЕЗ ADX статистики)
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
                
                # Статистика по тикерам
                ticker_stats = await conn.fetch('''
                    SELECT t.symbol, COUNT(us.id) as subscribers
                    FROM tickers t
                    LEFT JOIN user_subscriptions us ON t.id = us.ticker_id AND us.is_active = TRUE
                    WHERE t.is_active = TRUE
                    GROUP BY t.symbol
                    ORDER BY t.symbol
                ''')
                
                stats['ticker_subscriptions'] = {row['symbol']: row['subscribers'] for row in ticker_stats}
                
                return stats
                
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {}
