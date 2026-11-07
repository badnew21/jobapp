"""Job Helper - find local jobs, tailor the resume, and work through applications.

Start it with:  streamlit run app.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from jobapp.industries import INDUSTRIES, JOB_TYPES
from jobapp.keywords import analyze
from jobapp.profile import DATA_DIR, FIELDS, load_profile, save_profile
from jobapp.resume import build_summary, build_tailored_docx, docx_to_text, existing_summary, read_resume
from jobapp.search import SearchOptions, search_jobs
from jobapp.tracker import STATUSES, Tracker

load_dotenv()
st.set_page_config(page_title="Job Helper", page_icon="💼", layout="wide")


@st.cache_resource
def get_tracker() -> Tracker:
    return Tracker()


tracker = get_tracker()
profile = load_profile()

st.title("💼 Job Helper")
counts = tracker.counts()
cols = st.columns(5)
for col, key in zip(cols, ["new", "queued", "applied", "interview", "skipped"]):
    col.metric(key.title(), counts.get(key, 0))

tab_profile, tab_search, tab_resume, tab_apply, tab_track = st.tabs(
    ["1. Me & my resume", "2. Find jobs", "3. Tailor resume", "4. Apply", "5. Tracker"]
)

# ------------------------------------------------------------------ profile
with tab_profile:
    st.subheader("Your details")
    st.caption("Used to fill in application forms. Saved only on this computer, in the data/ folder.")
    with st.form("profile"):
        c1, c2 = st.columns(2)
        new_profile = dict(profile)
        for i, (key, label) in enumerate(FIELDS.items()):
            new_profile[key] = (c1 if i % 2 == 0 else c2).text_input(label, value=profile.get(key, ""))
        if st.form_submit_button("Save details"):
            save_profile(new_profile)
            st.success("Saved.")
            profile = load_profile()

    st.subheader("Your resume")
    upload = st.file_uploader("Upload your resume (Word .docx works best, PDF or .txt also OK)",
                              type=["docx", "pdf", "txt"])
    if upload is not None:
        DATA_DIR.mkdir(exist_ok=True)
        dest = DATA_DIR / f"resume_original{Path(upload.name).suffix.lower()}"
        dest.write_bytes(upload.getvalue())
        profile["resume_path"] = str(dest)
        save_profile(profile)
        st.success(f"Resume saved ({upload.name}).")
    if profile.get("resume_path"):
        st.write(f"Current resume: `{Path(profile['resume_path']).name}`")


def resume_text() -> str:
    path = profile.get("resume_path")
    if not path or not Path(path).exists():
        return ""
    return read_resume(path, Path(path).read_bytes())


# ------------------------------------------------------------------ search
with tab_search:
    st.subheader("What are you looking for?")
    c1, c2, c3 = st.columns([2, 1, 2])
    location = c1.text_input("City or ZIP code", value=profile.get("zip") or profile.get("city_state", ""))
    radius = c2.slider("Radius (miles)", 1, 100, 15)
    industry = c3.selectbox("Industry", list(INDUSTRIES))
    c4, c5, c6 = st.columns([2, 2, 1])
    job_types = c4.multiselect("Job type", JOB_TYPES, default=["Part time"])
    extra = c5.text_input("Extra keywords (optional)", placeholder="e.g. cashier, morning shift")
    max_days = c6.number_input("Posted within (days)", 1, 60, 14)

    if st.button("🔎 Search", type="primary"):
        opts = SearchOptions(location=location, radius_miles=radius, job_types=job_types,
                             industry=industry, extra_keywords=extra, max_days_old=int(max_days))
        with st.spinner("Searching..."):
            jobs, warnings = search_jobs(opts)
        for w in warnings:
            st.warning(w)
        added = tracker.add_jobs(jobs)
        st.session_state["results"] = [j.to_dict() for j in jobs]
        st.session_state["industry"] = industry
        st.success(f"Found {len(jobs)} jobs ({added} new to you).")

    results = st.session_state.get("results", [])
    if results:
        rt = resume_text()
        rows = []
        for j in results:
            status = tracker.status_of(j["id"]) or "new"
            score = analyze(rt, [j["description"]], st.session_state.get("industry", "Any")).score if rt else None
            rows.append({
                "queue": status == "queued",
                "title": j["title"], "company": j["company"], "location": j["location"],
                "type": j["job_type"].replace("_", " "), "remote": j["remote"], "pay": j["salary"],
                "match %": score, "status": status, "posted": j["posted"], "link": j["url"], "id": j["id"],
            })
        st.caption("Tick the jobs you want to apply to, then press *Queue selected*. "
                   "“match %” is how many of the posting's keywords your resume already has.")
        c1, c2 = st.columns(2)
        select_all = c1.checkbox("Select all new jobs")
        if select_all:
            for r in rows:
                if r["status"] == "new":
                    r["queue"] = True
        edited = st.data_editor(
            rows, hide_index=True, use_container_width=True, disabled=[k for k in rows[0] if k != "queue"],
            column_config={"link": st.column_config.LinkColumn("link", display_text="open"),
                           "id": None,
                           "match %": st.column_config.ProgressColumn("match %", min_value=0, max_value=100)},
            key="results_editor",
        )
        if c2.button("➕ Queue selected"):
            n = 0
            for r in edited:
                if r["queue"] and r["status"] in ("new", "skipped"):
                    tracker.set_status(r["id"], "queued")
                    n += 1
            st.success(f"Queued {n} jobs. Go to the Apply tab.")
            st.rerun()

# ------------------------------------------------------------------ resume tailoring
with tab_resume:
    st.subheader("Make your resume match what employers' filters look for")
    rt = resume_text()
    if not rt:
        st.info("Upload your resume in tab 1 first.")
    else:
        pool = st.session_state.get("results") or [r for r in tracker.rows() if r["status"] in ("new", "queued")]
        industry = st.selectbox("Industry to tailor for", list(INDUSTRIES),
                                index=list(INDUSTRIES).index(st.session_state.get("industry", "Any")),
                                key="tailor_industry")
        target_title = st.text_input("Job title you're aiming for", placeholder="e.g. Cashier, Crew Member")
        if not pool:
            st.info("No job postings to compare against yet. Using the industry's common keywords. "
                    "Run a search for better results.")
        report = analyze(rt, [j["description"] for j in pool], industry)

        c1, c2 = st.columns([1, 2])
        c1.metric("Keyword match now", f"{report.score}%")
        c1.caption(f"Compared against {len(pool)} postings.")
        with c2:
            st.write("**Already on your resume:**")
            st.write(", ".join(report.present) or "—")

        st.write("**Keywords employers use that your resume is missing.** "
                 "Tick only the ones that are **true for you**. You'll be asked about them in interviews.")
        approved: list[str] = []
        grid = st.columns(3)
        for i, kw in enumerate(report.missing):
            count = dict(report.keywords).get(kw, 0)
            if grid[i % 3].checkbox(f"{kw}  ({count} postings)", key=f"kw_{kw}"):
                approved.append(kw)
        custom = st.text_input("Other skills to add (comma separated)", placeholder="e.g. forklift certified, CPR")
        approved += [c.strip().lower() for c in custom.split(",") if c.strip()]

        all_kw = approved + report.present
        summary = st.text_area(
            "Professional summary (edit freely)",
            value=build_summary(target_title, all_kw, existing_summary(rt)),
            height=110,
        )

        if st.button("📝 Build tailored resume", type="primary"):
            data = build_tailored_docx(rt, profile, target_title, approved + report.present, summary)
            out = DATA_DIR / "resume_tailored.docx"
            out.write_bytes(data)
            profile["tailored_resume_path"] = str(out)
            save_profile(profile)
            new_score = analyze(docx_to_text(data), [j["description"] for j in pool], industry).score
            st.success(f"Done. Keyword match went from {report.score}% to {new_score}%. "
                       "The Apply assistant will attach this version.")
            st.download_button("⬇️ Download tailored resume", data, file_name="resume_tailored.docx",
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

        with st.expander("Formatting tips that help ATS filters"):
            st.markdown(
                "- Save as **.docx** (or a text-based PDF). Scanned or image PDFs can't be read.\n"
                "- Use standard headings: *Summary, Skills, Experience, Education*.\n"
                "- No tables, columns, text boxes, icons or photos. Parsers scramble them.\n"
                "- Put contact info in the body, not the header/footer.\n"
                "- Use the employer's exact words (\"cash handling\", not \"handled money\").\n"
                "- Don't hide keywords in white text. Recruiters see it and toss the resume."
            )

# ------------------------------------------------------------------ apply
with tab_apply:
    st.subheader("Work through your queue")
    queued = tracker.rows("queued")
    st.write(f"**{len(queued)} jobs queued.**")
    if queued:
        st.dataframe([{"title": j["title"], "company": j["company"], "location": j["location"]}
                      for j in queued], hide_index=True, use_container_width=True)
    resume_to_send = profile.get("tailored_resume_path") or profile.get("resume_path")
    st.write(f"Resume that will be attached: `{Path(resume_to_send).name if resume_to_send else 'none'}`")
    st.markdown(
        "Pressing **Start** opens a browser window. For each job it opens the posting, clicks *Apply*, "
        "fills in your name, email, phone and address, and attaches your resume.\n\n"
        "Then **you** answer the screening questions and press the site's Submit button. "
        "Use the bar at the bottom of the window:\n"
        "- **Fill this form**: fill the page again (use it after the site moves to a new page)\n"
        "- **I applied ✓**: marks it applied and goes to the next job\n"
        "- **Skip** / **Stop**\n\n"
        "The first time, you may need to sign in to sites like Indeed or Workday. The browser remembers you."
    )
    limit = st.number_input("How many jobs this session", 1, 200, min(len(queued), 20) or 1)
    if st.button("▶️ Start applying", type="primary", disabled=not queued):
        subprocess.Popen([sys.executable, "-m", "jobapp.apply_assist", "--limit", str(int(limit))],
                         cwd=str(Path(__file__).parent))
        st.success("Browser opening... Come back here and refresh when you're done.")

# ------------------------------------------------------------------ tracker
with tab_track:
    st.subheader("Everything you've found and applied to")
    status_filter = st.selectbox("Show", ["all"] + STATUSES)
    rows = tracker.rows(None if status_filter == "all" else status_filter)
    if not rows:
        st.info("Nothing here yet.")
    for r in rows[:300]:
        with st.expander(f"{r['title']} — {r['company']}  ·  {r['status']}"):
            st.write(f"{r['location']} · {r['job_type'].replace('_', ' ')} · {r['salary']} · posted {r['posted']}")
            st.write(r["description"][:1500])
            st.link_button("Open posting", r["url"])
            c1, c2 = st.columns([1, 3])
            new_status = c1.selectbox("Status", STATUSES, index=STATUSES.index(r["status"]), key=f"s_{r['id']}")
            notes = c2.text_input("Notes", value=r["notes"], key=f"n_{r['id']}")
            if st.button("Save", key=f"b_{r['id']}"):
                tracker.set_status(r["id"], new_status, notes)
                st.rerun()
