"""Shared PyInstaller configuration for the EDLD binary.

Imported by ``edld.spec``.  Anything that differs between platforms is a
parameter rather than a fork of the spec, so the three official binaries are
produced from one description.

On excluding Qt modules
-----------------------
PySide6 ships a very large surface: WebEngine alone is hundreds of megabytes.
EDLD uses QtCore, QtGui, QtWidgets and QtSvg (the funding icons are SVG), so
everything else is excluded explicitly.  This is a size decision, not a
licensing one.

On the Qt licence
-----------------
Qt is LGPL v3 and is never statically linked; PyInstaller bundles it as
ordinary shared libraries loaded at runtime.  The licence texts are added to
DATA_FILES below so a copy travels inside every binary, and the relinking
requirement is met by publishing the complete source.  See docs/LICENSING.md.
"""

from __future__ import annotations

from pathlib import Path

#: Repository root, derived from this file's own location.  PyInstaller
#: injects SPECPATH into the spec's namespace only, not into modules the
#: spec imports, so it cannot be relied on here.
ROOT = Path(__file__).resolve().parent.parent

#: The version file is bundled so a frozen binary can report its version.
#: EDLD keeps it at core/version, and core/state.py reads it relative to the
#: core package — so it has to land in a "core" subdirectory of the bundle,
#: not at the root.
VERSION_FILE = ROOT / "core" / "version"

#: Files shipped alongside the code inside the bundle.
DATA_FILES = [
    (str(VERSION_FILE), "core"),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "THIRD-PARTY-NOTICES.md"), "."),
    (str(ROOT / "licenses"), "licenses"),
    (str(ROOT / "gui" / "resources"), "gui/resources"),
    (str(ROOT / ".github" / "FUNDING.yml"), ".github"),
    (str(ROOT / "packaging" / "icons" / "edld.png"), "packaging/icons"),
    (str(ROOT / "themes"), "themes"),
    (str(ROOT / "example.config.toml"), "."),
    (str(ROOT / "example.layout.json"), "."),
    # The component sources ship as data as well as compiled code.
    # core/plugin_loader.py discovers components by globbing this directory and
    # loads each by file path so it gets its own namespace and a sandboxed
    # open(); that needs real files on disk. Without this entry the binary
    # builds, starts, and shows a dashboard with every window empty.
    (str(ROOT / "components"), "components"),
]


def _ca_bundle() -> list[tuple[str, str]]:
    """Ship certifi's CA bundle so HTTPS works in the packaged build.

    The binary carries its own OpenSSL, built with the build machine's
    certificate paths compiled in. Those paths do not exist on most target
    machines, so verification fails everywhere and every network feature stops
    working silently. core/certs.py points OpenSSL at this copy at startup.
    """
    try:
        import certifi
        return [(certifi.where(), "certs")]
    except Exception:
        return []


DATA_FILES += _ca_bundle()

#: Qt modules EDLD never touches.  Excluding them roughly halves the binary
#: and removes components with their own licensing questions.
QT_EXCLUDES = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
]

#: Other heavyweight packages that may be present in a build environment
#: but are never imported by EDLD.
OTHER_EXCLUDES = [
    "IPython",
    "matplotlib",
    "numpy",
    "pandas",
    "pytest",
    "scipy",
    "setuptools",
    "tkinter",
]

EXCLUDES = QT_EXCLUDES + OTHER_EXCLUDES

#: Components are discovered at runtime by core/plugin_loader.py walking the
#: components/ directory, so PyInstaller's static analysis cannot see any of
#: them.  Every one has to be named here or the frozen binary loads a
#: dashboard with no data in it — the single most likely way to ship a broken
#: build, and the reason the workflow smoke-tests the artefact.
def _component_imports() -> list[str]:
    comp_dir = ROOT / "components"
    return [
        f"components.{p.stem}"
        for p in sorted(comp_dir.glob("*.py"))
        if p.stem != "__init__"
    ]


def _block_imports() -> list[str]:
    """TUI and GUI blocks, both resolved dynamically by name."""
    out: list[str] = []
    for pkg in ("tui/blocks", "gui/blocks"):
        d = ROOT / pkg
        if not d.is_dir():
            continue
        out += [
            f"{pkg.replace('/', '.')}.{p.stem}"
            for p in sorted(d.glob("*.py"))
            if p.stem != "__init__"
        ]
    return out


def _textual_submodules() -> list[str]:
    """Every submodule of Textual, collected explicitly.

    ``textual.widgets.__init__`` resolves its widgets lazily through a module
    level ``__getattr__`` that calls ``importlib.import_module`` on a name
    built at runtime. PyInstaller's static analysis cannot see through that,
    so it bundles only the handful of submodules something imports directly
    and silently drops the rest — the binary then dies on first use with
    ``No module named 'textual.widgets._tab_pane'`` or similar.

    Collecting the whole package costs a little size and removes the entire
    class of failure, including for widgets a future block might use.
    """
    try:
        from PyInstaller.utils.hooks import collect_submodules
        return collect_submodules("textual")
    except Exception:
        # Textual absent from the build environment: a GUI-only build. The
        # terminal front end will not work in that binary either way.
        return []


HIDDEN_IMPORTS = (
    _component_imports()
    + _block_imports()
    + _textual_submodules()
    + [
        "core.palette",
        "gui.app",
        "gui.about",
        "gui.funding",
        "gui.markup",
        "gui.preferences",
        "gui.search_dialog",
        "gui.theme",
        "tui.app",
        "tui.theme",
        # Optional at runtime; present when the user installed them.
        "discord_webhook",
        # psutil is imported inside a try/except so a source install without it
        # still runs. That makes it look optional to PyInstaller's static
        # analysis, which may then leave it out of the bundle even when it is
        # installed in the build environment. Naming it here is what guarantees
        # the shipped binary keeps game-process detection and session
        # management.
        "psutil",
    ]
)


def analysis_kwargs(extra_hidden: list[str] | None = None) -> dict:
    """Return the keyword arguments for a PyInstaller ``Analysis``."""
    return {
        "scripts": [str(ROOT / "edld.py")],
        "pathex": [str(ROOT)],
        "binaries": [],
        "datas": [d for d in DATA_FILES if Path(d[0]).exists()],
        "hiddenimports": HIDDEN_IMPORTS + list(extra_hidden or []),
        "hookspath": [],
        "hooksconfig": {},
        "runtime_hooks": [],
        "excludes": EXCLUDES,
        "noarchive": False,
        "optimize": 0,
    }
