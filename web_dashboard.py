import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn

from database import db
from config import SUPPORTED_STOCKS
from stock_service import StockService

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Revushiy Kotenok Dashboard")

# Фильтр по пользователю
TARGET_USERNAME = 'matve1ch'

# Дата начала торговли
TRADING_START_DATE = datetime(2025, 10, 1)

# Сервис для получения данных акций
stock_service = StockService()

# Подключаем статические файлы и шаблоны
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def startup():
    """Подключение к БД при старте"""
    await db.connect()
    logger.info("✅ Web Dashboard started")


@app.on_event("shutdown")
async def shutdown():
    """Отключение от БД при остановке"""
    await db.disconnect()
    logger.info("👋 Web Dashboard stopped")


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request, 
    year: Optional[int] = None, 
    month: Optional[int] = None,
    ticker_year: Optional[int] = None,
    ticker_month: Optional[int] = None,
    feed_type: Optional[str] = None
):
    """Главная страница дашборда"""
    
    # Если месяц не указан, берем текущий
    if year is None or month is None:
        now = datetime.now()
        year = now.year
        month = now.month
    
    try:
        # Получаем общую статистику за месяц (без фильтра по типу)
        monthly_stats_all = await db.get_global_monthly_statistics(year, month, username=TARGET_USERNAME)
        
        open_positions = await db.get_all_open_positions_web(username=TARGET_USERNAME)
        
        # Статистика по акциям с фильтром по месяцу
        if ticker_year and ticker_month:
            ticker_stats_all = await db.get_statistics_by_ticker_filtered(
                username=TARGET_USERNAME, 
                year=ticker_year, 
                month=ticker_month
            )
            ticker_filter_label = datetime(ticker_year, ticker_month, 1).strftime("%B %Y")
        else:
            ticker_stats_all = await db.get_statistics_by_ticker(username=TARGET_USERNAME)
            ticker_filter_label = "за всё время"
        
        # Лента сделок - последние 50 с фильтром по типу
        if feed_type and feed_type != 'all':
            closed_positions = await db.get_all_closed_positions_web(
                limit=50, 
                username=TARGET_USERNAME,
                position_type=feed_type
            )
        else:
            closed_positions = await db.get_all_closed_positions_web(
                limit=50, 
                username=TARGET_USERNAME
            )
        
        # Для раздела "Дополнительно" показываем общую статистику (без фильтра по username)
        best_worst_all = await db.get_best_and_worst_trades()
        avg_duration_all = await db.get_average_trade_duration()
        
        # Форматируем среднюю продолжительность
        def format_duration(avg_duration):
            if avg_duration:
                if avg_duration < 24:
                    return f"{avg_duration:.1f} часов"
                else:
                    return f"{avg_duration / 24:.1f} дней"
            else:
                return "Н/Д"
        
        avg_duration_str_all = format_duration(avg_duration_all)
        
        # Добавляем имена и эмодзи к акциям
        for pos in open_positions:
            ticker = pos['ticker']
            pos['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            pos['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
            
            # Получаем текущую цену
            try:
                stock_data = await stock_service.get_stock_data(ticker)
                if stock_data:
                    pos['current_price'] = stock_data.price.current_price
                    # Рассчитываем текущую прибыль с учетом типа позиции
                    entry_price = float(pos['entry_price'])
                    position_type = pos['position_type']
                    
                    if position_type == 'LONG':
                        current_profit = ((pos['current_price'] - entry_price) / entry_price) * 100
                    else:  # SHORT
                        current_profit = ((entry_price - pos['current_price']) / entry_price) * 100
                    
                    pos['current_profit'] = current_profit
                else:
                    pos['current_price'] = None
                    pos['current_profit'] = None
            except Exception as e:
                logger.error(f"Error getting current price for {ticker}: {e}")
                pos['current_price'] = None
                pos['current_profit'] = None
        
        for pos in closed_positions:
            ticker = pos['ticker']
            pos['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            pos['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
            # Вычисляем продолжительность сделки
            duration = pos['exit_time'] - pos['entry_time']
            duration_hours = duration.total_seconds() / 3600
            if duration_hours < 24:
                pos['duration_str'] = f"{duration_hours:.1f}ч"
            else:
                pos['duration_str'] = f"{duration_hours / 24:.1f}д"
        
        for stat in ticker_stats_all:
            ticker = stat['ticker']
            stat['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            stat['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
        
        # Добавляем имена к лучшей/худшей сделке
        if best_worst_all['best']:
            ticker = best_worst_all['best']['ticker']
            best_worst_all['best']['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            best_worst_all['best']['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
        
        if best_worst_all['worst']:
            ticker = best_worst_all['worst']['ticker']
            best_worst_all['worst']['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            best_worst_all['worst']['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
        
        # Формируем список месяцев (с октября 2025 до текущего месяца)
        months_list = []
        current_date = datetime.now()
        
        # Начинаем с текущего месяца и идём назад до октября 2025
        temp_date = datetime(current_date.year, current_date.month, 1)
        
        while temp_date >= TRADING_START_DATE:
            months_list.append({
                'year': temp_date.year,
                'month': temp_date.month,
                'label': temp_date.strftime("%B %Y")
            })
            
            # Переходим к предыдущему месяцу
            if temp_date.month == 1:
                temp_date = datetime(temp_date.year - 1, 12, 1)
            else:
                temp_date = datetime(temp_date.year, temp_date.month - 1, 1)
        
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "year": year,
                "month": month,
                "month_name": datetime(year, month, 1).strftime("%B %Y"),
                "months_list": months_list,
                "monthly_stats_all": monthly_stats_all,
                "open_positions": open_positions,
                "closed_positions": closed_positions,
                "ticker_stats_all": ticker_stats_all,
                "ticker_filter_label": ticker_filter_label,
                "ticker_year": ticker_year,
                "ticker_month": ticker_month,
                "feed_type": feed_type or 'all'
            }
        )
    
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}", exc_info=True)
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "error": str(e)
            }
        )


@app.get("/health")
async def health_check():
    """Health check endpoint для Railway"""
    return {"status": "ok"}


@app.get("/top-trades", response_class=HTMLResponse)
async def top_trades(request: Request, type: str = "best", position_type: str = None):
    """Страница топ-10 лучших или худших сделок"""
    try:
        is_best = type == "best"
        trades = await db.get_top_trades(username=TARGET_USERNAME, limit=10, best=is_best, position_type=position_type)
        
        # Добавляем имена и эмодзи
        for trade in trades:
            ticker = trade['ticker']
            trade['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            trade['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
        
        # Формируем заголовок
        if position_type == 'LONG':
            title_suffix = " (LONG)"
        elif position_type == 'SHORT':
            title_suffix = " (SHORT)"
        else:
            title_suffix = ""
        
        title = f"🏆 Топ-10 лучших сделок{title_suffix}" if is_best else f"📉 Топ-10 худших сделок{title_suffix}"
        
        return templates.TemplateResponse(
            "top_trades.html",
            {
                "request": request,
                "title": title,
                "trades": trades,
                "is_best": is_best
            }
        )
    
    except Exception as e:
        logger.error(f"Error loading top trades: {e}", exc_info=True)
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "error": str(e)
            }
        )


if __name__ == "__main__":
    uvicorn.run(
        "web_dashboard:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )
