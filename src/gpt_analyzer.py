# src/gpt_analyzer.py - GPT сам рассчитывает ADX
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
    """Совет от GPT по сигналу с РЕАЛЬНЫМИ ADX данными"""
    recommendation: str  # "BUY", "AVOID", "WEAK_BUY", "WAIT"
    confidence: int      # 0-100%
    reasoning: str       # Объяснение
    risk_warning: str    # Предупреждение о рисках
    
    # НОВЫЕ поля с РЕАЛЬНЫМИ ADX расчетами от GPT
    calculated_adx: Optional[float] = None        # ADX рассчитанный GPT
    calculated_plus_di: Optional[float] = None    # +DI рассчитанный GPT  
    calculated_minus_di: Optional[float] = None   # -DI рассчитанный GPT
    
    # Остальные поля
    take_profit: Optional[str] = None
    stop_loss: Optional[str] = None
    expected_levels: Optional[str] = None
    timeframe: Optional[str] = None

class GPTMarketAnalyzer:
    """GPT анализатор с РЕАЛЬНЫМ расчетом ADX/DI"""
    
    def __init__(self, openai_api_key: str):
        self.api_key = openai_api_key
        self.base_url = "https://api.openai.com/v1/chat/completions"
        
        # НОВЫЙ системный промпт с инструкциями по расчету ADX
        self.base_system_prompt = """Ты профессиональный трейдер российского рынка с 20-летним опытом анализа голубых фишек и математическими навыками расчета технических индикаторов.

ТВОЯ РОЛЬ: Рассчитать ADX, +DI, -DI из свечных данных и принять торговое решение для {symbol}.

ОБЯЗАТЕЛЬНЫЙ РАСЧЕТ ADX/DI:
Ты ДОЛЖЕН рассчитать следующие индикаторы по классическим формулам:

1. TRUE RANGE (TR):
   TR = max(High - Low, |High - PrevClose|, |Low - PrevClose|)

2. DIRECTIONAL MOVEMENT (DM):
   +DM = High - PrevHigh если > 0 и > (PrevLow - Low), иначе 0
   -DM = PrevLow - Low если > 0 и > (High - PrevHigh), иначе 0

3. СГЛАЖИВАНИЕ (14-периодное сглаживание Уайлдера):
   Первое значение = среднее за 14 периодов
   Последующие = ((предыдущее * 13) + новое значение) / 14

4. DIRECTIONAL INDICATORS:
   +DI = (+DM14 / TR14) * 100
   -DI = (-DM14 / TR14) * 100

5. ADX CALCULATION:
   DX = (|+DI - -DI| / (+DI + -DI)) * 100
   ADX = 14-периодное сглаживание DX

КРИТЕРИИ СИГНАЛА BUY (ВСЕ ДОЛЖНЫ ВЫПОЛНЯТЬСЯ):
1. Цена > EMA20 (базовый фильтр уже пройден)
2. ADX > 25 (сильный тренд)
3. +DI > -DI (восходящее движение)
4. (+DI - -DI) > 1 (достаточная разница)

КРИТЕРИИ ПИКА ТРЕНДА (продавать):
- ADX > 45 (экстремально сильный тренд = пик)

{ticker_specific_context}

ФОРМАТ ОТВЕТА - СТРОГО JSON:
{{
  "calculated_adx": число (твой расчет ADX),
  "calculated_plus_di": число (твой расчет +DI),
  "calculated_minus_di": число (твой расчет -DI),
  "recommendation": "BUY/WEAK_BUY/WAIT/AVOID",
  "confidence": число_от_0_до_100,
  "reasoning": "подробное объяснение с показом расчетов ADX",
  "take_profit": "точная цена для BUY/WEAK_BUY или null",
  "stop_loss": "точная цена для BUY/WEAK_BUY или null",
  "expected_levels": "что ждать для WAIT/AVOID или null", 
  "timeframe": "временной горизонт",
  "risk_warning": "главные риски"
}}

ВАЖНО: 
- Обязательно покажи в reasoning свои расчеты ADX
- Используй минимум 30 последних свечей для расчета
- Рекомендация BUY только если ВСЕ критерии ADX выполнены"""

        # Контексты для разных тикеров
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
        """Анализ сигнала с РЕАЛЬНЫМ расчетом ADX через GPT"""
        try:
            # Получаем правильный системный промпт для тикера
            system_prompt = self.get_system_prompt(symbol)
            
            # Создаем промпт с большим количеством свечных данных для расчета ADX
            prompt = self._create_adx_calculation_prompt(signal_data, candles_data, is_manual_check, symbol)
            
            response = await self._call_openai_api(prompt, system_prompt)
            
            if response:
                return self._parse_adx_advice(response)
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка анализа GPT с ADX для {symbol}: {e}")
            return None
    
    def _create_adx_calculation_prompt(self, signal_data: Dict, candles_data: Optional[List], 
                                     is_manual_check: bool, symbol: str = 'SBER') -> str:
        """Создание промпта с данными для расчета ADX"""
        
        # Проверяем наличие достаточного количества свечей
        if not candles_data or len(candles_data) < 30:
            return f"""НЕДОСТАТОЧНО ДАННЫХ для расчета ADX {symbol}:
Получено свечей: {len(candles_data) if candles_data else 0}
Требуется минимум: 30

Ответь в JSON:
{{
  "calculated_adx": null,
  "calculated_plus_di": null, 
  "calculated_minus_di": null,
  "recommendation": "WAIT",
  "confidence": 20,
  "reasoning": "Недостаточно исторических данных для расчета ADX",
  "risk_warning": "Невозможно оценить силу тренда без ADX"
}}"""

        # Берем последние 50 свечей для надежного расчета ADX
        analysis_candles = candles_data[-50:] if len(candles_data) > 50 else candles_data
        
        # Формируем таблицу свечей для GPT
        candles_table = "№  | ДАТА_ВРЕМЯ     | OPEN    | HIGH    | LOW     | CLOSE   | VOLUME\n"
        candles_table += "---|----------------|---------|---------|---------|---------|----------\n"
        
        for i, candle in enumerate(analysis_candles):
            timestamp = candle.get('timestamp', datetime.now())
            if hasattr(timestamp, 'strftime'):
                date_str = timestamp.strftime('%d.%m %H:%M')
            else:
                date_str = str(timestamp)[:11]
            
            candles_table += f"{i+1:2d} | {date_str} | {candle['open']:7.2f} | {candle['high']:7.2f} | {candle['low']:7.2f} | {candle['close']:7.2f} | {candle['volume']:8,}\n"
        
        # Получаем контекстную информацию
        current_price = signal_data.get('price', 0)
        current_ema20 = signal_data.get('ema20', 0)
        session = signal_data.get('trading_session', 'unknown')
        time_quality = signal_data.get('time_quality', 'unknown')
        
        # Анализ объёмов и движения
        volume_info = ""
        if 'volume_analysis' in signal_data:
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

        # Уровни поддержки/сопротивления
        levels_info = ""
        if 'price_levels' in signal_data and signal_data['price_levels']:
            levels = signal_data['price_levels']
            levels_info = f"""
📈 УРОВНИ ПОДДЕРЖКИ/СОПРОТИВЛЕНИЯ:
• Ближайшее сопротивление: {levels.get('nearest_resistance', 'не найдено')} ₽
• Ближайшая поддержка: {levels.get('nearest_support', 'не найдено')} ₽
• Диапазон: {levels.get('recent_low', 0):.2f} - {levels.get('recent_high', 0):.2f} ₽"""

        signal_type = "Ручная проверка" if is_manual_check else "Автоматический анализ"
        check_peak = signal_data.get('check_peak', False)
        task_description = "ПРОВЕРИТЬ пик тренда (ADX>45?)" if check_peak else "РАССЧИТАТЬ ADX и дать рекомендацию"

        prompt = f"""РАСЧЕТ ADX ДЛЯ ТОРГОВОГО РЕШЕНИЯ {symbol}:

💰 ТЕКУЩИЕ ДАННЫЕ:
• Цена: {current_price:.2f} ₽
• EMA20: {current_ema20:.2f} ₽ (базовый фильтр {'✅ пройден' if current_price > current_ema20 else '❌ не пройден'})
• Пробой EMA20: {((current_price / current_ema20 - 1) * 100):+.2f}%{levels_info}{volume_info}{movement_info}

⏰ ТОРГОВЫЙ КОНТЕКСТ:
• Время: {datetime.now().strftime('%H:%M МСК')} (сессия: {session}, качество: {time_quality})
• Тип анализа: {signal_type}

📊 СВЕЧНЫЕ ДАННЫЕ ДЛЯ РАСЧЕТА ADX:
{candles_table}

🎯 ЗАДАЧА: {task_description}

ИНСТРУКЦИЯ:
1. Используй последние 30+ свечей из таблицы
2. Рассчитай TR, +DM, -DM для каждой свечи
3. Примени 14-периодное сглаживание Уайлдера
4. Вычисли +DI, -DI, DX, ADX
5. Покажи ключевые расчеты в reasoning
6. Дай рекомендацию на основе критериев ADX

КРИТЕРИИ BUY: ADX>25 И +DI>-DI И (+DI--DI)>1
КРИТЕРИЙ ПИКА: ADX>45"""

        return prompt
    
    def _parse_adx_advice(self, response: str) -> Optional[GPTAdvice]:
        """Парсинг ответа GPT с ADX расчетами"""
        try:
            data = json.loads(response.strip())
            
            # Валидация обязательных полей
            recommendation = data.get('recommendation', 'AVOID').upper()
            if recommendation not in ['BUY', 'WEAK_BUY', 'WAIT', 'AVOID']:
                recommendation = 'AVOID'
            
            confidence = data.get('confidence', 50)
            if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 100:
                confidence = 50
            
            reasoning = str(data.get('reasoning', 'Анализ недоступен'))[:800]  # Увеличил лимит для расчетов
            risk_warning = str(data.get('risk_warning', ''))[:300]
            
            # НОВОЕ: Извлекаем РЕАЛЬНЫЕ ADX расчеты от GPT
            calculated_adx = data.get('calculated_adx')
            calculated_plus_di = data.get('calculated_plus_di') 
            calculated_minus_di = data.get('calculated_minus_di')
            
            # Валидация ADX значений
            if calculated_adx is not None:
                try:
                    calculated_adx = float(calculated_adx)
                    if calculated_adx < 0 or calculated_adx > 100:
                        logger.warning(f"ADX вне диапазона: {calculated_adx}")
                        calculated_adx = None
                except (ValueError, TypeError):
                    calculated_adx = None
            
            if calculated_plus_di is not None:
                try:
                    calculated_plus_di = float(calculated_plus_di)
                    if calculated_plus_di < 0 or calculated_plus_di > 100:
                        calculated_plus_di = None
                except (ValueError, TypeError):
                    calculated_plus_di = None
                    
            if calculated_minus_di is not None:
                try:
                    calculated_minus_di = float(calculated_minus_di)
                    if calculated_minus_di < 0 or calculated_minus_di > 100:
                        calculated_minus_di = None
                except (ValueError, TypeError):
                    calculated_minus_di = None
            
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
            
            advice = GPTAdvice(
                recommendation=recommendation,
                confidence=int(confidence),
                reasoning=reasoning,
                risk_warning=risk_warning,
                # НОВЫЕ поля с РЕАЛЬНЫМИ расчетами
                calculated_adx=calculated_adx,
                calculated_plus_di=calculated_plus_di,
                calculated_minus_di=calculated_minus_di,
                # Остальные поля
                take_profit=take_profit,
                stop_loss=stop_loss,
                expected_levels=expected_levels,
                timeframe=timeframe
            )
            
            # Логируем полученные ADX значения
            if calculated_adx is not None:
                logger.info(f"🎯 GPT рассчитал ADX: {calculated_adx:.1f}, +DI: {calculated_plus_di:.1f}, -DI: {calculated_minus_di:.1f}")
            else:
                logger.warning("⚠️ GPT не смог рассчитать ADX")
            
            return advice
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Некорректный JSON от GPT: {e}")
            logger.error(f"Ответ GPT: {response[:200]}...")
            return None
        except Exception as e:
            logger.error(f"💥 Ошибка парсинга GPT с ADX: {e}")
            return None
    
    async def _call_openai_api(self, prompt: str, system_prompt: str = None) -> Optional[str]:
        """Вызов OpenAI API с увеличенным лимитом токенов для ADX расчетов"""
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
            "max_tokens": 1500,  # Увеличено для подробных расчетов ADX
            "response_format": {"type": "json_object"}
        }
        
        timeout = aiohttp.ClientTimeout(total=30)  # Увеличен таймаут
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.base_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data['choices'][0]['message']['content']
                        logger.info("✅ GPT анализ с ADX получен")
                        return content
                    elif response.status == 429:
                        logger.warning("⚠️ Rate limit OpenAI API")
                        return None
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ OpenAI API ошибка {response.status}: {error_text}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.warning("⏰ Таймаут запроса к OpenAI (ADX расчеты)")
            return None
        except Exception as e:
            logger.error(f"💥 Ошибка OpenAI с ADX: {e}")
            return None
    
    def format_advice_for_telegram(self, advice: GPTAdvice, symbol: str = 'SBER') -> str:
        """Форматирование совета GPT для Telegram с РЕАЛЬНЫМИ ADX данными"""
        
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
🤖 <b>GPT АНАЛИЗ {symbol} (с расчетом ADX):</b>
{rec_emoji.get(advice.recommendation, '❓')} <b>{advice.recommendation}</b> | {confidence_emoji} {confidence_text} ({advice.confidence}%)"""

        # НОВОЕ: Показываем РЕАЛЬНЫЕ ADX расчеты от GPT
        if advice.calculated_adx is not None:
            adx_status = "🟢" if advice.calculated_adx > 25 else "🔴"
            di_status = "🟢" if (advice.calculated_plus_di or 0) > (advice.calculated_minus_di or 0) else "🔴"
            
            result += f"""

📊 <b>РАСЧЕТЫ ADX (от GPT):</b>
• <b>ADX:</b> {advice.calculated_adx:.1f} {adx_status} {'(сильный тренд)' if advice.calculated_adx > 25 else '(слабый тренд)'}
• <b>+DI:</b> {advice.calculated_plus_di:.1f}
• <b>-DI:</b> {advice.calculated_minus_di:.1f} {di_status}
• <b>Разница DI:</b> {(advice.calculated_plus_di or 0) - (advice.calculated_minus_di or 0):+.1f}"""

        result += f"""

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
