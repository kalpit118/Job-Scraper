"""
scraper/custom.py
-----------------
Generic scraper for companies that do NOT use a standard ATS platform.

Uses Playwright (headless Chromium) to render the career page so that
JavaScript-heavy sites load properly, then parses the DOM with
BeautifulSoup / lxml.

Behaviour
---------
This scraper applies a set of heuristics to locate job-card elements:

1. Look for common CSS selectors used by popular bespoke career pages.
2. Walk sibling/parent nodes to gather role, location, and apply link.
3. Fall back to link-text matching if card selectors yield nothing.

Because every custom site differs, this scraper is intentionally
best-effort.  It will always return whatever partial data it can find
rather than crashing.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.base import BaseScraper, Job
from scraper.greenhouse import _extract_salary, _strip_html
from utils.helpers import (
    classify_work_mode,
    extract_experience,
    get_logo_url,
)
from utils.logger import logger


# Common selectors used by bespoke career pages
_CARD_SELECTORS = [
    "[data-job-id]",
    "[class*='job-card']",
    "[class*='job-item']",
    "[class*='job-listing']",
    "[class*='career-item']",
    "[class*='position-item']",
    "[class*='opening']",
    "li[class*='job']",
    "article[class*='job']",
    "tr[class*='job']",
]

_LOCATION_SELECTORS = [
    "[class*='location']",
    "[class*='city']",
    "[class*='office']",
    "[data-location]",
]

_ROLE_SELECTORS = [
    "h2", "h3", "h4",
    "[class*='title']",
    "[class*='role']",
    "[class*='position']",
]


def _get_page_html(url: str) -> str:
    """
    Render *url* with a headless Playwright browser and return the page HTML.

    Falls back to an empty string on any error so that the scraper degrades
    gracefully without crashing the pipeline.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=15_000)
            except PWTimeout:
                logger.warning(f"[Custom] Timeout waiting for networkidle on {url}, using partial content")
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        logger.error(f"[Custom] Playwright render failed for {url}: {exc}")
        return ""


def _find_cards(soup: BeautifulSoup) -> list[BeautifulSoup]:
    """Try each card selector in order, returning the first non-empty result."""
    for sel in _CARD_SELECTORS:
        cards = soup.select(sel)
        if cards:
            return cards
    return []


def _extract_text(tag, selectors: list[str]) -> str:
    """Search *tag* for the first matching sub-element and return its text."""
    for sel in selectors:
        el = tag.select_one(sel)
        if el:
            return el.get_text(separator=" ", strip=True)
    return ""


def _extract_apply_url(tag, base_url: str) -> str:
    """Return the first <a> href inside *tag*, resolved to an absolute URL."""
    a = tag.find("a", href=True)
    if a:
        return urljoin(base_url, a["href"])
    return base_url


class CustomScraper(BaseScraper):
    """
    Playwright-based scraper for bespoke career pages.

    Args:
        company_name: Human-readable company name.
        career_url: URL of the company's career / jobs page.
    """

    def __init__(self, company_name: str, career_url: str) -> None:
        super().__init__(company_name, career_url)
        self._logo_url = get_logo_url(company_name, career_url)

    def fetch_jobs(self) -> list[Job]:
        html = _get_page_html(self.career_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        cards = _find_cards(soup)

        if not cards:
            logger.warning(
                f"[{self.company_name}] No job cards matched known selectors. "
                "Falling back to link heuristic."
            )
            return self._fallback_link_scan(soup)

        logger.debug(f"[{self.company_name}] Found {len(cards)} candidate cards")
        results: list[Job] = []
        for card in cards:
            job = self._parse_card(card)
            if job:
                results.append(job)
        return results

    def _parse_card(self, card) -> Job | None:
        """Parse a single job card element."""
        role = _extract_text(card, _ROLE_SELECTORS)
        if not role:
            a = card.find("a")
            role = a.get_text(strip=True) if a else ""
        if not role:
            return None

        location = _extract_text(card, _LOCATION_SELECTORS) or "Unknown"
        apply_url = _extract_apply_url(card, self.career_url)
        full_text = card.get_text(separator=" ", strip=True)

        return Job(
            company=self.company_name,
            role=role,
            location=location,
            apply_url=apply_url,
            salary=_extract_salary(full_text),
            experience=extract_experience(full_text),
            work_mode=classify_work_mode(f"{role} {location} {full_text}"),
            logo_url=self._logo_url,
            description=full_text,
        )

    def _fallback_link_scan(self, soup: BeautifulSoup) -> list[Job]:
        """
        Last-resort: collect all links that look like job postings based on
        keywords in their text or href.
        """
        job_keywords = re.compile(
            r"\b(engineer|developer|analyst|designer|manager|scientist|intern|"
            r"architect|devops|qa|data|product|marketing|sales)\b",
            re.IGNORECASE,
        )
        jobs: list[Job] = []
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = urljoin(self.career_url, a["href"])
            if href in seen or not text:
                continue
            if job_keywords.search(text) or job_keywords.search(href):
                seen.add(href)
                jobs.append(
                    Job(
                        company=self.company_name,
                        role=text[:120],
                        location="Unknown",
                        apply_url=href,
                        logo_url=self._logo_url,
                    )
                )
        return jobs
