#!/usr/bin/env python3
"""
optimizer.py - Запуск оптимизатора SBER на Railway
Используйте этот файл как основной скрипт для оптимизации
"""

import asyncio
import logging
import os
import sys

# Настройка логирования для Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)  # Вывод в Railway консоль
    ]
)

logger = logging.getLogger(__name__)

def check_environment():
    """Проверка окружения Railway"""
    logger.info("🔍 Проверка окружения Railway...")
    
    # Проверяем токен
    token = os.getenv('TINKOFF_TOKEN')
    if not token:
        logger.error("❌ TINKOFF_TOKEN не найден!")
        logger.error("💡 Добавьте токен в Railway:")
        logger.error("   1. Откройте ваш проект в Railway")
        logger.error("   2. Перейдите в Variables")
        logger.error("   3. Добавьте TINKOFF_TOKEN = ваш_токен")
        return False
    
    logger.info("✅ TINKOFF_TOKEN найден")
    
    # Проверяем Python версию
    python_version = sys.version_info
    logger.info(f"🐍 Python версия: {python_version.major}.{python_version.minor}")
    
    if python_version < (3, 8):
        logger.warning("⚠️ Рекомендуется Python 3.8+")
    
    return True

async def run_optimization():
    """Запуск оптимизации с импортом"""
    try:
        # Импортируем оптимизатор (может быть в том же файле или отдельном)
        logger.info("📦 Импорт модулей оптимизатора...")
        
        # Здесь должен быть импорт вашего оптимизатора
        # Например, если вы поместили код выше в этот же файл:
        from sber_optimizer_railway import EnhancedStrategyOptimizer
        
        # Или если создали отдельный файл:
        # from enhanced_optimizer import EnhancedStrategyOptimizer
        
        # Получаем токен
        token = os.getenv('TINKOFF_TOKEN')
        
        # Создаем оптимизатор
        logger.info("🏗️ Создание оптимизатора...")
        optimizer = EnhancedStrategyOptimizer(token)
        
        # Запускаем оптимизацию (60 дней для Railway)
        logger.info("🚀 Запуск оптимизации стратегии SBER...")
        results = await optimizer.run_optimization(test_days=60)
        
        if results:
            # Выводим результаты
            optimizer.print_results(results, top_n=10)
            
            # Сохраняем лучший результат
            best = results[0]
            
            # Можно сохранить в файл для последующего использования
            logger.info("💾 Сохранение лучших параметров...")
            
            with open('best_strategy.txt', 'w') as f:
                f.write("# Лучшие параметры для SBER стратегии\n")
                f.write(f"EMA_PERIOD = {best.params.ema_period}\n")
                f.write(f"ADX_THRESHOLD = {best.params.adx_threshold}\n")
                f.write(f"VOLUME_MULTIPLIER = {best.params.volume_multiplier}\n")
                
                if best.params.stop_loss_pct:
                    f.write(f"STOP_LOSS_PCT = {best.params.stop_loss_pct}\n")
                if best.params.take_profit_pct:
                    f.write(f"TAKE_PROFIT_PCT = {best.params.take_profit_pct}\n")
                if best.params.rsi_period:
                    f.write(f"RSI_PERIOD = {best.params.rsi_period}\n")
                    f.write(f"RSI_OVERBOUGHT = {best.params.rsi_overbought}\n")
                if best.params.avoid_lunch_time:
                    f.write("AVOID_LUNCH_TIME = True\n")
                
                f.write(f"\n# Ожидаемые результаты:\n")
                f.write(f"# Доходность: {best.total_return:+.2f}%\n")
                f.write(f"# Винрейт: {best.win_rate:.1f}%\n")
                f.write(f"# Количество сделок: {best.total_trades}\n")
            
            logger.info("✅ Оптимизация завершена! Результаты сохранены в best_strategy.txt")
            
        else:
            logger.error("❌ Не удалось получить результаты оптимизации")
            
    except ImportError as e:
        logger.error(f"❌ Ошибка импорта: {e}")
        logger.error("💡 Убедитесь, что файл оптимизатора находится в том же каталоге")
    except Exception as e:
        logger.error(f"❌ Ошибка оптимизации: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Главная функция для Railway"""
    print("🚀 SBER Strategy Optimizer для Railway")
    print("=" * 60)
    print("📊 Поиск оптимальных параметров торговой стратегии")
    print("⏱️ Процесс займет 3-5 минут...")
    print("=" * 60)
    
    # Проверяем окружение
    if not check_environment():
        sys.exit(1)
    
    try:
        # Запускаем оптимизацию
        asyncio.run(run_optimization())
        
    except KeyboardInterrupt:
        logger.info("👋 Оптимизация прервана пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

# ===============================================
# ИНСТРУКЦИИ ДЛЯ RAILWAY DEPLOYMENT:
# ===============================================
"""
1. СОЗДАНИЕ ПРОЕКТА:
   - Загрузите этот файл как optimizer.py
   - Добавьте код оптимизатора (из предыдущего артефакта)
   
2. НАСТРОЙКА ПЕРЕМЕННЫХ:
   - TINKOFF_TOKEN = ваш_токен_тинькофф
   
3. НАСТРОЙКА ЗАПУСКА:
   - Start Command: python optimizer.py
   - Build Command: pip install -r requirements.txt
   
4. REQUIREMENTS.TXT:
   tinkoff-investments>=0.2.0b39
   pandas>=2.0.0
   numpy>=1.24.0
   asyncio
   
5. ЗАПУСК:
   - Deploy в Railway
   - Проект запустится автоматически
   - Результаты появятся в логах Railway
   
6. ПОЛУЧЕНИЕ РЕЗУЛЬТАТОВ:
   - Смотрите логи в Railway Dashboard
   - Лучшие параметры будут выведены в консоль
   - Файл best_strategy.txt создастся автоматически
"""
