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
                for part in re.split(r"[,•|;·▪●■◦\x7f\uf0b7]|\s{2,}", line.lstrip("-*• ")):
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


BULLETS = "-*•●▪◦"


def build_structure(
    resume_text: str,
    profile: dict,
    target_title: str,
    approved_keywords: list[str],
    summary: str | None = None,
) -> dict:
    """The resume as plain data: name, contact, summary, skills, other sections."""
    sections = split_sections(resume_text)
    header_lines = sections[0][1] if sections and sections[0][0] == "" else []
    name = profile.get("full_name") or (header_lines[0] if header_lines else "")
    contact = " | ".join(
        x for x in [profile.get("city_state"), profile.get("phone"), profile.get("email"),
                    profile.get("linkedin")] if x
    )
    if not contact and len(header_lines) > 1:
        contact = " | ".join(header_lines[1:4])
    skills: dict[str, str] = {}
    for s in [_title_case(k.lower()) for k in approved_keywords] + existing_skills(resume_text):
        skills.setdefault(s.lower(), s)
    body = []
    for key, lines in sections[1:]:
        if key in SKIP_SECTIONS or not lines:
            continue
        items = []
        for line in lines:
            if line[:1] in BULLETS:
                items.append(("bullet", line.lstrip(BULLETS + " ").strip()))
            else:
                items.append(("text", line))
        body.append((key.title(), items))
    return {
        "name": name,
        "contact": contact,
        "summary": summary or build_summary(target_title, approved_keywords, existing_summary(resume_text)),
        "skills": list(skills.values()),
        "sections": body,
    }


def render_docx(res: dict) -> bytes:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(res["name"])
    run.bold = True
    run.font.size = Pt(18)
    if res["contact"]:
        doc.add_paragraph(res["contact"]).alignment = WD_ALIGN_PARAGRAPH.CENTER

    def heading(text: str) -> None:
        r = doc.add_paragraph().add_run(text.upper())
        r.bold = True
        r.font.size = Pt(12)

    heading("Professional Summary")
    doc.add_paragraph(res["summary"])
    if res["skills"]:
        heading("Skills")
        doc.add_paragraph(" • ".join(res["skills"]))
    for title, items in res["sections"]:
        heading(title)
        for kind, text in items:
            doc.add_paragraph(text, style="List Bullet" if kind == "bullet" else None)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def render_pdf(res: dict) -> bytes:
    """Text-based PDF (selectable text, one column) so ATS parsers can read it."""
    from xml.sax.saxutils import escape

    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    base = ParagraphStyle("base", fontName="Helvetica", fontSize=10.5, leading=14)
    name_s = ParagraphStyle("name", parent=base, fontName="Helvetica-Bold", fontSize=18, leading=22,
                            alignment=TA_CENTER)
    center = ParagraphStyle("center", parent=base, alignment=TA_CENTER)
    head = ParagraphStyle("head", parent=base, fontName="Helvetica-Bold", fontSize=12, spaceBefore=10,
                          spaceAfter=3)
    bullet_s = ParagraphStyle("bullet", parent=base, leftIndent=14, bulletIndent=3)

    story = [Paragraph(escape(res["name"]), name_s)]
    if res["contact"]:
        story.append(Paragraph(escape(res["contact"]), center))
    story += [Spacer(1, 6), Paragraph("PROFESSIONAL SUMMARY", head), Paragraph(escape(res["summary"]), base)]
    if res["skills"]:
        story += [Paragraph("SKILLS", head), Paragraph(escape(", ".join(res["skills"])), base)]
    for title, items in res["sections"]:
        story.append(Paragraph(escape(title.upper()), head))
        for kind, text in items:
            if kind == "bullet":
                story.append(Paragraph(escape(text), bullet_s, bulletText="•"))
            else:
                story.append(Paragraph(escape(text), base))

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                      topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                      title=f"{res['name']} Resume", author=res["name"]).build(story)
    return buf.getvalue()


def build_tailored_docx(
    resume_text: str,
    profile: dict,
    target_title: str,
    approved_keywords: list[str],
    summary: str | None = None,
) -> bytes:
    return render_docx(build_structure(resume_text, profile, target_title, approved_keywords, summary))


def clean_title(title: str) -> str:
    """'Crew Member - Part Time - Chicago, IL ($15/hr)' -> 'Crew Member'"""
    title = re.split(r"\s+[-|–—/]\s+|\(|,", title)[0]
    return title.strip() or "team member"


def tailor_for_job(resume_text: str, profile: dict, job: dict, skill_bank: list[str],
                   fmt: str = "pdf") -> tuple[bytes, list[str]]:
    """Resume for one posting. Uses only skills from her confirmed bank.

    Skills the posting mentions go first in the Skills section and in the
    summary, and the summary names the job title she's applying for.
    Returns (file bytes, matched skills).
    """
    from .keywords import contains, normalize

    desc = normalize(f"{job.get('title', '')} {job.get('description', '')}")
    bank = list(dict.fromkeys(k.lower().strip() for k in skill_bank if k.strip()))
    matched = [k for k in bank if contains(desc, k)]
    ordered = matched + [k for k in bank if k not in matched]
    title = clean_title(job.get("title", ""))
    summary = build_summary(title, matched or ordered, existing_summary(resume_text))
    res = build_structure(resume_text, profile, title, ordered[:20], summary)
    return (render_pdf(res) if fmt == "pdf" else render_docx(res)), matched


def resume_filename(job: dict, name: str, fmt: str) -> str:
    """'Jane Doe Resume - Walmart.pdf', safe for every OS."""
    company = re.sub(r"[^A-Za-z0-9 ]+", "", job.get("company", "")).strip()[:40]
    person = re.sub(r"[^A-Za-z0-9 ]+", "", name).strip() or "Resume"
    return f"{person} Resume{' - ' + company if company else ''}.{fmt}"


def docx_to_text(data: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)


def pdf_to_text(data: bytes) -> str:
    from pypdf import PdfReader
    return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages)
