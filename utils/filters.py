"""
utils/filters.py
----------------
Job relevance filter for the aggregation pipeline.

STRICT MODE:
  - Experience : Fresher / 0-2 years only.
  - Role       : Software Engineering related only.
  - Location   : India / Remote India only.
  
Relevance Scoring System:
  - Role Match: 0-50
  - Experience Match: 0-25
  - Location Match: 0-15
  - Skills Match: 0-10
  - Minimum Score: 75
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from scraper.base import Job
from utils.logger import logger


# ---------------------------------------------------------------------------
# Strict Rule Definitions
# ---------------------------------------------------------------------------

_HIGH_PRIORITY_ROLES = [
    "software engineer", "software development engineer", "sde", "sde i",
    "associate software engineer", "graduate software engineer", "backend engineer",
    "backend developer", "frontend engineer", "frontend developer",
    "full stack engineer", "full stack developer", "web developer",
    "application developer", "ai engineer", "ml engineer",
    "machine learning engineer", "data engineer", "cloud engineer",
    "devops engineer", "platform engineer", "qa automation engineer",
    "software qa engineer", "test automation engineer", "embedded software engineer",
    "mobile developer", "android developer", "ios developer",
    "react developer", "node.js developer", "python developer",
    "java developer", "c++ developer", "golang developer",
    "rust developer", "game developer", "computer vision engineer",
    "nlp engineer", "firmware engineer", "security engineer",
    "site reliability engineer"
]

_ROLE_EXCLUSIONS = [
    "sales", "marketing", "hr", "finance", "business development",
    "consultant", "account executive", "support executive",
    "customer support", "operations", "recruiter", "product manager",
    "project manager", "technical writer", "network technician",
    "electrical engineer", "mechanical engineer", "civil engineer",
    "chemical engineer", "medical", "nurse", "teacher", "professor",
    "legal", "bpo", "call center", "insurance", "relationship manager",
    "banking", "loan officer", "retail", "store manager", "telecaller",
    "content writer", "seo", "digital marketing", "graphic designer",
    "video editor", "ui designer", "ux designer", "data entry",
    "administrative"
]

_INDIA_LOCATIONS = [
    "india", "bengaluru", "bangalore", "hyderabad", "mumbai", "new delhi", "delhi",
    "pune", "chennai", "kolkata", "noida", "gurgaon", "gurugram",
    "ahmedabad", "jaipur", "kochi", "trivandrum", "chandigarh", "indore", "coimbatore"
]

_FRESHER_KEYWORDS = [
    "fresher", "0 years", "0-1 years", "0-2 years", "graduate",
    "campus", "university graduate", "new grad", "early career",
    "entry level", "associate", "junior", "trainee", "intern",
    "internship", "bachelor's degree", "recent graduate", "final year"
]

_SENIOR_KEYWORDS = [
    "senior", "lead", "principal", "architect", "manager", "director", "staff", "vp", "head"
]

_SKILLS_BONUS = [
    "python", "java", "c++", "javascript", "typescript", "react",
    "angular", "node.js", "spring boot", "django", "flask",
    "mongodb", "mysql", "postgresql", "redis", "docker",
    "kubernetes", "aws", "azure", "gcp", "git", "rest api",
    "graphql", "microservices", "linux", "oop", "dsa",
    "algorithms", "data structures", "operating systems",
    "computer networks", "sql"
]


@dataclass
class JobFilter:
    """
    Evaluates jobs using strict criteria and a scoring system.
    Only jobs with a score >= 75 are accepted.
    """
    
    class CfgStub:
        max_exp_years = 2
    cfg = CfgStub()

    def is_relevant(self, job: Job) -> bool:
        """
        Calculates the relevance score and determines if the job passes.
        """
        title = job.role.lower()
        desc = (job.description or "").lower()
        loc = job.location.lower()
        combined_text = f"{title} {desc}"

        label = f"[{job.company}] {job.role} @ {job.location}"

        # 1. Strict Role Rejections
        for exc in _ROLE_EXCLUSIONS:
            if exc == "analyst":
                if "analyst" in title and not any(kw in title for kw in ["software", "data", "security"]):
                    logger.debug(f"FILTERED (Analyst role): {label}")
                    return False
            elif exc == "consultant":
                if "consultant" in title and "developer" not in title and "software" not in title:
                    logger.debug(f"FILTERED (Consultant role): {label}")
                    return False
            # Check with word boundaries so 'manager' doesn't flag 'product manager' if we only wanted to flag exact matches,
            # but since 'product manager' is in exclusions, it's fine.
            # Using \b to avoid matching "staffing" when checking for "staff"
            elif re.search(rf"\b{re.escape(exc)}\b", title):
                logger.debug(f"FILTERED (Excluded Role '{exc}'): {label}")
                return False

        # 2. Strict Location Rejections
        # MUST explicitly mention India or an Indian city. 
        # If it just says "Remote" without India, we reject it to avoid US/Global remote jobs.
        is_india = any(kw in loc for kw in _INDIA_LOCATIONS)
        if not is_india:
            logger.debug(f"FILTERED (Not strictly India): {label}")
            return False

        # 3. Strict Experience Rejections
        
        # 3a. Reject explicit senior titles
        for kw in _SENIOR_KEYWORDS:
            if re.search(rf"\b{re.escape(kw)}\b", title):
                logger.debug(f"FILTERED (Senior Title '{kw}'): {label}")
                return False

        # 3b. Reject >2 years in text
        # Regex explanation: looks for a number (e.g., 3, 3-5, 3+, 10), 
        # followed by optional + or -, followed by 'year' or 'years' or 'yrs'
        # Captures the first number to check if it's > 2
        exp_patterns = [
            r"\b(\d+)\s*(?:\+|to|-)?\s*(?:\d+)?\s*(?:year|yrs|years?)\b",
            r"\b(\d+)\s*(?:\+)?\s*(?:year|yrs|years?)\s*of\s*experience\b"
        ]
        
        for pat in exp_patterns:
            if re.search(pat, title) or re.search(pat, job.experience.lower()):
                logger.debug(f"FILTERED (Senior Exp in Title/Exp field): {label}")
                return False
                
            # Scan description for years of experience
            for match in re.finditer(pat, desc):
                years = int(match.group(1))
                if years > 2:
                    # Context check: avoid rejecting "company has 10 years of history"
                    # We check if the phrase "experience" or "required" is somewhat near.
                    snippet_start = max(0, match.start() - 30)
                    snippet_end = min(len(desc), match.end() + 30)
                    snippet = desc[snippet_start:snippet_end]
                    if any(c in snippet for c in ["exp", "require", "minimum", "track record", "proven"]):
                        logger.debug(f"FILTERED (>{years} years exp in Desc): {label}")
                        return False

        # --- SCORING ---
        score = 0
        
        # Role Score (0-50)
        role_matched = False
        for kw in _HIGH_PRIORITY_ROLES:
            if kw in title:
                score += 50
                role_matched = True
                break
        
        if not role_matched:
            swe_desc_keywords = ["java", "python", "software", "developer", "backend", "frontend", "api"]
            if "engineer" in title or "associate" in title or "member of technical staff" in title or "sde" in title:
                if any(kw in desc for kw in swe_desc_keywords):
                    score += 40
                    role_matched = True
            
            if not role_matched and not any(kw in title for kw in ["software", "developer", "engineer", "data", "cloud", "security", "qa", "test"]):
                logger.debug(f"FILTERED (Not Tech Role): {label}")
                return False

        # Experience Score (0-25)
        exp_matched = False
        for kw in _FRESHER_KEYWORDS:
            if re.search(rf"\b{re.escape(kw)}\b", title) or re.search(rf"\b{re.escape(kw)}\b", job.experience.lower()) or re.search(rf"\b{re.escape(kw)}\b", desc):
                score += 25
                exp_matched = True
                break
                
        if not exp_matched:
            # Entry level assumed if no senior keywords were found
            score += 15
            
        # Location Score (0-15)
        score += 15 # Guaranteed to be India at this point
        
        # Skills Match (0-10)
        skills_matched = 0
        for skill in _SKILLS_BONUS:
            # Word boundary check for skills
            # C++ requires special handling in regex
            if skill == "c++":
                if "c++" in combined_text:
                    skills_matched += 1
            else:
                if re.search(rf"\b{re.escape(skill)}\b", combined_text):
                    skills_matched += 1
        
        skill_score = min(10, skills_matched * 2)
        score += skill_score

        logger.debug(f"SCORE {score} (R:{50 if role_matched else (40 if role_matched else 0)} E:{25 if exp_matched else 15} L:15 S:{skill_score}): {label}")

        if score >= 75:
            return True
        else:
            logger.debug(f"FILTERED (Low Score {score}): {label}")
            return False

    def filter_jobs(self, jobs: list[Job]) -> tuple[list[Job], int]:
        """
        Filter a list of jobs and return (accepted_jobs, rejected_count).
        """
        accepted = [j for j in jobs if self.is_relevant(j)]
        rejected = len(jobs) - len(accepted)
        return accepted, rejected
