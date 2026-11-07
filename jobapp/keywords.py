"""Keyword analysis: what the job postings ask for vs. what the resume says.

ATS filters mostly do literal (or lightly stemmed) phrase matching against
the job posting, so the job is to find the phrases employers repeat and check
which of them the resume is missing.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .industries import all_lexicon_keywords, keywords_for

STOPWORDS = set("""
a about above after again against all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had
has have having he her here hers herself him himself his how i if in into is it its itself just
me more most my myself no nor not now of off on once only or other our ours ourselves out over own
same she should so some such than that the their theirs them themselves then there these they this
those through to too under until up very was we were what when where which while who whom why will
with you your yours yourself yourselves must may per etc us job jobs work working position role
apply applicant applicants candidate candidates company team looking hiring hire new including
include includes able ability year years experience required preferred requirements responsibilities
opportunity opportunities benefits pay hour hours hourly salary week weekly day days time full part
please equal employer employment status well within across every one two three get make using use
""".split())

WORD = re.compile(r"[a-z][a-z+#&\-']*[a-z+#]|[a-z]")


def normalize(text: str) -> str:
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9+#&'\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _variants(phrase: str) -> list[str]:
    """A few spelling variants so 'drive thru' matches 'drive-thru' and plurals match."""
    p = normalize(phrase)
    out = {p, p.replace("-", " "), p.replace(" ", "-")}
    for v in list(out):
        if v.endswith("s"):
            out.add(v[:-1])
        else:
            out.add(v + "s")
    return [v for v in out if v]


def contains(text_norm: str, phrase: str) -> bool:
    padded = f" {text_norm} "
    return any(f" {v} " in padded for v in _variants(phrase))


@dataclass
class KeywordReport:
    keywords: list[tuple[str, int]]     # (keyword, number of postings mentioning it)
    present: list[str]
    missing: list[str]
    score: int                          # 0-100, weighted by how often employers ask for it


def top_phrases(texts: list[str], n: int = 25) -> list[tuple[str, int]]:
    """Frequent 1-3 word phrases outside the lexicon (counted once per posting)."""
    counts: Counter[str] = Counter()
    for text in texts:
        words = [w for w in WORD.findall(normalize(text))]
        grams: set[str] = set()
        for size in (2, 3):
            for i in range(len(words) - size + 1):
                chunk = words[i : i + size]
                if chunk[0] in STOPWORDS or chunk[-1] in STOPWORDS:
                    continue
                if any(len(w) < 3 for w in chunk):
                    continue
                grams.add(" ".join(chunk))
        counts.update(grams)
    min_count = max(2, len(texts) // 10)
    return [(g, c) for g, c in counts.most_common(n * 3) if c >= min_count][:n]


def extract_job_keywords(
    descriptions: list[str], industry: str = "Any", limit: int = 40
) -> list[tuple[str, int]]:
    """Rank keywords by how many postings mention them."""
    norms = [normalize(d) for d in descriptions if d]
    if not norms:
        return []
    lexicon = list(dict.fromkeys(keywords_for(industry) + all_lexicon_keywords()))
    found: Counter[str] = Counter()
    for kw in lexicon:
        hits = sum(1 for t in norms if contains(t, kw))
        if hits:
            found[kw] = hits
    # Industry preset terms always show up as suggestions, even if the snippets
    # the APIs return were too short to mention them.
    for kw in keywords_for(industry):
        found.setdefault(kw, 0)
    for phrase, c in top_phrases(descriptions):
        if not any(phrase in k or k in phrase for k in found):
            found[phrase] = c
    ranked = sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:limit]


def analyze(resume_text: str, descriptions: list[str], industry: str = "Any") -> KeywordReport:
    keywords = extract_job_keywords(descriptions, industry)
    resume_norm = normalize(resume_text)
    present = [k for k, _ in keywords if contains(resume_norm, k)]
    missing = [k for k, _ in keywords if k not in present]
    weights = {k: c + 1 for k, c in keywords}
    total = sum(weights.values()) or 1
    score = round(100 * sum(weights[k] for k in present) / total)
    return KeywordReport(keywords=keywords, present=present, missing=missing, score=score)
