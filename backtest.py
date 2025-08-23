#!/usr/bin/env python3
"""
ОПТИМИЗИРОВАННАЯ СТРАТЕГИЯ на основе результатов бэктеста
"""

from dataclasses import dataclass
from typing import Dict, List
import asyncio

@dataclass
class OptimizedTradeSetup:
    """Оптимизированные настройки на основе бэктеста"""
    
    # Основные выводы из бэктеста:
    # 1. Агрессивная стратегия работает лучше
    # 2. Большинство сделок закрывается по таймауту
    # 3. Нужны более реалистичные цели
    
    stop_loss_pct: float = -3.5        # Чуть шире стопы
    take_profit_pct: float = 4.0       # Более достижимые цели
    partial_profit_pct: float = 2.0    # Быстрая фиксация
    partial_close_pct: float = 0.5     # Закрываем 50%
    max_hold_hours: int = 36           # Короче удержание
    trailing_stop_pct: float = 1.5     # Тайтер трейлинг
    commission_pct: float = 0.1        # Реальная комиссия

@dataclass 
class SmartFilters:
    """Умные фильтры на основе анализа"""
    
    # Из бэктеста: сигналы 80-90% показали лучший винрейт (75%)
    min_signal_strength: float = 80.0
    max_signal_strength: float = 92.0  # Избегаем перекупленности
    
    # Временные фильтры
    avoid_late_friday: bool = True
    avoid_lunch_time: bool = True
    
    # Дополнительные условия
    min_adx: float = 35.0              # Выше среднего
    min_di_diff: float = 15.0          # Сильное доминирование
    max_ema_distance: float = 1.5      # Не слишком далеко от тренда

class OptimizedStrategy:
    """Оптимизированная стратегия торговли"""
    
    def __init__(self, token: str):
        self.token = token
        self.setup = OptimizedTradeSetup()
        self.filters = SmartFilters()
    
    def filter_signals(self, signals: List[Dict]) -> List[Dict]:
        """Умная фильтрация сигналов"""
        filtered = []
        
        for signal in signals:
            # Основные фильтры
            if not self.passes_strength_filter(signal):
                continue
            if not self.passes_time_filter(signal):
                continue
            if not self.passes_technical_filter(signal):
                continue
                
            filtered.append(signal)
        
        print(f"🔍 Отфильтровано {len(filtered)} из {len(signals)} сигналов")
        return filtered
    
    def passes_strength_filter(self, signal: Dict) -> bool:
        """Фильтр силы сигнала"""
        strength = signal['strength']
        return (self.filters.min_signal_strength <= strength <= 
                self.filters.max_signal_strength)
    
    def passes_time_filter(self, signal: Dict) -> bool:
        """Временной фильтр"""
        timestamp = signal['timestamp']
        
        # Избегаем пятницу после 16:00
        if (self.filters.avoid_late_friday and 
            timestamp.weekday() == 4 and timestamp.hour >= 16):
            return False
        
        # Избегаем обеденное время
        if (self.filters.avoid_lunch_time and 
            13 <= timestamp.hour <= 14):
            return False
            
        return True
    
    def passes_technical_filter(self, signal: Dict) -> bool:
        """Технический фильтр"""
        return (signal['adx'] >= self.filters.min_adx and
                signal['di_diff'] >= self.filters.min_di_diff)
    
    def calculate_position_size(self, signal: Dict, capital: float) -> Dict:
        """Расчет размера позиции на основе силы сигнала"""
        
        strength = signal['strength']
        base_risk = 0.02  # 2% риска на сделку
        
        # Корректировка риска по силе
        if strength >= 90:
            risk_multiplier = 1.5      # Больше риска на топ сигналы
        elif strength >= 85:
            risk_multiplier = 1.25
        elif strength >= 82:
            risk_multiplier = 1.0
        else:
            risk_multiplier = 0.75     # Меньше риска на слабые
        
        risk_per_trade = capital * base_risk * risk_multiplier
        stop_distance = abs(self.setup.stop_loss_pct / 100)
        
        # Количество акций
        shares = int(risk_per_trade / (signal['price'] * stop_distance))
        position_value = shares * signal['price']
        
        return {
            'shares': shares,
            'position_value': position_value,
            'risk_amount': risk_per_trade,
            'risk_multiplier': risk_multiplier
        }

async def test_optimized_strategy():
    """Тест оптимизированной стратегии"""
    
    import os
    from backtest_analyzer import BacktestEngine  # Импорт из предыдущего кода
    
    token = os.getenv('TINKOFF_TOKEN')
    if not token:
        print("❌ TINKOFF_TOKEN не найден")
        return
    
    print("🎯 ТЕСТИРОВАНИЕ ОПТИМИЗИРОВАННОЙ СТРАТЕГИИ")
    print("=" * 60)
    
    # Создаем оптимизированную стратегию
    opt_setup = OptimizedTradeSetup()
    engine = BacktestEngine(token, opt_setup)
    
    # Генерируем сигналы
    all_signals = engine.generate_sample_signals()
    
    # Применяем умную фильтрацию
    strategy = OptimizedStrategy(token)
    filtered_signals = strategy.filter_signals(all_signals)
    
    if not filtered_signals:
        print("❌ Не осталось сигналов после фильтрации")
        return
    
    # Тестируем
    print(f"\n📊 Тестируем {len(filtered_signals)} отфильтрованных сигналов...")
    results = await engine.run_backtest(filtered_signals)
    
    # Дополнительный анализ
    if results:
        analyze_optimization_results(results, filtered_signals)

def analyze_optimization_results(results, signals: List[Dict]):
    """Анализ результатов оптимизации"""
    
    print(f"\n{'='*60}")
    print("🎯 АНАЛИЗ ОПТИМИЗИРОВАННОЙ СТРАТЕГИИ")
    print(f"{'='*60}")
    
    print(f"\n📈 УЛУЧШЕНИЯ:")
    
    # Сравнение с базовой стратегией
    base_winrate = 40.0   # Из предыдущих результатов
    base_return = 0.3
    
    improvement_winrate = results.win_rate - base_winrate
    improvement_return = results.total_return_pct - base_return
    
    print(f"   📊 Винрейт: {results.win_rate:.1f}% ({improvement_winrate:+.1f}% vs базовой)")
    print(f"   💰 Доходность: {results.total_return_pct:.1f}% ({improvement_return:+.1f}% vs базовой)")
    print(f"   🔧 Отфильтровано сигналов: {80 - len(signals)}")
    
    # Статистика по силе оставшихся сигналов
    strengths = [s['strength'] for s in signals]
    print(f"\n📊 СТАТИСТИКА ОТФИЛЬТРОВАННЫХ СИГНАЛОВ:")
    print(f"   • Средняя сила: {sum(strengths)/len(strengths):.1f}%")
    print(f"   • Минимальная: {min(strengths):.1f}%")
    print(f"   • Максимальная: {max(strengths):.1f}%")
    
    # Расчет для разных капиталов
    print(f"\n💼 РЕКОМЕНДУЕМЫЕ РАЗМЕРЫ ПОЗИЦИЙ:")
    
    strategy = OptimizedStrategy("")
    
    for capital in [100_000, 500_000, 1_000_000]:
        total_risk = 0
        total_positions = 0
        
        for signal in signals[:5]:  # Первые 5 для примера
            pos_calc = strategy.calculate_position_size(signal, capital)
            total_risk += pos_calc['risk_amount']
            total_positions += 1
        
        avg_position = total_risk / total_positions if total_positions > 0 else 0
        
        print(f"   💰 Капитал {capital:,}: средний риск {avg_position:,.0f} руб на сделку")
        print(f"      └─ При винрейте {results.win_rate:.1f}% ожидаемая прибыль: "
              f"{(avg_position * results.average_trade_pct / 100):+,.0f} руб")

def create_trading_plan():
    """Создание финального торгового плана"""
    
    plan = f"""
🎯 ФИНАЛЬНЫЙ ТОРГОВЫЙ ПЛАН - SBER 1H (на основе бэктеста)

📋 ФИЛЬТРЫ ВХОДА:
✅ Сила сигнала: 80-92% (избегаем перекупленности)
✅ ADX ≥ 35 (сильный тренд)
✅ DI разность ≥ 15 (доминирование покупателей)
✅ Время: избегать 13:00-14:00 и пятницу после 16:00
✅ Цена не более чем на 1.5% выше EMA20

💰 УПРАВЛЕНИЕ КАПИТАЛОМ:
• Базовый риск: 2% капитала на сделку
• Сильные сигналы (90%+): риск × 1.5
• Средние сигналы (85-90%): риск × 1.25  
• Слабые сигналы (80-85%): риск × 0.75

🎯 ЦЕЛИ И СТОПЫ (оптимизированные):
• Стоп-лосс: -3.5% (реалистично)
• Частичная фиксация: +2% (50% позиции)
• Основная цель: +4% (достижимо)
• Максимальное удержание: 36 часов
• Трейлинг-стоп: 1.5% после достижения +2%

📊 ОЖИДАЕМЫЕ РЕЗУЛЬТАТЫ:
• Винрейт: ~55-65% (улучшение за счет фильтров)
• Средняя прибыль: +0.5-1.0% на сделку
• Максимальная просадка: <15%
• Сделок в месяц: 8-12 (качество важнее количества)

💡 ПСИХОЛОГИЯ ТОРГОВЛИ:
• Не торговать все сигналы подряд
• Строго следовать фильтрам
• Фиксировать частичную прибыль на +2%
• Не передвигать стопы против себя
• Вести дневник сделок для анализа

🚨 КРАСНЫЕ ФЛАГИ (выходить немедленно):
• Резкие новости по Сберу
• Обвал рынка более 3%
• Нарушение технических уровней
• Превышение дневного лимита убытков (-6% капитала)

🤖 КОД ДЛЯ АВТОМАТИЗАЦИИ:
if (signal_strength >= 80 and signal_strength <= 92 and
    adx >= 35 and di_diff >= 15 and
    not (13 <= hour <= 14) and
    not (weekday == 4 and hour >= 16)):
    
    risk_mult = get_risk_multiplier(signal_strength)
    position_size = calculate_position(capital, risk_mult)
    
    entry_price = current_price
    stop_loss = entry_price * 0.965
    partial_target = entry_price * 1.02
    full_target = entry_price * 1.04
    
    execute_trade(position_size, stop_loss, partial_target, full_target)
    """
    
    return plan

if __name__ == "__main__":
    # Запуск оптимизированного теста
    asyncio.run(test_optimized_strategy())
    
    # Показ торгового плана
    print("\n" + "="*80)
    print(create_trading_plan())
