"""Does she meet a posting's requirements?

Reads each posting for the things that get an application rejected outright:
a required degree, a license or certification she doesn't hold, more years of
experience than she has, a senior title. "Preferred" or "a plus" requirements
only make a job a stretch, not a no.

Returns one of:
  good     - nothing in the posting rules her out
  stretch  - worth a try, but something is preferred or borderline
  no       - a hard requirement she doesn't meet
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .keywords import contains, normalize

EDUCATION_LEVELS = ["No diploma", "High school / GED", "Some college", "Associate degree",
                    "Bachelor's degree", "Master's degree or higher"]

# (rank needed, pattern). Rank indexes EDUCATION_LEVELS.
DEGREE_PATTERNS = [
    (5, r"\b(master'?s|mba|m\.s\.|msw|ph\.?d|doctorate|doctoral)\b"),
    (4, r"\b(bachelor'?s|b\.s\.|b\.a\.|bsn|4[- ]year degree|four[- ]year degree|college degree|university degree)"),
    # Not just "associate": that's also a job title (Sales Associate).
    (3, r"\b(associate'?s? degree|associate of (arts|science|applied science)|a\.a\.s?\.?|a\.s\. degree|"
        r"2[- ]year degree|two[- ]year degree)"),
    (1, r"\b(high school (diploma|graduate)|ged)\b"),
]

# Any degree at this level or above removes the job, even if only "preferred":
# postings that mention one aren't the entry-level jobs she's after.
DEGREE_CUTOFF = 3
NO_DEGREE = re.compile(r"\bno (college |university )?degree|degree (is )?not (required|necessary|needed)|"
                       r"without a degree|don'?t need a degree|no diploma (is )?required|regardless of degree", re.I)

# Licenses / certifications employers require. (name, pattern)
CREDENTIALS = [
    ("Registered Nurse (RN)", r"\b(registered nurse|rn license|\brn\b|bsn)\b"),
    ("LPN / LVN", r"\b(lpn|lvn|licensed practical nurse|licensed vocational nurse)\b"),
    ("CNA", r"\b(cna|certified nursing assistant)\b"),
    ("CDL", r"\b(cdl|commercial driver'?s? licen[cs]e)\b"),
    ("Forklift certification", r"\bforklift (certification|certified|license)\b"),
    ("Pharmacy technician license", r"\b(pharmacy tech(nician)? (license|certification|registration)|cpht|ptcb)\b"),
    ("Cosmetology license", r"\b(cosmetology|barber|esthetician|nail tech(nician)?) licen[cs]e\b"),
    ("Real estate license", r"\breal estate licen[cs]e\b"),
    ("Insurance license", r"\b(insurance|life (and|&) health|p&c|2-15|2-40|4-40) licen[cs]e\b"),
    ("Security guard license", r"\b(class d|security (guard )?licen[cs]e|guard card)\b"),
    ("CPA", r"\bcpa\b"),
    ("Teaching certificate", r"\bteach(ing|er) (certificate|certification|licen[cs]e)\b"),
    ("Phlebotomy certification", r"\bphlebotomy (certification|certified|license)\b"),
    ("Medical assistant certification", r"\b(cma|rma|ccma|certified medical assistant)\b"),
    ("EMT / Paramedic", r"\b(emt|paramedic)\b"),
    ("Food manager certification (ServSafe)", r"\b(servsafe manager|food (protection )?manager certification|certified food manager)\b"),
    ("CPR / BLS", r"\b(cpr|bls|basic life support)( certification| certified| card)?\b"),
    ("Driver's license", r"\b(valid )?driver'?s'? licen[cs]e\b"),
]
COMMON_CREDENTIALS = [name for name, _ in CREDENTIALS]

# Quick to get (a class or a short course), so missing one only makes a job a stretch.
EASY_CREDENTIALS = {"CPR / BLS", "Forklift certification", "Food manager certification (ServSafe)"}

SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|director|vice president|vp|chief|principal|head of|"
    r"district manager|regional manager|area manager)\b", re.I)
MANAGER_TITLE = re.compile(r"\b(general manager|store manager|operations manager|restaurant manager|"
                           r"assistant manager|department manager|office manager|manager)\b", re.I)
PROFESSIONAL_TITLE = re.compile(
    r"\b(nurse|rn|lpn|physician|doctor|pharmacist|dentist|hygienist|attorney|lawyer|paralegal|engineer|"
    r"developer|programmer|software|architect|accountant|cpa|auditor|therapist|psychologist|counselor|"
    r"social worker|professor|electrician|plumber|hvac|mechanic|welder|machinist|surgeon|veterinarian|"
    r"vet tech|radiolog|sonograph|phlebotomist|pilot|truck driver|cdl|analyst|scientist|technologist|"
    r"tech lead|full[- ]?stack|front[- ]?end|back[- ]?end|devops|rails|java|python|data engineer|"
    r"machine learning|qa engineer|sysadmin|network administrator)\b", re.I)
# Professional titles people do get hired into without the formal background.
TRAINABLE_TITLES = {"vet tech", "phlebotomist"}
SOFT = re.compile(r"preferred|a plus|is a plus|nice to have|desired|desirable|bonus|ideally|or equivalent|"
                  r"or related experience|helpful|not required|will train|willing to train", re.I)
YEARS = re.compile(
    r"(?:minimum (?:of )?|at least |)(\d{1,2})\s*\+?\s*(?:-|to)?\s*(?:\d{1,2}\s*)?(?:years?|yrs?)['’]?"
    r"\s*(?:of\s+)?((?:[a-z/&\-]+\s+){0,4}?)(?:work\s+)?experience", re.I)
FILLER = {"of", "the", "a", "an", "in", "with", "related", "relevant", "professional", "prior", "previous",
          "proven", "paid", "hands-on", "direct", "progressive", "similar", "recent", "and", "or", "industry",
          "field", "working", "total", "combined", "demonstrated", "successful", "least"}


@dataclass
class Fit:
    level: str = "good"                       # good / stretch / no
    reasons: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return fit_label(self.level)


LABELS = {"good": "✅ Good fit", "stretch": "🟨 Stretch", "no": "⛔ Not qualified"}


def fit_label(level: str) -> str:
    return LABELS.get(level, level)


def _lines(text: str) -> list[str]:
    """Split a posting into sentences/lines so 'preferred' only softens its own line."""
    return [s.strip() for s in re.split(r"[\n\r•·▪●]+|(?<=[.;!?])\s+", text) if s.strip()]


def _is_soft(line: str) -> bool:
    return bool(SOFT.search(line))


def check_fit(job: dict, quals: dict, resume_text: str = "") -> Fit:
    """quals: {"education": one of EDUCATION_LEVELS, "credentials": [names], "years": int | None}"""
    title = job.get("title", "")
    desc = job.get("description", "")
    resume = normalize(resume_text)
    have_edu = EDUCATION_LEVELS.index(quals.get("education") or "High school / GED")
    have_creds = {c.lower() for c in quals.get("credentials", [])}
    years = quals.get("years")
    hard: list[str] = []
    soft: list[str] = []

    if SENIOR_TITLE.search(title):
        hard.append(f"Senior role ({SENIOR_TITLE.search(title).group(0)})")
    mm = MANAGER_TITLE.search(title)
    if mm and not SENIOR_TITLE.search(title) and not re.search(r"shift (manager|lead|leader)", title, re.I):
        soft.append(f"Management role ({mm.group(0)}); her experience is shift-level")
    m = PROFESSIONAL_TITLE.search(title)
    if m and not contains(resume, m.group(0).lower()):
        word = m.group(0).lower()
        if word in TRAINABLE_TITLES:
            soft.append(f"\"{m.group(0)}\" jobs usually need some training")
        else:
            hard.append(f"\"{m.group(0)}\" jobs need training or experience that isn't on her resume")

    for line in _lines(f"{title}\n{desc}"):
        low = line.lower()
        is_soft = _is_soft(line)

        for rank, pattern in DEGREE_PATTERNS:
            if NO_DEGREE.search(low):
                break
            if re.search(pattern, low) and re.search(r"degree|diploma|ged|graduate|bsn|mba|ph\.?d", low):
                if rank > have_edu:
                    wording = "Prefers" if is_soft else "Requires"
                    reason = f"{wording} {EDUCATION_LEVELS[rank].lower()}"
                    (hard if rank >= DEGREE_CUTOFF or not is_soft else soft).append(reason)
                break

        for name, pattern in CREDENTIALS:
            if name.lower() in have_creds or not re.search(pattern, low):
                continue
            # "CPR certification within 30 days of hire" or "we'll get you certified" isn't a requirement up front.
            if re.search(r"within \d+ (days|months)|after hire|upon hire|we will (train|certify|pay)|obtain", low):
                continue
            if name in EASY_CREDENTIALS:
                soft.append(f"Asks for {name} (a short class)")
            else:
                (soft if is_soft else hard).append(f"{'Prefers' if is_soft else 'Requires'} {name}")

        for ym in YEARS.finditer(low):
            need = int(ym.group(1))
            if need == 0 or need > 25:
                continue
            raw = ym.group(2).strip()
            area = " ".join(w for w in raw.split() if w not in FILLER)
            # "restaurant or customer service" passes if she has either one.
            options = [[w for w in alt.split() if w not in FILLER]
                       for alt in re.split(r"\s+or\s+|/|,|\s+and/or\s+", raw)]
            options = [o for o in options if o]
            has_area = any(contains(resume, " ".join(o)) or all(contains(resume, w) for w in o) for o in options)
            if years is not None and need > years:
                (soft if is_soft else hard).append(
                    f"{'Prefers' if is_soft else 'Requires'} {need}+ years of experience (she has {years})")
            elif area and resume and not has_area:
                text = f"{need}+ years of {area} experience"
                if need >= 3 and not is_soft:
                    hard.append(f"Requires {text}, which isn't on her resume")
                else:
                    soft.append(f"Asks for {text}")

    hard = list(dict.fromkeys(hard))
    soft = [s for s in dict.fromkeys(soft) if s.replace("Prefers", "Requires") not in hard]
    if hard:
        return Fit("no", hard + soft)
    if soft:
        return Fit("stretch", soft)
    return Fit("good", [])
