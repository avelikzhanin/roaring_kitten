# src/gpt_analyzer.py
import logging
import aiohttp
import json
import asyncio
from typing import Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class GPTAdvice:
    """Совет от GPT по сигналу"""
    recommendation: str  # "BUY", "AVOID", "WEAK_BUY"
    confidence: int      # 0-100%
    reasoning: str       # Объяснение
    risk_warning: str    # Предупреждение о рисках

class GPTMarketAnalyzer:
    """Простой анализатор для обогащения сигналов"""
    
    def __init__(self, openai_api_key: str):
        self.api_key = openai_api_key
        self.base_url = "https://api.openai.com/v1/chat/completions"
        
        self.system_prompt = """Ты опытный трейдер российских акций. 

ЗАДАЧА: Дать короткий совет по техническому сигналу покупки SBER.

ПРИНЦИПЫ:
- Отвечай КРАТКО (1-2 предложения)
- Будь честным - если сигнал слабый, так и скажи
- Цель: ЗАРАБОТАТЬ, не потерять деньги
- Учитывай время торгов и силу индикаторов

РЕКОМЕНДАЦИИ:
- BUY: уверенно покупать (75-100% уверенности)
- WEAK_BUY: можно попробовать, но осторожно (50-74%)
- AVOID: лучше не покупать (<50% уверенности)

Отвечай строго в JSON формате без лишнего текста."""

    async def get_signal_advice(self, signal_data: Dict) -> Optional[GPTAdvice]:
        """Получить совет GPT по техническому сигналу"""
        try:
            prompt = self._create_signal_prompt(signal_data)
            response = await self._call_openai_api(prompt)
            
            if response:
                return self._parse_advice_response(response)
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка получения совета GPT: {e}")
            return None
    
    def _create_signal_prompt(self, signal_data: Dict) -> str:
        """Создание промпта для анализа сигнала"""
        
        # Оценка силы каждого индикатора
        adx_strength = "сильный" if signal_data['adx'] > 35 else "средний" if signal_data['adx'] > 28 else "слабый"
        di_difference = signal_data['plus_di'] - signal_data['minus_di']
        di_strength = "мощная" if di_difference > 10 else "хорошая" if di_difference > 5 else "слабая"
        
        price_above_ema_percent = ((signal_data['price'] / signal_data['ema20'] - 1) * 100)
        
        current_hour = datetime.now().hour
        session_quality = "оптимальное" if 11 <= current_hour <= 16 else "приемлемое" if 10 <= current_hour <= 18 else "плохое"
        
        prompt = f"""Анализируй технический сигнал покупки SBER:

ТЕХНИЧЕСКИЕ ДАННЫЕ:
- Цена: {signal_data['price']:.2f} ₽
- Превышение EMA20: +{price_above_ema_percent:.1f}%
- ADX: {signal_data['adx']:.1f} ({adx_strength} тренд)
- +DI: {signal_data['plus_di']:.1f}
- -DI: {signal_data['minus_di']:.1f}
- Разница DI: {di_difference:.1f} ({di_strength} доминация)

КОНТЕКСТ:
- Время: {datetime.now().strftime('%H:%M МСК')} ({session_quality} время)
- Все базовые условия стратегии выполнены ✅

ВОПРОС: Стоит ли покупать? Насколько сильный сигнал?

Ответ в JSON:
{{
  "recommendation": "BUY/WEAK_BUY/AVOID",
  "confidence": число 0-100,
  "reasoning": "краткое объяснение решения",
  "risk_warning": "главный риск или пустая строка"
}}"""
        
        return prompt
    
    async def _call_openai_api(self, prompt: str) -> Optional[str]:
        """Вызов OpenAI API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 300
        }
        
        timeout = aiohttp.ClientTimeout(total=20)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.base_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content']
                    else:
                        error_text = await response.text()
                        logger.error(f"OpenAI API ошибка {response.status}: {error_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error("Таймаут запроса к OpenAI")
            return None
        except Exception as e:
            logger.error(f"Ошибка OpenAI API: {e}")
            return None
    
    def _parse_advice_response(self, response: str) -> Optional[GPTAdvice]:
        """Парсинг ответа GPT"""
        try:
            # Ищем JSON в ответе
            response = response.strip()
            start_idx = response.find('{')
            end_idx = response.rfind('}') + 1
            
            if start_idx == -1:
                logger.error("JSON не найден в ответе GPT")
                return None
            
            json_str = response[start_idx:end_idx]
            data = json.loads(json_str)
            
            return GPTAdvice(
                recommendation=data.get('recommendation', 'AVOID'),
                confidence=max(0, min(100, int(data.get('confidence', 50)))),
                reasoning=str(data.get('reasoning', 'Анализ недоступен')),
                risk_warning=str(data.get('risk_warning', ''))
            )
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Ошибка парсинга ответа GPT: {e}")
            logger.error(f"Ответ: {response}")
            return None
        except Exception as e:
            logger.error(f"Ошибка обработки ответа: {e}")
            return None
