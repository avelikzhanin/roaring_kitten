# -*- coding: utf-8 -*-
import os
import logging
import pandas as pd
import numpy as np
from datetime import timedelta
from tinkoff.invest import Client
from tinkoff.invest.schemas import CandleInterval
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# =========================
# Конфиг
# =========================
BOT_VERSION = "v0.14 — strict BUY/SELL + directional DI emojis"
TINKOFF_API_TOKEN = os.getenv("TINKOFF_API_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

FIGI = "BBG004730N88"             # SBER
TF = CandleInterval.CANDLE_INTERVAL_HOUR
LOOKBACK_HOURS = 200
TRAIL_PCT = 0.015

# Глобальное состояние позиции (если используешь)
position_type = None   # "long" / "short" / None
entry_price = None
best_price = None
trailing_stop = None

# Логирование
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sber-bot")

# =========================
# Индикаторы (Wilder ADX)
# =========================
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    prev_close = close.shift(1)
    up_move = high.diff()
    down_move = low.shift(1) - low  # положительное значение = движение вниз

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    # Wilder smoothing через EWM с alpha=1/period
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
    if not TINKOFF_API_TOKEN:
        raise RuntimeError("Переменная окружения TINKOFF_API_TOKEN не задана.")
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

    # Направление BUY
    di_buy = last["+DI"] > last["-DI"]
    ema_buy = last["close"] > last["ema100"]

    # Направление SELL
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
# Трейлинг (если надо)
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
# Формирование текста
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

    # Параметры + пороги
    lines = []
    lines.append("📊 Параметры стратегии:")
    lines.append(f"ADX: {adx:.2f} {emoji(conds['adx_cond'])} (порог > 23)")
    lines.append(f"Объём: {int(vol)} {emoji(conds['vol_cond'])} (MA20 = {int(vol_ma20)})")

    # EMA — в зависимости от направления (покажем обе стороны)
    lines.append(f"EMA100: {ema100:.2f} | BUY: {emoji(conds['ema_buy'])} (цена {price:.2f} > EMA) | SELL: {emoji(conds['ema_sell'])} (цена {price:.2f} < EMA)")

    # DI — тоже в обе стороны
    lines.append(f"+DI / -DI: {plus_di:.2f} / {minus_di:.2f} | BUY: {emoji(conds['di_buy'])} (+DI > -DI) | SELL: {emoji(conds['di_sell'])} (-DI > +DI)")

    # Итоговый сигнал
    if conds["signal"] == "BUY":
        lines.append("\n✅ Сигнал стратегии: BUY")
    elif conds["signal"] == "SELL":
        lines.append("\n✅ Сигнал стратегии: SELL")
    else:
        lines.append("\n❌ Сигналов по стратегии нет")

    # Блок по позиции
    if position_type and entry_price:
        if position_type == "long":
            pnl = (price - entry_price) / entry_price * 100
        else:  # short
            pnl = (entry_price - price) / entry_price * 100
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
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
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
# Main
# =========================
def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("Переменная окружения TELEGRAM_TOKEN не задана.")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_cmd))
    app.run_polling()

if __name__ == "__main__":
    main()
