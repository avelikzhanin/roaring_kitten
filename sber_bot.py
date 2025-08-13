import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import pandas as pd
import talib
from tinkoff.invest import Client
from tinkoff.invest.services import InstrumentsService
from datetime import datetime, timedelta, timezone

# === НАСТРОЙКИ ===
TOKEN_TG = "ТВОЙ_ТОКЕН_ТЕЛЕГРАМ"
CHAT_ID = 215592311
TOKEN_TINKOFF = "ТВОЙ_ТОКЕН_ТИНЬКОФФ"
FIGI = "BBG004730N88"  # Сбербанк
TIMEFRAME_MINUTES = 60

# === ГЛОБАЛЬНОЕ СОСТОЯНИЕ ===
in_position = False
last_signal = None

# === ФУНКЦИЯ ЗАГРУЗКИ ДАННЫХ ===
async def get_candles():
    with Client(TOKEN_TINKOFF) as client:
        now = datetime.now(timezone.utc)
        from_ = now - timedelta(days=5)
        to = now
        candles = client.market_data.get_candles(
            figi=FIGI,
            from_=from_,
            to=to,
            interval=client.market_data.CandleInterval.CANDLE_INTERVAL_HOUR
        ).candles

        data = pd.DataFrame([{
            "time": c.time,
            "open": float(c.open.units + c.open.nano / 1e9),
            "high": float(c.high.units + c.high.nano / 1e9),
            "low": float(c.low.units + c.low.nano / 1e9),
            "close": float(c.close.units + c.close.nano / 1e9),
            "volume": c.volume
        } for c in candles])

        return data

# === РАСЧЁТ ИНДИКАТОРОВ ===
async def get_signal():
    df = await get_candles()

    if df.empty or len(df) < 100:
        return None, None, None

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    volume = df["volume"].values

    ema100 = talib.EMA(close, timeperiod=100)
    adx = talib.ADX(high, low, close, timeperiod=14)
    plus_di = talib.PLUS_DI(high, low, close, timeperiod=14)
    minus_di = talib.MINUS_DI(high, low, close, timeperiod=14)
    avg_volume = df["volume"].rolling(20).mean()

    last_idx = -1
    price = close[last_idx]

    # Условия входа в лонг
    long_cond = (adx[last_idx] > 23 and
                 plus_di[last_idx] > minus_di[last_idx] and
                 volume[last_idx] > avg_volume.iloc[last_idx] and
                 price > ema100[last_idx])

    # Условия выхода из лонга
    exit_long = (adx[last_idx] < 23 or
                 plus_di[last_idx] < minus_di[last_idx] or
                 price < ema100[last_idx])

    if long_cond:
        return "buy", adx[last_idx], price
    elif exit_long:
        return "exit", adx[last_idx], price
    else:
        return None, adx[last_idx], price

# === ОБРАБОТКА КОМАНД ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я бот сигналов по Сбербанку. Команда /signal покажет текущий сигнал.")

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    direction, adx, price = await get_signal()
    if direction:
        await update.message.reply_text(f"Сигнал: {direction.upper()} — ADX={adx:.2f}, цена={price:.2f}")
    else:
        await update.message.reply_text("Сигнала нет.")

# === АВТОМАТИЧЕСКАЯ ПРОВЕРКА ===
async def auto_check(app: Application):
    global in_position, last_signal
    while True:
        direction, adx, price = await get_signal()
        if not in_position and direction == "buy":
            in_position = True
            last_signal = "buy"
            await app.bot.send_message(chat_id=CHAT_ID, text=f"📈 BUY сигнал — ADX={adx:.2f}, цена={price:.2f}")
        elif in_position and direction == "exit":
            in_position = False
            last_signal = "exit"
            await app.bot.send_message(chat_id=CHAT_ID, text=f"📤 Выход из сделки — ADX={adx:.2f}, цена={price:.2f}")
        await asyncio.sleep(300)  # каждые 5 минут

# === ЗАПУСК ===
def main():
    app = Application.builder().token(TOKEN_TG).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal))
    app.job_queue.run_once(lambda _: asyncio.create_task(auto_check(app)), when=1)
    app.run_polling()

if __name__ == "__main__":
    main()
