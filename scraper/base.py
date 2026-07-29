"""
scraper/base.py
---------------
Abstract base class that every platform scraper must implement.

Each concrete scraper (Greenhouse, Lever, Ashby, Custom) inherits from
:class:`BaseScraper` and overrides :meth:`fetch_jobs`.

Design rationale
----------------
Using an ABC enforces a common interface so that ``main.py`` can call
any scraper polymorphically without caring which platform it talks to.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from utils.logger import logger


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Job:
    """
    Canonical job representation returned by every scraper.

    All fields are normalised strings.  Fields that cannot be extracted
    are left as empty strings (never ``None``) to simplify downstream
    processing and SQLite storage.
    """
    company: str
    role: str
    location: str
    apply_url: str

    salary: str = "Not Mentioned"
    experience: str = "Unknown"
    work_mode: str = "Unknown"
    logo_url: str = ""
    posted_date: str = ""
    description: str = ""

    # Added automatically – not part of the scraped payload
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def dedup_key(self) -> str:
        """
        Composite key used for duplicate detection.

        Two jobs are considered identical when they share the same
        company, role **and** location (case-insensitive).
        """
        return "|".join(
            [
                self.company.strip().lower(),
                self.role.strip().lower(),
                self.location.strip().lower(),
            ]
        )


# ---------------------------------------------------------------------------
# Abstract scraper
# ---------------------------------------------------------------------------

class BaseScraper(ABC):
    """
    Base class for all job scrapers.

    Subclasses must implement :meth:`fetch_jobs` which returns a list of
    :class:`Job` objects discovered on the company's career page.

    Args:
        company_name: Display name of the company.
        career_url: Entry-point URL for the career page / API.
    """

    def __init__(self, company_name: str, career_url: str) -> None:
        self.company_name = company_name
        self.career_url = career_url

    @abstractmethod
    def fetch_jobs(self) -> list[Job]:
        """
        Scrape jobs from the company career page.

        Returns:
            List of :class:`Job` instances found.  Returns an empty list
            on failure (never raises).
        """

    def scrape(self) -> list[Job]:
        """
        Public entry-point that wraps :meth:`fetch_jobs` with error handling.

        Any unhandled exception inside ``fetch_jobs`` is caught here so that
        one broken scraper never aborts the whole pipeline.
        """
        logger.info(f"[{self.company_name}] Starting scrape → {self.career_url}")
        try:
            jobs = self.fetch_jobs()
            logger.success(f"[{self.company_name}] Found {len(jobs)} job(s)")
            return jobs
        except Exception as exc:
            logger.exception(f"[{self.company_name}] Scrape failed: {exc}")
            return []
