"""Applies to queued jobs in a real browser.

Two modes:

  auto   (default) For each job: open the posting, click Apply, fill in her
         details, answer the screening questions she set up, attach a resume
         tailored to that posting, click Next/Submit, and check for a
         confirmation page. If something comes up that it can't handle
         honestly (a CAPTCHA, a login wall, a question she hasn't answered, an
         error after submitting), it marks the job "needs_review" with the
         reason and moves on. It never guesses an answer.

  review Same filling, but it stops on each job and she presses Submit
         herself. A bar at the bottom of the window has Fill / I applied / Skip / Stop.

    python -m jobapp.apply_assist                    # auto, all queued jobs
    python -m jobapp.apply_assist --dry-run          # auto, but never clicks the final Submit
    python -m jobapp.apply_assist --mode review --status needs_review
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from pathlib import Path

from .profile import DATA_DIR, load_profile
from .resume import read_resume, resume_filename, tailor_for_job
from .tracker import Tracker

BROWSER_PROFILE = DATA_DIR / "browser"
RESUME_DIR = DATA_DIR / "resumes"

APPLY_BUTTON_TEXT = [
    "Apply now", "Easy Apply", "Apply on company site", "Apply for this job",
    "Apply to this job", "Start application", "Apply",
]
SUBMIT_RE = re.compile(
    r"^\s*(submit( my| your)?( application)?|send( my)? application|complete( my)? application|"
    r"finish( application)?|apply( now)?)\s*$", re.I)
NEXT_RE = re.compile(r"^\s*(next( step)?|continue|save (and|&) continue|proceed|review( application)?)\s*[›>→]?\s*$", re.I)
CONFIRM_RE = re.compile(
    r"thank(s| you) for (applying|your application|your interest)|application (has been |was )?"
    r"(received|submitted|complete)|we('ve| have) received your application|successfully (submitted|applied)|"
    r"you('ve| have) (successfully )?applied", re.I)
ERROR_RE = re.compile(
    r"this field is required|(is|are) required\b|please (fill|select|enter|complete|answer|provide)|"
    r"required field|fix the (following )?errors|invalid (email|phone)", re.I)
CAPTCHA_RE = re.compile(r"recaptcha|hcaptcha|turnstile|challenges\.cloudflare|arkoselabs|funcaptcha", re.I)

# (question pattern, profile answer key). First match wins, so specific ones go first.
QUESTION_RULES = [
    (r"sponsor", "sponsorship"),
    (r"authori[sz]ed to work|legally (eligible|able|permitted) to work|eligible to work|right to work", "authorized"),
    (r"\b18\b.*(older|age|years)|at least 18|over (the age of )?18|age of 18|of legal (working )?age", "over18"),
    (r"relocat", "relocate"),
    (r"drug (test|screen)|background (check|screen)", "drug_test"),
    (r"transportation|reliable (means|way) to (get|commute)", "transportation"),
    (r"weekend|saturday|sunday", "weekends"),
    (r"\bnights?\b|evening|overnight|late shift|closing shift", "nights"),
]
EEO_RE = r"gender|\bsex\b|\brace\b|ethnicity|hispanic|latino|veteran|disabilit|pronoun|sexual orientation"
DECLINE_RE = r"decline|prefer not|don'?t wish|do not wish|not to (say|disclose|answer|identify|self)|choose not"
AGREE_RE = r"\bi agree|acknowledge|consent|i certify|i attest|privacy (policy|notice)|terms (of|and)"

OVERLAY_JS = r"""
(() => {
  if (window !== window.top) return;
  const build = async () => {
    if (document.getElementById('jobapp-bar')) return;
    const info = await window.jobappInfo();
    if (!info) return;
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

# Shared helpers injected ahead of each script below.
HELPERS_JS = r"""
const visible = (el) => !!(el.offsetParent || el.getClientRects().length) &&
  getComputedStyle(el).visibility !== 'hidden';
const textOf = (n) => (n && (n.innerText || n.textContent) || '').trim();
const describe = (el) => {
  let txt = [el.name, el.id, el.placeholder, el.getAttribute('aria-label'),
             el.getAttribute('autocomplete'), el.getAttribute('data-automation-id')];
  if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) txt.push(textOf(l)); }
  const wrap = el.closest('label'); if (wrap) txt.push(textOf(wrap));
  const lb = el.getAttribute('aria-labelledby');
  if (lb) lb.split(' ').forEach(i => { const n = document.getElementById(i); if (n) txt.push(textOf(n)); });
  return txt.filter(Boolean).join(' ').toLowerCase();
};
const optionLabel = (el) => {
  if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) return textOf(l); }
  const wrap = el.closest('label'); if (wrap) return textOf(wrap);
  return el.getAttribute('aria-label') || el.value || '';
};
const groupQuestion = (el) => {
  const fs = el.closest('fieldset');
  if (fs) { const lg = fs.querySelector('legend'); if (lg) return textOf(lg).toLowerCase(); }
  const grp = el.closest('[role=radiogroup],[role=group]');
  if (grp) {
    const lb = grp.getAttribute('aria-labelledby');
    if (lb) return lb.split(' ').map(i => textOf(document.getElementById(i))).join(' ').toLowerCase();
    if (grp.getAttribute('aria-label')) return grp.getAttribute('aria-label').toLowerCase();
  }
  // Fall back to the nearest ancestor that has text besides the option labels.
  let node = el.parentElement;
  for (let i = 0; i < 5 && node; i++, node = node.parentElement) {
    const radios = node.querySelectorAll('input[name="' + CSS.escape(el.name) + '"]');
    let t = textOf(node);
    radios.forEach(r => { t = t.replace(optionLabel(r), ''); });
    if (t.trim().length > 8) return t.trim().slice(0, 300).toLowerCase();
  }
  return describe(el);
};
"""

# Fills empty text fields whose label/name/placeholder matches a rule.
FILL_JS = "(rules) => {" + HELPERS_JS + r"""
  const setVal = (el, v) => {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    el.dispatchEvent(new Event('blur', {bubbles: true}));
  };
  let filled = 0;
  const fields = document.querySelectorAll(
    'input[type=text],input[type=email],input[type=tel],input[type=number],input[type=url],input:not([type]),textarea');
  for (const el of fields) {
    if (el.value || el.disabled || el.readOnly || !visible(el)) continue;
    const d = describe(el);
    if (el.tagName === 'TEXTAREA' && !/address|linkedin|hear about|find us/.test(d)) continue;
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

# Answers yes/no style questions (selects, radio groups) and EEO / consent items.
CHOICE_JS = "([rules, eeoRe, declineRe, eeoDecline, agreeRe, autoAgree]) => {" + HELPERS_JS + r"""
  const pick = (q) => {
    if (eeoDecline && new RegExp(eeoRe).test(q)) return '__decline__';
    for (const [pattern, answer] of rules) if (answer && new RegExp(pattern).test(q)) return answer;
    return null;
  };
  const matches = (label, answer) => {
    label = label.trim().toLowerCase();
    if (answer === '__decline__') return new RegExp(declineRe).test(label);
    return label === answer.toLowerCase() || label.startsWith(answer.toLowerCase() + ' ') ||
           label.startsWith(answer.toLowerCase() + ',');
  };
  let answered = 0;
  for (const el of document.querySelectorAll('select')) {
    if (el.disabled || !visible(el)) continue;
    const cur = el.options[el.selectedIndex];
    if (cur && cur.value && el.selectedIndex > 0) continue;
    const a = pick(describe(el)); if (!a) continue;
    const opt = [...el.options].find(o => o.value && matches(o.text, a));
    if (opt) {
      el.value = opt.value;
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      answered++;
    }
  }
  const groups = {};
  for (const r of document.querySelectorAll('input[type=radio]')) if (r.name && visible(r)) (groups[r.name] ||= []).push(r);
  for (const radios of Object.values(groups)) {
    if (radios.some(r => r.checked)) continue;
    const a = pick(groupQuestion(radios[0])); if (!a) continue;
    const r = radios.find(x => matches(optionLabel(x), a));
    if (r) { r.click(); answered++; }
  }
  if (autoAgree) {
    for (const c of document.querySelectorAll('input[type=checkbox]')) {
      if (c.checked || !visible(c)) continue;
      if (new RegExp(agreeRe).test(optionLabel(c).toLowerCase() + ' ' + describe(c))) { c.click(); answered++; }
    }
  }
  return answered;
}
"""

# Lists required fields that are still empty.
MISSING_JS = "() => {" + HELPERS_JS + r"""
  const out = [];
  const req = (el) => el.required || el.getAttribute('aria-required') === 'true';
  const seen = new Set();
  for (const el of document.querySelectorAll('input,select,textarea')) {
    if (!req(el) || el.disabled || el.type === 'hidden') continue;
    if (el.type === 'file') { if (!el.files.length) out.push('file upload: ' + describe(el).slice(0, 60)); continue; }
    if (!visible(el)) continue;
    if (el.type === 'radio') {
      if (seen.has(el.name)) continue; seen.add(el.name);
      const any = document.querySelectorAll('input[name="' + CSS.escape(el.name) + '"]:checked').length;
      if (!any) out.push(groupQuestion(el).slice(0, 80));
    } else if (el.type === 'checkbox') {
      if (!el.checked) out.push(optionLabel(el).slice(0, 80));
    } else if (!el.value || (el.tagName === 'SELECT' && el.selectedIndex <= 0 && !el.options[0]?.value)) {
      out.push(describe(el).slice(0, 80));
    }
  }
  return out;
}
"""


def fill_rules(profile: dict) -> list[tuple[str, str, str]]:
    """(pattern, exclude pattern, value) for text fields. First match wins."""
    not_other = "company|employer|user|school|reference|manager|supervisor|contact|emergency|referr"
    ans = profile.get("answers", {})
    return [
        (r"first.?name|given.?name|fname|legalnamesection_firstname", not_other, profile.get("first_name", "")),
        (r"last.?name|family.?name|surname|lname|legalnamesection_lastname", not_other, profile.get("last_name", "")),
        (r"e-?mail", "confirm.*no|reference|emergency", profile.get("email", "")),
        (r"phone|mobile|cell|\btel\b", "emergency|reference|extension|country|type", profile.get("phone", "")),
        (r"linkedin", "", profile.get("linkedin", "")),
        (r"\bzip|postal", "", profile.get("zip", "")),
        (r"\bcity\b|addresssection_city", "", profile.get("city", "")),
        (r"\bstate\b|province|region", "statement|united states|state why|state your", profile.get("state", "")),
        (r"street|address.?(line)?.?1|^address|addresssection_addressline1", "e-?mail|line.?2|web", profile.get("street", "")),
        (r"desired (pay|salary|wage|compensation|rate)|(pay|salary|wage) (expectation|requirement)|expected (pay|salary|wage)|hourly rate",
         "", ans.get("desired_pay", "")),
        (r"start date|available to start|when can you start|date available|availability date", "", ans.get("start_date", "")),
        (r"years? of (relevant |related )?experience|how many years", "", ans.get("years_experience", "")),
        (r"how did you (hear|find|learn)|hear about (us|this)", "", ans.get("how_heard", "")),
        (r"full.?name|your name|legal name|\bname\b", not_other + "|first|last|middle|preferred|nick", profile.get("full_name", "")),
    ]


def choice_args(profile: dict) -> list:
    ans = profile.get("answers", {})
    rules = [(pat, ans.get(key, "")) for pat, key in QUESTION_RULES]
    return [rules, EEO_RE, DECLINE_RE, bool(profile.get("eeo_decline", True)),
            AGREE_RE, bool(profile.get("auto_agree_terms", False))]


def _frames(page):
    for frame in page.frames:
        if not frame.is_detached():
            yield frame


def autofill(page, profile: dict, resume_path: str) -> int:
    rules, choices = fill_rules(profile), choice_args(profile)
    total = 0
    for frame in _frames(page):
        try:
            total += frame.evaluate(FILL_JS, rules)
            total += frame.evaluate(CHOICE_JS, choices)
            if resume_path:
                for inp in frame.query_selector_all("input[type=file]"):
                    if not inp.evaluate("e => e.files && e.files.length > 0"):
                        inp.set_input_files(resume_path)
                        total += 1
                        break
        except Exception:  # noqa: BLE001 - cross-origin or detached frames
            continue
    return total


def missing_required(page) -> list[str]:
    out: list[str] = []
    for frame in _frames(page):
        try:
            out += frame.evaluate(MISSING_JS)
        except Exception:  # noqa: BLE001
            continue
    return [m.strip() for m in out if m.strip()]


def page_text(page) -> str:
    chunks = []
    for frame in _frames(page):
        try:
            chunks.append(frame.evaluate("() => document.body ? document.body.innerText : ''"))
        except Exception:  # noqa: BLE001
            continue
    return "\n".join(chunks)


def blocker(page) -> str | None:
    for frame in _frames(page):
        if CAPTCHA_RE.search(frame.url) and "invisible" not in frame.url:
            return "CAPTCHA on the page"
    for frame in _frames(page):
        try:
            if frame.locator("input[type=password]:visible").count():
                return "Site wants a login or new account"
        except Exception:  # noqa: BLE001
            continue
    return None


def has_form(page) -> bool:
    for frame in _frames(page):
        try:
            if frame.locator("input[type=email]:visible, input[type=file], input[type=tel]:visible").count():
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def find_action(page):
    """Returns (locator, 'submit' | 'next') for the button that moves the form forward."""
    for kind, rx in (("next", NEXT_RE), ("submit", SUBMIT_RE)):
        for frame in _frames(page):
            try:
                for loc in (frame.get_by_role("button", name=rx), frame.locator("input[type=submit]")):
                    for i in range(loc.count()):
                        el = loc.nth(i)
                        if not el.is_visible() or not el.is_enabled():
                            continue
                        if el.evaluate("e => e.tagName") == "INPUT" and not rx.match(el.get_attribute("value") or ""):
                            continue
                        return el, kind
            except Exception:  # noqa: BLE001
                continue
    return None, None


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


def _settle(page, ms: int = 2500) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(ms)


def auto_apply(ctx, job: dict, profile: dict, resume_path: str, dry_run: bool = False) -> tuple[str, str]:
    """Returns (status, note)."""
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(job["url"], wait_until="domcontentloaded", timeout=45000)
    _settle(page)

    # Job boards often take two hops (board -> company site -> form).
    for _ in range(2):
        target = ctx.pages[-1]
        if has_form(target) or CONFIRM_RE.search(page_text(target)):
            break
        if not click_apply(target):
            break
        _settle(ctx.pages[-1])

    clicked_submit = False
    for _ in range(10):
        target = ctx.pages[-1]
        if CONFIRM_RE.search(page_text(target)):
            return "applied", "Confirmation page seen"
        reason = blocker(target)
        if reason:
            return "needs_review", reason
        if not has_form(target) and not clicked_submit:
            return "needs_review", "Couldn't find the application form"
        autofill(target, profile, resume_path)
        target.wait_for_timeout(800)
        missing = missing_required(target)
        if missing:
            return "needs_review", "Unanswered: " + "; ".join(missing[:3])
        button, kind = find_action(target)
        if not button:
            note = "No Submit button found"
            return "needs_review", note + (" (it may have gone through; check)" if clicked_submit else "")
        if kind == "submit" and dry_run:
            return "needs_review", "Test run: form filled, ready to submit"
        button.click(timeout=5000)
        clicked_submit = clicked_submit or kind == "submit"
        _settle(ctx.pages[-1], 3000)
        text = page_text(ctx.pages[-1])
        if CONFIRM_RE.search(text):
            return "applied", "Confirmation page seen"
        if kind == "submit" and ERROR_RE.search(text) and missing_required(ctx.pages[-1]):
            return "needs_review", "Form showed an error after Submit"
    return "needs_review", "Submitted but no confirmation seen; check your email"


def resume_for(job: dict, profile: dict, base_text: str) -> str:
    fmt = profile.get("resume_format", "pdf")
    data, _ = tailor_for_job(base_text, profile, job, profile.get("skill_bank", []), fmt)
    folder = RESUME_DIR / re.sub(r"[^A-Za-z0-9]+", "_", job["id"])
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / resume_filename(job, profile.get("full_name", ""), fmt)
    path.write_bytes(data)
    return str(path)


def run(limit: int | None = None, job_ids: list[str] | None = None, mode: str = "auto",
        status: str = "queued", headless: bool = False, dry_run: bool = False,
        daily_cap: int = 40, pause: tuple[int, int] = (20, 45)) -> None:
    from playwright.sync_api import sync_playwright

    tracker = Tracker()
    profile = load_profile()
    src = profile.get("resume_path", "")
    if not src or not Path(src).exists():
        print("No resume uploaded. Upload one in the app first.")
        return
    base_text = read_resume(src, Path(src).read_bytes())

    jobs = tracker.rows(status)
    if job_ids:
        wanted = set(job_ids)
        jobs = [j for j in tracker.rows() if j["id"] in wanted]
    jobs.reverse()  # oldest first
    if mode == "auto" and not dry_run:
        room = max(0, daily_cap - tracker.applied_today())
        if room == 0:
            print(f"Daily limit of {daily_cap} applications reached. Try again tomorrow.")
            return
        jobs = jobs[:room]
    if limit:
        jobs = jobs[:limit]
    if not jobs:
        print(f"No jobs with status '{status}'.")
        return

    state = {"decision": None, "fill": False, "info": ""}

    with sync_playwright() as p:
        BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
        # A persistent profile keeps her logged in to Indeed / Workday / etc. between runs.
        ctx = p.chromium.launch_persistent_context(
            str(BROWSER_PROFILE), headless=headless and mode == "auto", no_viewport=True,
            executable_path=os.environ.get("CHROMIUM_PATH") or None)
        ctx.expose_binding("jobappDecide", lambda source, v: state.update(decision=v))
        ctx.expose_binding("jobappFill", lambda source: state.update(fill=source["page"]))
        ctx.expose_binding("jobappInfo", lambda source: state["info"] if mode == "review" else "")
        ctx.add_init_script(OVERLAY_JS)
        if not ctx.pages:
            ctx.new_page()

        for n, job in enumerate(jobs, 1):
            label = f"[{n}/{len(jobs)}] {job['title']} - {job['company']}"
            state.update(decision=None, fill=False, info=label)
            print(label, flush=True)
            resume_path = resume_for(job, profile, base_text)

            if mode == "auto":
                try:
                    result, note = auto_apply(ctx, job, profile, resume_path, dry_run)
                except Exception as e:  # noqa: BLE001
                    result, note = "needs_review", f"Error: {str(e).splitlines()[0][:150]}"
                tracker.set_status(job["id"], result, note)
                print(f"  -> {result}: {note}", flush=True)
                for extra in ctx.pages[1:]:
                    extra.close()
                if n < len(jobs):
                    time.sleep(random.uniform(*pause))  # don't hammer sites; looks less like a bot
                continue

            page = ctx.pages[0] if ctx.pages else ctx.new_page()
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
            tracker.set_status(job["id"], state["decision"], "")
            print(f"  -> {state['decision']}")
            for extra in ctx.pages[1:]:
                extra.close()
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass
    print("Done.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["auto", "review"], default="auto")
    ap.add_argument("--status", default="queued", help="which jobs to work on (queued, needs_review, ...)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", help="JSON list of job ids")
    ap.add_argument("--headless", action="store_true", help="auto mode: don't show the browser")
    ap.add_argument("--dry-run", action="store_true", help="auto mode: fill everything but don't click Submit")
    ap.add_argument("--daily-cap", type=int, default=40)
    args = ap.parse_args()
    run(limit=args.limit, job_ids=json.loads(args.ids) if args.ids else None, mode=args.mode,
        status=args.status, headless=args.headless, dry_run=args.dry_run, daily_cap=args.daily_cap)


if __name__ == "__main__":
    main()
