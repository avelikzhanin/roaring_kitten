#!/usr/bin/env python3
"""
Скрипт запуска Financial Potential Strategy System
"""

import os
import sys
import subprocess
import time
import asyncio
from pathlib import Path

def install_requirements():
    """Установка зависимостей"""
    print("📦 Установка зависимостей...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ Зависимости установлены успешно!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка установки зависимостей: {e}")
        sys.exit(1)

def setup_database():
    """Инициализация базы данных"""
    print("🗄️ Инициализация базы данных...")
    try:
        sys.path.append('backend')
        from backend.models import create_database, get_db_session, StrategySettings, VirtualAccount
        
        # Создаем базу данных
        create_database()
        
        # Создаем настройки по умолчанию для всех символов
        symbols = ["SBER", "GAZP", "LKOH", "VTBR"]
        db = get_db_session()
        
        try:
            # Проверяем виртуальный счет
            account = db.query(VirtualAccount).first()
            if not account:
                account = VirtualAccount(
                    initial_balance=100000.0,
                    current_balance=100000.0,
                    max_balance=100000.0
                )
                db.add(account)
                print("💳 Создан виртуальный счет с балансом 100,000 ₽")
            
            # Создаем настройки стратегий
            for symbol in symbols:
                settings = db.query(StrategySettings).filter(StrategySettings.symbol == symbol).first()
                if not settings:
                    settings = StrategySettings(symbol=symbol)
                    db.add(settings)
                    print(f"⚙️ Созданы настройки для {symbol}")
            
            db.commit()
            print("✅ База данных инициализирована!")
            
        finally:
            db.close()
            
    except Exception as e:
        print(f"❌ Ошибка инициализации БД: {e}")
        sys.exit(1)

def test_moex_connection():
    """Тестирование подключения к MOEX"""
    print("🌐 Тестирование подключения к MOEX...")
    try:
        sys.path.append('backend')
        from backend.moex_api import get_moex_data
        
        # Тестируем получение данных
        test_symbols = ["SBER"]
        data = get_moex_data(test_symbols)
        
        if "SBER" in data and data["SBER"].get("current_price"):
            print(f"✅ MOEX API работает! Цена SBER: {data['SBER']['current_price']:.2f} ₽")
        else:
            print("⚠️ MOEX API отвечает, но данные могут быть неполными")
            
    except Exception as e:
        print(f"❌ Ошибка подключения к MOEX: {e}")
        print("⚠️ Проверьте интернет-соединение")

def create_frontend_structure():
    """Создание структуры frontend"""
    frontend_dir = Path("frontend")
    frontend_dir.mkdir(exist_ok=True)
    
    print("✅ Структура frontend создана")

def start_server():
    """Запуск сервера"""
    print("🚀 Запуск сервера...")
    print("📊 Система будет доступна по адресу: http://localhost:8000")
    print("📚 API документация: http://localhost:8000/docs")
    print("🎮 Веб-интерфейс: http://localhost:8000")
    print("\n" + "="*50)
    print("Нажмите Ctrl+C для остановки сервера")
    print("="*50 + "\n")
    
    try:
        os.chdir("backend")
        subprocess.run([sys.executable, "main.py"])
    except KeyboardInterrupt:
        print("\n👋 Сервер остановлен")
    except Exception as e:
        print(f"❌ Ошибка запуска сервера: {e}")

def main():
    """Основная функция"""
    print("🏦 Financial Potential Strategy System")
    print("="*50)
    
    # Проверяем структуру проекта
    required_dirs = ["backend", "frontend"]
    for dir_name in required_dirs:
        if not Path(dir_name).exists():
            print(f"❌ Отсутствует директория: {dir_name}")
            sys.exit(1)
    
    # Устанавливаем зависимости
    if not Path("requirements.txt").exists():
        print("❌ Отсутствует файл requirements.txt")
        sys.exit(1)
    
    # Проверяем, нужно ли устанавливать зависимости
    try:
        import fastapi, uvicorn, pandas, numpy, sqlalchemy, requests, ta
        print("✅ Основные зависимости уже установлены")
    except ImportError:
        install_requirements()
    
    # Создаем структуру
    create_frontend_structure()
    
    # Инициализируем базу данных
    setup_database()
    
    # Тестируем MOEX
    test_moex_connection()
    
    # Запускаем сервер
    start_server()

if __name__ == "__main__":
    main()
