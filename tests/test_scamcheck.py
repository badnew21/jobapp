from datetime import datetime, timedelta, timezone

from jobapp.scamcheck import assess, check_domain, company_domain, registered_domain

LEGIT = [
    {"title": "Crew Member", "company": "McDonald's", "url": "https://careers.mcdonalds.com/job/123",
     "description": "Take orders, handle cash and card payments, check out customers, keep the dining room "
                    "clean. Food safety training provided. Flexible schedules, weekends required. $15/hr."},
    {"title": "Cashier", "company": "Kroger", "url": "https://kroger.wd5.myworkdayjobs.com/x/job/1",
     "description": "Scan items, cash handling, check ID for age-restricted sales, deposit funds at end of "
                    "shift per store policy, help customers find products. Background check required after offer.",
     "salary": "$14 - $16/hr"},
    {"title": "Server", "company": "Olive Garden", "url": "https://www.indeed.com/viewjob?jk=1",
     "description": "Greet guests, take orders, run food, process payments on the POS. Must be 18 or older. "
                    "Apply online and we'll contact you to set up an in-person interview."},
]

SCAMS = [
    ({"title": "Remote Data Entry Clerk", "company": "Global Solutions", "salary": "$40 - $45/hr",
      "url": "https://globalsolutions-careers.com/apply",
      "description": "No experience needed! Interview on Telegram with our hiring manager. We will mail you a "
                     "check to buy your equipment, deposit the check with mobile deposit and send the remaining "
                     "balance to our vendor."},
     ["chat app", "check", "unusually high"]),
    ({"title": "Package Inspector (Work from Home)", "company": "", "url": "https://x.example/apply",
      "description": "Receive packages at home, inspect and reship them. Earn $500 per week from home. "
                     "Contact hr.dept.jobs@gmail.com"},
     ["Reshipping", "personal account", "No company name"]),
    ({"title": "Customer Service Rep", "company": "Acme Corp", "url": "https://acme.com/jobs",
      "description": "Great pay. There is a $49 training fee for your starter kit. Send your social security "
                     "number and bank account with your application so we can set up direct deposit. "
                     "Long description " * 3},
     ["pay for something", "SSN"]),
]


def test_legit_postings_are_not_flagged():
    for job in LEGIT:
        result = assess(job)
        assert result.level == "low", (job["company"], result.reasons)


def test_scam_postings_are_flagged_high():
    for job, expected in SCAMS:
        result = assess(job)
        assert result.level == "high", result.reasons
        text = " ".join(result.reasons)
        for word in expected:
            assert word.lower() in text.lower(), (word, result.reasons)
        assert "Better Business Bureau" in result.links


def test_domain_helpers():
    assert registered_domain("https://careers.mcdonalds.com/a") == "mcdonalds.com"
    assert registered_domain("https://shop.example.co.uk") == "example.co.uk"
    assert company_domain({"url": "https://kroger.wd5.myworkdayjobs.com/x"}) == ""   # ATS, not the employer
    assert company_domain({"url": "https://indeed.com/x", "company_url": "https://www.acme.com"}) == "acme.com"


class FakeResp:
    def __init__(self, status, data=None):
        self.status_code, self._data = status, data or {}

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, born_days_ago, loads=True):
        self.born = (datetime.now(timezone.utc) - timedelta(days=born_days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.loads = loads

    def get(self, url, **kw):
        if "rdap.org" in url:
            return FakeResp(200, {"events": [{"eventAction": "registration", "eventDate": self.born}]})
        if not self.loads:
            raise ConnectionError("down")
        return FakeResp(200)


def test_new_domain_is_high_risk():
    flags, age = check_domain("acme-hiring.com", FakeSession(30), cache={})
    assert 29 <= age <= 31
    reasons = " ".join(r for _, r in flags)
    assert "registered only" in reasons and "careers'-style" in reasons
    job = {"title": "Cashier", "company": "Acme", "url": "https://acme-hiring.com/apply",
           "description": "Cash handling and customer service at our busy store. " * 5}
    assert assess(job, online=True, session=FakeSession(30), cache={}).level == "high"


def test_old_domain_is_fine_and_dead_site_is_flagged():
    assert check_domain("kroger.com", FakeSession(9000), cache={})[0] == []
    flags, _ = check_domain("ghostco.com", FakeSession(3000, loads=False), cache={})
    assert flags == [("medium", "Company website ghostco.com didn't load")]


class OfflineSession:
    def get(self, url, **kw):
        raise ConnectionError("no internet")


def test_no_internet_does_not_flag_everything():
    assert check_domain("kroger.com", OfflineSession(), cache={}) == ([], None)


def test_auto_apply_skips_scams(tmp_path, monkeypatch):
    from jobapp import apply_assist
    from jobapp.search import Job
    from jobapp.tracker import Tracker

    t = Tracker(tmp_path / "t.db")
    job, _ = SCAMS[0]
    t.add_jobs([Job(id="s", source="x", location="", **job)])
    row = t.rows()[0]
    monkeypatch.setattr(apply_assist, "assess", lambda j, online: assess(j, online=False))
    status, note = apply_assist.safety_gate(row, t, {"skip_risky": True})
    assert status == "skipped" and note.startswith("Possible scam")
    assert t.research("s")["level"] == "high"
    assert apply_assist.safety_gate(row, t, {"skip_risky": False}) is None

    legit = dict(LEGIT[0], id="l")
    t.add_jobs([Job(source="x", location="", **legit)])
    assert apply_assist.safety_gate(t.rows()[0] if t.rows()[0]["id"] == "l" else t.rows()[1], t, {}) is None
