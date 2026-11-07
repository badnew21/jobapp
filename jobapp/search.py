"""Job search across public job APIs.

Providers:
  * JobSpy   - no key needed. Reads public listings from Indeed, ZipRecruiter,
               Glassdoor and Google Jobs (location, radius, job type, age).
  * Adzuna   - optional, free API key (https://developer.adzuna.com).
  * Remotive - no key needed. Remote jobs only.
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field, asdict

import requests

from .industries import INDUSTRIES
from .keywords import contains, normalize

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
    company_url: str = ""       # employer's own website, when the source gives it
    emails: list[str] = field(default_factory=list)

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
    sources: list[str] = field(default_factory=lambda: ["Indeed"])


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
    search = opts.extra_keywords or next((q for q in preset["queries"] if q), "")
    if search:
        params["search"] = search
    resp = s.get(REMOTIVE_URL, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return [parse_remotive(i) for i in resp.json().get("jobs", [])]


# ---------------------------------------------------------------- JobSpy

JOBSPY_SITES = {"Indeed": "indeed", "ZipRecruiter": "zip_recruiter", "Glassdoor": "glassdoor",
                "Google Jobs": "google"}
SOURCES = list(JOBSPY_SITES) + ["Adzuna", "Remotive"]


def _clean(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v != v:  # NaN from pandas
        return ""
    return str(v)


def _jobspy_salary(row: dict) -> str:
    lo, hi = row.get("min_amount"), row.get("max_amount")
    lo = None if _clean(lo) == "" else float(lo)
    hi = None if _clean(hi) == "" else float(hi)
    text = _format_salary(lo, hi)
    interval = _clean(row.get("interval"))
    if text and interval:
        text += {"hourly": "/hr", "yearly": "/yr", "monthly": "/mo", "weekly": "/wk", "daily": "/day"}.get(interval, "")
    return text


def parse_jobspy(row: dict) -> Job:
    types = _clean(row.get("job_type"))
    first = types.split(",")[0].strip()
    title, desc = _clean(row.get("title")), _clean(row.get("description"))
    desc = re.sub(r"[*_#`]+|\\", "", desc)  # strip markdown markup
    remote = row.get("is_remote")
    return Job(
        id=f"{_clean(row.get('site'))}:{_clean(row.get('id')) or _clean(row.get('job_url'))}",
        source=_clean(row.get("site")).replace("_", " ").title(),
        title=title,
        company=_clean(row.get("company")),
        location=_clean(row.get("location")),
        description=desc,
        # The company's own application page skips the job board's login wall.
        url=_clean(row.get("job_url_direct")) or _clean(row.get("job_url")),
        job_type={"fulltime": "full_time", "parttime": "part_time"}.get(first, first),
        remote=bool(remote) if _clean(remote) != "" else bool(REMOTE_PATTERN.search(f"{title} {desc}")),
        salary=_jobspy_salary(row),
        posted=_clean(row.get("date_posted"))[:10],
        company_url=_clean(row.get("company_url_direct")),
        emails=[e.strip() for e in _clean(row.get("emails")).split(",") if e.strip()],
    )


def search_jobspy(opts: SearchOptions, sites: list[str], scrape=None) -> list[Job]:
    if scrape is None:
        try:
            from jobspy import scrape_jobs as scrape
        except ImportError as e:
            raise RuntimeError("JobSpy isn't installed. Run: python -m pip install -r requirements.txt") from e
    preset = INDUSTRIES.get(opts.industry, INDUSTRIES["Any"])
    queries = preset["queries"][:3]
    per_query = max(10, opts.max_results // len(queries))
    picked = [t for t in ("Full time", "Part time", "Contract") if t in opts.job_types]
    job_type = {"Full time": "fulltime", "Part time": "parttime", "Contract": "contract"}[picked[0]] \
        if len(picked) == 1 else None
    remote_only = "Remote" in opts.job_types and not opts.location
    jobs: dict[str, Job] = {}
    for query in queries:
        term = " ".join(x for x in [query, opts.extra_keywords] if x).strip() or "jobs"
        where = opts.location or "USA"
        df = scrape(
            site_name=[JOBSPY_SITES[s] for s in sites],
            search_term=term,
            google_search_term=f"{term} jobs near {where} since last {max(1, opts.max_days_old)} days",
            location=opts.location or None,
            distance=opts.radius_miles,
            is_remote=remote_only,
            job_type=job_type,
            results_wanted=per_query,
            hours_old=opts.max_days_old * 24,
            description_format="markdown",
            verbose=0,
        )
        for row in df.to_dict("records"):
            job = parse_jobspy(row)
            jobs.setdefault(job.id, job)
        if len(jobs) >= opts.max_results:
            break
    return list(jobs.values())


# ---------------------------------------------------------------- combined

# Words too general to show a job matches the search on their own.
GENERIC_WORDS = {"jobs", "job", "work", "worker", "associate", "team", "member", "staff", "remote",
                 "part", "time", "full", "restaurant", "store", "grocery", "assistant", "general"}


def search_terms(opts: SearchOptions) -> list[str]:
    preset = INDUSTRIES.get(opts.industry, INDUSTRIES["Any"])
    extra = [t.strip() for t in re.split(r"[,;]", opts.extra_keywords) if t.strip()]
    return [q for q in preset["queries"] if q] + extra


def is_relevant(job: Job, terms: list[str]) -> bool:
    """True if the job plausibly matches what she searched for.

    Job sites pad results with loosely related postings (a "cashier" search on a
    remote board returns developer jobs). Keep a job only if its title has one of
    the search words, or its description has a whole search phrase.
    """
    if not terms:
        return True
    title = normalize(job.title)
    desc = normalize(job.description)
    for term in terms:
        t = normalize(term)
        if contains(title, t) or contains(desc, t):
            return True
        words = [w for w in t.split() if len(w) > 2 and w not in GENERIC_WORDS]
        if any(contains(title, w) for w in words):
            return True
    return False


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
    sites = [s for s in opts.sources if s in JOBSPY_SITES]
    if sites:
        try:
            jobs += search_jobspy(opts, sites)
        except Exception as e:  # noqa: BLE001 - surface any provider failure to the UI
            warnings.append(f"{', '.join(sites)}: {e}")

    if "Adzuna" in opts.sources:
        try:
            jobs += search_adzuna(opts)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"Adzuna: {e}")

    if "Remotive" in opts.sources or ("Remote" in opts.job_types and not sites):
        try:
            jobs += search_remotive(opts)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"Remotive: {e}")

    terms = search_terms(opts)
    seen: set[tuple[str, str]] = set()
    unique: list[Job] = []
    for job in jobs:
        key = (job.title.lower().strip(), job.company.lower().strip())
        if key in seen or not matches_job_type(job, opts.job_types) or not is_relevant(job, terms):
            continue
        seen.add(key)
        unique.append(job)
    return unique[: opts.max_results], warnings
