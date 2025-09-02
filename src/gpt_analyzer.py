# src/gpt_analyzer.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
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
    take_profit: Optional[str] = None    # Целевая прибыль (только для BUY/WEAK_BUY)
    stop_loss: Optional[str] = None      # Стоп-лосс (только для BUY/WEAK_BUY)
    expected_levels: Optional[str] = None # Ожидаемые уровни (для WAIT)
    timeframe: Optional[str] = None      # Временной горизонт

class GPTMarketAnalyzer:
    """Анализатор для обогащения торговых сигналов с помощью GPT"""
    
    def __init__(self, openai_api_key: str):
        self.api_key = openai_api_key
        self.base_url = "https://api.openai.com/v1/chat/completions"
        
        self.system_prompt = """Ты опытный технический аналитик российского рынка акций с 15-летним опытом работы с Сбербанком.

ВАЖНО: Давай TP/SL ТОЛЬКО для рекомендаций BUY и WEAK_BUY!
Для WAIT и AVOID указывай expected_levels (какие уровни ждать для входа).

ЛОГИКА РЕКОМЕНДАЦИЙ:
- BUY (80-100%): все технические условия выполнены + сильные уровни → обязательно TP/SL
- WEAK_BUY (60-79%): условия выполнены но есть риски → осторожные TP/SL  
- WAIT (40-59%): условия НЕ выполнены, ждем улучшения → expected_levels (какие показатели ждать)
- AVOID (<40%): плохая ситуация, не покупать → expected_levels (когда пересмотреть)

ПРИНЦИПЫ АНАЛИЗА:
- Анализируй ПОЛНУЮ картину: технические индикаторы + исторические данные + уровни
- Определяй конкретные уровни поддержки/сопротивления по свечным данным
- Учитывай объемы торгов и динамику цены
- Будь ЧЕСТНЫМ - если ситуация неясная, так и скажи
- Не давай TP/SL если не рекомендуешь покупать!

КОНТЕКСТ SBER:
- Обычно торгуется 280-330 рублей (волатильность 2-5% в день)
- Премиум время торгов: 11:00-16:00 МСК
- Реагирует на: новости ЦБ, санкции, нефть, дивиденды
- Ликвидная акция с узким спредом

ФОРМАТЫ ОТВЕТА:
- TP/SL: "312.50" (только цифры в рублях)
- expected_levels: "цена > EMA20 (310.50+), +DI > -DI с разностью >1"

Отвечай ТОЛЬКО в JSON формате."""

    async def analyze_signal(self, signal_data: Dict, candles_data: Optional[List] = None, is_manual_check: bool = False) -> Optional[GPTAdvice]:
        """Анализ торгового сигнала с помощью GPT с историческими данными"""
        try:
            prompt = self._create_enhanced_prompt(signal_data, candles_data, is_manual_check)
            response = await self._call_openai_api(prompt)
            
            if response:
                return self._parse_enhanced_advice(response, signal_data.get('conditions_met', False))
            
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
• Соотношение объемов: {levels_analysis.get('volume_ratio', 1.0)} (текущий/средний)"""
        
        # КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: проверяем выполнены ли технические условия
        conditions_met = signal_data.get('conditions_met', False)
        
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
            di_strength = "ОТСУТСТВУЕТ или НЕГАТИВНОЕ"
        
        price_above_ema_percent = ((signal_data['price'] / signal_data['ema20'] - 1) * 100)
        
        current_hour = datetime.now().hour
        if 11 <= current_hour <= 16:
            session_quality = "премиум время"
        elif 10 <= current_hour <= 18:
            session_quality = "нормальное время"
        else:
            session_quality = "плохое время для входа"
        
        signal_type = "Ручная проверка" if is_manual_check else "Автоматический сигнал"
        
        # КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: четко указываем статус стратегии
        if conditions_met:
            strategy_status = "✅ ВСЕ ТЕХНИЧЕСКИЕ УСЛОВИЯ ВЫПОЛНЕНЫ - можно покупать!"
            analysis_focus = "ДАТЬ КОНКРЕТНЫЕ TP/SL для покупки (рекомендация BUY/WEAK_BUY)"
        else:
            strategy_status = "❌ ТЕХНИЧЕСКИЕ УСЛОВИЯ НЕ ВЫПОЛНЕНЫ - НЕ покупаем!"
            analysis_focus = "УКАЗАТЬ expected_levels - какие показатели должны улучшиться (рекомендация WAIT/AVOID)"
        
        prompt = f"""АНАЛИЗ СИТУАЦИИ SBER:

📊 ТЕХНИЧЕСКИЕ ДАННЫЕ:
• Цена: {signal_data['price']:.2f} ₽
• EMA20: {signal_data['ema20']:.2f} ₽ (цена {'выше' if price_above_ema_percent > 0 else 'ниже'} на {abs(price_above_ema_percent):.1f}%)
• ADX: {adx_value:.1f} ({adx_strength} тренд, {adx_risk})
• +DI: {signal_data['plus_di']:.1f} vs -DI: {signal_data['minus_di']:.1f}
• Разность DI: {di_difference:.1f} ({di_strength} преимущество){candles_info}

⏰ КОНТЕКСТ:
• Время: {datetime.now().strftime('%H:%M МСК')} ({session_quality})
• Тип: {signal_type}

🚨 СТАТУС СТРАТЕГИИ: {strategy_status}

🎯 ЗАДАЧА: {analysis_focus}

СТРОГО СОБЛЮДАЙ ЛОГИКУ:
- Если условия НЕ выполнены → WAIT/AVOID + expected_levels (НЕ давай TP/SL!)
- Если условия выполнены → BUY/WEAK_BUY + TP/SL

JSON ответ:
{{
  "recommendation": "BUY/WEAK_BUY/WAIT/AVOID",
  "confidence": число_0_100,
  "reasoning": "краткое объяснение до 150 символов",
  "take_profit": {"только цифра типа 312.50" if условия_выполнены else null},
  "stop_loss": {"только цифра типа 307.80" if условия_выполнены else null}, 
  "expected_levels": {"что ждать для входа" if условия_НЕ_выполнены else null},
  "timeframe": "временной горизонт",
  "risk_warning": "главные риски до 100 символов"
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
            "max_tokens": 1200,   # Увеличили для полного анализа
            "response_format": {"type": "json_object"}
        }
        
        timeout = aiohttp.ClientTimeout(total=25)  # Увеличили таймаут
        
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
            logger.warning("⏰ Таймаут запроса к OpenAI (25s)")
            return None
        except Exception as e:
            logger.error(f"💥 Неожиданная ошибка OpenAI: {e}")
            return None
    
    def _parse_enhanced_advice(self, response: str, conditions_met: bool) -> Optional[GPTAdvice]:
        """Парсинг расширенного ответа GPT с валидацией логики"""
        try:
            data = json.loads(response.strip())
            
            # Валидация обязательных полей
            recommendation = data.get('recommendation', 'AVOID').upper()
            if recommendation not in ['BUY', 'WEAK_BUY', 'WAIT', 'AVOID']:
                recommendation = 'AVOID'
            
            confidence = data.get('confidence', 50)
            if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 100:
                confidence = 50
            
            reasoning = str(data.get('reasoning', 'Анализ недоступен'))[:200]  # Обрезаем
            risk_warning = str(data.get('risk_warning', ''))[:150]  # Обрезаем
            timeframe = str(data.get('timeframe', '')) if data.get('timeframe') else None
            
            # КЛЮЧЕВАЯ ЛОГИКА: TP/SL только для покупок, expected_levels только для ожидания
            take_profit = None
            stop_loss = None
            expected_levels = None
            
            if recommendation in ['BUY', 'WEAK_BUY']:
                # Для покупок - берем TP/SL
                take_profit = self._extract_price_from_string(data.get('take_profit'))
                stop_loss = self._extract_price_from_string(data.get('stop_loss'))
                
                # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: если технические условия не выполнены, 
                # но GPT рекомендует покупку - исправляем на WAIT
                if not conditions_met:
                    logger.warning(f"⚠️ GPT рекомендует {recommendation}, но условия не выполнены! Исправляем на WAIT")
                    recommendation = 'WAIT'
                    take_profit = None
                    stop_loss = None
                    expected_levels = "Технические условия стратегии не выполнены - ждем улучшения показателей"
                
            else:
                # Для ожидания/избегания - берем expected_levels
                expected_levels_raw = data.get('expected_levels')
                if expected_levels_raw:
                    if isinstance(expected_levels_raw, dict):
                        # Преобразуем словарь в читаемую строку
                        levels_parts = []
                        for key, value in expected_levels_raw.items():
                            if 'breakout' in key.lower():
                                levels_parts.append(f"пробой {value} ₽")
                            elif 'support' in key.lower():
                                levels_parts.append(f"поддержка {value} ₽")
                            else:
                                levels_parts.append(f"{key}: {value}")
                        expected_levels = ", ".join(levels_parts)
                    else:
                        expected_levels = str(expected_levels_raw)[:200]  # Обрезаем
            
            logger.info(f"🤖 Парсинг: {recommendation} | Условия: {conditions_met} | TP/SL: {bool(take_profit)}")
            
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
    
    def _extract_price_from_string(self, price_str) -> Optional[str]:
        """Извлечение цены из строки"""
        if not price_str:
            return None
        
        import re
        
        # Ищем числа с плавающей точкой
        price_match = re.search(r'(\d+\.?\d*)', str(price_str))
        if price_match:
            return price_match.group(1)
        
        return None  # Не возвращаем исходную строку
    
    def format_advice_for_telegram(self, advice: GPTAdvice) -> str:
        """Улучшенное форматирование совета GPT для Telegram"""
        
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
        
        # TP/SL только для покупок
        if advice.recommendation in ['BUY', 'WEAK_BUY']:
            if advice.take_profit and advice.stop_loss:
                result += f"\n🎯 <b>TP:</b> {advice.take_profit} ₽"
                result += f"\n🛑 <b>SL:</b> {advice.stop_loss} ₽"
            else:
                result += "\n💡 <i>TP/SL не определены</i>"
        
        # Expected levels только для ожидания
        elif advice.recommendation in ['WAIT', 'AVOID']:
            if advice.expected_levels:
                result += f"\n📊 <b>Ждать:</b> {advice.expected_levels}"
        
        # Временной горизонт
        if advice.timeframe:
            result += f"\n⏱️ <b>Горизонт:</b> {advice.timeframe}"
        
        # Риски
        if advice.risk_warning:
            result += f"\n⚠️ <b>Риск:</b> {advice.risk_warning}"
        
        return result
