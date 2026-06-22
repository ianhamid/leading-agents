#!/usr/bin/env python3
"""
Leading: Macro Intelligence Agent
Hybrid market philosopher decision engine.

Architecture:
- Modular indicator fetchers (swap free → paid APIs without core changes)
- State persistence (avoid duplicate alerts, track breach history)
- Secure by design (environment variables, no hardcoded secrets)
- Telegram delivery with retry logic
- Structured for cron scheduling at SGT times

Usage:
    python macro_agent.py --tier 1  # Fetch TIER 1 only
    python macro_agent.py --all     # Full briefing
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
import requests
import yfinance as yf
from dataclasses import dataclass
from enum import Enum
import argparse

# ============================================================================
# CONFIGURATION & SECURITY
# ============================================================================

@dataclass
class ThresholdConfig:
    """Define breach thresholds. Modify here to tune sensitivity."""
    # TIER 1
    NIKKEI_DOWN: float = -5.0  # percent
    OIL_UP: float = 80.0  # USD/bbl
    DXY_UP: float = 101.0
    
    # TIER 2
    HY_OAS_UP: float = 450  # basis points
    VIX_UP: float = 30.0
    
    # TIER 3
    LIBOR_OIS_UP: float = 20  # basis points
    IG_OAS_UP: float = 160  # basis points
    
    # CONFIRMATION LAYER (Gold/BTC liquidation signals)
    GOLD_DOWN: float = -3.0  # percent (liquidation pressure)
    BTC_DOWN: float = -10.0  # percent (institutional panic)

CONFIG = ThresholdConfig()

# Ensure state directory exists (must be before logging setup)
STATE_DIR = Path.home() / '.leading'
STATE_DIR.mkdir(exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(STATE_DIR / 'agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
STATE_FILE = STATE_DIR / 'state.json'

# ============================================================================
# SECURE CREDENTIAL MANAGEMENT
# ============================================================================

def get_telegram_token() -> str:
    """Fetch bot token from environment. Fail loudly if missing."""
    token = os.getenv('LEADING_TELEGRAM_TOKEN')
    if not token:
        raise RuntimeError(
            "Missing LEADING_TELEGRAM_TOKEN. Set via:\n"
            "export LEADING_TELEGRAM_TOKEN='your_bot_token_here'"
        )
    return token

def get_telegram_chat_id() -> str:
    """Fetch chat ID from environment."""
    chat_id = os.getenv('LEADING_TELEGRAM_CHAT_ID')
    if not chat_id:
        raise RuntimeError(
            "Missing LEADING_TELEGRAM_CHAT_ID. Set via:\n"
            "export LEADING_TELEGRAM_CHAT_ID='your_chat_id_here'"
        )
    return chat_id

# ============================================================================
# STATE MANAGEMENT (Avoid duplicate alerts, track history)
# ============================================================================

def load_state() -> Dict:
    """Load persisted state (last breaches, values)."""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {
        'last_breach': {},  # {indicator_name: timestamp}
        'last_values': {},  # {indicator_name: value}
        'breach_history': []  # [{timestamp, indicator, value, threshold}]
    }

def save_state(state: Dict):
    """Persist state to disk."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def should_alert(indicator: str, state: Dict, min_hours_between_alerts: int = 6) -> bool:
    """Prevent alert spam. Only alert if breach is NEW or hasn't fired in N hours."""
    last_breach_timestamp = state['last_breach'].get(indicator)
    if not last_breach_timestamp:
        return True
    
    last_breach_time = datetime.fromisoformat(last_breach_timestamp)
    hours_since = (datetime.now() - last_breach_time).total_seconds() / 3600
    return hours_since >= min_hours_between_alerts

# ============================================================================
# DATA FETCHERS (Free tier, swappable to paid APIs)
# ============================================================================

class DataFetcher:
    """Base class for swappable data sources. Inherit for Bloomberg, Refinitiv, etc."""
    
    @staticmethod
    def fetch_nikkei() -> Optional[dict]:
        """Nikkei 225 level + change. Returns {level, change_pct}"""
        try:
            nk = yf.Ticker('^N225')
            hist = nk.history(period='2d')
            if len(hist) >= 2:
                prev_close = hist['Close'].iloc[-2]
                curr_close = hist['Close'].iloc[-1]
                pct_change = ((curr_close - prev_close) / prev_close) * 100
                logger.info(f"Nikkei: {curr_close:.0f} (prev: {prev_close:.0f}) {pct_change:+.2f}%")
                return {'level': curr_close, 'change_pct': pct_change, 'prev': prev_close}
        except Exception as e:
            logger.error(f"Nikkei fetch failed: {e}")
        return None
    
    @staticmethod
    def fetch_oil() -> Optional[dict]:
        """WTI Crude Oil price + change. Returns {level, change_pct}"""
        try:
            oil = yf.Ticker('CL=F')
            hist = oil.history(period='2d')
            if len(hist) >= 2:
                prev_close = hist['Close'].iloc[-2]
                curr_close = hist['Close'].iloc[-1]
                pct_change = ((curr_close - prev_close) / prev_close) * 100
                logger.info(f"Oil (WTI): ${curr_close:.2f} (prev: ${prev_close:.2f}) {pct_change:+.2f}%")
                return {'level': curr_close, 'change_pct': pct_change, 'prev': prev_close}
        except Exception as e:
            logger.error(f"Oil fetch failed: {e}")
        return None
    
    @staticmethod
    def fetch_dxy() -> Optional[dict]:
        """Dollar Index level + change. Returns {level, change_pct}"""
        try:
            dxy = yf.Ticker('^DXY')
            hist = dxy.history(period='2d')
            if len(hist) >= 2:
                prev_close = hist['Close'].iloc[-2]
                curr_close = hist['Close'].iloc[-1]
                pct_change = ((curr_close - prev_close) / prev_close) * 100
                logger.info(f"DXY: {curr_close:.2f} (prev: {prev_close:.2f}) {pct_change:+.2f}%")
                return {'level': curr_close, 'change_pct': pct_change, 'prev': prev_close}
        except Exception as e:
            logger.error(f"DXY fetch failed: {e}")
        return None
    
    @staticmethod
    def fetch_vix() -> Optional[dict]:
        """VIX level + change. Returns {level, change_pct}"""
        try:
            vix = yf.Ticker('^VIX')
            hist = vix.history(period='2d')
            if len(hist) >= 2:
                prev_close = hist['Close'].iloc[-2]
                curr_close = hist['Close'].iloc[-1]
                pct_change = ((curr_close - prev_close) / prev_close) * 100
                logger.info(f"VIX: {curr_close:.2f} (prev: {prev_close:.2f}) {pct_change:+.2f}%")
                return {'level': curr_close, 'change_pct': pct_change, 'prev': prev_close}
        except Exception as e:
            logger.error(f"VIX fetch failed: {e}")
        return None
    
    @staticmethod
    def fetch_sp500_futures() -> Optional[dict]:
        """ES (S&P 500 E-mini futures) level + change. Returns {level, change_pct}"""
        try:
            es = yf.Ticker('ES=F')
            hist = es.history(period='2d')
            if len(hist) >= 2:
                prev_close = hist['Close'].iloc[-2]
                curr_close = hist['Close'].iloc[-1]
                pct_change = ((curr_close - prev_close) / prev_close) * 100
                logger.info(f"S&P 500 Futures: {curr_close:.0f} (prev: {prev_close:.0f}) {pct_change:+.2f}%")
                return {'level': curr_close, 'change_pct': pct_change, 'prev': prev_close}
        except Exception as e:
            logger.error(f"S&P 500 futures fetch failed: {e}")
        return None
    
    @staticmethod
    def fetch_hy_oas() -> Optional[float]:
        """
        High-Yield OAS approximation.
        FREE: Use HYG (iShares High Yield ETF) vs risk-free rate proxy.
        PAID: Swap to ICE BofA HY OAS via Bloomberg/Refinitiv.
        
        Returns: Approximate spread in bps
        """
        try:
            # Proxy: HYG yield spread vs 10Y Treasury
            hyg = yf.Ticker('HYG')
            tlt = yf.Ticker('TLT')  # 20Y Treasury ETF (stable rate)
            
            hyg_hist = hyg.history(period='5d')
            tlt_hist = tlt.history(period='5d')
            
            if not hyg_hist.empty and not tlt_hist.empty:
                # Approximation: Use price momentum as spread proxy
                # In production, fetch actual yields via FRED or Bloomberg
                hyg_ytd_return = ((hyg_hist['Close'].iloc[-1] / hyg_hist['Close'].iloc[0]) - 1) * 100
                tlt_ytd_return = ((tlt_hist['Close'].iloc[-1] / tlt_hist['Close'].iloc[0]) - 1) * 100
                
                spread_proxy = (tlt_ytd_return - hyg_ytd_return) * 100  # bps
                logger.info(f"HY OAS (proxy): {spread_proxy:.0f} bps")
                return max(0, spread_proxy)  # Avoid negatives
        except Exception as e:
            logger.error(f"HY OAS fetch failed: {e}")
        return None
    
    @staticmethod
    def fetch_ig_oas() -> Optional[float]:
        """
        Investment-Grade OAS approximation.
        FREE: Use LQD (iShares Investment Grade Bond ETF) vs 10Y Treasury.
        PAID: Swap to ICE BofA IG OAS via Bloomberg/Refinitiv.
        """
        try:
            lqd = yf.Ticker('LQD')
            tlt = yf.Ticker('TLT')
            
            lqd_hist = lqd.history(period='5d')
            tlt_hist = tlt.history(period='5d')
            
            if not lqd_hist.empty and not tlt_hist.empty:
                lqd_ytd_return = ((lqd_hist['Close'].iloc[-1] / lqd_hist['Close'].iloc[0]) - 1) * 100
                tlt_ytd_return = ((tlt_hist['Close'].iloc[-1] / tlt_hist['Close'].iloc[0]) - 1) * 100
                
                spread_proxy = (tlt_ytd_return - lqd_ytd_return) * 100  # bps
                logger.info(f"IG OAS (proxy): {spread_proxy:.0f} bps")
                return max(0, spread_proxy)
        except Exception as e:
            logger.error(f"IG OAS fetch failed: {e}")
        return None
    
    @staticmethod
    def fetch_libor_ois() -> Optional[float]:
        """
        LIBOR-OIS spread (liquidity stress indicator).
        FREE: Approximate via FRED SOFR spread data.
        PAID: Real Bloomberg/Refinitiv feed.
        
        Note: For accuracy, you may want to fetch from FRED directly.
        Returns: Spread in bps
        """
        try:
            # FRED series: SOFR (SOFR effective rate)
            # In practice, fetch LIBOR vs OIS from FRED API
            # For now, return placeholder that can be extended
            
            # TODO: Integrate FRED API call
            # import fredapi
            # fred = fredapi.FredApi(os.getenv('FRED_API_KEY'))
            # sofr = fred.get_series('SOFR')
            
            logger.warning("LIBOR-OIS: Using placeholder. Integrate FRED API for real data.")
            return None
        except Exception as e:
            logger.error(f"LIBOR-OIS fetch failed: {e}")
        return None
    
    @staticmethod
    def fetch_jobless_claims() -> Optional[float]:
        """
        US Initial Jobless Claims (weekly, Thursdays).
        FREE: Via FRED API (requires key, but free tier available).
        PAID: Bloomberg, Refinitiv, Econdb.
        
        Returns: Claims count in thousands.
        """
        try:
            logger.warning("Jobless Claims: Implement FRED API integration for real-time data.")
            # Placeholder for FRED integration
            return None
        except Exception as e:
            logger.error(f"Jobless claims fetch failed: {e}")
        return None
    
    @staticmethod
    def fetch_gold() -> Optional[dict]:
        """Gold price level + change. Returns {level, change_pct}"""
        try:
            gold = yf.Ticker('GC=F')  # COMEX Gold futures
            hist = gold.history(period='2d')
            if len(hist) >= 2:
                prev_close = hist['Close'].iloc[-2]
                curr_close = hist['Close'].iloc[-1]
                pct_change = ((curr_close - prev_close) / prev_close) * 100
                logger.info(f"Gold: ${curr_close:.2f} (prev: ${prev_close:.2f}) {pct_change:+.2f}%")
                return {'level': curr_close, 'change_pct': pct_change, 'prev': prev_close}
        except Exception as e:
            logger.error(f"Gold fetch failed: {e}")
        return None
    
    @staticmethod
    def fetch_bitcoin() -> Optional[dict]:
        """Bitcoin price level + change. Returns {level, change_pct}"""
        try:
            btc = yf.Ticker('BTC-USD')
            hist = btc.history(period='2d')
            if len(hist) >= 2:
                prev_close = hist['Close'].iloc[-2]
                curr_close = hist['Close'].iloc[-1]
                pct_change = ((curr_close - prev_close) / prev_close) * 100
                logger.info(f"Bitcoin: ${curr_close:.2f} (prev: ${prev_close:.2f}) {pct_change:+.2f}%")
                return {'level': curr_close, 'change_pct': pct_change, 'prev': prev_close}
        except Exception as e:
            logger.error(f"Bitcoin fetch failed: {e}")
        return None

# ============================================================================
# ALERT ENGINE
# ============================================================================

class AlertEngine:
    """Evaluate breaches and format Telegram messages."""
    
    def __init__(self):
        self.state = load_state()
    
    def check_tier_1(self, fetcher: DataFetcher) -> Tuple[list, dict]:
        """TIER 1: Nikkei | Oil | DXY. Returns (breaches, values)."""
        breaches = []
        values = {}
        
        # Nikkei
        nikkei = fetcher.fetch_nikkei()
        if nikkei is not None:
            values['nikkei'] = nikkei
            if nikkei['change_pct'] < CONFIG.NIKKEI_DOWN and should_alert('nikkei', self.state):
                breaches.append({
                    'indicator': 'Nikkei 225',
                    'value': nikkei['level'],
                    'prev_value': nikkei['prev'],
                    'threshold': CONFIG.NIKKEI_DOWN,
                    'unit': 'pts',
                    'narrative': 'Carry unwind pressure',
                    'plumbing': 'JPY strength forcing yen-borrow liquidation',
                    'trap': 'Watch for Fed easing signals (false comfort)'
                })
                self.state['last_breach']['nikkei'] = datetime.now().isoformat()
        
        # Oil
        oil = fetcher.fetch_oil()
        if oil is not None:
            values['oil'] = oil
            if oil['level'] >= CONFIG.OIL_UP and should_alert('oil', self.state):
                breaches.append({
                    'indicator': 'WTI Crude Oil',
                    'value': oil['level'],
                    'prev_value': oil['prev'],
                    'threshold': CONFIG.OIL_UP,
                    'unit': 'USD/bbl',
                    'narrative': 'Geopolitical shock premium',
                    'plumbing': 'Supply disruption or inflation spiral beginning',
                    'trap': 'Conflating risk premium with demand strength'
                })
                self.state['last_breach']['oil'] = datetime.now().isoformat()
        
        # DXY
        dxy = fetcher.fetch_dxy()
        if dxy is not None:
            values['dxy'] = dxy
            if dxy['level'] >= CONFIG.DXY_UP and should_alert('dxy', self.state):
                breaches.append({
                    'indicator': 'US Dollar Index (DXY)',
                    'value': dxy['level'],
                    'prev_value': dxy['prev'],
                    'threshold': CONFIG.DXY_UP,
                    'unit': '',
                    'narrative': 'Capital flight to USD',
                    'plumbing': 'EM currency stress + Fed rate premium',
                    'trap': 'Believing strong dollar = strong economy'
                })
                self.state['last_breach']['dxy'] = datetime.now().isoformat()
        
        save_state(self.state)
        return breaches, values
    
    def check_tier_2(self, fetcher: DataFetcher) -> Tuple[list, dict]:
        """TIER 2: HY OAS | VIX | US Futures."""
        breaches = []
        values = {}
        
        # HY OAS
        hy_oas = fetcher.fetch_hy_oas()
        if hy_oas is not None:
            values['hy_oas'] = hy_oas
            if hy_oas >= CONFIG.HY_OAS_UP and should_alert('hy_oas', self.state):
                breaches.append({
                    'indicator': 'High-Yield OAS',
                    'value': hy_oas,
                    'threshold': CONFIG.HY_OAS_UP,
                    'unit': 'bps',
                    'narrative': 'Risk-off rotation',
                    'plumbing': 'Covenant-lite defaults beginning, credit spreads widening',
                    'trap': 'Thinking HY bonds are "yield opportunities"'
                })
                self.state['last_breach']['hy_oas'] = datetime.now().isoformat()
        
        # VIX
        vix = fetcher.fetch_vix()
        if vix is not None:
            values['vix'] = vix
            if vix['level'] >= CONFIG.VIX_UP and should_alert('vix', self.state):
                breaches.append({
                    'indicator': 'VIX (Volatility)',
                    'value': vix['level'],
                    'prev_value': vix['prev'],
                    'threshold': CONFIG.VIX_UP,
                    'unit': '',
                    'narrative': 'Institutional panic active',
                    'plumbing': 'Vol surface inversion, tail hedges being exercised',
                    'trap': 'Selling into panic for "capitulation bottom"'
                })
                self.state['last_breach']['vix'] = datetime.now().isoformat()
        
        # S&P 500 Futures
        sp500_fut = fetcher.fetch_sp500_futures()
        if sp500_fut is not None:
            values['sp500_fut'] = sp500_fut
            if sp500_fut['change_pct'] < -2.0 and should_alert('sp500_fut', self.state):
                breaches.append({
                    'indicator': 'S&P 500 Futures (ES)',
                    'value': sp500_fut['level'],
                    'prev_value': sp500_fut['prev'],
                    'threshold': -2.0,
                    'unit': 'pts',
                    'narrative': 'Risk-off cascade',
                    'plumbing': 'Portfolio hedges detonating, systematic selloff',
                    'trap': 'Assuming gap-down = opportunity'
                })
                self.state['last_breach']['sp500_fut'] = datetime.now().isoformat()
        
        save_state(self.state)
        return breaches, values
    
    def check_tier_3(self, fetcher: DataFetcher) -> Tuple[list, dict]:
        """TIER 3: LIBOR-OIS | IG OAS | Jobless Claims."""
        breaches = []
        values = {}
        
        # LIBOR-OIS (not yet implemented in free fetcher)
        libor_ois = fetcher.fetch_libor_ois()
        if libor_ois is not None and libor_ois >= CONFIG.LIBOR_OIS_UP:
            breaches.append({
                'indicator': 'LIBOR-OIS Spread',
                'value': libor_ois,
                'threshold': CONFIG.LIBOR_OIS_UP,
                'unit': 'bps',
                'narrative': 'Systemic liquidity stress',
                'plumbing': 'Bank funding markets seizing, counterparty risk spiking',
                'trap': 'Believing central bank will bail out systemic risk immediately'
            })
        
        # IG OAS
        ig_oas = fetcher.fetch_ig_oas()
        if ig_oas is not None:
            values['ig_oas'] = ig_oas
            if ig_oas >= CONFIG.IG_OAS_UP and should_alert('ig_oas', self.state):
                breaches.append({
                    'indicator': 'Investment-Grade OAS',
                    'value': ig_oas,
                    'threshold': CONFIG.IG_OAS_UP,
                    'unit': 'bps',
                    'narrative': 'System getting nervous',
                    'plumbing': 'BBB-rated (weakest IG tier) defaults becoming priced in',
                    'trap': 'Treating IG downgrades as "static noise"'
                })
                self.state['last_breach']['ig_oas'] = datetime.now().isoformat()
        
        # Jobless Claims (not yet live)
        claims = fetcher.fetch_jobless_claims()
        if claims is not None:
            values['jobless_claims'] = claims
        
        save_state(self.state)
        return breaches, values
    
    def check_confirmation_layer(self, fetcher: DataFetcher) -> Tuple[list, dict]:
        """CONFIRMATION LAYER: Gold | Bitcoin. Liquidation + panic indicators."""
        breaches = []
        values = {}
        
        # Gold
        gold = fetcher.fetch_gold()
        if gold is not None:
            values['gold'] = gold
            if gold['change_pct'] < CONFIG.GOLD_DOWN and should_alert('gold', self.state):
                breaches.append({
                    'indicator': 'Gold (Liquidation Signal)',
                    'value': gold['level'],
                    'prev_value': gold['prev'],
                    'threshold': CONFIG.GOLD_DOWN,
                    'unit': 'USD/oz',
                    'narrative': 'Risk-off, margin calls happening',
                    'plumbing': 'Forced collateral liquidation, deleveraging cascade',
                    'trap': 'Gold dips = "buy the dip" vs. systemic forced selling'
                })
                self.state['last_breach']['gold'] = datetime.now().isoformat()
        
        # Bitcoin
        btc = fetcher.fetch_bitcoin()
        if btc is not None:
            values['btc'] = btc
            if btc['change_pct'] < CONFIG.BTC_DOWN and should_alert('btc', self.state):
                breaches.append({
                    'indicator': 'Bitcoin (Institutional Panic)',
                    'value': btc['level'],
                    'prev_value': btc['prev'],
                    'threshold': CONFIG.BTC_DOWN,
                    'unit': 'USD',
                    'narrative': 'Institutional redemptions, risk-off contagion',
                    'plumbing': 'Forced fund selling of uncorrelated assets, liquidity spirals',
                    'trap': 'BTC crash = "HODL and accumulate" vs. systemic unwind signal'
                })
                self.state['last_breach']['btc'] = datetime.now().isoformat()
        
        save_state(self.state)
        return breaches, values

# ============================================================================
# TELEGRAM DELIVERY
# ============================================================================

class TelegramMessenger:
    """Send alerts to Telegram with retry logic."""
    
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def send_message(self, text: str, max_retries: int = 3) -> bool:
        """Send message with exponential backoff retry."""
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    f"{self.base_url}/sendMessage",
                    json={'chat_id': self.chat_id, 'text': text, 'parse_mode': 'Markdown'},
                    timeout=10
                )
                if response.status_code == 200:
                    logger.info(f"Telegram message sent: {len(text)} chars")
                    return True
                else:
                    logger.error(f"Telegram error: {response.status_code} - {response.text}")
            except requests.exceptions.RequestException as e:
                wait_time = 2 ** attempt
                if attempt < max_retries - 1:
                    logger.warning(f"Telegram send failed (attempt {attempt+1}), retrying in {wait_time}s: {e}")
                    import time
                    time.sleep(wait_time)
                else:
                    logger.error(f"Telegram send failed after {max_retries} attempts: {e}")
        return False
    
    def format_breach_message(self, tier: str, breaches: list, values: dict = None) -> str:
        """Format breach list as Telegram message with PRICES prominently."""
        if not breaches and not values:
            return f"✅ TIER {tier}: All clear\n"
        
        lines = []
        
        # If no breaches, show all current values
        if not breaches:
            lines.append(f"✅ TIER {tier}: All clear\n")
            if values:
                for key, val in values.items():
                    if isinstance(val, dict):
                        lines.append(f"  {key.replace('_', ' ').title()}: {val['level']:.2f} ({val['change_pct']:+.2f}%)")
            return "\n".join(lines) + "\n"
        
        # Show breaches
        lines.append(f"🔴 TIER {tier} BREACH(ES)\n")
        for breach in breaches:
            indicator = breach['indicator']
            value = breach['value']
            prev_val = breach.get('prev_value')
            threshold = breach['threshold']
            unit = breach['unit']
            
            # Format price line (tape-reading format)
            if prev_val:
                lines.append(f"**{indicator}**: {value:.2f} (prev: {prev_val:.2f}) {unit}")
            else:
                lines.append(f"**{indicator}**: {value:.2f} {unit} (threshold: {threshold})")
            
            lines.append(f"  NARRATIVE: {breach['narrative']}")
            lines.append(f"  PLUMBING: {breach['plumbing']}")
            lines.append(f"  TRAP: {breach['trap']}")
            lines.append("")
        
        return "\n".join(lines)

# ============================================================================
# MAIN AGENT
# ============================================================================

def run_agent(tier: str = '1'):
    """Execute tier check and send Telegram alert."""
    try:
        fetcher = DataFetcher()
        engine = AlertEngine()
        messenger = TelegramMessenger(get_telegram_token(), get_telegram_chat_id())
        
        logger.info(f"Leading Agent: Running TIER {tier} check at {datetime.now().isoformat()}")
        
        if tier == '1':
            breaches, values = engine.check_tier_1(fetcher)
            msg = messenger.format_breach_message('1', breaches, values)
        elif tier == '2':
            breaches, values = engine.check_tier_2(fetcher)
            msg = messenger.format_breach_message('2', breaches, values)
        elif tier == '3':
            breaches, values = engine.check_tier_3(fetcher)
            # Include confirmation layer with TIER 3
            conf_breaches, conf_values = engine.check_confirmation_layer(fetcher)
            msg = (
                messenger.format_breach_message('3', breaches, values) + "\n" +
                messenger.format_breach_message('CONFIRMATION', conf_breaches, conf_values)
            )
        elif tier == 'confirmation':
            breaches, values = engine.check_confirmation_layer(fetcher)
            msg = messenger.format_breach_message('CONFIRMATION', breaches, values)
        elif tier == 'all':
            b1, v1 = engine.check_tier_1(fetcher)
            b2, v2 = engine.check_tier_2(fetcher)
            b3, v3 = engine.check_tier_3(fetcher)
            conf_b, conf_v = engine.check_confirmation_layer(fetcher)
            msg = (
                messenger.format_breach_message('1', b1, v1) + "\n" +
                messenger.format_breach_message('2', b2, v2) + "\n" +
                messenger.format_breach_message('3', b3, v3) + "\n" +
                messenger.format_breach_message('CONFIRMATION', conf_b, conf_v)
            )
        else:
            raise ValueError(f"Invalid tier: {tier}")
        
        msg += f"\n⏱️ *Check Time*: {datetime.now().strftime('%Y-%m-%d %H:%M:%S SGT')}"
        messenger.send_message(msg)
        
    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Leading: Macro Intelligence Agent')
    parser.add_argument('--tier', default='1', choices=['1', '2', '3', 'confirmation', 'all'],
                        help='Which tier to check (default: 1)')
    args = parser.parse_args()
    
    run_agent(tier=args.tier)
