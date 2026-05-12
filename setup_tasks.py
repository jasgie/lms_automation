"""
setup_tasks.py
--------------
Registers all class schedules as Windows Task Scheduler tasks.
Each task fires 15 minutes before class and auto-clicks Start Class.

KEY FEATURE: Tasks use StartWhenAvailable — if your laptop was off at
trigger time, the task runs automatically as soon as you log in.
A built-in deadline window prevents late runs (>75 min past trigger).

Run ONCE:
  python setup_tasks.py

To remove all registered tasks:
  python setup_tasks.py --delete

To list registered tasks:
  python setup_tasks.py --list
"""

import subprocess
import sys
import json
from pathlib import Path

# Day name mapping: schtasks abbrev → PowerShell full name
DAY_MAP = {
    "MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday",
    "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday",
}

# ---------------------------------------------------------------------------
# Paths — uses the Python interpreter from the current virtual environment
# ---------------------------------------------------------------------------

SCRIPT_DIR         = Path(__file__).parent.resolve()
APP_DIR            = Path.home() / "AppData" / "Local" / "ClassEdge LMS"
PYTHON_EXE         = APP_DIR / ".venv" / "Scripts" / "python.exe"
# Always point launchers at the installed copy so logs go to APP_DIR
START_CLASS_SCRIPT = APP_DIR / "lms_start_class.py"
TASK_FOLDER        = "LMS_ClassEdge"
SCHEDULE_FILE      = SCRIPT_DIR / "schedule.json"

# ---------------------------------------------------------------------------
# Load schedule from schedule.json
# ---------------------------------------------------------------------------

def load_schedule() -> list:
    if not SCHEDULE_FILE.exists():
        print(f"ERROR: {SCHEDULE_FILE.name} not found.")
        print("Run extract_schedule.py first to generate it from your schedule docx.")
        sys.exit(1)
    with open(SCHEDULE_FILE, encoding="utf-8") as f:
        data = json.load(f)
    # Normalize to tuple format: (name, day, trigger_time, url)
    return [(e["name"], e["day"], e["trigger_time"], e["url"]) for e in data]


# ---------------------------------------------------------------------------
# Task operations
# ---------------------------------------------------------------------------

LAUNCHERS_DIR = SCRIPT_DIR / "launchers"


def create_launcher(name: str, trigger_time: str, url: str) -> Path:
    """Write a .bat file that calls the python script. Returns the .bat path."""
    LAUNCHERS_DIR.mkdir(exist_ok=True)
    bat_path = LAUNCHERS_DIR / f"{name}.bat"
    bat_path.write_text(
        f'@echo off\n'
        f'"{PYTHON_EXE}" "{START_CLASS_SCRIPT}" '
        f'--url "{url}" --scheduled-time "{trigger_time}"\n',
        encoding="utf-8",
    )
    return bat_path


def create_task(name: str, day: str, trigger_time: str, url: str) -> bool:
    full_name = f"{TASK_FOLDER}\\{name}"
    bat_path  = create_launcher(name, trigger_time, url)
    ps_day    = DAY_MAP[day]

    # Use PowerShell Register-ScheduledTask for StartWhenAvailable support
    ps_script = f"""
$action   = New-ScheduledTaskAction -Execute '{bat_path}'
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek {ps_day} -At '{trigger_time}'
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
Register-ScheduledTask `
    -TaskName '{full_name}' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Force | Out-Null
Write-Output "OK"
""".strip()

    result = subprocess.run(
        ["powershell", "-NonInteractive", "-Command", ps_script],
        capture_output=True,
        text=True,
    )

    success = result.returncode == 0 and "OK" in result.stdout
    status  = "OK" if success else "FAILED"
    detail  = result.stderr.strip() if not success else "scheduled (StartWhenAvailable)"
    print(f"  [{status}] {name:35s}  {day} {trigger_time}  →  {detail}")
    return success


def delete_all():
    ps = f"Unregister-ScheduledTask -TaskPath '\\{TASK_FOLDER}\\' -Confirm:$false -ErrorAction SilentlyContinue"
    subprocess.run(["powershell", "-NonInteractive", "-Command", ps])
    print(f"Deleted task folder: {TASK_FOLDER}")


def list_tasks():
    ps = f"Get-ScheduledTask -TaskPath '\\{TASK_FOLDER}\\' | Format-Table TaskName,State -AutoSize"
    result = subprocess.run(
        ["powershell", "-NonInteractive", "-Command", ps],
        capture_output=True, text=True,
    )
    print(result.stdout if result.stdout.strip() else f"No tasks found under '{TASK_FOLDER}'.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--delete" in sys.argv:
        delete_all()
        sys.exit(0)

    if "--list" in sys.argv:
        list_tasks()
        sys.exit(0)

    print("=" * 60)
    print("  ClassEdge LMS — Task Scheduler Setup")
    print("=" * 60)
    print(f"  Python : {PYTHON_EXE}")
    print(f"  Script : {START_CLASS_SCRIPT}")
    print(f"  Folder : {TASK_FOLDER}")
    print()

    auth_file = SCRIPT_DIR / "auth.json"
    if not auth_file.exists():
        print("WARNING: auth.json not found!")
        print("Run lms_login_setup.py FIRST before using these tasks.\n")

    print("Creating tasks (trigger = 15 min before class, StartWhenAvailable ON)...\n")

    SCHEDULE = load_schedule()
    ok = 0
    for entry in SCHEDULE:
        if create_task(*entry):
            ok += 1

    print()
    print(f"Done: {ok}/{len(SCHEDULE)} tasks registered.")
    print()
    print("Behaviour when laptop was off at trigger time:")
    print("  → Task runs automatically as soon as you log in.")
    print("  → If more than 75 min have passed since trigger, it skips gracefully.")
    print()
    print("Next steps:")
    print("  1. If you haven't already, run:  python lms_login_setup.py")
    print("  2. Tasks are active — they will run automatically each week.")
    print("  3. To remove all:  python setup_tasks.py --delete")
    print("  4. To list all:    python setup_tasks.py --list")
    print("=" * 60)
