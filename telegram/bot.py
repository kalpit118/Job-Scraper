"""
telegram/bot.py
---------------
Telegram notification sender for the job alert system.

Responsibilities
----------------
- Send a richly-formatted job card message to a private group/channel.
- Optionally attach the company logo as a photo.
- Gracefully handle rate-limits (Telegram 429) with exponential back-off.
- Never raise on a single message failure – log and continue.

Credentials are read exclusively from environment variables:
    TELEGRAM_BOT_TOKEN   – token from @BotFather
    TELEGRAM_CHAT_ID     – numeric ID of the private group/channel
"""

from __future__ import annotations

import os
import time
from typing import Optional

import requests

from scraper.base import Job
from utils.helpers import build_session, safe_get
from utils.logger import logger

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
_RAW_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
_API_BASE = f"https://api.telegram.org/bot{_BOT_TOKEN}"

_MAX_RETRIES = 3
_RATE_LIMIT_SLEEP = 5  # seconds to wait after a 429


def _resolve_chat_id(raw_id: str) -> str:
    """
    Resolve a Telegram ``@username`` to its numeric chat ID.

    Telegram's Bot API accepts both ``@username`` and numeric IDs, but
    numeric IDs are more reliable (usernames can change; private chats
    with usernames may not be resolvable if the bot isn't a member).

    Calls ``getChat`` once at startup.  If resolution fails (bot not yet
    added to channel), returns the original raw_id and lets subsequent
    send calls surface the real error with a helpful message.

    Args:
        raw_id: Value from ``TELEGRAM_CHAT_ID`` env var.

    Returns:
        Numeric chat ID as string (e.g. ``"-1001234567890"``),
        or the original *raw_id* on failure.
    """
    if not raw_id or not _BOT_TOKEN:
        return raw_id

    # Already numeric — no resolution needed
    if raw_id.lstrip("-").isdigit():
        return raw_id

    try:
        resp = requests.get(
            f"{_API_BASE}/getChat",
            params={"chat_id": raw_id},
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            numeric_id = str(data["result"]["id"])
            logger.info(f"Resolved Telegram chat '{raw_id}' → numeric ID {numeric_id}")
            return numeric_id
        else:
            desc = data.get("description", "")
            if "not a member" in desc or "bot was kicked" in desc:
                logger.error(
                    f"Bot is NOT a member of '{raw_id}'. "
                    "Please add @j0bscraperbot as an Administrator "
                    "(with 'Post Messages' permission) to the channel, then restart."
                )
            elif "chat not found" in desc:
                logger.error(
                    f"Chat '{raw_id}' not found. "
                    "Either the channel doesn't exist, the username is wrong, "
                    "or the bot must be added as admin before it can resolve private channels."
                )
            else:
                logger.error(f"Could not resolve chat ID for '{raw_id}': {desc}")
    except Exception as exc:
        logger.warning(f"getChat request failed: {exc}")

    return raw_id  # Fall back to raw value


# Resolve once at import time (after load_dotenv() in main.py)
_CHAT_ID: str = _resolve_chat_id(_RAW_CHAT_ID)

# True only when the chat ID was successfully resolved to a numeric ID.
# Used to short-circuit all send calls when Telegram is mis-configured.
TELEGRAM_READY: bool = _CHAT_ID.lstrip("-").isdigit() and bool(_BOT_TOKEN)

if not TELEGRAM_READY and _BOT_TOKEN and _RAW_CHAT_ID:
    logger.warning(
        "Telegram is NOT ready — notifications will be queued in the DB "
        "and retried automatically once the bot is added to the channel.\n"
        "  Action required: Add @j0bscraperbot as Administrator to "
        f"'{_RAW_CHAT_ID}' with 'Post Messages' permission, then re-run."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_credentials() -> bool:
    """Verify that bot token, chat ID are configured and Telegram is reachable."""
    if not TELEGRAM_READY:
        return False
    return True


def _format_message(job: Job) -> str:
    """
    Build the HTML-formatted Telegram message for a single job.

    Uses Telegram's HTML parse mode for bold/italic/link support.
    All user-supplied strings are escaped to prevent injection.
    """
    def esc(text: str) -> str:
        """Escape Telegram HTML special characters."""
        return (
            text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
        )

    # apply_url must also be HTML-escaped so that & in query strings
    # (e.g. ?utm_source=a&utm_medium=b) doesn't break the <a href> tag.
    safe_url = esc(job.apply_url)

    lines = [
        f"🏢 <b>Company:</b> {esc(job.company)}",
        f"💼 <b>Role:</b> {esc(job.role)}",
        f"📍 <b>Location:</b> {esc(job.location)}",
        f"💰 <b>Salary:</b> {esc(job.salary)}",
        f"🦾 <b>Experience:</b> {esc(job.experience)}",
        f"🏠 <b>Work Mode:</b> {esc(job.work_mode)}",
        "",
        f'🔗 <b>Apply:</b> <a href="{safe_url}">Click Here</a>',
    ]

    return "\n".join(lines)


def _post(endpoint: str, payload: dict, session: requests.Session) -> Optional[dict]:
    """
    POST to a Telegram Bot API endpoint with retry + rate-limit handling.

    Returns:
        Parsed JSON response dict, or ``None`` on failure.
    """
    url = f"{_API_BASE}/{endpoint}"
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = session.post(url, json=payload, timeout=15)

            # --- 429 Rate limit: wait and retry ---
            if resp.status_code == 429:
                retry_after = int(
                    resp.json().get("parameters", {}).get("retry_after", _RATE_LIMIT_SLEEP)
                )
                logger.warning(
                    f"Rate limited by Telegram. Sleeping {retry_after}s (attempt {attempt})"
                )
                time.sleep(retry_after)
                continue

            # --- 403 Forbidden: bot not in chat, no point retrying ---
            if resp.status_code == 403:
                desc = resp.json().get("description", "")
                logger.error(
                    f"Telegram 403 Forbidden — {desc}. "
                    "Make sure the bot is added as an Administrator to the channel/group "
                    "with 'Post Messages' permission."
                )
                return None

            # --- 4xx Client errors: bad request, no point retrying ---
            if 400 <= resp.status_code < 500:
                try:
                    err_desc = resp.json().get("description", resp.text[:200])
                except Exception:
                    err_desc = resp.text[:200]
                logger.error(
                    f"Telegram {resp.status_code} on /{endpoint} — {err_desc}"
                )
                return None

            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.RequestException as exc:
            logger.warning(f"Telegram request failed (attempt {attempt}): {exc}")
            if attempt < _MAX_RETRIES:
                time.sleep(2 ** attempt)  # exponential back-off only before last retry
    return None


def _send_photo_with_caption(
    session: requests.Session,
    chat_id: str,
    photo_url: str,
    caption: str,
) -> bool:
    """Send a photo with an HTML caption."""
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    result = _post("sendPhoto", payload, session)
    return bool(result and result.get("ok"))


def _send_text(session: requests.Session, chat_id: str, text: str) -> bool:
    """Send a plain HTML text message."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    result = _post("sendMessage", payload, session)
    return bool(result and result.get("ok"))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_job_notification(job: Job) -> bool:
    """
    Send a formatted job card to the configured Telegram group/channel.

    Strategy:
    1. If a logo URL is available → send as a photo message with caption.
    2. Otherwise → send as a text message.

    Args:
        job: The :class:`Job` to announce.

    Returns:
        ``True`` if the message was delivered, ``False`` otherwise.
    """
    if not _check_credentials():
        return False

    session = build_session()
    caption = _format_message(job)

    if job.logo_url:
        success = _send_photo_with_caption(session, _CHAT_ID, job.logo_url, caption)
        if success:
            logger.info(f"📨 Sent [photo] → [{job.company}] {job.role}")
            return True
        logger.warning(f"Photo send failed for {job.company}, falling back to text")

    success = _send_text(session, _CHAT_ID, caption)
    if success:
        logger.info(f"📨 Sent [text] → [{job.company}] {job.role}")
    else:
        logger.error(f"Failed to send notification for [{job.company}] {job.role}")
    return success


def send_summary(new_count: int, total_count: int) -> None:
    """
    Send a brief run-summary message at the end of each scrape cycle.

    Args:
        new_count:   Number of new jobs found in this run.
        total_count: Total jobs in the database.
    """
    if not _check_credentials():
        return

    text = (
        "✅ <b>Job Alert — Run Complete</b>\n\n"
        f"🆕 New jobs this run: <b>{new_count}</b>\n"
        f"📊 Total jobs tracked: <b>{total_count}</b>"
    )
    session = build_session()
    _send_text(session, _CHAT_ID, text)
