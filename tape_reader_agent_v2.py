#!/usr/bin/env python3
"""
Tape Reader Agent V2: Clean formatting - minimal output, bold headers only
"""

import os, sys, logging, yfinance as yf
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass

try:
    from telegram import Update
    from telegram.ext import Application, ContextTypes, MessageHandler, filters
except ImportError:
    print("❌ Missing python-telegram-bot. Install: pip install python-telegram-bot")
    sys.exit(1)

STATE_DIR = Path.home() / '.leading'
STATE_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(STATE_DIR / 'tape_reader_v2.log'), logging.StreamHandler()])
logger = logging.getLogger(__name__)

@dataclass
class MarketData:
    current: float
    prev_close: float
    week_52_high: float
    week_52_low: float
    daily_closes: list
    daily_highs: list
    daily_lows: list
    daily_volumes: list
    
    @property
    def support(self) -> float:
        return min(self.daily_lows) if self.daily_lows else self.current * 0.95
    
    @property
    def resistance(self) -> float:
        return max(self.daily_highs) if self.daily_highs else self.current * 1.05
    
    @property
    def pct_change(self) -> float:
        return ((self.current - self.prev_close) / self.prev_close) * 100 if self.prev_close else 0
    
    @property
    def distance_high(self) -> float:
        return ((self.current - self.week_52_high) / self.week_52_high) * 100
    
    @property
    def distance_low(self) -> float:
        return ((self.current - self.week_52_low) / self.week_52_low) * 100

class DataFetcher:
    TICKER_MAP = {
        'btc': 'BTC-USD', 'bitcoin': 'BTC-USD', 'oil': 'CL=F',
        'nikkei': '^N225', 'dxy': 'UUP', 'vix': '^VIX', 'sp500': '^GSPC',
        'aapl': 'AAPL', 'msft': 'MSFT', 'nvda': 'NVDA', 'tsla': 'TSLA',
        'gld': 'GLD', 'uso': 'USO', 'uup': 'UUP',
    }
    
    @staticmethod
    def fetch(ticker: str) -> Optional[MarketData]:
        try:
            if ticker.lower() in ['gold', 'spot_gold']:
                yf_ticker = 'GC=F'
            elif ticker.lower() in ['silver', 'spot_silver']:
                yf_ticker = 'SI=F'
            else:
                yf_ticker = DataFetcher.TICKER_MAP.get(ticker.lower())
            
            if not yf_ticker:
                return None
            
            data = yf.Ticker(yf_ticker)
            hist_1y = data.history(period='1y')
            if hist_1y.empty:
                return None
            
            week_52_high = hist_1y['High'].max()
            week_52_low = hist_1y['Low'].min()
            
            daily_data = hist_1y.tail(5)
            daily_closes = daily_data['Close'].tolist()
            daily_highs = daily_data['High'].tolist()
            daily_lows = daily_data['Low'].tolist()
            daily_volumes = daily_data['Volume'].tolist() if 'Volume' in daily_data.columns else [1000000]*5
            
            current = daily_closes[-1] if daily_closes else None
            prev_close = daily_closes[-2] if len(daily_closes) > 1 else current
            
            return MarketData(
                current=current, prev_close=prev_close,
                week_52_high=week_52_high, week_52_low=week_52_low,
                daily_closes=daily_closes, daily_highs=daily_highs,
                daily_lows=daily_lows, daily_volumes=daily_volumes,
            )
        except Exception as e:
            logger.error(f"Error: {e}")
            return None

class Analyzer:
    @staticmethod
    def analyze(data: MarketData) -> Dict:
        distance_high = data.distance_high
        distance_low = data.distance_low
        
        if distance_high > distance_low:
            bias = "BULLISH"
        elif distance_low > distance_high:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"
        
        support = data.support
        resistance = data.resistance
        range_size = resistance - support
        position = (data.current - support) / range_size if range_size > 0 else 0.5
        
        if position < 0.3:
            location = "NEAR SUPPORT"
        elif position > 0.7:
            location = "NEAR RESISTANCE"
        else:
            location = "IN MIDDLE"
        
        if bias == "BULLISH" and location == "NEAR SUPPORT":
            setup = "BUY SETUP"
        elif bias == "BEARISH" and location == "NEAR RESISTANCE":
            setup = "SHORT SETUP"
        else:
            setup = "WAIT"
        
        return {
            'bias': bias, 'setup': setup, 'location': location,
            'support': support, 'resistance': resistance,
            'distance_high': distance_high, 'distance_low': distance_low,
            'current': data.current, 'week_high': data.week_52_high,
            'week_low': data.week_52_low, 'pct_change': data.pct_change,
        }

def format_output(ticker: str, analysis: Dict) -> str:
    msg = f"""*STRUCTURAL ANALYSIS: {ticker.upper()}*

*WEEKLY BIAS*
Current: ${analysis['current']:.2f}
52w Range: ${analysis['week_low']:.2f} - ${analysis['week_high']:.2f}
Bias: *{analysis['bias']}*

*DAILY SETUP*
Support: ${analysis['support']:.2f} | Resistance: ${analysis['resistance']:.2f}
Location: {analysis['location']}
Setup: *{analysis['setup']}*

*DECISION*
Weekly: {analysis['bias']} | Daily: {analysis['location']}
Action: *{analysis['setup']}*
"""
    return msg.strip()

async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ticker = update.message.text.strip().upper()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    data = DataFetcher.fetch(ticker)
    if data is None:
        await update.message.reply_text(f"❌ Ticker '{ticker}' not found")
        return
    
    analysis = Analyzer.analyze(data)
    msg = format_output(ticker, analysis)
    await update.message.reply_text(msg, parse_mode='Markdown')
    logger.info(f"V2: {ticker} - {analysis['bias']}")

def main():
    token = os.getenv('LEADING_TELEGRAM_TOKEN')
    if not token:
        print("❌ Missing LEADING_TELEGRAM_TOKEN")
        sys.exit(1)
    
    print("\n" + "="*60)
    print("TAPE READER V2: Clean Output")
    print("="*60 + "\n")
    
    application = Application.builder().token(token).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_request))
    application.run_polling()

if __name__ == '__main__':
    main()
