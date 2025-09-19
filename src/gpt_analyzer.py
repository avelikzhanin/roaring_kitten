# src/gpt_analyzer.py - Комплексный анализ всех факторов
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
    """Комплексный совет от GPT с анализом всех факторов"""
    recommendation: str  # "BUY", "AVOID", "WEAK_BUY", "WAIT"
    confidence: int      # 0-100%
    reasoning: str       # Детальное объяснение
    risk_warning: str    # Предупреждение о рисках
    
    # ADX как один из факторов (может быть None)
    calculated_adx: Optional[float] = None        
    calculated_plus_di: Optional[float] = None   
    calculated_minus_di: Optional[float] = None   
    
    # Дополнительные поля
    take_profit: Optional[str] = None
    stop_loss: Optional[str] = None
    expected_levels: Optional[str] = None
    timeframe: Optional[str] = None
    key_factors: Optional[str] = None  # Ключевые факторы решения

class GPTMarketAnalyzer:
    """GPT анализатор с комплексным подходом ко всем факторам"""
    
    def __init__(self, openai_api_key: str):
        self.api_key = openai_api_key
        self.base_url = "https://api.openai.com/v1/chat/completions"
        
        # ОБНОВЛЕННЫЙ комплексный системный промпт для GPT-4.1
        self.base_system_prompt = """Ты профессиональный трейдер российского рынка с 20-летним опытом торговли голубыми фишками и экспертным знанием комплексного технического анализа.

ТВОЯ РОЛЬ: Провести ГЛУБОКИЙ ПРОФЕССИОНАЛЬНЫЙ анализ всех доступных факторов и принять взвешенное торговое решение для {symbol}.

АНАЛИЗИРУЙ ВСЕ ФАКТОРЫ ПРОФЕССИОНАЛЬНО:

1. 📊 ТЕХНИЧЕСКИЕ ИНДИКАТОРЫ (ПРИОРИТЕТ):
   - EMA20 (основной тренд-фильтр)
   - ADX/DI (сила и направление тренда) - ТОЧНО РАССЧИТАЙ из свечей
   - Поддержка/сопротивление (ключевые уровни)
   - Позиция в диапазоне и пробои

2. 📈 ЦЕНОВАЯ ДИНАМИКА (ДЕТАЛЬНЫЙ АНАЛИЗ):
   - Краткосрочные изменения (1ч, 4ч, 12ч, 1д, 3д)
   - Волатильность и ее изменения
   - Свечные паттерны и их качество
   - Пробои уровней и их подтверждение

3. 🔊 ОБЪЕМЫ (КРИТИЧЕСКИЙ ФАКТОР):
   - Текущий vs средний (разные периоды)
   - Тренд объемов и его устойчивость
   - Всплески активности и их причины
   - Качество движения с подтверждением объемами

4. ⏰ ВРЕМЕННОЙ КОНТЕКСТ (ПРОФЕССИОНАЛЬНЫЙ ПОДХОД):
   - Торговая сессия и качество времени
   - Ликвидность и спреды
   - Сезонность и макроэкономические факторы

5. 🎯 РЫНОЧНАЯ СИТУАЦИЯ (ЭКСПЕРТНЫЙ АНАЛИЗ):
   - Положение относительно ключевых уровней
   - Близость к важным техническим зонам
   - Общий настрой рынка и сектора
   - Корреляции с другими активами

{ticker_specific_context}

ПРИНЦИПЫ ПРОФЕССИОНАЛЬНОГО РЕШЕНИЯ:
- BUY: Все ключевые факторы позитивны, риски минимальны, высокая вероятность роста
- WEAK_BUY: Преобладают позитивные факторы, но есть предостережения
- WAIT: Неопределенность или смешанные сигналы, лучше дождаться ясности
- AVOID: Преобладают негативные факторы или неприемлемые риски

ТРЕБОВАНИЯ К КАЧЕСТВУ АНАЛИЗА:
- Используй профессиональную терминологию
- Обоснуй каждое утверждение конкретными данными
- Укажи точные числовые значения где возможно
- Дай конкретные уровни входа/выхода
- Оцени вероятность успеха трезво и честно

ФОРМАТ ОТВЕТА - СТРОГО JSON:
{{
  "calculated_adx": число_или_null (если удалось рассчитать точно),
  "calculated_plus_di": число_или_null,
  "calculated_minus_di": число_или_null,
  "recommendation": "BUY/WEAK_BUY/WAIT/AVOID",
  "confidence": число_от_0_до_100,
  "reasoning": "профессиональный детальный анализ всех факторов с конкретными числами",
  "key_factors": "3-4 главных фактора решения с количественными данными",
  "take_profit": "конкретный уровень с обоснованием или null",
  "stop_loss": "конкретный уровень с обоснованием или null", 
  "expected_levels": "ключевые уровни для отслеживания или null",
  "timeframe": "реалистичный горизонт сделки с обоснованием",
  "risk_warning": "основные риски с оценкой вероятности"
}}

КРИТИЧЕСКИ ВАЖНО: Будь максимально точным и честным. Лучше признать неопределенность, чем дать неточный совет!"""

        # Обновленные контексты для более точного анализа
        self.ticker_contexts = {
            'SBER': """
ПРОФЕССИОНАЛЬНЫЙ КОНТЕКСТ SBER:
- Ценовой диапазон: 280-330₽, типичная дневная волатильность 2-5%
- Оптимальное время анализа: 11:00-16:00 МСК (максимальная ликвидность)
- Ключевые драйверы: решения ЦБ РФ, санкционная политика, цены на нефть, дивидендная политика
- Критические техуровни: поддержка 275-285₽, сопротивление 320-340₽
- Объемные характеристики: норма 1-3М/час, всплески 5М+ на макроновостях
- Корреляции: высокая с рублем, нефтью, индексом MOEX
- Особенности: системообразующий банк, лидер сектора, высокая дивидендная доходность""",

            'GAZP': """
ПРОФЕССИОНАЛЬНЫЙ КОНТЕКСТ GAZP:
- Ценовой диапазон: 120-180₽, высокая волатильность 3-7%
- Оптимальное время: 11:00-16:00 МСК, осторожность вечером
- Ключевые драйверы: цены на газ в Европе, санкции, геополитика, отопительный сезон
- Критические техуровни: поддержка 125-135₽, сопротивление 170-185₽
- Объемные характеристики: средняя ликвидность, резкие всплески на новостях
- Корреляции: газовые фьючерсы, геополитические риски
- Особенности: высокая чувствительность к внешним факторам, экспортер""",

            'LKOH': """
ПРОФЕССИОНАЛЬНЫЙ КОНТЕКСТ LKOH:
- Ценовой диапазон: 6000-8000₽, умеренная волатильность 2-6%
- Оптимальное время: 11:00-16:00 МСК
- Ключевые драйверы: нефть Brent, санкции, курс рубля, дивидендная политика
- Критические техуровни: поддержка 6000-6200₽, сопротивление 7500-8000₽
- Объемные характеристики: ниже SBER, более широкие спреды
- Корреляции: нефть Brent, рубль, нефтегазовый сектор
- Особенности: вертикально-интегрированная компания, стабильные дивиденды""",

            'DEFAULT': """
ОБЩИЕ ПРОФЕССИОНАЛЬНЫЕ ПРИНЦИПЫ:
- Всегда учитывай макроэкономическую ситуацию и настроения рынка
- Анализируй исторические паттерны из предоставленных данных
- Премиум-время для торговли: 11:00-16:00 МСК (максимальная ликвидность)
- Будь особенно осторожен в периоды низкой ликвидности"""
        }

    def get_system_prompt(self, symbol: str) -> str:
        """Получение системного промпта для профессионального анализа"""
        context = self.ticker_contexts.get(symbol, self.ticker_contexts['DEFAULT'])
        return self.base_system_prompt.format(
            symbol=symbol,
            ticker_specific_context=context
        )

    async def analyze_signal(self, signal_data: Dict, candles_data: Optional[List] = None, 
                           is_manual_check: bool = False, symbol: str = 'SBER') -> Optional[GPTAdvice]:
        """Профессиональный комплексный анализ всех факторов через GPT-4.1"""
        try:
            # Получаем профессиональный системный промпт
            system_prompt = self.get_system_prompt(symbol)
            
            # Создаем детальный профессиональный промпт
            prompt = self._create_professional_prompt(signal_data, candles_data, is_manual_check, symbol)
            
            response = await self._call_openai_api(prompt, system_prompt)
            
            if response:
                return self._parse_professional_advice(response)
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка профессионального GPT-4.1 анализа для {symbol}: {e}")
            return None
    
    def _create_professional_prompt(self, signal_data: Dict, candles_data: Optional[List], 
                                   is_manual_check: bool, symbol: str = 'SBER') -> str:
        """Создание профессионального детального промпта"""
        
        # Ограничиваем свечи до 50 для оптимальной работы GPT-4.1
        if candles_data and len(candles_data) > 50:
            candles_data = candles_data[-50:]
            logger.info(f"🔢 Оптимизировали данные до 50 свечей для GPT-4.1 анализа {symbol}")
        
        # Проверяем достаточность данных для профессионального анализа
        if not candles_data or len(candles_data) < 20:
            return f"""НЕДОСТАТОЧНО ДАННЫХ для профессионального анализа {symbol}:
Получено свечей: {len(candles_data) if candles_data else 0}
Требуется минимум: 20 для качественного технического анализа

{{
  "calculated_adx": null,
  "calculated_plus_di": null, 
  "calculated_minus_di": null,
  "recommendation": "WAIT",
  "confidence": 15,
  "reasoning": "Недостаточно исторических данных для проведения качественного технического анализа и расчета индикаторов",
  "key_factors": "Дефицит данных, невозможность расчета ADX/DI",
  "risk_warning": "Принятие решений без достаточной аналитической базы крайне рискованно"
}}"""

        # Формируем ПРОФЕССИОНАЛЬНУЮ таблицу свечей
        candles_table = "№  | ВРЕМЯ МСК   | OPEN    | HIGH    | LOW     | CLOSE   | VOLUME   | ИЗМЕНЕНИЕ\n"
        candles_table += "---|-------------|---------|---------|---------|---------|----------|----------\n"
        
        for i, candle in enumerate(candles_data):
            timestamp = candle.get('timestamp', datetime.now())
            if hasattr(timestamp, 'strftime'):
                time_str = timestamp.strftime('%d.%m %H:%M')
            else:
                time_str = str(timestamp)[:11]
            
            # Рассчитываем изменение свечи
            change_pct = ((candle['close'] - candle['open']) / candle['open'] * 100) if candle['open'] > 0 else 0
            change_str = f"{change_pct:+.1f}%"
            
            candles_table += f"{i+1:2d} |{time_str:11s}|{candle['open']:8.2f}|{candle['high']:8.2f}|{candle['low']:8.2f}|{candle['close']:8.2f}|{candle['volume']:9,}|{change_str:8s}\n"
        
        # Получаем все профессиональные данные
        current_price = signal_data.get('price', 0)
        current_ema20 = signal_data.get('ema20', 0)
        session = signal_data.get('trading_session', 'unknown')
        time_quality = signal_data.get('time_quality', 'unknown')
        
        # Детальный анализ объемов
        volume_info = ""
        if 'volume_analysis' in signal_data:
            vol = signal_data['volume_analysis']
            volume_info = f"""
🔊 ПРОФЕССИОНАЛЬНЫЙ АНАЛИЗ ОБЪЕМОВ:
• Текущий объем: {vol.get('current_volume', 0):,}
• Среднее 5 периодов: {vol.get('avg_5', 0):,}
• Среднее 20 периодов: {vol.get('avg_20', 0):,}
• Среднее 50 периодов: {vol.get('avg_50', 0):,}
• Отношение к среднему: {vol.get('current_vs_avg', 1.0):.2f}x
• Краткосрочный тренд: {vol.get('recent_vs_medium', 1.0):.2f}x
• Долгосрочный тренд: {vol.get('recent_vs_long', 1.0):.2f}x
• Классификация: {vol.get('trend', 'unknown')}"""

        # Детальная ценовая динамика
        movement_info = ""
        changes = []
        for key in ['change_1h', 'change_4h', 'change_12h', 'change_1d', 'change_3d']:
            if key in signal_data:
                period = key.replace('change_', '').upper()
                changes.append(f"{period}: {signal_data[key]:+.2f}%")
        
        # Волатильность
        volatility_data = []
        for key in ['volatility_1d', 'volatility_3d', 'volatility_5d']:
            if key in signal_data:
                period = key.replace('volatility_', '').upper()
                volatility_data.append(f"Vol{period}: {signal_data[key]:.2f}%")
        
        if changes or volatility_data:
            movement_info = f"\n📈 ДЕТАЛЬНАЯ ЦЕНОВАЯ ДИНАМИКА:\n• Изменения: " + " | ".join(changes)
            if volatility_data:
                movement_info += f"\n• Волатильность: " + " | ".join(volatility_data)

        # Профессиональные уровни поддержки/сопротивления
        levels_info = ""
        if 'price_levels' in signal_data and signal_data['price_levels']:
            levels = signal_data['price_levels']
            resistance = levels.get('nearest_resistance')
            support = levels.get('nearest_support')
            recent_low = levels.get("recent_low", 0)
            recent_high = levels.get("recent_high", 0)
            range_size = levels.get("range_size_pct", 0)
            position_pct = levels.get("position_in_range_pct", 50)
            
            resistance_text = f"{resistance:.2f}₽ ({((resistance/current_price-1)*100):+.1f}%)" if resistance else "не определено"
            support_text = f"{support:.2f}₽ ({((support/current_price-1)*100):+.1f}%)" if support else "не определено"
            
            levels_info = f"""
📊 ПРОФЕССИОНАЛЬНЫЕ УРОВНИ:
• Ближайшее сопротивление: {resistance_text}
• Ближайшая поддержка: {support_text}
• Диапазон сессии: {recent_low:.2f} - {recent_high:.2f}₽ (размер: {range_size:.1f}%)
• Позиция в диапазоне: {position_pct:.1f}% (0%=дно, 100%=вершина)"""

        signal_type = "Ручная экспертная проверка" if is_manual_check else "Автоматический мониторинг"
        check_peak = signal_data.get('check_peak', False)
        task_description = "ОЦЕНИТЬ признаки пика тренда" if check_peak else "КОМПЛЕКСНЫЙ ПРОФЕССИОНАЛЬНЫЙ анализ для принятия торгового решения"

        # Формируем итоговый профессиональный промпт
        prompt = f"""ПРОФЕССИОНАЛЬНЫЙ КОМПЛЕКСНЫЙ АНАЛИЗ {symbol} - ЭКСПЕРТНАЯ ОЦЕНКА:

💰 ТЕКУЩАЯ РЫНОЧНАЯ СИТУАЦИЯ:
• Цена: {current_price:.2f}₽
• EMA20: {current_ema20:.2f}₽ ({'✅ цена выше' if current_price > current_ema20 else '❌ цена ниже'})
• Отклонение от EMA20: {((current_price/current_ema20-1)*100):+.2f}%{levels_info}{volume_info}{movement_info}

⏰ ТОРГОВЫЙ КОНТЕКСТ:
• Текущее время: {datetime.now().strftime('%H:%M МСК, %d.%m.%Y')}
• Торговая сессия: {session}
• Качество времени: {time_quality}
• Тип анализа: {signal_type}

📊 ДЕТАЛЬНЫЕ СВЕЧНЫЕ ДАННЫЕ ({len(candles_data)} свечей):
{candles_table}

🎯 ПРОФЕССИОНАЛЬНАЯ ЗАДАЧА: {task_description}

ВЫПОЛНИ ЭКСПЕРТНЫЙ АНАЛИЗ:
1. 📊 Точно рассчитай ADX/DI из предоставленных свечных данных
2. 📈 Проанализируй ценовые паттерны и качество движения  
3. 🔊 Оцени объемный профиль и подтверждение движения
4. ⏰ Учти временной контекст и качество ликвидности
5. 🎯 Определи ключевые технические уровни и зоны
6. 💡 Дай профессиональную рекомендацию с конкретными уровнями

ТРЕБУЮ МАКСИМАЛЬНОЙ ТОЧНОСТИ И ЧЕСТНОСТИ В ОЦЕНКАХ!"""

        return prompt
    
    def _parse_professional_advice(self, response: str) -> Optional[GPTAdvice]:
        """Парсинг профессионального ответа GPT-4.1"""
        try:
            data = json.loads(response.strip())
            
            # Строгая валидация рекомендации
            recommendation = data.get('recommendation', 'AVOID').upper()
            if recommendation not in ['BUY', 'WEAK_BUY', 'WAIT', 'AVOID']:
                logger.warning(f"Неверная рекомендация GPT: {recommendation}, заменяем на AVOID")
                recommendation = 'AVOID'
            
            # Строгая валидация уверенности
            confidence = data.get('confidence', 50)
            if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 100:
                logger.warning(f"Неверная уверенность GPT: {confidence}, заменяем на 50")
                confidence = 50
            
            reasoning = str(data.get('reasoning', 'Профессиональный анализ недоступен'))[:1500]  # Увеличен лимит
            risk_warning = str(data.get('risk_warning', ''))[:400]  # Увеличен лимит
            
            # Профессиональная валидация ADX данных
            calculated_adx = data.get('calculated_adx')
            calculated_plus_di = data.get('calculated_plus_di') 
            calculated_minus_di = data.get('calculated_minus_di')
            
            # Строгая валидация ADX
            if calculated_adx is not None:
                try:
                    calculated_adx = float(calculated_adx)
                    if calculated_adx < 0 or calculated_adx > 100:
                        logger.warning(f"ADX вне диапазона: {calculated_adx}")
                        calculated_adx = None
                except (ValueError, TypeError):
                    logger.warning(f"Некорректный ADX: {calculated_adx}")
                    calculated_adx = None
            
            if calculated_plus_di is not None:
                try:
                    calculated_plus_di = float(calculated_plus_di)
                    if calculated_plus_di < 0 or calculated_plus_di > 100:
                        logger.warning(f"+DI вне диапазона: {calculated_plus_di}")
                        calculated_plus_di = None
                except (ValueError, TypeError):
                    logger.warning(f"Некорректный +DI: {calculated_plus_di}")
                    calculated_plus_di = None
                    
            if calculated_minus_di is not None:
                try:
                    calculated_minus_di = float(calculated_minus_di)
                    if calculated_minus_di < 0 or calculated_minus_di > 100:
                        logger.warning(f"-DI вне диапазона: {calculated_minus_di}")
                        calculated_minus_di = None
                except (ValueError, TypeError):
                    logger.warning(f"Некорректный -DI: {calculated_minus_di}")
                    calculated_minus_di = None
            
            # Дополнительные профессиональные поля
            key_factors = str(data.get('key_factors', ''))[:300] if data.get('key_factors') else None
            
            # TP/SL только для покупок с валидацией
            take_profit = None
            stop_loss = None
            if recommendation in ['BUY', 'WEAK_BUY']:
                tp_raw = data.get('take_profit')
                sl_raw = data.get('stop_loss')
                take_profit = str(tp_raw)[:150] if tp_raw else None
                stop_loss = str(sl_raw)[:150] if sl_raw else None
            
            # Expected levels для ожидания
            expected_levels = None
            if recommendation in ['WAIT', 'AVOID']:
                el_raw = data.get('expected_levels')
                expected_levels = str(el_raw)[:400] if el_raw else None
            
            timeframe_raw = data.get('timeframe')
            timeframe = str(timeframe_raw)[:200] if timeframe_raw else None
            
            advice = GPTAdvice(
                recommendation=recommendation,
                confidence=int(confidence),
                reasoning=reasoning,
                risk_warning=risk_warning,
                # Профессиональные ADX данные
                calculated_adx=calculated_adx,
                calculated_plus_di=calculated_plus_di,
                calculated_minus_di=calculated_minus_di,
                # Дополнительные профессиональные поля
                key_factors=key_factors,
                take_profit=take_profit,
                stop_loss=stop_loss,
                expected_levels=expected_levels,
                timeframe=timeframe
            )
            
            # Профессиональное логирование
            adx_info = ""
            if calculated_adx is not None:
                adx_info = f", ADX: {calculated_adx:.1f}"
                if calculated_plus_di is not None and calculated_minus_di is not None:
                    adx_info += f" (+DI: {calculated_plus_di:.1f}, -DI: {calculated_minus_di:.1f})"
            
            logger.info(f"🎯 GPT-4.1 профессиональный анализ: {recommendation} ({confidence}%){adx_info}")
            
            return advice
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Некорректный JSON от GPT-4.1: {e}")
            logger.error(f"Ответ GPT-4.1: {response[:300]}...")
            return None
        except Exception as e:
            logger.error(f"💥 Ошибка парсинга профессионального анализа GPT-4.1: {e}")
            return None
    
    async def _call_openai_api(self, prompt: str, system_prompt: str = None) -> Optional[str]:
        """Вызов OpenAI API с GPT-4.1 и максимальной точностью"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        if system_prompt is None:
            system_prompt = self.get_system_prompt('SBER')
        
        payload = {
            "model": "gpt-4.1",  # ОБНОВЛЕНО на GPT-4.1
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.05,  # МАКСИМАЛЬНАЯ ТОЧНОСТЬ (снижено с 0.2)
            "max_tokens": 2000,   # УВЕЛИЧЕНО для более детальных ответов
            "top_p": 0.9,        # ДОБАВЛЕНО для более сфокусированных ответов
            "frequency_penalty": 0.1,  # ДОБАВЛЕНО для избежания повторов
            "presence_penalty": 0.1,   # ДОБАВЛЕНО для более разнообразных ответов
            "response_format": {"type": "json_object"}
        }
        
        timeout = aiohttp.ClientTimeout(total=45)  # Увеличен таймаут для GPT-4.1
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.base_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data['choices'][0]['message']['content']
                        
                        # Логируем использование токенов
                        usage = data.get('usage', {})
                        prompt_tokens = usage.get('prompt_tokens', 0)
                        completion_tokens = usage.get('completion_tokens', 0)
                        total_tokens = usage.get('total_tokens', 0)
                        
                        logger.info(f"✅ GPT-4.1 профессиональный анализ получен (токены: {prompt_tokens}+{completion_tokens}={total_tokens})")
                        return content
                    elif response.status == 429:
                        logger.warning("⚠️ Rate limit OpenAI API GPT-4.1")
                        return None
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ OpenAI API GPT-4.1 ошибка {response.status}: {error_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.warning("⏰ Таймаут запроса к OpenAI GPT-4.1")
            return None
        except Exception as e:
            logger.error(f"💥 Ошибка OpenAI API GPT-4.1: {e}")
            return None
    
    def format_advice_for_telegram(self, advice: GPTAdvice, symbol: str = 'SBER') -> str:
        """Форматирование профессионального совета GPT-4.1 для Telegram"""
        
        # Эмодзи для рекомендаций
        rec_emoji = {
            'BUY': '🚀',
            'WEAK_BUY': '⚡',
            'WAIT': '⏳', 
            'AVOID': '⛔'
        }
        
        # Профессиональная оценка уверенности
        if advice.confidence >= 85:
            confidence_text = "очень высокая уверенность"
            confidence_emoji = '🟢'
        elif advice.confidence >= 70:
            confidence_text = "высокая уверенность"
            confidence_emoji = '🟢'
        elif advice.confidence >= 55:
            confidence_text = "умеренная уверенность"  
            confidence_emoji = '🟡'
        elif advice.confidence >= 40:
            confidence_text = "низкая уверенность"
            confidence_emoji = '🟠'
        else:
            confidence_text = "очень низкая уверенность"
            confidence_emoji = '🔴'
        
        result = f"""
🤖 <b>GPT-4.1 ПРОФЕССИОНАЛЬНЫЙ АНАЛИЗ {symbol}:</b>
{rec_emoji.get(advice.recommendation, '❓')} <b>{advice.recommendation}</b> | {confidence_emoji} {confidence_text} ({advice.confidence}%)"""

        # Ключевые факторы решения
        if advice.key_factors:
            result += f"""

🎯 <b>Ключевые факторы:</b> {advice.key_factors}"""

        # Профессиональные ADX данные если рассчитаны
        if advice.calculated_adx is not None:
            adx_status = "🟢 Сильный" if advice.calculated_adx > 25 else "🔴 Слабый"
            
            result += f"""

📊 <b>Технический анализ ADX/DI:</b>
• <b>ADX:</b> {advice.calculated_adx:.1f} {adx_status} тренд"""
            
            if advice.calculated_plus_di is not None and advice.calculated_minus_di is not None:
                di_diff = advice.calculated_plus_di - advice.calculated_minus_di
                di_status = "🟢 Восходящий" if di_diff > 1 else "🔴 Нисходящий"
                result += f"""
• <b>+DI:</b> {advice.calculated_plus_di:.1f} | <b>-DI:</b> {advice.calculated_minus_di:.1f}
• <b>Направление:</b> {di_status} (разница: {di_diff:+.1f})"""

        result += f"""

💡 <b>Профессиональный анализ:</b> {advice.reasoning}"""
        
        # TP/SL для покупок
        if advice.recommendation in ['BUY', 'WEAK_BUY']:
            if advice.take_profit:
                result += f"\n🎯 <b>Take Profit:</b> {advice.take_profit}"
            if advice.stop_loss:
                result += f"\n🛑 <b>Stop Loss:</b> {advice.stop_loss}"
            if advice.timeframe:
                result += f"\n⏰ <b>Временной горизонт:</b> {advice.timeframe}"
        
        # Уровни ожидания для осторожных рекомендаций
        elif advice.recommendation in ['WAIT', 'AVOID'] and advice.expected_levels:
            result += f"\n📊 <b>Отслеживать уровни:</b> {advice.expected_levels}"
        
        # Предупреждение о рисках
        if advice.risk_warning:
            result += f"\n\n⚠️ <b>Профессиональная оценка рисков:</b> {advice.risk_warning}"
        
        result += f"\n\n<i>🤖 Анализ выполнен GPT-4.1 с максимальной точностью</i>"
        
        return result
