# src/gpt_analyzer.py - РАСШИРЕННАЯ ВЕРСИЯ
import logging
import aiohttp
import json
import asyncio
import numpy as np
import pandas as pd
from typing import Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class GPTAdvice:
    """Совет от GPT по сигналу"""
    recommendation: str  # "BUY", "AVOID", "WEAK_BUY", "WAIT"
    confidence: int      # 0-100%
    reasoning: str       # Объяснение
    risk_warning: str    # Предупреждение о рисках
    take_profit: Optional[str] = None    # Целевая прибыль
    stop_loss: Optional[str] = None      # Стоп-лосс
    expected_levels: Optional[str] = None # Ожидаемые уровни
    timeframe: Optional[str] = None      # Временной горизонт

class GPTMarketAnalyzer:
    """Анализатор для обогащения торговых сигналов с помощью GPT"""
    
    def __init__(self, openai_api_key: str):
        self.api_key = openai_api_key
        self.base_url = "https://api.openai.com/v1/chat/completions"
        
        self.system_prompt = """Ты опытный технический аналитик российского рынка акций с 15-летним опытом работы с Сбербанком.

ТВОЯ ЗАДАЧА: Дать детальный профессиональный анализ SBER с конкретными уровнями и рекомендациями для ЗАРАБОТКА.

ПРИНЦИПЫ АНАЛИЗА:
- Анализируй ПОЛНУЮ картину: технические индикаторы + исторические данные + уровни
- Определяй конкретные уровни поддержки/сопротивления по свечным данным
- Давай четкие TP/SL ТОЛЬКО для покупок (BUY/WEAK_BUY)
- Для WAIT/AVOID указывай какие уровни/показатели ждать
- Учитывай объемы торгов и динамику цены
- Будь ЧЕСТНЫМ - если ситуация неясная, так и скажи

РЕКОМЕНДАЦИИ:
- BUY: уверенно покупать (80-100%) + обязательно TP/SL
- WEAK_BUY: можно попробовать осторожно (60-79%) + осторожные TP/SL  
- WAIT: ждать лучших условий (40-59%) + какие уровни ждем (БЕЗ TP/SL!)
- AVOID: точно не покупать (<40%) + объяснение почему (БЕЗ TP/SL!)

КОНТЕКСТ SBER:
- Обычно торгуется 280-330 рублей (волатильность 2-5% в день)
- Премиум время торгов: 11:00-16:00 МСК
- Реагирует на: новости ЦБ, санкции, нефть, дивиденды
- Ликвидная акция с узким спредом

ОБЯЗАТЕЛЬНО указывай:
- Конкретные цифры уровней (не "около", а точные значения)
- Логику размещения TP/SL только для покупок
- Временные горизонты для ожиданий

Отвечай ТОЛЬКО в JSON формате."""

    async def analyze_signal(self, signal_data: Dict, candles_data: Optional[List] = None, is_manual_check: bool = False) -> Optional[GPTAdvice]:
        """Анализ торгового сигнала с помощью GPT с историческими данными"""
        try:
            prompt = self._create_enhanced_prompt(signal_data, candles_data, is_manual_check)
            response = await self._call_openai_api(prompt)
            
            if response:
                return self._parse_enhanced_advice(response)
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка анализа GPT: {e}")
            return None
    
    def _analyze_price_levels(self, candles_data: List) -> Dict:
        """Анализ уровней поддержки и сопротивления"""
        if not candles_data or len(candles_data) < 20:
            return {}
        
        # Последние 50 свечей для анализа уровней
        recent_candles = candles_data[-50:] if len(candles_data) > 50 else candles_data
        
        highs = [candle['high'] for candle in recent_candles]
        lows = [candle['low'] for candle in recent_candles]
        closes = [candle['close'] for candle in recent_candles]
        volumes = [candle['volume'] for candle in recent_candles]
        
        current_price = closes[-1]
        
        # Простой алгоритм поиска уровней
        # Сопротивления - локальные максимумы
        resistances = []
        for i in range(2, len(highs) - 2):
            if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and 
                highs[i] > highs[i+1] and highs[i] > highs[i+2]):
                if highs[i] > current_price:  # Только выше текущей цены
                    resistances.append(highs[i])
        
        # Поддержки - локальные минимумы  
        supports = []
        for i in range(2, len(lows) - 2):
            if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and 
                lows[i] < lows[i+1] and lows[i] < lows[i+2]):
                if lows[i] < current_price:  # Только ниже текущей цены
                    supports.append(lows[i])
        
        # Сортируем и берем ближайшие
        resistances.sort()
        supports.sort(reverse=True)
        
        # Волатильность за период
        price_changes = [abs(closes[i] - closes[i-1]) / closes[i-1] * 100 for i in range(1, len(closes))]
        avg_volatility = np.mean(price_changes) if price_changes else 2.0
        
        # Средний объем
        avg_volume = np.mean(volumes) if volumes else 0
        recent_volume = np.mean(volumes[-5:]) if len(volumes) >= 5 else avg_volume
        
        return {
            'current_price': current_price,
            'nearest_resistance': resistances[0] if resistances else None,
            'nearest_support': supports[0] if supports else None,
            'all_resistances': resistances[:3],  # Топ-3 ближайших
            'all_supports': supports[:3],
            'avg_volatility': round(avg_volatility, 2),
            'volume_ratio': round(recent_volume / avg_volume, 2) if avg_volume > 0 else 1.0,
            'price_range_5d': {'high': max(highs[-25:]), 'low': min(lows[-25:])} if len(highs) >= 25 else None
        }
    
    def _create_enhanced_prompt(self, signal_data: Dict, candles_data: Optional[List], is_manual_check: bool) -> str:
        """Создание расширенного промпта с историческими данными"""
        
        # Анализ уровней если есть данные свечей
        levels_analysis = {}
        candles_info = ""
        
        if candles_data:
            levels_analysis = self._analyze_price_levels(candles_data)
            
            if levels_analysis:
                candles_info = f"""
📈 АНАЛИЗ УРОВНЕЙ (последние 50 свечей):
• Ближайшее сопротивление: {levels_analysis.get('nearest_resistance', 'не найдено')} ₽
• Ближайшая поддержка: {levels_analysis.get('nearest_support', 'не найдено')} ₽
• Все сопротивления: {levels_analysis.get('all_resistances', [])}
• Все поддержки: {levels_analysis.get('all_supports', [])}
• Средняя волатильность: {levels_analysis.get('avg_volatility', 0)}% в день
• Соотношение объемов: {levels_analysis.get('volume_ratio', 1.0)} (текущий/средний)
• Диапазон 5 дней: {levels_analysis.get('price_range_5d', 'нет данных')}"""
        
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
            analysis_focus = "ДАТЬ КОНКРЕТНЫЕ TP/SL для покупки"
        else:
            strategy_status = "❌ УСЛОВИЯ НЕ ВЫПОЛНЕНЫ"
            analysis_focus = "УКАЗАТЬ какие уровни/показатели ждать для входа (БЕЗ TP/SL)"
        
        prompt = f"""ПОЛНЫЙ АНАЛИЗ РЫНОЧНОЙ СИТУАЦИИ SBER:

📊 ТЕХНИЧЕСКИЕ ДАННЫЕ:
• Цена: {signal_data['price']:.2f} ₽
• EMA20: {signal_data['ema20']:.2f} ₽ (цена {'выше' if price_above_ema_percent > 0 else 'ниже'} на {abs(price_above_ema_percent):.1f}%)
• ADX: {adx_value:.1f} ({adx_strength} тренд, {adx_risk})
• +DI: {signal_data['plus_di']:.1f} vs -DI: {signal_data['minus_di']:.1f}
• Преимущество DI: {di_difference:.1f} ({di_strength} доминация){candles_info}

⏰ КОНТЕКСТ:
• Время: {datetime.now().strftime('%H:%M МСК')} ({session_quality})
• Тип проверки: {signal_type}
• Статус стратегии: {strategy_status}

🎯 ГЛАВНАЯ ЗАДАЧА: {analysis_focus}

ВАЖНО: TP/SL указывай ТОЛЬКО если рекомендуешь BUY или WEAK_BUY!

Ответь в JSON:
{{
  "recommendation": "BUY/WEAK_BUY/WAIT/AVOID",
  "confidence": число_0_100,
  "reasoning": "детальное объяснение с уровнями (до 600 символов)",
  "take_profit": "конкретная цена TP только для BUY/WEAK_BUY или null",
  "stop_loss": "конкретная цена SL только для BUY/WEAK_BUY или null", 
  "expected_levels": "что ждать для входа (только для WAIT/AVOID) или null",
  "timeframe": "временной горизонт",
  "risk_warning": "главные риски"
}}"""
        
        return prompt
    
    async def _call_openai_api(self, prompt: str) -> Optional[str]:
        """Вызов OpenAI API с увеличенными лимитами для детального анализа"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "gpt-4o-mini",  # Быстрая модель
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,  # Минимальная креативность
            "max_tokens": 1000,   # Увеличили для полного анализа
            "response_format": {"type": "json_object"}
        }
        
        timeout = aiohttp.ClientTimeout(total=25)  # Увеличили таймаут
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.base_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data['choices'][0]['message']['content']
                        logger.info("✅ Получен расширенный ответ от GPT")
                        return content
                    elif response.status == 429:
                        logger.warning("⚠️ Rate limit OpenAI API")
                        return None
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ OpenAI API ошибка {response.status}: {error_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.warning("⏰ Таймаут запроса к OpenAI (25s)")
            return None
        except Exception as e:
            logger.error(f"💥 Неожиданная ошибка OpenAI: {e}")
            return None
    
    def _parse_enhanced_advice(self, response: str) -> Optional[GPTAdvice]:
        """Парсинг расширенного ответа GPT"""
        try:
            data = json.loads(response.strip())
            
            # Валидация обязательных полей
            recommendation = data.get('recommendation', 'AVOID').upper()
            if recommendation not in ['BUY', 'WEAK_BUY', 'WAIT', 'AVOID']:
                recommendation = 'AVOID'
            
            confidence = data.get('confidence', 50)
            if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 100:
                confidence = 50
            
            # Увеличили лимит для reasoning до 600 символов
            reasoning = str(data.get('reasoning', 'Анализ недоступен'))[:600]
            risk_warning = str(data.get('risk_warning', ''))[:300]
            
            # TP/SL только для покупок
            take_profit = None
            stop_loss = None
            if recommendation in ['BUY', 'WEAK_BUY']:
                take_profit = str(data.get('take_profit', ''))[:100] if data.get('take_profit') else None
                stop_loss = str(data.get('stop_loss', ''))[:100] if data.get('stop_loss') else None
            
            # Expected levels только для ожидания
            expected_levels = None
            if recommendation in ['WAIT', 'AVOID']:
                expected_levels = str(data.get('expected_levels', ''))[:300] if data.get('expected_levels') else None
            
            timeframe = str(data.get('timeframe', ''))[:150] if data.get('timeframe') else None
            
            return GPTAdvice(
                recommendation=recommendation,
                confidence=int(confidence),
                reasoning=reasoning,
                risk_warning=risk_warning,
                take_profit=take_profit,
                stop_loss=stop_loss,
                expected_levels=expected_levels,
                timeframe=timeframe
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Некорректный JSON от GPT: {e}")
            logger.error(f"Ответ: {response[:500]}...")
            return None
        except Exception as e:
            logger.error(f"💥 Ошибка парсинга GPT ответа: {e}")
            return None
    
    def format_advice_for_telegram(self, advice: GPTAdvice) -> str:
        """Форматирование расширенного совета GPT для Telegram - ОБНОВЛЕННАЯ ВЕРСИЯ"""
        
        # Эмодзи для рекомендаций
        rec_emoji = {
            'BUY': '🚀',
            'WEAK_BUY': '⚡',
            'WAIT': '⏳', 
            'AVOID': '⛔'
        }
        
        # Оценка условий вместо процентов
        if advice.confidence >= 80:
            confidence_text = "отличные условия"
            confidence_emoji = '🟢'
        elif advice.confidence >= 60:
            confidence_text = "средние условия"
            confidence_emoji = '🟡'
        else:
            confidence_text = "плохие условия"
            confidence_emoji = '🔴'
        
        # ИЗМЕНЕНО: новый заголовок
        result = f"""
🐱 <b>РЕВУЩИЙ КОТЁНОК СООБЩАЕТ:</b>
{rec_emoji.get(advice.recommendation, '❓')} <b>{advice.recommendation}</b> | {confidence_emoji} {confidence_text}

💡 <b>Анализ:</b> {advice.reasoning}"""
        
        # TP/SL ТОЛЬКО для покупок
        if advice.recommendation in ['BUY', 'WEAK_BUY']:
            if advice.take_profit:
                result += f"\n🎯 <b>Take Profit:</b> {advice.take_profit}"
            if advice.stop_loss:
                result += f"\n🛑 <b>Stop Loss:</b> {advice.stop_loss}"
        
        # Expected levels ТОЛЬКО для ожидания
        elif advice.recommendation in ['WAIT', 'AVOID'] and advice.expected_levels:
            # Проверяем, является ли строка JSON-подобной
            if advice.expected_levels.strip().startswith('{') and advice.expected_levels.strip().endswith('}'):
                try:
                    # Пытаемся распарсить как JSON
                    levels_data = json.loads(advice.expected_levels)
                    
                    # Форматируем красиво
                    levels_text = []
                    if 'breakout_level' in levels_data:
                        levels_text.append(f"пробой {levels_data['breakout_level']} ₽")
                    if 'support_level' in levels_data:
                        levels_text.append(f"поддержка {levels_data['support_level']} ₽")
                    if 'resistance_level' in levels_data:
                        levels_text.append(f"сопротивление {levels_data['resistance_level']} ₽")
                    
                    if levels_text:
                        result += f"\n📊 <b>Ждать:</b> {', '.join(levels_text)}"
                    else:
                        result += f"\n📊 <b>Ждать:</b> {advice.expected_levels}"
                        
                except (json.JSONDecodeError, KeyError):
                    # Если не удалось распарсить, выводим как есть
                    result += f"\n📊 <b>Ждать:</b> {advice.expected_levels}"
            else:
                # Обычная строка - выводим как есть
                result += f"\n📊 <b>Ждать:</b> {advice.expected_levels}"
        
        # УБРАЛИ: Временной горизонт и риски больше не показываем
        # if advice.timeframe:
        #     result += f"\n⏱️ <b>Горизонт:</b> {advice.timeframe}"
        # if advice.risk_warning:
        #     result += f"\n⚠️ <b>Риск:</b> {advice.risk_warning}"
        
        return result
