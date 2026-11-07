"""Read a resume and write an ATS-friendly, keyword-tailored copy.

The tailored resume is a plain single-column .docx: standard section headings,
no tables, text boxes, columns, images or headers/footers. Those trip up ATS
parsers more often than missing keywords do.

Only keywords she ticks as true get added. Hidden white text or a block of
keywords she can't back up gets caught by recruiters and in interviews.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

SECTION_NAMES = {
    "summary", "professional summary", "profile", "objective", "career objective",
    "experience", "work experience", "employment history", "professional experience",
    "work history", "education", "skills", "core skills", "key skills", "skills & keywords",
    "certifications", "certificates", "licenses", "volunteer", "volunteer experience",
    "references", "awards", "languages", "additional information", "achievements",
}
SKIP_SECTIONS = {"summary", "professional summary", "profile", "objective", "career objective",
                 "skills", "core skills", "key skills", "skills & keywords"}


def read_resume(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".docx":
        doc = Document(io.BytesIO(data))
        lines = [p.text for p in doc.paragraphs]
        for table in doc.tables:  # some templates put everything in tables
            for row in table.rows:
                for cell in row.cells:
                    lines.extend(p.text for p in cell.paragraphs)
        return "\n".join(lines)
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    return data.decode("utf-8", errors="ignore")


def _heading_key(line: str) -> str | None:
    key = re.sub(r"[^a-z& ]", "", line.lower()).strip()
    return key if key in SECTION_NAMES else None


def split_sections(text: str) -> list[tuple[str, list[str]]]:
    """Returns [(heading, lines)]; text before the first heading goes under ''."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        key = _heading_key(line)
        if key:
            sections.append((key, []))
        else:
            sections[-1][1].append(line)
    return sections


def existing_skills(text: str) -> list[str]:
    for heading, lines in split_sections(text):
        if heading in {"skills", "core skills", "key skills", "skills & keywords"}:
            items: list[str] = []
            for line in lines:
                for part in re.split(r"[,•|;·▪●]", line.lstrip("-*• ")):
                    part = part.strip(" -*\t")
                    if 1 < len(part) < 50:
                        items.append(part)
            return items
    return []


def existing_summary(text: str) -> str:
    for heading, lines in split_sections(text):
        if heading in {"summary", "professional summary", "profile", "objective", "career objective"}:
            return " ".join(lines)
    return ""


def build_summary(target_title: str, keywords: list[str], original: str = "") -> str:
    title = target_title.strip() or "team member"
    top = [k for k in keywords[:4]]
    if original:
        base = original.rstrip(".")
        extra = f" Skilled in {', '.join(top)}." if top else ""
        return f"{base}.{extra}"
    skills = ", ".join(top) if top else "customer service and teamwork"
    return (
        f"Dependable {title} candidate with hands-on experience in {skills}. "
        "Quick learner who shows up on time, works well with a team, and keeps a positive attitude "
        "in a fast-paced environment."
    )


def _title_case(kw: str) -> str:
    small = {"and", "of", "the", "in", "to", "a"}
    acronyms = {"pos", "crm", "cpr", "bls", "hipaa", "ehr", "adl", "fifo", "osha", "rf", "cna"}
    words = []
    for i, w in enumerate(kw.split()):
        if w in acronyms:
            words.append(w.upper())
        elif w in small and i:
            words.append(w)
        else:
            words.append(w[:1].upper() + w[1:])
    return " ".join(words)


def build_tailored_docx(
    resume_text: str,
    profile: dict,
    target_title: str,
    approved_keywords: list[str],
    summary: str | None = None,
) -> bytes:
    """Rebuild the resume in a clean ATS layout with her approved keywords added."""
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    sections = split_sections(resume_text)
    header_lines = sections[0][1] if sections and sections[0][0] == "" else []

    name = profile.get("full_name") or (header_lines[0] if header_lines else "")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(name)
    run.bold = True
    run.font.size = Pt(18)

    contact = " | ".join(
        x for x in [
            profile.get("city_state"), profile.get("phone"), profile.get("email"),
            profile.get("linkedin"),
        ] if x
    )
    if not contact and len(header_lines) > 1:
        contact = " | ".join(header_lines[1:4])
    if contact:
        cp = doc.add_paragraph(contact)
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def heading(text: str) -> None:
        hp = doc.add_paragraph()
        r = hp.add_run(text.upper())
        r.bold = True
        r.font.size = Pt(12)

    heading("Professional Summary")
    doc.add_paragraph(
        summary or build_summary(target_title, approved_keywords, existing_summary(resume_text))
    )

    skills = list(dict.fromkeys(
        [_title_case(k.lower()) for k in approved_keywords] + existing_skills(resume_text)
    ))
    if skills:
        heading("Skills")
        doc.add_paragraph(" • ".join(skills))

    for key, lines in sections[1:]:
        if key in SKIP_SECTIONS or not lines:
            continue
        heading(key.title())
        for line in lines:
            if line[:1] in "-*•●▪":
                doc.add_paragraph(line.lstrip("-*•●▪ ").strip(), style="List Bullet")
            else:
                doc.add_paragraph(line)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def docx_to_text(data: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
