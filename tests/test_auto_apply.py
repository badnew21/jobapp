"""Runs the auto-submitter against local fake application forms."""

import functools
import os
import http.server
import threading
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

from jobapp.apply_assist import _on_dialog, auto_apply, dismiss_popups  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE = {
    "first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe", "email": "jane@example.com",
    "phone": "555-123-4567", "city": "Springfield", "state": "IL", "zip": "62701",
    "answers": {"authorized": "Yes", "weekends": "Yes", "desired_pay": "16"},
    "eeo_decline": True, "auto_agree_terms": True,
}


@pytest.fixture(scope="module")
def server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES))
    handler.log_message = lambda *a: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def ctx():
    with pw.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        context = browser.new_context()
        context.on("page", lambda pg: pg.on("dialog", _on_dialog))
        context.new_page()
        yield context
        browser.close()


@pytest.fixture
def resume(tmp_path):
    f = tmp_path / "Jane Doe Resume.pdf"
    f.write_bytes(b"%PDF-1.4 test")
    return str(f)


def test_multi_step_form_gets_submitted(server, ctx, resume):
    status, note = auto_apply(ctx, {"url": f"{server}/job.html"}, PROFILE, resume)
    assert (status, note) == ("applied", "Confirmation page seen")


def test_dry_run_stops_before_submit(server, ctx, resume):
    status, note = auto_apply(ctx, {"url": f"{server}/form.html"}, PROFILE, resume, dry_run=True)
    assert status == "needs_review" and note.startswith("Test run")
    page = ctx.pages[-1]
    assert page.input_value("#fn") == "Jane"
    assert page.input_value("#co") == ""            # not her company name
    assert page.is_checked("input[name=auth][value='1']")
    assert page.input_value("#wk") == "y"
    assert page.input_value("#g") == "d"            # EEO: declined
    assert page.input_value("#pay") == "16"


def test_unknown_question_is_not_guessed(server, ctx, resume):
    status, note = auto_apply(ctx, {"url": f"{server}/felony.html"}, PROFILE, resume)
    assert status == "needs_review"
    assert "felony" in note
    assert not ctx.pages[-1].is_checked("input[name=fel][value='0']")


def test_missing_consent_setting_blocks_submit(server, ctx, resume):
    status, note = auto_apply(ctx, {"url": f"{server}/form.html"}, PROFILE | {"auto_agree_terms": False}, resume)
    assert status == "needs_review" and "privacy" in note


def test_popups_closed_and_dark_pattern_boxes_unticked(server, ctx, resume):
    status, note = auto_apply(ctx, {"url": f"{server}/popup_job.html"}, PROFILE, resume)
    # The form posts to a "similar jobs" page with no confirmation. It must NOT click "Apply" there
    # (that would apply her to other jobs) and must say it isn't sure.
    assert status == "needs_review" and "check" in note
    url = ctx.pages[-1].url
    assert "after_submit.html" in url, url
    assert "terms=on" in url                      # required "I agree" ticked
    assert "sms=on" not in url and "share=on" not in url   # pre-ticked marketing boxes unticked


def test_newsletter_popup_not_filled_or_submitted(server, ctx, resume):
    page = ctx.pages[0]
    page.goto(f"{server}/popup_job.html")
    assert dismiss_popups(page) >= 2               # newsletter + cookie banner
    assert page.locator("input[name=newsletter_email]").count() == 0
    assert page.title() != "SUBSCRIBED"
    assert not page.locator("#intercom-container").is_visible()


def test_application_inside_a_modal_is_not_dismissed(server, ctx, resume):
    status, note = auto_apply(ctx, {"url": f"{server}/modal_form.html"}, PROFILE, resume)
    assert (status, note) == ("applied", "Confirmation page seen")


def test_closed_posting_is_skipped(server, ctx, resume):
    assert auto_apply(ctx, {"url": f"{server}/closed.html"}, PROFILE, resume) == (
        "skipped", "Posting is closed or expired")


def test_guest_option_used_on_login_wall(server, ctx, resume):
    status, _ = auto_apply(ctx, {"url": f"{server}/guest.html"}, PROFILE, resume)
    assert status == "applied"


def test_payment_page_is_skipped(server, ctx, resume):
    status, note = auto_apply(ctx, {"url": f"{server}/pay.html"}, PROFILE, resume)
    assert status == "skipped" and "payment" in note


def test_redirect_is_followed(server, ctx, resume):
    status, _ = auto_apply(ctx, {"url": f"{server}/redirect.html"}, PROFILE, resume)
    assert status == "applied"


def test_leave_page_dialog_does_not_block_next_job(server, ctx, resume):
    page = ctx.pages[0]
    page.goto(f"{server}/darkform.html")
    page.fill("#fn", "Jane")                      # arms the "Leave site?" dialog
    status, _ = auto_apply(ctx, {"url": f"{server}/job.html"}, PROFILE, resume)
    assert status == "applied"
