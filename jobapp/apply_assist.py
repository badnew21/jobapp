"""Apply assistant: walks through queued jobs in a real browser window.

For each job it opens the posting, clicks an "Apply" button if it finds one,
fills in name / email / phone / address and attaches the resume. A bar at the
bottom of the window lets her fill the form again (after a page change), mark
the job applied, skip it, or stop.

It never presses the final Submit button by itself. Application forms ask
screening questions (availability, work authorization, pay) that only she can
answer, many sites use CAPTCHAs, and job boards ban accounts that submit
automatically.

Run from the app, or by hand:
    python -m jobapp.apply_assist            # every job marked "queued"
    python -m jobapp.apply_assist --limit 10
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .profile import DATA_DIR, load_profile
from .tracker import Tracker

BROWSER_PROFILE = DATA_DIR / "browser"

APPLY_BUTTON_TEXT = [
    "Apply now", "Easy Apply", "Apply on company site", "Apply for this job",
    "Apply to this job", "Start application", "Apply",
]

OVERLAY_JS = r"""
(() => {
  if (window !== window.top) return;
  const build = async () => {
    if (document.getElementById('jobapp-bar')) return;
    const info = await window.jobappInfo();
    const bar = document.createElement('div');
    bar.id = 'jobapp-bar';
    bar.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;' +
      'background:#1f2937;color:#fff;font:14px system-ui,sans-serif;padding:10px 14px;' +
      'display:flex;gap:8px;align-items:center;flex-wrap:wrap;box-shadow:0 -2px 8px rgba(0,0,0,.3)';
    const label = document.createElement('span');
    label.style.cssText = 'flex:1;min-width:200px';
    label.textContent = info;
    bar.appendChild(label);
    const btn = (text, color, fn) => {
      const b = document.createElement('button');
      b.textContent = text;
      b.style.cssText = 'border:0;border-radius:6px;padding:8px 12px;font-weight:600;cursor:pointer;' +
        'color:#fff;background:' + color;
      b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); fn(); };
      bar.appendChild(b);
    };
    btn('Fill this form', '#2563eb', () => window.jobappFill());
    btn('I applied ✓', '#16a34a', () => window.jobappDecide('applied'));
    btn('Skip', '#6b7280', () => window.jobappDecide('skipped'));
    btn('Stop', '#dc2626', () => window.jobappDecide('stop'));
    document.documentElement.appendChild(bar);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
  else build();
})();
"""

# Fills empty text fields whose label/name/placeholder matches a rule.
FILL_JS = r"""
(rules) => {
  const setVal = (el, v) => {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    el.dispatchEvent(new Event('blur', {bubbles: true}));
  };
  const describe = (el) => {
    let txt = [el.name, el.id, el.placeholder, el.getAttribute('aria-label'),
               el.getAttribute('autocomplete'), el.getAttribute('data-automation-id')];
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) txt.push(l.innerText); }
    const wrap = el.closest('label'); if (wrap) txt.push(wrap.innerText);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) lb.split(' ').forEach(i => { const n = document.getElementById(i); if (n) txt.push(n.innerText); });
    return txt.filter(Boolean).join(' ').toLowerCase();
  };
  let filled = 0;
  const fields = document.querySelectorAll('input[type=text],input[type=email],input[type=tel],input:not([type]),textarea');
  for (const el of fields) {
    if (el.value || el.disabled || el.readOnly || el.offsetParent === null) continue;
    const d = describe(el);
    if (el.tagName === 'TEXTAREA' && !/address|linkedin/.test(d)) continue;
    for (const [pattern, exclude, value] of rules) {
      if (!value) continue;
      if (new RegExp(pattern).test(d) && !(exclude && new RegExp(exclude).test(d))) {
        setVal(el, value); filled++; break;
      }
    }
  }
  return filled;
}
"""


def fill_rules(profile: dict) -> list[tuple[str, str, str]]:
    """(pattern, exclude pattern, value). First match wins."""
    not_other = "company|employer|user|school|reference|manager|supervisor|contact|emergency|referr"
    return [
        (r"first.?name|given.?name|fname|legalnamesection_firstname", not_other, profile.get("first_name", "")),
        (r"last.?name|family.?name|surname|lname|legalnamesection_lastname", not_other, profile.get("last_name", "")),
        (r"e-?mail", "confirm.*no|reference|emergency", profile.get("email", "")),
        (r"phone|mobile|cell|\btel\b", "emergency|reference|extension|country", profile.get("phone", "")),
        (r"linkedin", "", profile.get("linkedin", "")),
        (r"\bzip|postal", "", profile.get("zip", "")),
        (r"\bcity\b|addresssection_city", "", profile.get("city", "")),
        (r"\bstate\b|province|region", "statement|united states", profile.get("state", "")),
        (r"street|address.?(line)?.?1|^address|addresssection_addressline1", "e-?mail|line.?2|web", profile.get("street", "")),
        (r"full.?name|your name|legal name|\bname\b", not_other + "|first|last|middle|preferred|nick", profile.get("full_name", "")),
    ]


def autofill(page, profile: dict, resume_path: str) -> int:
    rules = fill_rules(profile)
    total = 0
    for frame in page.frames:
        try:
            total += frame.evaluate(FILL_JS, rules)
            if resume_path:
                for inp in frame.query_selector_all("input[type=file]"):
                    if not inp.evaluate("e => e.files && e.files.length > 0"):
                        inp.set_input_files(resume_path)
                        total += 1
                        break
        except Exception:  # noqa: BLE001 - cross-origin or detached frames
            continue
    return total


def click_apply(page) -> bool:
    for text in APPLY_BUTTON_TEXT:
        for role in ("button", "link"):
            loc = page.get_by_role(role, name=text, exact=False)
            try:
                if loc.count() and loc.first.is_visible():
                    loc.first.click(timeout=3000)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    return True
            except Exception:  # noqa: BLE001
                continue
    return False


def run(limit: int | None = None, job_ids: list[str] | None = None) -> None:
    from playwright.sync_api import sync_playwright

    tracker = Tracker()
    profile = load_profile()
    resume_path = profile.get("tailored_resume_path") or profile.get("resume_path") or ""
    if resume_path and not Path(resume_path).exists():
        resume_path = ""

    jobs = tracker.rows("queued")
    if job_ids:
        wanted = set(job_ids)
        jobs = [j for j in tracker.rows() if j["id"] in wanted]
    if limit:
        jobs = jobs[:limit]
    if not jobs:
        print("No queued jobs. Queue some in the app first.")
        return

    state = {"decision": None, "fill": False, "info": ""}

    with sync_playwright() as p:
        BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
        # A persistent profile keeps her logged in to Indeed / Workday / etc. between runs.
        ctx = p.chromium.launch_persistent_context(str(BROWSER_PROFILE), headless=False, no_viewport=True)
        ctx.expose_binding("jobappDecide", lambda source, v: state.update(decision=v))
        ctx.expose_binding("jobappFill", lambda source: state.update(fill=source["page"]))
        ctx.expose_binding("jobappInfo", lambda source: state["info"])
        ctx.add_init_script(OVERLAY_JS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        for n, job in enumerate(jobs, 1):
            state.update(decision=None, fill=False,
                         info=f"[{n}/{len(jobs)}] {job['title']} - {job['company']}")
            print(state["info"])
            try:
                page.goto(job["url"], wait_until="domcontentloaded", timeout=45000)
                click_apply(page)
                page.wait_for_timeout(1500)
                autofill(ctx.pages[-1], profile, resume_path)
            except Exception as e:  # noqa: BLE001
                print(f"  couldn't load: {e}")

            while state["decision"] is None:
                if not ctx.pages:
                    state["decision"] = "stop"
                    break
                if state["fill"]:
                    target, state["fill"] = state["fill"], False
                    try:
                        print(f"  filled {autofill(target, profile, resume_path)} fields")
                    except Exception as e:  # noqa: BLE001
                        print(f"  fill failed: {e}")
                ctx.pages[0].wait_for_timeout(400)

            if state["decision"] == "stop":
                print("Stopped.")
                break
            tracker.set_status(job["id"], state["decision"])
            print(f"  -> {state['decision']}")
            # Close extra tabs the application opened, keep one for the next job.
            for extra in ctx.pages[1:]:
                extra.close()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", help="JSON list of job ids (otherwise all queued jobs)")
    args = ap.parse_args()
    run(limit=args.limit, job_ids=json.loads(args.ids) if args.ids else None)


if __name__ == "__main__":
    main()
