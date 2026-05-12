# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['lms_app.py'],
    pathex=[],
    binaries=[],
    datas=[('classedge_lms.ico', '.'), ('lms_login_setup.py', '.'), ('lms_start_class.py', '.'), ('extract_schedule_web.py', '.'), ('extract_schedule.py', '.'), ('setup_tasks.py', '.'), ('create_lesson_folders.py', '.'), ('upload_lessons.py', '.')],
    hiddenimports=['tkinter', 'tkinter.scrolledtext', 'tkinter.ttk'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ClassEdge LMS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['classedge_lms.ico'],
)
