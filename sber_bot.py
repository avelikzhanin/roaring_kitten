import logging
import time
import pandas as pd
from tinkoff.invest import Client, CandleInterval
from tinkoff.invest.utils import now
from tinkoff.invest.schemas import HistoricCandle
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import pandas_ta as ta
import datetime
import json
import os

# === Конфигурация ===
TOKEN_TINKOFF = "ТВОЙ_TINKOFF_API_ТОКЕН"
TOKEN_TELEGRAM = "ТВОЙ_TELEGRAM_BOT_TOKEN"
FIGI = "BBG004730RP0"  # FIGI для SBER
CANDLE_INTERVAL = CandleInterval.CANDLE_INTERVAL_15_MIN

# Файл для хранения данных пользователей
USERS_FILE = "users_data.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Управление пользователями ===
def load_users_data():
    """Загружает данные пользователей из файла"""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки данных пользователей: {e}")
            return {}
    return {}

def save_users_data(users_data):
    """Сохраняет данные пользователей в файл"""
    try:
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения данных пользователей: {e}")

def register_user(chat_id, username=None):
    """Регистрирует нового пользователя"""
    users_data = load_users_data()
    
    if str(chat_id) not in users_data:
        users_data[str(chat_id)] = {
            "username": username,
            "registered_at": datetime.datetime.now().isoformat(),
            "position_open": False,
            "entry_price": None,
            "subscribed": True
        }
        save_users_data(users_data)
        logger.info(f"Зарегистрирован новый пользователь: {chat_id} ({username})")
        return True
    return False

def get_subscribed_users():
    """Возвращает список подписанных пользователей"""
    users_data = load_users_data()
    return [int(chat_id) for chat_id, data in users_data.items() if data.get("subscribed", True)]

def update_user_position(chat_id, position_open, entry_price=None):
    """Обновляет позицию пользователя"""
    users_data = load_users_data()
    chat_id_str = str(chat_id)
    
    if chat_id_str in users_data:
        users_data[chat_id_str]["position_open"] = position_open
        users_data[chat_id_str]["entry_price"] = entry_price
        save_users_data(users_data)

def get_user_position(chat_id):
    """Получает позицию пользователя"""
    users_data = load_users_data()
    chat_id_str = str(chat_id)
    
    if chat_id_str in users_data:
        user_data = users_data[chat_id_str]
        return user_data.get("position_open", False), user_data.get("entry_price")
    return False, None

def subscribe_user(chat_id):
    """Подписывает пользователя на сигналы"""
    users_data = load_users_data()
    chat_id_str = str(chat_id)
    
    if chat_id_str in users_data:
        users_data[chat_id_str]["subscribed"] = True
        save_users_data(users_data)
        return True
    return False

def unsubscribe_user(chat_id):
    """Отписывает пользователя от сигналов"""
    users_data = load_users_data()
    chat_id_str = str(chat_id)
    
    if chat_id_str in users_data:
        users_data[chat_id_str]["subscribed"] = False
        save_users_data(users_data)
        return True
    return False

# === Получение исторических данных ===
def get_candles():
    """Получает исторические данные свечей"""
    try:
        with Client(TOKEN_TINKOFF) as client:
            now_dt = datetime.datetime.utcnow()
            from_dt = now_dt - datetime.timedelta(days=5)
            candles = client.market_data.get_candles(
                figi=FIGI,
                from_=from_dt,
                to=now_dt,
                interval=CANDLE_INTERVAL
            ).candles

        if not candles:
            logger.warning("Получен пустой список свечей")
            return None

        data = []
        for c in candles:
            data.append([
                c.time,
                candle_to_float(c.open),
                candle_to_float(c.high),
                candle_to_float(c.low),
                candle_to_float(c.close),
                c.volume
            ])

        df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close", "volume"])
        df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values('time').reset_index(drop=True)
        
        logger.info(f"Получено {len(df)} свечей")
        return df
        
    except Exception as e:
        logger.error(f"Ошибка получения данных: {e}")
        return None

def candle_to_float(p):
    """Конвертирует цену из Quotation в float"""
    return p.units + p.nano / 1e9

# === Проверка стратегии ===
def check_signal():
    """Проверяет торговые сигналы"""
    try:
        df = get_candles()
        
        if df is None or len(df) < 100:  # Нужно достаточно данных для EMA100
            logger.warning("Недостаточно данных для анализа")
            return False, None, None, None, None, None, None

        # Расчет индикаторов с помощью pandas_ta
        df.ta.adx(length=14, append=True)  # Добавляет ADX_14, DMP_14, DMN_14
        df.ta.ema(length=100, append=True)  # Добавляет EMA_100
        
        # Средний объем за 20 периодов
        df['avg_volume'] = df['volume'].rolling(window=20).mean()

        # Получаем последние значения
        last_row = df.iloc[-1]
        
        last_adx = last_row['ADX_14']
        last_plus_di = last_row['DMP_14']  # DM Plus (аналог +DI)
        last_minus_di = last_row['DMN_14']  # DM Minus (аналог -DI)
        last_close = last_row['close']
        last_volume = last_row['volume']
        last_ema100 = last_row['EMA_100']
        last_avg_volume = last_row['avg_volume']

        # Проверка на NaN значения
        if pd.isna([last_adx, last_plus_di, last_minus_di, last_ema100, last_avg_volume]).any():
            logger.warning("Обнаружены NaN значения в индикаторах")
            return False, last_close, last_adx, last_plus_di, last_minus_di, last_volume, last_ema100

        # Условия на покупку
        buy_signal = (
            last_adx > 23 and
            last_plus_di > last_minus_di and
            last_volume > last_avg_volume and
            last_close > last_ema100
        )

        return buy_signal, last_close, last_adx, last_plus_di, last_minus_di, last_volume, last_ema100
        
    except Exception as e:
        logger.error(f"Ошибка в check_signal: {e}")
        return False, None, None, None, None, None, None

# === Отправка сигналов ===
async def send_signal(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет торговые сигналы пользователям"""
    try:
        signal_data = check_signal()
        
        if len(signal_data) != 7:
            logger.error("Некорректные данные сигнала")
            return
            
        buy_signal, last_close, last_adx, last_plus_di, last_minus_di, last_volume, last_ema100 = signal_data
        
        if last_close is None:
            logger.warning("Нет данных для анализа")
            return
        
        subscribed_users = get_subscribed_users()
        
        if not subscribed_users:
            logger.info("Нет подписанных пользователей")
            return

        for chat_id in subscribed_users:
            try:
                position_open, entry_price = get_user_position(chat_id)
                
                # Проверка условий выхода для каждого пользователя
                sell_signal = (
                    position_open and (
                        last_adx < 20 or
                        last_plus_di < last_minus_di or
                        last_close < last_ema100
                    )
                )

                # Сигнал на покупку
                if buy_signal and not position_open:
                    update_user_position(chat_id, True, last_close)
                    
                    message = f"""📈 *Сигнал на покупку SBER!*

💰 Цена входа: {last_close:.2f}₽
📊 ADX: {last_adx:.1f}
📈 +DI: {last_plus_di:.1f}
📉 -DI: {last_minus_di:.1f}
📈 EMA100: {last_ema100:.2f}₽

⏰ {datetime.datetime.now().strftime('%H:%M:%S %d.%m.%Y')}"""

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode='Markdown'
                    )
                    logger.info(f"Отправлен сигнал на покупку пользователю {chat_id}")

                # Сигнал на выход
                elif sell_signal and entry_price is not None:
                    update_user_position(chat_id, False, None)
                    
                    profit_percent = ((last_close - entry_price) / entry_price) * 100
                    profit_emoji = "📈" if profit_percent > 0 else "📉"
                    
                    message = f"""📉 *Сигнал на выход из позиции*

💰 Цена выхода: {last_close:.2f}₽
🏁 Цена входа: {entry_price:.2f}₽
{profit_emoji} Результат: {profit_percent:+.2f}%

📊 ADX: {last_adx:.1f}
📈 +DI: {last_plus_di:.1f}
📉 -DI: {last_minus_di:.1f}

⏰ {datetime.datetime.now().strftime('%H:%M:%S %d.%m.%Y')}"""

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode='Markdown'
                    )
                    logger.info(f"Отправлен сигнал на выход пользователю {chat_id}. Результат: {profit_percent:+.2f}%")

            except Exception as e:
                logger.error(f"Ошибка отправки сигнала пользователю {chat_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка в send_signal: {e}")
        # Отправляем уведомление об ошибке всем пользователям
        subscribed_users = get_subscribed_users()
        for chat_id in subscribed_users:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Временная ошибка в боте. Проверяем..."
                )
            except:
                pass

# === Команды бота ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - регистрация пользователя"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    
    is_new_user = register_user(chat_id, username)
    
    if is_new_user:
        await update.message.reply_text(
            f"😺 *Добро пожаловать! Ревущий котёнок на связи!*\n\n"
            f"🎯 Вы успешно зарегистрированы и подписаны на торговые сигналы по SBER\n"
            f"📊 Стратегия: ADX + DI + EMA100\n"
            f"⏱ Таймфрейм: 15 минут\n\n"
            f"*Доступные команды:*\n"
            f"/status - текущий статус позиции\n"
            f"/subscribe - подписаться на сигналы\n"
            f"/unsubscribe - отписаться от сигналов\n"
            f"/help - помощь\n\n"
            f"⚠️ *Важно:* Сигналы носят информационный характер!",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"😺 *С возвращением!* Вы уже зарегистрированы.\n\n"
            f"Используйте /help для просмотра доступных команд.",
            parse_mode='Markdown'
        )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status - показать текущий статус"""
    chat_id = update.effective_chat.id
    position_open, entry_price = get_user_position(chat_id)
    
    try:
        signal_data = check_signal()
        
        if len(signal_data) != 7 or signal_data[1] is None:
            await update.message.reply_text("❌ Ошибка получения данных. Попробуйте позже.")
            return
            
        _, last_close, last_adx, last_plus_di, last_minus_di, last_volume, last_ema100 = signal_data
        
        status_text = f"📊 *Текущий статус:*\n\n"
        
        if position_open and entry_price:
            profit_loss = ((last_close - entry_price) / entry_price) * 100
            profit_emoji = "📈" if profit_loss > 0 else "📉"
            status_text += f"🟢 *Позиция открыта*\n"
            status_text += f"💰 Цена входа: {entry_price:.2f}₽\n"
            status_text += f"💹 Текущая цена: {last_close:.2f}₽\n"
            status_text += f"{profit_emoji} P&L: {profit_loss:+.2f}%\n\n"
        else:
            status_text += f"⭕ *Позиция закрыта*\n"
            status_text += f"💹 Текущая цена: {last_close:.2f}₽\n\n"
        
        status_text += f"📊 *Индикаторы:*\n"
        status_text += f"ADX: {last_adx:.1f}\n"
        status_text += f"+DI: {last_plus_di:.1f}\n"
        status_text += f"-DI: {last_minus_di:.1f}\n"
        status_text += f"EMA100: {last_ema100:.2f}₽\n\n"
        status_text += f"⏰ {datetime.datetime.now().strftime('%H:%M:%S %d.%m.%Y')}"
        
        await update.message.reply_text(status_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в команде status: {e}")
        await update.message.reply_text(f"❌ Ошибка получения данных: {str(e)}")

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /subscribe - подписка на сигналы"""
    chat_id = update.effective_chat.id
    
    if subscribe_user(chat_id):
        await update.message.reply_text("✅ Вы подписаны на торговые сигналы!")
    else:
        await update.message.reply_text("❌ Сначала используйте команду /start для регистрации")

async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /unsubscribe - отписка от сигналов"""
    chat_id = update.effective_chat.id
    
    if unsubscribe_user(chat_id):
        await update.message.reply_text("❌ Вы отписаны от торговых сигналов")
    else:
        await update.message.reply_text("❌ Вы не зарегистрированы в системе")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help - справка"""
    help_text = """🤖 *Торговый бот - Помощь*

📋 *Доступные команды:*

/start - Регистрация и подписка на сигналы
/status - Текущий статус позиции и индикаторы  
/subscribe - Подписаться на сигналы
/unsubscribe - Отписаться от сигналов
/help - Показать это сообщение

📊 *О стратегии:*
• Используется ADX, +DI, -DI, EMA100
• Таймфрейм: 15 минут
• Актив: SBER (Сбербанк)
• Сигналы на вход при ADX>23, +DI>-DI, объем выше среднего, цена выше EMA100
• Выход при ADX<20 или изменении тренда

⚠️ *Важно:* Сигналы носят информационный характер и не являются инвестиционными рекомендациями.

🔄 Проверка сигналов каждые 15 минут"""

    await update.message.reply_text(help_text, parse_mode='Markdown')

# === Основной запуск ===
def main():
    """Основная функция запуска бота"""
    logger.info("🚀 Запуск торгового бота...")
    
    # Проверяем токены
    if TOKEN_TELEGRAM == "ТВОЙ_TELEGRAM_BOT_TOKEN":
        logger.error("❌ Не указан токен Telegram бота!")
        return
        
    if TOKEN_TINKOFF == "ТВОЙ_TINKOFF_API_ТОКЕН":
        logger.error("❌ Не указан токен Tinkoff API!")
        return
    
    try:
        app = Application.builder().token(TOKEN_TELEGRAM).build()

        # Добавляем обработчики команд
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("status", status))
        app.add_handler(CommandHandler("subscribe", subscribe_command))
        app.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
        app.add_handler(CommandHandler("help", help_command))

        # Запускаем отправку сигналов каждые 15 минут (900 секунд)
        app.job_queue.run_repeating(send_signal, interval=900, first=10)

        logger.info("✅ Бот успешно запущен и работает...")
        app.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")

if __name__ == "__main__":
    main()
