"""
scraper/greenhouse.py
---------------------
Scraper for companies that use the Greenhouse ATS.

Greenhouse exposes a public JSON API at:
    https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true

The board token is the slug that appears in the company's Greenhouse URL, e.g.
    https://boards.greenhouse.io/atlassian  →  board_token = "atlassian"

No authentication is required.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from scraper.base import BaseScraper, Job
from utils.helpers import (
    build_session,
    classify_work_mode,
    extract_experience,
    get_logo_url,
    safe_get,
    truncate,
)
from utils.logger import logger


def _extract_board_token(url: str) -> Optional[str]:
    """
    Parse the Greenhouse board token from a career URL.

    Handles formats:
    - https://boards.greenhouse.io/company
    - https://company.greenhouse.io/
    - https://jobs.lever.co/company  (wrong type, returns None gracefully)
    """
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]
    if path_parts:
        return path_parts[-1]
    # Subdomain pattern: company.greenhouse.io
    host_parts = parsed.netloc.split(".")
    if "greenhouse" in host_parts:
        idx = host_parts.index("greenhouse")
        if idx > 0:
            return host_parts[idx - 1]
    return None


def _parse_location(job_json: dict) -> str:
    """Extract and normalise the location field from a Greenhouse job object."""
    offices = job_json.get("offices", [])
    if offices:
        return ", ".join(o.get("name", "") for o in offices if o.get("name"))
    return job_json.get("location", {}).get("name", "") or "Unknown"


def _strip_html(html: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", " ", html or "").strip()


class GreenhouseScraper(BaseScraper):
    """
    Fetches job listings from the Greenhouse Jobs Board JSON API.

    Args:
        company_name: Human-readable company name.
        career_url: Greenhouse board URL, e.g.
            ``https://boards.greenhouse.io/atlassian``.
    """

    _API_BASE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

    def __init__(self, company_name: str, career_url: str) -> None:
        super().__init__(company_name, career_url)
        self._session = build_session()
        self._logo_url = get_logo_url(company_name, career_url)

    def fetch_jobs(self) -> list[Job]:
        token = _extract_board_token(self.career_url)
        if not token:
            logger.error(f"[{self.company_name}] Cannot extract board token from {self.career_url}")
            return []

        api_url = self._API_BASE.format(token=token)
        resp = safe_get(f"{api_url}?content=true", session=self._session)
        if resp is None:
            return []

        data = resp.json()
        raw_jobs: list[dict] = data.get("jobs", [])
        logger.debug(f"[{self.company_name}] Raw API jobs: {len(raw_jobs)}")

        results: list[Job] = []
        for item in raw_jobs:
            results.append(self._parse_job(item))
        return results

    def _parse_job(self, item: dict) -> Job:
        """Convert a raw Greenhouse API job dict into a :class:`Job`."""
        title: str = item.get("title", "")
        location: str = _parse_location(item)
        apply_url: str = item.get("absolute_url", "")
        posted_at: str = item.get("updated_at", "")[:10]

        # Combine all text fields for classification
        content: str = _strip_html(item.get("content", ""))
        combined_text = f"{title} {location} {content}"

        return Job(
            company=self.company_name,
            role=title,
            location=location,
            apply_url=apply_url,
            salary=_extract_salary(content),
            experience=extract_experience(content),
            work_mode=classify_work_mode(combined_text),
            logo_url=self._logo_url,
            posted_date=posted_at,
            description=content,
        )


def _extract_salary(text: str) -> str:
    """
    Look for explicit salary mentions in job content.

    Returns the raw snippet if found, otherwise ``"Not Mentioned"``.
    """
    patterns = [
        re.compile(r"[\$₹£€]\s?\d[\d,]*(?:\s?[-–]\s?[\$₹£€]?\s?\d[\d,]*)?(?:\s?(?:LPA|k|K|lakh|per\s+year|pa))?", re.IGNORECASE),
        re.compile(r"\d[\d,]+\s?(?:LPA|lakh|k)\b", re.IGNORECASE),
    ]
    for pat in patterns:
        match = pat.search(text)
        if match:
            return truncate(match.group(0).strip(), 60)
    return "Not Mentioned"
