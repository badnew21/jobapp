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


def load_profile() -> dict:
    if PROFILE_PATH.exists():
        return json.loads(PROFILE_PATH.read_text())
    return {k: "" for k in FIELDS} | {"resume_path": "", "tailored_resume_path": ""}


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
