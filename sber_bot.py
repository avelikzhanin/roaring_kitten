import asyncio
import logging
from datetime import datetime, timezone, timedelta

import pandas as pd
import numpy as np
from tinkoff.invest import Client, CandleInterval
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ------------------- Настройки -------------------
TINKOFF_TOKEN = "ТВОЙ_TINKOFF_TOKEN"
TELEGRAM_TOKEN = "ТВОЙ_TELEGRAM_BOT_TOKEN"
CHAT_ID = "ТВОЙ_CHAT_ID"  # ID чата для уведомлений
FIGI = "BBG004730N88"  # SBER
CHECK_INTERVAL = 10 * 60  # каждые 10 минут

# ------------------- Логирование -------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------- История сделок -------------------
trades = []  # {"type": "LONG/SHORT", "price": float, "time": datetime, "status": "OPEN/CLOSED"}

# ------------------- Функции работы с данными -------------------
def get_candles():
    with Client(TINKOFF_TOKEN) as client:
        to_time = datetime.now(timezone.utc)
        from_time = to_time - timedelta(days=30)
        candles = client.market_data.get_candles(
            figi=FIGI,
            from_=from_time,
            to=to_time,
            interval=CandleInterval.CANDLE_INTERVAL_H1
        ).candles

    data = pd.DataFrame([{
        "time": c.time,
        "open": c.open,
        "high": c.high,
        "low": c.low,
        "close": c.close,
        "volume": c.volume
    } for c in candles])

    return data

def ema100(df):
    return df['close'].ewm(span=100, adjust=False).mean()

def true_range(df):
    tr1 = df['high'] - df['low']
    tr2 = abs(df['high'] - df['close'].shift())
    tr3 = abs(df['low'] - df['close'].shift())
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

def adx(df, period=14):
    df['TR'] = true_range(df)
    df['+DM'] = df['high'].diff()
    df['-DM'] = df['low'].diff() * -1

    df['+DM'] = np.where((df['+DM'] > df['-DM']) & (df['+DM'] > 0), df['+DM'], 0.0)
    df['-DM'] = np.where((df['-DM'] > df['+DM']) & (df['-DM'] > 0), df['-DM'], 0.0)

    df['+DI'] = 100 * df['+DM'].rolling(period).sum() / df['TR'].rolling(period).sum()
    df['-DI'] = 100 * df['-DM'].rolling(period).sum() / df['TR'].rolling(period).sum()
    df['DX'] = 100 * abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI'])
    df['ADX'] = df['DX'].rolling(period).mean()
    return df

def get_signal(df):
    df = df.copy()
    df['EMA100'] = ema100(df)
    df = adx(df)

    last = df.iloc[-1]
    volume_avg = df['volume'].rolling(14).mean().iloc[-1]
    strong_candle = abs(last['close'] - last['open']) > (df['high'] - df['low']).rolling(14).mean().iloc[-1]

    # Long
    if last['close'] > last['EMA100'] and last['+DI'] > last['-DI'] and last['ADX'] > 23 and last['volume'] > volume_avg and strong_candle:
        return "LONG"
    # Short
    elif last['close'] < last['EMA100'] and last['-DI'] > last['+DI'] and last['ADX'] > 23 and last['volume'] > volume_avg and strong_candle:
        return "SHORT"
    return None

def calculate_profit():
    profit = 0.0
    for trade in trades:
        if trade['status'] == 'CLOSED':
            if trade['type'] == 'LONG':
                profit += (trade['exit_price'] - trade['price']) / trade['price'] * 100
            else:  # SHORT
                profit += (trade['price'] - trade['exit_price']) / trade['price'] * 100
    return profit

def format_trades():
    lines = []
    for t in trades:
        if t['status'] == 'OPEN':
            lines.append(f"{t['time']:%Y-%m-%d %H:%M} | {t['type']} | OPEN @ {t['price']:.2f}")
        else:
            lines.append(f"{t['time']:%Y-%m-%d %H:%M} | {t['type']} | CLOSED @ {t['exit_price']:.2f}")
    return "\n".join(lines)

# ------------------- Telegram команды -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот запущен и отслеживает сигналы Long/Short для SBER.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"История сделок:\n{format_trades()}\n\nОбщая прибыль: {calculate_profit():.2f}%")

# ------------------- Основной цикл сигналов -------------------
async def signal_loop(app):
    while True:
        try:
            df = get_candles()
            signal = get_signal(df)
            now = datetime.now()
            last_trade = trades[-1] if trades else None

            # Закрытие открытой сделки, если появился противоположный сигнал
            if last_trade and last_trade['status'] == 'OPEN':
                if (last_trade['type'] == 'LONG' and signal == 'SHORT') or (last_trade['type'] == 'SHORT' and signal == 'LONG'):
                    last_trade['status'] = 'CLOSED'
                    last_trade['exit_price'] = df.iloc[-1]['close']
                    await app.bot.send_message(chat_id=CHAT_ID,
                                               text=f"Закрыта сделка {last_trade['type']} @ {last_trade['exit_price']:.2f}")

            # Открытие новой сделки при наличии сигнала
            if (not last_trade) or (last_trade['status'] == 'CLOSED'):
                if signal in ['LONG', 'SHORT']:
                    trades.append({
                        "type": signal,
                        "price": df.iloc[-1]['close'],
                        "time": now,
                        "status": "OPEN"
                    })
                    await app.bot.send_message(chat_id=CHAT_ID,
                                               text=f"Открыта сделка {signal} @ {df.iloc[-1]['close']:.2f}")

        except Exception as e:
            logger.error(f"Ошибка в signal_loop: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

# ------------------- Запуск бота -------------------
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))

    # Запуск цикла сигналов как фоновая задача
    app.job_queue.run_repeating(lambda _: asyncio.create_task(signal_loop(app)), interval=CHECK_INTERVAL, first=5)

    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
