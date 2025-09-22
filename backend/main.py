from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import json
import uvicorn
from contextlib import asynccontextmanager

from models import (
    create_database, get_db_session, StrategySettings, VirtualAccount,
    StrategySettingsRequest, StrategySettingsResponse, VirtualTradeResponse,
    AccountResponse, MarketDataResponse, StrategySignal
)
from moex_api import get_moex_data, MOEXClient
from strategy import FinancialPotentialStrategy
from virtual_trading import VirtualTradingEngine, StrategyManager

# Глобальные переменные
symbols = ["SBER", "GAZP", "LKOH", "VTBR"]
strategy_manager = None
latest_market_data = {}
is_trading_active = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    global strategy_manager
    
    # Startup
    try:
        # Создаем базу данных
        print("🔗 Подключение к базе данных...")
        create_database()
        print("✅ База данных готова")
        
        # Инициализируем виртуальный счет и настройки
        db = get_db_session()
        try:
            # Создаем виртуальные счета для каждого символа
            accounts_created = 0
            for symbol in symbols:
                account = db.query(VirtualAccount).filter(VirtualAccount.symbol == symbol).first()
                if not account:
                    account = VirtualAccount(
                        symbol=symbol,
                        initial_balance=100000.0,
                        current_balance=100000.0,
                        max_balance=100000.0
                    )
                    db.add(account)
                    accounts_created += 1
                    print(f"💳 Создан виртуальный счет для {symbol}")
                else:
                    print(f"💳 Счет {symbol}: {account.current_balance:,.0f} ₽")
            
            if accounts_created == 0:
                print("💳 Виртуальные счета уже существуют")
            
            # Создаем настройки стратегий
            settings_created = 0
            for symbol in symbols:
                settings = db.query(StrategySettings).filter(StrategySettings.symbol == symbol).first()
                if not settings:
                    settings = StrategySettings(symbol=symbol)
                    db.add(settings)
                    settings_created += 1
                    print(f"⚙️ Созданы настройки для {symbol}")
            
            if settings_created == 0:
                print("⚙️ Настройки стратегий уже существуют")
            
            db.commit()
            print("✅ Настройки инициализированы")
            
        except Exception as db_error:
            print(f"❌ Ошибка работы с БД: {db_error}")
            db.rollback()
        finally:
            db.close()
        
        # Инициализируем менеджер стратегий
        strategy_manager = StrategyManager()
        print("✅ Менеджер стратегий готов")
        
        # Запускаем фоновую задачу обновления данных
        asyncio.create_task(market_data_updater())
        
        print("🚀 Financial Potential Strategy API запущен!")
        print(f"📊 Отслеживаемые символы: {', '.join(symbols)}")
        
    except Exception as e:
        print(f"❌ Критическая ошибка инициализации: {e}")
        print("⚠️ Система запущена в ограниченном режиме")
        # Продолжаем работу, но без полной функциональности
    
    yield
    
    # Shutdown
    print("👋 Завершение работы Financial Potential Strategy API")

# Создание приложения с lifespan
app = FastAPI(
    title="Financial Potential Strategy API",
    description="API для тестирования стратегии Financial Potential на данных MOEX",
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Статические файлы
import os
from pathlib import Path

# Определяем путь к frontend
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

async def market_data_updater():
    """Фоновая задача для обновления рыночных данных"""
    global latest_market_data, is_trading_active
    
    while True:
        try:
            if is_trading_active:
                print("📡 Обновление рыночных данных...")
                
                # Получаем данные MOEX асинхронно
                from moex_api import get_moex_data_async
                market_data = await get_moex_data_async(symbols)
                latest_market_data = market_data
                
                # Анализируем рынок и генерируем сигналы
                signals = strategy_manager.analyze_market(market_data)
                
                if signals:
                    print(f"🎯 Получены сигналы: {len(signals)}")
                    for signal in signals:
                        print(f"   {signal.symbol}: {signal.direction} (confidence: {signal.confidence:.2f})")
                    
                    # Обрабатываем сигналы
                    results = strategy_manager.process_signals(signals)
                    if results:
                        print(f"💰 Размещено ордеров: {len(results)}")
                
                # Обновляем существующие сделки
                update_results = strategy_manager.trading_engine.update_trades(market_data)
                if update_results:
                    print(f"🔄 Обновлены сделки: {len(update_results)}")
                
        except Exception as e:
            print(f"❌ Ошибка обновления данных: {e}")
        
        # Ждем 1 минуту перед следующим обновлением
        await asyncio.sleep(60)

# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Главная страница - веб-интерфейс"""
    frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
    
    if frontend_path.exists():
        try:
            with open(frontend_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"Ошибка чтения frontend/index.html: {e}")
    
    # Fallback если файл не найден
    return """
    <html>
        <head>
            <title>Financial Potential Strategy</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                .header { background: #2196F3; color: white; padding: 20px; border-radius: 10px; }
                .status { margin: 20px 0; }
                .endpoint { background: #f5f5f5; padding: 10px; margin: 10px 0; border-radius: 5px; }
                .error { color: #ff6b6b; margin: 20px 0; padding: 15px; background: #ffe6e6; border-radius: 8px; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🚀 Financial Potential Strategy API v2.0</h1>
                <p>Тестирование торговой стратегии на реальных данных MOEX</p>
            </div>
            
            <div class="error">
                <h3>⚠️ Веб-интерфейс временно недоступен</h3>
                <p>Файл frontend/index.html не найден. Используйте API endpoints:</p>
            </div>
            
            <div class="status">
                <h2>📊 Статус системы</h2>
                <p><strong>Отслеживаемые инструменты:</strong> SBER, GAZP, LKOH, VTBR</p>
                <p><strong>Документация API:</strong> <a href="/docs">/docs</a></p>
                <p><strong>Интерактивная документация:</strong> <a href="/redoc">/redoc</a></p>
            </div>
            
            <div class="endpoints">
                <h2>🔗 Основные эндпоинты</h2>
                <div class="endpoint">GET /market-data - Текущие рыночные данные</div>
                <div class="endpoint">GET /account/statistics - Статистика торгового счета</div>
                <div class="endpoint">GET /trades/history - История сделок</div>
                <div class="endpoint">POST /settings/{symbol} - Настройка стратегии для символа</div>
                <div class="endpoint">POST /api/trading/start - Запуск автоматической торговли</div>
                <div class="endpoint">POST /api/trading/stop - Остановка торговли</div>
            </div>
            
            <div style="margin-top: 30px; padding: 15px; background: #e3f2fd; border-radius: 8px;">
                <h3>🛠️ Для разработчиков</h3>
                <p>Убедитесь, что файл <code>frontend/index.html</code> находится в правильной директории проекта.</p>
            </div>
        </body>
    </html>
    """

# Эндпоинты без префикса /api (для совместимости с frontend)
@app.get("/market-data", response_model=Dict[str, MarketDataResponse])
async def get_market_data_compat():
    """Получение текущих рыночных данных (совместимость)"""
    return await get_market_data()

@app.get("/account/statistics")
async def get_account_statistics_compat():
    """Получение статистики всех торговых счетов (совместимость)"""
    return await get_account_statistics()

@app.get("/trades/history")
async def get_trade_history_compat(symbol: Optional[str] = None, limit: int = 50):
    """Получение истории сделок (совместимость)"""
    return await get_trade_history(symbol, limit)

@app.get("/logs")
async def get_logs_compat(limit: int = 100):
    """Получение логов событий (совместимость)"""
    return await get_logs(limit)

@app.get("/settings/{symbol}", response_model=StrategySettingsResponse)
async def get_strategy_settings_compat(symbol: str):
    """Получение настроек стратегии для символа (совместимость)"""
    return await get_strategy_settings(symbol)

@app.post("/settings/{symbol}", response_model=StrategySettingsResponse)
async def update_strategy_settings_compat(symbol: str, settings_request: StrategySettingsRequest):
    """Обновление настроек стратегии для символа (совместимость)"""
    return await update_strategy_settings(symbol, settings_request)

# НОВЫЙ ЭНДПОИНТ для статуса торговли
@app.get("/api/trading/status")
async def get_trading_status():
    """Получение статуса торговли"""
    global is_trading_active
    return {
        "active": is_trading_active,
        "status": "ACTIVE" if is_trading_active else "STOPPED",
        "timestamp": datetime.now().isoformat()
    }

# Основные API эндпоинты
@app.get("/api/market-data", response_model=Dict[str, MarketDataResponse])
async def get_market_data():
    """Получение текущих рыночных данных"""
    global latest_market_data
    
    if not latest_market_data:
        # Если данных нет, получаем их асинхронно
        from moex_api import get_moex_data_async
        latest_market_data = await get_moex_data_async(symbols)
    
    result = {}
    for symbol, data in latest_market_data.items():
        result[symbol] = MarketDataResponse(
            symbol=symbol,
            current_price=data.get('current_price'),
            bid=data.get('current_price'),
            ask=data.get('current_price'),
            volume=None,
            last_update=data.get('last_update', datetime.now().isoformat())
        )
    
    return result

@app.get("/api/account/statistics")
async def get_account_statistics():
    """Получение статистики всех торговых счетов"""
    if not strategy_manager:
        raise HTTPException(status_code=503, detail="Strategy manager not initialized")
    
    return strategy_manager.trading_engine.get_account_statistics()

@app.get("/api/account/{symbol}/statistics")
async def get_symbol_account_statistics(symbol: str):
    """Получение статистики торгового счета для конкретного символа"""
    if symbol not in symbols:
        raise HTTPException(status_code=404, detail="Symbol not found")
    
    if not strategy_manager:
        raise HTTPException(status_code=503, detail="Strategy manager not initialized")
    
    return strategy_manager.trading_engine.get_account_statistics(symbol)

@app.post("/api/account/reset")
async def reset_all_accounts():
    """Сброс всех виртуальных счетов"""
    if not strategy_manager:
        raise HTTPException(status_code=503, detail="Strategy manager not initialized")
    
    strategy_manager.trading_engine.reset_account()
    return {"status": "All accounts reset successfully"}

@app.get("/api/trades/history")
async def get_trade_history(symbol: Optional[str] = None, limit: int = 50):
    """Получение истории сделок"""
    if not strategy_manager:
        raise HTTPException(status_code=503, detail="Strategy manager not initialized")
    
    return strategy_manager.trading_engine.get_trade_history(symbol, limit)

@app.get("/api/settings/{symbol}", response_model=StrategySettingsResponse)
async def get_strategy_settings(symbol: str):
    """Получение настроек стратегии для символа"""
    if symbol not in symbols:
        raise HTTPException(status_code=404, detail="Symbol not found")
    
    db = get_db_session()
    try:
        settings = db.query(StrategySettings).filter(StrategySettings.symbol == symbol).first()
        if not settings:
            raise HTTPException(status_code=404, detail="Settings not found")
        return settings
    finally:
        db.close()

@app.post("/api/settings/{symbol}", response_model=StrategySettingsResponse)
async def update_strategy_settings(symbol: str, settings_request: StrategySettingsRequest):
    """Обновление настроек стратегии для символа"""
    if symbol not in symbols:
        raise HTTPException(status_code=404, detail="Symbol not found")
    
    print(f"🔧 Обновление настроек для {symbol}")
    print(f"📥 Получены данные: {settings_request.dict()}")
    
    db = get_db_session()
    try:
        settings = db.query(StrategySettings).filter(StrategySettings.symbol == symbol).first()
        
        if not settings:
            print(f"➕ Создание новых настроек для {symbol}")
            settings = StrategySettings(symbol=symbol)
            db.add(settings)
        else:
            print(f"✏️ Обновление существующих настроек для {symbol}")
        
        # Обновляем настройки
        update_data = settings_request.dict()
        updated_fields = []
        
        for field, value in update_data.items():
            if field != 'symbol' and hasattr(settings, field):
                old_value = getattr(settings, field)
                setattr(settings, field, value)
                if old_value != value:
                    updated_fields.append(f"{field}: {old_value} → {value}")
        
        if updated_fields:
            print(f"🔄 Обновленные поля: {', '.join(updated_fields)}")
        else:
            print("ℹ️ Нет изменений в настройках")
        
        settings.updated_at = datetime.utcnow()
        
        try:
            db.commit()
            print(f"✅ Настройки для {symbol} сохранены в БД")
        except Exception as commit_error:
            print(f"❌ Ошибка сохранения в БД: {commit_error}")
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Database error: {commit_error}")
        
        db.refresh(settings)
        
        # Обновляем стратегию в менеджере
        global strategy_manager
        if strategy_manager:
            strategy_manager.strategies[symbol] = FinancialPotentialStrategy(settings)
            print(f"🔄 Стратегия для {symbol} обновлена в менеджере")
        
        return settings
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Ошибка обновления настроек: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating settings: {e}")
    finally:
        db.close()

@app.post("/api/trading/start")
async def start_trading():
    """Запуск автоматической торговли"""
    global is_trading_active
    is_trading_active = True
    
    # Логируем событие
    if strategy_manager:
        strategy_manager.trading_engine.log_event("TRADING_STARTED", "Автоматическая торговля запущена")
    
    return {"status": "Trading started", "active": is_trading_active}

@app.post("/api/trading/stop")
async def stop_trading():
    """Остановка автоматической торговли"""
    global is_trading_active
    is_trading_active = False
    
    # Логируем событие
    if strategy_manager:
        strategy_manager.trading_engine.log_event("TRADING_STOPPED", "Автоматическая торговля остановлена")
    
    return {"status": "Trading stopped", "active": is_trading_active}

@app.get("/api/signals/{symbol}")
async def get_current_signal(symbol: str):
    """Получение текущего сигнала для символа"""
    if symbol not in symbols:
        raise HTTPException(status_code=404, detail="Symbol not found")
    
    if not strategy_manager:
        raise HTTPException(status_code=503, detail="Strategy manager not initialized")
    
    # Пытаемся получить свежие данные
    try:
        if symbol not in latest_market_data or not latest_market_data[symbol].get('current_price'):
            print(f"🔄 Получение свежих данных для {symbol}...")
            from moex_api import get_moex_data_async
            fresh_data = await get_moex_data_async([symbol])
            if symbol in fresh_data:
                latest_market_data[symbol] = fresh_data[symbol]
        
        data = latest_market_data.get(symbol, {})
        
        # Проверяем наличие данных более гибко
        candles = data.get('candles')
        current_price = data.get('current_price')
        
        if current_price is None:
            # Возвращаем пустой сигнал вместо ошибки
            return {
                "symbol": symbol,
                "direction": "NONE",
                "confidence": 0.0,
                "entry_price": 0.0,
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "lot_size": 0.0,
                "indicators": {
                    "h_fin": 0.0,
                    "rsi": 50.0,
                    "v_level": 0.0,
                    "v_trend": 0.0,
                    "v_rsi": 0.0,
                    "v_total": 0.0
                },
                "timestamp": datetime.now().isoformat(),
                "status": "no_price_data"
            }
        
        # Проверяем наличие свечей
        if candles is None or (hasattr(candles, 'empty') and candles.empty) or len(candles) < 10:
            # Возвращаем базовый сигнал только с ценой
            return {
                "symbol": symbol,
                "direction": "NONE",
                "confidence": 0.0,
                "entry_price": current_price,
                "stop_loss": current_price,
                "take_profit": current_price,
                "lot_size": 0.0,
                "indicators": {
                    "h_fin": 0.0,
                    "rsi": 50.0,
                    "v_level": 0.0,
                    "v_trend": 0.0,
                    "v_rsi": 0.0,
                    "v_total": 0.0
                },
                "timestamp": datetime.now().isoformat(),
                "status": "insufficient_candles"
            }
        
        # Генерируем сигнал
        strategy = strategy_manager.strategies[symbol]
        signal = strategy.generate_signal(candles, current_price)
        
        return {
            "symbol": signal.symbol,
            "direction": signal.direction,
            "confidence": signal.confidence,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "lot_size": signal.lot_size,
            "indicators": {
                "h_fin": signal.h_fin,
                "rsi": signal.rsi,
                "v_level": signal.v_level,
                "v_trend": signal.v_trend,
                "v_rsi": signal.v_rsi,
                "v_total": signal.v_total
            },
            "timestamp": signal.timestamp.isoformat(),
            "status": "ok"
        }
        
    except Exception as e:
        print(f"❌ Ошибка генерации сигнала для {symbol}: {e}")
        # Возвращаем безопасный fallback сигнал
        return {
            "symbol": symbol,
            "direction": "NONE",
            "confidence": 0.0,
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "lot_size": 0.0,
            "indicators": {
                "h_fin": 0.0,
                "rsi": 50.0,
                "v_level": 0.0,
                "v_trend": 0.0,
                "v_rsi": 0.0,
                "v_total": 0.0
            },
            "timestamp": datetime.now().isoformat(),
            "status": "error",
            "error": str(e)
        }

@app.get("/api/levels/{symbol}")
async def get_levels(symbol: str):
    """Получение уровней поддержки/сопротивления для символа"""
    if symbol not in symbols:
        raise HTTPException(status_code=404, detail="Symbol not found")
    
    if not strategy_manager:
        raise HTTPException(status_code=503, detail="Strategy manager not initialized")
    
    strategy = strategy_manager.strategies[symbol]
    levels = strategy.get_levels_for_chart()
    
    return {
        "symbol": symbol,
        "levels": levels,
        "count": len(levels),
        "last_build": strategy.last_build_time.isoformat() if strategy.last_build_time else None
    }

@app.get("/api/logs")
async def get_logs(limit: int = 100):
    """Получение логов событий"""
    db = get_db_session()
    try:
        from models import StrategyLog
        logs = db.query(StrategyLog).order_by(StrategyLog.timestamp.desc()).limit(limit).all()
        
        return [{
            "id": log.id,
            "timestamp": log.timestamp.isoformat(),
            "symbol": log.symbol,
            "event_type": log.event_type,
            "message": log.message,
            "data": json.loads(log.data) if log.data else None
        } for log in logs]
        
    finally:
        db.close()

@app.post("/api/market-data/refresh")
async def refresh_market_data():
    """Принудительное обновление рыночных данных"""
    global latest_market_data
    
    try:
        print("🔄 Принудительное обновление рыночных данных...")
        from moex_api import get_moex_data_async
        fresh_data = await get_moex_data_async(symbols)
        
        if fresh_data:
            latest_market_data = fresh_data
            print(f"✅ Данные обновлены для {len(fresh_data)} символов")
            
            # Возвращаем статистику по обновлению
            result = {
                "status": "success",
                "updated_symbols": [],
                "failed_symbols": [],
                "timestamp": datetime.now().isoformat()
            }
            
            for symbol in symbols:
                if symbol in fresh_data and fresh_data[symbol].get('current_price'):
                    result["updated_symbols"].append({
                        "symbol": symbol,
                        "price": fresh_data[symbol]['current_price'],
                        "candles_count": len(fresh_data[symbol].get('candles', []))
                    })
                else:
                    result["failed_symbols"].append(symbol)
            
            return result
        else:
            return {
                "status": "failed",
                "message": "Не удалось получить данные MOEX",
                "timestamp": datetime.now().isoformat()
            }
            
    except Exception as e:
        print(f"❌ Ошибка обновления данных: {e}")
        return {
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat()
        }
    """Получение свечей для графика"""
    if symbol not in symbols:
        raise HTTPException(status_code=404, detail="Symbol not found")
    
    try:
        from moex_api import get_moex_candles_async
        df = await get_moex_candles_async(symbol, period, days)
        
        if df.empty:
            return {"symbol": symbol, "candles": []}
        
        candles = []
        for _, row in df.iterrows():
            candles.append({
                "datetime": row['datetime'].isoformat(),
                "open": float(row['open']),
                "high": float(row['high']),
                "low": float(row['low']),
                "close": float(row['close']),
                "volume": int(row['volume'])
            })
        
        return {
            "symbol": symbol,
            "period": period,
            "candles": candles,
            "count": len(candles)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching candles: {str(e)}")

# Для development
if __name__ == "__main__":
    print("🚀 Запуск Financial Potential Strategy API...")
    print("📊 Доступные символы: SBER, GAZP, LKOH, VTBR")
    print("🌐 API будет доступно по адресу: http://localhost:8000")
    print("📚 Документация: http://localhost:8000/docs")
    
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True,
        log_level="info"
    )
