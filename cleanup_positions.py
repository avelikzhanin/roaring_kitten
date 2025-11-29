"""
Скрипт для очистки открытых позиций и состояний сигналов
Использование: python cleanup_positions.py
"""
import asyncio
import logging

from database import db

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def cleanup():
    """Очистка открытых позиций и состояний сигналов"""
    
    try:
        # Подключаемся к БД
        await db.connect()
        logger.info("✅ Connected to database")
        
        # 1. Закрываем все открытые позиции
        async with db.pool.acquire() as conn:
            # Получаем количество открытых позиций
            open_count = await conn.fetchval(
                "SELECT COUNT(*) FROM positions WHERE is_open = TRUE"
            )
            logger.info(f"📊 Found {open_count} open positions")
            
            if open_count > 0:
                # Закрываем позиции с нулевой прибылью
                await conn.execute("""
                    UPDATE positions
                    SET 
                        exit_price = entry_price,
                        exit_time = CURRENT_TIMESTAMP,
                        profit_percent = 0,
                        is_open = FALSE
                    WHERE is_open = TRUE
                """)
                logger.info(f"✅ Closed {open_count} positions with 0% profit")
            else:
                logger.info("ℹ️ No open positions to close")
        
        # 2. Очищаем состояния сигналов
        async with db.pool.acquire() as conn:
            # Получаем количество записей
            signal_count = await conn.fetchval(
                "SELECT COUNT(*) FROM signal_states"
            )
            logger.info(f"📊 Found {signal_count} signal states")
            
            if signal_count > 0:
                await conn.execute("DELETE FROM signal_states")
                logger.info(f"✅ Deleted {signal_count} signal states")
            else:
                logger.info("ℹ️ No signal states to delete")
        
        # 3. Статистика после очистки
        async with db.pool.acquire() as conn:
            total_positions = await conn.fetchval(
                "SELECT COUNT(*) FROM positions"
            )
            open_positions = await conn.fetchval(
                "SELECT COUNT(*) FROM positions WHERE is_open = TRUE"
            )
            closed_positions = await conn.fetchval(
                "SELECT COUNT(*) FROM positions WHERE is_open = FALSE"
            )
            
            logger.info("\n" + "="*50)
            logger.info("📊 DATABASE STATISTICS AFTER CLEANUP:")
            logger.info("="*50)
            logger.info(f"Total positions: {total_positions}")
            logger.info(f"Open positions: {open_positions}")
            logger.info(f"Closed positions: {closed_positions}")
            logger.info("="*50 + "\n")
        
        logger.info("🎉 Cleanup completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}", exc_info=True)
        raise
    
    finally:
        # Отключаемся от БД
        await db.disconnect()
        logger.info("👋 Disconnected from database")


if __name__ == "__main__":
    asyncio.run(cleanup())
