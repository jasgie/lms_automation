"""
lms_start_class.py
------------------
Loads saved auth session and clicks "Start Class" on ClassEdge.
Called automatically by Windows Task Scheduler — do not run manually.

Usage:
  python lms_start_class.py --url "https://classedge.hccci.edu.ph/subjectDetail/331/?semester="
"""

import argparse
import re
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
            # --- Check if class is already running (End Class button visible) ---
            END_CLASS_SELECTORS = [
                "button:has-text('End Class')",
                "a:has-text('End Class')",
                "input[value*='End Class']",
                "[class*='end-class']",
                "[id*='end-class']",
                "[class*='endClass']",
            ]
            end_btn_found = False
            for sel in END_CLASS_SELECTORS:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=2_000):
                        end_btn_found = True
                        break
                except Exception:
                    continue

            if end_btn_found:
                # Try to read the running timer from the page.
                # ClassEdge typically shows something like "01:23:45" or "45 min"
                # Try common timer/duration element patterns.
                TIMER_SELECTORS = [
                    "[class*='timer']",
                    "[class*='duration']",
                    "[class*='elapsed']",
                    "[class*='running']",
                    "[class*='class-time']",
                    "[class*='classTime']",
                    "[id*='timer']",
                    "[id*='duration']",
                    "[id*='elapsed']",
                ]
                # Also scan all visible text for HH:MM:SS / H:MM:SS / MM:SS patterns
                elapsed_seconds = None
                timer_raw = ""

                for sel in TIMER_SELECTORS:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible(timeout=500):
                            timer_raw = el.inner_text().strip()
                            if timer_raw:
                                break
                    except Exception:
                        continue

                # If no dedicated element found, search page body text
                if not timer_raw:
                    try:
                        body_text = page.locator("body").inner_text()
                        # Look for HH:MM:SS or H:MM:SS or MM:SS
                        m = re.search(r'\b(\d{1,2}):(\d{2}):(\d{2})\b', body_text)
                        if m:
                            timer_raw = m.group(0)
                        else:
                            # Look for "X hour(s) Y min(s)" patterns
                            m2 = re.search(
                                r'(\d+)\s*h(?:our)?s?\s*(\d+)\s*m(?:in)?',
                                body_text, re.IGNORECASE
                            )
                            if m2:
                                timer_raw = f"{m2.group(1)}h {m2.group(2)}m"
                            else:
                                m3 = re.search(r'(\d+)\s*m(?:in(?:ute)?s?)?', body_text, re.IGNORECASE)
                                if m3:
                                    timer_raw = f"{m3.group(1)} min"
                    except Exception:
                        pass

                # Parse timer_raw → elapsed_seconds
                if timer_raw:
                    # HH:MM:SS or H:MM:SS
                    m = re.match(r'^(\d{1,2}):(\d{2}):(\d{2})$', timer_raw)
                    if m:
                        elapsed_seconds = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                    else:
                        # MM:SS
                        m = re.match(r'^(\d{1,2}):(\d{2})$', timer_raw)
                        if m:
                            elapsed_seconds = int(m.group(1)) * 60 + int(m.group(2))
                        else:
                            # "Xh Ym"
                            m = re.match(r'(\d+)h\s*(\d+)m', timer_raw)
                            if m:
                                elapsed_seconds = int(m.group(1)) * 3600 + int(m.group(2)) * 60
                            else:
                                # "X min"
                                m = re.match(r'(\d+)\s*min', timer_raw, re.IGNORECASE)
                                if m:
                                    elapsed_seconds = int(m.group(1)) * 60

                now = datetime.now()
                if elapsed_seconds is not None:
                    started_at = now - timedelta(seconds=elapsed_seconds)
                    started_str = started_at.strftime("%I:%M %p")
                    elapsed_str = str(timedelta(seconds=elapsed_seconds))  # H:MM:SS
                    msg = (f"Class already started at {started_str} "
                           f"(running {elapsed_str}, timer: {timer_raw}).")
                    log(f"INFO: {msg}")
                    notify("LMS: Class Already Running", msg)
                else:
                    now_str = now.strftime("%I:%M %p")
                    msg = f"Class is already running as of {now_str} (no timer found on page)."
                    log(f"INFO: {msg}")
                    notify("LMS: Class Already Running", msg)

                screenshot_error(page, "class_already_started")
                page.wait_for_timeout(4_000)
                browser.close()
                return

            # End Class button not found either — truly unknown state
            log("WARNING: 'Start Class' button not found. It may already be active, "
                "or the page layout changed. Browser window left open for manual check.")
            screenshot_error(page, "button_not_found")
            notify("LMS: Check Needed", "Could not find Start Class — browser is open for you.")
            # Leave browser open so teacher can check manually
            page.wait_for_timeout(30_000)
            browser.close()
            return

        # --- Handle possible confirmation modal or error dialog ---
        page.wait_for_timeout(1_500)

        # ERROR_SELECTORS: modals that indicate the action failed.
        # Check BEFORE trying to confirm so we don't mistake an error OK for a confirm.
        ERROR_INDICATORS = [
            # Text patterns that signal an error dialog is visible
            "text=Oops",
            "text=Something went wrong",
            "text=Error",
            "text=Failed",
            "text=not valid JSON",
            "text=Unexpected token",
            "text=Internal Server Error",
            "text=500",
        ]
        error_detected = False
        error_text = ""
        for sel in ERROR_INDICATORS:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=500):
                    # Try to grab the full modal text for logging
                    try:
                        # Walk up to a container to get more context
                        container = page.locator(".swal2-popup, .modal-content, [role='dialog'], [role='alertdialog']").first
                        if container.is_visible(timeout=300):
                            error_text = container.inner_text().strip()
                        else:
                            error_text = el.inner_text().strip()
                    except Exception:
                        error_text = sel
                    error_detected = True
                    break
            except Exception:
                continue

        if error_detected:
            log(f"ERROR: Server returned an error after clicking Start Class. Modal text: {repr(error_text)}")
            screenshot_error(page, "start_class_server_error")
            # Dismiss the error dialog if possible
            for dismiss_sel in ["button:has-text('OK')", "button:has-text('Close')", ".swal2-confirm"]:
                try:
                    btn = page.locator(dismiss_sel).first
                    if btn.is_visible(timeout=500):
                        btn.click()
                        break
                except Exception:
                    continue
            notify("LMS Error: Start Class Failed",
                   f"The server returned an error. Check start_class.log for details.")
            page.wait_for_timeout(4_000)
            browser.close()
            sys.exit(1)

        # No error — handle a legitimate confirmation dialog (if any)
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

        # Wait briefly then do a final error check in case the confirmation itself triggered an error
        page.wait_for_timeout(1_500)
        for sel in ERROR_INDICATORS:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=500):
                    try:
                        container = page.locator(".swal2-popup, .modal-content, [role='dialog'], [role='alertdialog']").first
                        error_text = container.inner_text().strip() if container.is_visible(timeout=300) else el.inner_text().strip()
                    except Exception:
                        error_text = sel
                    log(f"ERROR: Server returned an error after confirmation. Modal text: {repr(error_text)}")
                    screenshot_error(page, "start_class_post_confirm_error")
                    for dismiss_sel in ["button:has-text('OK')", "button:has-text('Close')", ".swal2-confirm"]:
                        try:
                            btn = page.locator(dismiss_sel).first
                            if btn.is_visible(timeout=500):
                                btn.click()
                                break
                        except Exception:
                            continue
                    notify("LMS Error: Start Class Failed",
                           f"The server returned an error. Check start_class.log for details.")
                    page.wait_for_timeout(4_000)
                    browser.close()
                    sys.exit(1)
            except Exception:
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
