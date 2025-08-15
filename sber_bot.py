import logging
import time
import pandas as pd
from tinkoff.invest import Client, CandleInterval
from tinkoff.invest.utils import now
from tinkoff.invest.schemas import HistoricCandle
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import talib
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
    with Client(TOKEN_TINKOFF) as client:
        now_dt = datetime.datetime.utcnow()
        from_dt = now_dt - datetime.timedelta(days=5)
        candles = client.market_data.get_candles(
            figi=FIGI,
            from_=from_dt,
            to=now_dt,
            interval=CANDLE_INTERVAL
        ).candles

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
    return df

def candle_to_float(p):
    return p.units + p.nano / 1e9

# === Проверка стратегии ===
def check_signal():
    df = get_candles()

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    volume = df["volume"].values

    # Индикаторы
    adx = talib.ADX(high, low, close, timeperiod=14)
    plus_di = talib.PLUS_DI(high, low, close, timeperiod=14)
    minus_di = talib.MINUS_DI(high, low, close, timeperiod=14)
    ema100 = talib.EMA(close, timeperiod=100)
    avg_volume = pd.Series(volume).rolling(window=20).mean()

    last_adx = adx[-1]
    last_plus_di = plus_di[-1]
    last_minus_di = minus_di[-1]
    last_close = close[-1]
    last_volume = volume[-1]
    last_ema100 = ema100[-1]
    last_avg_volume = avg_volume.iloc[-1]

    # Условия на покупку
    buy_signal = (
        last_adx > 23 and
        last_plus_di > last_minus_di and
        last_volume > last_avg_volume and
        last_close > last_ema100
    )

    # Условия на выход (проверяем для каждого пользователя отдельно)
    return buy_signal, last_close, last_adx, last_plus_di, last_minus_di, last_volume, last_ema100

# === Отправка сигналов ===
async def send_signal(context: ContextTypes.DEFAULT_TYPE):
    try:
        buy_signal, last_close, last_adx, last_plus_di, last_minus_di, last_volume, last_ema100 = check_signal()
        
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
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"📈 Сигнал на покупку SBER!\nЦена входа: {last_close:.2f}₽"
                    )
                    logger.info(f"Отправлен сигнал на покупку пользователю {chat_id}")

                # Сигнал на выход
                elif sell_signal:
                    update_user_position(chat_id, False, None)
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"📉 Сигнал на выход из позиции\nЦена выхода: {last_close:.2f}₽\nВход был по: {entry_price:.2f}₽"
                    )
                    logger.info(f"Отправлен сигнал на выход пользователю {chat_id}")

            except Exception as e:
                logger.error(f"Ошибка отправки сигнала пользователю {chat_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка в send_signal: {e}")

# === Команды бота ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    
    is_new_user = register_user(chat_id, username)
    
    if is_new_user:
        await update.message.reply_text(
            f"😺 Добро пожаловать! Ревущий котёнок на связи!\n\n"
            f"🎯 Вы успешно зарегистрированы и подписаны на торговые сигналы по SBER\n"
            f"📊 Стратегия: ADX + DI + EMA100\n"
            f"⏱ Таймфрейм: 15 минут\n\n"
            f"Доступные команды:\n"
            f"/status - текущий статус позиции\n"
            f"/subscribe - подписаться на сигналы\n"
            f"/unsubscribe - отписаться от сигналов\n"
            f"/help - помощь"
        )
    else:
        await update.message.reply_text(
            f"😺 С возвращением! Вы уже зарегистрированы.\n\n"
            f"Используйте /help для просмотра доступных команд."
        )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    position_open, entry_price = get_user_position(chat_id)
    
    try:
        _, last_close, last_adx, last_plus_di, last_minus_di, last_volume, last_ema100 = check_signal()
        
        status_text = f"📊 Текущий статус:\n\n"
        
        if position_open:
            profit_loss = ((last_close - entry_price) / entry_price) * 100
            status_text += f"🟢 Позиция открыта\n"
            status_text += f"💰 Цена входа: {entry_price:.2f}₽\n"
            status_text += f"💹 Текущая цена: {last_close:.2f}₽\n"
            status_text += f"📈 P&L: {profit_loss:+.2f}%\n\n"
        else:
            status_text += f"⭕ Позиция закрыта\n"
            status_text += f"💹 Текущая цена: {last_close:.2f}₽\n\n"
        
        status_text += f"📊 Индикаторы:\n"
        status_text += f"ADX: {last_adx:.1f}\n"
        status_text += f"+DI: {last_plus_di:.1f}\n"
        status_text += f"-DI: {last_minus_di:.1f}\n"
        status_text += f"EMA100: {last_ema100:.2f}₽"
        
        await update.message.reply_text(status_text)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка получения данных: {str(e)}")

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if subscribe_user(chat_id):
        await update.message.reply_text("✅ Вы подписаны на торговые сигналы!")
    else:
        await update.message.reply_text("❌ Сначала используйте команду /start для регистрации")

async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if unsubscribe_user(chat_id):
        await update.message.reply_text("❌ Вы отписаны от торговых сигналов")
    else:
        await update.message.reply_text("❌ Вы не зарегистрированы в системе")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🤖 Торговый бот - Помощь

📋 Доступные команды:

/start - Регистрация и подписка на сигналы
/status - Текущий статус позиции и индикаторы  
/subscribe - Подписаться на сигналы
/unsubscribe - Отписаться от сигналов
/help - Показать это сообщение

📊 О стратегии:
• Используется ADX, +DI, -DI, EMA100
• Таймфрейм: 15 минут
• Актив: SBER

⚠️ Важно: Сигналы носят информационный характер и не являются инвестиционными рекомендациями.
    """
    await update.message.reply_text(help_text)

# === Основной запуск ===
def main():
    app = Application.builder().token(TOKEN_TELEGRAM).build()

    # Добавляем обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
    app.add_handler(CommandHandler("help", help_command))

    # Запускаем отправку сигналов каждые 15 минут
    app.job_queue.run_repeating(send_signal, interval=900, first=5)

    logger.info("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
