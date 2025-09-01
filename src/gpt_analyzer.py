# src/gpt_analyzer.py
import logging
import aiohttp
import json
import asyncio
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class GPTAdvice:
    """Совет от GPT по сигналу"""
    recommendation: str  # "BUY", "AVOID", "WEAK_BUY"
    confidence: int      # 0-100%
    reasoning: str       # Объяснение
    risk_warning: str    # Предупреждение о рисках
    profit_target: Optional[str] = None  # Цель по прибыли

class GPTMarketAnalyzer:
    """Анализатор для обогащения торговых сигналов с помощью GPT"""
    
    def __init__(self, openai_api_key: str):
        self.api_key = openai_api_key
        self.base_url = "https://api.openai.com/v1/chat/completions"
        
        self.system_prompt = """Ты опытный трейдер российского рынка акций с 10-летним опытом работы с Сбербанком.

ТВОЯ ЗАДАЧА: Дать краткий и честный совет по текущему состоянию SBER для ЗАРАБОТКА.

ПРИНЦИПЫ:
- Отвечай максимально КРАТКО (1-2 предложения на reasoning)
- Будь ЧЕСТНЫМ - если условия не выполнены, объясни что не так
- ЦЕЛЬ: помочь заработать, а не потерять деньги
- Анализируй ВСЕ ситуации: и готовые сигналы, и ожидание условий
- Учитывай время торгов, силу тренда и рыночную ситуацию

РЕКОМЕНДАЦИИ:
- BUY: уверенно покупать (80-100% уверенности) - все условия выполнены + сильные показатели
- WEAK_BUY: можно попробовать осторожно (60-79%) - условия выполнены, но есть нюансы
- WAIT: ждать лучших условий (40-59%) - условия почти выполнены
- AVOID: точно не покупать (<40%) - плохие условия или неподходящее время

КОНТЕКСТ СБЕРА:
- Обычно торгуется 280-330 рублей
- Волатильность 2-5% в день
- Лучшее время торгов: 11:00-16:00 МСК
- Реагирует на новости ЦБ, санкции, нефть

Отвечай ТОЛЬКО в JSON формате без лишнего текста."""

    async def analyze_signal(self, signal_data: Dict, is_manual_check: bool = False) -> Optional[GPTAdvice]:
        """Анализ торгового сигнала с помощью GPT"""
        try:
            prompt = self._create_detailed_prompt(signal_data, is_manual_check)
            response = await self._call_openai_api(prompt)
            
            if response:
                return self._parse_advice_response(response)
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка анализа GPT: {e}")
            return None
    
    def _create_detailed_prompt(self, signal_data: Dict, is_manual_check: bool) -> str:
        """Создание детального промпта для анализа"""
        
        # Проверяем выполнены ли технические условия
        conditions_met = signal_data.get('conditions_met', True)
        
        # Анализ силы индикаторов
        adx_value = signal_data['adx']
        if adx_value > 40:
            adx_strength = "очень сильный"
            adx_risk = "возможен разворот"
        elif adx_value > 25:
            adx_strength = "сильный" 
            adx_risk = "стабильный тренд"
        else:
            adx_strength = "СЛАБЫЙ"
            adx_risk = "тренд не сформирован"
        
        di_difference = signal_data['plus_di'] - signal_data['minus_di']
        if di_difference > 15:
            di_strength = "очень сильное"
        elif di_difference > 10:
            di_strength = "сильное"
        elif di_difference > 5:
            di_strength = "среднее"
        elif di_difference > 1:
            di_strength = "слабое"
        else:
            di_strength = "ОТСУТСТВУЕТ"
        
        price_above_ema_percent = ((signal_data['price'] / signal_data['ema20'] - 1) * 100)
        
        current_hour = datetime.now().hour
        if 11 <= current_hour <= 16:
            session_quality = "премиум время"
        elif 10 <= current_hour <= 18:
            session_quality = "нормальное время"
        else:
            session_quality = "плохое время для входа"
        
        signal_type = "Ручная проверка" if is_manual_check else "Автоматический сигнал"
        
        # Определяем статус условий стратегии
        if conditions_met:
            strategy_status = "✅ ВСЕ УСЛОВИЯ ВЫПОЛНЕНЫ"
            analysis_focus = "Покупать ли SBER прямо сейчас?"
        else:
            strategy_status = "❌ УСЛОВИЯ НЕ ВЫПОЛНЕНЫ"
            analysis_focus = "Стоит ли ждать или есть альтернативы?"
        
        prompt = f"""АНАЛИЗ РЫНОЧНОЙ СИТУАЦИИ SBER:

📊 ТЕХНИЧЕСКИЕ ДАННЫЕ:
• Цена: {signal_data['price']:.2f} ₽
• EMA20: {signal_data['ema20']:.2f} ₽ (цена {'выше' if price_above_ema_percent > 0 else 'ниже'} на {abs(price_above_ema_percent):.1f}%)
• ADX: {adx_value:.1f} ({adx_strength} тренд, {adx_risk})
• +DI: {signal_data['plus_di']:.1f} vs -DI: {signal_data['minus_di']:.1f}
• Преимущество DI: {di_difference:.1f} ({di_strength} доминация)

⏰ КОНТЕКСТ:
• Время: {datetime.now().strftime('%H:%M МСК')} ({session_quality})
• Тип проверки: {signal_type}
• Статус стратегии: {strategy_status}

🎯 ГЛАВНЫЙ ВОПРОС: {analysis_focus}

Дай честную оценку - стоит ли покупать SBER в текущих условиях?

Ответь в JSON:
{{
  "recommendation": "BUY/WEAK_BUY/WAIT/AVOID",
  "confidence": число_0_100,
  "reasoning": "краткое объяснение решения",
  "risk_warning": "главный риск или пустая строка",
  "profit_target": "ожидаемая прибыль % или временной горизонт"
}}"""
        
        return prompt
    
    async def _call_openai_api(self, prompt: str) -> Optional[str]:
        """Вызов OpenAI API с улучшенной обработкой ошибок"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "gpt-4o-mini",  # Быстрая и дешевая модель
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,  # Минимальная креативность для стабильности
            "max_tokens": 400,
            "response_format": {"type": "json_object"}  # Принудительный JSON
        }
        
        timeout = aiohttp.ClientTimeout(total=15)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.base_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data['choices'][0]['message']['content']
                        logger.info("✅ Получен ответ от GPT")
                        return content
                    elif response.status == 429:
                        logger.warning("⚠️ Rate limit OpenAI API")
                        return None
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ OpenAI API ошибка {response.status}: {error_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.warning("⏰ Таймаут запроса к OpenAI (15s)")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"🌐 Сетевая ошибка OpenAI: {e}")
            return None
        except Exception as e:
            logger.error(f"💥 Неожиданная ошибка OpenAI: {e}")
            return None
    
    def _parse_advice_response(self, response: str) -> Optional[GPTAdvice]:
        """Парсинг ответа GPT с валидацией"""
        try:
            data = json.loads(response.strip())
            
            # Валидация обязательных полей
            recommendation = data.get('recommendation', 'AVOID').upper()
            if recommendation not in ['BUY', 'WEAK_BUY', 'WAIT', 'AVOID']:
                recommendation = 'AVOID'
            
            confidence = data.get('confidence', 50)
            if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 100:
                confidence = 50
            
            reasoning = str(data.get('reasoning', 'Анализ недоступен'))[:200]  # Ограничиваем длину
            risk_warning = str(data.get('risk_warning', ''))[:150]
            profit_target = str(data.get('profit_target', ''))[:100] if data.get('profit_target') else None
            
            return GPTAdvice(
                recommendation=recommendation,
                confidence=int(confidence),
                reasoning=reasoning,
                risk_warning=risk_warning,
                profit_target=profit_target
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Некорректный JSON от GPT: {e}")
            logger.error(f"Ответ: {response[:500]}...")
            return None
        except Exception as e:
            logger.error(f"💥 Ошибка парсинга GPT ответа: {e}")
            return None
    
    def format_advice_for_telegram(self, advice: GPTAdvice) -> str:
        """Форматирование совета GPT для Telegram"""
        
        # Эмодзи для рекомендаций
        rec_emoji = {
            'BUY': '🚀',
            'WEAK_BUY': '⚡',
            'WAIT': '⏳',
            'AVOID': '⛔'
        }
        
        # Цвет уверенности
        if advice.confidence >= 80:
            confidence_emoji = '🟢'
        elif advice.confidence >= 60:
            confidence_emoji = '🟡'
        else:
            confidence_emoji = '🔴'
        
        result = f"""
🤖 <b>СОВЕТ GPT:</b>
{rec_emoji.get(advice.recommendation, '❓')} <b>{advice.recommendation}</b> | {confidence_emoji} {advice.confidence}%

💡 <b>Анализ:</b> {advice.reasoning}"""
        
        if advice.profit_target:
            result += f"\n🎯 <b>Цель:</b> {advice.profit_target}"
        
        if advice.risk_warning:
            result += f"\n⚠️ <b>Риск:</b> {advice.risk_warning}"
        
        return result
