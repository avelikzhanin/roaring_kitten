# src/gpt_analyzer.py - СОВРЕМЕННАЯ ВЕРСИЯ без ADX/DI
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
    """СОВРЕМЕННЫЙ анализатор для гибридной стратегии (БЕЗ ADX/DI)"""
    
    def __init__(self, openai_api_key: str):
        self.api_key = openai_api_key
        self.base_url = "https://api.openai.com/v1/chat/completions"
        
        # НОВЫЙ системный промпт без ADX/DI
        self.base_system_prompt = """Ты профессиональный трейдер российского рынка с 20-летним опытом анализа голубых фишек.

ТВОЯ РОЛЬ: Принимать торговые решения на основе СОВРЕМЕННОГО анализа {symbol} для получения ПРИБЫЛИ.

ДАННЫЕ ДЛЯ АНАЛИЗА:
- Ценовое движение относительно EMA20 (базовый тренд)
- Объёмы торгов и их динамика  
- Уровни поддержки и сопротивления
- Свечные паттерны (последние 50 свечей)
- Волатильность и momentum
- Контекст торговой сессии

ПРИНЦИПЫ РЕШЕНИЙ:
- ЧЕСТНОСТЬ: если ситуация неясная, говори прямо
- КОНКРЕТНОСТЬ: точные цифры вместо "около" или "примерно"  
- ПРИБЫЛЬ: фокус на заработке, а не на академической теории
- РИСКИ: всегда предупреждай о главных опасностях
- ВРЕМЯ: учитывай качество торговой сессии

ТИПЫ РЕКОМЕНДАЦИЙ:
- BUY: уверенная покупка (75-100%) → обязательно TP/SL
- WEAK_BUY: осторожная покупка (60-74%) → консервативные TP/SL
- WAIT: ждать лучшего момента (40-59%) → указать какие уровни ждать
- AVOID: не покупать сейчас (<40%) → объяснить почему

{ticker_specific_context}

ТРЕБОВАНИЯ К ОТВЕТУ:
- Конкретные числовые уровни (не "около 300", а "302.50")
- TP/SL только для BUY/WEAK_BUY
- Временные рамки для всех решений
- Анализ рисков

Отвечай СТРОГО в JSON формате."""

        # Контексты для разных тикеров (обновлённые)
        self.ticker_contexts = {
            'SBER': """
СПЕЦИФИКА SBER:
- Типичный диапазон: 280-330 ₽ (волатильность 2-5%/день)
- Премиум торги: 11:00-16:00 МСК (максимальная ликвидность)
- Реакция на: решения ЦБ, санкции, нефть, дивиденды, геополитику
- Ключевые уровни: поддержка 270-280₽, сопротивление 320-340₽
- Объёмы: норма 1-3М/час, всплески до 5М+ на новостях""",

            'GAZP': """
СПЕЦИФИКА GAZP:
- Типичный диапазон: 120-180 ₽ (волатильность 3-7%/день)
- Премиум торги: 11:00-16:00 МСК
- Реакция на: цены на газ, санкции, геополитику, сезонность отопления
- Ключевые уровни: поддержка 120-130₽, сопротивление 170-190₽
- Особенность: высокая волатильность из-за внешних факторов""",

            'LKOH': """
СПЕЦИФИКА LKOH:
- Типичный диапазон: 6000-8000 ₽ (волатильность 2-6%/день)  
- Премиум торги: 11:00-16:00 МСК
- Реакция на: цены на нефть Brent, санкции, курс рубля, дивиденды
- Ключевые уровни: поддержка 6000-6200₽, сопротивление 7500-8000₽
- Особенность: менее ликвидная, больший спред чем SBER""",

            'DEFAULT': """
ОБЩИЕ ПРИНЦИПЫ:
- Учитывай общерыночные факторы и новости компании
- Анализируй исторические уровни из предоставленных данных
- Премиум время торгов: 11:00-16:00 МСК"""
        }

    def get_system_prompt(self, symbol: str) -> str:
        """Получение системного промпта для конкретного тикера"""
        context = self.ticker_contexts.get(symbol, self.ticker_contexts['DEFAULT'])
        return self.base_system_prompt.format(
            symbol=symbol,
            ticker_specific_context=context
        )

    async def analyze_signal(self, signal_data: Dict, candles_data: Optional[List] = None, 
                           is_manual_check: bool = False, symbol: str = 'SBER') -> Optional[GPTAdvice]:
        """СОВРЕМЕННЫЙ анализ торгового сигнала (БЕЗ ADX/DI)"""
        try:
            # Получаем правильный системный промпт для тикера
            system_prompt = self.get_system_prompt(symbol)
            
            # Создаем СОВРЕМЕННЫЙ промпт
            prompt = self._create_modern_prompt(signal_data, candles_data, is_manual_check, symbol)
            
            response = await self._call_openai_api(prompt, system_prompt)
            
            if response:
                return self._parse_enhanced_advice(response)
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка анализа GPT для {symbol}: {e}")
            return None
    
    def _create_modern_prompt(self, signal_data: Dict, candles_data: Optional[List], 
                             is_manual_check: bool, symbol: str = 'SBER') -> str:
        """Создание СОВРЕМЕННОГО промпта без ADX/DI"""
        
        # Анализ уровней если есть данные свечей
        levels_info = ""
        volume_info = ""
        movement_info = ""
        
        if candles_data and len(candles_data) > 10:
            levels_analysis = self._analyze_price_levels(candles_data)
            
            if levels_analysis:
                levels_info = f"""
📈 УРОВНИ ПОДДЕРЖКИ/СОПРОТИВЛЕНИЯ:
• Ближайшее сопротивление: {levels_analysis.get('nearest_resistance', 'не найдено')} ₽
• Ближайшая поддержка: {levels_analysis.get('nearest_support', 'не найдено')} ₽
• Диапазон 50 свечей: {levels_analysis.get('range_low', 0):.2f} - {levels_analysis.get('range_high', 0):.2f} ₽"""
        
        # Анализ объёмов
        if 'volume_analysis' in signal_data and signal_data['volume_analysis']:
            vol = signal_data['volume_analysis']
            volume_info = f"""
🔊 АНАЛИЗ ОБЪЁМОВ:
• Текущий объём: {vol.get('current_volume', 0):,} акций
• Отношение к среднему: {vol.get('volume_ratio', 1.0):.2f}x
• Тренд объёмов: {vol.get('volume_trend', 'unknown')}"""
        
        # Движение цены  
        movement_info = ""
        for key in ['change_1h', 'change_4h', 'change_1d', 'volatility_5d']:
            if key in signal_data:
                if key == 'volatility_5d':
                    movement_info += f"\n• Волатильность 5д: {signal_data[key]:.1f}%"
                else:
                    period = key.replace('change_', '').upper()
                    movement_info += f"\n• Изменение {period}: {signal_data[key]:+.2f}%"
        
        if movement_info:
            movement_info = f"\n📊 ДВИЖЕНИЕ ЦЕНЫ:{movement_info}"
        
        # Проверяем выполнены ли базовые условия
        conditions_met = signal_data.get('conditions_met', True)
        price_above_ema = signal_data.get('price_above_ema', True)
        
        # Контекст времени торгов
        current_hour = datetime.now().hour
        session = signal_data.get('trading_session', 'unknown')
        time_quality = signal_data.get('time_quality', 'unknown')
        
        if time_quality == 'premium':
            session_desc = "отличное время (премиум часы)"
        elif time_quality == 'normal':
            session_desc = "нормальное время"
        elif time_quality == 'evening':
            session_desc = "вечерняя сессия"
        else:
            session_desc = f"сессия {session}"
        
        # Определяем статус условий стратегии
        if conditions_met and price_above_ema:
            strategy_status = "✅ БАЗОВЫЙ ФИЛЬТР ПРОЙДЕН"
            analysis_focus = "ДАТЬ КОНКРЕТНЫЕ TP/SL для покупки"
        else:
            strategy_status = "❌ БАЗОВЫЕ УСЛОВИЯ НЕ ВЫПОЛНЕНЫ"
            analysis_focus = "УКАЗАТЬ какие уровни/показатели ждать (БЕЗ TP/SL)"
        
        signal_type = "Ручная проверка" if is_manual_check else "Автоматический сигнал"
        check_peak = signal_data.get('check_peak', False)
        if check_peak:
            analysis_focus = "ПРОВЕРИТЬ не пик ли тренда (продавать?)"
        
        prompt = f"""АНАЛИЗ РЫНОЧНОЙ СИТУАЦИИ {symbol}:

💰 ОСНОВНЫЕ ДАННЫЕ:
• Цена: {signal_data.get('price', 0):.2f} ₽
• EMA20: {signal_data.get('ema20', 0):.2f} ₽ (цена {'выше ✅' if price_above_ema else 'ниже ❌'})
• Пробой EMA20: {((signal_data.get('price', 0) / signal_data.get('ema20', 1) - 1) * 100):+.2f}%{levels_info}{volume_info}{movement_info}

⏰ ТОРГОВЫЙ КОНТЕКСТ:
• Время: {datetime.now().strftime('%H:%M МСК')} ({session_desc})
• Тип проверки: {signal_type}
• Статус стратегии: {strategy_status}

🎯 ЗАДАЧА: {analysis_focus}

Ответь в JSON:
{{
  "recommendation": "BUY/WEAK_BUY/WAIT/AVOID",
  "confidence": число_от_0_до_100,
  "reasoning": "детальное объяснение с конкретными уровнями (до 600 символов)",
  "take_profit": "точная цена TP для BUY/WEAK_BUY или null",
  "stop_loss": "точная цена SL для BUY/WEAK_BUY или null", 
  "expected_levels": "что ждать для WAIT/AVOID или null",
  "timeframe": "временной горизонт сделки",
  "risk_warning": "главные риски текущей ситуации"
}}"""
        
        return prompt
    
    def _analyze_price_levels(self, candles_data: List[Dict]) -> Dict:
        """Анализ уровней поддержки и сопротивления из свечных данных"""
        try:
            if len(candles_data) < 20:
                return {}
            
            # Последние 50 свечей для анализа уровней
            recent_candles = candles_data[-50:] if len(candles_data) > 50 else candles_data
            
            highs = [c['high'] for c in recent_candles]
            lows = [c['low'] for c in recent_candles]
            closes = [c['close'] for c in recent_candles]
            
            current_price = closes[-1]
            
            # Поиск уровней сопротивления (локальные максимумы)
            resistances = []
            for i in range(2, len(highs) - 2):
                if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and 
                    highs[i] > highs[i+1] and highs[i] > highs[i+2]):
                    if highs[i] > current_price:
                        resistances.append(highs[i])
            
            # Поиск уровней поддержки (локальные минимумы)
            supports = []
            for i in range(2, len(lows) - 2):
                if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and 
                    lows[i] < lows[i+1] and lows[i] < lows[i+2]):
                    if lows[i] < current_price:
                        supports.append(lows[i])
            
            resistances = sorted(list(set(resistances)))[:3]  # Ближайшие 3
            supports = sorted(list(set(supports)), reverse=True)[:3]  # Ближайшие 3
            
            return {
                'current_price': current_price,
                'nearest_resistance': resistances[0] if resistances else None,
                'nearest_support': supports[0] if supports else None,
                'all_resistances': resistances,
                'all_supports': supports,
                'range_high': max(highs),
                'range_low': min(lows)
            }
            
        except Exception as e:
            logger.error(f"Ошибка анализа уровней: {e}")
            return {}
    
    async def _call_openai_api(self, prompt: str, system_prompt: str = None) -> Optional[str]:
        """Вызов OpenAI API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        if system_prompt is None:
            system_prompt = self.get_system_prompt('SBER')
        
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 1000,
            "response_format": {"type": "json_object"}
        }
        
        timeout = aiohttp.ClientTimeout(total=25)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.base_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data['choices'][0]['message']['content']
                        logger.info("✅ GPT анализ получен")
                        return content
                    elif response.status == 429:
                        logger.warning("⚠️ Rate limit OpenAI API")
                        return None
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ OpenAI API ошибка {response.status}: {error_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.warning("⏰ Таймаут запроса к OpenAI")
            return None
        except Exception as e:
            logger.error(f"💥 Ошибка OpenAI: {e}")
            return None
    
    def _parse_enhanced_advice(self, response: str) -> Optional[GPTAdvice]:
        """Парсинг ответа GPT"""
        try:
            data = json.loads(response.strip())
            
            # Валидация обязательных полей
            recommendation = data.get('recommendation', 'AVOID').upper()
            if recommendation not in ['BUY', 'WEAK_BUY', 'WAIT', 'AVOID']:
                recommendation = 'AVOID'
            
            confidence = data.get('confidence', 50)
            if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 100:
                confidence = 50
            
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
            return None
        except Exception as e:
            logger.error(f"💥 Ошибка парсинга GPT: {e}")
            return None
    
    def format_advice_for_telegram(self, advice: GPTAdvice, symbol: str = 'SBER') -> str:
        """Форматирование совета GPT для Telegram"""
        
        # Эмодзи для рекомендаций
        rec_emoji = {
            'BUY': '🚀',
            'WEAK_BUY': '⚡',
            'WAIT': '⏳', 
            'AVOID': '⛔'
        }
        
        # Оценка уверенности
        if advice.confidence >= 80:
            confidence_text = "высокая уверенность"
            confidence_emoji = '🟢'
        elif advice.confidence >= 60:
            confidence_text = "средняя уверенность"
            confidence_emoji = '🟡'
        else:
            confidence_text = "низкая уверенность"
            confidence_emoji = '🔴'
        
        result = f"""
🤖 <b>GPT АНАЛИЗ {symbol}:</b>
{rec_emoji.get(advice.recommendation, '❓')} <b>{advice.recommendation}</b> | {confidence_emoji} {confidence_text} ({advice.confidence}%)

💡 <b>Обоснование:</b> {advice.reasoning}"""
        
        # TP/SL ТОЛЬКО для покупок
        if advice.recommendation in ['BUY', 'WEAK_BUY']:
            if advice.take_profit:
                result += f"\n🎯 <b>Take Profit:</b> {advice.take_profit}"
            if advice.stop_loss:
                result += f"\n🛑 <b>Stop Loss:</b> {advice.stop_loss}"
            if advice.timeframe:
                result += f"\n⏰ <b>Горизонт:</b> {advice.timeframe}"
        
        # Expected levels ТОЛЬКО для ожидания
        elif advice.recommendation in ['WAIT', 'AVOID'] and advice.expected_levels:
            result += f"\n📊 <b>Ждать:</b> {advice.expected_levels}"
        
        # Предупреждение о рисках
        if advice.risk_warning:
            result += f"\n\n⚠️ <b>Риски:</b> {advice.risk_warning}"
        
        return result
