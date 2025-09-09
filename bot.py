import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import pandas as pd
from dataclasses import dataclass

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError, TimedOut, NetworkError

# Изменили относительные импорты на абсолютные
from src.data_provider import TinkoffDataProvider
from src.indicators import TechnicalIndicators
from src.gpt_analyzer import GPTMarketAnalyzer, GPTAdvice
from src.database import DatabaseManager

logger = logging.getLogger(__name__)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

@dataclass
class TradingSignal:
    """Структура торгового сигнала"""
    timestamp: datetime
    price: float
    ema20: float
    adx: float
    plus_di: float
    minus_di: float

class TradingBot:
    """Основной класс торгового бота с полной интеграцией БД"""
    
    def __init__(self, telegram_token: str, tinkoff_token: str, database_url: str, openai_token: Optional[str] = None):
        self.telegram_token = telegram_token
        self.tinkoff_provider = TinkoffDataProvider(tinkoff_token)
        self.gpt_analyzer = GPTMarketAnalyzer(openai_token) if openai_token else None
        self.db = DatabaseManager(database_url)
        
        # Убираем все переменные состояния из памяти - теперь всё в БД
        self.app: Optional[Application] = None
        self.is_running = False
        self._signal_task = None
        
        # Логирование статуса компонентов
        logger.info("🔗 Инициализация компонентов:")
        logger.info(f"   📊 Tinkoff API: ✅")
        logger.info(f"   🗄️ База данных: ✅")
        logger.info(f"   🤖 GPT анализ: {'✅' if self.gpt_analyzer else '❌ (опционально)'}")
        
    async def start(self):
        """Запуск бота с полной инициализацией БД"""
        try:
            # 1. Инициализируем БД первым делом
            logger.info("🗄️ Инициализация базы данных...")
            await self.db.initialize()
            logger.info("✅ База данных готова")
            
            # 2. Создаем приложение Telegram
            self.app = Application.builder().token(self.telegram_token).build()
            
            # 3. Добавляем обработчики команд
            self.app.add_handler(CommandHandler("start", self.start_command))
            self.app.add_handler(CommandHandler("stop", self.stop_command))
            self.app.add_handler(CommandHandler("signal", self.signal_command))
            
            logger.info("🚀 Запуск Ревущего котёнка с полной БД интеграцией...")
            
            # 4. Запускаем периодическую проверку
            self.is_running = True
            self._signal_task = asyncio.create_task(self.check_signals_periodically())
            
            # 5. Инициализируем и запускаем Telegram бота
            await self.app.initialize()
            await self.app.start()
            
            # 6. Принудительно удаляем webhook и запускаем polling
            try:
                logger.info("🔧 Удаляем webhook и настраиваем polling...")
                await self.app.bot.delete_webhook(drop_pending_updates=True)
                await asyncio.sleep(1)  # Небольшая пауза
                
                await self.app.updater.start_polling(
                    drop_pending_updates=True,
                    allowed_updates=['message', 'callback_query'],
                    timeout=30,
                    read_timeout=30,
                    write_timeout=30,
                    connect_timeout=30,
                    pool_timeout=30
                )
                logger.info("✅ Telegram polling запущен")
            except Exception as e:
                logger.error(f"❌ Ошибка запуска polling: {e}")
                # Пробуем запустить без дополнительных параметров
                await self.app.updater.start_polling(drop_pending_updates=True)
                logger.info("✅ Telegram polling запущен (fallback режим)")
            
            # 7. Ждем до остановки с обработкой ошибок polling
            try:
                logger.info("🎉 Бот запущен и готов к работе!")
                await asyncio.gather(self._signal_task)
            except asyncio.CancelledError:
                logger.info("Задача проверки сигналов отменена")
            except Exception as polling_error:
                logger.error(f"Ошибка в polling: {polling_error}")
                # Пытаемся переподключиться
                logger.info("🔄 Попытка переподключения...")
                await asyncio.sleep(5)
                
        except Exception as e:
            logger.error(f"Ошибка в start(): {e}")
            await self.shutdown()
            raise
    
    async def shutdown(self):
        """Корректная остановка бота с закрытием БД"""
        logger.info("🛑 Начинаем остановку бота...")
        
        self.is_running = False
        
        # Отменяем задачу проверки сигналов
        if self._signal_task and not self._signal_task.done():
            self._signal_task.cancel()
            try:
                await self._signal_task
            except asyncio.CancelledError:
                pass
        
        # Останавливаем Telegram приложение
        if self.app:
            try:
                # Останавливаем updater
                if self.app.updater and self.app.updater.running:
                    logger.info("🔧 Останавливаем updater...")
                    await self.app.updater.stop()
                
                # Удаляем webhook на всякий случай
                try:
                    await self.app.bot.delete_webhook(drop_pending_updates=True)
                    logger.info("🔧 Webhook удален")
                except Exception as e:
                    logger.warning(f"Не удалось удалить webhook: {e}")
                
                # Останавливаем приложение
                await self.app.stop()
                await self.app.shutdown()
                logger.info("🔧 Telegram приложение остановлено")
                
            except Exception as e:
                logger.error(f"Ошибка при остановке Telegram приложения: {e}")
        
        # Закрываем БД
        try:
            await self.db.close()
            logger.info("🗄️ База данных закрыта")
        except Exception as e:
            logger.error(f"Ошибка закрытия БД: {e}")
        
        logger.info("🛑 Котёнок остановлен")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start с сохранением в БД"""
        chat_id = update.effective_chat.id
        user = update.effective_user
        
        # Добавляем/обновляем пользователя в БД
        success = await self.db.add_or_update_user(
            telegram_id=chat_id,
            username=user.username if user else None,
            first_name=user.first_name if user else None
        )
        
        if success:
            gpt_status = "🤖 <b>GPT анализ:</b> включен с уровнями TP/SL" if self.gpt_analyzer else "📊 <b>Режим:</b> только технический анализ"
            
            await update.message.reply_text(
                "🐱 <b>Добро пожаловать в Ревущего котёнка!</b>\n\n"
                "📈 Вы подписаны на торговые сигналы по SBER\n"
                "🔔 Котёнок будет сообщать о сигналах покупки и продажи акций\n\n"
                f"{gpt_status}\n\n"
                "<b>Параметры стратегии:</b>\n"
                "• EMA20 - цена выше средней\n"
                "• ADX > 25 - сильный тренд\n"
                "• +DI > -DI (разница > 1) - восходящее движение\n"
                "• 🔥 ADX > 45 - пик тренда, время продавать!\n\n"
                "<b>Команды:</b>\n"
                "/stop - отписаться от сигналов\n"
                "/signal - проверить текущий сигнал с полным анализом",
                parse_mode='HTML'
            )
            logger.info(f"👤 Новый/обновленный подписчик: {chat_id} (@{user.username if user else 'unknown'})")
        else:
            await update.message.reply_text(
                "❌ <b>Ошибка подключения к базе данных</b>\n\n"
                "Попробуйте позже или обратитесь к администратору.",
                parse_mode='HTML'
            )
    
    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stop с обновлением БД"""
        chat_id = update.effective_chat.id
        
        # Деактивируем пользователя в БД
        await self.db.deactivate_user(chat_id)
        
        await update.message.reply_text(
            "❌ <b>Вы отписались от рычания котёнка</b>\n\n"
            "Все ваши открытые позиции закрыты.\n"
            "Для повторной подписки используйте /start",
            parse_mode='HTML'
        )
        logger.info(f"👤 Пользователь отписался: {chat_id}")
    
    async def signal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /signal - проверка текущего сигнала с GPT анализом"""
        try:
            await update.message.reply_text("🔍 Анализирую текущую ситуацию на рынке...")
            
            # Выполняем анализ рынка
            signal = await self.analyze_market()
            
            if signal:
                # Есть активный сигнал - получаем анализ GPT
                message = f"""✅ <b>АКТИВНЫЙ СИГНАЛ ПОКУПКИ SBER</b>

{self.format_signal_message(signal)}

⏰ <b>Время сигнала:</b> {signal.timestamp.strftime('%H:%M %d.%m.%Y')}"""
                
                # Добавляем GPT анализ если доступен
                if self.gpt_analyzer:
                    gpt_advice = await self.get_gpt_analysis(signal, is_manual_check=True)
                    if gpt_advice:
                        message += f"\n{self.gpt_analyzer.format_advice_for_telegram(gpt_advice)}"
                    else:
                        message += "\n\n🤖 <i>GPT анализ временно недоступен</i>"
                
            else:
                # Анализируем почему нет сигнала
                message = await self.get_detailed_market_status()
            
            await update.message.reply_text(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Ошибка в команде /signal: {e}")
            await update.message.reply_text(
                "❌ <b>Ошибка при проверке сигнала</b>\n\n"
                "Попробуйте позже или обратитесь к администратору.",
                parse_mode='HTML'
            )

    async def get_detailed_market_status(self) -> str:
        """Получение детального статуса рынка с расширенным GPT анализом"""
        try:
            candles = await self.tinkoff_provider.get_candles(hours=120)
            
            if len(candles) < 50:
                return "❌ <b>Недостаточно данных для анализа</b>\n\nПопробуйте позже."
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            
            if df.empty:
                return "❌ <b>Ошибка получения данных</b>"
            
            # Получаем текущие значения индикаторов
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            # Расчет индикаторов
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
            adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            
            # Последние значения
            current_price = closes[-1]
            current_ema20 = ema20[-1]
            current_adx = adx_data['adx'][-1]
            current_plus_di = adx_data['plus_di'][-1]
            current_minus_di = adx_data['minus_di'][-1]
            
            # Проверяем условия
            price_above_ema = current_price > current_ema20 if not pd.isna(current_ema20) else False
            strong_trend = current_adx > 25 if not pd.isna(current_adx) else False
            positive_direction = current_plus_di > current_minus_di if not pd.isna(current_plus_di) and not pd.isna(current_minus_di) else False
            di_difference = (current_plus_di - current_minus_di) > 1 if not pd.isna(current_plus_di) and not pd.isna(current_minus_di) else False
            peak_trend = current_adx > 45 if not pd.isna(current_adx) else False
            
            all_conditions_met = all([price_above_ema, strong_trend, positive_direction, di_difference])
            
            # Проверяем активные позиции из БД
            active_positions = await self.db.get_active_positions_count()
            peak_warning = ""
            if peak_trend and active_positions > 0:
                peak_warning = "\n🔥 <b>ВНИМАНИЕ: ADX > 45 - пик тренда! Время продавать!</b>"
            elif peak_trend:
                peak_warning = "\n🔥 <b>ADX > 45 - пик тренда</b>"
            
            message = f"""📊 <b>ТЕКУЩЕЕ СОСТОЯНИЕ АКЦИЙ SBER</b>

💰 <b>Цена:</b> {current_price:.2f} ₽
📈 <b>EMA20:</b> {current_ema20:.2f} ₽ {'✅' if price_above_ema else '❌'}

📊 <b>Индикаторы:</b>
• <b>ADX:</b> {current_adx:.1f} {'✅' if strong_trend else '❌'} (нужно >25)
• <b>+DI:</b> {current_plus_di:.1f}
• <b>-DI:</b> {current_minus_di:.1f} {'✅' if positive_direction else '❌'}
• <b>Разница DI:</b> {current_plus_di - current_minus_di:.1f} {'✅' if di_difference else '❌'} (нужно >1){peak_warning}

{'🔔 <b>Все условия выполнены - ожидайте сигнал!</b>' if all_conditions_met else '⏳ <b>Ожидаем улучшения показателей...</b>'}"""
            
            # Добавляем РАСШИРЕННЫЙ GPT анализ с историческими данными
            if self.gpt_analyzer:
                # Преобразуем данные свечей для GPT
                candles_data = []
                try:
                    for _, row in df.iterrows():
                        candles_data.append({
                            'timestamp': row['timestamp'],
                            'open': float(row['open']),
                            'high': float(row['high']),
                            'low': float(row['low']),
                            'close': float(row['close']),
                            'volume': int(row['volume'])
                        })
                except Exception as e:
                    logger.warning(f"Ошибка подготовки данных свечей: {e}")
                    candles_data = None
                
                signal_data = {
                    'price': current_price,
                    'ema20': current_ema20,
                    'adx': current_adx,
                    'plus_di': current_plus_di,
                    'minus_di': current_minus_di,
                    'conditions_met': all_conditions_met
                }
                
                logger.info("🤖 Запрашиваем расширенный GPT анализ с уровнями...")
                gpt_advice = await self.gpt_analyzer.analyze_signal(signal_data, candles_data, is_manual_check=True)
                if gpt_advice:
                    message += f"\n{self.gpt_analyzer.format_advice_for_telegram(gpt_advice)}"
                    logger.info(f"✅ GPT дал рекомендацию: {gpt_advice.recommendation}")
                else:
                    message += "\n\n🤖 <i>GPT анализ временно недоступен</i>"
                    logger.warning("⚠️ GPT анализ недоступен")
            
            return message
                
        except Exception as e:
            logger.error(f"Ошибка в детальном анализе: {e}")
            return "❌ <b>Ошибка получения данных для анализа</b>\n\nПопробуйте позже."

    async def analyze_market(self) -> Optional[TradingSignal]:
        """Анализ рынка и генерация сигнала"""
        try:
            # Получаем данные за последние 120 часов для расчета индикаторов
            candles = await self.tinkoff_provider.get_candles(hours=120)
            
            if len(candles) < 50:  # Минимум данных для расчетов
                logger.warning("Недостаточно данных для анализа")
                return None
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            
            if df.empty:
                logger.warning("Пустой DataFrame")
                return None
            
            # Расчет технических индикаторов
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            # EMA20
            ema20 = TechnicalIndicators.calculate_ema(closes, 20)
            
            # ADX, +DI, -DI
            adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            
            # Проверка последней свечи
            last_idx = -1
            current_price = closes[last_idx]
            current_ema20 = ema20[last_idx]
            current_adx = adx_data['adx'][last_idx]
            current_plus_di = adx_data['plus_di'][last_idx]
            current_minus_di = adx_data['minus_di'][last_idx]
            
            # Проверка на NaN
            if any(pd.isna(val) for val in [current_ema20, current_adx, current_plus_di, current_minus_di]):
                logger.warning("Не все индикаторы рассчитаны")
                return None
            
            # Расширенное логирование для отладки
            logger.info(f"🔍 ОТЛАДКА ИНДИКАТОРОВ:")
            logger.info(f"💰 Цена: {current_price:.2f} ₽ | EMA20: {current_ema20:.2f} ₽")
            logger.info(f"📊 ADX: {current_adx:.2f} | +DI: {current_plus_di:.2f} | -DI: {current_minus_di:.2f}")
            
            # Проверка условий сигнала
            conditions = [
                current_price > current_ema20,              # Цена выше EMA20
                current_adx > 25,                           # ADX больше 25 
                current_plus_di > current_minus_di,         # +DI больше -DI
                current_plus_di - current_minus_di > 1,     # Разница больше 1
            ]
            
            condition_names = [
                "Цена > EMA20",
                "ADX > 25", 
                "+DI > -DI",
                "Разница DI > 1",
            ]
            
            # Детальное логирование условий
            for i, (condition, name) in enumerate(zip(conditions, condition_names)):
                logger.info(f"   {i+1}. {name}: {'✅' if condition else '❌'}")
            
            if all(conditions):
                logger.info("🎉 Все условия выполнены - генерируем сигнал!")
                return TradingSignal(
                    timestamp=df.iloc[last_idx]['timestamp'],
                    price=current_price,
                    ema20=current_ema20,
                    adx=current_adx,
                    plus_di=current_plus_di,
                    minus_di=current_minus_di
                )
            else:
                logger.info(f"⏳ Условия не выполнены: {sum(conditions)}/{len(conditions)}")
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка анализа рынка: {e}")
            return None
    
    async def get_gpt_analysis(self, signal: TradingSignal, is_manual_check: bool = False) -> Optional[GPTAdvice]:
        """Получение GPT анализа для сигнала с историческими данными"""
        if not self.gpt_analyzer:
            return None
        
        # Получаем свечные данные для анализа уровней
        try:
            candles = await self.tinkoff_provider.get_candles(hours=120)  # 5 дней данных
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            
            # Преобразуем в формат для GPT
            candles_data = []
            if not df.empty:
                for _, row in df.iterrows():
                    candles_data.append({
                        'timestamp': row['timestamp'],
                        'open': float(row['open']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'close': float(row['close']),
                        'volume': int(row['volume'])
                    })
        except Exception as e:
            logger.warning(f"Не удалось получить данные свечей для GPT: {e}")
            candles_data = None
        
        signal_data = {
            'price': signal.price,
            'ema20': signal.ema20,
            'adx': signal.adx,
            'plus_di': signal.plus_di,
            'minus_di': signal.minus_di
        }
        
        return await self.gpt_analyzer.analyze_signal(signal_data, candles_data, is_manual_check)
    
    async def check_peak_trend(self) -> Optional[float]:
        """Проверка пика тренда (ADX > 45)"""
        try:
            candles = await self.tinkoff_provider.get_candles(hours=120)
            
            if len(candles) < 50:
                return None
            
            df = self.tinkoff_provider.candles_to_dataframe(candles)
            
            if df.empty:
                return None
            
            # Расчет индикаторов
            closes = df['close'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            
            # ADX
            adx_data = TechnicalIndicators.calculate_adx(highs, lows, closes, 14)
            current_adx = adx_data['adx'][-1]
            current_price = closes[-1]
            
            if pd.isna(current_adx):
                return None
                
            # Проверяем пик тренда
            if current_adx > 45:
                logger.info(f"🔥 ПИК ТРЕНДА! ADX: {current_adx:.1f} > 45")
                return current_price
                
            return None
            
        except Exception as e:
            logger.error(f"Ошибка проверки пика тренда: {e}")
            return None
    
    async def get_current_price(self) -> float:
        """Получение текущей цены"""
        try:
            candles = await self.tinkoff_provider.get_candles(hours=50)
            if candles:
                df = self.tinkoff_provider.candles_to_dataframe(candles)
                return df.iloc[-1]['close'] if not df.empty else 0
            return 0
        except:
            return 0
    
    def calculate_profit_percentage(self, buy_price: float, sell_price: float) -> float:
        """Расчет прибыли в процентах"""
        if buy_price <= 0:
            return 0
        return ((sell_price - buy_price) / buy_price) * 100
    
    async def get_profit_summary(self, current_price: float) -> str:
        """Получение сводки по прибыли для всех открытых позиций"""
        try:
            # Получаем все активные позиции из БД
            if not self.db.pool:
                return ""
            
            async with self.db.pool.acquire() as conn:
                positions = await conn.fetch('''
                    SELECT buy_price, COUNT(*) as position_count
                    FROM active_positions
                    GROUP BY buy_price
                ''')
                
                if not positions:
                    return ""
                
                total_positions = sum(pos['position_count'] for pos in positions)
                profits = []
                
                for pos in positions:
                    buy_price = float(pos['buy_price'])
                    count = pos['position_count']
                    profit_pct = self.calculate_profit_percentage(buy_price, current_price)
                    profits.append((buy_price, profit_pct, count))
                
                # Средневзвешенная прибыль
                weighted_profit = sum(profit * count for _, profit, count in profits) / total_positions
                
                # Форматируем результат
                if weighted_profit > 0:
                    profit_emoji = "🟢"
                    profit_text = f"+{weighted_profit:.2f}%"
                elif weighted_profit < 0:
                    profit_emoji = "🔴"
                    profit_text = f"{weighted_profit:.2f}%"
                else:
                    profit_emoji = "⚪"
                    profit_text = "0.00%"
                
                if len(profits) == 1:
                    # Одна цена покупки
                    buy_price = profits[0][0]
                    return f"\n\n💰 <b>Результат сделки:</b> {profit_emoji} {profit_text}\n📈 <b>Вход:</b> {buy_price:.2f} ₽ → <b>Выход:</b> {current_price:.2f} ₽"
                else:
                    # Несколько разных цен покупки
                    return f"\n\n💰 <b>Средний результат:</b> {profit_emoji} {profit_text}\n👥 <b>Позиций закрыто:</b> {total_positions}"
                
        except Exception as e:
            logger.error(f"Ошибка расчета прибыли: {e}")
            return ""
    
    async def send_peak_signal(self, current_price: float):
        """Отправка сигнала пика тренда всем подписчикам с сохранением в БД"""
        if not self.app:
            logger.error("Telegram приложение не инициализировано")
            return
        
        # Получаем список активных подписчиков из БД
        subscribers = await self.db.get_active_users()
        if not subscribers:
            logger.info("📊 Нет активных подписчиков")
            return
        
        # Сохраняем сигнал пика в БД
        signal_id = await self.db.save_signal(
            signal_type='PEAK',
            price=current_price,
            ema20=current_price * 0.98,  # Примерное значение
            adx=47,  # Пиковое значение
            plus_di=35,
            minus_di=20
        )
        
        # Расчет средней прибыли по всем открытым позициям
        # Здесь можно добавить более сложную логику расчета
        
        message = f"""🔥 <b>ПИК ТРЕНДА - ПРОДАЁМ SBER!</b>

💰 <b>Текущая цена:</b> {current_price:.2f} ₽

📊 <b>Причина продажи:</b>
ADX > 45 - мы на пике тренда!
Время фиксировать прибыль.

🔍 <b>Продолжаем мониторинг новых возможностей...</b>"""
        
        # Добавляем GPT анализ для пикового сигнала если доступен
        if self.gpt_analyzer:
            try:
                temp_signal_data = {
                    'price': current_price,
                    'ema20': current_price * 0.98,
                    'adx': 47,
                    'plus_di': 35,
                    'minus_di': 20
                }
                
                gpt_advice = await self.gpt_analyzer.analyze_signal(temp_signal_data, None, is_manual_check=False)
                if gpt_advice and gpt_advice.recommendation == 'AVOID':
                    message += f"\n\n🤖 <b>GPT подтверждает:</b> {gpt_advice.reasoning}"
            except Exception as e:
                logger.error(f"Ошибка GPT анализа для пика: {e}")
        
        # Отправляем сообщения
        failed_chats = []
        successful_sends = 0
        
        for chat_id in subscribers:
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id, 
                    text=message, 
                    parse_mode='HTML'
                )
                successful_sends += 1
                await asyncio.sleep(0.1)
                
            except (TelegramError, TimedOut, NetworkError) as e:
                logger.error(f"Не удалось отправить сообщение пика в чат {chat_id}: {e}")
                failed_chats.append(chat_id)
                
        # Деактивируем недоступные чаты в БД
        for chat_id in failed_chats:
            await self.db.deactivate_user(chat_id)
            logger.warning(f"Деактивирован недоступный чат: {chat_id}")
        
        # Закрываем все активные позиции в БД
        await self.db.close_positions('PEAK')
        
        logger.info(f"🔥 Сигнал пика отправлен: {successful_sends} получателей, {len(failed_chats)} ошибок")
    
    async def send_signal_to_subscribers(self, signal: TradingSignal):
        """Отправка сигнала всем подписчикам с сохранением в БД"""
        if not self.app:
            logger.error("Telegram приложение не инициализировано")
            return
        
        # Получаем список активных подписчиков из БД
        subscribers = await self.db.get_active_users()
        if not subscribers:
            logger.info("📊 Нет активных подписчиков")
            return
            
        message = self.format_signal_message(signal)
        
        # Получаем GPT анализ
        gpt_data = None
        if self.gpt_analyzer:
            logger.info("🤖 Получаем расширенный анализ GPT с TP/SL для сигнала...")
            gpt_advice = await self.get_gpt_analysis(signal, is_manual_check=False)
            
            if gpt_advice:
                message += f"\n{self.gpt_analyzer.format_advice_for_telegram(gpt_advice)}"
                
                # Подготавливаем данные GPT для сохранения в БД
                gpt_data = {
                    'recommendation': gpt_advice.recommendation,
                    'confidence': gpt_advice.confidence,
                    'take_profit': gpt_advice.take_profit,
                    'stop_loss': gpt_advice.stop_loss
                }
                
                logger.info(f"🤖 GPT рекомендация: {gpt_advice.recommendation} ({gpt_advice.confidence}%)")
                
                if gpt_advice.take_profit and gpt_advice.stop_loss:
                    logger.info(f"🎯 TP: {gpt_advice.take_profit} | 🛑 SL: {gpt_advice.stop_loss}")
                
                if gpt_advice.recommendation == 'AVOID':
                    message += f"\n\n⚠️ <b>ВНИМАНИЕ:</b> GPT не рекомендует покупку!"
                elif gpt_advice.recommendation == 'WEAK_BUY':
                    message += f"\n\n⚡ <b>Осторожно:</b> GPT рекомендует минимальный риск"
            else:
                message += "\n\n🤖 <i>GPT анализ временно недоступен</i>"
                logger.warning("⚠️ Не удалось получить GPT анализ")
        
        # Сохраняем сигнал в БД ПЕРЕД отправкой
        signal_id = await self.db.save_signal(
            signal_type='BUY',
            price=signal.price,
            ema20=signal.ema20,
            adx=signal.adx,
            plus_di=signal.plus_di,
            minus_di=signal.minus_di,
            gpt_data=gpt_data
        )
        
        if not signal_id:
            logger.error("❌ Не удалось сохранить сигнал в БД")
            return
        
        # Отправляем сообщения подписчикам
        failed_chats = []
        successful_sends = 0
        
        for chat_id in subscribers:
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id, 
                    text=message, 
                    parse_mode='HTML'
                )
                
                # Открываем позицию для пользователя в БД
                await self.db.open_position(chat_id, signal_id, signal.price)
                
                successful_sends += 1
                await asyncio.sleep(0.1)
                
            except (TelegramError, TimedOut, NetworkError) as e:
                logger.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")
                failed_chats.append(chat_id)
                
        # Деактивируем недоступные чаты в БД
        for chat_id in failed_chats:
            await self.db.deactivate_user(chat_id)
            logger.warning(f"Деактивирован недоступный чат: {chat_id}")
        
        logger.info(f"📈 Сигнал отправлен: {successful_sends} получателей, {len(failed_chats)} ошибок")
    
    def format_signal_message(self, signal: TradingSignal) -> str:
        """Форматирование сообщения с сигналом"""
        return f"""🔔 <b>СИГНАЛ ПОКУПКИ SBER</b>

💰 <b>Цена:</b> {signal.price:.2f} ₽
📈 <b>EMA20:</b> {signal.ema20:.2f} ₽ (цена выше)

📊 <b>Индикаторы:</b>
• <b>ADX:</b> {signal.adx:.1f} (сильный тренд >25)
• <b>+DI:</b> {signal.plus_di:.1f}
• <b>-DI:</b> {signal.minus_di:.1f}
• <b>Разница DI:</b> {signal.plus_di - signal.minus_di:.1f}"""
    
    async def check_signals_periodically(self):
        """Периодическая проверка сигналов с использованием БД"""
        logger.info("🔄 Запущена периодическая проверка сигналов")
        
        while self.is_running:
            try:
                logger.info("🔍 Выполняется анализ рынка...")
                signal = await self.analyze_market()
                conditions_met = signal is not None
                
                # Проверяем ADX для сигнала "пик тренда"
                peak_signal = await self.check_peak_trend()
                
                # Получаем количество открытых позиций из БД
                active_positions = await self.db.get_active_positions_count()
                
                # Улучшенная логика отправки сигналов
                if conditions_met and active_positions == 0:
                    # Новый сигнал покупки - нет открытых позиций
                    await self.send_signal_to_subscribers(signal)
                    logger.info(f"✅ Отправлен сигнал ПОКУПКИ по цене {signal.price:.2f}")
                
                elif peak_signal and active_positions > 0:
                    # Пик тренда (ADX > 45) - есть открытые позиции
                    await self.send_peak_signal(peak_signal)
                    logger.info(f"🔥 Отправлен сигнал ПИКА ТРЕНДА по цене {peak_signal:.2f}")
                
                elif not conditions_met and active_positions > 0:
                    # Условия перестали выполняться - есть открытые позиции
                    current_price = await self.get_current_price()
                    await self.send_cancel_signal(current_price)
                    logger.info("❌ Отправлен сигнал ОТМЕНЫ")
                
                elif conditions_met and active_positions > 0:
                    logger.info("✅ Сигнал покупки остается актуальным")
                
                else:
                    logger.info("📊 Ожидаем сигнал...")
                
                # Оптимизированная частота проверки - каждые 20 минут для часовых свечей
                await asyncio.sleep(1200)  # 20 минут = 1200 секунд
                
            except asyncio.CancelledError:
                logger.info("Задача проверки сигналов отменена")
                break
            except Exception as e:
                logger.error(f"Ошибка в периодической проверке: {e}")
                await asyncio.sleep(60)  # Ждем минуту при ошибке
    
    async def send_cancel_signal(self, current_price: float = 0):
        """Отправка сигнала отмены всем подписчикам с обновлением БД"""
        if not self.app:
            logger.error("Telegram приложение не инициализировано")
            return
        
        # Получаем список активных подписчиков из БД
        subscribers = await self.db.get_active_users()
        if not subscribers:
            logger.info("📊 Нет активных подписчиков")
            return
        
        # Получаем текущие данные если цена не передана
        if current_price == 0:
            current_price = await self.get_current_price()
        
        # Сохраняем сигнал отмены в БД
        signal_id = await self.db.save_signal(
            signal_type='SELL',
            price=current_price,
            ema20=current_price * 0.98,  # Примерное значение
            adx=20,  # Слабый тренд
            plus_di=25,
            minus_di=30
        )
        
        message = f"""❌ <b>СИГНАЛ ОТМЕНЕН SBER</b>

💰 <b>Текущая цена:</b> {current_price:.2f} ₽

⚠️ <b>Причина отмены:</b>
Условия покупки больше не выполняются:
• Цена может быть ниже EMA20
• ADX снизился < 25
• Изменилось соотношение +DI/-DI
• Разница DI стала < 1

🔍 <b>Продолжаем мониторинг...</b>"""
        
        failed_chats = []
        successful_sends = 0
        
        for chat_id in subscribers:
            try:
                await self.app.bot.send_message(
                    chat_id=chat_id, 
                    text=message, 
                    parse_mode='HTML'
                )
                successful_sends += 1
                await asyncio.sleep(0.1)
                
            except (TelegramError, TimedOut, NetworkError) as e:
                logger.error(f"Не удалось отправить сообщение отмены в чат {chat_id}: {e}")
                failed_chats.append(chat_id)
                
        # Деактивируем недоступные чаты в БД
        for chat_id in failed_chats:
            await self.db.deactivate_user(chat_id)
        
        # Закрываем все активные позиции в БД
        await self.db.close_positions('SELL')
        
        logger.info(f"❌ Сигнал отмены отправлен: {successful_sends} получателей, {len(failed_chats)} ошибок")


async def main():
    """Основная функция запуска бота с полной БД интеграцией"""
    logger.info("🚀 Запуск основной функции...")
    
    # Получение токенов из переменных окружения
    telegram_token = os.getenv("TELEGRAM_TOKEN")
    tinkoff_token = os.getenv("TINKOFF_TOKEN") 
    database_url = os.getenv("DATABASE_URL")
    openai_token = os.getenv("OPENAI_API_KEY")  # Опционально
    
    # Проверка обязательных токенов
    if not telegram_token:
        logger.error("❌ TELEGRAM_TOKEN не найден в переменных окружения")
        return
        
    if not tinkoff_token:
        logger.error("❌ TINKOFF_TOKEN не найден в переменных окружения")
        return
    
    if not database_url:
        logger.error("❌ DATABASE_URL не найден в переменных окружения")
        logger.error("   БД обязательна для работы с полной интеграцией!")
        return
    
    # Логируем статус токенов
    logger.info("🔑 Проверка токенов:")
    logger.info(f"   📱 Telegram: {'✅' if telegram_token else '❌'}")
    logger.info(f"   📊 Tinkoff: {'✅' if tinkoff_token else '❌'}")
    logger.info(f"   🗄️ Database: {'✅' if database_url else '❌'}")
    logger.info(f"   🤖 OpenAI: {'✅' if openai_token else '❌ (опционально)'}")
    
    # Создание и запуск бота
    bot = TradingBot(
        telegram_token=telegram_token,
        tinkoff_token=tinkoff_token,
        database_url=database_url,
        openai_token=openai_token
    )
    
    try:
        logger.info("▶️ Запускаем бота...")
        await bot.start()
    except KeyboardInterrupt:
        logger.info("⌨️ Получен сигнал прерывания")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        logger.info("🔄 Завершаем работу...")
        await bot.shutdown()
        logger.info("✅ Завершение main()")


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("🐱 РЕВУЩИЙ КОТЁНОК СТАРТУЕТ")
    logger.info("=" * 50)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🔄 Программа завершена пользователем")
    except Exception as e:
        logger.error(f"💥 Фатальная ошибка в main: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
    finally:
        logger.info("👋 До свидания!")
