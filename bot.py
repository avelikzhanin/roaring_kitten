import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import pandas as pd
import numpy as np
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import Conflict, NetworkError, TimedOut
import openai
from dataclasses import dataclass
import json

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Подавляем избыточные логи
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

@dataclass
class TradingSignal:
    symbol: str
    signal_type: str  # 'BUY' или 'SELL'
    price: float
    confidence: float
    timestamp: datetime
    analysis: str

class DataProvider:
    def __init__(self, token: str):
        self.token = token
        self.logger = logging.getLogger(__name__)
    
    async def get_candles(self, symbol: str, days: int = 5) -> pd.DataFrame:
        """Получение исторических данных"""
        try:
            from tinkoff.invest import Client, CandleInterval
            from tinkoff.invest.utils import now
            
            async with Client(self.token) as client:
                end_time = now()
                start_time = end_time - timedelta(days=days)
                
                self.logger.info(f"Запрос данных {symbol} с {start_time} по {end_time}")
                
                # Получаем FIGI инструмента
                instruments = await client.instruments.shares()
                figi = None
                for instrument in instruments.instruments:
                    if instrument.ticker == symbol:
                        figi = instrument.figi
                        break
                
                if not figi:
                    raise ValueError(f"Инструмент {symbol} не найден")
                
                # Получаем свечи
                candles_response = await client.market_data.get_candles(
                    figi=figi,
                    from_=start_time,
                    to=end_time,
                    interval=CandleInterval.CANDLE_INTERVAL_HOUR
                )
                
                self.logger.info(f"Получено {len(candles_response.candles)} свечей")
                
                # Преобразуем в DataFrame
                data = []
                for candle in candles_response.candles:
                    data.append({
                        'timestamp': candle.time,
                        'open': float(candle.open.units + candle.open.nano / 1e9),
                        'high': float(candle.high.units + candle.high.nano / 1e9),
                        'low': float(candle.low.units + candle.low.nano / 1e9),
                        'close': float(candle.close.units + candle.close.nano / 1e9),
                        'volume': candle.volume
                    })
                
                df = pd.DataFrame(data)
                df.set_index('timestamp', inplace=True)
                return df
                
        except Exception as e:
            self.logger.error(f"Ошибка получения данных: {e}")
            raise

class TechnicalAnalyzer:
    @staticmethod
    def calculate_ema(data: pd.Series, period: int) -> pd.Series:
        """Расчет экспоненциальной скользящей средней"""
        return data.ewm(span=period).mean()
    
    @staticmethod
    def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Dict[str, float]:
        """Расчет ADX и направленных индикаторов"""
        try:
            # Расчет True Range
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            
            # Расчет направленных движений
            dm_plus = np.where((high - high.shift(1)) > (low.shift(1) - low), 
                              np.maximum(high - high.shift(1), 0), 0)
            dm_minus = np.where((low.shift(1) - low) > (high - high.shift(1)), 
                               np.maximum(low.shift(1) - low, 0), 0)
            
            # Сглаживание
            tr_smooth = pd.Series(tr).rolling(window=period).mean()
            dm_plus_smooth = pd.Series(dm_plus).rolling(window=period).mean()
            dm_minus_smooth = pd.Series(dm_minus).rolling(window=period).mean()
            
            # Расчет DI
            di_plus = 100 * dm_plus_smooth / tr_smooth
            di_minus = 100 * dm_minus_smooth / tr_smooth
            
            # Расчет ADX
            dx = 100 * abs(di_plus - di_minus) / (di_plus + di_minus)
            adx = dx.rolling(window=period).mean()
            
            return {
                'adx': adx.iloc[-1] if not adx.empty else 0,
                'di_plus': di_plus.iloc[-1] if not di_plus.empty else 0,
                'di_minus': di_minus.iloc[-1] if not di_minus.empty else 0
            }
        except Exception as e:
            logger.error(f"Ошибка расчета ADX: {e}")
            return {'adx': 0, 'di_plus': 0, 'di_minus': 0}

class GPTAnalyzer:
    def __init__(self, api_key: str):
        self.client = openai.OpenAI(api_key=api_key)
        self.logger = logging.getLogger(__name__)
    
    async def analyze_market_data(self, df: pd.DataFrame, technical_indicators: Dict) -> str:
        """Анализ рыночных данных с помощью GPT"""
        try:
            # Подготовка данных для анализа
            recent_data = df.tail(10)
            price_change = ((df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2]) * 100
            
            prompt = f"""
            Проанализируй следующие рыночные данные для принятия торгового решения:
            
            Текущая цена: {df['close'].iloc[-1]:.2f}
            Изменение цены: {price_change:.2f}%
            
            Технические индикаторы:
            - EMA20: {technical_indicators.get('ema20', 0):.2f}
            - ADX: {technical_indicators.get('adx', 0):.2f}
            - +DI: {technical_indicators.get('di_plus', 0):.2f}
            - -DI: {technical_indicators.get('di_minus', 0):.2f}
            
            Последние 5 свечей:
            {recent_data[['open', 'high', 'low', 'close', 'volume']].to_string()}
            
            Дай краткий анализ (до 200 слов) с рекомендацией: BUY, SELL или HOLD.
            Укажи уровень уверенности от 1 до 10.
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Ты опытный трейдер и технический аналитик."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.3
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            self.logger.error(f"Ошибка GPT анализа: {e}")
            return "Анализ недоступен"

class TradingBot:
    def __init__(self, tinkoff_token: str, openai_key: str):
        self.data_provider = DataProvider(tinkoff_token)
        self.analyzer = TechnicalAnalyzer()
        self.gpt_analyzer = GPTAnalyzer(openai_key) if openai_key else None
        self.logger = logging.getLogger(__name__)
        self.subscribers = set()
        
    async def analyze_market(self, symbol: str = "SBER") -> Optional[TradingSignal]:
        """Анализ рынка и генерация сигналов"""
        try:
            # Получаем данные
            df = await self.data_provider.get_candles(symbol)
            if df.empty:
                return None
            
            # Рассчитываем индикаторы
            ema20 = self.analyzer.calculate_ema(df['close'], 20)
            adx_data = self.analyzer.calculate_adx(df['high'], df['low'], df['close'])
            
            current_price = df['close'].iloc[-1]
            current_ema = ema20.iloc[-1]
            
            # Логирование для отладки
            self.logger.info("🔍 ОТЛАДКА ИНДИКАТОРОВ:")
            self.logger.info(f"💰 Цена: {current_price:.2f} ₽ | EMA20: {current_ema:.2f} ₽")
            self.logger.info(f"📊 ADX: {adx_data['adx']:.2f} | +DI: {adx_data['di_plus']:.2f} | -DI: {adx_data['di_minus']:.2f}")
            
            # Проверяем условия для сигнала
            conditions = {
                'price_above_ema': current_price > current_ema,
                'strong_trend': adx_data['adx'] > 25,
                'bullish_momentum': adx_data['di_plus'] > adx_data['di_minus'],
                'significant_difference': abs(adx_data['di_plus'] - adx_data['di_minus']) > 1
            }
            
            # Логирование условий
            self.logger.info(f"   1. Цена > EMA20: {'✅' if conditions['price_above_ema'] else '❌'}")
            self.logger.info(f"   2. ADX > 25: {'✅' if conditions['strong_trend'] else '❌'}")
            self.logger.info(f"   3. +DI > -DI: {'✅' if conditions['bullish_momentum'] else '❌'}")
            self.logger.info(f"   4. Разница DI > 1: {'✅' if conditions['significant_difference'] else '❌'}")
            
            conditions_met = sum(conditions.values())
            self.logger.info(f"⏳ Условия не выполнены: {conditions_met}/4")
            
            # Генерируем сигнал если все условия выполнены
            if all(conditions.values()):
                # GPT анализ если доступен
                gpt_analysis = ""
                if self.gpt_analyzer:
                    technical_indicators = {
                        'ema20': current_ema,
                        'adx': adx_data['adx'],
                        'di_plus': adx_data['di_plus'],
                        'di_minus': adx_data['di_minus']
                    }
                    gpt_analysis = await self.gpt_analyzer.analyze_market_data(df, technical_indicators)
                
                signal = TradingSignal(
                    symbol=symbol,
                    signal_type='BUY',
                    price=current_price,
                    confidence=0.8,
                    timestamp=datetime.now(),
                    analysis=gpt_analysis
                )
                
                self.logger.info(f"🚀 СИГНАЛ НАЙДЕН: {signal.signal_type} {symbol} по цене {signal.price:.2f}")
                return signal
            
            return None
            
        except Exception as e:
            self.logger.error(f"Ошибка анализа рынка: {e}")
            return None

# Telegram Bot
class TelegramNotifier:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.application = None
        self.trading_bot = None
        self.subscribers = set()
        self.logger = logging.getLogger(__name__)
        
    async def setup_bot(self, trading_bot: TradingBot):
        """Настройка бота с обработкой конфликтов"""
        self.trading_bot = trading_bot
        
        # Создаем приложение
        self.application = Application.builder().token(self.bot_token).build()
        
        # Добавляем обработчики команд
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("stop", self.stop_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("analyze", self.analyze_command))
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        user_id = update.effective_user.id
        self.subscribers.add(user_id)
        
        welcome_message = """
🤖 Добро пожаловать в Ревущего котёнка!

📊 Доступные команды:
/start - Подписаться на сигналы
/stop - Отписаться от сигналов  
/status - Текущий статус
/analyze - Анализ рынка

🔥 Бот автоматически анализирует рынок и отправляет торговые сигналы!
        """
        
        await update.message.reply_text(welcome_message)
        self.logger.info(f"Новый подписчик: {user_id}")
    
    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /stop"""
        user_id = update.effective_user.id
        self.subscribers.discard(user_id)
        await update.message.reply_text("❌ Вы отписались от уведомлений")
        self.logger.info(f"Пользователь отписался: {user_id}")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /status"""
        status_message = f"""
📊 Статус бота:
👥 Подписчиков: {len(self.subscribers)}
🤖 GPT анализ: {'✅ Активен' if self.trading_bot.gpt_analyzer else '❌ Отключен'}
⏰ Время: {datetime.now().strftime('%H:%M:%S')}
        """
        await update.message.reply_text(status_message)
    
  


    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /analyze"""
        await update.message.reply_text("🔍 Анализирую рынок...")
        
        try:
            signal = await self.trading_bot.analyze_market()
            if signal:
                message = self.format_signal_message(signal)
                await update.message.reply_text(message, parse_mode='HTML')
            else:
                await update.message.reply_text("📊 Сигналов не найдено. Ожидаем подходящих условий...")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка анализа: {str(e)}")
            self.logger.error(f"Ошибка в команде analyze: {e}")
    
    def format_signal_message(self, signal: TradingSignal) -> str:
        """Форматирование сообщения с сигналом"""
        emoji = "🚀" if signal.signal_type == "BUY" else "📉"
        
        message = f"""
{emoji} <b>ТОРГОВЫЙ СИГНАЛ</b>

📈 <b>{signal.symbol}</b>
🎯 <b>{signal.signal_type}</b>
💰 Цена: <b>{signal.price:.2f} ₽</b>
📊 Уверенность: <b>{signal.confidence:.0%}</b>
⏰ Время: <b>{signal.timestamp.strftime('%H:%M:%S')}</b>

{signal.analysis if signal.analysis else ''}
        """
        return message
    
    async def send_signal_to_subscribers(self, signal: TradingSignal):
        """Отправка сигнала всем подписчикам"""
        if not self.subscribers:
            return
            
        message = self.format_signal_message(signal)
        
        for user_id in self.subscribers.copy():
            try:
                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode='HTML'
                )
            except Exception as e:
                self.logger.error(f"Ошибка отправки сообщения пользователю {user_id}: {e}")
                # Удаляем неактивных пользователей
                self.subscribers.discard(user_id)
    
    async def start_bot_with_retry(self):
        """Запуск бота с обработкой конфликтов"""
        max_retries = 5
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"🤖 Попытка запуска бота {attempt + 1}/{max_retries}")
                
                # Инициализируем бота
                await self.application.initialize()
                await self.application.start()
                
                # Очищаем webhook и pending updates
                await self.application.bot.delete_webhook(drop_pending_updates=True)
                
                # Запускаем polling
                await self.application.updater.start_polling(
                    drop_pending_updates=True,
                    allowed_updates=Update.ALL_TYPES
                )
                
                self.logger.info("✅ Telegram бот успешно запущен")
                return True
                
            except Conflict as e:
                if attempt < max_retries - 1:
                    self.logger.warning(f"⚠️ Конфликт с другим экземпляром бота. Попытка {attempt + 1}/{max_retries}")
                    self.logger.warning(f"Ждем {retry_delay} секунд перед повторной попыткой...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Экспоненциальная задержка
                else:
                    self.logger.error("❌ Не удалось запустить бота после всех попыток")
                    raise
            except (NetworkError, TimedOut) as e:
                if attempt < max_retries - 1:
                    self.logger.warning(f"⚠️ Сетевая ошибка: {e}. Попытка {attempt + 1}/{max_retries}")
                    await asyncio.sleep(retry_delay)
                else:
                    self.logger.error("❌ Сетевые ошибки после всех попыток")
                    raise
            except Exception as e:
                self.logger.error(f"❌ Неожиданная ошибка при запуске бота: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                else:
                    raise
        
        return False
    
    async def stop_bot(self):
        """Остановка бота"""
        if self.application:
            try:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
                self.logger.info("🛑 Telegram бот остановлен")
            except Exception as e:
                self.logger.error(f"Ошибка при остановке бота: {e}")

# Основной класс приложения
class TradingApp:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.trading_bot = None
        self.telegram_notifier = None
        self.running = False
        
        # Загружаем конфигурацию
        self.config = self.load_config()
        
    def load_config(self) -> Dict[str, Any]:
        """Загрузка конфигурации из переменных окружения"""
        config = {
            'tinkoff_token': os.getenv('TINKOFF_TOKEN'),
            'telegram_token': os.getenv('TELEGRAM_TOKEN'),
            'openai_key': os.getenv('OPENAI_API_KEY'),
            'check_interval': int(os.getenv('CHECK_INTERVAL', '300')),  # 5 минут по умолчанию
            'symbol': os.getenv('TRADING_SYMBOL', 'SBER')
        }
        
        # Проверяем обязательные параметры
        required_params = ['tinkoff_token', 'telegram_token']
        missing_params = [param for param in required_params if not config[param]]
        
        if missing_params:
            raise ValueError(f"Отсутствуют обязательные параметры: {missing_params}")
        
        return config
    
    async def initialize(self):
        """Инициализация компонентов"""
        try:
            # Создаем торгового бота
            self.trading_bot = TradingBot(
                tinkoff_token=self.config['tinkoff_token'],
                openai_key=self.config['openai_key']
            )
            
            # Создаем Telegram уведомитель
            self.telegram_notifier = TelegramNotifier(self.config['telegram_token'])
            await self.telegram_notifier.setup_bot(self.trading_bot)
            
            self.logger.info("✅ Все компоненты инициализированы")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации: {e}")
            raise
    
    async def market_analysis_loop(self):
        """Основной цикл анализа рынка"""
        while self.running:
            try:
                self.logger.info("🔍 Выполняется анализ рынка...")
                
                # Анализируем рынок
                signal = await self.trading_bot.analyze_market(self.config['symbol'])
                
                if signal:
                    self.logger.info(f"🎯 Найден сигнал: {signal.signal_type} {signal.symbol}")
                    
                    # Отправляем сигнал подписчикам
                    if self.telegram_notifier:
                        await self.telegram_notifier.send_signal_to_subscribers(signal)
                else:
                    self.logger.info("📊 Ожидаем сигнал...")
                
                # Ждем до следующей проверки
                await asyncio.sleep(self.config['check_interval'])
                
            except Exception as e:
                self.logger.error(f"❌ Ошибка в цикле анализа: {e}")
                await asyncio.sleep(60)  # Ждем минуту при ошибке
    
    async def run(self):
        """Запуск приложения"""
        try:
            self.logger.info("🚀 Запуск Ревущего котёнка с GPT...")
            
            if self.config['openai_key']:
                self.logger.info("🤖 GPT анализ активирован")
            else:
                self.logger.info("⚠️ GPT анализ отключен (нет API ключа)")
            
            # Инициализируем компоненты
            await self.initialize()
            
            # Запускаем Telegram бота
            bot_started = await self.telegram_notifier.start_bot_with_retry()
            if not bot_started:
                raise Exception("Не удалось запустить Telegram бота")
            
            # Запускаем анализ рынка
            self.running = True
            self.logger.info("🔄 Запущена периодическая проверка сигналов")
            
            # Создаем задачи
            market_task = asyncio.create_task(self.market_analysis_loop())
            
            # Ждем завершения
            await market_task
            
        except KeyboardInterrupt:
            self.logger.info("🛑 Получен сигнал остановки")
        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка: {e}")
            raise
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Корректное завершение работы"""
        self.logger.info("🔄 Завершение работы...")
        self.running = False
        
        if self.telegram_notifier:
            await self.telegram_notifier.stop_bot()
        
        self.logger.info("✅ Приложение завершено")

# Точка входа
async def main():
    """Главная функция"""
    try:
        app = TradingApp()
        await app.run()
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        # Запускаем приложение
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Программа прервана пользователем")
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка: {e}")
        sys.exit(1)
```

## Основные изменения:

### 1. **Обработка конфликтов Telegram API**
- Добавлен метод `start_bot_with_retry()` с повторными попытками
- Обработка ошибок `Conflict`, `NetworkError`, `TimedOut`
- Экспоненциальная задержка между попытками

### 2. **Улучшенная архитектура**
- Разделение на классы `TradingApp`, `TelegramNotifier`, `TradingBot`
- Корректное управление жизненным циклом приложения
- Graceful shutdown при получении сигналов

### 3. **Надежность**
- Обработка сетевых ошибок
- Автоматическое удаление неактивных подписчиков
- Логирование всех важных событий

### 4. **Конфигурация**
- Все настройки через переменные окружения
- Проверка обязательных параметров при запуске

### 5. **Telegram Bot улучшения**
- `drop_pending_updates=True` для очистки старых обновлений
- Удаление webhook перед запуском polling
- Правильная инициализация и остановка бота

Этот код должен решить проблему с конфликтами и обеспечить стабильную работу на Railway.















                              
