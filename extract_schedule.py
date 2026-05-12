"""
extract_schedule.py
-------------------
Reads your schedule .docx from ClassEdge and automatically generates
schedule.json — so you don't have to manually copy URLs.

Usage:
  python extract_schedule.py "C:\\path\\to\\your\\2ND SEM SCHED.docx"

Or just run it and it will ask for the file path:
  python extract_schedule.py
"""

import json
import re
import sys
import zipfile
from pathlib import Path

OUTPUT = Path(__file__).parent / "schedule.json"

DAY_ABBREV = {
    "mon": "MON", "monday":    "MON",
    "tue": "TUE", "tuesday":   "TUE",
    "wed": "WED", "wednesday": "WED",
    "thu": "THU", "thursday":  "THU",
    "fri": "FRI", "friday":    "FRI",
    "sat": "SAT", "saturday":  "SAT",
    "sun": "SUN", "sunday":    "SUN",
}

# How many minutes before class start to trigger the task
LEAD_MINUTES = 15


def subtract_minutes(hhmm: str, minutes: int) -> str:
    h, m = map(int, hhmm.split(":"))
    total = h * 60 + m - minutes
    if total < 0:
        total += 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}"


def parse_time(raw: str) -> str:
    """Convert '7:30 AM', '1:30 PM', '12:30 PM' → '07:30', '13:30', '12:30'"""
    raw = raw.strip()
    m = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)", raw, re.IGNORECASE)
    if not m:
        return None
    h, mins, period = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if period == "AM":
        h = 0 if h == 12 else h
    else:
        h = 12 if h == 12 else h + 12
    return f"{h:02d}:{mins:02d}"


def make_name(day: str, trigger: str, subject_short: str, kind: str) -> str:
    t = trigger.replace(":", "")
    return f"{day.capitalize()[:3]}_{t}_{subject_short}_{kind}"


def extract(docx_path: str) -> list:
    path = Path(docx_path)
    if not path.exists():
        print(f"ERROR: File not found: {docx_path}")
        sys.exit(1)

    with zipfile.ZipFile(path, "r") as z:
        doc_xml = z.read("word/document.xml").decode("utf-8")

    # Extract all HYPERLINK field entries with their following text block
    blocks = re.split(r'HYPERLINK "([^"]+)"', doc_xml)
    entries = []

    for i, block in enumerate(blocks):
        if not block.startswith("https://"):
            continue

        url     = block
        content = blocks[i + 1] if i + 1 < len(blocks) else ""

        # Subject title (bold text, first occurrence)
        title_match = re.search(
            r'<w:b/>.*?<w:t[^>]*>([^<]{3,})</w:t>', content
        )
        subject = title_match.group(1).strip() if title_match else "Subject"
        subject = re.sub(r'\s+', ' ', subject)

        # Lec / Lab
        kind_match = re.search(r'<w:t[^>]*>(Lec|Lab)</w:t>', content)
        kind = kind_match.group(1) if kind_match else "Class"

        # Schedule line: "Sat - 9:30 AM to 12:30 PM"
        sched_match = re.search(
            r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*-\s*(\d{1,2}:\d{2}\s*(?:AM|PM))',
            content, re.IGNORECASE
        )
        if not sched_match:
            print(f"  WARNING: No schedule found for {subject} ({url}) — skipped.")
            continue

        day_raw  = sched_match.group(1).lower()
        time_raw = sched_match.group(2)
        day      = DAY_ABBREV.get(day_raw, day_raw.upper()[:3])
        start_24 = parse_time(time_raw)
        if not start_24:
            print(f"  WARNING: Could not parse time '{time_raw}' for {subject} — skipped.")
            continue

        trigger = subtract_minutes(start_24, LEAD_MINUTES)

        # Build a short subject name (first word, max 10 chars)
        subj_short = re.sub(r'[^A-Za-z0-9]', '', subject.split()[0])[:10]
        name = make_name(day, trigger, subj_short, kind)

        entries.append({
            "name":         name,
            "day":          day,
            "trigger_time": trigger,
            "url":          url,
        })
        print(f"  Found: {day} {start_24}  {subject} ({kind})  → trigger {trigger}")

    return entries


def main():
    if len(sys.argv) > 1:
        docx_path = sys.argv[1]
    else:
        print("=" * 60)
        print("  ClassEdge Schedule Extractor")
        print("=" * 60)
        print("\nPaste the full path to your schedule .docx file.")
        print('Example: C:\\Users\\YourName\\OneDrive\\2ND SEM SCHED.docx\n')
        docx_path = input("Path: ").strip().strip('"')

    print(f"\nReading: {docx_path}\n")
    entries = extract(docx_path)

    if not entries:
        print("\nNo schedule entries found. Make sure the docx has LMS hyperlinks.")
        sys.exit(1)

    OUTPUT.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    print(f"\nSaved {len(entries)} entries to: {OUTPUT.name}")
    print("You can now run: python setup_tasks.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
