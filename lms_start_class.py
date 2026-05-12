"""
lms_start_class.py
------------------
Loads saved auth session and clicks "Start Class" on ClassEdge.
Called automatically by Windows Task Scheduler — do not run manually.

Usage:
  python lms_start_class.py --url "https://classedge.hccci.edu.ph/subjectDetail/331/?semester="
"""

import argparse
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

AUTH_FILE       = Path(__file__).parent / "auth.json"
LOG_FILE        = Path(__file__).parent / "start_class.log"
SCREENSHOTS_DIR = Path(__file__).parent / "errors"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def screenshot_error(page, label: str) -> str:
    """Take a screenshot, save to errors/ with timestamp, return the path."""
    try:
        SCREENSHOTS_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_label = "".join(c if c.isalnum() or c in "_-" else "_" for c in label)
        path = SCREENSHOTS_DIR / f"{ts}_{safe_label}.png"
        page.screenshot(path=str(path), full_page=True)
        log(f"Screenshot saved: {path}")
        return str(path)
    except Exception as exc:
        log(f"Could not save screenshot: {exc}")
        return ""


def notify(title: str, body: str):
    """Non-blocking Windows popup that auto-closes after 6 seconds."""
    try:
        ps = (
            '$s = New-Object -ComObject Wscript.Shell; '
            f'$s.Popup("{body}", 6, "{title}", 64) | Out-Null'
        )
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass  # Notification is optional — don't crash if it fails


# ---------------------------------------------------------------------------
# Main automation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Deadline check
# ---------------------------------------------------------------------------

DEADLINE_MINUTES = 75  # skip if more than this many minutes past trigger time


def check_deadline(scheduled_time: str) -> bool:
    """Return True if still within the allowed window, False if too late."""
    if not scheduled_time:
        return True  # no time given, always proceed
    try:
        now = datetime.now()
        sched = datetime.strptime(scheduled_time, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day
        )
        elapsed = (now - sched).total_seconds() / 60
        if elapsed > DEADLINE_MINUTES:
            log(f"SKIPPED: {elapsed:.0f} min past scheduled time {scheduled_time} "
                f"(deadline is {DEADLINE_MINUTES} min). Class is likely over.")
            return False
        if elapsed < -60:
            # Running way too early (clock issue?) — proceed anyway
            return True
        log(f"Running {elapsed:.0f} min after scheduled time {scheduled_time}.")
        return True
    except ValueError:
        return True  # bad format, proceed anyway


def start_class(url: str, scheduled_time: str = ""):
    if not check_deadline(scheduled_time):
        sys.exit(0)

    if not AUTH_FILE.exists():
        log("ERROR: auth.json not found. Run lms_login_setup.py first.")
        notify("LMS Error", "auth.json not found. Run lms_login_setup.py to save your session.")
        sys.exit(1)

    log(f"Starting automation for: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=200)
        context = browser.new_context(storage_state=str(AUTH_FILE))
        page    = context.new_page()

        # Navigate to subject page
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except PlaywrightTimeout:
            log("ERROR: Page load timed out. Check your internet connection.")
            screenshot_error(page, "page_load_timeout")
            notify("LMS Error", "Page timed out. Check internet connection.")
            browser.close()
            sys.exit(1)

        # Detect session expiry (redirect to login)
        current = page.url
        if (
            "login" in current.lower()
            or "microsoftonline" in current.lower()
            or "oauth" in current.lower()
        ):
            log("ERROR: Session expired. Re-run lms_login_setup.py to renew the session.")
            screenshot_error(page, "session_expired")
            notify("LMS Session Expired", "Please run lms_login_setup.py to re-login.")
            browser.close()
            sys.exit(1)

        log(f"Page loaded: {current}")

        # Wait for page to fully render
        page.wait_for_timeout(2_000)

        # --- Try to find and click "Start Class" ---
        # Ordered from most specific to least specific
        BUTTON_SELECTORS = [
            "button:has-text('Start Class')",
            "a:has-text('Start Class')",
            "input[value*='Start Class']",
            "button:has-text('Start')",
            "[class*='start-class']",
            "[id*='start-class']",
            "[class*='startClass']",
        ]

        clicked = False
        for sel in BUTTON_SELECTORS:
            try:
                btn = page.locator(sel).first
                btn.wait_for(state="visible", timeout=3_000)
                btn.scroll_into_view_if_needed()
                btn.click()
                log(f"Clicked 'Start Class' using selector: {sel}")
                clicked = True
                break
            except PlaywrightTimeout:
                continue
            except Exception as exc:
                log(f"Selector '{sel}' failed: {exc}")
                continue

        if not clicked:
            log("WARNING: 'Start Class' button not found. It may already be active, "
                "or the page layout changed. Browser window left open for manual check.")
            screenshot_error(page, "button_not_found")
            notify("LMS: Check Needed", "Could not find Start Class — browser is open for you.")
            # Leave browser open so teacher can check manually
            page.wait_for_timeout(30_000)
            browser.close()
            return

        # --- Handle possible confirmation modal ---
        page.wait_for_timeout(1_500)
        CONFIRM_SELECTORS = [
            "button:has-text('Confirm')",
            "button:has-text('Yes')",
            "button:has-text('OK')",
            "button:has-text('Proceed')",
        ]
        for sel in CONFIRM_SELECTORS:
            try:
                btn = page.locator(sel).first
                if btn.is_visible():
                    btn.click()
                    log(f"Confirmed dialog via: {sel}")
                    break
            except PlaywrightTimeout:
                continue

        # Success
        time_str = datetime.now().strftime("%I:%M %p")
        log(f"SUCCESS: Class started at {time_str}.")
        notify("LMS: Class Started \u2713", f"Start Class clicked at {time_str}.")

        # Keep browser open briefly so you can see the result
        page.wait_for_timeout(6_000)
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-click Start Class on ClassEdge LMS")
    parser.add_argument("--url", required=True, help="ClassEdge subjectDetail URL")
    parser.add_argument("--scheduled-time", default="", help="Scheduled trigger time HH:MM (24h) for deadline check")
    args = parser.parse_args()

    try:
        start_class(args.url, args.scheduled_time)
    except Exception as exc:
        log(f"UNHANDLED ERROR: {exc}")
        # Try to capture a screenshot using a fresh page if possible
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    storage_state=str(AUTH_FILE) if AUTH_FILE.exists() else None
                )
                page = context.new_page()
                page.goto(args.url, wait_until="domcontentloaded", timeout=15_000)
                screenshot_error(page, "unhandled_error")
                browser.close()
        except Exception:
            pass  # Best-effort only
        notify("LMS Error", f"Unexpected error — check start_class.log for details.")
        sys.exit(1)
