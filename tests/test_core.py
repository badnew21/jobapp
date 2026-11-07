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
