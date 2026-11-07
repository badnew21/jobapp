"""Job search across public job APIs.

Providers:
  * Adzuna  - free API key (https://developer.adzuna.com). Handles local jobs:
              location + radius, full/part time, category.
  * Remotive - no key needed. Remote jobs only.
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field, asdict

import requests

from .industries import INDUSTRIES

ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
TIMEOUT = 20
MILES_TO_KM = 1.609344

REMOTE_PATTERN = re.compile(r"\b(remote|work from home|wfh|telecommute|telework)\b", re.I)


@dataclass
class Job:
    id: str
    source: str
    title: str
    company: str
    location: str
    description: str
    url: str
    job_type: str = ""          # full_time / part_time / contract / ""
    remote: bool = False
    salary: str = ""
    posted: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchOptions:
    location: str = ""
    radius_miles: int = 15
    job_types: list[str] = field(default_factory=list)   # values from industries.JOB_TYPES
    industry: str = "Any"
    extra_keywords: str = ""
    max_days_old: int = 14
    max_results: int = 100
    country: str = "us"


def strip_html(text: str) -> str:
    text = re.sub(r"<(br|/p|/li|/div)[^>]*>", "\n", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _format_salary(lo, hi) -> str:
    if not lo and not hi:
        return ""
    if lo and hi and round(lo) != round(hi):
        return f"${lo:,.0f} - ${hi:,.0f}"
    return f"${(lo or hi):,.0f}"


# ---------------------------------------------------------------- Adzuna

def _adzuna_params(opts: SearchOptions, query: str, category: str | None) -> dict:
    params = {
        "app_id": os.environ.get("ADZUNA_APP_ID", ""),
        "app_key": os.environ.get("ADZUNA_APP_KEY", ""),
        "results_per_page": 50,
        "max_days_old": opts.max_days_old,
        "sort_by": "date",
        "content-type": "application/json",
    }
    what = " ".join(x for x in [query, opts.extra_keywords] if x).strip()
    if "Remote" in opts.job_types and not opts.location:
        what = f"{what} remote".strip()
    if what:
        params["what"] = what
    if opts.location:
        params["where"] = opts.location
        params["distance"] = max(1, round(opts.radius_miles * MILES_TO_KM))
    if category:
        params["category"] = category
    # Adzuna only lets you send one of these, so send it when exactly one is picked.
    picked = [t for t in ("Full time", "Part time") if t in opts.job_types]
    if picked == ["Full time"]:
        params["full_time"] = 1
    elif picked == ["Part time"]:
        params["part_time"] = 1
    if "Contract" in opts.job_types and not picked:
        params["contract"] = 1
    return params


def parse_adzuna(result: dict) -> Job:
    desc = strip_html(result.get("description", ""))
    title = strip_html(result.get("title", ""))
    return Job(
        id=f"adzuna:{result.get('id')}",
        source="Adzuna",
        title=title,
        company=(result.get("company") or {}).get("display_name", ""),
        location=(result.get("location") or {}).get("display_name", ""),
        description=desc,
        url=result.get("redirect_url", ""),
        job_type=result.get("contract_time") or result.get("contract_type") or "",
        remote=bool(REMOTE_PATTERN.search(f"{title} {desc}")),
        salary=_format_salary(result.get("salary_min"), result.get("salary_max")),
        posted=(result.get("created") or "")[:10],
        tags=[(result.get("category") or {}).get("label", "")],
    )


def search_adzuna(opts: SearchOptions, session: requests.Session | None = None) -> list[Job]:
    if not os.environ.get("ADZUNA_APP_ID") or not os.environ.get("ADZUNA_APP_KEY"):
        raise RuntimeError(
            "Adzuna keys missing. Get a free key at https://developer.adzuna.com "
            "and put ADZUNA_APP_ID / ADZUNA_APP_KEY in your .env file."
        )
    s = session or requests.Session()
    preset = INDUSTRIES.get(opts.industry, INDUSTRIES["Any"])
    jobs: dict[str, Job] = {}
    for query in preset["queries"]:
        for category in ([preset["adzuna_category"], None] if preset["adzuna_category"] else [None]):
            page = 1
            while len(jobs) < opts.max_results and page <= 3:
                url = ADZUNA_URL.format(country=opts.country, page=page)
                resp = s.get(url, params=_adzuna_params(opts, query, category), timeout=TIMEOUT)
                if resp.status_code == 400 and category:
                    break  # unknown category for this country; the uncategorized pass covers it
                resp.raise_for_status()
                results = resp.json().get("results", [])
                for r in results:
                    job = parse_adzuna(r)
                    jobs.setdefault(job.id, job)
                if len(results) < 50:
                    break
                page += 1
            if category and jobs:
                break  # category search worked, no need for the broad one
        if len(jobs) >= opts.max_results:
            break
    return list(jobs.values())


# ---------------------------------------------------------------- Remotive

def parse_remotive(item: dict) -> Job:
    return Job(
        id=f"remotive:{item.get('id')}",
        source="Remotive",
        title=item.get("title", ""),
        company=item.get("company_name", ""),
        location=item.get("candidate_required_location", "") or "Remote",
        description=strip_html(item.get("description", "")),
        url=item.get("url", ""),
        job_type=item.get("job_type", ""),
        remote=True,
        salary=item.get("salary", "") or "",
        posted=(item.get("publication_date") or "")[:10],
        tags=item.get("tags", []) or [],
    )


def search_remotive(opts: SearchOptions, session: requests.Session | None = None) -> list[Job]:
    s = session or requests.Session()
    preset = INDUSTRIES.get(opts.industry, INDUSTRIES["Any"])
    params: dict = {"limit": opts.max_results}
    if preset["remotive_category"]:
        params["category"] = preset["remotive_category"]
    if opts.extra_keywords:
        params["search"] = opts.extra_keywords
    resp = s.get(REMOTIVE_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return [parse_remotive(i) for i in resp.json().get("jobs", [])]


# ---------------------------------------------------------------- combined

def matches_job_type(job: Job, job_types: list[str]) -> bool:
    if not job_types:
        return True
    wanted = set(job_types)
    if wanted == {"Remote"}:
        return job.remote
    if "Remote" in wanted and not job.remote:
        return False
    mapping = {"Full time": "full_time", "Part time": "part_time", "Contract": "contract"}
    hours = {mapping[t] for t in wanted if t in mapping}
    # Postings without a stated type are kept: lots of hourly jobs leave it blank.
    return not hours or not job.job_type or job.job_type in hours


def search_jobs(opts: SearchOptions) -> tuple[list[Job], list[str]]:
    """Run every provider that applies. Returns (jobs, warnings)."""
    jobs: list[Job] = []
    warnings: list[str] = []
    only_remote = opts.job_types == ["Remote"]

    if opts.location or not only_remote:
        try:
            jobs += search_adzuna(opts)
        except Exception as e:  # noqa: BLE001 - surface any provider failure to the UI
            warnings.append(f"Adzuna: {e}")

    if "Remote" in opts.job_types:
        try:
            jobs += search_remotive(opts)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"Remotive: {e}")

    seen: set[tuple[str, str]] = set()
    unique: list[Job] = []
    for job in jobs:
        key = (job.title.lower().strip(), job.company.lower().strip())
        if key in seen or not matches_job_type(job, opts.job_types):
            continue
        seen.add(key)
        unique.append(job)
    return unique[: opts.max_results], warnings
