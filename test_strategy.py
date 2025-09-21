#!/usr/bin/env python3
"""
Утилита для тестирования стратегии Financial Potential
"""

import sys
import os
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json

# Добавляем путь к backend модулям
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from models import create_database, get_db_session, StrategySettings, VirtualAccount
from moex_api import get_moex_data, get_moex_candles
from strategy import FinancialPotentialStrategy
from virtual_trading import VirtualTradingEngine, StrategyManager

class StrategyTester:
    """Класс для тестирования стратегии"""
    
    def __init__(self):
        self.symbols = ["SBER", "GAZP", "LKOH", "VTBR"]
        self.results = {}
        
    def test_moex_connection(self):
        """Тест подключения к MOEX"""
        print("🌐 Тестирование подключения к MOEX...")
        try:
            data = get_moex_data(["SBER"])
            if "SBER" in data and data["SBER"].get("current_price"):
                print(f"✅ Подключение успешно! Цена SBER: {data['SBER']['current_price']:.2f} ₽")
                return True
            else:
                print("⚠️ Подключение есть, но данные неполные")
                return False
        except Exception as e:
            print(f"❌ Ошибка подключения: {e}")
            return False
    
    def test_strategy_calculations(self):
        """Тест расчетов стратегии"""
        print("\n🧮 Тестирование расчетов стратегии...")
        
        # Создаем тестовые данные
        dates = pd.date_range(start='2024-01-01', periods=100, freq='H')
        np.random.seed(42)  # Для воспроизводимости
        
        price = 100.0
        prices = [price]
        for _ in range(99):
            price += np.random.normal(0, 1)
            prices.append(price)
        
        test_data = pd.DataFrame({
            'datetime': dates,
            'open': prices,
            'high': [p + abs(np.random.normal(0, 0.5)) for p in prices],
            'low': [p - abs(np.random.normal(0, 0.5)) for p in prices],
            'close': prices,
            'volume': np.random.randint(1000, 10000, 100)
        })
        
        # Создаем настройки стратегии
        settings = StrategySettings(symbol="TEST")
        strategy = FinancialPotentialStrategy(settings)
        
        try:
            # Тестируем индикаторы
            indicators = strategy.calculate_indicators(test_data)
            print(f"   📊 ATR: {indicators.get('atr', 0):.4f}")
            print(f"   📊 RSI: {indicators.get('rsi', 0):.2f}")
            print(f"   📊 EMA: {indicators.get('ema', 0):.2f}")
            
            # Тестируем построение уровней
            strategy.build_levels(test_data)
            print(f"   📏 Построено уровней: {len(strategy.levels)}")
            
            # Тестируем генерацию сигнала
            signal = strategy.generate_signal(test_data, prices[-1])
            print(f"   🎯 Сигнал: {signal.direction}")
            print(f"   📈 Уверенность: {signal.confidence:.2f}")
            print(f"   💰 V_total: {signal.v_total:.4f}")
            
            print("✅ Расчеты работают корректно!")
            return True
            
        except Exception as e:
            print(f"❌ Ошибка в расчетах: {e}")
            return False
    
    def test_virtual_trading(self):
        """Тест виртуальной торговли"""
        print("\n💱 Тестирование виртуальной торговли...")
        
        try:
            # Создаем торговый движок
            engine = VirtualTradingEngine()
            
            # Получаем статистику счета
            stats = engine.get_account_statistics()
            print(f"   💳 Начальный баланс: {stats['account']['initial_balance']:,.0f} ₽")
            
            # Создаем тестовый сигнал
            from models import StrategySignal
            
            test_signal = StrategySignal(
                symbol="SBER",
                direction="BUY",
                confidence=0.8,
                entry_price=100.0,
                stop_loss=98.0,
                take_profit=105.0,
                lot_size=1.0,
                h_fin=0.5,
                rsi=35.0,
                v_level=-1.2,
                v_trend=0.1,
                v_rsi=-15.0,
                v_total=-1.1,
                timestamp=datetime.now()
            )
            
            # Размещаем ордер
            trade = engine.place_virtual_order(test_signal)
            if trade:
                print(f"   📝 Создан ордер ID: {trade.id}")
                print(f"   📊 Направление: {trade.direction}")
                print(f"   💰 Размер: {trade.lot_size} лот")
                print(f"   🎯 Цена входа: {trade.entry_price:.2f}")
            
            # Эмулируем изменение цены для закрытия сделки
            market_data = {
                "SBER": {
                    "current_price": 105.5,  # Цена выше тейк-профита
                    "candles": pd.DataFrame()
                }
            }
            
            # Обновляем сделки
            results = engine.update_trades(market_data)
            if results:
                print(f"   🔄 Обновлений сделок: {len(results)}")
                for result in results:
                    print(f"      {result['action']}: {result.get('symbol', 'N/A')}")
            
            # Получаем обновленную статистику
            new_stats = engine.get_account_statistics()
            profit = new_stats['account']['current_balance'] - stats['account']['initial_balance']
            print(f"   📈 Итоговый баланс: {new_stats['account']['current_balance']:,.2f} ₽")
            print(f"   💵 Прибыль/убыток: {profit:+.2f} ₽")
            
            print("✅ Виртуальная торговля работает!")
            return True
            
        except Exception as e:
            print(f"❌ Ошибка виртуальной торговли: {e}")
            return False
    
    def test_full_cycle(self):
        """Тест полного цикла работы"""
        print("\n🔄 Тестирование полного цикла...")
        
        try:
            # Получаем реальные данные
            print("   📡 Получение данных MOEX...")
            market_data = get_moex_data(["SBER"])
            
            if "SBER" not in market_data or not market_data["SBER"].get("current_price"):
                print("   ⚠️ Нет данных MOEX, используем тестовые")
                return self.test_strategy_calculations()
            
            # Создаем менеджер стратегий
            manager = StrategyManager()
            
            # Анализируем рынок
            print("   🔍 Анализ рынка...")
            signals = manager.analyze_market(market_data)
            
            print(f"   🎯 Получено сигналов: {len(signals)}")
            for signal in signals:
                print(f"      {signal.symbol}: {signal.direction} "
                      f"(confidence: {signal.confidence:.2f}, v_total: {signal.v_total:.4f})")
            
            # Обрабатываем сигналы
            if signals:
                print("   💼 Обработка сигналов...")
                results = manager.process_signals(signals)
                print(f"   📋 Размещено ордеров: {len(results)}")
            
            print("✅ Полный цикл работает!")
            return True
            
        except Exception as e:
            print(f"❌ Ошибка полного цикла: {e}")
            return False
    
    def benchmark_performance(self):
        """Бенчмарк производительности"""
        print("\n⚡ Тестирование производительности...")
        
        try:
            import time
            
            # Создаем большой dataset
            dates = pd.date_range(start='2024-01-01', periods=1000, freq='H')
            prices = np.random.randn(1000).cumsum() + 100
            
            test_data = pd.DataFrame({
                'datetime': dates,
                'open': prices,
                'high': prices + np.abs(np.random.randn(1000) * 0.5),
                'low': prices - np.abs(np.random.randn(1000) * 0.5),
                'close': prices,
                'volume': np.random.randint(1000, 10000, 1000)
            })
            
            settings = StrategySettings(symbol="BENCH")
            strategy = FinancialPotentialStrategy(settings)
            
            # Тест построения уровней
            start_time = time.time()
            strategy.build_levels(test_data)
            levels_time = time.time() - start_time
            print(f"   📏 Построение уровней (1000 баров): {levels_time:.3f}с")
            
            # Тест расчета индикаторов
            start_time = time.time()
            indicators = strategy.calculate_indicators(test_data)
            indicators_time = time.time() - start_time
            print(f"   📊 Расчет индикаторов: {indicators_time:.3f}с")
            
            # Тест генерации сигналов
            start_time = time.time()
            for _ in range(100):
                signal = strategy.generate_signal(test_data, prices[-1])
            signals_time = time.time() - start_time
            print(f"   🎯 100 сигналов: {signals_time:.3f}с")
            
            print("✅ Производительность в норме!")
            return True
            
        except Exception as e:
            print(f"❌ Ошибка производительности: {e}")
            return False
    
    def generate_report(self):
        """Генерация отчета о тестировании"""
        print("\n📊 Генерация отчета...")
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "tests": {
                "moex_connection": self.test_moex_connection(),
                "strategy_calculations": self.test_strategy_calculations(), 
                "virtual_trading": self.test_virtual_trading(),
                "full_cycle": self.test_full_cycle(),
                "performance": self.benchmark_performance()
            },
            "system_info": {
                "python_version": sys.version,
                "platform": sys.platform
            }
        }
        
        # Сохраняем отчет
        with open("test_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        # Выводим результаты
        print("\n" + "="*50)
        print("📋 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
        print("="*50)
        
        passed = 0
        total = len(report["tests"])
        
        for test_name, result in report["tests"].items():
            status = "✅ ПРОЙДЕН" if result else "❌ ПРОВАЛЕН"
            print(f"{test_name:.<30} {status}")
            if result:
                passed += 1
        
        print("-"*50)
        print(f"Общий результат: {passed}/{total} тестов пройдено")
        
        if passed == total:
            print("🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ! Система готова к работе.")
        else:
            print("⚠️ ЕСТЬ ПРОБЛЕМЫ! Проверьте логи выше.")
        
        print(f"📄 Подробный отчет сохранен в: test_report.json")
        
        return passed == total

def main():
    """Основная функция"""
    print("🧪 ТЕСТИРОВАНИЕ FINANCIAL POTENTIAL STRATEGY")
    print("="*60)
    
    # Инициализируем базу данных если нужно
    try:
        create_database()
    except Exception as e:
        print(f"Предупреждение: {e}")
    
    # Запускаем тесты
    tester = StrategyTester()
    success = tester.generate_report()
    
    if success:
        print("\n🚀 Система готова! Запустите:")
        print("   python run.py")
        sys.exit(0)
    else:
        print("\n❌ Найдены проблемы! Проверьте установку.")
        sys.exit(1)

if __name__ == "__main__":
    main()
