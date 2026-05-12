"""
lms_app.py
----------
ClassEdge LMS Automation — GUI Application.

All LMS automation features in one window. Manages its own virtual
environment in %LOCALAPPDATA%\\ClassEdge LMS\\ so teachers don't need
to use the command line at all.

Compile to EXE (from lms_automation/ folder):
  pyinstaller --onefile --windowed --name "ClassEdge LMS" ^
    --add-data "lms_login_setup.py;." ^
    --add-data "lms_start_class.py;." ^
    --add-data "extract_schedule_web.py;." ^
    --add-data "extract_schedule.py;." ^
    --add-data "setup_tasks.py;." ^
    --add-data "create_lesson_folders.py;." ^
    --add-data "upload_lessons.py;." ^
    lms_app.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

# Force UTF-8 output from all child Python processes (avoids CP1252 UnicodeEncodeError)
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# ─────────────────────────────────────────────────────────────────────────────
# Version  (bump this string when distributing a new build)
# ─────────────────────────────────────────────────────────────────────────────

VERSION = "1.3.0"

# GitHub repo used for update checks (format: "owner/repo")
GITHUB_REPO = "jasgie/lms_automation"

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

APP_DIR  = Path.home() / "AppData" / "Local" / "ClassEdge LMS"
VENV_DIR = APP_DIR / ".venv"
PYTHON   = VENV_DIR / "Scripts" / "python.exe"

# Python scripts that get extracted from the EXE bundle on first run
BUNDLED_SCRIPTS = [

    "lms_login_setup.py",
    "lms_start_class.py",
    "extract_schedule_web.py",
    "extract_schedule.py",
    "setup_tasks.py",
    "create_lesson_folders.py",
    "upload_lessons.py",
]


def bundled(name: str) -> Path:
    """Path to a file bundled inside the EXE (or local dev folder)."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / name
    return Path(__file__).parent / name


ICON_PATH = bundled("classedge_lms.ico")


def is_setup_done() -> bool:
    return PYTHON.exists() and (APP_DIR / "extract_schedule_web.py").exists()


def has_session() -> bool:
    return (APP_DIR / "auth.json").exists()


def has_schedule() -> bool:
    return (APP_DIR / "schedule.json").exists()


# ─────────────────────────────────────────────────────────────────────────────
# Colour palette
# ─────────────────────────────────────────────────────────────────────────────

C_SIDEBAR  = "#1b2d40"
C_SIDEBAR2 = "#243547"
C_ACCENT   = "#1a73e8"
C_BG       = "#f5f7fa"
C_DARK     = "#1b2d40"
C_TERM_BG  = "#0f1e2d"
C_TERM_FG  = "#c8d8e8"

C_OK    = "#4caf8e"
C_ERR   = "#e05c5c"
C_WARN  = "#e8b84b"
C_INFO  = "#56b4d3"
C_DIM   = "#7a99b8"


# ─────────────────────────────────────────────────────────────────────────────
# Self-installer
# ─────────────────────────────────────────────────────────────────────────────

INSTALL_DIR  = Path.home() / "AppData" / "Local" / "Programs" / "ClassEdge LMS"
INSTALL_EXE  = INSTALL_DIR / "ClassEdge LMS.exe"
INSTALL_FLAG = APP_DIR / "_installed"   # written after successful install
VERSION_FILE = INSTALL_DIR / "version.txt"  # stores the installed version


def _parse_version(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except Exception:
        return (0,)


def _installed_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return "0.0.0"


def _write_shortcuts_and_registry():
    exe_s = str(INSTALL_EXE)
    desktop    = Path.home() / "Desktop"
    start_menu = (
        Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    )

    def _q(p: Path) -> str:
        return str(p).replace("'", "`'")

    ps_shortcuts = f"""
$ws = New-Object -ComObject WScript.Shell
foreach ($dest in @('{_q(desktop / "ClassEdge LMS.lnk")}',
                    '{_q(start_menu / "ClassEdge LMS.lnk")}')) {{
    $lnk = $ws.CreateShortcut($dest)
    $lnk.TargetPath      = '{_q(INSTALL_EXE)}'
    $lnk.WorkingDirectory= '{_q(INSTALL_DIR)}'
    $lnk.Description     = 'ClassEdge LMS Automation'
    $lnk.Save()
}}
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_shortcuts],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )

    reg_key = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\ClassEdge LMS"
    for cmd in [
        f'reg add "{reg_key}" /v DisplayName      /t REG_SZ    /d "ClassEdge LMS Automation" /f',
        f'reg add "{reg_key}" /v DisplayVersion   /t REG_SZ    /d "{VERSION}"                /f',
        f'reg add "{reg_key}" /v Publisher        /t REG_SZ    /d "HCCI"                     /f',
        f'reg add "{reg_key}" /v InstallLocation  /t REG_SZ    /d "{str(INSTALL_DIR)}"        /f',
        f'reg add "{reg_key}" /v UninstallString  /t REG_SZ    /d "{exe_s} --uninstall"       /f',
        f'reg add "{reg_key}" /v NoModify         /t REG_DWORD /d 1                           /f',
        f'reg add "{reg_key}" /v NoRepair         /t REG_DWORD /d 1                           /f',
    ]:
        subprocess.run(cmd, capture_output=True, shell=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)


def self_install(app: "App | None" = None):
    """
    Fresh install OR update — runs in a background thread on every launch.

    Logic:
      • Running from INSTALL_EXE already  → nothing to do (normal launch).
      • Running from elsewhere, no install flag → fresh install.
      • Running from elsewhere, install flag exists → update if VERSION is newer.
    """
    if not getattr(sys, "frozen", False):
        return  # dev mode — skip

    src = Path(sys.executable).resolve()
    is_installed_copy = src == INSTALL_EXE.resolve() if INSTALL_EXE.exists() else False

    if is_installed_copy:
        return  # launched from the installed location — normal run

    already_installed = INSTALL_FLAG.exists()

    if already_installed:
        # ── Update path ───────────────────────────────────────────────────────
        old_ver = _installed_version()
        if _parse_version(VERSION) <= _parse_version(old_ver):
            return  # same or older — don't touch the installed copy

        # Ask user on main thread, then proceed if they say yes
        if app is not None:
            confirmed = threading.Event()
            answer    = [False]

            def _ask():
                answer[0] = messagebox.askyesno(
                    "Update Available",
                    f"A newer version of ClassEdge LMS is available.\n\n"
                    f"  Installed : {old_ver}\n"
                    f"  This file : {VERSION}\n\n"
                    "Update now? The app will restart automatically.",
                )
                confirmed.set()

            app.after(0, _ask)
            confirmed.wait()
            if not answer[0]:
                return
        else:
            return  # headless — skip update prompt
    # else: fresh install — proceed silently

    # ── Copy EXE ──────────────────────────────────────────────────────────────
    try:
        INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        # If updating, the old EXE may be running (it's not — we're the new EXE).
        # Overwrite directly; Windows allows overwriting a file that isn't open.
        shutil.copy2(src, INSTALL_EXE)
        VERSION_FILE.write_text(VERSION, encoding="utf-8")
    except Exception as exc:
        if app is not None:
            app.after(0, lambda: messagebox.showerror(
                "Install Failed", f"Could not copy EXE:\n{exc}"))
        return

    _write_shortcuts_and_registry()

    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        INSTALL_FLAG.touch()
    except Exception:
        pass

    if already_installed:
        # Update complete — restart from installed location
        if app is not None:
            def _restart():
                messagebox.showinfo(
                    "Update Complete",
                    f"Updated to version {VERSION}.\n\n"
                    "The app will now restart from the installed location.",
                )
                app.destroy()
                subprocess.Popen(
                    [str(INSTALL_EXE)],
                    creationflags=subprocess.DETACHED_PROCESS,
                )
            app.after(0, _restart)
    else:
        # Fresh install complete — notify
        if app is not None:
            app.after(0, lambda: messagebox.showinfo(
                "ClassEdge LMS Installed",
                f"ClassEdge LMS v{VERSION} has been installed.\n\n"
                "A shortcut has been added to your Desktop and Start Menu.\n\n"
                "You can now use the Desktop shortcut to launch it.",
            ))


# ─────────────────────────────────────────────────────────────────────────────
# Main Application
# ─────────────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ClassEdge LMS Automation")
        self.geometry("900x640")
        self.minsize(720, 500)
        self.configure(bg=C_BG)
        try:
            if ICON_PATH.exists():
                self.iconbitmap(str(ICON_PATH))
        except Exception:
            pass

        self._busy     = False
        self._btn_map: dict[str, tk.Button] = {}
        self._update_banner: tk.Frame | None = None

        self._build_sidebar()
        self._build_content()
        self.after(300, self._initial_check)
        threading.Thread(target=self_install, args=(self,), daemon=True).start()
        threading.Thread(target=self._check_github_updates, daemon=True).start()

    # ── GitHub update check ───────────────────────────────────────────────────

    def _check_github_updates(self):
        """Background thread: fetch latest GitHub release and show banner if newer."""
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": f"ClassEdge-LMS/{VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            tag        = data.get("tag_name", "").lstrip("v")
            release_url = data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases")
            if not tag:
                return
            if _parse_version(tag) > _parse_version(VERSION):
                self.after(0, lambda: self._show_update_banner(tag, release_url))
        except Exception:
            pass  # silently ignore network errors

    def _show_update_banner(self, latest_ver: str, release_url: str):
        """Show a dismissible update-available banner below the header."""
        if self._update_banner is not None:
            return  # already shown

        # Insert before the output box (right frame's second child)
        right = self._out.master
        banner = tk.Frame(right, bg="#2d4a1e", pady=6)
        banner.pack(fill="x", padx=14, before=self._out)
        self._update_banner = banner

        tk.Label(
            banner,
            text=f"🔔  Update available: v{latest_ver}  (current: v{VERSION})",
            bg="#2d4a1e", fg="#3fb950",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=(10, 6))

        tk.Button(
            banner, text="Download",
            bg="#3fb950", fg="white", relief="flat",
            font=("Segoe UI", 8, "bold"), padx=8, pady=2, cursor="hand2",
            command=lambda: webbrowser.open(release_url),
        ).pack(side="left", padx=4)

        def _dismiss():
            banner.destroy()
            self._update_banner = None

        tk.Button(
            banner, text="✕", bg="#2d4a1e", fg="#8b949e",
            relief="flat", font=("Segoe UI", 9), padx=6, pady=0,
            cursor="hand2", command=_dismiss,
        ).pack(side="right", padx=6)

    def _show_update_dialog(self, latest_ver: str, release_url: str, download_url: str | None = None):
        """Show a popup with Download & Install (or browser fallback)."""
        win = tk.Toplevel(self)
        win.title("Update Available")
        win.resizable(False, False)
        win.grab_set()
        win.configure(bg=C_BG)
        try:
            win.iconbitmap(str(ICON_PATH))
        except Exception:
            pass

        tk.Label(
            win, text="🔔  A new version is available!",
            bg=C_BG, fg=C_DARK, font=("Segoe UI", 11, "bold"),
            pady=14, padx=20,
        ).pack()

        info = tk.Frame(win, bg=C_BG)
        info.pack(padx=20, pady=(0, 10))
        tk.Label(info, text=f"  Latest  :  v{latest_ver}", bg=C_BG, fg=C_DARK,
                 font=("Segoe UI", 9), anchor="w").pack(fill="x")
        tk.Label(info, text=f"  Current :  v{VERSION}", bg=C_BG, fg=C_DIM,
                 font=("Segoe UI", 9), anchor="w").pack(fill="x")

        # Progress area — hidden until download starts
        prog_frame = tk.Frame(win, bg=C_BG)
        progress_var = tk.IntVar(value=0)
        ttk.Progressbar(
            prog_frame, variable=progress_var, maximum=100, length=260
        ).pack(fill="x", pady=(0, 4))
        status_lbl = tk.Label(
            prog_frame, text="", bg=C_BG, fg=C_DIM, font=("Segoe UI", 8)
        )
        status_lbl.pack()

        btns = tk.Frame(win, bg=C_BG)
        btns.pack(pady=(6, 16), padx=20)

        can_self_update = download_url and hasattr(sys, "_MEIPASS")
        if can_self_update:
            btn_install = tk.Button(
                btns, text="⬇  Download & Install", bg=C_ACCENT, fg="white",
                relief="flat", font=("Segoe UI", 9, "bold"),
                padx=16, pady=6, cursor="hand2",
            )
            btn_install.pack(side="left", padx=(0, 8))

            def _start_install():
                prog_frame.pack(padx=20, pady=(0, 8), before=btns, fill="x")
                win.update_idletasks()
                self._do_self_update(download_url, win, btn_install, status_lbl, progress_var)

            btn_install.config(command=_start_install)
        else:
            tk.Button(
                btns, text="Download", bg=C_ACCENT, fg="white",
                relief="flat", font=("Segoe UI", 9, "bold"),
                padx=16, pady=6, cursor="hand2",
                command=lambda: [webbrowser.open(release_url), win.destroy()],
            ).pack(side="left", padx=(0, 8))

        tk.Button(
            btns, text="Later", bg=C_BG, fg=C_DIM,
            relief="flat", font=("Segoe UI", 9),
            padx=12, pady=6, cursor="hand2",
            command=win.destroy,
        ).pack(side="left")

        win.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_y() + (self.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{x}+{y}")

    def _do_self_update(self, download_url: str, win: tk.Toplevel,
                        btn_install, status_lbl, progress_var):
        """Download new EXE to a temp file, then replace self via a detached batch script."""
        import tempfile
        current_exe = Path(sys.executable)
        new_exe = current_exe.parent / (current_exe.stem + "_update.exe")

        def _download():
            try:
                self.after(0, lambda: btn_install.config(
                    state="disabled", text="Downloading..."))
                req = urllib.request.Request(
                    download_url,
                    headers={"User-Agent": f"ClassEdge-LMS/{VERSION}"},
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    total = int(resp.headers.get("Content-Length", 0))
                    downloaded = 0
                    with open(new_exe, "wb") as f:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                pct = int(downloaded / total * 100)
                                self.after(0, lambda p=pct: progress_var.set(p))
                                self.after(0, lambda p=pct: status_lbl.config(
                                    text=f"Downloading...  {p}%"))
                self.after(0, lambda: status_lbl.config(
                    text="Applying update — app will restart shortly..."))
                self.after(800, _apply_update)
            except Exception as exc:
                if new_exe.exists():
                    try:
                        new_exe.unlink()
                    except Exception:
                        pass
                self.after(0, lambda: messagebox.showerror(
                    "Update Failed", f"Could not download update:\n{exc}"))
                self.after(0, lambda: btn_install.config(
                    state="normal", text="⬇  Download & Install"))
                self.after(0, lambda: status_lbl.config(text=""))

        def _apply_update():
            bat = Path(tempfile.gettempdir()) / "classedge_update.bat"
            bat.write_text(
                "@echo off\n"
                "ping -n 4 127.0.0.1 > nul\n"
                f'move /y "{new_exe}" "{current_exe}"\n'
                f'start "" "{current_exe}"\n'
                'del "%~f0"\n',
                encoding="utf-8",
            )
            subprocess.Popen(
                ["cmd.exe", "/c", str(bat)],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
            self.destroy()
            sys.exit(0)

        threading.Thread(target=_download, daemon=True).start()

    def cmd_check_updates(self):
        """Manual: check for updates and show result."""
        def _worker():
            try:
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": f"ClassEdge-LMS/{VERSION}"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                tag         = data.get("tag_name", "").lstrip("v")
                release_url = data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases")
                if not tag:
                    self.after(0, lambda: messagebox.showinfo(
                        "Check for Updates", "Could not determine latest version."))
                    return
                assets = data.get("assets", [])
                download_url = next(
                    (a["browser_download_url"] for a in assets
                     if a.get("name", "").endswith(".exe")),
                    None,
                )
                if _parse_version(tag) > _parse_version(VERSION):
                    self.after(0, lambda: self._show_update_banner(tag, release_url))
                    self.after(0, lambda: self._show_update_dialog(tag, release_url, download_url))
                else:
                    self.after(0, lambda: messagebox.showinfo(
                        "Check for Updates",
                        f"You are on the latest version (v{VERSION}). ✅",
                    ))
            except urllib.error.URLError:
                self.after(0, lambda: messagebox.showwarning(
                    "Check for Updates",
                    "Could not reach GitHub. Check your internet connection.",
                ))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror(
                    "Check for Updates", f"Unexpected error:\n{exc}"))

        threading.Thread(target=_worker, daemon=True).start()

    # ── Sidebar ──────────────────────────────────────────────────────────────

    def _build_sidebar(self):
        self._sidebar = tk.Frame(self, bg=C_SIDEBAR, width=210)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        # Logo / title (fixed, not scrollable)
        tk.Label(
            self._sidebar, text="ClassEdge", bg=C_SIDEBAR, fg="white",
            font=("Segoe UI", 14, "bold"), pady=12
        ).pack(fill="x", padx=14)
        tk.Label(
            self._sidebar, text="LMS Automation", bg=C_SIDEBAR, fg=C_DIM,
            font=("Segoe UI", 9)
        ).pack(fill="x", padx=14)
        tk.Label(
            self._sidebar, text=f"v{VERSION}", bg=C_SIDEBAR, fg=C_DIM,
            font=("Segoe UI", 8)
        ).pack(fill="x", padx=14)

        self._sep(self._sidebar)

        # Scrollable canvas for buttons
        canvas = tk.Canvas(
            self._sidebar, bg=C_SIDEBAR, highlightthickness=0, bd=0
        )
        scrollbar = tk.Scrollbar(
            self._sidebar, orient="vertical", command=canvas.yview,
            bg=C_SIDEBAR, troughcolor=C_SIDEBAR, activebackground=C_SIDEBAR2,
            width=6,
        )
        canvas.configure(yscrollcommand=scrollbar.set)

        # Scrollbar only appears when needed; pack canvas to fill remaining space
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Inner frame inside canvas holds the actual buttons
        inner = tk.Frame(canvas, bg=C_SIDEBAR)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfig(inner_id, width=event.width)

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Mouse-wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        ITEMS = [
            ("setup",     "⚙   First-Time Setup",     self.cmd_setup,        True),
            ("login",     "🔑  Save Login Session",    self.cmd_login,        False),
            ("schedule",  "📅  Extract Schedule",      self.cmd_schedule,     False),
            (None, None, None, None),
            ("folders",   "📁  Create Lesson Folders", self.cmd_folders,      False),
            ("upload",    "📤  Upload Lessons",        self.cmd_upload,       False),
            (None, None, None, None),
            ("startnow",  "▶  Start Class Now",       self.cmd_start_now,    False),
            (None, None, None, None),
            ("tasks",     "🗓  Register Tasks",        self.cmd_tasks,        False),
            ("listtasks", "📋  List Tasks",            self.cmd_list_tasks,   False),
            ("deltasks",  "🗑  Remove All Tasks",      self.cmd_delete_tasks, False),
            (None, None, None, None),
            ("opendir",   "📂  Open App Folder",       self.cmd_open_dir,     False),
            ("openless",  "📂  Open Lessons Folder",   self.cmd_open_lessons, False),
            ("openerr",   "⚠️  Open Errors Folder",    self.cmd_open_errors,  False),
            ("viewlog",   "📜  View Start Class Log",  self.cmd_view_log,     False),
            (None, None, None, None),
            ("howto",     "❓  How-To Guide",          self.cmd_howto,          False),
            ("updates",   "🔄  Check for Updates",     self.cmd_check_updates,  False),
        ]

        for key, label, cmd, is_primary in ITEMS:
            if key is None:
                self._sep(inner)
                continue
            bg = C_ACCENT if is_primary else C_SIDEBAR
            btn = tk.Button(
                inner, text=label, command=cmd,
                bg=bg, fg="white", activebackground=C_SIDEBAR2,
                activeforeground="white", relief="flat",
                anchor="w", padx=14, pady=7,
                font=("Segoe UI", 9), cursor="hand2", bd=0,
            )
            btn.pack(fill="x", pady=1)
            self._btn_map[key] = btn

    def _sep(self, parent):
        tk.Frame(parent, bg=C_SIDEBAR2, height=1).pack(fill="x", padx=10, pady=6)

    # ── Content area ─────────────────────────────────────────────────────────

    def _build_content(self):
        right = tk.Frame(self, bg=C_BG)
        right.pack(side="right", fill="both", expand=True)

        # Header bar
        header = tk.Frame(right, bg=C_BG, pady=8)
        header.pack(fill="x", padx=14)
        self._title_lbl = tk.Label(
            header, text="ClassEdge LMS Automation", bg=C_BG, fg=C_DARK,
            font=("Segoe UI", 12, "bold")
        )
        self._title_lbl.pack(side="left")
        tk.Button(
            header, text="Clear output", bg=C_BG, fg=C_DIM,
            relief="flat", font=("Segoe UI", 8), cursor="hand2",
            command=self.clear_output
        ).pack(side="right")

        # Terminal-style output box
        self._out = scrolledtext.ScrolledText(
            right, font=("Consolas", 9), bg=C_TERM_BG, fg=C_TERM_FG,
            insertbackground="white", relief="flat", wrap="word",
            state="disabled", pady=6, padx=8,
        )
        self._out.pack(fill="both", expand=True, padx=14, pady=(0, 0))
        self._out.tag_config("ok",   foreground=C_OK)
        self._out.tag_config("err",  foreground=C_ERR)
        self._out.tag_config("warn", foreground=C_WARN)
        self._out.tag_config("info", foreground=C_INFO)
        self._out.tag_config("dim",  foreground=C_DIM)

        # Status bar
        self._status_var = tk.StringVar(value="Ready")
        tk.Label(
            right, textvariable=self._status_var, bg="#dde5ef", fg=C_DARK,
            anchor="w", padx=14, font=("Segoe UI", 8)
        ).pack(fill="x")

    # ── Logging ───────────────────────────────────────────────────────────────

    def log(self, text: str, tag: str = ""):
        if not tag:
            tl = text.lower()
            if any(k in tl for k in ("error", "failed", "exception", "traceback")):
                tag = "err"
            elif any(k in tl for k in ("warning", "skipped")):
                tag = "warn"
            elif any(k in tl for k in ("success", "done", "complete", "saved",
                                       "created", "uploaded", "registered", "✓")):
                tag = "ok"
            elif any(k in tl for k in ("===", "───", "classedge", "step",
                                       "check", "opening", "loading", "found")):
                tag = "info"
            else:
                tag = ""

        ts = datetime.now().strftime("%H:%M:%S")
        self._out.configure(state="normal")
        self._out.insert("end", f"[{ts}] {text}\n", tag or C_TERM_FG)
        self._out.see("end")
        self._out.configure(state="disabled")

    def clear_output(self):
        self._out.configure(state="normal")
        self._out.delete("1.0", "end")
        self._out.configure(state="disabled")

    def status(self, msg: str):
        self._status_var.set(msg)

    # ── Initial check ─────────────────────────────────────────────────────────

    def _initial_check(self):
        if not is_setup_done():
            self.log("Welcome to ClassEdge LMS Automation!", "info")
            self.log("First-time setup is required. Click  ⚙ First-Time Setup  to begin.", "warn")
        else:
            # Always sync bundled scripts so EXE updates propagate without re-running setup
            for name in BUNDLED_SCRIPTS:
                src = bundled(name)
                dst = APP_DIR / name
                if src.exists():
                    try:
                        shutil.copy2(src, dst)
                    except Exception:
                        pass
            self.log("ClassEdge LMS Automation  ✓  ready", "ok")
            self.log(f"App folder : {APP_DIR}", "dim")
            if has_session():
                self.log("Session    : auth.json found ✓", "ok")
            else:
                self.log("Session    : auth.json missing — click Save Login Session", "warn")
            if has_schedule():
                self.log("Schedule   : schedule.json found ✓", "ok")
            else:
                self.log("Schedule   : not extracted yet — click Extract Schedule", "warn")

    # ── Subprocess runner (background thread) ─────────────────────────────────

    def _run(self, label: str, args: list, on_done=None):
        if self._busy:
            messagebox.showwarning("Busy", "Another operation is running. Please wait.")
            return
        self._busy = True
        self.status(f"Running: {label}…")

        def _worker():
            self.log(f"▶  {label}", "info")
            try:
                proc = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    cwd=str(APP_DIR),
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                for line in iter(proc.stdout.readline, ""):
                    stripped = line.rstrip("\n")
                    if stripped:
                        self.log(stripped)
                proc.wait()
                rc = proc.returncode
            except Exception as exc:
                self.log(f"ERROR: {exc}", "err")
                rc = -1
            finally:
                self._busy = False
                ok = rc == 0
                self.status(f"{label}: {'OK' if ok else f'FAILED (code {rc})'}")
                self.log(f"■  {label} finished {'✓' if ok else '✗'}", "ok" if ok else "err")
                if on_done:
                    self.after(0, on_done, rc)

        threading.Thread(target=_worker, daemon=True).start()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def cmd_setup(self):
        if self._busy:
            return
        threading.Thread(target=self._do_setup, daemon=True).start()

    def _do_setup(self):
        self._busy = True
        self.status("Running first-time setup…")
        self.log("═" * 52, "info")
        self.log("  First-Time Setup", "info")
        self.log("═" * 52, "info")
        try:
            # 1. Create app directory
            APP_DIR.mkdir(parents=True, exist_ok=True)
            self.log(f"App folder: {APP_DIR}", "ok")

            # 2. Extract scripts
            self.log("Extracting scripts…", "info")
            for name in BUNDLED_SCRIPTS:
                src = bundled(name)
                dst = APP_DIR / name
                if src.exists():
                    shutil.copy2(src, dst)
                    self.log(f"  {name}", "ok")
                else:
                    self.log(f"  WARNING: {name} not found in bundle", "warn")

            # 3. Check Python
            self.log("Checking Python installation…", "info")
            try:
                r = subprocess.run(
                    ["python", "--version"], capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if r.returncode != 0:
                    raise FileNotFoundError
                self.log(f"  {r.stdout.strip()}", "ok")
            except FileNotFoundError:
                self.log("ERROR: Python not found. Install from python.org", "err")
                self.log("Tick 'Add Python to PATH' during install, then restart this app.", "warn")
                self.after(0, messagebox.showerror, "Python Not Found",
                    "Python is not installed or not in PATH.\n\n"
                    "Please install Python 3.10+ from:\n"
                    "  https://www.python.org/downloads/\n\n"
                    "IMPORTANT: Tick 'Add Python to PATH' during install,\n"
                    "then restart this application.")
                return

            # 4. Virtual environment
            if not VENV_DIR.exists():
                self.log("Creating virtual environment…", "info")
                r = subprocess.run(
                    ["python", "-m", "venv", str(VENV_DIR)],
                    capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if r.returncode != 0:
                    self.log(f"ERROR: {r.stderr[:400]}", "err")
                    return
            self.log("  Virtual environment ready.", "ok")

            # 5. Install pip packages
            self.log("Installing packages (playwright, python-docx)…", "info")
            self.log("  This may take a minute…", "warn")
            pip = str(VENV_DIR / "Scripts" / "pip.exe")
            proc = subprocess.Popen(
                [pip, "install", "--upgrade", "playwright", "python-docx"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in iter(proc.stdout.readline, ""):
                stripped = line.rstrip("\n")
                if stripped:
                    self.log(f"  {stripped}", "dim")
            proc.wait()
            if proc.returncode != 0:
                self.log("ERROR: pip install failed. Check internet connection.", "err")
                return
            self.log("  Packages installed.", "ok")

            # 6. Playwright Chromium
            self.log("Installing Playwright Chromium (~150 MB, may take a few minutes)…", "info")
            playwright_exe = str(VENV_DIR / "Scripts" / "playwright.exe")
            proc = subprocess.Popen(
                [playwright_exe, "install", "chromium"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in iter(proc.stdout.readline, ""):
                stripped = line.rstrip("\n")
                if stripped:
                    self.log(f"  {stripped}", "dim")
            proc.wait()
            if proc.returncode != 0:
                self.log("ERROR: Playwright browser install failed.", "err")
                return
            self.log("  Chromium installed.", "ok")

            self.log("═" * 52, "info")
            self.log("  Setup complete! ✓", "ok")
            self.log("  Next: click  🔑 Save Login Session", "info")
            self.log("═" * 52, "info")
            self.status("Setup complete!")
            self.after(0, messagebox.showinfo, "Setup Complete",
                "Setup is complete!\n\n"
                "Next step: click  🔑 Save Login Session\n"
                "to log into ClassEdge with your Microsoft 365 account.")

        except Exception as exc:
            self.log(f"UNHANDLED ERROR: {exc}", "err")
        finally:
            self._busy = False

    # ── Login ─────────────────────────────────────────────────────────────────

    def cmd_login(self):
        if not is_setup_done():
            messagebox.showwarning("Not Set Up", "Please run First-Time Setup first.")
            return
        messagebox.showinfo(
            "Save Login Session",
            "A browser window will open.\n\n"
            "1. Log in with your HCCI Microsoft 365 account.\n"
            "2. Complete MFA if prompted.\n"
            "3. Once you reach the ClassEdge dashboard,\n"
            "   the session saves automatically.\n\n"
            "Click OK to open the browser now.",
        )
        self._run("Save Login Session",
                  [str(PYTHON), str(APP_DIR / "lms_login_setup.py")])

    # ── Schedule ──────────────────────────────────────────────────────────────

    def cmd_schedule(self):
        if not is_setup_done():
            messagebox.showwarning("Not Set Up", "Please run First-Time Setup first.")
            return
        if not has_session():
            messagebox.showwarning("No Session",
                "auth.json not found.\nRun Save Login Session first.")
            return
        self._run("Extract Schedule",
                  [str(PYTHON), str(APP_DIR / "extract_schedule_web.py")])

    # ── Lesson folders ────────────────────────────────────────────────────────

    def cmd_folders(self):
        if not is_setup_done():
            messagebox.showwarning("Not Set Up", "Please run First-Time Setup first.")
            return
        if not has_schedule():
            messagebox.showwarning("No Schedule",
                "schedule.json not found.\nRun Extract Schedule first.")
            return
        self._run("Create Lesson Folders",
                  [str(PYTHON), str(APP_DIR / "create_lesson_folders.py")])

    # ── Upload lessons ────────────────────────────────────────────────────────

    def cmd_upload(self):
        if not is_setup_done():
            messagebox.showwarning("Not Set Up", "Please run First-Time Setup first.")
            return
        if not has_session():
            messagebox.showwarning("No Session",
                "auth.json not found.\nRun Save Login Session first.")
            return

        win = tk.Toplevel(self)
        win.title("Upload Lessons")
        win.geometry("340x220")
        win.resizable(False, False)
        win.configure(bg=C_BG)
        win.grab_set()

        tk.Label(win, text="Upload Lessons", bg=C_BG, fg=C_DARK,
                 font=("Segoe UI", 12, "bold"), pady=14).pack()
        tk.Label(win, text="Which term are you uploading for?",
                 bg=C_BG, fg=C_DARK, font=("Segoe UI", 10)).pack()

        term_var = tk.StringVar(value="auto")
        frame = tk.Frame(win, bg=C_BG, pady=8)
        frame.pack()
        for val, lbl in [("midterm", "Midterm"),
                          ("final",   "Final Term"),
                          ("auto",    "Auto-detect (use ClassEdge default)")]:
            tk.Radiobutton(
                frame, text=lbl, variable=term_var, value=val,
                bg=C_BG, fg=C_DARK, activebackground=C_BG,
                font=("Segoe UI", 10), selectcolor=C_BG,
            ).pack(anchor="w", padx=20)

        def go():
            t = term_var.get()
            win.destroy()
            self._run("Upload Lessons",
                      [str(PYTHON), str(APP_DIR / "upload_lessons.py"),
                       "--term", t])

        tk.Button(win, text="Start Upload →", command=go,
                  bg=C_ACCENT, fg="white", relief="flat",
                  font=("Segoe UI", 10, "bold"),
                  padx=18, pady=7, cursor="hand2").pack(pady=12)

    # ── Manual Start Class ──────────────────────────────────────────────────────

    def cmd_start_now(self):
        if not is_setup_done():
            messagebox.showwarning("Not Set Up", "Please run First-Time Setup first.")
            return
        if not has_session():
            messagebox.showwarning("No Session",
                "auth.json not found.\nRun Save Login Session first.")
            return
        if not has_schedule():
            messagebox.showwarning("No Schedule",
                "schedule.json not found.\nRun Extract Schedule first.")
            return

        # Load schedule entries
        try:
            import json as _json
            with open(APP_DIR / "schedule.json", encoding="utf-8") as f:
                entries = _json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read schedule.json:\n{e}")
            return

        DAY_NAMES = {"MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday",
                     "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday"}

        # Build display labels
        labels = [
            f"{DAY_NAMES.get(e['day'], e['day'])}  {e['trigger_time']}  —  {e['subject']} ({e['kind']})"
            for e in entries
        ]

        win = tk.Toplevel(self)
        win.title("Start Class Now")
        win.geometry("480x220")
        win.configure(bg=C_BG)
        win.resizable(False, False)
        win.grab_set()

        tk.Label(win, text="▶  Start Class Now", bg=C_BG, fg=C_DARK,
                 font=("Segoe UI", 11, "bold"), pady=12).pack(fill="x", padx=18)
        tk.Label(win, text="Select a class to start immediately:",
                 bg=C_BG, fg=C_DIM, font=("Segoe UI", 9)).pack(anchor="w", padx=18)

        selected = tk.StringVar(value=labels[0])
        cb = ttk.Combobox(win, textvariable=selected, values=labels,
                          state="readonly", font=("Segoe UI", 9), width=52)
        cb.pack(padx=18, pady=10, fill="x")

        def go():
            idx = labels.index(selected.get())
            entry = entries[idx]
            win.destroy()
            self._run(
                f"Start Class — {entry['subject']} ({entry['kind']})",
                [str(PYTHON), str(APP_DIR / "lms_start_class.py"),
                 "--url", entry["url"]],  # no --scheduled-time → skips deadline
            )

        btn_frame = tk.Frame(win, bg=C_BG)
        btn_frame.pack(pady=6)
        tk.Button(btn_frame, text="Start Class →", command=go,
                  bg=C_ACCENT, fg="white", relief="flat",
                  font=("Segoe UI", 10, "bold"),
                  padx=18, pady=7, cursor="hand2").pack(side="left", padx=6)
        tk.Button(btn_frame, text="Cancel", command=win.destroy,
                  bg=C_BG, fg=C_DIM, relief="flat",
                  font=("Segoe UI", 9),
                  padx=12, pady=7, cursor="hand2").pack(side="left")

    # ── Task Scheduler ────────────────────────────────────────────────────────

    def cmd_tasks(self):
        if not is_setup_done():
            messagebox.showwarning("Not Set Up", "Please run First-Time Setup first.")
            return
        if not has_schedule():
            messagebox.showwarning("No Schedule",
                "schedule.json not found.\nRun Extract Schedule first.")
            return
        self._run("Register Tasks",
                  [str(PYTHON), str(APP_DIR / "setup_tasks.py")])

    def cmd_list_tasks(self):
        if not is_setup_done():
            messagebox.showwarning("Not Set Up", "Please run First-Time Setup first.")
            return
        self._run("List Tasks",
                  [str(PYTHON), str(APP_DIR / "setup_tasks.py"), "--list"])

    def cmd_delete_tasks(self):
        if not is_setup_done():
            messagebox.showwarning("Not Set Up", "Please run First-Time Setup first.")
            return
        if not messagebox.askyesno(
            "Remove All Tasks",
            "This will remove all ClassEdge tasks from\nWindows Task Scheduler.\n\n"
            "You can re-register them any time.\n\nContinue?",
        ):
            return
        self._run("Remove Tasks",
                  [str(PYTHON), str(APP_DIR / "setup_tasks.py"), "--delete"])

    # ── Open folders ──────────────────────────────────────────────────────────

    def cmd_open_dir(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(APP_DIR))

    def cmd_open_lessons(self):
        lessons = APP_DIR / "lessons"
        if not lessons.exists():
            messagebox.showinfo(
                "Lessons Folder",
                "The lessons folder does not exist yet.\n\n"
                "Run Create Lesson Folders first to generate it.",
            )
            return
        os.startfile(str(lessons))

    def cmd_open_errors(self):
        errors = APP_DIR / "errors"
        if not errors.exists():
            messagebox.showinfo(
                "Errors Folder",
                "No errors folder found.\n\n"
                "It is created automatically when an upload fails.",
            )
            return
        os.startfile(str(errors))

    def cmd_view_log(self):
        log_file = APP_DIR / "start_class.log"
        if not log_file.exists():
            messagebox.showinfo(
                "Start Class Log",
                "No log file found yet.\n\n"
                "Logs are created after the first automated Start Class runs.",
            )
            return

        win = tk.Toplevel(self)
        win.title("Start Class Log")
        win.geometry("860x580")
        win.configure(bg=C_BG)
        win.resizable(True, True)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(win, bg=C_SIDEBAR, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="📜  Start Class Log", bg=C_SIDEBAR, fg="white",
                 font=("Segoe UI", 11, "bold"), padx=14).pack(side="left")

        btn_frame = tk.Frame(hdr, bg=C_SIDEBAR)
        btn_frame.pack(side="right", padx=10)

        # ── Filter bar ────────────────────────────────────────────────────────
        fbar = tk.Frame(win, bg="#1a2332", pady=5)
        fbar.pack(fill="x")

        tk.Label(fbar, text="Show:", bg="#1a2332", fg=C_DIM,
                 font=("Segoe UI", 8)).pack(side="left", padx=(12, 4))

        filter_var = tk.StringVar(value="All")
        FILTERS = ["All", "✅ Success", "❌ Error", "⚠️ Warning / Skipped", "ℹ️ Info"]
        filter_cb = ttk.Combobox(fbar, textvariable=filter_var, values=FILTERS,
                                 state="readonly", font=("Segoe UI", 8), width=22)
        filter_cb.pack(side="left", padx=4)

        # Stats labels (populated by _load)
        stats_var = tk.StringVar(value="")
        tk.Label(fbar, textvariable=stats_var, bg="#1a2332", fg=C_DIM,
                 font=("Segoe UI", 8)).pack(side="left", padx=16)

        # ── Log text area ─────────────────────────────────────────────────────
        txt = scrolledtext.ScrolledText(
            win, font=("Consolas", 9), bg="#0d1117", fg="#c9d1d9",
            relief="flat", wrap="none", state="normal",
            pady=6, padx=8,
        )
        txt.pack(fill="both", expand=True)

        # colour / style tags
        txt.tag_config("date_hdr", foreground="#58a6ff", font=("Segoe UI", 9, "bold"),
                       spacing1=10, spacing3=2)
        txt.tag_config("date_sep", foreground="#30363d")
        txt.tag_config("ok",       foreground="#3fb950", font=("Consolas", 9, "bold"))
        txt.tag_config("err",      foreground="#f85149", font=("Consolas", 9, "bold"))
        txt.tag_config("warn",     foreground="#d29922")
        txt.tag_config("info",     foreground="#79c0ff")
        txt.tag_config("ts",       foreground="#8b949e")
        txt.tag_config("icon",     foreground="#c9d1d9")
        txt.tag_config("dim",      foreground="#484f58")

        ICONS = {
            "ok":   "✅",
            "err":  "❌",
            "warn": "⚠️ ",
            "info": "ℹ️ ",
        }

        def _classify(rest: str) -> str:
            u = rest.upper()
            if "SUCCESS" in u:                    return "ok"
            if "ERROR" in u or "UNHANDLED" in u:  return "err"
            if "WARNING" in u or "SKIPPED" in u:  return "warn"
            return "info"

        def _load():
            try:
                raw = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception as e:
                raw = [f"Could not read log: {e}"]

            # Parse into structured entries
            import re as _re
            entries = []
            pat = _re.compile(r"^\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\] (.*)$")
            for line in raw:
                m = pat.match(line)
                if m:
                    entries.append({"date": m.group(1), "time": m.group(2),
                                    "msg": m.group(3), "raw": line})
                else:
                    entries.append({"date": None, "time": None,
                                    "msg": line, "raw": line})

            # Count stats
            counts = {"ok": 0, "err": 0, "warn": 0, "info": 0}
            for e in entries:
                if e["date"]:
                    counts[_classify(e["msg"])] += 1
            stats_var.set(
                f"✅ {counts['ok']}  ❌ {counts['err']}  ⚠️ {counts['warn']}  "
                f"ℹ️ {counts['info']}  │  {len([e for e in entries if e['date']])} total entries"
            )

            # Apply filter
            fval = filter_var.get()
            filter_map = {
                "✅ Success":             "ok",
                "❌ Error":               "err",
                "⚠️ Warning / Skipped":  "warn",
                "ℹ️ Info":               "info",
            }
            only = filter_map.get(fval)  # None = show all

            txt.configure(state="normal")
            txt.delete("1.0", "end")

            current_date = None
            for e in entries:
                if not e["date"]:
                    txt.insert("end", e["raw"] + "\n", "dim")
                    continue

                kind = _classify(e["msg"])
                if only and kind != only:
                    continue

                # Date group header
                if e["date"] != current_date:
                    current_date = e["date"]
                    from datetime import datetime as _dt
                    try:
                        d = _dt.strptime(current_date, "%Y-%m-%d")
                        label = d.strftime("%A, %B %d, %Y")
                    except Exception:
                        label = current_date
                    txt.insert("end", f"\n  📅  {label}\n", "date_hdr")
                    txt.insert("end", "  " + "─" * 72 + "\n", "date_sep")

                icon = ICONS[kind]
                txt.insert("end", f"  {icon} ", "icon")
                txt.insert("end", e["time"] + "  ", "ts")
                txt.insert("end", e["msg"] + "\n", kind)

            txt.configure(state="disabled")
            txt.see("end")

        _load()
        filter_cb.bind("<<ComboboxSelected>>", lambda _: _load())

        def _refresh():
            _load()

        def _clear():
            if messagebox.askyesno("Clear Log",
                                   "Delete all log entries?\nThis cannot be undone."):
                log_file.write_text("", encoding="utf-8")
                _load()

        tk.Button(btn_frame, text="↻ Refresh", command=_refresh,
                  bg=C_ACCENT, fg="white", relief="flat",
                  font=("Segoe UI", 8), padx=10, pady=3, cursor="hand2").pack(side="left", padx=4)
        tk.Button(btn_frame, text="🗑 Clear", command=_clear,
                  bg="#c0392b", fg="white", relief="flat",
                  font=("Segoe UI", 8), padx=10, pady=3, cursor="hand2").pack(side="left", padx=4)


    # ── How-To Guide ──────────────────────────────────────────────────────────

    def cmd_howto(self):
        win = tk.Toplevel(self)
        win.title(f"How-To Guide  —  ClassEdge LMS v{VERSION}")
        win.geometry("680x580")
        win.configure(bg=C_BG)
        win.resizable(True, True)

        tk.Label(
            win, text="How-To Guide", bg=C_BG, fg=C_DARK,
            font=("Segoe UI", 13, "bold"), pady=12
        ).pack(fill="x", padx=18)
        tk.Label(
            win, text=f"ClassEdge LMS Automation  ·  v{VERSION}  ·  HCCI",
            bg=C_BG, fg=C_DIM, font=("Segoe UI", 8)
        ).pack(fill="x", padx=18)

        frame = tk.Frame(win, bg=C_BG)
        frame.pack(fill="both", expand=True, padx=12, pady=(8, 12))

        txt = scrolledtext.ScrolledText(
            frame, font=("Segoe UI", 9), bg="#f0f4fa", fg=C_DARK,
            relief="flat", wrap="word", state="normal",
            pady=8, padx=10, spacing1=2, spacing3=4,
        )
        txt.pack(fill="both", expand=True)

        txt.tag_config("h1",  font=("Segoe UI", 11, "bold"), foreground=C_ACCENT, spacing1=10)
        txt.tag_config("h2",  font=("Segoe UI",  9, "bold"), foreground=C_DARK,   spacing1=8)
        txt.tag_config("num", font=("Segoe UI",  9, "bold"), foreground=C_ACCENT)
        txt.tag_config("tip", font=("Segoe UI",  8, "italic"), foreground="#5a7a9a")
        txt.tag_config("code",font=("Consolas",  8),           foreground="#c0392b", background="#f8f0f0")

        def h1(t):  txt.insert("end", t + "\n", "h1")
        def h2(t):  txt.insert("end", t + "\n", "h2")
        def p(t):   txt.insert("end", t + "\n")
        def tip(t): txt.insert("end", "💡 " + t + "\n", "tip")
        def nl():   txt.insert("end", "\n")

        h1("🚀  First-Time Setup  (Do this once)")
        for i, step in enumerate([
            ("⚙  First-Time Setup",  "Click this button first. It installs Python packages and\n"
                                      "    the Chromium browser needed to automate ClassEdge."),
            ("🔑  Save Login Session","A browser window opens. Log in with your HCCI Microsoft 365\n"
                                      "    account (including MFA). The session saves automatically\n"
                                      "    once you reach your ClassEdge dashboard."),
            ("📅  Extract Schedule",  "The app reads your ClassEdge Subject List and builds a\n"
                                      "    schedule.json with all your classes and their times."),
            ("🗓  Register Tasks",     "Registers Windows Task Scheduler tasks so the app\n"
                                      "    automatically clicks \"Start Class\" 15 minutes before\n"
                                      "    each of your classes — even if you forget."),
        ], 1):
            txt.insert("end", f"  {i}. ", "num")
            txt.insert("end", f"{step[0]}\n", "h2")
            p(f"     {step[1]}")
            nl()

        h1("📤  Uploading Lesson Files")
        for i, step in enumerate([
            ("📁  Create Lesson Folders",
             "Creates a lessons/ folder with one subfolder per subject\n"
             "    (e.g. \"Computer Programming 2 (LAB)/\"). Run this once\n"
             "    after extracting your schedule."),
            ("Add your files",
             "Open the Lessons Folder (📂 button) and drop your PDF /\n"
             "    PPTX / DOCX files into the correct subject subfolder.\n"
             "    Name files like:  01 - HTML Basics.pdf\n"
             "                      Week 3 - Variables.pptx"),
            ("📤  Upload Lessons",
             "Choose Midterm or Final Term and click Start Upload.\n"
             "    Each file is uploaded to ALL sections of that subject\n"
             "    automatically. Already-uploaded files are skipped."),
        ], 1):
            txt.insert("end", f"  {i}. ", "num")
            txt.insert("end", f"{step[0]}\n", "h2")
            p(f"     {step[1]}")
            nl()

        h1("🔁  Day-to-Day Use")
        p("  The Task Scheduler handles Start Class automatically.\n"
          "  Just make sure your computer is on before each class.\n")
        p("  If your session expires (login errors), click:\n")
        txt.insert("end", "  🔑 Save Login Session", "num")
        p("  — then log in again.\n")

        h1("📁  File Naming Tips")
        for pattern, example in [
            ("01 - Lesson Title.pdf",      "→  title = \"Lesson Title\",  week 1"),
            ("Week 3 - Topic Name.pptx",   "→  title = \"Topic Name\",   week 3"),
            ("My Lesson.pdf",              "→  title = \"My Lesson\",    no week number"),
        ]:
            txt.insert("end", f"  {pattern}", "code")
            p(f"  {example}")
        nl()
        tip("All sections of a subject share one folder — upload once, reaches all classes.")
        tip("Files already uploaded are tracked and will never be re-uploaded by accident.")
        nl()

        h1("❓  Troubleshooting")
        for q, a in [
            ("Browser closes before I can log in",
             "This is fixed in v1.1+. Make sure you are on the latest version."),
            ("Upload fails / unclear result",
             "Check the errors/ folder inside the App Folder for screenshots\n"
             "     showing exactly what went wrong."),
            ("Tasks not firing at class time",
             "Ensure your PC is powered on and not in sleep mode before class.\n"
             "     Tasks use \"Run as soon as possible\" so they catch up after sleep."),
            ("Session expired",
             "Click 🔑 Save Login Session and log in again.\n"
             "     Sessions typically last several days to weeks."),
        ]:
            txt.insert("end", f"  Q: {q}\n", "h2")
            p(f"     A: {a}")
            nl()

        txt.configure(state="disabled")

        tk.Button(
            win, text="Close", command=win.destroy,
            bg=C_ACCENT, fg="white", relief="flat",
            font=("Segoe UI", 9, "bold"), padx=20, pady=6, cursor="hand2"
        ).pack(pady=(0, 12))


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
