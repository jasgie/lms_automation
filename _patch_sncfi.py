"""
_patch_sncfi.py  —  internal build helper, do not run manually.
Creates patched copies of lms_app.py and extract_schedule_web.py
for the SNCFI institution build.
"""
import pathlib, sys

root = pathlib.Path(__file__).parent

# ---------- lms_app.py ----------
src = (root / "lms_app.py").read_text(encoding="utf-8")
src = src.replace(
    'SCHOOL_SHORT = "HCCI"',
    'SCHOOL_SHORT = "SNCFI"',
)
src = src.replace(
    'SCHOOL_NAME  = "Holy Child Central Colleges, Inc."',
    'SCHOOL_NAME  = "Santo Nino College Foundation, Inc."',
)
src = src.replace(
    'GITHUB_REPO = "jasgie/lms_automation"',
    'GITHUB_REPO = ""',
)
(root / "_lms_app_sncfi.py").write_text(src, encoding="utf-8")

# ---------- extract_schedule_web.py → _sncfi_tmp/ (keeps original filename) ----------
tmp = root / "_sncfi_tmp"
tmp.mkdir(exist_ok=True)
src2 = (root / "extract_schedule_web.py").read_text(encoding="utf-8")
src2 = src2.replace(
    'SUBJECT_LIST  = "https://classedge.hccci.edu.ph/SubjectList/"  # LMS_SUBJECT_LIST_URL',
    'SUBJECT_LIST  = "https://classedge.sncfi.edu.ph/SubjectList/"  # LMS_SUBJECT_LIST_URL',
)
(tmp / "extract_schedule_web.py").write_text(src2, encoding="utf-8")

print("  Patched OK.")
