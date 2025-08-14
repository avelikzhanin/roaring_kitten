import os
import logging
import time
from threading import Thread
import pandas as pd
from tinkoff.invest import Client
from tinkoff.invest.schemas import CandleInterval
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Настройки ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TINKOFF_TOKEN = os.getenv("TINKOFF_API_TOKEN")
FIGI = "BBG004730N88"  # SBER
HISTORY_HOURS = 200
INTERVAL = CandleInterval.CANDLE_INTERVAL_HOUR
TRAIL_PCT = 0.015  # трейлинг-стоп 1.5%
CHAT_ID_FILE = "chat_id.txt"

# --- Логирование ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Состояние стратегии ---
position_type = None  # None / 'long' / 'short'
entry_price = None
trailing_stop = None
best_price = None
signal_sent = False

# --- Telegram utilities ---
def save_chat_id(chat_id):
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))
    logging.info(f"Chat ID saved: {chat_id}")

def load_chat_id():
    if os.path.exists(CHAT_ID_FILE):
        with open(CHAT_ID_FILE, "r") as f:
            return int(f.read().strip())
    return None

def send_telegram_message(text):
    chat_id = load_chat_id()
    if not chat_id:
        logging.warning("❌ Chat ID не найден — отправьте /start")
        return
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

# --- Telegram handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
    await context.bot.send_message(chat_id=chat_id, text="😺 Бот активирован. Ожидаем сигналы.")

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_price = get_current_price()
    pnl_text = "-"
    if position_type and entry_price:
        pnl = (current_price - entry_price) / entry_price * 100
        if position_type == "short":
            pnl = -pnl
        pnl_text = f"{pnl:.2f}%"

    text = (
        f"Текущая цена: {current_price:.2f}\n"
        f"Тип позиции: {position_type or '-'}\n"
        f"Цена входа: {entry_price if entry_price else '-'}\n"
        f"Трейлинг-стоп: {trailing_stop if trailing_stop else '-'}\n"
        f"Текущая прибыль: {pnl_text}"
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)

# --- Индикаторы ---
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def adx(high, low, close, period=14):
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr).abs()
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    return dx.rolling(window=period).mean(), plus_di, minus_di

# --- Получение свечей ---
def get_candles():
    with Client(TINKOFF_TOKEN) as client:
        now_time = pd.Timestamp.now(tz="Europe/Moscow")
        candles = client.market_data.get_candles(
            figi=FIGI,
            from_=now_time - pd.Timedelta(hours=HISTORY_HOURS),
            to=now_time,
            interval=INTERVAL
        ).candles
        df = pd.DataFrame([{
            "time": c.time,
            "open": c.open.units + c.open.nano / 1e9,
            "high": c.high.units + c.high.nano / 1e9,
            "low": c.low.units + c.low.nano / 1e9,
            "close": c.close.units + c.close.nano / 1e9,
            "volume": c.volume
        } for c in candles])
    return df

def get_current_price():
    df = get_candles()
    return df["close"].iloc[-1]

# --- Сигнал стратегии ---
def check_signal(df):
    df["ema100"] = ema(df["close"], 100)
    df["ADX"], df["+DI"], df["-DI"] = adx(df["high"], df["low"], df["close"])
    vol_ma = df["volume"].rolling(20).mean()
    last = df.iloc[-1]

    if last["ADX"] > 23 and last["+DI"] > last["-DI"] and last["close"] > last["ema100"] and last["volume"] > vol_ma.iloc[-1]:
        return "BUY"
    elif last["ADX"] < 20 or last["close"] < last["ema100"]:
        return "SELL"
    else:
        return None

# --- Трейлинг ---
def update_trailing(curr_price):
    global trailing_stop, best_price
    if position_type == "long":
        best_price = max(best_price, curr_price)
        trailing_stop = best_price * (1 - TRAIL_PCT)
    elif position_type == "short":
        best_price = min(best_price, curr_price)
        trailing_stop = best_price * (1 + TRAIL_PCT)

def should_close(curr_price):
    if not trailing_stop or not position_type:
        return False
    if position_type == "long":
        return curr_price <= trailing_stop
    else:
        return curr_price >= trailing_stop

# --- Основной цикл ---
def main_loop():
    global position_type, entry_price, trailing_stop, best_price, signal_sent
    while True:
        try:
            df = get_candles()
            curr_price = df["close"].iloc[-1]
            signal = check_signal(df)

            # Если позиция открыта, проверяем трейлинг и обратный сигнал
            if position_type:
                update_trailing(curr_price)
                
                # Закрытие по трейлинг-стопу
                if should_close(curr_price):
                    pnl = (curr_price - entry_price)/entry_price*100 if position_type=="long" else (entry_price - curr_price)/entry_price*100
                    send_telegram_message(f"🔔 Закрытие {position_type} по трейлинг-стопу {curr_price:.2f}\nPnL: {pnl:.2f}%")
                    position_type = None
                    entry_price = None
                    trailing_stop = None
                    best_price = None
                    signal_sent = False
                    continue

                # Закрытие по обратному сигналу
                if (position_type == "long" and signal == "SELL") or (position_type == "short" and signal == "BUY"):
                    pnl = (curr_price - entry_price)/entry_price*100 if position_type=="long" else (entry_price - curr_price)/entry_price*100
                    send_telegram_message(f"🔔 Закрытие {position_type} по обратному сигналу {signal}\nЦена: {curr_price:.2f}\nPnL: {pnl:.2f}%")
                    position_type = None
                    entry_price = None
                    trailing_stop = None
                    best_price = None
                    signal_sent = False
                    continue

            # Открытие новой позиции
            if not position_type and signal and not signal_sent:
                position_type = "long" if signal=="BUY" else "short"
                entry_price = curr_price
                best_price = curr_price
                trailing_stop = None
                signal_sent = True
                send_telegram_message(f"📈 Открытие {position_type} по {entry_price:.2f}")

        except Exception as e:
            logging.error(f"Ошибка main_loop: {e}")
        time.sleep(300)

# --- Запуск Telegram ---
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_command))

    Thread(target=main_loop, daemon=True).start()
    app.run_polling()
