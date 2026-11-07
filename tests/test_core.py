import io

from docx import Document

from jobapp.keywords import analyze, contains, normalize
from jobapp.resume import build_tailored_docx, docx_to_text, existing_skills, split_sections
from jobapp.search import Job, SearchOptions, _adzuna_params, matches_job_type, parse_adzuna, parse_remotive
from jobapp.tracker import Tracker

RESUME = """Jane Doe
Springfield, IL | 555-123-4567 | jane@example.com

SUMMARY
Friendly cashier with three years of experience.

EXPERIENCE
Cashier, QuickMart (2021-2024)
- Handled customer service at the register
- Stocked shelves and helped with inventory

SKILLS
Customer service, Cash handling, Teamwork

EDUCATION
Springfield High School, Diploma
"""

POSTINGS = [
    "Crew member wanted. Must have food safety knowledge, cash handling and customer service. Drive-thru experience a plus.",
    "Join our team! Cash handling, POS system, food safety certification (ServSafe) preferred. Fast-paced environment.",
    "Cashier needed: customer service, cash handling, upselling, opening and closing duties.",
]


def test_contains_variants():
    t = normalize("Experience with drive thru orders and POS systems")
    assert contains(t, "drive-thru")
    assert contains(t, "pos system")
    assert not contains(t, "forklift")


def test_analyze_finds_missing_keywords():
    report = analyze(RESUME, POSTINGS, "Fast food / Restaurant")
    assert "cash handling" in report.present
    assert "customer service" in report.present
    assert "food safety" in report.missing
    assert 0 < report.score < 100


def test_tailored_resume_adds_approved_keywords_and_raises_score():
    before = analyze(RESUME, POSTINGS, "Fast food / Restaurant").score
    data = build_tailored_docx(RESUME, {"full_name": "Jane Doe", "email": "jane@example.com"},
                               "Crew Member", ["food safety", "pos system"])
    text = docx_to_text(data)
    assert "Food Safety" in text and "POS System" in text
    assert "QuickMart" in text and "EDUCATION" in text
    assert text.count("SKILLS") == 1  # original skills section merged, not duplicated
    assert analyze(text, POSTINGS, "Fast food / Restaurant").score > before
    Document(io.BytesIO(data))  # valid docx


def test_sections_and_skills():
    heads = [h for h, _ in split_sections(RESUME)]
    assert heads == ["", "summary", "experience", "skills", "education"]
    assert existing_skills(RESUME) == ["Customer service", "Cash handling", "Teamwork"]


def test_adzuna_params_and_parse():
    opts = SearchOptions(location="60601", radius_miles=10, job_types=["Part time"], industry="Grocery")
    p = _adzuna_params(opts, "stocker", "retail-jobs")
    assert p["where"] == "60601" and p["distance"] == 16 and p["part_time"] == 1
    assert p["category"] == "retail-jobs" and p["what"] == "stocker"

    job = parse_adzuna({
        "id": 1, "title": "<strong>Stocker</strong>", "description": "Night shift, remote not possible",
        "company": {"display_name": "FoodCo"}, "location": {"display_name": "Chicago, IL"},
        "redirect_url": "https://x", "contract_time": "part_time", "salary_min": 15, "salary_max": 18,
        "created": "2026-11-01T00:00:00Z",
    })
    assert job.title == "Stocker" and job.company == "FoodCo" and job.salary == "$15 - $18"
    assert job.posted == "2026-11-01"


def test_job_type_filter():
    j = parse_remotive({"id": 2, "title": "Support", "company_name": "R", "url": "u", "job_type": "full_time"})
    assert j.remote
    assert matches_job_type(j, ["Remote"])
    assert matches_job_type(j, ["Remote", "Full time"])
    assert not matches_job_type(j, ["Remote", "Part time"])
    local = Job(id="a", source="x", title="t", company="c", location="l", description="", url="", job_type="")
    assert matches_job_type(local, ["Part time"])  # unknown type kept
    assert not matches_job_type(local, ["Remote"])


def test_tracker(tmp_path):
    t = Tracker(tmp_path / "t.db")
    job = Job(id="a", source="x", title="t", company="c", location="l", description="d", url="u")
    assert t.add_jobs([job, job]) == 1
    t.set_status("a", "queued")
    assert t.status_of("a") == "queued"
    assert t.counts()["queued"] == 1


def test_pdf_round_trip_and_per_job_tailoring():
    from jobapp.resume import build_structure, pdf_to_text, read_resume, render_pdf, tailor_for_job

    pdf = render_pdf(build_structure(RESUME, {}, "Cashier", []))
    text = read_resume("resume.pdf", pdf)
    assert existing_skills(text) == ["Customer service", "Cash handling", "Teamwork"]

    job = {"title": "Crew Member - Part Time - Chicago", "company": "Burger Co", "description": POSTINGS[0]}
    bank = ["customer service", "food safety", "forklift"]
    data, matched = tailor_for_job(text, {"full_name": "Jane Doe"}, job, bank, "pdf")
    out = pdf_to_text(data)
    assert matched == ["customer service", "food safety"]
    assert "Forklift" in out                       # in her bank, listed after the matched ones
    assert out.index("Food Safety") < out.index("Forklift")
    assert "forklift" not in out.split("SKILLS")[0].lower()  # summary only mentions matched skills
    assert "QuickMart" in out


def test_clean_title_and_filename():
    from jobapp.resume import clean_title, resume_filename

    assert clean_title("Crew Member - Part Time - Chicago, IL") == "Crew Member"
    assert resume_filename({"company": "Kroger/Ralphs Inc."}, "Jane Doe", "pdf") == "Jane Doe Resume - KrogerRalphs Inc.pdf"


def test_jobspy_rows_are_converted():
    import pandas as pd
    from jobspy.model import JobPost, Location

    from jobapp.search import search_jobs, search_jobspy

    calls = []

    def fake_scrape(**kw):
        calls.append(kw)
        posts = [
            JobPost(id="in-1", site="indeed", job_url="https://indeed.com/viewjob?jk=1",
                    job_url_direct="https://careers.burgerco.com/apply/1", title="Crew Member",
                    company="Burger Co", location=Location(city="Springfield", state="IL"),
                    job_type=["parttime"], min_amount=14.0, max_amount=17.0, interval="hourly",
                    is_remote=False, description="**Food safety** and cash handling"),
            JobPost(id="in-2", site="indeed", job_url="https://indeed.com/viewjob?jk=2", title="Cashier",
                    company="Grocer"),
        ]
        return pd.DataFrame([p.model_dump() for p in posts])

    opts = SearchOptions(location="62701", radius_miles=10, job_types=["Part time"],
                         industry="Fast food / Restaurant", max_days_old=7)
    jobs = search_jobspy(opts, ["Indeed"], scrape=fake_scrape)
    a = next(j for j in jobs if j.company == "Burger Co")
    assert a.url == "https://careers.burgerco.com/apply/1"   # company site preferred
    assert a.job_type == "part_time" and a.salary == "$14 - $17/hr"
    assert a.location == "Springfield, IL" and a.description == "Food safety and cash handling"
    b = next(j for j in jobs if j.company == "Grocer")
    assert b.url.startswith("https://indeed.com") and b.salary == "" and b.posted == ""
    assert calls[0]["job_type"] == "parttime" and calls[0]["hours_old"] == 168
    assert calls[0]["distance"] == 10 and calls[0]["site_name"] == ["indeed"]

    # No Adzuna key and Adzuna not picked: no Adzuna error shown.
    import jobapp.search as S
    orig = S.search_jobspy
    S.search_jobspy = lambda o, sites: search_jobspy(o, sites, scrape=fake_scrape)
    try:
        found, warnings = search_jobs(opts)
    finally:
        S.search_jobspy = orig
    assert warnings == [] and len(found) == 2


def test_google_query_and_blocked_site_warning(monkeypatch):
    import pandas as pd

    import jobapp.search as S

    calls = []

    def fake_scrape(**kw):
        calls.append(kw)
        if kw["site_name"] == ["google"]:
            return pd.DataFrame()  # what JobSpy returns when Google blocks it
        return pd.DataFrame([{"site": "indeed", "id": "1", "job_url": "https://indeed.com/1",
                              "title": "Cashier", "company": "Publix", "description": "Run the register."}])

    real = S.search_jobspy
    monkeypatch.setattr(S, "search_jobspy", lambda o, sites: real(o, sites, scrape=fake_scrape))
    opts = SearchOptions(location="33870", job_types=["Part time"], extra_keywords="cashier",
                         sources=["Indeed", "Google Jobs"])
    jobs, warnings = S.search_jobs(opts)
    assert [j.company for j in jobs] == ["Publix"]
    assert len(warnings) == 1 and warnings[0].startswith("Google Jobs returned no jobs")
    assert all("google_search_term" not in c for c in calls)  # JobSpy builds Google's query itself
    assert {tuple(c["site_name"]) for c in calls} == {("indeed",), ("google",)}
