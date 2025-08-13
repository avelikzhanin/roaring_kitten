import os
import logging
import asyncio
from datetime import datetime
import pandas as pd
from tinkoff.invest import Client
from tinkoff.invest.schemas import CandleInterval
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- Логирование ---
logging.basicConfig(level=logging.INFO)

# --- Переменные окружения ---
TOKEN = os.getenv("TINKOFF_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
FIGI = "BBG004730N88"  # SBER
INTERVAL = CandleInterval.CANDLE_INTERVAL_HOUR
HISTORY_HOURS = 200
CHAT_ID_FILE = "chat_id.txt"
DEAL_HISTORY_FILE = "deal_history.csv"

# --- Chat ID ---
def save_chat_id(chat_id):
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))
    logging.info(f"Chat ID saved: {chat_id}")

def load_chat_id():
    if os.path.exists(CHAT_ID_FILE):
        with open(CHAT_ID_FILE, "r") as f:
            return f.read().strip()
    return None

# --- EMA и ADX ---
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def adx(high, low, close, period=14):
    plus_dm = high.diff()
    minus_dm = low.diff()

    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(window=period).mean()
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.rolling(window=period).mean()
    return adx, plus_di, minus_di

# --- Получение свечей ---
def get_candles():
    with Client(TOKEN) as client:
        now = pd.Timestamp.now(tz="Europe/Moscow")
        candles = client.market_data.get_candles(
            figi=FIGI,
            from_=now - pd.Timedelta(hours=HISTORY_HOURS),
            to=now,
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

# --- История сделок ---
def load_history():
    if os.path.exists(DEAL_HISTORY_FILE):
        return pd.read_csv(DEAL_HISTORY_FILE)
    return pd.DataFrame(columns=["type","entry_price","exit_price","profit_pct","time_entry","time_exit"])

def save_history(df):
    df.to_csv(DEAL_HISTORY_FILE, index=False)

# --- Проверка сигналов ---
current_position = None  # None, "LONG", "SHORT"

def check_signal():
    global current_position
    df = get_candles()
    df["ema100"] = ema(df["close"], 100)
    df["ADX"], df["+DI"], df["-DI"] = adx(df["high"], df["low"], df["close"])
    vol_ma = df["volume"].rolling(window=20).mean()
    last = df.iloc[-1]

    entry_signal = None
    exit_signal = None

    if current_position is None:
        # Вход
        if last["ADX"] > 23 and last["+DI"] > last["-DI"] and last["close"] > last["ema100"] and last["volume"] > vol_ma.iloc[-1]:
            entry_signal = ("LONG", last["close"], last["time"])
            current_position = "LONG"
        elif last["ADX"] > 23 and last["+DI"] < last["-DI"] and last["close"] < last["ema100"] and last["volume"] > vol_ma.iloc[-1]:
            entry_signal = ("SHORT", last["close"], last["time"])
            current_position = "SHORT"
    else:
        # Выход
        if current_position == "LONG":
            if last["ADX"] < 20 or last["close"] < last["ema100"]:
                exit_signal = ("LONG", last["close"], last["time"])
                current_position = None
        elif current_position == "SHORT":
            if last["ADX"] < 20 or last["close"] > last["ema100"]:
                exit_signal = ("SHORT", last["close"], last["time"])
                current_position = None

    return entry_signal, exit_signal

# --- Отправка сообщений ---
async def send_telegram_message(text):
    chat_id = load_chat_id()
    if not chat_id:
        logging.warning("❌ Chat ID не найден — напиши /start боту")
        return
    from telegram import Bot
    bot = Bot(TELEGRAM_TOKEN)
    await bot.send_message(chat_id=chat_id, text=text)

# --- Команды Telegram ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
    await update.message.reply_text("✅ Chat ID сохранён! Теперь бот будет присылать сигналы.")

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    entry, exit_ = await asyncio.to_thread(check_signal)
    msg = ""
    if entry:
        msg += f"📈 Вход {entry[0]} — цена {entry[1]:.2f}\n"
    if exit_:
        msg += f"📉 Выход {exit_[0]} — цена {exit_[1]:.2f}\n"
    if not msg:
        msg = "Нет активных сигналов сейчас."
    await update.message.reply_text(msg)

# --- Цикл сигналов ---
async def signal_loop(app):
    while True:
        entry, exit_ = await asyncio.to_thread(check_signal)
        history = load_history()

        if entry:
            msg = f"📈 Вход {entry[0]} — цена {entry[1]:.2f}"
            await send_telegram_message(msg)
            history = history.append({
                "type": entry[0],
                "entry_price": entry[1],
                "exit_price": None,
                "profit_pct": None,
                "time_entry": entry[2],
                "time_exit": None
            }, ignore_index=True)
            save_history(history)

        if exit_:
            last_idx = history[(history["type"]==exit_[0]) & (history["exit_price"].isna())].index[-1]
            history.at[last_idx,"exit_price"] = exit_[1]
            history.at[last_idx,"time_exit"] = exit_[2]
            entry_price = history.at[last_idx,"entry_price"]
            profit_pct = (exit_[1]-entry_price)/entry_price*100
            if exit_[0]=="SHORT":
                profit_pct = -profit_pct
            history.at[last_idx,"profit_pct"] = profit_pct
            save_history(history)
            msg = f"📉 Выход {exit_[0]} — цена {exit_[1]:.2f}, P/L {profit_pct:.2f}%"
            await send_telegram_message(msg)

        await asyncio.sleep(300)

# --- Main ---
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_command))
    app.post_init(lambda _: asyncio.create_task(signal_loop(app)))
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
