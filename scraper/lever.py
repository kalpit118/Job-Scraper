"""
scraper/lever.py
----------------
Scraper for companies using the Lever ATS.

Lever exposes a public JSON API at:
    https://api.lever.co/v0/postings/{company}?mode=json

The ``company`` slug is extracted from the Lever career URL:
    https://jobs.lever.co/netflix  →  company = "netflix"
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from scraper.base import BaseScraper, Job
from scraper.greenhouse import _extract_salary
from utils.helpers import (
    build_session,
    classify_work_mode,
    extract_experience,
    get_logo_url,
    safe_get,
    truncate,
)
from utils.logger import logger


def _extract_company_slug(url: str) -> str:
    """Extract the Lever company slug from a jobs.lever.co URL."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    return parts[0] if parts else ""


class LeverScraper(BaseScraper):
    """
    Fetches job listings from the Lever public postings JSON API.

    Args:
        company_name: Human-readable company name.
        career_url: Lever career URL, e.g. ``https://jobs.lever.co/netflix``.
    """

    _API_BASE = "https://api.lever.co/v0/postings/{slug}?mode=json"

    def __init__(self, company_name: str, career_url: str) -> None:
        super().__init__(company_name, career_url)
        self._session = build_session()
        self._logo_url = get_logo_url(company_name, career_url)

    def fetch_jobs(self) -> list[Job]:
        slug = _extract_company_slug(self.career_url)
        if not slug:
            logger.error(f"[{self.company_name}] Cannot extract slug from {self.career_url}")
            return []

        api_url = self._API_BASE.format(slug=slug)
        resp = safe_get(api_url, session=self._session)
        if resp is None:
            return []

        raw_jobs: list[dict] = resp.json()
        logger.debug(f"[{self.company_name}] Raw Lever jobs: {len(raw_jobs)}")
        return [self._parse_job(item) for item in raw_jobs]

    def _parse_job(self, item: dict) -> Job:
        """Convert a raw Lever posting dict into a :class:`Job`."""
        title: str = item.get("text", "")
        categories: dict = item.get("categories", {})
        location: str = (
            categories.get("location")
            or item.get("workplaceType", "")
            or "Unknown"
        )
        apply_url: str = item.get("hostedUrl", "")
        posted_ts: int = item.get("createdAt", 0)
        posted_date: str = ""
        if posted_ts:
            from datetime import datetime, timezone
            posted_date = datetime.fromtimestamp(
                posted_ts / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d")

        # Flatten description text
        lists_block: list[dict] = item.get("lists", [])
        desc_text = " ".join(
            block.get("content", "") for block in lists_block
        )
        plain_desc = re.sub(r"<[^>]+>", " ", item.get("descriptionPlain", "") or desc_text)
        combined = f"{title} {location} {plain_desc}"

        return Job(
            company=self.company_name,
            role=title,
            location=location,
            apply_url=apply_url,
            salary=_extract_salary(plain_desc),
            experience=extract_experience(plain_desc),
            work_mode=classify_work_mode(combined),
            logo_url=self._logo_url,
            posted_date=posted_date,
            description=plain_desc,
        )
