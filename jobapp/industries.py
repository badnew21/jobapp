"""Industry presets: search terms, Adzuna categories and the ATS keyword lexicon.

The lexicon lists the skill phrases that show up again and again in postings for
each industry. ATS filters mostly match on phrases like these, so the resume
tailor uses them (plus whatever the actual postings say) to find gaps.
"""

from __future__ import annotations

# Phrases that show up across almost every hourly / entry-level posting.
GENERAL_KEYWORDS = [
    "customer service",
    "communication skills",
    "team player",
    "teamwork",
    "time management",
    "problem solving",
    "attention to detail",
    "reliable",
    "punctual",
    "flexible schedule",
    "weekends",
    "multitasking",
    "fast-paced environment",
    "microsoft office",
    "bilingual",
    "spanish",
    "positive attitude",
    "work independently",
    "organizational skills",
    "conflict resolution",
    "training new employees",
    "leadership",
]

INDUSTRIES: dict[str, dict] = {
    "Any": {
        "queries": [""],
        "adzuna_category": None,
        "remotive_category": None,
        "keywords": [],
    },
    "Fast food / Restaurant": {
        "queries": ["crew member", "cashier restaurant", "cook", "server", "fast food"],
        "adzuna_category": "hospitality-catering-jobs",
        "remotive_category": None,
        "keywords": [
            "food safety", "food handler", "servsafe", "food preparation", "cash handling",
            "pos system", "point of sale", "drive-thru", "order accuracy", "upselling",
            "sanitation", "cleanliness", "opening and closing", "food quality",
            "guest experience", "hospitality", "line cook", "front of house",
            "back of house", "inventory", "stocking", "health code",
        ],
    },
    "Grocery": {
        "queries": ["grocery", "grocery clerk", "stocker", "cashier grocery", "deli clerk"],
        "adzuna_category": "retail-jobs",
        "remotive_category": None,
        "keywords": [
            "cash handling", "pos system", "point of sale", "stocking", "merchandising",
            "inventory", "planogram", "rotation", "fifo", "product knowledge", "bagging",
            "deli", "bakery", "produce", "food safety", "customer service",
            "pallet jack", "loss prevention", "price changes", "shelf stocking",
        ],
    },
    "Retail": {
        "queries": ["retail associate", "sales associate", "cashier", "store associate"],
        "adzuna_category": "retail-jobs",
        "remotive_category": None,
        "keywords": [
            "sales", "cash handling", "pos system", "point of sale", "merchandising",
            "visual merchandising", "inventory", "stocking", "loss prevention",
            "product knowledge", "upselling", "sales goals", "returns and exchanges",
            "store opening", "store closing", "fitting room", "customer loyalty",
        ],
    },
    "Customer service / Call center": {
        "queries": ["customer service representative", "call center", "customer support"],
        "adzuna_category": "customer-services-jobs",
        "remotive_category": "customer-support",
        "keywords": [
            "inbound calls", "outbound calls", "call center", "crm", "salesforce",
            "zendesk", "ticketing system", "de-escalation", "first call resolution",
            "data entry", "typing speed", "active listening", "empathy", "chat support",
            "email support", "customer satisfaction", "troubleshooting",
        ],
    },
    "Healthcare support": {
        "queries": ["medical assistant", "caregiver", "cna", "patient care", "home health aide"],
        "adzuna_category": "healthcare-nursing-jobs",
        "remotive_category": None,
        "keywords": [
            "patient care", "cpr", "first aid", "bls", "hipaa", "vital signs",
            "electronic health records", "ehr", "scheduling appointments", "medical terminology",
            "compassion", "activities of daily living", "adl", "infection control",
            "medication reminders", "cna",
        ],
    },
    "Office / Administrative": {
        "queries": ["receptionist", "administrative assistant", "office assistant", "data entry"],
        "adzuna_category": "admin-jobs",
        "remotive_category": None,
        "keywords": [
            "microsoft office", "excel", "word", "outlook", "google workspace", "data entry",
            "scheduling", "calendar management", "filing", "front desk", "phone etiquette",
            "record keeping", "invoicing", "quickbooks", "typing", "office management",
        ],
    },
    "Warehouse / Logistics": {
        "queries": ["warehouse associate", "picker packer", "material handler", "shipping receiving"],
        "adzuna_category": "logistics-warehouse-jobs",
        "remotive_category": None,
        "keywords": [
            "picking", "packing", "shipping and receiving", "forklift", "pallet jack",
            "rf scanner", "inventory", "order fulfillment", "lift 50 lbs", "safety procedures",
            "osha", "loading", "unloading", "quality control", "labeling",
        ],
    },
    "Cleaning / Housekeeping": {
        "queries": ["housekeeper", "janitor", "custodian", "cleaner"],
        "adzuna_category": None,
        "remotive_category": None,
        "keywords": [
            "housekeeping", "janitorial", "sanitation", "cleaning chemicals", "floor care",
            "laundry", "attention to detail", "safety data sheets", "restocking supplies",
            "commercial cleaning", "time management",
        ],
    },
    "Childcare / Education": {
        "queries": ["childcare", "daycare teacher", "teacher assistant", "nanny"],
        "adzuna_category": "teaching-jobs",
        "remotive_category": None,
        "keywords": [
            "childcare", "early childhood education", "lesson planning", "classroom management",
            "cpr", "first aid", "child development", "patience", "background check",
            "parent communication", "supervision",
        ],
    },
}

JOB_TYPES = ["Full time", "Part time", "Contract", "Remote"]


def keywords_for(industry: str) -> list[str]:
    preset = INDUSTRIES.get(industry, INDUSTRIES["Any"])
    seen: dict[str, None] = {}
    for kw in preset["keywords"] + GENERAL_KEYWORDS:
        seen.setdefault(kw.lower(), None)
    return list(seen)


def all_lexicon_keywords() -> list[str]:
    seen: dict[str, None] = {}
    for preset in INDUSTRIES.values():
        for kw in preset["keywords"]:
            seen.setdefault(kw.lower(), None)
    for kw in GENERAL_KEYWORDS:
        seen.setdefault(kw.lower(), None)
    return list(seen)
