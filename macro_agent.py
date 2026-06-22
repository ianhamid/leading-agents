#!/usr/bin/env python3
"""Leading Macro Agent: Scheduled Tier updates at fixed times (SGT)"""

import os, sys, logging, yfinance as yf
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

try:
    from telegram import Update
    from telegram.ext import Application, ContextTypes, MessageHandler, filters
    from apscheduler.schedulers.background import BackgroundScheduler
except ImportError:
    print("❌ Missing dependencies. Install: pip install python-telegram-bot apscheduler")
    sys.exit(1)

STATE_DIR = Path.home() / '.leading'
STATE_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(STATE_DIR / 'macro_agent.log'), logging.StreamHandler()])
logger = logging.getLogger(__name__)

class MacroFetcher:
    TICKERS = {
        'nikkei': '^N225',
        'oil': 'CL=F',
        'dxy': 'UUP',
        'vix': '^VIX',
        'sp500': '^GSPC',
        'gold': 'GC=F',
        'silver': 'SI=F',
    }
    
    @staticmethod
    def fetch_all() -> Dict:
        data = {}
        for name, ticker in MacroFetcher.TICKERS.items():
            try:
                hist = yf.Ticker(ticker).history(period='5d')
                if not hist.empty:
                    current = hist['Close'].iloc[-1]
                    prev = hist['Close'].iloc[-2] if len(hist) > 1 else current
                    change_pct = ((current - prev) / prev) * 100 if prev else 0
                    data[name] = {'price': current, 'change': change_pct}
            except Exception as e:
                logger.error(f"Error fetching {name}: {e}")
        return data

async def send_tier1(application: Application):
    """TIER 1: 09:00 AM SGT - Nikkei, Oil, DXY"""
    data = MacroFetcher.fetch_all()
    msg = f"""✅ *TIER 1: All clear*

Nikkei: {data.get('nikkei', {}).get('price', 0):.2f} ({data.get('nikkei', {}).get('change', 0):+.2f}%)
Oil (CL=F): {data.get('oil', {}).get('price', 0):.2f} ({data.get('oil', {}).get('change', 0):+.2f}%)
DXY (UUP): {data.get('dxy', {}).get('price', 0):.2f} ({data.get('dxy', {}).get('change', 0):+.2f}%)

🕐 Check Time: {datetime.now().__format__('%Y-%m-%d %H:%M:%S SGT')}"""
    
    chat_id = os.getenv('LEADING_TELEGRAM_CHAT_ID')
    if chat_id:
        try:
            await application.bot.send_message(chat_id=int(chat_id), text=msg, parse_mode='Markdown')
            logger.info("TIER 1 sent")
        except Exception as e:
            logger.error(f"Error sending TIER 1: {e}")

async def send_tier2(application: Application):
    """TIER 2: 10:00 AM SGT - VIX, S&P 500, HY OAS"""
    data = MacroFetcher.fetch_all()
    msg = f"""✅ *TIER 2: Market structure*

VIX: {data.get('vix', {}).get('price', 0):.2f} ({data.get('vix', {}).get('change', 0):+.2f}%)
S&P 500: {data.get('sp500', {}).get('price', 0):.2f} ({data.get('sp500', {}).get('change', 0):+.2f}%)

🕐 Check Time: {datetime.now().__format__('%Y-%m-%d %H:%M:%S SGT')}"""
    
    chat_id = os.getenv('LEADING_TELEGRAM_CHAT_ID')
    if chat_id:
        try:
            await application.bot.send_message(chat_id=int(chat_id), text=msg, parse_mode='Markdown')
            logger.info("TIER 2 sent")
        except Exception as e:
            logger.error(f"Error sending TIER 2: {e}")

async def send_tier3(application: Application):
    """TIER 3: 12:30 PM SGT - Gold, Silver confirmation"""
    data = MacroFetcher.fetch_all()
    msg = f"""✅ *TIER 3: Confirmation*

Gold (GC=F): {data.get('gold', {}).get('price', 0):.2f} ({data.get('gold', {}).get('change', 0):+.2f}%)
Silver (SI=F): {data.get('silver', {}).get('price', 0):.2f} ({data.get('silver', {}).get('change', 0):+.2f}%)

🕐 Check Time: {datetime.now().__format__('%Y-%m-%d %H:%M:%S SGT')}"""
    
    chat_id = os.getenv('LEADING_TELEGRAM_CHAT_ID')
    if chat_id:
        try:
            await application.bot.send_message(chat_id=int(chat_id), text=msg, parse_mode='Markdown')
            logger.info("TIER 3 sent")
        except Exception as e:
            logger.error(f"Error sending TIER 3: {e}")

def schedule_tasks(application: Application):
    """Schedule Tier updates at specific times (SGT)"""
    scheduler = BackgroundScheduler()
    
    # TIER 1: 09:00 AM SGT
    scheduler.add_job(send_tier1, 'cron', hour=9, minute=0, args=(application,), timezone='Asia/Singapore')
    
    # TIER 2: 10:00 AM SGT
    scheduler.add_job(send_tier2, 'cron', hour=10, minute=0, args=(application,), timezone='Asia/Singapore')
    
    # TIER 3: 12:30 PM SGT
    scheduler.add_job(send_tier3, 'cron', hour=12, minute=30, args=(application,), timezone='Asia/Singapore')
    
    scheduler.start()
    logger.info("Scheduler started: TIER 1 (09:00), TIER 2 (10:00), TIER 3 (12:30) SGT")

def main():
    token = os.getenv('LEADING_TELEGRAM_TOKEN')
    if not token:
        print("❌ Missing LEADING_TELEGRAM_TOKEN")
        sys.exit(1)
    
    print("\n" + "="*70)
    print("LEADING MACRO AGENT: Scheduled Tier Updates")
    print("="*70)
    print("TIER 1: 09:00 AM SGT (Nikkei, Oil, DXY)")
    print("TIER 2: 10:00 AM SGT (VIX, S&P 500)")
    print("TIER 3: 12:30 PM SGT (Gold, Silver)\n")
    
    application = Application.builder().token(token).build()
    schedule_tasks(application)
    application.run_polling()

if __name__ == '__main__':
    main()
