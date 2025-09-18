import os
import asyncio
from datetime import datetime, timedelta, timezone
import logging

import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from tinkoff.invest import Client, CandleInterval
from tinkoff.invest.utils import quotation_to_decimal, now

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
TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
SBER_FIGI = 'BBG004730N88'  # FIGI для Сбербанка

if not TELEGRAM_TOKEN or not TINKOFF_TOKEN:
    raise ValueError("Missing required environment variables")


async def get_sber_data():
    """Получение данных SBER и расчет технических индикаторов"""
    try:
        with Client(TINKOFF_TOKEN) as client:
            # Получаем данные за последние 30 дней (используем timezone-aware datetime)
            to_date = now()  # Текущее время с timezone
            from_date = to_date - timedelta(days=30)
            
            # Получаем свечи (меняем на часовой таймфрейм)
            candles_data = []
            for candle in client.get_all_candles(
                figi=SBER_FIGI,
                from_=from_date,
                interval=CandleInterval.CANDLE_INTERVAL_HOUR  # Часовые вместо дневных
            ):
                candles_data.append({
                    'high': float(quotation_to_decimal(candle.high)),
                    'low': float(quotation_to_decimal(candle.low)),
                    'close': float(quotation_to_decimal(candle.close)),
                    'volume': candle.volume,
                    'time': candle.time
                })
            
            if not candles_data:
                logger.error("No candles data received")
                return None
            
            # Преобразуем в DataFrame
            df = pd.DataFrame(candles_data)
            df = df.sort_values('time').reset_index(drop=True)
            
            if df.empty or len(df) < 20:
                logger.error("Insufficient data for calculations")
                return None
            
            # Расчет технических индикаторов с настройками
            # EMA20
            df['ema20'] = ta.ema(df['close'], length=20)
            
            # ADX с настраиваемым периодом - попробуйте разные значения
            adx_period = 10  # Попробуйте 7, 10, 14, 21, 28
            adx_data = ta.adx(df['high'], df['low'], df['close'], length=adx_period)
            df['adx'] = adx_data[f'ADX_{adx_period}']
            df['di_plus'] = adx_data[f'DMP_{adx_period}'] 
            df['di_minus'] = adx_data[f'DMN_{adx_period}']
            
            # Берем последние значения
            last_row = df.iloc[-1]
            
            return {
                'current_price': last_row['close'],
                'ema20': last_row['ema20'],
                'adx': last_row['adx'],
                'di_plus': last_row['di_plus'],
                'di_minus': last_row['di_minus']
            }
            
    except Exception as e:
        logger.error(f"Error fetching SBER data: {e}")
        return None


def format_sber_message(data):
    """Форматирование сообщения с данными SBER"""
    adx_strength = "Сильный тренд" if data['adx'] > 25 else "Слабый тренд"
    
    message = f"""🏦 <b>SBER - Сбербанк</b>

💰 <b>Цена:</b> {data['current_price']:.2f} ₽
📊 <b>EMA20:</b> {data['ema20']:.2f} ₽

📈 <b>Технические индикаторы:</b>
• <b>ADX:</b> {data['adx']:.2f} ({adx_strength})
• <b>DI+:</b> {data['di_plus']:.2f}
• <b>DI-:</b> {data['di_minus']:.2f}"""
    
    return message


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    welcome_message = """👋 Привет! Я бот для мониторинга акций SBER.

📊 <b>Доступные команды:</b>
/sber - Получить актуальные данные по Сбербанку

<i>Бот предоставляет информацию о цене, EMA20, ADX, DI+ и DI-</i>"""
    
    await update.message.reply_text(welcome_message, parse_mode='HTML')


async def sber_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /sber"""
    # Отправляем сообщение о загрузке
    loading_message = await update.message.reply_text('⏳ Получаю данные по SBER...')
    
    try:
        # Получаем данные
        sber_data = await get_sber_data()
        
        if not sber_data:
            await loading_message.edit_text('❌ Не удалось получить данные по SBER. Попробуйте позже.')
            return
        
        # Проверяем на NaN значения
        if (pd.isna(sber_data['ema20']) or 
            pd.isna(sber_data['adx']) or 
            pd.isna(sber_data['di_plus']) or 
            pd.isna(sber_data['di_minus'])):
            await loading_message.edit_text('❌ Недостаточно данных для расчета индикаторов. Попробуйте позже.')
            return
        
        # Форматируем и отправляем результат
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
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("sber", sber_command))
    
    # Добавляем обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Запускаем бота
    logger.info("🤖 SBER Telegram Bot started...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
