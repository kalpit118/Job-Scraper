"""
main.py
-------
Entry-point for the Job Alert Aggregation System.

Pipeline
--------
1. Load company list from ``config/companies.json``.
2. For each company, instantiate the correct scraper (Greenhouse / Lever / Ashby / Custom).
3. Scrape jobs.
4. Apply relevance filter (fresher, tech roles, India/Remote).
5. Filter out duplicates against the SQLite database.
6. Persist new jobs.
7. Send Telegram notifications for each new job.
8. Log a summary.

Usage
-----
    python main.py

Environment variables (via .env):
    TELEGRAM_BOT_TOKEN        – Telegram bot token
    TELEGRAM_CHAT_ID          – Target group/channel chat ID
    DB_PATH                   – Override default database path (optional)
    COMPANIES_PATH            – Override default companies JSON path (optional)
    SEND_SUMMARY              – Set to "false" to suppress the end-of-run summary
    FILTER_ENABLED            – Set to "false" to disable relevance filtering
    FILTER_MAX_EXP_YEARS      – Max years of experience to accept (default: 2)
    FILTER_LOCATION_KEYWORDS  – Comma-separated location whitelist keywords
    FILTER_ROLE_KEYWORDS      – Comma-separated tech-role title keywords
    FILTER_EXCLUSION_KEYWORDS – Comma-separated non-tech role keywords
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env before any other import reads environment variables
load_dotenv()

from database.db import (
    count_jobs,
    count_pending,
    get_pending_notifications,
    init_db,
    insert_job,
    is_duplicate,
    mark_notified,
)
from scraper.ashby import AshbyScraper
from scraper.base import BaseScraper, Job
from scraper.custom import CustomScraper
from scraper.greenhouse import GreenhouseScraper
from scraper.lever import LeverScraper
from telegram.bot import TELEGRAM_READY, send_job_notification, send_summary
from utils.filters import JobFilter
from utils.helpers import sleep_between
from utils.logger import logger

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

COMPANIES_PATH: Path = Path(os.getenv("COMPANIES_PATH", "config/companies.json"))
SEND_SUMMARY_FLAG: bool = os.getenv("SEND_SUMMARY", "true").lower() != "false"
INTER_REQUEST_DELAY: float = float(os.getenv("INTER_REQUEST_DELAY", "1.0"))

_SCRAPER_MAP: dict[str, type[BaseScraper]] = {
    "greenhouse": GreenhouseScraper,
    "lever": LeverScraper,
    "ashby": AshbyScraper,
    "custom": CustomScraper,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_companies() -> list[dict]:
    """
    Load and validate the company list from the JSON configuration file.

    Returns:
        List of company dicts, each containing ``name``, ``url``, and ``type``.

    Raises:
        SystemExit: If the file is missing or malformed.
    """
    if not COMPANIES_PATH.exists():
        logger.critical(f"Companies file not found: {COMPANIES_PATH}")
        sys.exit(1)

    try:
        with open(COMPANIES_PATH, encoding="utf-8") as fh:
            companies: list[dict] = json.load(fh)
    except json.JSONDecodeError as exc:
        logger.critical(f"Invalid JSON in {COMPANIES_PATH}: {exc}")
        sys.exit(1)

    required_keys = {"name", "url", "type"}
    valid = []
    for entry in companies:
        if not required_keys.issubset(entry):
            logger.warning(f"Skipping malformed company entry: {entry}")
            continue
        if entry["type"] not in _SCRAPER_MAP:
            logger.warning(
                f"Unknown scraper type '{entry['type']}' for {entry['name']}. "
                f"Valid types: {list(_SCRAPER_MAP)}"
            )
            continue
        valid.append(entry)

    logger.info(f"Loaded {len(valid)} valid companies from {COMPANIES_PATH}")
    return valid


def build_scraper(company: dict) -> BaseScraper:
    """
    Instantiate the appropriate scraper for a company config dict.

    Args:
        company: Dict with keys ``name``, ``url``, ``type``.

    Returns:
        A concrete :class:`BaseScraper` instance.
    """
    scraper_cls = _SCRAPER_MAP[company["type"]]
    return scraper_cls(company_name=company["name"], career_url=company["url"])


def process_jobs(jobs: list[Job]) -> tuple[list[Job], int]:
    """
    Filter duplicates, insert new jobs, and return new jobs + skipped count.

    Args:
        jobs: Raw job list from a scraper.

    Returns:
        A tuple of (new_jobs, duplicate_count).
    """
    new_jobs: list[Job] = []
    duplicate_count = 0

    for job in jobs:
        if is_duplicate(job):
            duplicate_count += 1
            logger.debug(f"Duplicate skipped: {job.company} | {job.role} | {job.location}")
            continue
        inserted = insert_job(job)
        if inserted:
            new_jobs.append(job)

    return new_jobs, duplicate_count


def _notify_pending() -> int:
    """
    Re-send any jobs that were stored in a previous run but never notified.

    This handles the case where Telegram was unavailable during a past run.
    Jobs are marked notified only after a confirmed successful send.

    Returns:
        Number of previously-pending jobs successfully sent.
    """
    if not TELEGRAM_READY:
        return 0

    pending = get_pending_notifications()
    if not pending:
        return 0

    logger.info(f"Re-sending {len(pending)} previously unnotified job(s) from DB...")
    sent = 0
    for row in pending:
        # Reconstruct a minimal Job for formatting
        job = Job(
            company=row["company"],
            role=row["role"],
            location=row["location"],
            apply_url=row["url"],
            salary=row["salary"],
            experience=row["experience"],
            work_mode=row["mode"],
            logo_url=row["logo"],
            posted_date=row["posted"],
            created_at=row["created_at"],
        )
        success = send_job_notification(job)
        if success:
            mark_notified(row["id"])
            sent += 1
        sleep_between(0.5)

    if sent:
        logger.success(f"Re-sent {sent}/{len(pending)} pending notifications")
    return sent


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline() -> None:
    """
    Execute the full job aggregation pipeline.

    Steps:
    1. Initialise DB (with migration).
    2. Re-send previously unnotified jobs (if Telegram is now ready).
    3. Load companies.
    4. Scrape → relevance filter → dedup → persist → notify.
    5. Log summary.
    """
    run_start = time.monotonic()
    logger.info("=" * 60)
    logger.info("Job Alert System — pipeline starting")
    logger.info("=" * 60)

    init_db()

    # --- Step 2: Re-deliver previously queued notifications ---
    pending_sent = _notify_pending()

    companies = load_companies()

    # Initialise the relevance filter once (reads config from .env)
    job_filter = JobFilter()
    logger.info(
        f"Filter profile: experience ≤ {job_filter.cfg.max_exp_years} yrs | "
        f"tech roles only | India / Remote"
    )

    if not TELEGRAM_READY:
        logger.warning(
            "Telegram NOT ready — jobs will be saved to DB and notified next run."
        )

    total_new: int = 0
    total_notified: int = 0
    total_duplicates: int = 0
    total_filtered: int = 0
    total_errors: int = 0

    for company in companies:
        scraper = build_scraper(company)
        raw_jobs = scraper.scrape()  # Always returns a list, never raises

        if not raw_jobs:
            total_errors += 1
        else:
            # --- Stage 1: Relevance filter ---
            relevant_jobs, filtered_out = job_filter.filter_jobs(raw_jobs)
            total_filtered += filtered_out
            if filtered_out:
                logger.info(
                    f"[{company['name']}] "
                    f"{filtered_out}/{len(raw_jobs)} jobs filtered out "
                    f"({len(relevant_jobs)} passed)"
                )

            # --- Stage 2: Dedup + persist ---
            new_jobs, dupes = process_jobs(relevant_jobs)
            total_new += len(new_jobs)
            total_duplicates += dupes

            # --- Stage 3: Telegram notifications (only if ready) ---
            if TELEGRAM_READY:
                for job in new_jobs:
                    success = send_job_notification(job)
                    if success:
                        # Find the DB id by dedup key and mark notified
                        from database.db import _get_connection
                        with _get_connection() as conn:
                            row = conn.execute(
                                "SELECT id FROM jobs WHERE dedup_key = ?",
                                (job.dedup_key(),)
                            ).fetchone()
                        if row:
                            mark_notified(row["id"])
                            total_notified += 1
                    sleep_between(0.5)  # Avoid Telegram rate limits

        sleep_between(INTER_REQUEST_DELAY)

    elapsed = time.monotonic() - run_start
    db_total = count_jobs()
    still_pending = count_pending()

    logger.info("=" * 60)
    logger.info(f"Pipeline complete in {elapsed:.1f}s")
    logger.info(f"  New jobs found   : {total_new}")
    logger.info(f"  Filtered out     : {total_filtered}")
    logger.info(f"  Notified         : {total_notified + pending_sent}")
    logger.info(f"  Pending (queued) : {still_pending}")
    logger.info(f"  Duplicates skip  : {total_duplicates}")
    logger.info(f"  Companies errored: {total_errors}")
    logger.info(f"  DB total jobs    : {db_total}")
    logger.info("=" * 60)

    if SEND_SUMMARY_FLAG and (total_notified + pending_sent) > 0:
        send_summary(new_count=total_notified + pending_sent, total_count=db_total)


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_pipeline()
