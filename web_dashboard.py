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

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Revushiy Kotenok Dashboard")

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
async def dashboard(request: Request, year: Optional[int] = None, month: Optional[int] = None):
    """Главная страница дашборда"""
    
    # Если месяц не указан, берем текущий
    if year is None or month is None:
        now = datetime.now()
        year = now.year
        month = now.month
    
    try:
        # Получаем данные из БД
        monthly_stats = await db.get_global_monthly_statistics(year, month)
        open_positions = await db.get_all_open_positions_web()
        closed_positions = await db.get_all_closed_positions_web(limit=50)
        ticker_stats = await db.get_statistics_by_ticker()
        best_worst = await db.get_best_and_worst_trades()
        avg_duration = await db.get_average_trade_duration()
        
        # Форматируем средюю продолжительность
        if avg_duration:
            if avg_duration < 24:
                avg_duration_str = f"{avg_duration:.1f} часов"
            else:
                avg_duration_str = f"{avg_duration / 24:.1f} дней"
        else:
            avg_duration_str = "Н/Д"
        
        # Добавляем имена и эмодзи к акциям
        for pos in open_positions:
            ticker = pos['ticker']
            pos['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            pos['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
        
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
        
        for stat in ticker_stats:
            ticker = stat['ticker']
            stat['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            stat['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
        
        # Добавляем имена к лучшей/худшей сделке
        if best_worst['best']:
            ticker = best_worst['best']['ticker']
            best_worst['best']['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            best_worst['best']['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
        
        if best_worst['worst']:
            ticker = best_worst['worst']['ticker']
            best_worst['worst']['stock_name'] = SUPPORTED_STOCKS.get(ticker, {}).get('name', ticker)
            best_worst['worst']['stock_emoji'] = SUPPORTED_STOCKS.get(ticker, {}).get('emoji', '📊')
        
        # Формируем список месяцев для селектора (последние 12 месяцев)
        months_list = []
        current_date = datetime.now()
        for i in range(12):
            date = datetime(current_date.year, current_date.month, 1)
            # Вычитаем i месяцев
            month_num = date.month - i
            year_num = date.year
            while month_num <= 0:
                month_num += 12
                year_num -= 1
            
            months_list.append({
                'year': year_num,
                'month': month_num,
                'label': datetime(year_num, month_num, 1).strftime("%B %Y")
            })
        
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "year": year,
                "month": month,
                "month_name": datetime(year, month, 1).strftime("%B %Y"),
                "months_list": months_list,
                "monthly_stats": monthly_stats,
                "open_positions": open_positions,
                "closed_positions": closed_positions,
                "ticker_stats": ticker_stats,
                "best_trade": best_worst['best'],
                "worst_trade": best_worst['worst'],
                "avg_duration": avg_duration_str
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


if __name__ == "__main__":
    uvicorn.run(
        "web_dashboard:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )
