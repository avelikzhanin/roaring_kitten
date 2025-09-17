import TelegramBot from 'node-telegram-bot-api';
import { TinkoffInvestGrpcApi } from '@tinkoff/invest-js';
import { EMA, ADX } from 'technicalindicators';
import * as dotenv from 'dotenv';

dotenv.config();

const TELEGRAM_TOKEN = process.env.TELEGRAM_TOKEN!;
const TINKOFF_TOKEN = process.env.TINKOFF_TOKEN!;
const SBER_FIGI = 'BBG004730N88'; // FIGI для Сбербанка

if (!TELEGRAM_TOKEN || !TINKOFF_TOKEN) {
    console.error('Missing required environment variables');
    process.exit(1);
}

const bot = new TelegramBot(TELEGRAM_TOKEN, { polling: true });
const tinkoffApi = new TinkoffInvestGrpcApi({
    token: TINKOFF_TOKEN,
    appName: 'SberTelegramBot'
});

interface CandleData {
    high: number;
    low: number;
    close: number;
    volume: number;
}

async function getSberData(): Promise<{
    currentPrice: number;
    ema20: number;
    adx: number;
    diPlus: number;
    diMinus: number;
} | null> {
    try {
        // Получаем исторические данные за последние 30 дней для расчета индикаторов
        const to = new Date();
        const from = new Date(to.getTime() - 30 * 24 * 60 * 60 * 1000);
        
        const candlesResponse = await tinkoffApi.marketdata.getCandles({
            figi: SBER_FIGI,
            from: from,
            to: to,
            interval: 1 // CandleInterval.CANDLE_INTERVAL_DAY
        });

        if (!candlesResponse.candles || candlesResponse.candles.length === 0) {
            console.error('No candle data received');
            return null;
        }

        const candles = candlesResponse.candles;
        const candleData: CandleData[] = candles.map((candle: any) => ({
            high: parseFloat(candle.high?.units || '0') + parseFloat(candle.high?.nano || '0') / 1000000000,
            low: parseFloat(candle.low?.units || '0') + parseFloat(candle.low?.nano || '0') / 1000000000,
            close: parseFloat(candle.close?.units || '0') + parseFloat(candle.close?.nano || '0') / 1000000000,
            volume: parseFloat(candle.volume || '0')
        }));

        const closePrices = candleData.map(c => c.close);
        const highPrices = candleData.map(c => c.high);
        const lowPrices = candleData.map(c => c.low);

        // Расчет EMA20
        const emaResult = EMA.calculate({
            period: 20,
            values: closePrices
        });
        const ema20 = emaResult[emaResult.length - 1] || 0;

        // Расчет ADX, DI+, DI-
        const adxResult = ADX.calculate({
            period: 14,
            high: highPrices,
            low: lowPrices,
            close: closePrices
        });
        
        const lastAdxData = adxResult[adxResult.length - 1];
        const adx = lastAdxData?.adx || 0;
        const diPlus = lastAdxData?.pdi || 0;
        const diMinus = lastAdxData?.mdi || 0;

        const currentPrice = closePrices[closePrices.length - 1];

        return {
            currentPrice,
            ema20,
            adx,
            diPlus,
            diMinus
        };

    } catch (error) {
        console.error('Error fetching SBER data:', error);
        return null;
    }
}

function formatSberMessage(data: {
    currentPrice: number;
    ema20: number;
    adx: number;
    diPlus: number;
    diMinus: number;
}): string {
    const trend = data.currentPrice > data.ema20 ? '📈 Выше EMA' : '📉 Ниже EMA';
    const adxStrength = data.adx > 25 ? 'Сильный тренд' : 'Слабый тренд';
    const diDirection = data.diPlus > data.diMinus ? '🟢 Бычий' : '🔴 Медвежий';
    
    return `🏦 <b>SBER - Сбербанк</b>
    
💰 <b>Цена:</b> ${data.currentPrice.toFixed(2)} ₽
📊 <b>EMA20:</b> ${data.ema20.toFixed(2)} ₽
${trend}

📈 <b>Технические индикаторы:</b>
• <b>ADX:</b> ${data.adx.toFixed(2)} (${adxStrength})
• <b>DI+:</b> ${data.diPlus.toFixed(2)}
• <b>DI-:</b> ${data.diMinus.toFixed(2)}
• <b>Направление:</b> ${diDirection}

⏰ <i>Обновлено: ${new Date().toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })}</i>`;
}

// Обработка команды /sber
bot.onText(/\/sber/, async (msg) => {
    const chatId = msg.chat.id;
    
    try {
        await bot.sendMessage(chatId, '⏳ Получаю данные по SBER...');
        
        const sberData = await getSberData();
        
        if (!sberData) {
            await bot.sendMessage(chatId, '❌ Не удалось получить данные по SBER. Попробуйте позже.');
            return;
        }

        const message = formatSberMessage(sberData);
        await bot.sendMessage(chatId, message, { parse_mode: 'HTML' });
        
    } catch (error) {
        console.error('Error handling /sber command:', error);
        await bot.sendMessage(chatId, '❌ Произошла ошибка при получении данных.');
    }
});

// Обработка команды /start
bot.onText(/\/start/, async (msg) => {
    const chatId = msg.chat.id;
    const welcomeMessage = `👋 Привет! Я бот для мониторинга акций SBER.

📊 <b>Доступные команды:</b>
/sber - Получить актуальные данные по Сбербанку

<i>Бот предоставляет информацию о цене, EMA20, ADX, DI+ и DI-</i>`;
    
    await bot.sendMessage(chatId, welcomeMessage, { parse_mode: 'HTML' });
});

// Обработка ошибок
bot.on('polling_error', (error) => {
    console.error('Polling error:', error);
});

console.log('🤖 SBER Telegram Bot started...');
