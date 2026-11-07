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
from jobapp.profile import ANSWERS, DATA_DIR, FIELDS, load_profile, save_profile
from jobapp.resume import (docx_to_text, existing_skills, pdf_to_text, read_resume, resume_filename,
                           tailor_for_job)
import os

from jobapp.employers import find_employers, job_links
from jobapp.qualify import COMMON_CREDENTIALS, EDUCATION_LEVELS, check_fit, fit_label
from jobapp.scamcheck import assess, risk_label
from jobapp.search import SOURCES, SearchOptions, search_jobs
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
for col, key in zip(cols, ["new", "queued", "needs_review", "applied", "interview"]):
    col.metric(key.replace('_', ' ').title(), counts.get(key, 0))

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

    st.subheader("Qualifications")
    st.caption("Search results automatically leave out jobs she can't get: anything asking for a college "
               "degree, a license she doesn't hold, or more experience than she has.")
    with st.form("quals"):
        c1, c2 = st.columns(2)
        edu_opts = ["(not set)"] + EDUCATION_LEVELS
        cur = profile.get("education") or "(not set)"
        education = c1.selectbox("Highest education", edu_opts, index=edu_opts.index(cur) if cur in edu_opts else 0)
        work_years = c2.number_input("Total years of work experience", 0, 60,
                                     int(profile.get("work_years") or 0))
        held = [c for c in profile.get("credentials", []) if c in COMMON_CREDENTIALS]
        creds = st.multiselect("Licenses and certifications she currently holds (leave out expired ones)",
                               COMMON_CREDENTIALS, default=held)
        if st.form_submit_button("Save qualifications"):
            profile.update(education="" if education == "(not set)" else education, credentials=creds,
                           work_years=int(work_years) or None)
            save_profile(profile)
            st.success("Saved.")

    st.subheader("Screening question answers")
    st.caption("The auto-submitter uses these to answer the usual questions. Answer them truthfully: "
               "employers check, and a wrong \"yes\" gets offers pulled. If a form asks something not "
               "on this list, the job goes to *Needs review* for you to finish.")
    with st.form("answers"):
        answers = dict(profile.get("answers", {}))
        c1, c2 = st.columns(2)
        for i, (key, (label, options)) in enumerate(ANSWERS.items()):
            col = c1 if i % 2 == 0 else c2
            if options:
                cur = answers.get(key, "")
                choices = ["(not set)"] + options
                val = col.selectbox(label, choices, index=choices.index(cur) if cur in choices else 0, key=f"a_{key}")
                answers[key] = "" if val == "(not set)" else val
            else:
                answers[key] = col.text_input(label, value=answers.get(key, ""), key=f"a_{key}")
        eeo = st.checkbox("Answer demographic questions (gender, race, veteran, disability) with "
                          "\"decline to self-identify\"", value=profile.get("eeo_decline", True))
        agree = st.checkbox("Tick \"I agree / I acknowledge the privacy policy\" boxes for me",
                            value=profile.get("auto_agree_terms", False))
        if st.form_submit_button("Save answers"):
            profile.update(answers=answers, eeo_decline=eeo, auto_agree_terms=agree)
            save_profile(profile)
            st.success("Saved.")

    st.subheader("Your resume")
    upload = st.file_uploader("Upload your resume (PDF or Word .docx)", type=["pdf", "docx", "txt"])
    if upload is not None and st.session_state.get("uploaded") != upload.file_id:
        DATA_DIR.mkdir(exist_ok=True)
        dest = DATA_DIR / f"resume_original{Path(upload.name).suffix.lower()}"
        dest.write_bytes(upload.getvalue())
        profile["resume_path"] = str(dest)
        text = read_resume(dest.name, upload.getvalue())
        if not profile.get("skill_bank"):
            profile["skill_bank"] = [s.lower() for s in existing_skills(text)]
        save_profile(profile)
        st.session_state["uploaded"] = upload.file_id
        st.success(f"Resume saved ({upload.name}).")
    if profile.get("resume_path") and Path(profile["resume_path"]).exists():
        st.write(f"Current resume: `{Path(profile['resume_path']).name}`")
        text = read_resume(profile["resume_path"], Path(profile["resume_path"]).read_bytes())
        if len(text.strip()) < 200:
            st.error("Almost no text could be read from this file. It's probably a scanned or image PDF, "
                     "which resume filters can't read either. Upload the Word version, or re-save the PDF "
                     "from Word or Google Docs.")
        with st.expander("What the filters will read from your resume"):
            st.text(text)


def qualifications() -> dict:
    return {"education": profile.get("education") or "High school / GED",
            "credentials": profile.get("credentials", []), "years": profile.get("work_years")}


def resume_text() -> str:
    path = profile.get("resume_path")
    if not path or not Path(path).exists():
        return ""
    return read_resume(path, Path(path).read_bytes())


# ------------------------------------------------------------------ search
with tab_search:
    st.subheader("What are you looking for?")
    c1, c2, c3 = st.columns([2, 1, 3])
    location = c1.text_input("City or ZIP code", value=profile.get("zip") or profile.get("city_state", ""))
    radius = c2.slider("Radius (miles)", 1, 100, 25)
    industries = c3.multiselect("Industries", [i for i in INDUSTRIES if i != "Any"],
                                default=["Fast food / Restaurant", "Grocery", "Retail"],
                                help="Pick several. Leave empty to search all jobs.")
    c4, c5, c6 = st.columns([2, 2, 1])
    job_types = c4.multiselect("Job type", JOB_TYPES, default=[],
                               help="Leave empty for any. Postings that don't say are always kept.")
    extra = c5.text_input("Extra searches (optional, comma separated)",
                          placeholder="e.g. dollar store, deli, dishwasher")
    max_days = c6.number_input("Posted within (days)", 1, 90, 30)
    default_sources = ["Indeed"] + (["Adzuna"] if os.environ.get("ADZUNA_APP_ID") else [])
    sources = st.multiselect("Job sites to search", SOURCES, default=default_sources,
                             help="No sign-up needed for any of these except Adzuna. Indeed has the most "
                                  "hourly jobs. Google Jobs, Glassdoor and ZipRecruiter often block automated "
                                  "searches; if one returns nothing, just leave it out.")

    def run_search(opts: SearchOptions, merge: bool = False) -> None:
        with st.spinner("Searching... (a few minutes for big searches)"):
            jobs, warnings = search_jobs(opts)
        for w in warnings:
            st.warning(w)
        # Jobs she can't get (degree, license, senior or technical roles) are dropped here,
        # so they never reach the results, the tracker or the queue.
        quals, rt = qualifications(), resume_text()
        keep, removed = [], []
        for job in jobs:
            fit = check_fit(job.to_dict(), quals, rt)
            if fit.level == "no":
                removed.append({"title": job.title, "company": job.company, "why": "; ".join(fit.reasons)})
            else:
                keep.append(job)
        added = tracker.add_jobs(keep)
        new_results = [j.to_dict() for j in keep]
        if merge:
            have = {j["id"] for j in st.session_state.get("results", [])}
            new_results = st.session_state.get("results", []) + [j for j in new_results if j["id"] not in have]
            removed = st.session_state.get("removed", []) + removed
        st.session_state["results"] = new_results
        st.session_state["removed"] = removed
        st.session_state["industry"] = (opts.industries or ["Any"])[0]
        st.success(f"Found {len(keep)} jobs ({added} new to you).")

    if st.button("🔎 Search", type="primary"):
        run_search(SearchOptions(location=location, radius_miles=radius, job_types=job_types,
                                 industries=industries, extra_keywords=extra, max_days_old=int(max_days),
                                 sources=sources))

    with st.expander("🗺️ Employers near you (stores and restaurants that may not post on job sites)"):
        st.write("Lots of local hiring never reaches job sites: Publix only takes applications on its own "
                 "site, many franchise restaurants use their own hiring pages, and small places just put a "
                 "sign in the window. This lists the real businesses within your radius, from OpenStreetMap, "
                 "with links to each one's jobs.")
        if st.button("Find employers near me", disabled=not location):
            try:
                with st.spinner("Looking up businesses on the map..."):
                    st.session_state["employers"] = [e.to_dict() for e in find_employers(location, radius)]
                    st.session_state["employers_for"] = (location, radius)
            except Exception as e:  # noqa: BLE001
                st.error(f"Couldn't load the map data: {e}")
        emps = st.session_state.get("employers", [])
        if emps:
            place, rad = st.session_state["employers_for"]
            cats = st.multiselect("Show", ["Fast food / Restaurant", "Grocery", "Retail"],
                                  default=["Fast food / Restaurant", "Grocery", "Retail"], key="emp_cats")
            rows = []
            for e in emps:
                if e["category"] not in cats:
                    continue
                links = job_links(e["name"], place, rad)
                rows.append({"search": False, "employer": e["name"], "type": e["category"],
                             "locations": e["locations"], "address": e["address"] if e["locations"] == 1 else "",
                             "google jobs": links["Google jobs"], "indeed": links["Indeed"],
                             "careers page": links["Careers page"]})
            st.caption(f"{len(rows)} employers within {rad} miles of {place}. The links open each one's job "
                       "listings in your browser. Tick employers and press the button below to pull their "
                       "job-site postings into your results.")
            picked_rows = st.data_editor(
                rows, hide_index=True, width="stretch", key="emp_editor",
                disabled=[k for k in (rows[0] if rows else {}) if k != "search"],
                column_config={k: st.column_config.LinkColumn(k, display_text="open")
                               for k in ("google jobs", "indeed", "careers page")},
            )
            names = [r["employer"] for r in picked_rows if r["search"]]
            if st.button(f"🔎 Search job sites for {len(names)} ticked employers", disabled=not names):
                run_search(SearchOptions(location=location, radius_miles=radius, job_types=job_types,
                                         industries=["Any"], extra_keywords=", ".join(names[:40]),
                                         max_days_old=int(max_days), sources=sources, per_query=25),
                           merge=True)

    results = st.session_state.get("results", [])
    if results:
        rt = resume_text()
        if st.button("🛡️ Research these companies (scam check)",
                     help="Looks up each company's website and how old it is. Takes a few seconds per company."):
            bar = st.progress(0.0, text="Checking companies...")
            cache: dict = {}
            for i, j in enumerate(results):
                tracker.save_research(j["id"], assess(j, online=True, cache=cache).to_dict())
                bar.progress((i + 1) / len(results), text=f"Checked {j['company'] or j['title']}")
            bar.empty()
            st.success("Done. See the safety column, and the list below the table.")

        risks: dict[str, dict] = {}
        for j in results:
            risks[j["id"]] = tracker.research(j["id"]) or assess(j).to_dict()
        labels = {k: risk_label(r["level"]) for k, r in risks.items()}
        fits = {j["id"]: check_fit(j, qualifications(), rt) for j in results}
        results = [j for j in results if fits[j["id"]].level != "no"]  # if her qualifications changed
        removed = st.session_state.get("removed", [])
        if removed:
            with st.expander(f"Removed {len(removed)} jobs that need a degree, license or experience she "
                             "doesn't have"):
                st.dataframe(removed, hide_index=True, width="stretch")
        rows = []
        for j in results:
            status = tracker.status_of(j["id"]) or "new"
            score = analyze(rt, [j["description"]], st.session_state.get("industry", "Any")).score if rt else None
            rows.append({
                "queue": status == "queued",
                "title": j["title"], "company": j["company"], "fit": fits[j["id"]].label,
                "safety": labels[j["id"]],
                "location": j["location"], "type": j["job_type"].replace("_", " "), "remote": j["remote"], "pay": j["salary"],
                "match %": score, "status": status, "posted": j["posted"], "link": j["url"], "id": j["id"],
            })
        st.caption("Tick the jobs you want to apply to, then press *Queue selected*. "
                   "“match %” is how many of the posting's keywords your resume already has.")
        c1, c2 = st.columns(2)
        select_all = c1.checkbox("Select all new jobs (except possible scams)")
        if select_all:
            for r in rows:
                if r["status"] == "new" and risks[r["id"]]["level"] != "high":
                    r["queue"] = True
        edited: list[dict] = []
        if not rows:
            st.info("Every job in these results needs something she doesn't have. Try another industry.")
        else:
            edited = st.data_editor(
                rows, hide_index=True, width="stretch", disabled=[k for k in rows[0] if k != "queue"],
                column_config={"link": st.column_config.LinkColumn("link", display_text="open"),
                               "id": None,
                               "match %": st.column_config.ProgressColumn("match %", min_value=0, max_value=100)},
                key="results_editor",
            )
        if c2.button("➕ Queue selected"):
            n = 0
            for r in edited:
                if r["queue"] and r["status"] in ("new", "skipped", "needs_review"):
                    tracker.set_status(r["id"], "queued")
                    n += 1
            st.success(f"Queued {n} jobs. Go to the Apply tab.")
            st.rerun()

        stretch = [j for j in results if fits[j["id"]].level == "stretch"]
        if stretch:
            with st.expander(f"Why {len(stretch)} jobs are a stretch"):
                for j in stretch:
                    f = fits[j["id"]]
                    st.markdown(f"**{f.label} · {j['title']} — {j['company'] or '(no company)'}**  \n"
                                + "; ".join(f.reasons))
        flagged = [j for j in results if risks[j["id"]]["level"] != "low"]
        if flagged:
            with st.expander(f"Why {len(flagged)} jobs are flagged"):
                for j in sorted(flagged, key=lambda x: risks[x["id"]]["level"] != "high"):
                    r = risks[j["id"]]
                    st.markdown(f"**{labels[j['id']]} · {j['title']} — {j['company'] or '(no company)'}**")
                    for reason in r["reasons"]:
                        st.markdown(f"- {reason}")
                    st.markdown(" · ".join(f"[{name}]({url})" for name, url in r["links"].items()))
        st.caption("The scam check reads each posting for warning signs. *Research these companies* also "
                   "checks the company's website. A green result isn't a guarantee: never pay to get a job, "
                   "and never give your SSN or bank details before a real interview.")

# ------------------------------------------------------------------ resume tailoring
with tab_resume:
    st.subheader("Your skills bank")
    rt = resume_text()
    if not rt:
        st.info("Upload your resume in tab 1 first.")
    else:
        st.write("A separate resume is made automatically for **every job** you apply to. Each one puts the "
                 "skills that posting asks for at the top of the Skills section and in the summary, and "
                 "names the job title. It only uses skills from this bank, so keep it to things that are "
                 "true for you.")
        pool = st.session_state.get("results") or [r for r in tracker.rows() if r["status"] in ("new", "queued")]
        industry = st.selectbox("Industry", list(INDUSTRIES),
                                index=list(INDUSTRIES).index(st.session_state.get("industry", "Any")),
                                key="tailor_industry")
        report = analyze(rt, [j["description"] for j in pool], industry)
        bank = [k.lower() for k in profile.get("skill_bank", [])]
        hits = dict(report.keywords)
        options = list(dict.fromkeys(bank + report.present + report.missing))

        def fmt(k: str) -> str:
            return f"{k}  ({hits[k]} postings)" if hits.get(k) else k

        st.caption("Skills employers ask for are listed with how many of your search results mention them.")
        chosen = st.multiselect("Skills you have", options, default=bank or report.present, format_func=fmt)
        custom = st.text_input("Add other skills (comma separated)", placeholder="e.g. forklift certified, CPR")
        chosen += [c.strip().lower() for c in custom.split(",") if c.strip()]
        missing_now = [k for k in report.missing if k not in chosen][:12]
        if missing_now:
            st.write("**Often asked for, not in your bank yet:** " + ", ".join(missing_now))

        fmt_choice = st.radio("Resume file type to send", ["pdf", "docx"], horizontal=True,
                              index=0 if profile.get("resume_format", "pdf") == "pdf" else 1)
        if st.button("💾 Save skills", type="primary"):
            profile.update(skill_bank=list(dict.fromkeys(chosen)), resume_format=fmt_choice)
            save_profile(profile)
            st.success(f"Saved {len(profile['skill_bank'])} skills.")

        st.divider()
        st.subheader("Preview the resume for one job")
        if not pool:
            st.info("Search for jobs first.")
        else:
            idx = st.selectbox("Job", range(len(pool)),
                               format_func=lambda i: f"{pool[i]['title']} — {pool[i]['company']}")
            job = pool[idx]
            data, matched = tailor_for_job(rt, profile, job, chosen, fmt_choice)
            text = pdf_to_text(data) if fmt_choice == "pdf" else docx_to_text(data)
            before = analyze(rt, [job["description"]], industry).score
            after = analyze(text, [job["description"]], industry).score
            c1, c2 = st.columns(2)
            c1.metric("Keyword match for this job", f"{after}%", f"{after - before:+d} vs. original")
            c2.write("**Skills this posting asks for that you have:** " + (", ".join(matched) or "none"))
            st.download_button("⬇️ Download this version", data,
                               file_name=resume_filename(job, profile.get("full_name", ""), fmt_choice))

        with st.expander("Formatting tips that help ATS filters"):
            st.markdown(
                "- Text-based PDF or .docx. Scanned or image PDFs can't be read.\n"
                "- Standard headings: *Summary, Skills, Experience, Education*.\n"
                "- No tables, columns, text boxes, icons or photos. Parsers scramble them.\n"
                "- Use the employer's exact words (\"cash handling\", not \"handled money\")."
            )

# ------------------------------------------------------------------ apply
LOG = DATA_DIR / "apply_log.txt"


def launch(args: list[str]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    log = open(LOG, "w")  # noqa: SIM115 - handed to the child process
    subprocess.Popen([sys.executable, "-u", "-m", "jobapp.apply_assist", *args],
                     cwd=str(Path(__file__).parent), stdout=log, stderr=subprocess.STDOUT)


with tab_apply:
    queued = tracker.rows("queued")
    review = tracker.rows("needs_review")
    st.subheader(f"{len(queued)} jobs queued")
    if queued:
        st.dataframe([{"title": j["title"], "company": j["company"], "location": j["location"]}
                      for j in queued], hide_index=True, width="stretch")

    mode = st.radio("How should it apply?",
                    ["Automatically (it presses Submit)", "Review each one (you press Submit)"])
    ans = profile.get("answers", {})
    not_ready = [label for key, (label, opts) in ANSWERS.items()
                 if key in ("authorized", "over18", "sponsorship") and not ans.get(key)]
    if not profile.get("email") or not profile.get("phone"):
        not_ready.append("your email and phone")
    if not profile.get("resume_path"):
        not_ready.append("your resume")

    if mode.startswith("Auto"):
        c1, c2, c3 = st.columns(3)
        dry = c1.checkbox("Test run (fill forms, don't submit)", value=not tracker.counts().get("applied"))
        headless = c2.checkbox("Hide the browser window")
        cap = c3.number_input("Daily limit", 1, 200, 40,
                              help="Most job sites flag accounts that send hundreds a day.")
        limit = st.number_input("Jobs this run", 1, 500, max(1, min(len(queued), 40)))
        c1, c2 = st.columns(2)
        skip_risky = c1.checkbox("Skip possible scams (🔴)", value=profile.get("skip_risky", True))
        hold_check = c2.checkbox("Hold 🟡 \"check first\" jobs for me to look at",
                                 value=profile.get("hold_check", False))
        if (skip_risky, hold_check) != (profile.get("skip_risky", True), profile.get("hold_check", False)):
            profile.update(skip_risky=skip_risky, hold_check=hold_check)
            save_profile(profile)
        st.caption(
            "For each job it opens the posting, fills everything in, attaches a resume made for that job, "
            "and submits. Jobs it can't finish honestly (CAPTCHA, login needed, a question you haven't "
            "answered) go to **Needs review** with the reason. Before each job it runs the scam check, so "
            "your details aren't sent to companies that look fake. It waits 20-45 seconds between jobs. "
            "Indeed and LinkedIn don't allow automated applying and can suspend accounts, so jobs that "
            "need you signed in to them are best done in review mode.")
        if not_ready:
            st.warning("Fill in first (tab 1): " + ", ".join(not_ready))
        if st.button("▶️ Start", type="primary", disabled=not queued or bool(not_ready)):
            args = ["--mode", "auto", "--limit", str(int(limit)), "--daily-cap", str(int(cap))]
            args += ["--dry-run"] if dry else []
            args += ["--headless"] if headless else []
            launch(args)
            st.success("Started. Progress shows below; press Refresh to update it.")
    else:
        st.markdown(
            "It opens each job, fills in what it can and attaches that job's resume. You answer anything "
            "left and press the site's Submit, then use the bar at the bottom of the window: "
            "**Fill this form** (after the site changes page), **I applied ✓**, **Skip**, **Stop**.")
        if st.button("▶️ Start", type="primary", disabled=not queued):
            launch(["--mode", "review"])
            st.success("Browser opening...")

    if LOG.exists():
        st.subheader("Progress")
        st.button("🔄 Refresh")
        st.code("\n".join(LOG.read_text().splitlines()[-40:]) or "starting...")

    st.subheader(f"Needs review ({len(review)})")
    if review:
        st.dataframe([{"title": j["title"], "company": j["company"], "why": j["notes"]} for j in review],
                     hide_index=True, width="stretch")
        if st.button("Open these so I can finish them"):
            launch(["--mode", "review", "--status", "needs_review"])
            st.success("Browser opening...")

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
            if r["notes"]:
                st.info(r["notes"])
            risk = tracker.research(r["id"]) or assess(r).to_dict()
            if risk["level"] != "low":
                st.warning(f"{risk_label(risk['level'])}: "
                           + "; ".join(risk["reasons"]))
            st.markdown("Check this company: " + " · ".join(f"[{n}]({u})" for n, u in risk["links"].items()))
            st.write(r["description"][:1500])
            st.link_button("Open posting", r["url"])
            c1, c2 = st.columns([1, 3])
            new_status = c1.selectbox("Status", STATUSES, index=STATUSES.index(r["status"]), key=f"s_{r['id']}")
            notes = c2.text_input("Notes", value=r["notes"], key=f"n_{r['id']}")
            if st.button("Save", key=f"b_{r['id']}"):
                tracker.set_status(r["id"], new_status, notes)
                st.rerun()
