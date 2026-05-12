"""
extract_schedule_web.py
-----------------------
Scrapes your ClassEdge SubjectList page and generates schedule.json
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
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# Ensure UTF-8 output on Windows (avoids CP1252 UnicodeEncodeError with → ✓ etc.)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

AUTH_FILE     = Path(__file__).parent / "auth.json"
OUTPUT        = Path(__file__).parent / "schedule.json"
DEBUG_DIR     = Path(__file__).parent / "debug"
SUBJECT_LIST  = "https://classedge.hccci.edu.ph/SubjectList/"
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


def save_debug(page):
    DEBUG_DIR.mkdir(exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    shot = DEBUG_DIR / f"subjectlist_{ts}.png"
    html = DEBUG_DIR / f"subjectlist_{ts}.html"
    page.screenshot(path=str(shot), full_page=True)
    html.write_text(page.content(), encoding="utf-8")
    print(f"  [debug] screenshot → {shot.name}")
    print(f"  [debug] html       → {html.name}")


# ---------------------------------------------------------------------------
# Scraper — uses exact ClassEdge CSS selectors found from page inspection
# ---------------------------------------------------------------------------

def scrape_cards(page) -> list:
    """
    Extracts all subject cards from the SubjectList page using a single
    page.evaluate() call. Uses global h6.sc-title list (full untruncated names)
    matched by index to card elements.
    """
    raw = page.evaluate("""
    () => {
        const allTitles = Array.from(document.querySelectorAll('h6.sc-title'))
            .map(h => h.textContent.trim());
        const cards = document.querySelectorAll('a.sc-body-link[href*="/subjectDetail/"]');

        return Array.from(cards).map((card, i) => {
            const subject = allTitles[i] || '';

            const wrapper = card.closest('.card, [class*=\"sc-card\"], .subject-card') || card.parentElement;
            const typeBadge = wrapper ? wrapper.querySelector('.sc-type-badge') : null;
            const kind = typeBadge ? typeBadge.textContent.trim() : 'Class';

            const dayBadges = Array.from(
                card.querySelectorAll('.sc-day-badge.sc-day-active, .sc-day-badge.bg-primary')
            ).map(b => b.textContent.trim().toUpperCase()).filter(Boolean);

            let startTime = '';
            for (const row of Array.from(card.querySelectorAll('.sc-meta-row'))) {
                const m = row.textContent.trim().match(/(\\d{1,2}:\\d{2}\\s*(?:AM|PM))/i);
                if (m) { startTime = m[1]; break; }
            }

            return { href: card.href, subject, kind, days: dayBadges, startTime };
        });
    }
    """)

    print(f"  Found {len(raw)} subject cards.")
    entries = []

    for card in raw:
        href    = card["href"]
        subject = card["subject"] or "Subject"
        kind    = card["kind"]
        days    = card["days"]
        start_raw = card["startTime"]

        if not days:
            print(f"  WARNING: No day found for {subject} ({href}) — skipped.")
            continue

        start_24 = parse_time(start_raw) if start_raw else None
        if not start_24:
            print(f"  WARNING: No time found for {subject} ({href}) — skipped.")
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
# Main
# ---------------------------------------------------------------------------

def main():
    if not AUTH_FILE.exists():
        print("ERROR: auth.json not found. Run lms_login_setup.py first.")
        sys.exit(1)

    print("=" * 60)
    print("  ClassEdge — Automatic Schedule Extractor")
    print("=" * 60)
    print(f"  Opening: {SUBJECT_LIST}\n")

    entries = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)
        context = browser.new_context(
            storage_state=str(AUTH_FILE),
            viewport={"width": 1920, "height": 1080},  # wide viewport prevents JS text truncation
        )
        page    = context.new_page()

        # Navigate to SubjectList
        try:
            page.goto(SUBJECT_LIST, wait_until="networkidle", timeout=30_000)
        except PlaywrightTimeout:
            page.goto(SUBJECT_LIST, wait_until="domcontentloaded", timeout=30_000)

        # Check for session expiry
        current = page.url
        if "login" in current.lower() or "microsoftonline" in current.lower():
            print("ERROR: Session expired. Run lms_login_setup.py to re-login.")
            browser.close()
            sys.exit(1)

        print(f"  Loaded: {current}")
        page.wait_for_timeout(2_000)

        # Save debug snapshot
        save_debug(page)

        # Try scraping with correct selectors
        entries = scrape_cards(page)

        browser.close()

    # Deduplicate by URL
    seen  = set()
    clean = []
    for e in entries:
        if e["url"] not in seen:
            seen.add(e["url"])
            clean.append(e)

    if not clean:
        print("\nWARNING: No schedule entries found.")
        print("Check the debug/ folder for a screenshot and HTML snapshot.")
        print("The page layout may differ — share the snapshot and we'll update the scraper.")
        sys.exit(1)

    # Print summary
    print(f"\n  Found {len(clean)} classes:\n")
    for e in clean:
        print(f"    {e['day']:3s}  {e['trigger_time']}  {e['name']}")

    # Save
    OUTPUT.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    print(f"\n  Saved to: {OUTPUT.name}")
    print("  Run: python setup_tasks.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
