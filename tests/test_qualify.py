from jobapp.qualify import check_fit

RESUME = """Shift Manager, Culver's. Led closing shifts, cash handling, customer service, food safety.
Team Trainer. Kennel Technician: pet care, medication administration. Administrative Assistant: data entry,
Excel, Google Sheets, QuickBooks, bookkeeping. Graphic design, Adobe Photoshop."""
QUALS = {"education": "Some college", "credentials": ["Driver's license"], "years": 10}


def fit(title, desc, quals=QUALS):
    return check_fit({"title": title, "description": desc}, quals, RESUME)


def test_entry_level_jobs_are_good():
    assert fit("Crew Member", "Customer service, cash handling. No experience necessary. Must be 16+.").level == "good"
    assert fit("Kennel Attendant", "1 year of pet care experience preferred. High school diploma or GED.").level == "good"
    assert fit("Cashier", "Valid driver's license required. 2 years of customer service experience.").level == "good"
    assert fit("Shift Leader", "2+ years of restaurant or customer service experience required.").level == "good"


def test_hard_requirements_rule_jobs_out():
    r = fit("Registered Nurse - Med Surg", "Active Florida RN license required. BSN preferred.")
    assert r.level == "no" and any("Registered Nurse" in x for x in r.reasons)
    assert fit("Delivery Driver", "Must have a Class A CDL and clean record.").level == "no"
    assert fit("Senior Accountant", "Bachelor's degree in accounting required. CPA a plus.").level == "no"
    r = fit("Office Coordinator", "Bachelor's degree required. Microsoft Office.")
    assert r.reasons == ["Requires bachelor's degree"]
    r = fit("Payroll Specialist", "Minimum of 5 years of payroll experience required.")
    assert r.level == "no" and "payroll" in r.reasons[0]
    assert fit("Team Member", "Must have 12+ years of experience.").level == "no"   # more years than she has


def test_preferred_or_quick_requirements_are_a_stretch():
    r = fit("Office Assistant", "Associate degree preferred. Data entry and Excel.")
    assert r.level == "stretch" and r.reasons == ["Prefers associate degree"]
    assert fit("Daycare Assistant", "CPR certification required.").level == "stretch"
    assert fit("Assistant Store Manager", "Customer service and cash handling.").level == "stretch"
    assert fit("Vet Tech", "Help with animal care.").level == "stretch"
    # Certification after hire isn't a barrier.
    assert fit("Caregiver", "CNA certification must be obtained within 90 days of hire.").level == "good"


def test_credentials_she_has_count():
    q = QUALS | {"credentials": ["Driver's license", "CNA"]}
    assert fit("Home Health Aide", "Current CNA certification required.", q).level == "good"
    assert fit("Home Health Aide", "Current CNA certification required.").level == "no"


def test_tech_titles_are_not_qualified():
    for title in ["Full-Stack Developer", "Software Engineer, AI Coding Tasks", "Tech Lead Full-Stack Rails Engineer",
                  "Registered Nurse", "Data Analyst"]:
        assert fit(title, "Great team, remote.").level == "no", title
    assert fit("Vet Tech", "Help with animal care.").level == "stretch"


def test_search_results_must_match_the_search():
    from jobapp.search import Job, SearchOptions, is_relevant, search_terms

    def job(title, desc="Remote role with a great team."):
        return Job(id=title, source="x", title=title, company="c", location="", description=desc, url="")

    terms = search_terms(SearchOptions(industry="Any", extra_keywords="cashier"))
    assert is_relevant(job("Cashier / Front End"), terms)
    assert is_relevant(job("Store Associate", "Run the register as a cashier and stock shelves."), terms)
    for title in ["Full-Stack Developer", "Software Engineer, AI Coding Tasks", "Remote Office Assistant",
                  "Content Reviewer - United States", "Inside Sales Contractor"]:
        assert not is_relevant(job(title), terms), title

    terms = search_terms(SearchOptions(industry="Fast food / Restaurant"))
    assert is_relevant(job("Line Cook"), terms)
    assert is_relevant(job("Crew Member - Part Time"), terms)
    assert not is_relevant(job("Tech Lead Full-Stack Rails Engineer"), terms)
    assert is_relevant(job("Anything at all"), search_terms(SearchOptions(industry="Any")))   # nothing to match
