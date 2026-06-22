#!/usr/bin/env python3
"""Tape Reader V3: Alpha Vantage API (Free, works on VPS)"""

import os, sys, logging, requests, time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass

try:
    from telegram import Update
    from telegram.ext import Application, ContextTypes, MessageHandler, filters
except ImportError:
    print("❌ Missing python-telegram-bot")
    sys.exit(1)

STATE_DIR = Path.home() / '.leading'
STATE_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(STATE_DIR / 'tape_reader_v3.log'), logging.StreamHandler()])
logger = logging.getLogger(__name__)

API_KEY = '3EFXDLDSU56WU2QT'
BASE_URL = 'https://www.alphavantage.co/query'

@dataclass
class CompleteMarketData:
    current: float
    prev_close: float
    week_52_high: float
    week_52_low: float
    daily_closes: List[float]
    daily_highs: List[float]
    daily_lows: List[float]
    daily_volumes: List[float]
    weekly_closes: List[float]
    weekly_volumes: List[float]
    weekly_dates: List[str]
    
    @property
    def pct_change_today(self) -> float:
        return ((self.current - self.prev_close) / self.prev_close) * 100 if self.prev_close else 0
    
    @property
    def distance_to_52h(self) -> float:
        return ((self.current - self.week_52_high) / self.week_52_high) * 100
    
    @property
    def distance_to_52l(self) -> float:
        return ((self.current - self.week_52_low) / self.week_52_low) * 100
    
    @property
    def weekly_pattern(self) -> str:
        if len(self.weekly_closes) < 3:
            return "INSUFFICIENT"
        closes = self.weekly_closes[-5:]
        lows_rising = all(closes[i] < closes[i+1] for i in range(len(closes)-1))
        highs_falling = all(closes[i] > closes[i+1] for i in range(len(closes)-1))
        return "HIGHER_LOWS" if lows_rising else "LOWER_HIGHS" if highs_falling else "RANGING"
    
    @property
    def daily_support(self) -> float:
        return min(self.daily_lows) if self.daily_lows else self.current * 0.95
    
    @property
    def daily_resistance(self) -> float:
        return max(self.daily_highs) if self.daily_highs else self.current * 1.05
    
    @property
    def avg_daily_volume(self) -> float:
        return sum(self.daily_volumes) / len(self.daily_volumes) if self.daily_volumes else 1000000
    
    @property
    def current_daily_volume(self) -> float:
        return self.daily_volumes[-1] if self.daily_volumes else self.avg_daily_volume
    
    @property
    def volume_ratio(self) -> float:
        return self.current_daily_volume / self.avg_daily_volume if self.avg_daily_volume > 0 else 1.0
    
    @property
    def avg_weekly_volume(self) -> float:
        return sum(self.weekly_volumes) / len(self.weekly_volumes) if self.weekly_volumes else 1000000
    
    @property
    def current_weekly_volume(self) -> float:
        return self.weekly_volumes[-1] if self.weekly_volumes else self.avg_weekly_volume
    
    @property
    def weekly_volume_ratio(self) -> float:
        return self.current_weekly_volume / self.avg_weekly_volume if self.avg_weekly_volume > 0 else 1.0

class AlphaVantageFetcher:
    @staticmethod
    def fetch_complete_data(ticker: str) -> Optional[CompleteMarketData]:
        try:
            logger.info(f"Fetching {ticker} from Alpha Vantage...")
            
            # Get daily data
            time.sleep(0.5)  # Rate limit
            resp = requests.get(BASE_URL, params={
                'function': 'TIME_SERIES_DAILY',
                'symbol': ticker,
                'apikey': API_KEY,
                'outputsize': 'full'
            }, timeout=15)
            
            if resp.status_code != 200:
                logger.error(f"Status {resp.status_code}")
                return None
            
            data = resp.json()
            
            if 'Time Series (Daily)' not in data:
                logger.error(f"No data for {ticker}. Response keys: {list(data.keys())}")
                logger.error(f"Full response: {str(data)[:500]}")
                return None
            
            ts = data['Time Series (Daily)']
            dates = sorted(ts.keys())
            
            if len(dates) < 5:
                logger.error(f"Not enough data for {ticker}")
                return None
            
            # Last 5 days
            daily_closes = []
            daily_highs = []
            daily_lows = []
            daily_volumes = []
            
            for date in dates[-5:]:
                candle = ts[date]
                daily_closes.append(float(candle['4. close']))
                daily_highs.append(float(candle['2. high']))
                daily_lows.append(float(candle['3. low']))
                daily_volumes.append(float(candle['5. volume']))
            
            current = daily_closes[-1]
            prev_close = daily_closes[-2] if len(daily_closes) > 1 else current
            
            # Last 8 weeks (roughly)
            weekly_closes = []
            weekly_highs = []
            weekly_lows = []
            weekly_volumes = []
            weekly_dates = []
            
            week_dates = []
            for i, date in enumerate(reversed(dates)):
                if len(week_dates) == 0:
                    week_dates.append(date)
                elif (datetime.strptime(dates[-1], '%Y-%m-%d') - datetime.strptime(date, '%Y-%m-%d')).days >= 7 * len(weekly_closes):
                    week_dates.append(date)
                    if len(week_dates) > 8:
                        break
            
            if len(week_dates) < 8:
                week_dates = dates[-56::7] if len(dates) > 56 else dates[::max(1, len(dates)//8)]
            
            week_dates = sorted(week_dates)[-8:]
            
            for date in week_dates:
                candle = ts[date]
                weekly_closes.append(float(candle['4. close']))
                weekly_highs.append(float(candle['2. high']))
                weekly_lows.append(float(candle['3. low']))
                weekly_volumes.append(float(candle['5. volume']))
                weekly_dates.append(datetime.strptime(date, '%Y-%m-%d').strftime('%d %b %Y'))
            
            week_52_high = max(weekly_highs) if weekly_highs else current
            week_52_low = min(weekly_lows) if weekly_lows else current
            
            return CompleteMarketData(
                current=current, prev_close=prev_close,
                week_52_high=week_52_high, week_52_low=week_52_low,
                daily_closes=daily_closes, daily_highs=daily_highs,
                daily_lows=daily_lows, daily_volumes=daily_volumes,
                weekly_closes=weekly_closes, weekly_volumes=weekly_volumes,
                weekly_dates=weekly_dates,
            )
        except Exception as e:
            logger.error(f"Error: {e}")
            return None

class MasterPromptAnalyzer:
    @staticmethod
    def analyze_part1_weekly(data: CompleteMarketData) -> Dict:
        distance_high = data.distance_to_52h
        distance_low = data.distance_to_52l
        weekly_closes = data.weekly_closes[-8:]
        
        if len(weekly_closes) >= 3:
            higher_lows = all(weekly_closes[i] < weekly_closes[i+1] for i in range(len(weekly_closes)-1))
            lower_highs = all(weekly_closes[i] > weekly_closes[i+1] for i in range(len(weekly_closes)-1))
        else:
            higher_lows = lower_highs = False
        
        if higher_lows and data.weekly_volume_ratio > 1.0:
            bias = "BULLISH"
        elif lower_highs and data.weekly_volume_ratio > 1.0:
            bias = "BEARISH"
        elif not higher_lows and not lower_highs:
            bias = "BROKEN"
        else:
            bias = "RANGE"
        
        confidence = "HIGH" if abs(distance_high - distance_low) > 15 else "MEDIUM" if abs(distance_high - distance_low) > 5 else "LOW"
        
        return {
            'current_price': data.current, 'week_52_high': data.week_52_high, 'week_52_low': data.week_52_low,
            'distance_high_pct': distance_high, 'distance_low_pct': distance_low,
            'weekly_closes_8weeks': weekly_closes, 'pattern': data.weekly_pattern,
            'higher_lows': higher_lows, 'lower_highs': lower_highs,
            'avg_weekly_volume': data.avg_weekly_volume, 'current_weekly_volume': data.current_weekly_volume,
            'weekly_volume_ratio': data.weekly_volume_ratio,
            'bias': bias, 'confidence': confidence,
        }
    
    @staticmethod
    def analyze_part2_daily(data: CompleteMarketData, weekly_bias: str) -> Dict:
        daily_closes = data.daily_closes[-5:]
        daily_highs = data.daily_highs[-5:]
        daily_lows = data.daily_lows[-5:]
        support = data.daily_support
        resistance = data.daily_resistance
        range_size = resistance - support
        position = (data.current - support) / range_size if range_size > 0 else 0.5
        
        location = "NEAR SUPPORT" if position < 0.3 else "NEAR RESISTANCE" if position > 0.7 else "IN MIDDLE"
        
        if weekly_bias == "BULLISH" and location == "NEAR SUPPORT":
            setup, setup_confidence = "BUY SETUP", "HIGH"
        elif weekly_bias == "BEARISH" and location == "NEAR RESISTANCE":
            setup, setup_confidence = "SHORT SETUP", "HIGH"
        elif weekly_bias in ["BULLISH", "BEARISH"] and location == "IN MIDDLE":
            setup, setup_confidence = "SETUP FORMING", "MEDIUM"
        else:
            setup, setup_confidence = "NO SETUP", "LOW"
        
        return {
            'daily_closes_5days': daily_closes, 'daily_highs_5days': daily_highs, 'daily_lows_5days': daily_lows,
            'support': support, 'resistance': resistance, 'current_position_pct': position * 100,
            'location': location, '3day_cycle_position': 1,
            'avg_daily_volume': data.avg_daily_volume, 'current_daily_volume': data.current_daily_volume,
            'daily_volume_ratio': data.volume_ratio,
            'setup': setup, 'setup_confidence': setup_confidence,
        }
    
    @staticmethod
    def analyze_part3_intraday(data: CompleteMarketData) -> Dict:
        pct_change = data.pct_change_today
        gap_direction = "UP" if pct_change > 0 else "DOWN" if pct_change < 0 else "FLAT"
        vol_ratio = data.volume_ratio
        
        if vol_ratio > 1.5 and abs(pct_change) > 0.5:
            move_type, move_confidence = "REAL MOVE", "HIGH"
        elif vol_ratio < 0.7 and abs(pct_change) > 0.5:
            move_type, move_confidence = "FAKE MOVE (TRAP)", "HIGH"
        elif vol_ratio > 1.2 and abs(pct_change) < 0.2:
            move_type, move_confidence = "ACCUMULATION", "MEDIUM"
        else:
            move_type, move_confidence = "NORMAL / NEUTRAL", "LOW"
        
        return {
            'current': data.current, 'prev_close': data.prev_close,
            'gap_pct': pct_change, 'gap_direction': gap_direction,
            'current_volume': data.current_daily_volume, 'avg_volume': data.avg_daily_volume,
            'volume_ratio': vol_ratio, 'pct_change_today': pct_change,
            'move_type': move_type, 'move_confidence': move_confidence,
        }
    
    @staticmethod
    def analyze_part4_cycles(part1: Dict, part2: Dict, part3: Dict) -> Dict:
        weekly_dir = "UP" if part1['bias'] == "BULLISH" else "DOWN" if part1['bias'] == "BEARISH" else "NONE"
        daily_dir = "UP" if "BUY" in part2['setup'] else "DOWN" if "SHORT" in part2['setup'] else "NONE"
        intraday_dir = "UP" if part3['gap_direction'] == "UP" else "DOWN" if part3['gap_direction'] == "DOWN" else "FLAT"
        
        if weekly_dir == daily_dir == "UP":
            alignment = "YES (ALL UP)"
            conflict = False
        elif weekly_dir == daily_dir == "DOWN":
            alignment = "YES (ALL DOWN)"
            conflict = False
        elif weekly_dir == "UP" and daily_dir == "DOWN":
            alignment = "NO (BULLISH RUPTURE)"
            conflict = True
        elif weekly_dir == "DOWN" and daily_dir == "UP":
            alignment = "NO (BEARISH RUPTURE)"
            conflict = True
        else:
            alignment = "PARTIAL / UNCLEAR"
            conflict = False
        
        return {
            'weekly_dir': weekly_dir, 'daily_dir': daily_dir, 'intraday_dir': intraday_dir,
            'alignment': alignment, 'has_conflict': conflict,
        }
    
    @staticmethod
    def analyze_part5_risk_reward(data: CompleteMarketData, part1: Dict, part2: Dict) -> Dict:
        current = data.current
        support = part2['support']
        resistance = part2['resistance']
        range_size = resistance - support
        
        if part1['bias'] == "BULLISH":
            target = resistance + (range_size * 0.5)
            stop = support * 0.99
            potential_move_pct = ((target - current) / current) * 100
            risk_pct = ((current - stop) / current) * 100
        else:
            target = support - (range_size * 0.5)
            stop = resistance * 1.01
            potential_move_pct = ((current - target) / current) * 100
            risk_pct = ((stop - current) / current) * 100
        
        rr_ratio = abs(potential_move_pct) / risk_pct if risk_pct > 0 else 0
        
        if rr_ratio > 3 and part1['confidence'] == "HIGH":
            position_size = "5-7%"
        elif rr_ratio > 2 and part1['confidence'] in ["HIGH", "MEDIUM"]:
            position_size = "3-5%"
        elif rr_ratio > 1.5:
            position_size = "2-4%"
        elif rr_ratio > 1:
            position_size = "1-2%"
        else:
            position_size = "SKIP"
        
        return {
            'target': target, 'stop': stop, 'potential_move_pct': potential_move_pct,
            'risk_pct': risk_pct, 'rr_ratio': rr_ratio, 'position_size': position_size,
        }
    
    @staticmethod
    def analyze_part6_decision(part1: Dict, part2: Dict, part3: Dict, part4: Dict, part5: Dict) -> Dict:
        if part1['bias'] == "BULLISH" and part2['setup'] == "BUY SETUP":
            verdict = "BUY"
            reasoning = f"Weekly {part1['bias']} + daily {part2['location']} = entry ready"
        elif part1['bias'] == "BEARISH" and part2['setup'] == "SHORT SETUP":
            verdict = "SHORT"
            reasoning = f"Weekly {part1['bias']} + daily {part2['location']} = entry ready"
        elif part4['has_conflict']:
            verdict = "WAIT"
            reasoning = f"Cycle conflict detected ({part4['alignment']}). Wait for clarity."
        else:
            verdict = "FLAT"
            reasoning = f"No high-conviction setup. Stay in cash."
        
        break_level = part2['support'] if part1['bias'] == "BULLISH" else part2['resistance']
        break_event = f"Price closes below ${break_level:.2f}" if part1['bias'] == "BULLISH" else f"Price closes above ${break_level:.2f}"
        
        return {
            'verdict': verdict, 'reasoning': reasoning,
            'entry_price': f"${part2['support']:.2f} - ${part2['resistance']:.2f}",
            'target': f"${part5['target']:.2f}", 'stop': f"${part5['stop']:.2f}",
            'position_size': part5['position_size'], 'break_event': break_event,
        }

def format_master_prompt_output(ticker: str, data: CompleteMarketData, p1: Dict, p2: Dict, p3: Dict, p4: Dict, p5: Dict, p6: Dict) -> str:
    weekly_str = ""
    week_nums = [8, 7, 6, 5, 4, 3, 2, 1]
    for week_num, (close, date) in zip(week_nums, zip(p1['weekly_closes_8weeks'], data.weekly_dates)):
        weekly_str += f"• Week {week_num} ({date}): ${close:.2f}\n"
    
    daily_str = ""
    day_nums = [5, 4, 3, 2, 1]
    for day_num, close in zip(day_nums, p2['daily_closes_5days']):
        daily_str += f"• Day {day_num}: ${close:.2f}\n"
    
    msg = f"""*STRUCTURAL MARKET ANALYSIS PROTOCOL*
*Asset: {ticker.upper()}*
*Analysis Date: {datetime.now().strftime('%Y-%m-%d')}*

*PART 1: WEEKLY TIMEFRAME (Your Bias)*

**1. TREND IDENTIFICATION (52-week structure)**
• Current: ${p1['current_price']:.2f}
• 52w High: ${p1['week_52_high']:.2f} ({p1['distance_high_pct']:+.1f}%)
• 52w Low: ${p1['week_52_low']:.2f} ({p1['distance_low_pct']:+.1f}%)

**2. WEEKLY CLOSE STRUCTURE (Last 8 weeks)**
{weekly_str}• Pattern: {p1['pattern']}
• Higher Lows: {p1['higher_lows']} | Lower Highs: {p1['lower_highs']}

**3. VOLUME CONFIRMATION**
• Avg Weekly Vol: {p1['avg_weekly_volume']:,.0f}
• Current Weekly Vol: {p1['current_weekly_volume']:,.0f}
• Ratio: {p1['weekly_volume_ratio']:.2f}x

**5. WEEKLY BIAS DECISION**
*Bias: {p1['bias']}* (Confidence: {p1['confidence']})

*PART 2: DAILY TIMEFRAME (Your Entry Setup)*

**1. RECENT DAILY ACTION (Last 5 days)**
{daily_str}• Range: ${min(p2['daily_lows_5days']):.2f} - ${max(p2['daily_highs_5days']):.2f}

**2. 3-DAY CYCLE POSITION**
• Day {p2['3day_cycle_position']} of 3-day cycle
  (1=Setup/Quiet | 2=Trap/Pain | 3=Flush/Panic)

**3. DAILY SUPPORT/RESISTANCE**
• Support: ${p2['support']:.2f}
• Resistance: ${p2['resistance']:.2f}
• Current Position: {p2['location']} ({p2['current_position_pct']:.0f}% up from low)

**4. VOLUME CONFIRMATION (Daily)**
• Avg Volume: {p2['avg_daily_volume']:,.0f}
• Current Volume: {p2['current_daily_volume']:,.0f}
• Ratio: {p2['daily_volume_ratio']:.2f}x

**5. DAILY SETUP READINESS**
*Setup: {p2['setup']}* (Confidence: {p2['setup_confidence']})

*PART 3: INTRADAY TAPE (Your Filter)*

**1. OVERNIGHT/GAP ACTION**
• Last Close: ${p3['prev_close']:.2f}
• Current Open/Price: ${p3['current']:.2f}
• Gap: {p3['gap_pct']:+.2f}% ({p3['gap_direction']})

**2. OPENING HOUR VOLUME**
• Current: {p3['current_volume']:,.0f}
• Average: {p3['avg_volume']:,.0f}
• Ratio: {p3['volume_ratio']:.2f}x

**3. REAL MOVE vs. SUCKER PUNCH TEST**
• Move Type: {p3['move_type']}
• Confidence: {p3['move_confidence']}

*PART 4: CYCLE CONFLICT ANALYSIS*

**1. CYCLE ALIGNMENT CHECK**
• Weekly: {p4['weekly_dir']}
• Daily: {p4['daily_dir']}
• Intraday: {p4['intraday_dir']}

*Alignment: {p4['alignment']}*
*Conflict Present: {p4['has_conflict']}*

*PART 5: RISK/REWARD & POSITION SIZING*

**1. POTENTIAL MOVE**
• Target: ${p5['target']:.2f}
• Move: {p5['potential_move_pct']:+.1f}%
• Timeframe: 2-3 weeks

**2. STOP LOSS (Hard Technical Level)**
• Stop: ${p5['stop']:.2f}
• Risk: {p5['risk_pct']:.1f}%
• R:R Ratio: {p5['rr_ratio']:.1f}:1

**3. POSITION SIZE DECISION**
*Size: {p5['position_size']}*

*PART 6: FINAL DECISION & ACTION PLAN*

*FINAL VERDICT:*
*[{p6['verdict']}]*

Entry: {p6['entry_price']}
Target: {p6['target']}
Stop: {p6['stop']}
Size: {p6['position_size']}

**Reasoning:**
{p6['reasoning']}

**WHAT COULD BREAK THIS THESIS:**
• {p6['break_event']} → Invalidate thesis
"""
    return msg.strip()

async def handle_master_prompt_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ticker = update.message.text.strip().upper()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    data = AlphaVantageFetcher.fetch_complete_data(ticker)
    if data is None:
        await update.message.reply_text(f"❌ Ticker '{ticker}' not found or error fetching data")
        return
    
    p1 = MasterPromptAnalyzer.analyze_part1_weekly(data)
    p2 = MasterPromptAnalyzer.analyze_part2_daily(data, p1['bias'])
    p3 = MasterPromptAnalyzer.analyze_part3_intraday(data)
    p4 = MasterPromptAnalyzer.analyze_part4_cycles(p1, p2, p3)
    p5 = MasterPromptAnalyzer.analyze_part5_risk_reward(data, p1, p2)
    p6 = MasterPromptAnalyzer.analyze_part6_decision(p1, p2, p3, p4, p5)
    
    msg = format_master_prompt_output(ticker, data, p1, p2, p3, p4, p5, p6)
    
    if len(msg) > 4000:
        chunks = [msg[i:i+3900] for i in range(0, len(msg), 3900)]
        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, parse_mode='Markdown')
    
    logger.info(f"V3: {ticker} - {p1['bias']} / {p2['setup']}")

def main():
    token = os.getenv('LEADING_TELEGRAM_TOKEN')
    if not token:
        print("❌ Missing LEADING_TELEGRAM_TOKEN")
        sys.exit(1)
    
    print("\n" + "="*70)
    print("TAPE READER V3: Alpha Vantage (FREE - Works on VPS)")
    print("="*70 + "\n")
    
    application = Application.builder().token(token).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_master_prompt_request))
    application.run_polling()

if __name__ == '__main__':
    main()
