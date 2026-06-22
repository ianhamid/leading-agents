#!/usr/bin/env python3
"""
Leading Agent: Setup & Deployment Orchestrator

Handles:
- Telegram credential setup & validation
- Cron job installation (SGT times: 9 AM, 10 AM, 12:30 PM)
- Log directory initialization
- Environment variable persistence
- Upgrade path to paid API tiers

Usage:
    python setup.py --init           # First-time setup
    python setup.py --validate       # Check credentials
    python setup.py --install-cron   # Add to crontab
    python setup.py --logs           # Show recent agent activity
"""

import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import argparse
import json

# ============================================================================
# SETUP STATE
# ============================================================================

STATE_DIR = Path.home() / '.leading'
STATE_DIR.mkdir(exist_ok=True)

CONFIG_FILE = STATE_DIR / 'config.json'
AGENT_SCRIPT = Path(__file__).parent / 'macro_agent.py'
LOG_FILE = STATE_DIR / 'agent.log'

# ============================================================================
# TELEGRAM SETUP
# ============================================================================

def setup_telegram():
    """Interactive Telegram bot credential setup."""
    print("\n" + "="*70)
    print("LEADING AGENT: Telegram Setup")
    print("="*70)
    
    print("\n📱 You need two credentials:")
    print("  1. LEADING_TELEGRAM_TOKEN - Your Telegram bot token")
    print("  2. LEADING_TELEGRAM_CHAT_ID - Your personal chat ID\n")
    
    print("Get these from:")
    print("  • Token: Message @BotFather on Telegram, create new bot")
    print("  • Chat ID: Message @userinfobot, it will reply with your ID\n")
    
    token = input("Enter LEADING_TELEGRAM_TOKEN: ").strip()
    if not token:
        print("❌ Token required.")
        return False
    
    chat_id = input("Enter LEADING_TELEGRAM_CHAT_ID: ").strip()
    if not chat_id:
        print("❌ Chat ID required.")
        return False
    
    # Windows: Use setx to save to Registry (persistent, Task Scheduler can see)
    # Linux/Mac: Save to shell profile
    if sys.platform == 'win32':
        try:
            subprocess.run(['setx', 'LEADING_TELEGRAM_TOKEN', token], check=True, capture_output=True)
            subprocess.run(['setx', 'LEADING_TELEGRAM_CHAT_ID', chat_id], check=True, capture_output=True)
            os.environ['LEADING_TELEGRAM_TOKEN'] = token
            os.environ['LEADING_TELEGRAM_CHAT_ID'] = chat_id
            print(f"\n✅ Credentials saved to Windows Registry (permanent)")
            print("⚠️  Task Scheduler will see them immediately")
            return True
        except Exception as e:
            print(f"❌ Failed to save: {e}")
            return False
    else:
        # Linux/Mac
        shell_profile = Path.home() / '.bashrc'
        if not shell_profile.exists():
            shell_profile = Path.home() / '.zshrc'
        
        with open(shell_profile, 'a') as f:
            f.write(f"\n# Leading Agent Credentials\n")
            f.write(f"export LEADING_TELEGRAM_TOKEN='{token}'\n")
            f.write(f"export LEADING_TELEGRAM_CHAT_ID='{chat_id}'\n")
        
        os.environ['LEADING_TELEGRAM_TOKEN'] = token
        os.environ['LEADING_TELEGRAM_CHAT_ID'] = chat_id
        
        print(f"\n✅ Credentials saved to {shell_profile}")
        print("⚠️  Restart your terminal or run: source ~/.bashrc")
        return True

def validate_telegram():
    """Test Telegram credentials by sending test message."""
    import requests
    
    token = os.getenv('LEADING_TELEGRAM_TOKEN')
    chat_id = os.getenv('LEADING_TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        print("❌ Missing credentials. Run: python setup.py --init")
        return False
    
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                'chat_id': chat_id,
                'text': '✅ Leading Agent is configured correctly.'
            },
            timeout=10
        )
        if response.status_code == 200:
            print("✅ Telegram credentials valid. Test message sent.")
            return True
        else:
            print(f"❌ Telegram error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

# ============================================================================
# CRON SETUP (SGT Times)
# ============================================================================

def sgt_to_local_time(sgt_hour: int, sgt_minute: int = 0) -> tuple:
    """
    Convert SGT time to local cron time.
    
    Cron runs in system timezone. SGT is UTC+8.
    Calculate offset and convert.
    """
    from datetime import datetime, timezone, timedelta
    
    # Current SGT time
    sgt_tz = timezone(timedelta(hours=8))
    now_sgt = datetime.now(sgt_tz)
    
    # Local time equivalent
    local_now = datetime.now()
    offset = local_now.astimezone().utcoffset().total_seconds() / 3600
    
    # Convert SGT hour to local hour
    sgt_offset = 8
    local_hour = sgt_hour - sgt_offset + offset
    
    if local_hour < 0:
        local_hour += 24
    elif local_hour >= 24:
        local_hour -= 24
    
    return int(local_hour), sgt_minute

def install_cron():
    """Install cron jobs for TIER 1/2/3 at SGT times."""
    print("\n" + "="*70)
    print("LEADING AGENT: Cron Installation")
    print("="*70)
    
    if not AGENT_SCRIPT.exists():
        print(f"❌ Agent script not found: {AGENT_SCRIPT}")
        return False
    
    # SGT schedule
    tier1_sgt = (9, 0)    # 9 AM SGT
    tier2_sgt = (10, 0)   # 10 AM SGT
    tier3_sgt = (12, 30)  # 12:30 PM SGT
    
    # Convert to local time
    tier1_local = sgt_to_local_time(*tier1_sgt)
    tier2_local = sgt_to_local_time(*tier2_sgt)
    tier3_local = sgt_to_local_time(*tier3_sgt)
    
    print(f"\n📅 Schedule (converted to your local timezone):")
    print(f"  TIER 1: {tier1_sgt[0]:02d}:{tier1_sgt[1]:02d} SGT → {tier1_local[0]:02d}:{tier1_local[1]:02d} local")
    print(f"  TIER 2: {tier2_sgt[0]:02d}:{tier2_sgt[1]:02d} SGT → {tier2_local[0]:02d}:{tier2_local[1]:02d} local")
    print(f"  TIER 3: {tier3_sgt[0]:02d}:{tier3_sgt[1]:02d} SGT → {tier3_local[0]:02d}:{tier3_local[1]:02d} local")
    
    # Build cron entries
    cron_entries = [
        f"{tier1_local[1]} {tier1_local[0]} * * * cd {STATE_DIR} && python {AGENT_SCRIPT} --tier 1 >> {LOG_FILE} 2>&1",
        f"{tier2_local[1]} {tier2_local[0]} * * * cd {STATE_DIR} && python {AGENT_SCRIPT} --tier 2 >> {LOG_FILE} 2>&1",
        f"{tier3_local[1]} {tier3_local[0]} * * * cd {STATE_DIR} && python {AGENT_SCRIPT} --tier 3 >> {LOG_FILE} 2>&1",
    ]
    
    # Write to temp crontab
    temp_cron = STATE_DIR / 'crontab.tmp'
    
    # Get current crontab
    try:
        current = subprocess.check_output(['crontab', '-l'], stderr=subprocess.DEVNULL).decode()
    except subprocess.CalledProcessError:
        current = ""
    
    # Append new entries (filter out old Leading entries to avoid duplicates)
    new_entries = [line for line in current.split('\n') if 'Leading' not in line and 'macro_agent' not in line]
    new_entries.extend(cron_entries)
    
    with open(temp_cron, 'w') as f:
        f.write('\n'.join(new_entries))
    
    # Install
    try:
        subprocess.run(['crontab', str(temp_cron)], check=True)
        print(f"\n✅ Cron jobs installed!")
        print(f"📝 Log file: {LOG_FILE}")
        
        # Clean up
        temp_cron.unlink()
        return True
    except Exception as e:
        print(f"❌ Cron installation failed: {e}")
        return False

def list_cron():
    """Show active Leading cron jobs."""
    print("\n" + "="*70)
    print("LEADING AGENT: Active Cron Jobs")
    print("="*70 + "\n")
    
    try:
        crontab = subprocess.check_output(['crontab', '-l'], stderr=subprocess.DEVNULL).decode()
        leading_jobs = [line for line in crontab.split('\n') if 'macro_agent' in line]
        
        if leading_jobs:
            for job in leading_jobs:
                print(f"  {job}")
        else:
            print("No Leading agent cron jobs found.")
    except subprocess.CalledProcessError:
        print("No crontab installed.")

# ============================================================================
# LOGS & MONITORING
# ============================================================================

def show_logs(lines: int = 50):
    """Display recent agent activity."""
    print("\n" + "="*70)
    print(f"LEADING AGENT: Recent Activity (last {lines} lines)")
    print("="*70 + "\n")
    
    if not LOG_FILE.exists():
        print("No logs yet. Agent hasn't run.")
        return
    
    with open(LOG_FILE, 'r') as f:
        log_lines = f.readlines()
    
    for line in log_lines[-lines:]:
        print(line.rstrip())

def show_state():
    """Display agent state (last breaches, values)."""
    print("\n" + "="*70)
    print("LEADING AGENT: State & Breach History")
    print("="*70 + "\n")
    
    state_file = STATE_DIR / 'state.json'
    if not state_file.exists():
        print("No state yet. Agent hasn't run.")
        return
    
    with open(state_file, 'r') as f:
        state = json.load(f)
    
    print("Last Breaches:")
    for indicator, timestamp in state.get('last_breach', {}).items():
        print(f"  {indicator}: {timestamp}")
    
    print("\nLast Values:")
    for indicator, value in state.get('last_values', {}).items():
        print(f"  {indicator}: {value:.2f}")

# ============================================================================
# PAID API UPGRADE PATH
# ============================================================================

def show_upgrade_path():
    """Document how to upgrade from free to paid APIs."""
    print("\n" + "="*70)
    print("LEADING AGENT: Upgrade to Paid Data Sources")
    print("="*70 + "\n")
    
    print("Current: Free APIs (yfinance, FRED)")
    print("Limitation: OAS spreads are approximated, some data is delayed\n")
    
    print("🎯 Upgrade Targets:\n")
    
    print("1. **Bloomberg Terminal (B-PIPE API)**")
    print("   • Real-time HY/IG OAS (ICE BofA indices)")
    print("   • LIBOR-OIS spreads")
    print("   • Integration: Replace DataFetcher methods with B-PIPE calls")
    print("   • Cost: ~$24k/year for real-time")
    print("   • Setup time: 2-3 days\n")
    
    print("2. **Refinitiv/LSEG (EIKON API)**")
    print("   • Similar coverage to Bloomberg")
    print("   • Better for FX, commodities")
    print("   • Cost: ~$18k/year")
    print("   • Setup time: 1-2 days\n")
    
    print("3. **FRED (Federal Reserve) + Alternative Data**")
    print("   • Free tier (5 calls/min)")
    print("   • Good for: jobless claims, SOFR spreads")
    print("   • Setup: Get API key at https://fred.stlouisfed.org")
    print("   • Integration: ~30 min\n")
    
    print("Architecture Note:")
    print("  DataFetcher class is designed for easy swaps.")
    print("  Inherit DataFetcher, override fetch_* methods with paid APIs.")
    print("  No change to alert logic or Telegram delivery needed.\n")

# ============================================================================
# MAIN ORCHESTRATOR
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Leading Agent: Setup & Deployment')
    parser.add_argument('--init', action='store_true', help='Initial setup (Telegram credentials)')
    parser.add_argument('--validate', action='store_true', help='Validate Telegram credentials')
    parser.add_argument('--install-cron', action='store_true', help='Install cron jobs')
    parser.add_argument('--list-cron', action='store_true', help='Show active cron jobs')
    parser.add_argument('--logs', action='store_true', help='Show recent logs')
    parser.add_argument('--logs-lines', type=int, default=50, help='Number of log lines (default: 50)')
    parser.add_argument('--state', action='store_true', help='Show agent state')
    parser.add_argument('--upgrade', action='store_true', help='Show paid API upgrade options')
    
    args = parser.parse_args()
    
    if args.init:
        setup_telegram()
    elif args.validate:
        validate_telegram()
    elif args.install_cron:
        install_cron()
    elif args.list_cron:
        list_cron()
    elif args.logs:
        show_logs(args.logs_lines)
    elif args.state:
        show_state()
    elif args.upgrade:
        show_upgrade_path()
    else:
        # Default: interactive menu
        print("\n" + "="*70)
        print("LEADING AGENT: Interactive Setup")
        print("="*70)
        print("\nOptions:")
        print("  1. Setup Telegram credentials (--init)")
        print("  2. Validate Telegram credentials (--validate)")
        print("  3. Install cron jobs (--install-cron)")
        print("  4. View logs (--logs)")
        print("  5. View agent state (--state)")
        print("  6. Show paid API upgrade path (--upgrade)")
        print("  7. Exit")
        
        choice = input("\nChoose option (1-7): ").strip()
        
        if choice == '1':
            setup_telegram()
        elif choice == '2':
            validate_telegram()
        elif choice == '3':
            install_cron()
        elif choice == '4':
            show_logs()
        elif choice == '5':
            show_state()
        elif choice == '6':
            show_upgrade_path()
        elif choice == '7':
            print("Goodbye.")
        else:
            print("Invalid choice.")

if __name__ == '__main__':
    main()
