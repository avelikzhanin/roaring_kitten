import asyncio
import logging
import os
from datetime import datetime, time
import pytz
from typing import Optional

from telegram import BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

from src.data_provider import TinkoffDataProvider
from src.gpt_analyzer import GPTMarketAnalyzer
from src.database import DatabaseManager
from src.signal_processor import SignalProcessor
from src.message_sender import MessageSender
from src.user_interface import UserInterface

logger = logging.getLogger(__name__)

# Компактная настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ============================================================================
# ТОРГОВОЕ РАСПИСАНИЕ MOEX (актуально на 2025 год):
# ============================================================================
# РАБОЧИЕ ДНИ (Пн-Пт):
#   Основная сессия:  09:50 - 18:50 МСК  
#   Вечерняя сессия:  19:00 - 23:49 МСК
# 
# ВЫХОДНЫЕ ДНИ (Сб-Вс с 1 марта 2025):
#   Дополнительная сессия выходного дня: 10:00 - 19:00 МСК
# 
# Итого: почти 7 дней торгов в неделю!
# ============================================================================

class MarketTimeChecker:
    """Проверка торгового времени MOEX - только основная и вечерняя сессии"""
    
    def __init__(self):
        self.moscow_tz = pytz.timezone('Europe/Moscow')
        # Основная сессия: 09:50 - 18:50 МСК
        self.main_session_start = time(9, 50)
        self.main_session_end = time(18, 50)
        # Вечерняя сессия: 19:00 - 23:49 МСК
        self.evening_session_start = time(19, 0)
        self.evening_session_end = time(23, 49)
        
    def is_market_open(self) -> bool:
        """Проверяет открыт ли рынок (только основная и вечерняя сессии)"""
        now_moscow = datetime.now(self.moscow_tz)
        current_time = now_moscow.time()
        current_weekday = now_moscow.weekday()
        
        # Только рабочие дни
        if current_weekday >= 5:  # Сб, Вс
            return False
        
        # Проверяем две торговые сессии
        main_session = (self.main_session_start <= current_time <= self.main_session_end)
        evening_session = (self.evening_session_start <= current_time <= self.evening_session_end)
        
        return main_session or evening_session

class TradingBot:
    """Основной класс торгового бота с GPT рассчитывающим РЕАЛЬНЫЙ ADX"""
    
    def __init__(self, telegram_token: str, tinkoff_token: str, database_url: str, openai_token: Optional[str] = None):
        self.telegram_token = telegram_token
        self.market_checker = MarketTimeChecker()
        
        # Инициализируем компоненты
        self.tinkoff_provider = TinkoffDataProvider(tinkoff_token)
        self.gpt_analyzer = GPTMarketAnalyzer(openai_token) if openai_token else None
        self.db = DatabaseManager(database_url)
        
        # Создаем модули с правильными зависимостями
        self.signal_processor = SignalProcessor(self.tinkoff_provider, self.db, self.gpt_analyzer)
        self.message_sender = MessageSender(self.db, self.gpt_analyzer, self.tinkoff_provider)
        self.user_interface = UserInterface(self.db, self.signal_processor, self.gpt_analyzer)
        
        # Состояние бота
        self.app: Optional[Application] = None
        self.is_running = False
        self._signal_tasks = {}
        
        strategy_info = "🤖 GPT с РЕАЛЬНЫМ ADX + 📊 EMA20" if self.gpt_analyzer else "📊 Только EMA20"
        logger.info(f"🤖 Бот инициализирован (Стратегия: {strategy_info})")
        
    async def start(self):
        """Запуск бота с проверкой стратегии РЕАЛЬНОГО ADX от GPT"""
        try:
            # 1. Инициализируем БД
            logger.info("🗄️ Инициализация БД...")
            await self.db.initialize()
            
            # 2. НОВАЯ ПРОВЕРКА: Тестируем стратегию с РЕАЛЬНЫМ ADX
            logger.info("🧪 Проверка стратегии с РЕАЛЬНЫМ ADX от GPT...")
            try:
                from src.indicators import TechnicalIndicators
                
                # Быстрый тест индикаторов
                test_prices = [100, 101, 102, 103, 104]
                ema = TechnicalIndicators.calculate_ema(test_prices, 3)
                
                logger.info(f"✅ EMA работает: {ema[-1]:.2f}")
                
                if self.gpt_analyzer:
                    logger.info("✅ GPT подключен - будет рассчитывать РЕАЛЬНЫЙ ADX")
                    logger.info("🎯 КРИТЕРИИ ПОКУПКИ: EMA20 + ADX>25 + +DI>-DI + разница>1")
                    logger.info("🔥 КРИТЕРИЙ ПИКА: ADX>45 (экстремально сильный тренд)")
                else:
                    logger.warning("⚠️ GPT отключен - ADX расчеты недоступны!")
                    logger.warning("🚨 Без GPT качество сигналов будет низким!")
                
                logger.info("🎉 Стратегия с РЕАЛЬНЫМ ADX готова к работе!")
                
            except Exception as e:
                logger.error(f"❌ Ошибка проверки стратегии: {e}")
                logger.error("🚨 Запуск может быть нестабильным!")
            
            # 3. Создаем Telegram приложение
            self.app = Application.builder().token(self.telegram_token).build()
            
            # 4. Передаем app в модули
            self.message_sender.set_app(self.app)
            self.user_interface.set_app(self.app)
            
            # 5. Добавляем обработчики
            self._add_handlers()
            
            # 6. Запускаем мониторинг
            self.is_running = True
            await self._start_monitoring()
            
            # 7. Запускаем Telegram polling
            await self.app.initialize()
            await self.app.start()
            
            # 8. Устанавливаем меню команд
            await self._setup_bot_menu()
            
            await self.app.bot.delete_webhook(drop_pending_updates=True)
            await self.app.updater.start_polling(drop_pending_updates=True)
            
            logger.info("🎉 Бот запущен с РЕАЛЬНЫМ ADX от GPT!")
            await asyncio.gather(*self._signal_tasks.values())
                
        except Exception as e:
            logger.error(f"Ошибка запуска: {e}")
            await self.shutdown()
            raise
    
    async def shutdown(self):
        """Остановка бота"""
        logger.info("🛑 Остановка бота...")
        self.is_running = False
        
        # Отменяем задачи мониторинга
        for symbol, task in self._signal_tasks.items():
            if task and not task.done():
                task.cancel()
        
        # Останавливаем Telegram приложение
        if self.app:
            try:
                if self.app.updater and self.app.updater.running:
                    await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()
            except Exception as e:
                logger.error(f"Ошибка остановки Telegram: {e}")
        
        # Закрываем БД
        await self.db.close()
        logger.info("✅ Бот остановлен")
    
    async def _setup_bot_menu(self):
        """Установка меню команд бота"""
        try:
            commands = [
                BotCommand("portfolio", "📊 Управление подписками на акции"),
                BotCommand("signal", "🔍 Проверить текущие сигналы с ADX"),
            ]
            
            await self.app.bot.set_my_commands(commands)
            logger.info("📱 Меню команд установлено")
            
        except Exception as e:
            logger.warning(f"Не удалось установить меню команд: {e}")
    
    def _add_handlers(self):
        """Добавление обработчиков команд"""
        self.app.add_handler(CommandHandler("start", self.user_interface.start_command))
        self.app.add_handler(CommandHandler("stop", self.user_interface.stop_command))
        self.app.add_handler(CommandHandler("signal", self.user_interface.signal_command))
        self.app.add_handler(CommandHandler("portfolio", self.user_interface.portfolio_command))
        self.app.add_handler(CallbackQueryHandler(self.user_interface.handle_callback))
    
    async def _start_monitoring(self):
        """Запуск мониторинга всех тикеров"""
        available_tickers = await self.db.get_available_tickers()
        
        for ticker in available_tickers:
            symbol = ticker['symbol']
            self._signal_tasks[symbol] = asyncio.create_task(
                self._monitor_ticker(symbol)
            )
        
        logger.info(f"📊 Мониторинг запущен для {len(self._signal_tasks)} акций с РЕАЛЬНЫМ ADX")
    
    async def _monitor_ticker(self, symbol: str):
        """Мониторинг одного тикера с GPT рассчитывающим РЕАЛЬНЫЙ ADX"""
        logger.info(f"🔄 Мониторинг {symbol} запущен (GPT рассчитывает РЕАЛЬНЫЙ ADX)")
        
        while self.is_running:
            try:
                # Проверяем торговое время (только основная и вечерняя сессии)
                if not self.market_checker.is_market_open():
                    # Рынок закрыт - просто ждем 20 минут (как в торговое время)
                    await asyncio.sleep(1200)  # 20 минут
                    continue
                
                # === УМНАЯ СТРАТЕГИЯ С РЕАЛЬНЫМ ADX ОТ GPT ===
                
                # Анализируем рынок: базовый фильтр + GPT рассчитывает РЕАЛЬНЫЙ ADX
                signal = await self.signal_processor.analyze_market(symbol)
                
                # Проверяем пик тренда через РЕАЛЬНЫЙ ADX от GPT (ADX > 45)
                peak_signal = await self.signal_processor.check_peak_trend(symbol)
                
                # Получаем количество активных позиций
                active_positions = await self.db.get_active_positions_count(symbol)
                
                # Логика отправки сигналов
                if signal and active_positions == 0:
                    # Новый сигнал покупки с РЕАЛЬНЫМ ADX от GPT
                    await self.message_sender.send_buy_signal(signal)
                    adx_info = f"ADX={signal.adx:.1f}" if signal.adx > 0 else "ADX=расчет"
                    logger.info(f"📈 Сигнал покупки {symbol}: {signal.price:.2f} ({adx_info}, GPT: {getattr(signal, 'gpt_recommendation', 'N/A')})")
                
                elif peak_signal and active_positions > 0:
                    # Пик тренда (РЕАЛЬНЫЙ ADX > 45 от GPT)
                    await self.message_sender.send_peak_signal(symbol, peak_signal)
                    logger.info(f"🔥 Пик тренда {symbol}: {peak_signal:.2f} (РЕАЛЬНЫЙ ADX > 45)")
                
                elif not signal and active_positions > 0:
                    # Отмена сигнала (РЕАЛЬНЫЕ ADX условия не выполняются)
                    current_price = await self.signal_processor.get_current_price(symbol)
                    await self.message_sender.send_cancel_signal(symbol, current_price)
                    logger.info(f"❌ Отмена сигнала {symbol} (ADX условия нарушены)")
                
                else:
                    # Логируем состояние для отладки
                    if signal:
                        adx_info = f"(ADX={signal.adx:.1f})" if signal.adx > 0 else ""
                        logger.info(f"✅ Сигнал {symbol} остается актуальным {adx_info}")
                    else:
                        logger.info(f"⏳ Ожидаем сигнал {symbol} (анализ ADX...)...")
                
                # Всегда ждем 20 минут
                await asyncio.sleep(1200)  # 20 минут
                
            except asyncio.CancelledError:
                logger.info(f"❌ Мониторинг {symbol} отменен")
                break
            except Exception as e:
                logger.error(f"Ошибка мониторинга {symbol}: {e}")
                await asyncio.sleep(60)  # Ждем минуту при ошибке


async def main():
    """Главная функция с информацией о стратегии РЕАЛЬНОГО ADX от GPT"""
    logger.info("🚀 Запуск котёнка...")
    logger.info("⚡ УМНАЯ СТРАТЕГИЯ: EMA20 + GPT рассчитывает РЕАЛЬНЫЙ ADX")
    
    # Получаем переменные окружения
    telegram_token = os.getenv("TELEGRAM_TOKEN")
    tinkoff_token = os.getenv("TINKOFF_TOKEN") 
    database_url = os.getenv("DATABASE_URL")
    openai_token = os.getenv("OPENAI_API_KEY")
    
    # Валидация
    if not telegram_token:
        logger.error("❌ TELEGRAM_TOKEN не найден")
        return
    if not tinkoff_token:
        logger.error("❌ TINKOFF_TOKEN не найден")
        return
    if not database_url:
        logger.error("❌ DATABASE_URL не найден")
        return
    
    # НОВОЕ ЛОГИРОВАНИЕ с РЕАЛЬНЫМ ADX
    strategy_info = "🤖 GPT с РЕАЛЬНЫМ ADX + 📊 EMA20" if openai_token else "📊 Только EMA20 (не рекомендуется)"
    logger.info(f"🔑 Токены: TG✅ Tinkoff✅ DB✅ GPT{'✅' if openai_token else '❌'}")
    logger.info(f"⚡ Стратегия: {strategy_info}")
    logger.info("🎯 Базовый фильтр: цена > EMA20 + торговое время")
    
    if openai_token:
        logger.info("🤖 GPT будет:")
        logger.info("   📊 Рассчитывать РЕАЛЬНЫЙ ADX из свечных данных")
        logger.info("   ✅ Проверять ADX > 25 (сильный тренд)")
        logger.info("   ✅ Проверять +DI > -DI (восходящее движение)")
        logger.info("   ✅ Проверять разность DI > 1 (достаточная сила)")
        logger.info("   🔥 Определять пик при ADX > 45")
        logger.info("   💾 Сохранять РЕАЛЬНЫЕ значения в БД")
    else:
        logger.warning("⚠️ БЕЗ GPT:")
        logger.warning("   ❌ ADX расчеты недоступны")
        logger.warning("   ❌ Высокий риск ложных сигналов")
        logger.warning("   💡 Рекомендуется настроить OPENAI_API_KEY")
    
    # Проверяем торговое время при запуске
    market_checker = MarketTimeChecker()
    if market_checker.is_market_open():
        logger.info("🟢 Запуск в торговое время")
    else:
        logger.info("🔴 Запуск вне торгового времени")
    
    # Запускаем бота
    bot = TradingBot(
        telegram_token=telegram_token,
        tinkoff_token=tinkoff_token,
        database_url=database_url,
        openai_token=openai_token
    )
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("⌨️ Прерывание")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
    finally:
        await bot.shutdown()


if __name__ == "__main__":
    logger.info("🐱 РЕВУЩИЙ КОТЁНОК - УМНАЯ СТРАТЕГИЯ")
    logger.info("📊 EMA20 + 🤖 GPT рассчитывает РЕАЛЬНЫЙ ADX + ⚡ Точные сигналы")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🔄 Завершено пользователем")
    except Exception as e:
        logger.error(f"💥 Фатальная ошибка: {e}")
        exit(1)
