import os
import logging
import pandas as pd
import numpy as np
from datetime import timedelta
from threading import Thread
import time

from tinkoff.invest import Client
from tinkoff.invest.schemas import CandleInterval
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import requests

# =========================
# Конфиг
# =========================
BOT_VERSION = "v0.18 — auto-check every 15min"
TINKOFF_API_TOKEN = os.getenv("TINKOFF_API_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

FIGI = "BBG004730N88"             # SBER
TF = CandleInterval.CANDLE_INTERVAL_HOUR
LOOKBACK_HOURS = 200
CHECK_INTERVAL = 900  # 15 минут
TRAIL_PCT = 0.015

CHAT_ID_FILE = "chat_id.txt"

# Глобальное состояние позиции
position_type = None   # "long" / "short" / None
entry_price = None
best_price = None
trailing_stop = None
last_signal_sent = None

# Логирование
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sber-bot")

# =========================
# Работа с chat_id
# =========================
def save_chat_id(chat_id):
    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))
    log.info(f"Chat ID сохранён: {chat_id}")

def load_chat_id():
    if os.path.exists(CHAT_ID_FILE):
        with open(CHAT_ID_FILE, "r") as f:
            return f.read().strip()
    return None

# =========================
# Индикаторы
# =========================
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    prev_close = close.shift(1)
    up_move = high.diff()
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (pd.Series(plus_dm, index=high.index).ewm(alpha=1/period, adjust=False).mean() / atr)
    minus_di = 100 * (pd.Series(minus_dm, index=high.index).ewm(alpha=1/period, adjust=False).mean() / atr)

    dx = 100 * (plus_di.subtract(minus_di).abs() / (plus_di + minus_di))
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx, plus_di, minus_di

# =========================
# Данные
# =========================
def get_candles() -> pd.DataFrame:
    with Client(TINKOFF_API_TOKEN) as client:
        now = pd.Timestamp.now(tz="Europe/Moscow")
        candles = client.market_data.get_candles(
            figi=FIGI,
            from_=now - pd.Timedelta(hours=LOOKBACK_HOURS),
            to=now,
            interval=TF
        ).candles

    df = pd.DataFrame([{
        "time": c.time,
        "open": c.open.units + c.open.nano / 1e9,
        "high": c.high.units + c.high.nano / 1e9,
        "low":  c.low.units  + c.low.nano  / 1e9,
        "close":c.close.units+ c.close.nano / 1e9,
        "volume": c.volume
    } for c in candles])
    return df

# =========================
# Оценка условий и сигнал
# =========================
def evaluate_signal(df: pd.DataFrame):
    df = df.copy()
    df["ema100"] = ema(df["close"], 100)
    df["ADX"], df["+DI"], df["-DI"] = compute_adx(df["high"], df["low"], df["close"], period=14)
    df["vol_ma20"] = df["volume"].rolling(20).mean()

    last = df.iloc[-1]

    adx_cond = last["ADX"] > 23
    vol_cond = last["volume"] > last["vol_ma20"]

    di_buy = last["+DI"] > last["-DI"]
    ema_buy = last["close"] > last["ema100"]

    di_sell = last["-DI"] > last["+DI"]
    ema_sell = last["close"] < last["ema100"]

    buy_ok = adx_cond and di_buy and vol_cond and ema_buy
    sell_ok = adx_cond and di_sell and vol_cond and ema_sell

    if buy_ok:
        signal = "BUY"
    elif sell_ok:
        signal = "SELL"
    else:
        signal = None

    return last, {
        "adx_cond": adx_cond,
        "vol_cond": vol_cond,
        "di_buy": di_buy,
        "ema_buy": ema_buy,
        "di_sell": di_sell,
        "ema_sell": ema_sell,
        "signal": signal,
        "vol_ma20": last["vol_ma20"]
    }, df

# =========================
# Трейлинг
# =========================
def update_trailing(curr_price: float):
    global trailing_stop, best_price, position_type
    if position_type == "long":
        best_price = max(best_price or curr_price, curr_price)
        trailing_stop = best_price * (1 - TRAIL_PCT)
    elif position_type == "short":
        best_price = min(best_price or curr_price, curr_price)
        trailing_stop = best_price * (1 + TRAIL_PCT)

# =========================
# Сообщение
# =========================
def emoji(ok: bool) -> str:
    return "✅" if ok else "❌"

def build_message(last: pd.Series, conds: dict) -> str:
    global position_type, entry_price, trailing_stop

    price = last["close"]
    adx = last["ADX"]
    plus_di = last["+DI"]
    minus_di = last["-DI"]
    ema100 = last["ema100"]
    vol = last["volume"]
    vol_ma20 = conds["vol_ma20"]

    lines = []
    lines.append("📊 Параметры стратегии:")

    lines.append(f"ADX: {adx:.2f} | BUY: {emoji(conds['adx_cond'])} | SELL: {emoji(conds['adx_cond'])} (порог > 23)")
    lines.append(f"Объём: {int(vol)} | BUY: {emoji(conds['vol_cond'])} | SELL: {emoji(conds['vol_cond'])} (MA20={int(vol_ma20)})")
    lines.append(f"EMA100: {ema100:.2f} | BUY: {emoji(conds['ema_buy'])} | SELL: {emoji(conds['ema_sell'])}")
    lines.append(f"+DI / -DI: {plus_di:.2f} / {minus_di:.2f} | BUY: {emoji(conds['di_buy'])} | SELL: {emoji(conds['di_sell'])}")

    if conds["signal"]:
        lines.append(f"\n📢 Сигнал стратегии: {conds['signal']}")
    else:
        lines.append("\n❌ Сигналов по стратегии нет")

    if position_type and entry_price:
        pnl = (price - entry_price) / entry_price * 100 if position_type=="long" else (entry_price - price)/entry_price*100
        ts_text = f"{trailing_stop:.2f}" if trailing_stop else "-"
        lines.append(f"\nТекущая цена: {price:.2f}")
        lines.append(f"Тип позиции: {position_type}")
        lines.append(f"Цена входа: {entry_price:.2f}")
        lines.append(f"Трейлинг-стоп: {ts_text}")
        lines.append(f"Текущая прибыль: {pnl:.2f}%")
    else:
        lines.append(f"\nТекущая цена: {price:.2f}")
        lines.append("Тип позиции: -")
        lines.append("Цена входа: -")
        lines.append("Трейлинг-стоп: -")
        lines.append("Текущая прибыль: -")

    lines.append(f"\n🧩 Версия бота: {BOT_VERSION}")
    return "\n".join(lines)

# =========================
# Telegram Handlers
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"😺 Ревущий котёнок на связи! Буду присылать сигналы по SBER\nВерсия: {BOT_VERSION}"
    )

async def signal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        df = get_candles()
        last, conds, _ = evaluate_signal(df)
        msg = build_message(last, conds)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)
    except Exception as e:
        log.exception("Ошибка в /signal")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Ошибка: {e}")

# =========================
# Авто-проверка и управление позицией
# =========================
def auto_check(app):
    global last_signal_sent, position_type, entry_price, best_price, trailing_stop
    while True:
        try:
            df = get_candles()
            last, conds, _ = evaluate_signal(df)
            current_signal = conds["signal"]
            price = last["close"]
            chat_id = load_chat_id()

            # Обновляем трейлинг-стоп
            if position_type:
                update_trailing(price)
                exit_pos = False
                if position_type=="long" and price <= trailing_stop:
                    exit_pos = True
                elif position_type=="short" and price >= trailing_stop:
                    exit_pos = True
                if exit_pos:
                    pnl = (price - entry_price)/entry_price*100 if position_type=="long" else (entry_price - price)/entry_price*100
                    msg = f"❌ Закрытие позиции {position_type.upper()}!\nЦена: {price:.2f}\nПрибыль: {pnl:.2f}%"
                    if chat_id:
                        app.bot.send_message(chat_id=chat_id, text=msg)
                    position_type = None
                    entry_price = None
                    best_price = None
                    trailing_stop = None

            # Новый сигнал — открываем позицию
            if current_signal and current_signal != last_signal_sent and not position_type:
                position_type = "long" if current_signal=="BUY" else "short"
                entry_price = price
                best_price = price
                trailing_stop = price*(1-TRAIL_PCT) if position_type=="long" else price*(1+TRAIL_PCT)
                if chat_id:
                    msg = build_message(last, conds)
                    app.bot.send_message(chat_id=chat_id, text=msg)
                last_signal_sent = current_signal

        except Exception as e:
            log.exception("Ошибка в авто-проверке сигналов")
        time.sleep(CHECK_INTERVAL)

# =========================
# Main
# =========================
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_cmd))

    Thread(target=auto_check, args=(app,), daemon=True).start()
    app.run_polling()

if __name__ == "__main__":
    main()
