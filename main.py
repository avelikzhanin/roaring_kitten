import os
import asyncio
from datetime import datetime, timedelta
import logging

import pandas as pd
import pandas_ta as ta
import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Переменные окружения
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

if not TELEGRAM_TOKEN:
    raise ValueError("Missing TELEGRAM_TOKEN environment variable")


def calculate_adx_tradingview_exact(df, period=14):
    """
    Точная копия Pine Script кода TradingView:
    ADX = sma(DX, len) - простая скользящая средняя!
    """
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    
    # Расчет True Range
    tr = []
    dm_plus = []
    dm_minus = []
    
    for i in range(1, len(high)):
        # True Range (точно как в Pine Script)
        tr1 = high[i] - low[i]
        tr2 = abs(high[i] - close[i-1])
        tr3 = abs(low[i] - close[i-1])
        tr.append(max(tr1, tr2, tr3))
        
        # Directional Movement (точно как в Pine Script)
        up_move = high[i] - high[i-1]
        down_move = low[i-1] - low[i]
        
        # DirectionalMovementPlus = high-nz(high[1]) > nz(low[1])-low ? max(high-nz(high[1]), 0): 0
        dm_p = max(up_move, 0) if up_move > down_move else 0
        # DirectionalMovementMinus = nz(low[1])-low > high-nz(high[1]) ? max(nz(low[1])-low, 0): 0  
        dm_m = max(down_move, 0) if down_move > up_move else 0
        
        dm_plus.append(dm_p)
        dm_minus.append(dm_m)
    
    # Wilder's Smoothing (точно как в Pine Script)
    # SmoothedTrueRange := nz(SmoothedTrueRange[1]) - (nz(SmoothedTrueRange[1])/len) + TrueRange
    def wilders_smoothing_exact(data, period):
        if not data:
            return []
        
        smoothed = []
        # Первое значение - простая средняя
        first_smooth = sum(data[:period]) / period if len(data) >= period else sum(data) / len(data)
        smoothed.append(first_smooth)
        
        # Остальные по формуле: new = previous - (previous/period) + current
        start_idx = period if len(data) >= period else len(data)
        for i in range(start_idx, len(data)):
            prev_smooth = smoothed[-1]
            new_smooth = prev_smooth - (prev_smooth / period) + data[i]
            smoothed.append(new_smooth)
        
        return smoothed
    
    # Сглаженные значения
    str_values = wilders_smoothing_exact(tr, period)
    sdm_plus = wilders_smoothing_exact(dm_plus, period)
    sdm_minus = wilders_smoothing_exact(dm_minus, period)
    
    if not str_values or not sdm_plus or not sdm_minus:
        return {'adx': 0, 'di_plus': 0, 'di_minus': 0}
    
    # DI+ и DI- (точно как в Pine Script)
    # DIPlus = SmoothedDirectionalMovementPlus / SmoothedTrueRange * 100
    # DIMinus = SmoothedDirectionalMovementMinus / SmoothedTrueRange * 100
    di_plus = [(sdm_plus[i] / str_values[i]) * 100 if str_values[i] > 0 else 0 
               for i in range(min(len(str_values), len(sdm_plus)))]
    di_minus = [(sdm_minus[i] / str_values[i]) * 100 if str_values[i] > 0 else 0
                for i in range(min(len(str_values), len(sdm_minus)))]
    
    # DX (точно как в Pine Script)  
    # DX = abs(DIPlus-DIMinus) / (DIPlus+DIMinus)*100
    dx = []
    for i in range(min(len(di_plus), len(di_minus))):
        if (di_plus[i] + di_minus[i]) > 0:
            dx_val = abs(di_plus[i] - di_minus[i]) / (di_plus[i] + di_minus[i]) * 100
            dx.append(dx_val)
        else:
            dx.append(0)
    
    # ADX - ПРОСТАЯ СКОЛЬЗЯЩАЯ СРЕДНЯЯ (как в Pine Script!)
    # ADX = sma(DX, len)
    if len(dx) >= period:
        adx = sum(dx[-period:]) / period  # Простая SMA за последние 14 периодов
    else:
        adx = sum(dx) / len(dx) if dx else 0
    
    return {
        'adx': adx,
        'di_plus': di_plus[-1] if di_plus else 0,
        'di_minus': di_minus[-1] if di_minus else 0
    }


async def get_current_sber_price():
    """Получение актуальной цены SBER"""
    try:
        # Правильный endpoint для получения актуальной цены в режиме TQBR
        url = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/SBER.json"
        params = {
            'iss.meta': 'off',
            'iss.only': 'marketdata',
            'marketdata.columns': 'LAST,BID,OFFER,TIME'  # Последняя цена, bid, offer, время
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        
        # Извлекаем данные из правильной структуры
        if 'marketdata' in data and 'data' in data['marketdata'] and data['marketdata']['data']:
            columns = data['marketdata']['columns']  # ['LAST', 'BID', 'OFFER', 'TIME']
            market_data = data['marketdata']['data'][0]  # Первая строка данных
            
            # Находим индекс колонки LAST
            last_price_index = columns.index('LAST') if 'LAST' in columns else None
            time_index = columns.index('TIME') if 'TIME' in columns else None
            
            if last_price_index is not None and market_data[last_price_index]:
                current_price = float(market_data[last_price_index])
                time_str = market_data[time_index] if time_index is not None else "неизвестно"
                logger.info(f"💰 Получена актуальная цена SBER: {current_price:.2f} ₽ (время: {time_str})")
                return current_price
        
        logger.warning("Не удалось получить актуальную цену из TQBR marketdata endpoint")
        return None
        
    except Exception as e:
        logger.error(f"Error fetching current SBER price: {e}")
        return None


async def get_sber_data():
    """Получение данных SBER через MOEX API и расчет технических индикаторов"""
    try:
        # Получаем актуальную цену
        current_price = await get_current_sber_price()
        
        # Получаем исторические данные за последние 5 дней для индикаторов
        to_date = datetime.now()
        from_date = to_date - timedelta(days=5)
        
        # MOEX API для получения часовых свечей SBER (как TradingView)
        url = "https://iss.moex.com/iss/engines/stock/markets/shares/securities/SBER/candles.json"
        params = {
            'from': from_date.strftime('%Y-%m-%d'),
            'till': to_date.strftime('%Y-%m-%d'),
            'interval': '60'  # 60 минут = часовые свечи (как TradingView)
        }
        
        logger.info(f"Запрашиваем исторические данные MOEX API с {from_date.strftime('%Y-%m-%d')} по {to_date.strftime('%Y-%m-%d')} (часовой таймфрейм, 5 дней)")
        
        # Делаем запрос к MOEX API с httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
        
        # Извлекаем данные свечей
        if 'candles' not in data or not data['candles']['data']:
            logger.error("No candle data received from MOEX API")
            return None
        
        columns = data['candles']['columns']
        candles_raw = data['candles']['data']
        
        # Преобразуем в удобный формат для pandas
        candles_data = []
        for candle in candles_raw:
            # columns: ["open", "close", "high", "low", "value", "volume", "begin", "end"]
            candles_data.append({
                'open': float(candle[0]),
                'close': float(candle[1]),
                'high': float(candle[2]),
                'low': float(candle[3]),
                'volume': int(candle[5]),
                'time': candle[6]  # время начала свечи
            })
        
        # Ограничиваем до последних 50 свечей
        if len(candles_data) > 50:
            candles_data = candles_data[-50:]
        
        logger.info(f"Получено {len(candles_data)} часовых свечей с MOEX за 5 дней")
        
        # ДИАГНОСТИКА: показываем последние несколько свечей
        if candles_data:
            logger.info("🔍 ПОСЛЕДНИЕ 3 СВЕЧИ (для диагностики индикаторов):")
            for i, candle in enumerate(candles_data[-3:]):
                logger.info(f"   {i+1}. {candle['time']} | O:{candle['open']:.2f} H:{candle['high']:.2f} L:{candle['low']:.2f} C:{candle['close']:.2f}")
            
            first_time = candles_data[0]['time']
            last_time = candles_data[-1]['time']
            logger.info(f"Диапазон времени (МСК): {first_time} → {last_time}")
            logger.info(f"Цена последней свечи: {candles_data[-1]['close']:.2f} ₽")
            if current_price:
                logger.info(f"Актуальная цена (отдельный запрос): {current_price:.2f} ₽")
        
        if len(candles_data) < 30:
            logger.error(f"Insufficient data: {len(candles_data)} candles (need at least 30)")
            return None
        
        # Преобразуем в DataFrame
        df = pd.DataFrame(candles_data)
        
        # Расчет EMA20
        df['ema20'] = ta.ema(df['close'], length=20)
        
        # ДВА ВАРИАНТА расчета ADX
        # 1. pandas-ta (стандартный)
        adx_data_standard = ta.adx(df['high'], df['low'], df['close'], length=14, mamode='rma')
        
        # 2. Pine Script (ADX = sma(DX, len))
        adx_pinescript = calculate_adx_tradingview_exact(df, period=14)
        
        # Берем последние значения
        last_row = df.iloc[-1]
        
        # Сравниваем результаты в логах
        logger.info("📊 СРАВНЕНИЕ ДВУХ ФОРМУЛ ADX:")
        logger.info(f"   🔧 pandas-ta: ADX={adx_data_standard['ADX_14'].iloc[-1]:.2f}, DI+={adx_data_standard['DMP_14'].iloc[-1]:.2f}, DI-={adx_data_standard['DMN_14'].iloc[-1]:.2f}")
        logger.info(f"   📈 Pine Script: ADX={adx_pinescript['adx']:.2f}, DI+={adx_pinescript['di_plus']:.2f}, DI-={adx_pinescript['di_minus']:.2f}")
        
        return {
            'current_price': current_price if current_price else last_row['close'],  # Приоритет актуальной цене
            'ema20': last_row['ema20'],
            # pandas-ta
            'adx_standard': adx_data_standard['ADX_14'].iloc[-1],
            'di_plus_standard': adx_data_standard['DMP_14'].iloc[-1],
            'di_minus_standard': adx_data_standard['DMN_14'].iloc[-1],
            # Pine Script
            'adx_pinescript': adx_pinescript['adx'],
            'di_plus_pinescript': adx_pinescript['di_plus'],
            'di_minus_pinescript': adx_pinescript['di_minus']
        }
        
    except httpx.HTTPError as e:
        logger.error(f"MOEX API request error: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching SBER data: {e}")
        return None


def format_sber_message(data):
    """Форматирование сообщения с данными SBER - показываем ДВА варианта ADX"""
    
    # Определяем силу тренда для двух вариантов
    adx_standard_strength = "Сильный тренд" if data['adx_standard'] > 25 else "Слабый тренд"
    adx_pine_strength = "Сильный тренд" if data['adx_pinescript'] > 25 else "Слабый тренд"
    
    message = f"""🏦 <b>SBER - Сбербанк</b>

💰 <b>Цена:</b> {data['current_price']:.2f} ₽
📊 <b>EMA20:</b> {data['ema20']:.2f} ₽

🔧 <b>ADX — pandas-ta (стандарт):</b>
• <b>ADX:</b> {data['adx_standard']:.2f} ({adx_standard_strength})
• <b>DI+:</b> {data['di_plus_standard']:.2f} | <b>DI-:</b> {data['di_minus_standard']:.2f}

📈 <b>ADX — Pine Script (sma):</b>
• <b>ADX:</b> {data['adx_pinescript']:.2f} ({adx_pine_strength})
• <b>DI+:</b> {data['di_plus_pinescript']:.2f} | <b>DI-:</b> {data['di_minus_pinescript']:.2f}"""
    
    return message


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    welcome_message = """👋 Привет! Я бот для мониторинга акций SBER.

📊 <b>Доступные команды:</b>
/sber - Получить актуальные данные по Сбербанку

<i>Данные получаются напрямую с Московской биржи через MOEX API</i>"""
    
    await update.message.reply_text(welcome_message, parse_mode='HTML')


async def sber_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /sber"""
    loading_message = await update.message.reply_text('⏳ Получаю данные с MOEX...')
    
    try:
        sber_data = await get_sber_data()
        
        if not sber_data:
            await loading_message.edit_text('❌ Не удалось получить данные с MOEX API. Попробуйте позже.')
            return
        
        # Проверяем на NaN значения (для двух вариантов)
        if (pd.isna(sber_data['ema20']) or 
            pd.isna(sber_data['adx_standard']) or pd.isna(sber_data['adx_pinescript']) or
            pd.isna(sber_data['di_plus_standard']) or pd.isna(sber_data['di_plus_pinescript']) or
            pd.isna(sber_data['di_minus_standard']) or pd.isna(sber_data['di_minus_pinescript'])):
            await loading_message.edit_text('❌ Недостаточно данных для расчета индикаторов. Попробуйте позже.')
            return
        
        message = format_sber_message(sber_data)
        await loading_message.edit_text(message, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error in sber_command: {e}")
        await loading_message.edit_text('❌ Произошла ошибка при получении данных.')


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}")


def main():
    """Основная функция запуска бота"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("sber", sber_command))
    
    application.add_error_handler(error_handler)
    
    logger.info("🤖 SBER Telegram Bot started with MOEX API...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
