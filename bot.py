import asyncio
import logging
import os
from datetime import datetime
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

class TradingBot:
    """Основной класс торгового бота"""
    
    def __init__(self, telegram_token: str, tinkoff_token: str, database_url: str, openai_token: Optional[str] = None):
        self.telegram_token = telegram_token
        
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
        
        logger.info(f"🤖 Бот инициализирован (GPT: {'✅' if self.gpt_analyzer else '❌'})")
        
    async def start(self):
        """Запуск бота"""
        try:
            # 1. Инициализируем БД
            logger.info("🗄️ Инициализация БД...")
            await self.db.initialize()
            
            # 2. Создаем Telegram приложение
            self.app = Application.builder().token(self.telegram_token).build()
            
            # 3. Передаем app в модули
            self.message_sender.set_app(self.app)
            self.user_interface.set_app(self.app)
            
            # 4. Добавляем обработчики
            self._add_handlers()
            
            # 5. Запускаем мониторинг
            self.is_running = True
            await self._start_monitoring()
            
            # 6. Запускаем Telegram polling
            await self.app.initialize()
            await self.app.start()
            
            # 7. Устанавливаем меню команд
            await self._setup_bot_menu()
            
            await self.app.bot.delete_webhook(drop_pending_updates=True)
            await self.app.updater.start_polling(drop_pending_updates=True)
            
            logger.info("🎉 Бот запущен!")
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
                BotCommand("Выбрать акции", "📊 Управление подписками на акции"),
                BotCommand("signal", "🔍 Проверить текущие сигналы"),
            ]
            
            await self.app.bot.set_my_commands(commands)
            logger.info("📱 Меню команд установлено")
            
        except Exception as e:
            logger.warning(f"Не удалось установить меню команд: {e}")
            # Не критично, продолжаем работу
    
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
        
        logger.info(f"📊 Мониторинг запущен для {len(self._signal_tasks)} акций")
    
    async def _monitor_ticker(self, symbol: str):
        """Мониторинг одного тикера"""
        logger.info(f"🔄 Мониторинг {symbol} запущен")
        
        while self.is_running:
            try:
                # Анализируем рынок
                signal = await self.signal_processor.analyze_market(symbol)
                peak_signal = await self.signal_processor.check_peak_trend(symbol)
                active_positions = await self.db.get_active_positions_count(symbol)
                
                # Логика отправки сигналов
                if signal and active_positions == 0:
                    # Новый сигнал покупки
                    await self.message_sender.send_buy_signal(signal)
                    logger.info(f"📈 Сигнал покупки {symbol}: {signal.price:.2f}")
                
                elif peak_signal and active_positions > 0:
                    # Пик тренда
                    await self.message_sender.send_peak_signal(symbol, peak_signal)
                    logger.info(f"🔥 Пик тренда {symbol}: {peak_signal:.2f}")
                
                elif not signal and active_positions > 0:
                    # Отмена сигнала
                    current_price = await self.signal_processor.get_current_price(symbol)
                    await self.message_sender.send_cancel_signal(symbol, current_price)
                    logger.info(f"❌ Отмена сигнала {symbol}")
                
                # Пауза между проверками
                await asyncio.sleep(1200)  # 20 минут
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка мониторинга {symbol}: {e}")
                await asyncio.sleep(60)


async def main():
    """Главная функция"""
    logger.info("🚀 Запуск котёнка...")
    
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
    
    logger.info(f"🔑 Токены: TG✅ Tinkoff✅ DB✅ GPT{'✅' if openai_token else '❌'}")
    
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
    logger.info("🐱 РЕВУЩИЙ КОТЁНОК - МУЛЬТИАКЦИИ")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🔄 Завершено пользователем")
    except Exception as e:
        logger.error(f"💥 Фатальная ошибка: {e}")
        exit(1)
