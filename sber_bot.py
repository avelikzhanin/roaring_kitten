import os
import logging
import pandas as pd
from tinkoff.invest import Client
from tinkoff.invest.schemas import CandleInterval
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# =========================
# Конфиг
# =========================
BOT_VERSION = "v0.24 — асинхронные сделки + автосигналы + апдейты"
TINKOFF_API_TOKEN = os.getenv("TINKOFF_API_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

FIGI = "BBG004730N88"             # SBER
TF = CandleInterval.CANDLE_INTERVAL_HOUR
LOOKBACK_HOURS = 200
CHECK_INTERVAL = 60  # секунд
TRAIL_PCT = 0.015
ADX_THRESHOLD = 23

CHAT_ID_FILE = "chat_id.txt"

# =========================
# Глобальное состояние позиции
# =========================
position_type = None
entry_price = None
best_price = None
trailing_stop = None

# =========================
# Логирование
# =========================
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

def adx(high, low, close, period=14):
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0

    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(window=period).mean()

    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = abs(100 * (minus_dm.rolling(window=period).mean() / atr))

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx_val = dx.rolling(window=period).mean()
    return adx_val, plus_di, minus_di

# =========================
# Данные
# =========================
def get_candles():
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
# Оценка сигналов
# =========================
def evaluate_signal(df):
    df = df.copy()
    df["ema100"] = ema(df["close"], 100)
    df["ADX"], df["+DI"], df["-DI"] = adx(df["high"], df["low"], df["close"], period=14)
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    last = df.iloc[-1]

    adx_cond = last["ADX"] > ADX_THRESHOLD
    vol_cond = last["volume"] > last["vol_ma20"]
    di_buy = last["+DI"] > last["-DI"]
    ema_buy = last["close"] > last["ema100"]
    di_sell = last["-DI"] > last["+DI"]
    ema_sell = last["close"] < last["ema100"]

    buy_ok = adx_cond and di_buy and vol_cond and ema_buy
    sell_ok = adx_cond and di_sell and vol_cond and ema_sell

    signal = "BUY" if buy_ok else "SELL" if sell_ok else None

    return last, {
        "adx_cond": adx_cond, "vol_cond": vol_cond, "di_buy": di_buy, "ema_buy": ema_buy,
        "di_sell": di_sell, "ema_sell": ema_sell, "signal": signal, "vol_ma20": last["vol_ma20"]
    }

# =========================
# Трейлинг
# =========================
def update_trailing(curr_price):
    global trailing_stop, best_price, position_type
    if position_type == "long":
        best_price = max(best_price or curr_price, curr_price)
        trailing_stop = best_price * (1 - TRAIL_PCT)
    elif position_type == "short":
        best_price = min(best_price or curr_price, curr_price)
        trailing_stop = best_price * (1 + TRAIL_PCT)

# =========================
# Сообщения
# =========================
def build_message(last, conds):
    global position_type, entry_price, trailing_stop
    price = last["close"]
    lines = [
        f"📊 ADX: {last['ADX']:.2f} | BUY: {'✅' if conds['adx_cond'] else '❌'} | SELL: {'✅' if conds['adx_cond'] else '❌'}",
        f"Объём: {int(last['volume'])} | BUY: {'✅' if conds['vol_cond'] else '❌'} | SELL: {'✅' if conds['vol_cond'] else '❌'}",
        f"EMA100: {last['ema100']:.2f} | BUY: {'✅' if conds['ema_buy'] else '❌'} | SELL: {'✅' if conds['ema_sell'] else '❌'}",
        f"+DI / -DI: {last['+DI']:.2f}/{last['-DI']:.2f} | BUY: {'✅' if conds['di_buy'] else '❌'} | SELL: {'✅' if conds['di_sell'] else '❌'}"
    ]
    if conds["signal"]:
        lines.append(f"\n📢 Сигнал: {conds['signal']}")
    if position_type and entry_price:
        pnl = (price - entry_price)/entry_price*100 if position_type=="long" else (entry_price - price)/entry_price*100
        lines.append(f"\nТекущая цена: {price:.2f}\nПозиция: {position_type}\nВход: {entry_price:.2f}\nТрейлинг: {trailing_stop:.2f}\nPNL: {pnl:.2f}%")
    return "\n".join(lines)

# =========================
# Telegram Handlers
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
    await context.bot.send_message(chat_id=chat_id, text=f"😺 Бот на связи!\nВерсия: {BOT_VERSION}")

async def signal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    df = get_candles()
    last, conds = evaluate_signal(df)
    msg = build_message(last, conds)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)

# =========================
# Авто-проверка сигналов
# =========================
async def auto_check(app):
    global position_type, entry_price, best_price, trailing_stop
    while True:
        try:
            df = get_candles()
            last, conds = evaluate_signal(df)
            chat_id = load_chat_id()
            price = last["close"]
            signal = conds["signal"]

            # Обновляем трейлинг и закрытие
            if position_type:
                update_trailing(price)
                close_pos = False
                reason = ""
                if position_type=="long" and (price <= trailing_stop or signal!="BUY"):
                    close_pos = True
                    reason = "трейлинг/сигнал"
                elif position_type=="short" and (price >= trailing_stop or signal!="SELL"):
                    close_pos = True
                    reason = "трейлинг/сигнал"
                if close_pos and chat_id:
                    pnl = (price-entry_price)/entry_price*100 if position_type=="long" else (entry_price-price)/entry_price*100
                    await app.bot.send_message(chat_id, f"❌ Закрытие позиции {position_type.upper()} ({reason})\nЦена: {price:.2f}\nPNL: {pnl:.2f}%")
                    position_type = entry_price = best_price = trailing_stop = None

            # Новый сигнал
            if signal and not position_type and chat_id:
                position_type = "long" if signal=="BUY" else "short"
                entry_price = price
                best_price = price
                trailing_stop = price*(1-TRAIL_PCT) if position_type=="long" else price*(1+TRAIL_PCT)
                await app.bot.send_message(chat_id, build_message(last, conds))
        except Exception as e:
            log.exception("Ошибка в авто-проверке сигналов")
        await asyncio.sleep(CHECK_INTERVAL)

# =========================
# Main
# =========================
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", signal_cmd))

    await app.initialize()
    await app.start()
    app.create_task(auto_check(app))
    await app.updater.start_polling()
    await asyncio.Event().wait()

# =========================
# Запуск
# =========================
if __name__ == "__main__":
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(main())
    except RuntimeError:
        asyncio.run(main())
