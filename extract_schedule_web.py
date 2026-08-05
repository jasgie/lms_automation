"""
extract_schedule_web.py
-----------------------
Scrapes your ClassEdge course list page and generates schedule.json
automatically — no docx download required.

Usage:
  python extract_schedule_web.py

Requires auth.json to exist (run lms_login_setup.py first).
"""

import json
import io
import re
import sys
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# Ensure UTF-8 output on Windows (avoids CP1252 UnicodeEncodeError with → ✓ etc.)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

AUTH_FILE     = Path(__file__).parent / "auth.json"
OUTPUT        = Path(__file__).parent / "schedule.json"
DEBUG_DIR     = Path(__file__).parent / "debug"
COURSE_LIST   = "https://classedge.hccci.edu.ph/course/list/"  # LMS course list URL (paginated)
MAX_PAGES     = 50  # Safety limit for pagination
LEAD_MINUTES  = 15  # trigger this many minutes before class start

DAY_ABBREV = {
    "mon": "MON", "tue": "TUE", "wed": "WED",
    "thu": "THU", "fri": "FRI", "sat": "SAT", "sun": "SUN",
}
DAY_MAP = {
    "MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday",
    "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def subtract_minutes(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":"))
    total = h * 60 + m - minutes
    if total < 0:
        total += 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}"


def parse_time(raw: str) -> str | None:
    """'7:30 AM' / '1:30 PM' → '07:30' / '13:30'"""
    m = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)", raw.strip(), re.IGNORECASE)
    if not m:
        return None
    h, mins, period = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if period == "AM":
        h = 0 if h == 12 else h
    else:
        h = 12 if h == 12 else h + 12
    return f"{h:02d}:{mins:02d}"


def make_name(day: str, trigger: str, subj: str, kind: str) -> str:
    t    = trigger.replace(":", "")
    slug = re.sub(r"[^A-Za-z0-9]", "", subj.split()[0])[:10]
    return f"{day.capitalize()[:3]}_{t}_{slug}_{kind}"


def save_debug(page, suffix: str = ""):
    DEBUG_DIR.mkdir(exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = f"courselist_{ts}{suffix}"
    shot = DEBUG_DIR / f"{label}.png"
    html = DEBUG_DIR / f"{label}.html"
    page.screenshot(path=str(shot), full_page=True)
    html.write_text(page.content(), encoding="utf-8")
    print(f"  [debug] screenshot → {shot.name}")
    print(f"  [debug] html       → {html.name}")


# ---------------------------------------------------------------------------
# Scraper — selectors for ClassEdge course/list page (2026 redesign)
# ---------------------------------------------------------------------------

def scrape_cards(page) -> list:
    """
    Extracts all course cards from the /course/list/ page.
    
    New ClassEdge structure (2026):
    - Cards: a.course-card[href*="/material/list/"]
    - Name: .course-name (inside .course-body)
    - Type: .course-type-pill (contains "Lab" or "Lec")
    - Days: .course-schedule-days (e.g., "Thu", "Sat, Sun")
    - Time: .course-schedule-time (e.g., "· 10:30 AM–1:30 PM")

    Some cards list MULTIPLE schedule rows under the same kind pill (e.g. a LEC
    that meets Tue 1:00-3:00 PM AND Wed 10:30-12:30 PM at different times), so
    every .course-schedule-days / .course-schedule-time pair on the card must
    be read — not just the first one — otherwise later rows are silently lost.
    """
    raw = page.evaluate("""
    () => {
        const cards = document.querySelectorAll('a.course-card[href*="/material/list/"]');
        
        return Array.from(cards).map(card => {
            // Course name from .course-name element or title attribute
            const nameEl = card.querySelector('.course-name');
            const subject = nameEl ? (nameEl.getAttribute('title') || nameEl.textContent.trim()) : '';
            
            // Type badge (Lab/Lec) from .course-type-pill
            const typePill = card.querySelector('.course-type-pill');
            const kind = typePill ? typePill.textContent.trim() : 'Class';
            
            // A card can have several schedule rows (different day/time pairs).
            // Pair each .course-schedule-days element with the .course-schedule-time
            // element at the same index instead of grabbing only the first of each.
            const daysEls = card.querySelectorAll('.course-schedule-days');
            const timeEls = card.querySelectorAll('.course-schedule-time');
            const rowCount = Math.max(daysEls.length, timeEls.length);

            const schedules = [];
            for (let i = 0; i < rowCount; i++) {
                const daysEl = daysEls[i] || daysEls[daysEls.length - 1];
                const timeEl = timeEls[i] || timeEls[timeEls.length - 1];

                let days = [];
                if (daysEl) {
                    const daysText = daysEl.textContent.trim();
                    // Split by comma or space to handle "Sat, Sun" format
                    days = daysText.split(/[,\\s]+/).filter(d => d.length > 0);
                }

                let startTime = '';
                if (timeEl) {
                    const timeText = timeEl.textContent.trim();
                    const match = timeText.match(/(\\d{1,2}:\\d{2}\\s*(?:AM|PM))/i);
                    if (match) startTime = match[1];
                }

                if (days.length || startTime) {
                    schedules.push({ days, startTime });
                }
            }
            
            return { href: card.href, subject, kind, schedules };
        });
    }
    """)

    print(f"  Found {len(raw)} subject cards.")
    entries = []

    for card in raw:
        href      = card["href"]
        subject   = card["subject"] or "Subject"
        kind      = card["kind"]
        schedules = card["schedules"]

        if not schedules:
            print(f"  WARNING: No schedule found for {subject} ({href}) — skipped.")
            continue

        for sched in schedules:
            days      = sched["days"]
            start_raw = sched["startTime"]

            if not days:
                print(f"  WARNING: No day found for {subject} ({href}) — skipped row.")
                continue

            start_24 = parse_time(start_raw) if start_raw else None
            if not start_24:
                print(f"  WARNING: No time found for {subject} ({href}) — skipped row.")
                continue

            trigger = subtract_minutes(start_24, LEAD_MINUTES)

            for day in days:
                day = DAY_ABBREV.get(day[:3].lower(), day[:3].upper())
                name = make_name(day, trigger, subject, kind)
                entries.append({
                    "name":         name,
                    "subject":      subject,
                    "kind":         kind.upper(),
                    "day":          day,
                    "trigger_time": trigger,
                    "url":          href,
                })
                print(f"  {day:3s}  {start_24}  {subject} ({kind})  → trigger {trigger}")

    return entries


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------

def get_page_url(base_url: str, page_num: int) -> str:
    """Build paginated URL: /course/list/?page=N"""
    if page_num == 1:
        return base_url
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}page={page_num}"


def has_next_page(page) -> bool:
    """
    Check if there's a next page link in the pagination.
    
    ClassEdge pagination structure:
    <nav class="pagination-row">
      <span class="active">1</span>
      <a href="?page=2">2</a>
      <a href="?page=2"><i class="fas fa-chevron-right"></i></a>
    </nav>
    """
    return page.evaluate("""
    () => {
        // Find pagination container
        const paginationRow = document.querySelector('.pagination-row, .pagination');
        if (!paginationRow) return false;
        
        // Get current page number from .active element
        const activeEl = paginationRow.querySelector('.active');
        const currentNum = activeEl ? parseInt(activeEl.textContent.trim()) : 1;
        
        // Check if any link goes to a higher page number
        const pageLinks = paginationRow.querySelectorAll('a[href*="page="]');
        for (const link of pageLinks) {
            const match = link.href.match(/page=(\\d+)/);
            if (match) {
                const pageNum = parseInt(match[1]);
                if (pageNum > currentNum) return true;
            }
        }
        
        return false;
    }
    """)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not AUTH_FILE.exists():
        print("ERROR: auth.json not found. Run lms_login_setup.py first.")
        sys.exit(1)

    print("=" * 60)
    print("  ClassEdge — Automatic Schedule Extractor")
    print("=" * 60)
    print(f"  Opening: {COURSE_LIST}\n")

    all_entries = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)
        context = browser.new_context(
            storage_state=str(AUTH_FILE),
            viewport={"width": 1920, "height": 1080},  # wide viewport prevents JS text truncation
        )
        page    = context.new_page()

        # Navigate to first page of course list
        try:
            page.goto(COURSE_LIST, wait_until="networkidle", timeout=30_000)
        except PlaywrightTimeout:
            page.goto(COURSE_LIST, wait_until="domcontentloaded", timeout=30_000)

        # Check for session expiry
        current = page.url
        if "login" in current.lower() or "microsoftonline" in current.lower():
            print("ERROR: Session expired. Run lms_login_setup.py to re-login.")
            browser.close()
            sys.exit(1)

        print(f"  Loaded: {current}")
        page.wait_for_timeout(2_000)

        # Save debug snapshot for first page
        save_debug(page, "_page1")

        # Scrape with pagination
        page_num = 1
        while page_num <= MAX_PAGES:
            print(f"\n  Scraping page {page_num}...")
            
            entries = scrape_cards(page)
            if not entries:
                print(f"  No entries found on page {page_num}.")
                if page_num == 1:
                    # First page empty - save debug for troubleshooting
                    save_debug(page, "_empty")
                break
            
            all_entries.extend(entries)
            print(f"  Collected {len(entries)} entries from page {page_num} (total: {len(all_entries)})")

            # Check if there's a next page
            if not has_next_page(page):
                print(f"  No more pages after page {page_num}.")
                break

            # Navigate to next page
            page_num += 1
            next_url = get_page_url(COURSE_LIST, page_num)
            print(f"  Navigating to: {next_url}")
            
            try:
                page.goto(next_url, wait_until="networkidle", timeout=30_000)
            except PlaywrightTimeout:
                page.goto(next_url, wait_until="domcontentloaded", timeout=30_000)
            
            page.wait_for_timeout(1_500)

        browser.close()

    # Deduplicate by (url, day, trigger_time) — a subject can have multiple
    # schedule rows on the same course card (e.g. different day/time slots),
    # so deduping by url alone would drop all but the first row.
    seen  = set()
    clean = []
    for e in all_entries:
        key = (e["url"], e["day"], e["trigger_time"])
        if key not in seen:
            seen.add(key)
            clean.append(e)

    if not clean:
        print("\nWARNING: No schedule entries found.")
        print("Check the debug/ folder for a screenshot and HTML snapshot.")
        print("The page layout may differ — share the snapshot and we'll update the scraper.")
        sys.exit(1)

    # Print summary
    print(f"\n  Found {len(clean)} unique classes:\n")
    for e in clean:
        print(f"    {e['day']:3s}  {e['trigger_time']}  {e['name']}")

    # Save
    OUTPUT.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    print(f"\n  Saved to: {OUTPUT.name}")
    print("  Run: python setup_tasks.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
