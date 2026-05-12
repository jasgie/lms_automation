"""
upload_lessons.py
-----------------
Reads lesson files from lessons/<Subject (LEC|LAB)>/ folders
and uploads each file to ClassEdge using the create_lesson form.

Files already uploaded are tracked in _uploaded.json per folder
and will NOT be re-uploaded on future runs.

FORM FIELDS USED (from ClassEdge create_lesson page):
  file_name  — lesson title
  term       — Midterm or Final Term
  file       — the actual file attachment
  description — optional (leave blank by default)

USAGE
  python upload_lessons.py                          # upload all pending files
  python upload_lessons.py --dry-run                # preview without uploading
  python upload_lessons.py --folder "Web Design"    # one subject only (partial match)
  python upload_lessons.py --term final             # specify term
  python upload_lessons.py --inspect                # show form fields and save screenshot
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

AUTH_FILE    = Path(__file__).parent / "auth.json"
LESSONS_ROOT = Path(__file__).parent / "lessons"
LOG_FILE     = Path(__file__).parent / "upload_lessons.log"
ERRORS_DIR   = Path(__file__).parent / "errors"
DEBUG_DIR    = Path(__file__).parent / "debug"

SUPPORTED_EXTENSIONS = {
    ".pdf", ".pptx", ".ppt", ".docx", ".doc",
    ".xlsx", ".xls", ".mp4", ".zip", ".png", ".jpg", ".jpeg",
}

TERM_KEYWORDS = {
    "midterm": "midterm",
    "mid":     "midterm",
    "final":   "final",
    "finals":  "final",
    "auto":    "auto",
}

BASE_URL = "https://classedge.hccci.edu.ph/create_lesson/{id}/"


# ---------------------------------------------------------------------------
# Logging & error screenshots
# ---------------------------------------------------------------------------

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def screenshot_error(page, label: str) -> str:
    try:
        ERRORS_DIR.mkdir(exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", label)
        path = ERRORS_DIR / f"{ts}_{safe}.png"
        page.screenshot(path=str(path), full_page=True)
        log(f"  Screenshot saved: errors/{path.name}")
        return str(path)
    except Exception as e:
        log(f"  Could not save screenshot: {e}")
        return ""


# ---------------------------------------------------------------------------
# File & folder helpers
# ---------------------------------------------------------------------------

def parse_filename(filename: str) -> tuple[str, int | None]:
    """
    Extract lesson title and optional week number from filename.

    "01 - Introduction to HTML.pdf"    → ("Introduction to HTML", 1)
    "Week 3 - Topic Name.pptx"         → ("Topic Name", 3)
    "My Lesson.pdf"                    → ("My Lesson", None)
    """
    stem = Path(filename).stem
    m = re.match(r"^(\d+)\s*[-–]\s*(.+)$", stem)
    if m:
        return m.group(2).strip(), int(m.group(1))
    m = re.match(r"^[Ww]eek\s*(\d+)\s*[-–]\s*(.+)$", stem)
    if m:
        return m.group(2).strip(), int(m.group(1))
    return stem.strip(), None


def get_subject_ids(folder: Path) -> list[str]:
    ids_file = folder / "_subject_ids.json"
    if ids_file.exists():
        data = json.loads(ids_file.read_text(encoding="utf-8"))
        return [str(i) for i in data.get("subject_ids", [])]
    return []


def load_uploaded(folder: Path) -> set:
    tracker = folder / "_uploaded.json"
    if tracker.exists():
        data = json.loads(tracker.read_text(encoding="utf-8"))
        return set(data.get("uploaded", []))
    return set()


def save_uploaded(folder: Path, uploaded: set):
    (folder / "_uploaded.json").write_text(
        json.dumps({"uploaded": sorted(uploaded)}, indent=2), encoding="utf-8"
    )


def get_pending_files(folder: Path, uploaded: set) -> list[Path]:
    files = []
    for f in sorted(folder.iterdir()):
        if f.name.startswith("_") or f.name.startswith("."):
            continue
        if f.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if f.name in uploaded:
            continue
        files.append(f)
    return files


# ---------------------------------------------------------------------------
# Term selection
# ---------------------------------------------------------------------------

def select_term(page, term_pref: str) -> tuple[str, str]:
    """
    Select Midterm or Final Term in the term dropdown.
    Returns (start_date, end_date) as MM/DD/YYYY strings parsed from the
    option label (e.g. "Midterm - 2026-01-05 - 2026-05-22").
    Both return as empty strings if dates cannot be parsed.
    """
    start_date = end_date = ""
    try:
        opts = page.evaluate("""
        () => {
            const sel = document.querySelector('select[name="term"]');
            return sel ? Array.from(sel.options).map(o => ({value: o.value, text: o.text.trim()})) : [];
        }
        """)
        chosen = None
        for opt in opts:
            if term_pref == "auto":
                chosen = opt   # pick the first option that exists
                break
            if term_pref in opt["text"].lower():
                chosen = opt
                break

        if chosen:
            if term_pref != "auto":
                page.select_option('select[name="term"]', chosen["value"])
            log(f"  Term: {chosen['text']}")

            # Parse dates from label: "Midterm - 2026-01-05 - 2026-05-22"
            dates = re.findall(r"(\d{4}-\d{2}-\d{2})", chosen["text"])
            if len(dates) >= 2:
                # datetime-local inputs expect YYYY-MM-DDTHH:MM
                start_date = dates[0] + "T00:00"
                end_date   = dates[1] + "T23:59"
        else:
            if term_pref != "auto":
                log(f"  WARNING: Term '{term_pref}' not found — using default.")
    except Exception as e:
        log(f"  Could not set term: {e}")
    return start_date, end_date


def fill_dates(page, start_date: str, end_date: str):
    """
    Fill Start Date and End Date datetime-local inputs.
    Expects values in YYYY-MM-DDTHH:MM format.
    Uses JavaScript to set the value reliably (avoids browser date-picker quirks).
    """
    if not start_date:
        return
    for field_names, value in [
        (["start_date", "id_start_date"], start_date),
        (["end_date",   "id_end_date"],   end_date),
    ]:
        for name in field_names:
            try:
                # Use JS to set value + fire change event (most reliable for datetime-local)
                set_ok = page.evaluate(f"""
                    () => {{
                        const el = document.querySelector(
                            'input[name="{name}"], input#id_{name}, input#{name}'
                        );
                        if (!el) return false;
                        el.value = '{value}';
                        el.dispatchEvent(new Event('input',  {{bubbles:true}}));
                        el.dispatchEvent(new Event('change', {{bubbles:true}}));
                        return true;
                    }}
                """)
                if set_ok:
                    break
            except Exception:
                continue


# ---------------------------------------------------------------------------
# Upload one lesson to one subject
# ---------------------------------------------------------------------------

def upload_one(page, subject_id: str, lesson_file: Path, title: str,
               term_pref: str, dry_run: bool) -> bool:
    """
    Navigate to create_lesson/{subject_id}/, fill the form, submit.
    Returns True on success.
    """
    create_url = BASE_URL.format(id=subject_id)

    # Load the form
    try:
        page.goto(create_url, wait_until="domcontentloaded", timeout=30_000)
    except PlaywrightTimeout:
        log(f"  ERROR: Timed out loading create_lesson for ID {subject_id}")
        screenshot_error(page, f"timeout_id{subject_id}")
        return False

    # Session expiry check
    cur = page.url
    if "login" in cur.lower() or "microsoftonline" in cur.lower():
        log("  ERROR: Session expired. Re-run lms_login_setup.py to renew.")
        screenshot_error(page, "session_expired")
        return False

    if dry_run:
        # Check form is reachable but don't submit
        log(f"  [DRY RUN] Would upload '{title}' → ID {subject_id}")
        return True

    # --- Fill lesson title ---
    try:
        page.fill("input[name='file_name']", title)
    except Exception as e:
        log(f"  WARNING: Could not fill title: {e}")
        screenshot_error(page, f"no_title_id{subject_id}")

    # --- Fill description (required field — defaults to lesson title) ---
    desc_file = lesson_file.parent / "_description.txt"
    description = desc_file.read_text(encoding="utf-8").strip() if desc_file.exists() else title
    try:
        # Try named selectors first, then fall back to first textarea on page
        filled = False
        for sel in ["textarea[name='description']", "textarea#id_description", "textarea"]:
            loc = page.locator(sel).first
            if loc.count():
                loc.fill(description)
                filled = True
                break
        if not filled:
            log("  WARNING: Could not find description field")
    except Exception as e:
        log(f"  WARNING: Could not fill description: {e}")

    # --- Select term + parse dates from term label ---
    start_date, end_date = select_term(page, term_pref)

    # --- Fill Start / End dates ---
    fill_dates(page, start_date, end_date)

    # --- Attach file ---
    try:
        page.set_input_files("input[name='file']", str(lesson_file))
        log(f"  File attached: {lesson_file.name}")
    except Exception as e:
        log(f"  ERROR: Could not attach file: {e}")
        screenshot_error(page, f"attach_failed_id{subject_id}")
        return False

    # --- Submit ---
    SUBMIT_SELECTORS = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Save')",
        "button:has-text('Create')",
        "button:has-text('Upload')",
        "button:has-text('Submit')",
        "button:has-text('Add Lesson')",
    ]
    submitted = False
    for sel in SUBMIT_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.is_visible():
                btn.click()
                submitted = True
                break
        except Exception:
            continue

    if not submitted:
        log(f"  ERROR: Could not find submit button on create_lesson/{subject_id}/")
        screenshot_error(page, f"no_submit_id{subject_id}")
        return False

    # --- Check result ---
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15_000)
    except PlaywrightTimeout:
        pass

    cur = page.url
    # Success: redirected away from create_lesson page
    if "create_lesson" not in cur:
        log(f"  SUCCESS: '{title}' uploaded to ID {subject_id}")
        return True

    # Check for success messages on the same page
    for sel in [".alert-success", "[class*='success']"]:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                log(f"  SUCCESS: '{title}' uploaded to ID {subject_id}")
                return True
        except Exception:
            continue

    # Check for error messages
    for sel in [".alert-danger", ".errorlist", "[class*='error']"]:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                err = el.inner_text()[:300].strip()
                log(f"  ERROR: Form error for ID {subject_id}: {err}")
                screenshot_error(page, f"form_error_id{subject_id}")
                return False
        except Exception:
            continue

    # Ambiguous result
    screenshot_error(page, f"unknown_result_id{subject_id}")
    log(f"  WARNING: Unclear result after uploading '{title}' to ID {subject_id}. Check errors/.")
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Bulk upload lessons to ClassEdge LMS")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Preview what would be uploaded without submitting")
    parser.add_argument("--inspect",  action="store_true",
                        help="Print create_lesson form fields and save a screenshot, then exit")
    parser.add_argument("--folder",   default="",
                        help="Only process this subject folder (partial name match)")
    parser.add_argument("--term",     default="auto",
                        help="Term: midterm / final / auto (default: auto = currently selected)")
    args = parser.parse_args()

    term_pref = TERM_KEYWORDS.get(args.term.lower(), args.term.lower())

    if not AUTH_FILE.exists():
        print("ERROR: auth.json not found. Run lms_login_setup.py first.")
        sys.exit(1)

    if not LESSONS_ROOT.exists():
        print("ERROR: No lessons/ folder found.")
        print("Run create_lesson_folders.py (or UPLOAD_LESSONS.bat) first to create it.")
        sys.exit(1)

    # Gather subject folders
    subject_folders = [
        f for f in sorted(LESSONS_ROOT.iterdir())
        if f.is_dir() and not f.name.startswith("_")
    ]
    if args.folder:
        subject_folders = [
            f for f in subject_folders
            if args.folder.lower() in f.name.lower()
        ]

    if not subject_folders:
        print("No matching subject folders found.")
        sys.exit(0)

    total_ok   = 0
    total_fail = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=300)
        context = browser.new_context(storage_state=str(AUTH_FILE))
        page    = context.new_page()

        # --inspect: dump form fields and exit
        if args.inspect:
            ids = get_subject_ids(subject_folders[0])
            if not ids:
                print(f"No subject IDs in: {subject_folders[0].name}")
                browser.close()
                return
            url = BASE_URL.format(id=ids[0])
            print(f"\nInspecting: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            fields = page.evaluate("""
            () => Array.from(document.querySelectorAll('input,select,textarea')).map(e => ({
                tag: e.tagName.toLowerCase(), type: e.type || '',
                name: e.name || '', id: e.id || '', placeholder: e.placeholder || ''
            }))
            """)
            print("Form fields:")
            for field in fields:
                print(f"  [{field['tag']}] name='{field['name']}' "
                      f"type='{field['type']}' id='{field['id']}'")
            DEBUG_DIR.mkdir(exist_ok=True)
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            png = DEBUG_DIR / f"inspect_lesson_form_{ts}.png"
            page.screenshot(path=str(png), full_page=True)
            print(f"\nScreenshot saved: debug/{png.name}")
            browser.close()
            return

        # Main upload loop
        log("=" * 60)
        log("ClassEdge LMS — Bulk Lesson Upload")
        if args.dry_run:
            log("[DRY RUN mode — no files will actually be submitted]")
        log(f"Term preference : {term_pref}")
        log("=" * 60)

        for folder in subject_folders:
            ids = get_subject_ids(folder)
            if not ids:
                log(f"\nSkipping '{folder.name}': no _subject_ids.json found.")
                continue

            uploaded_set = load_uploaded(folder)
            pending      = get_pending_files(folder, uploaded_set)

            if not pending:
                log(f"\n{folder.name}: no new files.")
                continue

            log(f"\nSubject folder : {folder.name}")
            log(f"  Section IDs  : {ids}")
            log(f"  Files pending: {len(pending)}")

            for lesson_file in pending:
                title, week = parse_filename(lesson_file.name)
                week_str    = f"Week {week}" if week else "(no week)"

                log(f"\n  File  : {lesson_file.name}")
                log(f"  Title : {title}  |  {week_str}")

                all_ok = True
                for subject_id in ids:
                    ok = upload_one(
                        page, subject_id, lesson_file,
                        title, term_pref, args.dry_run
                    )
                    if not ok:
                        all_ok = False
                        total_fail += 1
                    page.wait_for_timeout(700)

                if all_ok:
                    uploaded_set.add(lesson_file.name)
                    if not args.dry_run:
                        save_uploaded(folder, uploaded_set)
                    total_ok += 1

        browser.close()

    log("")
    log("=" * 60)
    log(f"Done.  Uploaded: {total_ok}   Failed: {total_fail}")
    if total_fail > 0:
        log("Check the errors/ folder and upload_lessons.log for details.")
    log("=" * 60)


if __name__ == "__main__":
    main()
