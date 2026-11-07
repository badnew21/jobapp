"""Scam check for job postings.

Two layers:
  1. The posting itself (no internet needed): the patterns the FTC and job
     boards list for fake jobs - fees, check cashing, reshipping, chat-app
     interviews, asking for bank info or an SSN up front, pay that's too good,
     personal email addresses, no company name.
  2. The company's website (online): whether it loads, and how old the domain
     is. Scam outfits register fresh domains; real employers rarely have a
     careers site that's a few weeks old. Domain ages come from RDAP, the free
     public replacement for WHOIS.

It also builds links for checking the company by hand (BBB, reviews, a
"<company> scam" search).

A clean result doesn't prove a job is real, and a flag doesn't prove it's
fake. It points out what's worth a second look.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import requests

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "domain_cache.json"
RDAP_URL = "https://rdap.org/domain/{}"
TIMEOUT = 12

# Application systems and job boards. Their domains say nothing about the employer.
KNOWN_HOSTS = (
    "myworkdayjobs.com", "workday.com", "greenhouse.io", "lever.co", "icims.com", "taleo.net",
    "oraclecloud.com", "smartrecruiters.com", "jobvite.com", "paylocity.com", "adp.com",
    "ultipro.com", "ukg.com", "bamboohr.com", "successfactors.com", "jazzhr.com", "applytojob.com",
    "breezy.hr", "workable.com", "recruitee.com", "paycom.com", "paycor.com", "dayforcehcm.com",
    "harri.com", "snagajob.com", "fountain.com", "hirebridge.com", "appone.com", "brassring.com",
    "indeed.com", "ziprecruiter.com", "glassdoor.com", "linkedin.com", "google.com", "adzuna.com",
    "remotive.com", "monster.com", "careerbuilder.com", "simplyhired.com", "talent.com",
    "rippling.com", "gusto.com", "teamtailor.com", "pinpointhq.com", "jobs.net", "governmentjobs.com",
)
FREE_EMAIL = re.compile(
    r"[\w.+-]+@(gmail|yahoo|hotmail|outlook|aol|icloud|protonmail|proton|live|mail|gmx|ymail)\.\w+", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# (severity, pattern, reason). Severity: high = classic scam move, medium = worth checking.
RED_FLAGS: list[tuple[str, str, str]] = [
    ("high", r"(training|registration|application|processing|background check|onboarding) fee"
             r"|(pay|purchase|buy)\b.{0,40}\b(starter kit|equipment|software|certification|uniform kit)",
     "Asks you to pay for something to get the job"),
    ("high", r"(deposit|cash) (the |a |your )?checks?\b|mobile (check )?deposit|money orders?"
             r"|send (back )?the (remaining|balance|difference|extra)",
     "Mentions depositing a check or sending money back (fake-check scam)"),
    ("high", r"(buy|purchase)\b.{0,30}\bgift cards?", "Asks you to buy gift cards"),
    ("high", r"\bre-?ship|package (forwarding|inspector|processor)|receive (packages|parcels) at (your )?home",
     "Reshipping packages from home (often stolen goods)"),
    ("high", r"\b(telegram|whatsapp|signal app|google hangouts|wickr|wire app)\b",
     "Interview or contact through a chat app"),
    ("high", r"\b(bitcoin|crypto(currency)?|usdt)\b|wire (transfer|the money|funds)",
     "Mentions crypto or wiring money"),
    ("high", r"(social security( number)?|ssn|bank account|routing number|credit card)\b.{0,60}"
             r"\b(to apply|with your application|before (the |your )?interview|to be considered|upfront)",
     "Wants your SSN or bank details before an interview"),
    ("medium", r"\bno interview\b|hired (immediately )?without (an )?interview",
     "Hiring with no interview"),
    ("medium", r"\b(secret|mystery) shopper\b|\bpersonal assistant\b.{0,60}\b(remote|from home|online)",
     "Job type commonly used by scammers"),
    ("medium", r"\$\s?\d{3,}(,\d{3})?\s?(per|a|/|every)\s?(day|week)\b.{0,80}\b(no experience|from home|part[- ]time)"
             r"|\b(no experience|from home)\b.{0,80}\$\s?\d{3,}(,\d{3})?\s?(per|a|/|every)\s?(day|week)",
     "Promises big daily or weekly pay for easy work"),
    ("medium", r"\b(text|sms)\b.{0,30}\b(to apply|for (an )?interview)\b",
     "Asks you to apply or interview by text message"),
]


LABELS = {"low": "🟢 Looks OK", "check": "🟡 Check first", "high": "🔴 Possible scam"}


def risk_label(level: str) -> str:
    return LABELS.get(level, level)


@dataclass
class Assessment:
    level: str = "low"                          # low / check / high
    reasons: list[str] = field(default_factory=list)
    domain: str = ""
    domain_age_days: int | None = None
    links: dict[str, str] = field(default_factory=dict)
    online_checked: bool = False

    @property
    def label(self) -> str:
        return risk_label(self.level)

    def to_dict(self) -> dict:
        return asdict(self)


def registered_domain(url_or_host: str) -> str:
    host = urlparse(url_or_host).netloc if "//" in url_or_host else url_or_host
    host = host.split("@")[-1].split(":")[0].lower().strip(".")
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "ac") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def is_known_host(domain: str) -> bool:
    return any(domain == h or domain.endswith("." + h) for h in KNOWN_HOSTS)


def _slug(name: str) -> str:
    name = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|company|group|the|us|usa)\b", "", name.lower())
    return re.sub(r"[^a-z0-9]", "", name)


def research_links(company: str, location: str = "") -> dict[str, str]:
    q = quote_plus(company)
    return {
        "Better Business Bureau": f"https://www.bbb.org/search?find_text={q}&find_loc={quote_plus(location)}",
        "Search \"scam\" reports": f"https://www.google.com/search?q=%22{q}%22+job+scam",
        "Employee reviews (Indeed)": f"https://www.indeed.com/companies/search?q={q}",
        "Employee reviews (Glassdoor)": f"https://www.glassdoor.com/Search/results.htm?keyword={q}",
        "BBB Scam Tracker": f"https://www.bbb.org/scamtracker/lookupscam?searchText={q}",
    }


def check_posting(job: dict) -> list[tuple[str, str]]:
    """Flags from the posting text alone. Returns [(severity, reason)]."""
    title, company = job.get("title", ""), job.get("company", "").strip()
    text = f"{title}\n{job.get('description', '')}"
    low = text.lower()
    flags: list[tuple[str, str]] = []
    for severity, pattern, reason in RED_FLAGS:
        if re.search(pattern, low):
            flags.append((severity, reason))

    emails = set(EMAIL.findall(text)) | set(job.get("emails") or [])
    if any(FREE_EMAIL.fullmatch(e) for e in emails):
        flags.append(("medium", "Contact email is a personal account (Gmail, Yahoo, etc.)"))

    if not company or company.lower() in ("confidential", "private", "private company", "n/a", "undisclosed"):
        flags.append(("medium", "No company name given"))

    m = re.search(r"\$\s?(\d+(?:\.\d+)?)\s*(?:-\s*\$?\s?(\d+(?:\.\d+)?))?\s*/hr", job.get("salary", ""))
    if m:
        top = float(m.group(2) or m.group(1))
        if top >= 35 and re.search(r"data entry|no experience|entry[- ]level|package|assistant|chat support", low):
            flags.append(("medium", f"Pay (${top:.0f}/hr) is unusually high for this kind of job"))

    url = job.get("url", "")
    if url and company:
        dom = registered_domain(url)
        slug = _slug(company)
        if not is_known_host(dom) and slug and slug[:5] not in dom.replace("-", ""):
            flags.append(("low", f"Apply link goes to {dom}, which doesn't look like {company}'s site"))
    if len(job.get("description", "")) < 150:
        flags.append(("low", "Very short job description"))
    return flags


# ---------------------------------------------------------------- online

def _load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache))
    except Exception:  # noqa: BLE001
        pass


def domain_age_days(domain: str, session: requests.Session) -> int | None:
    resp = session.get(RDAP_URL.format(domain), timeout=TIMEOUT,
                       headers={"Accept": "application/rdap+json"})
    if resp.status_code != 200:
        return None
    for event in resp.json().get("events", []):
        if event.get("eventAction") == "registration" and event.get("eventDate"):
            born = datetime.fromisoformat(event["eventDate"].replace("Z", "+00:00"))
            if born.tzinfo is None:
                born = born.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - born).days
    return None


def site_loads(domain: str, session: requests.Session) -> bool:
    for url in (f"https://{domain}", f"https://www.{domain}"):
        try:
            if session.get(url, timeout=TIMEOUT, allow_redirects=True).status_code < 500:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def company_domain(job: dict) -> str:
    """The employer's own domain, if we can tell it."""
    for key in ("company_url", "url"):
        url = job.get(key) or ""
        if url:
            dom = registered_domain(url)
            if dom and not is_known_host(dom):
                return dom
    return ""


def check_domain(domain: str, session: requests.Session | None = None,
                 cache: dict | None = None) -> tuple[list[tuple[str, str]], int | None]:
    s = session or requests.Session()
    cache = _load_cache() if cache is None else cache
    entry = cache.get(domain)
    if entry is None:
        age = loads = None
        try:
            age = domain_age_days(domain, s)
        except Exception:  # noqa: BLE001
            pass
        try:
            loads = site_loads(domain, s)
        except Exception:  # noqa: BLE001
            pass
        entry = {"age": age, "loads": loads, "checked": datetime.now().isoformat(timespec="seconds")}
        if age is not None or loads:
            cache[domain] = entry
            _save_cache(cache)

    flags: list[tuple[str, str]] = []
    age = entry.get("age")
    if age is not None:
        if age < 180:
            flags.append(("high", f"Company website {domain} was registered only {age} days ago"))
        elif age < 365:
            flags.append(("medium", f"Company website {domain} is less than a year old"))
        if age < 365 and re.search(r"career|jobs?|hiring|recruit|staffing|hr\b|-hr|work", domain):
            flags.append(("high", f"{domain} is a new 'careers'-style domain, a common scam setup"))
    # Only trust "didn't load" when the domain lookup worked; otherwise it's
    # probably our own connection that's down.
    if entry.get("loads") is False and age is not None:
        flags.append(("medium", f"Company website {domain} didn't load"))
    return flags, age


def assess(job: dict, online: bool = False, session: requests.Session | None = None,
           cache: dict | None = None) -> Assessment:
    flags = check_posting(job)
    result = Assessment(links=research_links(job.get("company", ""), job.get("location", "")))
    domain = company_domain(job)
    result.domain = domain
    if online and domain:
        dflags, result.domain_age_days = check_domain(domain, session, cache)
        flags += dflags
        result.online_checked = True

    severities = [s for s, _ in flags]
    if "high" in severities or severities.count("medium") >= 3:
        result.level = "high"
    elif "medium" in severities or severities.count("low") >= 2:
        result.level = "check"
    order = {"high": 0, "medium": 1, "low": 2}
    result.reasons = [r for s, r in sorted(flags, key=lambda f: order[f[0]])]
    return result
