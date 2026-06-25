"""
create_lesson_folders.py
------------------------
Creates a 'lessons/' folder with one subfolder per subject group.

One folder is created per unique (subject, type) pair — e.g.
"Computer Programming 2 (LAB)" — and it lists all section IDs
to upload to in a _subject_ids.json file inside the folder.

This means you drop lesson files in ONE place and they upload
to ALL sections automatically (e.g., all 5 CP2-Lab sections).

Run this ONCE before using upload_lessons.py.
"""

import json
import re
from pathlib import Path

SCHEDULE_FILE = Path(__file__).parent / "schedule.json"
LESSONS_ROOT  = Path(__file__).parent / "lessons"

NAMING_GUIDE = """\
HOW TO ADD LESSONS TO THIS FOLDER
==================================

DROP your lesson files (PDF, PPTX, DOCX, etc.) into this folder.

NAMING CONVENTION
-----------------
Use this format for the best results:

   01 - Lesson Title Here.pdf
   02 - Next Lesson.pptx
   Week 3 - Topic Name.pdf

The number at the start becomes the lesson order (Week/sequence).
The text after " - " becomes the lesson title on ClassEdge.

You can also just use plain filenames:
   Introduction to Programming.pdf     ← title = "Introduction to Programming"

EXAMPLES
--------
   01 - Introduction to HTML.pdf
   02 - CSS Basics.pptx
   03 - JavaScript Fundamentals.docx
   Week 4 - Responsive Design.pdf

SUPPORTED FILE TYPES
---------------------
.pdf  .pptx  .ppt  .docx  .doc  .xlsx  .xls  .mp4  .zip  .png  .jpg

NOTES
-----
- Files that start with "_" are ignored (config files, etc.)
- Files already uploaded will NOT be uploaded again.
- After dropping files here, run:  UPLOAD_LESSONS.bat
"""


def subject_folder_name(subject: str, kind: str) -> str:
    """Build a safe Windows folder name from subject + type."""
    safe = re.sub(r'[<>:"/\\|?*]', '', subject).strip()
    return f"{safe} ({kind.upper()})"


def extract_id(url: str) -> str | None:
    """Extract numeric subject/material ID from URL.
    
    Works with multiple URL patterns:
    - /material/list/32/
    - /subjectDetail/331/
    - /course/detail/123/
    """
    for part in url.split("/"):
        if part.isdigit():
            return part
    return None


def main():
    if not SCHEDULE_FILE.exists():
        print("ERROR: schedule.json not found.")
        print("Run extract_schedule_web.py first to generate it.")
        return

    with open(SCHEDULE_FILE, encoding="utf-8") as f:
        schedule = json.load(f)

    # Group entries by (subject, kind) → collect unique section IDs + day/time info
    groups: dict[str, dict] = {}

    for entry in schedule:
        subject = entry.get("subject") or entry.get("name", "Unknown Subject")
        kind    = entry.get("kind", "CLASS").upper()
        url     = entry.get("url", "")

        subject_id = extract_id(url)
        if not subject_id:
            continue

        folder_name = subject_folder_name(subject, kind)

        if folder_name not in groups:
            groups[folder_name] = {
                "folder_name": folder_name,
                "subject":     subject,
                "kind":        kind,
                "ids":         [],
                "sections":    [],
            }

        if subject_id not in groups[folder_name]["ids"]:
            groups[folder_name]["ids"].append(subject_id)

        section = f"{entry.get('day','')} {entry.get('trigger_time','')}".strip()
        if section and section not in groups[folder_name]["sections"]:
            groups[folder_name]["sections"].append(section)

    LESSONS_ROOT.mkdir(exist_ok=True)

    print()
    print("=" * 60)
    print("  ClassEdge LMS — Create Lesson Folders")
    print("=" * 60)
    print(f"  Lessons folder: {LESSONS_ROOT}")
    print()

    for folder_name, info in sorted(groups.items()):
        folder = LESSONS_ROOT / folder_name
        was_new = not folder.exists()
        folder.mkdir(exist_ok=True)

        # Always write/update _subject_ids.json (IDs may change each semester)
        ids_data = {
            "subject":     info["subject"],
            "kind":        info["kind"],
            "subject_ids": info["ids"],
            "sections":    info["sections"],
            "note": (
                "These are the ClassEdge subject IDs this folder uploads to. "
                "Do not delete. Re-run create_lesson_folders.py to update."
            ),
        }
        (folder / "_subject_ids.json").write_text(
            json.dumps(ids_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Write naming guide only once (don't overwrite if teacher edited it)
        guide = folder / "_HOW_TO_ADD_LESSONS.txt"
        if not guide.exists():
            guide.write_text(NAMING_GUIDE, encoding="utf-8")

        status = "Created" if was_new else "Updated"
        sections_str = ", ".join(info["sections"])
        print(f"  {status}: {folder_name}/")
        print(f"           IDs: {info['ids']}  |  Sections: {sections_str}")

    print()
    print(f"  {len(groups)} subject folder(s) ready in: {LESSONS_ROOT}")
    print()
    print("  NEXT STEPS:")
    print("  1. Open the lessons\\ folder")
    print("  2. Drop your lesson files into the matching subject folder")
    print("  3. Run UPLOAD_LESSONS.bat to upload everything")
    print()


if __name__ == "__main__":
    main()
