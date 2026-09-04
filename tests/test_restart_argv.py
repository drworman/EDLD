"""
tests/test_restart_argv.py — guard the process-restart argv construction.

Background
----------
Preferences restarts the process with ``os.execv`` when a ⚠ setting changes
(theme, journal folder, the Data tab's EDDN/EDSM/EDAstro toggles, window
layout).  ``execv`` takes the new argv *including* argv[0], and what must be
prepended differs between a source run and a frozen build:

  source  — sys.executable is the interpreter, launch_argv[0] is the script
  frozen  — sys.executable *is* the program, and so is launch_argv[0]

Prepending sys.executable to an unmodified launch_argv is correct only in the
source case.  In a frozen build it passed the old argv[0] through as a stray
positional; edld's parser defines no positionals, so argparse exited 2 before
logging was initialised and the restart vanished silently — presenting as a
crash to desktop with nothing in the log.

The parser is lifted out of edld.py rather than restated here, so new flags
are covered automatically and the test cannot drift from the real one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.core_api import CoreAPI  # noqa: E402


def _edld_parser():
    """Build edld.py's ArgumentParser without running the rest of the module.

    edld.py calls ``parser.parse_args()`` at module scope, so it cannot simply
    be imported.  Execute the source up to that call instead — this keeps the
    flag list mechanically in sync with the real entry point.
    """
    src = (ROOT / "edld.py").read_text(encoding="utf-8")
    marker = "args = parser.parse_args()"
    assert marker in src, "edld.py no longer calls parse_args() as expected"

    ns: dict = {"__file__": str(ROOT / "edld.py"), "__name__": "_edld_parser_probe"}
    exec(compile(src[: src.index(marker)], "edld.py", "exec"), ns)
    return ns["parser"]


def _core(launch_argv):
    core = CoreAPI.__new__(CoreAPI)
    core.launch_argv = list(launch_argv)
    return core


@pytest.fixture
def as_process(monkeypatch):
    """Present the interpreter as either a source run or a frozen build."""

    def _apply(*, frozen: bool, executable: str):
        monkeypatch.setattr(sys, "executable", executable, raising=False)
        if frozen:
            monkeypatch.setattr(sys, "frozen", True, raising=False)
        else:
            monkeypatch.delattr(sys, "frozen", raising=False)

    return _apply


# Every launch line that appears in real EDLD logs, plus a bare invocation.
LAUNCHES = [
    ["edld"],
    ["edld", "-p", "EDP1"],
    ["edld", "-p", "EDP1", "--gui"],
    ["edld", "-p", "EDP1", "--tui"],
    ["edld", "-p", "EDP1", "--trace"],
    ["edld", "-p", "EDP2", "--terminal"],
    ["edld", "-p", "EDP1", "--mode", "gui"],
]


def _child_argv(execv_args, *, frozen):
    """The sys.argv the restarted process will actually see."""
    # execv_args[0] becomes argv[0].  A frozen program is its own argv[0];
    # in a source run CPython drops the interpreter and argv starts at the
    # script path.
    return list(execv_args) if frozen else list(execv_args[1:])


@pytest.mark.parametrize("launch_argv", LAUNCHES)
@pytest.mark.parametrize(
    "frozen, executable, argv0",
    [
        (False, "/usr/bin/python3", "./edld.py"),
        (True, "/usr/local/bin/edld", None),   # invoked via PATH
        (True, "/usr/local/bin/edld", "/usr/local/bin/edld"),  # absolute path
    ],
    ids=["source", "frozen-path", "frozen-abs"],
)
def test_restart_argv_survives_reparse(as_process, launch_argv, frozen,
                                       executable, argv0):
    """A restart must reproduce the original options, not error out."""
    as_process(frozen=frozen, executable=executable)

    argv = list(launch_argv)
    if argv0 is not None:
        argv[0] = argv0

    execv_args = _core(argv).restart_argv()
    assert execv_args[0] == executable, "execv argv[0] must be the program to run"

    child = _child_argv(execv_args, frozen=frozen)
    parser = _edld_parser()

    # The real failure mode: argparse rejecting a stray positional and
    # calling sys.exit(2) before any logging exists.
    try:
        restarted = parser.parse_args(child[1:])
    except SystemExit as exc:  # pragma: no cover - only on regression
        pytest.fail(f"restart argv {child!r} rejected by parser (exit {exc.code})")

    original = parser.parse_args(argv[1:])
    assert vars(restarted) == vars(original), (
        "restarted process must carry the same options as the original"
    )


def test_frozen_restart_drops_stale_argv0(as_process):
    """Regression: the frozen build must not re-pass its own argv[0]."""
    as_process(frozen=True, executable="/usr/local/bin/edld")

    execv_args = _core(["edld", "-p", "EDP1", "--gui"]).restart_argv()

    assert execv_args == ["/usr/local/bin/edld", "-p", "EDP1", "--gui"]
    assert "edld" not in execv_args[1:], "old argv[0] leaked in as a positional"


def test_source_restart_keeps_script_path(as_process):
    """A source run must still hand the script path to the interpreter."""
    as_process(frozen=False, executable="/usr/bin/python3")

    execv_args = _core(["./edld.py", "-p", "EDP1", "--gui"]).restart_argv()

    assert execv_args == ["/usr/bin/python3", "./edld.py", "-p", "EDP1", "--gui"]


def test_restart_argv_falls_back_to_sys_argv(as_process, monkeypatch):
    """An empty launch_argv falls back to the live sys.argv."""
    as_process(frozen=False, executable="/usr/bin/python3")
    monkeypatch.setattr(sys, "argv", ["./edld.py", "-p", "EDP2"])

    assert _core([]).restart_argv() == ["/usr/bin/python3", "./edld.py", "-p", "EDP2"]
