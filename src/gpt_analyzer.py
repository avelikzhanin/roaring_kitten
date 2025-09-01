def _create_detailed_prompt(self, signal_data: Dict, is_manual_check: bool) -> str:
        """Создание детального промпта с расширенными рыночными данными"""
        
        # Базовые технические данные
        conditions_met = signal_data.get('conditions_met', True)
        current_price = signal_data['price']
        
        # Анализ силы индикаторов
        adx_value = signal_data['adx']
        adx_analysis = self._analyze_adx(adx_value)
        
        di_difference = signal_data['plus_di'] - signal_data['minus_di']
        di_analysis = self._analyze_di_difference(di_difference)
        
        price_above_ema_percent = ((signal_data['price'] / signal_data['ema20'] - 1) * 100)
        
        # Расширенные данные
        support_resistance = signal_data.get('support_resistance', {})
        volatility = signal_data.get('volatility', {})
        volume_profile = signal_data.get('volume_profile', {})
        chart_patterns = signal_data.get('chart_patterns', {})
        fibonacci = signal_data.get('fibonacci', {})
        tp_sl_rec = signal_data.get('tp_sl_recommendations', {})
        
        # Анализ времени торгов
        current_hour = datetime.now().hour
        session_analysis = self._analyze_trading_session(current_hour)
        
        # Статус стратегии
        strategy_status = "✅ ВСЕ УСЛОВИЯ ВЫПОЛНЕНЫ" if conditions_met else "❌ УСЛОВИЯ НЕ ВЫПОЛНЕНЫ"
        
        prompt = f"""ПОЛНЫЙ АНАЛИЗ ТОРГОВОЙ СИТУАЦИИ SBER:

📊 БАЗОВЫЕ ТЕХНИЧЕСКИЕ ДАННЫЕ:
• Цена: {current_price:.2f} ₽
• EMA20: {signal_data['ema20']:.2f} ₽ (цена {'выше' if price_above_ema_percent > 0 else 'ниже'} на {abs(price_above_ema_percent):.1f}%)
• ADX: {adx_value:.1f} ({adx_analysis['strength']}, {adx_analysis['interpretation']})
• +DI: {signal_data['plus_di']:.1f} vs -DI: {signal_data['minus_di']:.1f}
• Разница DI: {di_difference:.1f} ({di_analysis})

🎯 УРОВНИ ПОДДЕРЖКИ/СОПРОТИВЛЕНИЯ:
• Ближайшее сопротивление: {support_resistance.get('nearest_resistance', 'не определено')}
• Ближайшая поддержка: {support_resistance.get('nearest_support', 'не определено')}
• Психологические уровни: {support_resistance.get('psychological_levels', [])}

📈 ВОЛАТИЛЬНОСТЬ И РИСКИ:
• ATR(14): {volatility.get('atr_14', 0):.2f} ₽ ({volatility.get('atr_percentage', 0):.2f}% от цены)
• 7-дневная волатильность: {volatility.get('volatility_7d', 0):.2f}%
• Средний диапазон свечи: {volatility.get('avg_candle_range', 0):.2f} ₽

📊 ОБЪЕМЫ И ЛИКВИДНОСТЬ:
• Текущий объем vs средний: {volume_profile.get('volume_ratio_20', 1):.1f}x
• Объемный уклон: {volume_profile.get('# src/gpt_analyzer.py
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
    """Расширенный совет от GPT по сигналу с TP/SL"""
    recommendation: str  # "BUY", "WEAK_BUY", "WAIT", "AVOID"
    confidence: int      # 0-100%
    reasoning: str       # Объяснение решения
    risk_warning: str    # Предупреждение о рисках
    
    # Новые поля для торгового плана
    stop_loss: Optional[float] = None      # Цена стопа
    take_profit: Optional[float] = None    # Цена тейк-профита
    risk_amount: Optional[float] = None    # Риск в рублях
    risk_percent: Optional[float] = None   # Риск в процентах
    reward_amount: Optional[float] = None  # Потенциальная прибыль в рублях
    reward_percent: Optional[float] = None # Потенциальная прибыль в процентах
    risk_reward_ratio: Optional[float] = None  # Соотношение риск/прибыль
    key_levels: Optional[List[float]] = None   # Ключевые уровни для мониторинга
    trade_plan: Optional[str] = None       # Торговый план

class GPTMarketAnalyzer:
    """Анализатор для обогащения торговых сигналов с помощью GPT"""
    
    def __init__(self, openai_api_key: str):
        self.api_key = openai_api_key
        self.base_url = "https://api.openai.com/v1/chat/completions"
        
        self.system_prompt = """Ты опытный трейдер российского рынка акций с 15-летним опытом работы с Сбербанком и специализацией на внутридневной торговле.

ТВОЯ ЗАДАЧА: Дать детальный торговый план по SBER с конкретными уровнями входа, стопа и тейк-профита.

ПРИНЦИПЫ АНАЛИЗА:
- Используй ВСЕ доступные данные: технические индикаторы, уровни поддержки/сопротивления, волатильность, объемы, паттерны
- Будь максимально КОНКРЕТЕН: точные цены для SL/TP, а не общие слова
- ЦЕЛЬ: дать план для заработка 2-7% за сделку с разумным риском 1-3%
- Учитывай время торгов, рыночную ликвидность и текущий контекст

РЕКОМЕНДАЦИИ:
- BUY: уверенная покупка (85-100%) - все факторы за покупку + четкий план
- WEAK_BUY: осторожная покупка (65-84%) - больше плюсов чем минусов
- WAIT: ждать лучших условий (45-64%) - неопределенность или близко к уровням
- AVOID: не покупать (0-44%) - против тренда или плохие условия

ОБЯЗАТЕЛЬНО УКАЗЫВАЙ:
- Конкретные цены Stop Loss и Take Profit
- Обоснование выбора уровней
- Риск в рублях и процентах
- Ожидаемую прибыль
- Ключевые уровни для мониторинга

КОНТЕКСТ СБЕРА:
- Торговый диапазон обычно 280-330 рублей
- Средняя внутридневная волатильность 2-5%
- Лучшее время: 11:00-16:00 МСК (высокая ликвидность)
- Реагирует на новости ЦБ РФ, санкции, цены на нефть
- Психологические уровни: круглые числа (300, 310, 320 и т.д.)

Отвечай ТОЛЬКО в JSON формате."""

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
        """Создание детального промпта с расширенными рыночными данными"""
        
        # Базовые технические данные
        conditions_met = signal_data.get('conditions_met', True)
        current_price = signal_data['price']
        
        # Анализ силы индикаторов
        adx_value = signal_data['adx']
        adx_analysis = self._analyze_adx(adx_value)
        
        di_difference = signal_data['plus_di'] - signal_data['minus_di']
        di_analysis = self._analyze_di_difference(di_difference)
        
        price_above_ema_percent = ((signal_data['price'] / signal_data['ema20'] - 1) * 100)
        
        # Расширенные данные
        support_resistance = signal_data.get('support_resistance', {})
        volatility = signal_data.get('volatility', {})
        volume_profile = signal_data.get('volume_profile', {})
        chart_patterns = signal_data.get('chart_patterns', {})
        fibonacci = signal_data.get('fibonacci', {})
        tp_sl_rec = signal_data.get('tp_sl_recommendations', {})
        
        # Анализ времени торгов
        current_hour = datetime.now().hour
        session_analysis = self._analyze_trading_session(current_hour)
        
        # Статус стратегии
        strategy_status = "✅ ВСЕ УСЛОВИЯ ВЫПОЛНЕНЫ" if conditions_met else "❌ УСЛОВИЯ НЕ ВЫПОЛНЕНЫ"
        
        prompt = f"""ПОЛНЫЙ АНАЛИЗ ТОРГОВОЙ СИТУАЦИИ SBER:

📊 БАЗОВЫЕ ТЕХНИЧЕСКИЕ ДАННЫЕ:
• Цена: {current_price:.2f} ₽
• EMA20: {signal_data['ema20']:.2f} ₽ (цена {'выше' if price_above_ema_percent > 0 else 'ниже'} на {abs(price_above_ema_percent):.1f}%)
• ADX: {adx_value:.1f} ({adx_analysis['strength']}, {adx_analysis['interpretation']})
• +DI: {signal_data['plus_di']:.1f} vs -DI: {signal_data['minus_di']:.1f}
• Разница DI: {di_difference:.1f} ({di_analysis})

🎯 УРОВНИ ПОДДЕРЖКИ/СОПРОТИВЛЕНИЯ:
• Ближайшее сопротивление: {support_resistance.get('nearest_resistance', 'не определено')}
• Ближайшая поддержка: {support_resistance.get('nearest_support', 'не определено')}
• Психологические уровни: {support_resistance.get('psychological_levels', [])}

📈 ВОЛАТИЛЬНОСТЬ И РИСКИ:
• ATR(14): {volatility.get('atr_14', 0):.2f} ₽ ({volatility.get('atr_percentage', 0):.2f}% от цены)
• 7-дневная волатильность: {volatility.get('volatility_7d', 0):.2f}%
• Средний диапазон свечи: {volatility.get('avg_candle_range', 0):.2f} ₽

📊 ОБЪЕМЫ И ЛИКВИДНОСТЬ:
• Текущий объем vs средний: {volume_profile.get('volume_ratio_20', 1):.1f}x
• Объемный уклон: {volume_profile.get('volume_bias', 'нейтральный')}

📉 ГРАФИЧЕСКИЕ ПАТТЕРНЫ:
• Направление тренда: {chart_patterns.get('trend_direction', 'не определен')}
• Пробитие уровней: {chart_patterns.get('breakout_type', 'нет')}
• Консолидация: {'да' if chart_patterns.get('is_consolidation') else 'нет'}

🔢 ФИБОНАЧЧИ УРОВНИ:
• Ближайший уровень выше: {fibonacci.get('nearest_fib_above', 'не определен')}
• Ближайший уровень ниже: {fibonacci.get('nearest_fib_below', 'не определен')}

💡 ПРЕДВАРИТЕЛЬНЫЕ TP/SL РЕКОМЕНДАЦИИ:
• Рекомендуемый Stop Loss: {tp_sl_rec.get('stop_loss', {}).get('price', 'не определен')} (метод: {tp_sl_rec.get('stop_loss', {}).get('method', 'нет')})
• Рекомендуемый Take Profit: {tp_sl_rec.get('take_profit', {}).get('price', 'не определен')} (метод: {tp_sl_rec.get('take_profit', {}).get('method', 'нет')})
• Соотношение R/R: {tp_sl_rec.get('risk_reward_ratio', 'не определено')}

⏰ КОНТЕКСТ ТОРГОВОЙ СЕССИИ:
• Время: {datetime.now().strftime('%H:%M МСК')} ({session_analysis})
• Статус стратегии: {strategy_status}

🎯 ТОРГОВОЕ ЗАДАНИЕ:
Дай детальный торговый план: покупать ли SBER, какие конкретные уровни Stop Loss и Take Profit, какой риск в рублях и процентах, на какие ключевые уровни обратить внимание.

Ответ в JSON:
{{
  "recommendation": "BUY/WEAK_BUY/WAIT/AVOID",
  "confidence": число_0_100,
  "reasoning": "детальное обоснование решения с анализом всех факторов",
  "risk_warning": "главные риски или пустая строка",
  
  "stop_loss": цена_числом_или_null,
  "take_profit": цена_числом_или_null,
  "risk_amount": риск_в_рублях_или_null,
  "risk_percent": риск_в_процентах_или_null,
  "reward_amount": прибыль_в_рублях_или_null,  
  "reward_percent": прибыль_в_процентах_или_null,
  "risk_reward_ratio": соотношение_или_null,
  
  "key_levels": [массив_ключевых_уровней_для_мониторинга],
  "trade_plan": "пошаговый план действий и условия для корректировки позиции"
}}"""
        
        return prompt
    
    def _analyze_adx(self, adx_value: float) -> Dict[str, str]:
        """Анализ силы ADX"""
        if adx_value > 45:
            return {"strength": "экстремально сильный", "interpretation": "возможен разворот тренда"}
        elif adx_value > 30:
            return {"strength": "сильный", "interpretation": "устойчивый тренд"}
        elif adx_value > 25:
            return {"strength": "умеренный", "interpretation": "формирующийся тренд"}
        else:
            return {"strength": "слабый", "interpretation": "боковое движение"}
    
    def _analyze_di_difference(self, di_diff: float) -> str:
        """Анализ разницы DI"""
        if di_diff > 15:
            return "очень сильное преимущество покупателей"
        elif di_diff > 10:
            return "сильное преимущество покупателей"
        elif di_diff > 5:
            return "умеренное преимущество покупателей"
        elif di_diff > 1:
            return "слабое преимущество покупателей"
        elif di_diff > -1:
            return "равновесие сил"
        elif di_diff > -5:
            return "слабое преимущество продавцов"
        else:
            return "сильное преимущество продавцов"
    
    def _analyze_trading_session(self, hour: int) -> str:
        """Анализ качества торговой сессии"""
        if 11 <= hour <= 16:
            return "премиум время - высокая ликвидность"
        elif 10 <= hour <= 18:
            return "хорошее время - нормальная ликвидность"
        elif 9 <= hour <= 19:
            return "приемлемое время - средняя ликвидность"
        else:
            return "плохое время - низкая ликвидность"
    
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
        """Парсинг расширенного ответа GPT с торговым планом"""
        try:
            data = json.loads(response.strip())
            
            # Валидация обязательных полей
            recommendation = data.get('recommendation', 'AVOID').upper()
            if recommendation not in ['BUY', 'WEAK_BUY', 'WAIT', 'AVOID']:
                recommendation = 'AVOID'
            
            confidence = data.get('confidence', 50)
            if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 100:
                confidence = 50
            
            reasoning = str(data.get('reasoning', 'Анализ недоступен'))[:500]  # Увеличиваем лимит
            risk_warning = str(data.get('risk_warning', ''))[:200]
            
            # Парсинг торгового плана
            stop_loss = data.get('stop_loss')
            take_profit = data.get('take_profit')
            risk_amount = data.get('risk_amount')
            risk_percent = data.get('risk_percent')
            reward_amount = data.get('reward_amount') 
            reward_percent = data.get('reward_percent')
            risk_reward_ratio = data.get('risk_reward_ratio')
            key_levels = data.get('key_levels', [])
            trade_plan = str(data.get('trade_plan', ''))[:300] if data.get('trade_plan') else None
            
            # Валидация числовых значений
            def validate_number(value, default=None):
                if value is not None and isinstance(value, (int, float)) and value > 0:
                    return float(value)
                return default
            
            return GPTAdvice(
                recommendation=recommendation,
                confidence=int(confidence),
                reasoning=reasoning,
                risk_warning=risk_warning,
                stop_loss=validate_number(stop_loss),
                take_profit=validate_number(take_profit),
                risk_amount=validate_number(risk_amount),
                risk_percent=validate_number(risk_percent),
                reward_amount=validate_number(reward_amount),
                reward_percent=validate_number(reward_percent),
                risk_reward_ratio=validate_number(risk_reward_ratio),
                key_levels=[float(level) for level in key_levels if isinstance(level, (int, float))],
                trade_plan=trade_plan
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Некорректный JSON от GPT: {e}")
            logger.error(f"Ответ: {response[:500]}...")
            return None
        except Exception as e:
            logger.error(f"💥 Ошибка парсинга расширенного GPT ответа: {e}")
            return None
    
    def format_advice_for_telegram(self, advice: GPTAdvice) -> str:
        """Форматирование расширенного совета GPT для Telegram"""
        
        # Эмодзи для рекомендаций
        rec_emoji = {
            'BUY': '🚀',
            'WEAK_BUY': '⚡',
            'WAIT': '⏳',
            'AVOID': '⛔'
        }
        
        # Цвет уверенности
        if advice.confidence >= 85:
            confidence_emoji = '🟢'
        elif advice.confidence >= 65:
            confidence_emoji = '🟡'
        else:
            confidence_emoji = '🔴'
        
        result = f"""
🤖 <b>СОВЕТ GPT:</b>
{rec_emoji.get(advice.recommendation, '❓')} <b>{advice.recommendation}</b> | {confidence_emoji} {advice.confidence}%

💡 <b>Анализ:</b> {advice.reasoning}"""
        
        # Добавляем торговый план если есть конкретные уровни
        if advice.stop_loss or advice.take_profit:
            result += "\n\n📋 <b>ТОРГОВЫЙ ПЛАН:</b>"
            
            if advice.stop_loss:
                result += f"\n🛑 <b>Stop Loss:</b> {advice.stop_loss:.2f} ₽"
                if advice.risk_amount:
                    result += f" (риск: {advice.risk_amount:.0f}₽)"
                if advice.risk_percent:
                    result += f" (-{advice.risk_percent:.1f}%)"
            
            if advice.take_profit:
                result += f"\n🎯 <b>Take Profit:</b> {advice.take_profit:.2f} ₽"
                if advice.reward_amount:
                    result += f" (прибыль: +{advice.reward_amount:.0f}₽)"
                if advice.reward_percent:
                    result += f" (+{advice.reward_percent:.1f}%)"
            
            if advice.risk_reward_ratio:
                result += f"\n⚖️ <b>R/R:</b> 1:{advice.risk_reward_ratio:.1f}"
        
        # Ключевые уровни для мониторинга
        if advice.key_levels:
            levels_str = ", ".join([f"{level:.2f}" for level in advice.key_levels[:3]])  # Максимум 3 уровня
            result += f"\n👁 <b>Следить за:</b> {levels_str} ₽"
        
        # Предупреждения о рисках
        if advice.risk_warning:
            result += f"\n⚠️ <b>Риск:</b> {advice.risk_warning}"
        
        # Торговый план
        if advice.trade_plan:
            result += f"\n📝 <b>План:</b> {advice.trade_plan}"
        
        return result
