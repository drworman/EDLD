# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the EDLD binary.

Build with:
    pyinstaller packaging/edld.spec --noconfirm --clean

One binary carries all three interfaces.  On Linux it is launched with
--tui (default), --terminal or --gui; on Windows and macOS the GUI is the
practical entry point, but the terminal modes remain available to anyone who
runs the executable from a shell.

The console setting is the one genuine platform difference.  A Windows GUI
build with console=True pops a terminal window behind the dashboard, and one
with console=False cannot write to stdout at all — which would break
--terminal.  EDLD ships console=True on Linux and macOS, where a terminal
launch is normal and a desktop launcher hides the console anyway, and
console=False on Windows, where src/win_console.py reattaches stdout on demand
for the terminal modes.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH)))
from build_common import ROOT, VERSION_FILE, analysis_kwargs  # noqa: E402

APP_NAME = "EDLD"
ICON = ROOT / "packaging" / "icons" / "edld.ico"
ICNS = ROOT / "packaging" / "icons" / "edld.icns"

a = Analysis(**analysis_kwargs())
pyz = PYZ(a.pure)

icon = None
if sys.platform == "win32" and ICON.is_file():
    icon = str(ICON)
elif sys.platform == "darwin" and ICNS.is_file():
    icon = str(ICNS)

# See the module docstring: Windows is windowed so the GUI has no stray
# console; the other two keep a console so --terminal and --tui work when the
# binary is run from a shell.
_console = sys.platform != "win32"

# One file by default, as released.  EDLD_ONEDIR=1 builds the directory layout
# instead, for inspecting what went into the bundle.  It has to be chosen here:
# PyInstaller refuses --onedir/--onefile on the command line when given a spec,
# which is how scripts/build_local.sh --dir used to fail before building
# anything.
_onedir = os.environ.get("EDLD_ONEDIR") == "1"

# Onefile packs binaries and data into the executable; onedir leaves them for
# COLLECT to lay out beside it.
_packed = [] if _onedir else [a.binaries, a.datas]

exe = EXE(
    pyz,
    a.scripts,
    *_packed,
    [],
    exclude_binaries=_onedir,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX corrupts signed Qt libraries on Windows
    runtime_tmpdir=None,
    console=_console,
    # A windowed build that raises during startup shows the traceback in a
    # modal dialog and waits for someone to dismiss it. On a CI runner nobody
    # ever does, so the process sits there until the job is cancelled — a crash
    # that presents as a hang, with the real error hidden inside a window no
    # one can see. Suppressing the dialog turns that back into a normal
    # non-zero exit with the traceback on stderr, where the smoke test and the
    # logs can both see it.
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

if _onedir:
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
                   name=APP_NAME)

if sys.platform == "darwin" and not _onedir:
    app = BUNDLE(
        exe,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="com.drworman.edld",
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": "ED Live Dashboard",
            "CFBundleShortVersionString": VERSION_FILE.read_text().strip(),
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": (
                "MIT licensed. Uses Qt for Python under the LGPL v3."
            ),
        },
    )
