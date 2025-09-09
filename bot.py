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
    """Основной класс торгового бота с GPT анализом и обязательной БД"""
    
    def __init__(self, telegram_token: str, tinkoff_token: str, database_url: str,
                 openai_token: Optional[str] = None):
        self.telegram_token = telegram_token
        self.tinkoff_provider = TinkoffDataProvider(tinkoff_token)
        self.gpt_analyzer = GPTMarketAnalyzer(openai_token) if openai_token else None
        self.db = DatabaseManager(database_url)  # БД теперь обязательна
        self.app: Optional[Application] = None
        self.is_running = False
        self.current_signal_active = False
        self.last_conditions_met = False
        self._signal_task = None
        self.buy_price: Optional[float] = None
        self.last_buy_signal_id: Optional[int] = None
        
        # Логирование статусов
        logger.info("💾 Подключаемся к базе данных...")
        if self.gpt_analyzer:
            logger.info("🤖 GPT анализ активирован")
        else:
            logger.info("📊 Работаем без GPT анализа")
        
    async def start(self):
        """Запуск бота"""
        try:
            # Инициализируем БД (обязательно)
            await self.db.initialize()
            logger.info("✅ База данных инициализирована")
            
            # Создаем приложение Telegram
            self.app = Application.builder().token(self.telegram_token).build()
            
            # Добавляем обработчики команд
            self.app.add_handler(CommandHandler("start", self.start_command))
            self.app.add_handler(CommandHandler("stop", self.stop_command))
            self.app.add_handler(CommandHandler("signal", self.signal_command))
            self.app.add_handler(CommandHandler("stats", self.stats_command))
            
            logger.info("🚀 Запуск Ревущего котёнка с БД и GPT...")
            
            # Запускаем периодическую проверку в отдельной задаче
            self.is_running = True
            self._signal_task = asyncio.create_task(self.check_signals_periodically())
            
            # Инициализируем и запускаем Telegram бота
            await self.app.initialize()
            await self.app.start()
            
            # Запускаем polling
            await self.app.updater.start_polling(drop_pending_updates=True)
            
            # Ждем до остановки
            try:
                await asyncio.gather(self._signal_task)
            except asyncio.CancelledError:
                logger.info("Задача проверки сигналов отменена")
                
        except Exception as e:
            logger.error(f"Ошибка в start(): {e}")
            await self.shutdown()
            raise
    
    async def shutdown(self):
        """Корректная остановка бота"""
        logger.info("Начинаем остановку бота...")
        
        self.is_running = False
        
        # Отменяем задачу проверки сигналов
        if self._signal_task and not self._signal_task.done():
            self._signal_task.cancel()
            try:
                await self._signal_task
            except asyncio.CancelledError:
                pass
        
        # Закрываем соединение с БД
        await self.db.close()
        
        # Останавливаем Telegram приложение
        if self.app:
            try:
                if self.app.updater and self.app.updater.running:
                    await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()
            except Exception as e:
                logger.error(f"Ошибка при остановке Telegram приложения: {e}")
        
        logger.info("Котёнок остановлен")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        chat_id = update.effective_chat.id
        username = update.effective_user.username
        first_name = update.effective_user.first_name
        
        # Сохраняем/обновляем пользователя в БД
        user_added = await self.db.add_or_update_user(chat_id, username, first_name)
        
        if user_added:
            gpt_status = "🤖 <b>GPT анализ:</b> включен с уровнями TP/SL" if self.gpt_analyzer else "📊 <b>Режим:</b> только технический анализ"
            
            await update.message.reply_text(
                "🐱 <b>Добро пожаловать в Ревущего котёнка!</b>\n\n"
                "📈 Вы подписаны на торговые сигналы по SBER\n"
                "🔔 Котёнок будет рычать о сигналах покупки и их отмене\n"
                "💾 Все сигналы сохраняются в базе данных\n\n"
                f"{gpt_status}\n\n"
                "<b>Параметры стратегии:</b>\n"
                "• EMA20 - цена выше средней\n"
                "• ADX > 25 - сильный тренд\n"
                "• +DI > -DI (разница > 1) - восходящее движение\n"
                "• 🔥 ADX > 45 - пик тренда, время продавать!\n\n"
                "<b>Команды:</b>\n"
                "/stop - отписаться от сигналов\n"
                "/signal - проверить текущий сигнал\n"
                "/stats - статистика бота",
                parse_mode='HTML'
            )
            logger.info(f"Новый/обновленный подписчик: {chat_id} (@{username})")
        else:
            await update.message.reply_text("❌ Ошибка добавления в базу данных. Обратитесь к администратору.")
    
    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stop"""
        chat_id = update.effective_chat.id
        
        # Деактивируем пользователя в БД
        await self.db.deactivate_user(chat_id)
        
        await update.message.reply_text("❌ Вы отписались от рычания котёнка")
        logger.info(f"Пользователь отписался: {chat_id}")
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда для просмотра статистики"""
        try:
            stats = await self.db.get_stats()
            
            message = f"""📊 <b>СТАТИСТИКА БОТА</b>

👥 <b>Пользователи:</b>
• Всего: {stats.get('total_users', 0)}
• Активных: {stats.get('active_users', 0)}

📈 <b>Сигналы:</b>
• Всего: {stats.get('total_signals', 0)}
• Покупок: {stats.get('buy_signals', 0)}
• Продаж: {stats.get('sell_signals', 0)}

💼 <b>Открытых позиций:</b> {stats.get('open_positions', 0)}"""
            
            await update.message.reply_text(message, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            await update.message.reply_text("❌ Ошибка получения статистики")
    
    async def signal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /signal - проверка текущего сигнала с GPT анализом"""
        try:
            await update.message.reply_text("🔍 Анализирую текущую ситуацию на рынке с историческими данными...")
            
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
            
            peak_warning = ""
            if peak_trend and self.current_signal_active:
                peak_warning = "\n🔥 <b>ВНИМАНИЕ: ADX > 45 - пик тренда! Время продавать!</b>"
            elif peak_trend:
                peak_warning = "\n🔥 <b>ADX > 45 - пик тренда</b>"
            
            message = f"""📊 <b>ТЕКУЩЕЕ СОСТОЯНИЕ РЫНКА SBER</b>

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
    
    async def send_peak_signal(self, current_price: float):
        """Отправка сигнала пика тренда всем подписчикам"""
        if not self.app:
            logger.error("Telegram приложение не инициализировано")
            return
        
        # Сохраняем сигнал пика в БД
        await self.db.save_signal(
            signal_type='PEAK',
            price=current_price,
            ema20=0,  # Не важно для пика
            adx=47,   # Примерное значение > 45
            plus_di=0,
            minus_di=0
        )
        
        # Закрываем позиции
        await self.db.close_positions('PEAK')
        
        # Расчет прибыли
        profit_text = ""
        if self.buy_price and self.buy_price > 0:
            profit_percentage = self.calculate_profit_percentage(self.buy_price, current_price)
            profit_emoji = "🟢" if profit_percentage > 0 else "🔴" if profit_percentage < 0 else "⚪"
            profit_text = f"\n💰 <b>Прибыль:</b> {profit_emoji} {profit_percentage:+.2f}% (с {self.buy_price:.2f} до {current_price:.2f} ₽)"
        
        message = f"""🔥 <b>ПИК ТРЕНДА - ВСЁ ПРОДАЁМ!</b>

💰 <b>Текущая цена:</b> {current_price:.2f} ₽

📊 <b>Причина продажи:</b>
ADX > 45 - мы на пике тренда!
Время фиксировать прибыль.{profit_text}

🔍 <b>Продолжаем мониторинг новых возможностей...</b>"""
        
        # Отправляем всем активным пользователям из БД
        subscribers = await self.db.get_active_users()
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
                
        # Деактивируем недоступных пользователей
        for chat_id in failed_chats:
            await self.db.deactivate_user(chat_id)
        
        logger.info(f"Сигнал пика отправлен: {successful_sends} получателей, {len(failed_chats)} ошибок")
    
    async def send_signal_to_subscribers(self, signal: TradingSignal):
        """Отправка сигнала всем подписчикам с расширенным GPT анализом и сохранением в БД"""
        if not self.app:
            logger.error("Telegram приложение не инициализировано")
            return
            
        message = self.format_signal_message(signal)
        
        # Подготавливаем данные GPT для БД
        gpt_data = None
        
        # Добавляем РАСШИРЕННЫЙ GPT анализ если доступен
        if self.gpt_analyzer:
            logger.info("🤖 Получаем расширенный анализ GPT с TP/SL для сигнала...")
            gpt_advice = await self.get_gpt_analysis(signal, is_manual_check=False)
            
            if gpt_advice:
                message += f"\n{self.gpt_analyzer.format_advice_for_telegram(gpt_advice)}"
                
                # Сохраняем данные GPT для БД
                gpt_data = {
                    'recommendation': gpt_advice.recommendation,
                    'confidence': gpt_advice.confidence,
                    'take_profit': gpt_advice.take_profit,
                    'stop_loss': gpt_advice.stop_loss
                }
                
                # Логируем рекомендацию GPT
                logger.info(f"🤖 GPT рекомендация: {gpt_advice.recommendation} ({gpt_advice.confidence}%)")
                
                # Если есть TP/SL, логируем их
                if gpt_advice.take_profit and gpt_advice.stop_loss:
                    logger.info(f"🎯 TP: {gpt_advice.take_profit} | 🛑 SL: {gpt_advice.stop_loss}")
                
                # Если GPT не рекомендует покупать, добавляем предупреждение
                if gpt_advice.recommendation == 'AVOID':
                    message += f"\n\n⚠️ <b>ВНИМАНИЕ:</b> GPT не рекомендует покупку!"
                elif gpt_advice.recommendation == 'WEAK_BUY':
                    message += f"\n\n⚡ <b>Осторожно:</b> GPT"
