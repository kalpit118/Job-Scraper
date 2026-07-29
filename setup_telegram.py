"""
setup_telegram.py
-----------------
Diagnostic helper to verify and complete Telegram bot setup.

Run this BEFORE main.py to confirm your bot token and channel are
configured correctly.

Usage:
    python setup_telegram.py
"""

import os
import sys
import json
import requests
from dotenv import load_dotenv

# Force UTF-8 on Windows to avoid cp1252 encoding errors
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BASE = f"https://api.telegram.org/bot{TOKEN}"

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}[OK]  {RESET} {msg}")
def fail(msg): print(f"  {RED}[FAIL]{RESET} {msg}")
def warn(msg): print(f"  {YELLOW}[WARN]{RESET} {msg}")
def info(msg): print(f"  {CYAN}[INFO]{RESET} {msg}")


def check_token() -> bool:
    print("\n[1/3] Checking bot token...")
    if not TOKEN:
        fail("TELEGRAM_BOT_TOKEN is not set in .env")
        return False
    try:
        r = requests.get(f"{BASE}/getMe", timeout=10)
        data = r.json()
        if data.get("ok"):
            bot = data["result"]
            ok(f"Bot found: @{bot['username']} (ID: {bot['id']})")
            ok(f"Can join groups: {bot.get('can_join_groups', False)}")
            return True
        else:
            fail(f"Invalid token: {data.get('description', 'unknown error')}")
            info("Get a new token from @BotFather → /mybots → API Token")
            return False
    except Exception as e:
        fail(f"Network error: {e}")
        return False


def check_channel() -> str | None:
    print(f"\n[2/3] Resolving channel '{CHAT_ID}'...")
    if not CHAT_ID:
        fail("TELEGRAM_CHAT_ID is not set in .env")
        return None
    try:
        r = requests.get(f"{BASE}/getChat", params={"chat_id": CHAT_ID}, timeout=10)
        data = r.json()
        if data.get("ok"):
            chat = data["result"]
            numeric_id = str(chat["id"])
            chat_type = chat.get("type", "?")
            title = chat.get("title", chat.get("username", "?"))
            ok(f"Channel resolved: '{title}' ({chat_type})")
            ok(f"Numeric chat ID : {numeric_id}")
            if not CHAT_ID.lstrip("-").isdigit():
                warn(f"Update your .env: TELEGRAM_CHAT_ID={numeric_id}")
            return numeric_id
        else:
            desc = data.get("description", "")
            if "not a member" in desc or "bot was kicked" in desc:
                fail("Bot is NOT a member of the channel.")
                print()
                print(f"  {YELLOW}ACTION REQUIRED:{RESET}")
                print(f"  1. Open Telegram → go to your channel/group")
                print(f"  2. Tap ⋮ → Manage Channel → Administrators")
                print(f"  3. Add Administrator → search: @{_get_bot_username()}")
                print(f"  4. Give permission: ✅ Post Messages → Save")
                print(f"  5. Re-run: python setup_telegram.py")
            elif "chat not found" in desc:
                fail(f"Chat '{CHAT_ID}' not found.")
                print()
                print(f"  {YELLOW}Possible causes:{RESET}")
                print(f"  • The username is wrong (check spelling/zeros vs letter O)")
                print(f"  • The channel is private and the bot is not yet a member")
                print(f"  • The channel was deleted or renamed")
                print()
                print(f"  {YELLOW}Fix:{RESET}")
                print(f"  Add the bot (@{_get_bot_username()}) as Admin to the channel,")
                print(f"  then re-run this script.")
            else:
                fail(f"Could not resolve channel: {desc}")
            return None
    except Exception as e:
        fail(f"Network error: {e}")
        return None


def send_test_message(numeric_id: str) -> bool:
    print(f"\n[3/3] Sending test message to {numeric_id}...")
    payload = {
        "chat_id": numeric_id,
        "text": (
            "✅ <b>Job Alert System</b>\n\n"
            "Bot connected successfully! 🎉\n"
            "You will start receiving job notifications shortly."
        ),
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(f"{BASE}/sendMessage", json=payload, timeout=10)
        data = r.json()
        if data.get("ok"):
            ok("Test message sent! Check your channel.")
            return True
        else:
            desc = data.get("description", "")
            fail(f"Send failed: {desc}")
            if "not enough rights" in desc.lower():
                warn("Bot is a member but lacks 'Post Messages' permission.")
                warn("Edit the bot's admin permissions in your channel settings.")
            return False
    except Exception as e:
        fail(f"Network error: {e}")
        return False


def _get_bot_username() -> str:
    try:
        r = requests.get(f"{BASE}/getMe", timeout=5)
        return r.json().get("result", {}).get("username", "your_bot")
    except Exception:
        return "your_bot"


def update_env_chat_id(numeric_id: str) -> None:
    """Offer to write the resolved numeric ID back to .env."""
    if CHAT_ID.lstrip("-").isdigit():
        return  # Already numeric, nothing to do

    env_path = ".env"
    try:
        with open(env_path, encoding="utf-8") as f:
            content = f.read()
        updated = content.replace(
            f"TELEGRAM_CHAT_ID={CHAT_ID}",
            f"TELEGRAM_CHAT_ID={numeric_id}"
        )
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(updated)
        ok(f".env updated: TELEGRAM_CHAT_ID={numeric_id}")
    except Exception as e:
        warn(f"Could not auto-update .env: {e}")
        info(f"Manually set: TELEGRAM_CHAT_ID={numeric_id}")


if __name__ == "__main__":
    print(f"\n{CYAN}{'='*50}")
    print(f"  Telegram Bot Setup Diagnostic")
    print(f"{'='*50}{RESET}")

    token_ok = check_token()
    if not token_ok:
        sys.exit(1)

    numeric_id = check_channel()
    if not numeric_id:
        print(f"\n{RED}Setup incomplete. Fix the issues above and re-run.{RESET}\n")
        sys.exit(1)

    sent = send_test_message(numeric_id)

    if sent:
        update_env_chat_id(numeric_id)
        print(f"\n{GREEN}✓ Setup complete! Run 'py main.py' to start scraping.{RESET}\n")
    else:
        print(f"\n{YELLOW}Bot can reach the channel but cannot post. Check permissions.{RESET}\n")
        sys.exit(1)
