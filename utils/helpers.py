"""
utils/helpers.py
----------------
Shared utility helpers used across scrapers and the Telegram bot.

Responsibilities
----------------
- Robust HTTP GET with retry + timeout.
- Work-mode classification from free text.
- Experience string normalisation.
- Company logo URL resolution via Clearbit / Google favicons.
"""

from __future__ import annotations

import re
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from utils.logger import logger

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_TIMEOUT = 15  # seconds
_MAX_RETRIES = 3
_BACKOFF_FACTOR = 0.5


def build_session() -> requests.Session:
    """
    Return a :class:`requests.Session` pre-configured with retries,
    backoff and a realistic browser User-Agent.
    """
    session = requests.Session()
    retry = Retry(
        total=_MAX_RETRIES,
        read=_MAX_RETRIES,
        connect=_MAX_RETRIES,
        backoff_factor=_BACKOFF_FACTOR,
        status_forcelist={500, 502, 503, 504, 429},
        allowed_methods={"GET"},
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def safe_get(url: str, session: Optional[requests.Session] = None, **kwargs) -> Optional[requests.Response]:
    """
    Perform a GET request with timeout, returning ``None`` on failure.

    Args:
        url: Target URL.
        session: Optional pre-built session (creates a temporary one if absent).
        **kwargs: Additional kwargs forwarded to :func:`requests.Session.get`.

    Returns:
        :class:`requests.Response` on success, ``None`` on any error.
    """
    sess = session or build_session()
    kwargs.setdefault("timeout", _TIMEOUT)
    try:
        response = sess.get(url, **kwargs)
        response.raise_for_status()
        return response
    except requests.exceptions.Timeout:
        logger.debug(f"Timeout fetching {url}")
    except requests.exceptions.HTTPError as exc:
        logger.warning(f"HTTP {exc.response.status_code} fetching {url}")
    except requests.exceptions.ConnectionError:
        logger.debug(f"Connection error (DNS/network) fetching {url}")
    except requests.exceptions.RequestException as exc:
        logger.debug(f"Request failed for {url}: {exc}")
    return None


# ---------------------------------------------------------------------------
# Work-mode classification
# ---------------------------------------------------------------------------

_REMOTE_KEYWORDS = re.compile(
    r"\b(remote|work[- ]?from[- ]?home|wfh|fully[- ]remote|distributed)\b",
    re.IGNORECASE,
)
_HYBRID_KEYWORDS = re.compile(r"\b(hybrid|flexible|partial[- ]remote)\b", re.IGNORECASE)
_ONSITE_KEYWORDS = re.compile(
    r"\b(on[- ]?site|in[- ]office|office[- ]based|in[- ]person)\b", re.IGNORECASE
)


def classify_work_mode(text: str) -> str:
    """
    Determine work mode from a job description / title / location string.

    Returns one of: ``"Remote"``, ``"Hybrid"``, ``"On-site"``, ``"Unknown"``.
    """
    if not text:
        return "Unknown"
    if _REMOTE_KEYWORDS.search(text):
        return "Remote"
    if _HYBRID_KEYWORDS.search(text):
        return "Hybrid"
    if _ONSITE_KEYWORDS.search(text):
        return "On-site"
    return "Unknown"


# ---------------------------------------------------------------------------
# Experience extraction
# ---------------------------------------------------------------------------

_EXP_RANGE = re.compile(r"(\d+)\s*[-–to]+\s*(\d+)\s*(?:years?|yrs?)", re.IGNORECASE)
_EXP_SINGLE = re.compile(r"(\d+)\+?\s*(?:years?|yrs?)", re.IGNORECASE)
_FRESHER = re.compile(r"\b(fresh|fresher|entry[- ]?level|graduate|0[- ]year)\b", re.IGNORECASE)


def extract_experience(text: str) -> str:
    """
    Parse an experience requirement string from job description text.

    Returns human-readable labels such as ``"0–2 Years"``, ``"Freshers"``,
    ``"5+ Years"``, or ``"Unknown"`` when nothing can be inferred.
    """
    if not text:
        return "Unknown"
    if _FRESHER.search(text):
        return "Freshers"
    match = _EXP_RANGE.search(text)
    if match:
        lo, hi = match.group(1), match.group(2)
        return f"{lo}–{hi} Years"
    match = _EXP_SINGLE.search(text)
    if match:
        return f"{match.group(1)}+ Years"
    return "Unknown"


# ---------------------------------------------------------------------------
# Logo resolution
# ---------------------------------------------------------------------------

# Known ATS hostnames whose path slug is the real company identifier
_ATS_HOSTS = {
    "boards.greenhouse.io",
    "greenhouse.io",
    "jobs.lever.co",
    "lever.co",
    "jobs.ashbyhq.com",
    "ashbyhq.com",
    "apply.workable.com",
    "jobs.smartrecruiters.com",
}


def _resolve_company_domain(company_name: str, career_url: str) -> str:
    """
    Return the most likely real company domain from a career URL.

    For ATS platforms (Greenhouse, Lever, Ashby, …) the real company is
    encoded in the URL *path*, not the hostname.  We extract it and append
    ``.com`` as the best-effort domain.

    For custom career pages the company's own domain is the hostname.
    """
    from urllib.parse import urlparse
    parsed = urlparse(career_url)
    host = parsed.netloc.lstrip("www.")

    if host in _ATS_HOSTS:
        # Slug is the first path segment: boards.greenhouse.io/stripe → stripe
        slug = next((p for p in parsed.path.split("/") if p), "")
        if slug:
            return f"{slug}.com"

    # For custom domains, use the hostname directly (strip port if present)
    return host.split(":")[0]


def get_logo_url(company_name: str, company_url: str) -> str:
    """
    Attempt to resolve a usable company logo URL via the Clearbit Logo API.

    The function derives the real company domain from the career URL,
    handling ATS platforms (Greenhouse, Lever, Ashby) where the company
    slug lives in the URL path rather than the hostname.

    Returns:
        A Clearbit PNG URL string, or empty string when unavailable.
        Empty string causes the caller to fall back to a text-only message.
    """
    try:
        domain = _resolve_company_domain(company_name, company_url)
        if not domain:
            return ""

        clearbit_url = f"https://logo.clearbit.com/{domain}"
        resp = safe_get(clearbit_url, timeout=5)
        if resp and resp.status_code == 200:
            return clearbit_url

        # No reliable fallback — Google favicons are HTML pages, not images,
        # and Telegram's sendPhoto rejects them with 400 Bad Request.
        return ""
    except Exception as exc:
        logger.warning(f"Could not resolve logo for {company_name}: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def truncate(text: str, max_len: int = 200) -> str:
    """Safely truncate a string to *max_len* characters."""
    if not text:
        return ""
    return text[:max_len].rstrip() + ("…" if len(text) > max_len else "")


def sleep_between(seconds: float = 1.0) -> None:
    """Polite delay between HTTP requests to avoid rate-limiting."""
    time.sleep(seconds)
