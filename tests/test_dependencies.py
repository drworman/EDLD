"""
tests/test_dependencies.py — requirements files say what the code imports.

Both had drifted.  requirements.txt declared cryptography, which nothing
imports, and not Rich, which the terminal blocks import directly;
requirements-dev.txt declared Pillow for an icon script that does not exist,
and not pytest or pyflakes, which the tests need.  These derive what must be
declared from the imports themselves, in both directions.

It also checks the build still carries every bundled package's licence text:
the binaries shipped the code of a dozen MIT, BSD and Apache packages and none
of their licences, which is the one condition those licences set.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Import name -> distribution name, where they differ.
IMPORT_TO_DIST = {
    "discord_webhook": "discord-webhook",
    "PyInstaller":     "pyinstaller",
    "PySide6":         "pyside6",
}

#: Runtime imports declared somewhere other than requirements.txt, and why.
RUNTIME_ELSEWHERE = {
    # C extensions; installed from the distro for source runs (see the
    # comment at the top of requirements.txt) and from requirements-dev.txt
    # for builds.
    "psutil",
}

_LOCAL = {p.name for p in ROOT.iterdir() if p.is_dir()} | {p.stem for p in ROOT.glob("*.py")}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared(path: Path) -> set[str]:
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("-r "):
            out |= _declared(path.parent / line[3:].strip())
        elif line and not line.startswith("-"):
            out.add(_norm(re.split(r"[\s<>=!~;\[]", line, maxsplit=1)[0]))
    return out


def _imports(dirs: list[str]) -> set[str]:
    found: set[str] = set()
    for d in dirs:
        base = ROOT / d
        files = [base] if base.suffix == ".py" else list(base.rglob("*.py"))
        for f in files:
            if "__pycache__" in f.parts:
                continue
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                for n in names:
                    top = n.split(".")[0]
                    if top not in sys.stdlib_module_names and top not in _LOCAL:
                        found.add(top)
    return found


RUNTIME_DIRS = ["core", "components", "gui", "tui", "edld.py"]


def _dist(import_name: str) -> str:
    return _norm(IMPORT_TO_DIST.get(import_name, import_name))


@pytest.mark.parametrize("name", sorted(_imports(RUNTIME_DIRS) - RUNTIME_ELSEWHERE))
def test_every_runtime_import_is_in_requirements(name):
    assert _dist(name) in _declared(ROOT / "requirements.txt"), (
        f"{name} is imported by EDLD but not declared in requirements.txt")


def test_psutil_is_still_declared_for_builds():
    assert "psutil" in _declared(ROOT / "requirements-dev.txt")


def test_pypa_packaging_is_declared_for_builds():
    """``packaging`` is also this repo's directory name, so the import scan
    below cannot see build_common.py's use of PyPA's package; checked here."""
    src = (ROOT / "packaging" / "build_common.py").read_text(encoding="utf-8")
    assert "from packaging.requirements import" in src
    assert "packaging" in _declared(ROOT / "requirements-dev.txt")


@pytest.mark.parametrize("name", sorted(_imports(["tests", "packaging"])))
def test_every_test_and_build_import_is_in_requirements_dev(name):
    # Imported by file name from a sibling directory — the spec's
    # build_common, the sheet builders, one test reusing another's harness.
    if any((ROOT / d / f"{name}.py").is_file() for d in ("packaging", "sheets", "tests")):
        return
    assert _dist(name) in _declared(ROOT / "requirements-dev.txt"), (
        f"{name} is imported by tests or packaging but not declared in "
        f"requirements-dev.txt")


@pytest.mark.parametrize("dist", sorted(_declared(ROOT / "requirements.txt")))
def test_nothing_in_requirements_is_dead(dist):
    """cryptography sat here for a token store that never used it."""
    used = {_dist(n) for n in _imports(RUNTIME_DIRS)}
    assert dist in used, f"{dist} is declared in requirements.txt but never imported"


# ── Licence texts travel with the binary ──────────────────────────────────────

def _build_common():
    sys.path.insert(0, str(ROOT / "packaging"))
    try:
        import build_common
        return build_common
    finally:
        sys.path.pop(0)


def test_the_build_collects_a_licence_for_every_bundled_package():
    pytest.importorskip("packaging.requirements")
    bc = _build_common()
    files = bc.licence_files()                   # SystemExit if any is missing
    dests = {d for _, d in files}
    for dist in bc.bundled_distributions():
        if dist in bc._LICENCE_EXEMPT:
            continue
        assert any(d.startswith(f"licenses/third-party/{dist}-") for d in dests), dist


def test_the_build_names_miniaudio_explicitly():
    """Each of these is invisible to PyInstaller's analysis: core.radio and
    miniaudio sit behind try/except, _miniaudio is imported by name, and
    _cffi_backend is imported from _miniaudio's C code.  Missing the last one
    built three binaries whose --selftest failed on every platform."""
    bc = _build_common()
    assert {"miniaudio", "_miniaudio", "_cffi_backend",
            "core.radio"} <= set(bc.HIDDEN_IMPORTS)


def test_the_dir_build_does_not_pass_onedir_beside_the_spec():
    """PyInstaller rejects -D/--onedir with a .spec; --dir failed before building."""
    script = (ROOT / "scripts" / "build_local.sh").read_text(encoding="utf-8")
    calls = [ln for ln in script.splitlines() if "PyInstaller packaging/edld.spec" in ln]
    assert calls and not any(re.search(r"\s(-D|--onedir|-F|--onefile)\b", c) for c in calls)
    assert "EDLD_ONEDIR" in (ROOT / "packaging" / "edld.spec").read_text(encoding="utf-8")
