import logging
from typing import Optional, List, Dict, Any
import json

from openai import AsyncOpenAI

from config import OPENAI_API_KEY, GPT_MODEL, GPT_MAX_TOKENS, GPT_TEMPERATURE, ADX_THRESHOLD, DI_PLUS_THRESHOLD
from models import StockData

logger = logging.getLogger(__name__)


class GPTAnalyst:
    """Класс для анализа акций с помощью GPT"""
    
    def __init__(self):
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.model = GPT_MODEL
    
    async def analyze_stock(self, stock_data: StockData, candles_data: List[Dict[str, Any]]) -> Optional[str]:
        """
        Анализ акции с помощью GPT
        
        Args:
            stock_data: Данные акции с индикаторами
            candles_data: Список последних свечей
            
        Returns:
            Текст анализа от GPT или None при ошибке
        """
        try:
            # Формируем промпт для GPT
            prompt = self._create_prompt(stock_data, candles_data)
            
            logger.info(f"🤖 Запрашиваем GPT анализ для {stock_data.info.ticker}...")
            
            # Отправляем запрос к GPT
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_completion_tokens=GPT_MAX_TOKENS
            )
            
            # Проверяем что ответ содержит content
            if not response.choices or not response.choices[0].message.content:
                logger.error(f"⚠️ GPT вернул пустой ответ для {stock_data.info.ticker}")
                return None
            
            analysis = response.choices[0].message.content.strip()
            
            logger.info(f"✅ GPT анализ получен для {stock_data.info.ticker}")
            logger.info(f"📝 Длина ответа: {len(analysis)} символов")
            logger.info(f"📄 Текст ответа: {analysis[:200]}...")  # Первые 200 символов
            
            if not analysis:
                logger.warning(f"⚠️ GPT вернул пустой ответ после strip для {stock_data.info.ticker}")
                return None
            
            return analysis
            
        except Exception as e:
            logger.error(f"❌ Ошибка при запросе к GPT для {stock_data.info.ticker}: {e}")
            return None
    
    def _get_system_prompt(self) -> str:
        """Системный промпт для GPT"""
        return """Ты опытный технический аналитик российского фондового рынка с 15-летним стажем.

Твоя задача - анализировать часовые свечи акций и давать краткие, конкретные рекомендации.

ВАЖНО:
- Отвечай КРАТКО и ПО ДЕЛУ (максимум 6-8 строк)
- Используй простой язык, понятный новичкам
- Указывай конкретные уровни цен
- Давай четкую рекомендацию: ПОКУПАТЬ / ЖДАТЬ / НЕ ВХОДИТЬ
- Если рекомендуешь покупку - укажи целевую цену и стоп-лосс

Формат ответа:
📊 [Краткий анализ паттернов и тренда]
💡 [Рекомендация с уровнями]

НЕ используй лишние заголовки, эмодзи флагов, и избыточное форматирование."""
    
    def _create_prompt(self, stock_data: StockData, candles_data: List[Dict[str, Any]]) -> str:
        """Создание промпта для GPT"""
        
        # Берем последние 20 свечей для анализа
        recent_candles = candles_data[-20:] if len(candles_data) > 20 else candles_data
        
        # Форматируем свечи
        candles_text = self._format_candles(recent_candles)
        
        # Формируем промпт
        prompt = f"""Проанализируй часовые свечи акции {stock_data.info.ticker} ({stock_data.info.name}):

СВЕЧИ (последние 20):
{candles_text}

ТЕКУЩИЕ ИНДИКАТОРЫ:
• Цена: {stock_data.price.current_price:.2f} ₽
• EMA20: {stock_data.technical.ema20:.2f} ₽
• ADX: {stock_data.technical.adx:.2f} (порог сильного тренда: {ADX_THRESHOLD})
• DI+: {stock_data.technical.di_plus:.2f}
• DI-: {stock_data.technical.di_minus:.2f}

УСЛОВИЯ ДЛЯ ПОКУПКИ в нашей системе:
• ADX > {ADX_THRESHOLD} AND DI+ > {DI_PLUS_THRESHOLD}

Дай краткий анализ и рекомендацию."""
        
        return prompt
    
    def _format_candles(self, candles: List[Dict[str, Any]]) -> str:
        """Форматирование свечей для промпта"""
        lines = []
        for i, candle in enumerate(candles, 1):
            time = candle['time']
            o = candle['open']
            h = candle['high']
            l = candle['low']
            c = candle['close']
            v = candle['volume']
            
            # Определяем цвет свечи
            color = "🟢" if c > o else "🔴" if c < o else "⚪"
            
            lines.append(f"{i}. {time} {color} O:{o:.2f} H:{h:.2f} L:{l:.2f} C:{c:.2f} V:{v}")
        
        return "\n".join(lines)


# Глобальный экземпляр
gpt_analyst = GPTAnalyst()
