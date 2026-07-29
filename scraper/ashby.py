"""
scraper/ashby.py
----------------
Scraper for companies using the Ashby ATS.

Ashby exposes a public GraphQL endpoint:
    https://api.ashbyhq.com/posting-api/job-board/{slug}

The slug is extracted from the career URL:
    https://jobs.ashbyhq.com/openai  →  slug = "openai"
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
)
from utils.logger import logger


def _extract_slug(url: str) -> str:
    """Extract the Ashby organisation slug from a jobs.ashbyhq.com URL."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    # jobs.ashbyhq.com/slug  or  ashbyhq.com/slug
    return parts[0] if parts else ""


class AshbyScraper(BaseScraper):
    """
    Fetches job listings from the Ashby public job-board API.

    Args:
        company_name: Human-readable company name.
        career_url: Ashby career URL, e.g. ``https://jobs.ashbyhq.com/openai``.
    """

    _API_BASE = "https://api.ashbyhq.com/posting-api/job-board/{slug}"

    def __init__(self, company_name: str, career_url: str) -> None:
        super().__init__(company_name, career_url)
        self._session = build_session()
        self._logo_url = get_logo_url(company_name, career_url)

    def fetch_jobs(self) -> list[Job]:
        slug = _extract_slug(self.career_url)
        if not slug:
            logger.error(f"[{self.company_name}] Cannot extract slug from {self.career_url}")
            return []

        api_url = self._API_BASE.format(slug=slug)
        resp = safe_get(api_url, session=self._session)
        if resp is None:
            return []

        data: dict = resp.json()
        raw_jobs: list[dict] = data.get("jobs", [])
        logger.debug(f"[{self.company_name}] Raw Ashby jobs: {len(raw_jobs)}")
        return [self._parse_job(item) for item in raw_jobs]

    def _parse_job(self, item: dict) -> Job:
        """Convert a raw Ashby job dict into a :class:`Job`.

        Note: The ``location`` field varies by company — it may be a plain
        string (e.g. ``"San Francisco"``) or a dict with ``locationStr``/
        ``name`` keys.  Both shapes are handled defensively here.
        """
        title: str = item.get("title", "")

        # location can be str | dict | None depending on Ashby company config
        location_raw = item.get("location", {})
        if isinstance(location_raw, str):
            location: str = location_raw or "Unknown"
        elif isinstance(location_raw, dict):
            location = (
                location_raw.get("locationStr")
                or location_raw.get("name")
                or "Unknown"
            )
        else:
            location = "Unknown"

        apply_url: str = item.get("jobUrl") or item.get("applyUrl", "")
        posted_date: str = (item.get("publishedDate") or "")[:10]

        description: str = re.sub(r"<[^>]+>", " ", item.get("descriptionHtml") or "")
        secondary_locations: list[str] = [
            loc.get("locationStr", "") for loc in item.get("secondaryLocations", [])
        ]
        combined_text = " ".join(
            filter(None, [title, location, description] + secondary_locations)
        )

        return Job(
            company=self.company_name,
            role=title,
            location=location,
            apply_url=apply_url,
            salary=_extract_salary(description),
            experience=extract_experience(description),
            work_mode=classify_work_mode(combined_text),
            logo_url=self._logo_url,
            posted_date=posted_date,
            description=description,
        )
