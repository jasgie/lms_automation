"""
setup_sncfi_workspace.py  —  run once to create the SNCFI workspace
"""
import shutil, pathlib

SRC = pathlib.Path(r"c:\Users\gatdu\OneDrive\Documents\SCHOOL FILES\TO-TQS 2025-2026\2ND SEM\FINALS\lms_automation")
DST = pathlib.Path(r"C:\Users\gatdu\OneDrive\Documents\WEBDEV\lms-automation_SNCFI")

DST.mkdir(parents=True, exist_ok=True)

PLAIN_FILES = [
    "lms_start_class.py", "lms_login_setup.py", "extract_schedule.py",
    "setup_tasks.py", "create_lesson_folders.py", "upload_lessons.py",
    "build_exe.bat", "requirements.txt", "SETUP.bat", "SETUP.txt",
    "UPDATE.bat", "UPLOAD_LESSONS.bat", "make_icon.py",
    "classedge_lms.ico", "classedge_preview.png",
]
for f in PLAIN_FILES:
    p = SRC / f
    if p.exists():
        shutil.copy2(p, DST / f)
        print(f"  copied  {f}")
    else:
        print(f"  MISSING {f}")

# lms_app.py — patch for SNCFI
app = (SRC / "lms_app.py").read_text(encoding="utf-8")
app = app.replace('SCHOOL_SHORT = "HCCI"',           'SCHOOL_SHORT = "SNCFI"')
app = app.replace('SCHOOL_NAME  = "Holy Child Central Colleges, Inc."',
                  'SCHOOL_NAME  = "Santo Nino College Foundation, Inc."')
app = app.replace('GITHUB_REPO = "jasgie/lms_automation"',
                  'GITHUB_REPO = "jasgie/lms-automation_SNCFI"')
(DST / "lms_app.py").write_text(app, encoding="utf-8")
print("  patched lms_app.py")

# extract_schedule_web.py — patch URL
sched = (SRC / "extract_schedule_web.py").read_text(encoding="utf-8")
sched = sched.replace("classedge.hccci.edu.ph/SubjectList/",
                      "classedge.sncfi.edu.ph/SubjectList/")
(DST / "extract_schedule_web.py").write_text(sched, encoding="utf-8")
print("  patched extract_schedule_web.py")

print(f"\nWorkspace ready at:\n  {DST}")
