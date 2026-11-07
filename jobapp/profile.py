"""Her contact details and default answers, kept locally in data/profile.json."""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PROFILE_PATH = DATA_DIR / "profile.json"

FIELDS = {
    "full_name": "Full name",
    "first_name": "First name",
    "last_name": "Last name",
    "email": "Email",
    "phone": "Phone",
    "street": "Street address",
    "city": "City",
    "state": "State",
    "zip": "ZIP code",
    "linkedin": "LinkedIn URL (optional)",
}


# Answers to the screening questions most hourly applications ask. The
# auto-submitter only answers questions that match one of these. Anything
# else sends the job to "needs review" instead of guessing.
ANSWERS = {
    "authorized": ("Legally authorized to work in the US?", ["Yes", "No"]),
    "sponsorship": ("Will you need visa sponsorship?", ["No", "Yes"]),
    "over18": ("Are you 18 or older?", ["Yes", "No"]),
    "weekends": ("Can you work weekends?", ["Yes", "No"]),
    "nights": ("Can you work nights / evenings?", ["Yes", "No"]),
    "transportation": ("Reliable transportation?", ["Yes", "No"]),
    "drug_test": ("Willing to take a drug test / background check?", ["Yes", "No"]),
    "relocate": ("Willing to relocate?", ["No", "Yes"]),
    "desired_pay": ("Desired pay (e.g. 16 or 16/hour)", None),
    "start_date": ("When can you start? (e.g. Immediately)", None),
    "years_experience": ("Years of relevant experience (number)", None),
    "how_heard": ("How did you hear about us?", None),
}
ANSWER_DEFAULTS = {"start_date": "Immediately", "how_heard": "Online job board"}


def load_profile() -> dict:
    base = {k: "" for k in FIELDS} | {
        "resume_path": "", "tailored_resume_path": "", "skill_bank": [], "resume_format": "pdf",
        "answers": dict(ANSWER_DEFAULTS), "eeo_decline": True, "auto_agree_terms": False,
        "skip_risky": True, "hold_check": False,
        "education": "", "credentials": [], "work_years": None,
    }
    if PROFILE_PATH.exists():
        base.update(json.loads(PROFILE_PATH.read_text()))
    return base


def save_profile(profile: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    full = profile.get("full_name", "").strip()
    if full and not profile.get("first_name"):
        parts = full.split()
        profile["first_name"] = parts[0]
        profile["last_name"] = " ".join(parts[1:])
    city, state = profile.get("city", ""), profile.get("state", "")
    profile["city_state"] = ", ".join(x for x in [city, state] if x)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2))
