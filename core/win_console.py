"""Making standard output usable on Windows GUI builds.

The Windows EDLD binary is built with ``console=False`` so that launching
the desktop dashboard does not flash up a console window behind it. On
Windows that puts the executable in the GUI subsystem, where it starts
with no console attached and PyInstaller leaves ``sys.stdout`` and
``sys.stderr`` unusable. Anything printed then vanishes, and flushing at
exit raises ``OSError: [Errno 22] Invalid argument``.

That is fine for the desktop interface, which prints nothing once it is
up, but it breaks ``--terminal`` and ``--version`` completely: output
disappears whether the user is reading it in a terminal or a script is
capturing it. It also silences the startup banner and the error paths
that report a missing journal folder — the messages a confused user most
needs to see.

This module reconnects the streams. It handles both cases:

*Redirected* — ``EDLD.exe --version > out.txt``, or a shell
capturing the output. The shell has already given the process valid
standard handles, inherited at creation. They just need wrapping back
into Python file objects.

*Interactive* — the user runs the command in an existing console.
There are no inherited handles, so the process attaches to the console
of whichever process launched it and picks up the handles that creates.

Everything here is a no-op off Windows.
"""

from __future__ import annotations

import os
import sys

#: Passed to AttachConsole to mean "the console of my parent process".
ATTACH_PARENT_PROCESS = -1

#: GetStdHandle selectors.
STD_OUTPUT_HANDLE = -11
STD_ERROR_HANDLE = -12

#: What GetStdHandle returns when there is no handle to give.
INVALID_HANDLE_VALUE = 2**64 - 1


def _is_usable(stream: object) -> bool:
    """Return whether ``stream`` can actually be written to.

    A windowed PyInstaller build may leave the stream as ``None``, or as
    an object whose underlying descriptor is invalid; both must be
    replaced.
    """
    if stream is None:
        return False
    fileno = getattr(stream, "fileno", None)
    if fileno is None:
        return False
    try:
        return fileno() >= 0
    except (OSError, ValueError):
        return False


def enable_console_output() -> bool:
    """Reconnect ``sys.stdout`` and ``sys.stderr`` on Windows.

    Returns ``True`` when both streams are usable afterwards. Never
    raises: failing to attach a console must not stop the command from
    running, since its exit code may be all the caller needs.
    """
    if sys.platform != "win32":
        return True

    if _is_usable(sys.stdout) and _is_usable(sys.stderr):
        return True

    try:
        import ctypes
        import msvcrt
    except ImportError:  # pragma: no cover - Windows only
        return False

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Declared explicitly: a HANDLE is pointer-sized, and ctypes'
        # default int return type truncates it on 64-bit Windows.
        kernel32.GetStdHandle.argtypes = [ctypes.c_uint32]
        kernel32.GetStdHandle.restype = ctypes.c_void_p
        kernel32.AttachConsole.argtypes = [ctypes.c_uint32]
        kernel32.AttachConsole.restype = ctypes.c_bool

        def std_handle(selector: int) -> int | None:
            handle = kernel32.GetStdHandle(ctypes.c_uint32(selector & 0xFFFFFFFF))
            if not handle or handle == INVALID_HANDLE_VALUE:
                return None
            return handle

        # Ask what we already have *before* touching the console. This
        # order matters: AttachConsole replaces the process's standard
        # handles with the console's own. If the caller redirected our
        # output to a pipe or a file, we inherited a perfectly good
        # handle at creation, and attaching would send everything to the
        # console instead — leaving the caller's pipe empty, which is
        # exactly the failure this module exists to prevent.
        handles = {
            "stdout": std_handle(STD_OUTPUT_HANDLE),
            "stderr": std_handle(STD_ERROR_HANDLE),
        }

        if handles["stdout"] is None and handles["stderr"] is None:
            # Nothing inherited, so we were launched from a console
            # without redirection. Borrowing the parent's console is now
            # the only way to be seen. Failure is expected and fine when
            # the parent has no console either.
            kernel32.AttachConsole(ctypes.c_uint32(ATTACH_PARENT_PROCESS & 0xFFFFFFFF))
            handles = {
                "stdout": std_handle(STD_OUTPUT_HANDLE),
                "stderr": std_handle(STD_ERROR_HANDLE),
            }

        for name, handle in handles.items():
            if handle is None or _is_usable(getattr(sys, name, None)):
                continue
            descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY)
            stream = os.fdopen(
                descriptor,
                "w",
                buffering=1,
                encoding="utf-8",
                errors="replace",
                closefd=False,
            )
            setattr(sys, name, stream)
    except (OSError, ValueError, AttributeError):  # pragma: no cover
        return False

    return _is_usable(sys.stdout) and _is_usable(sys.stderr)


__all__ = [
    "ATTACH_PARENT_PROCESS",
    "STD_ERROR_HANDLE",
    "STD_OUTPUT_HANDLE",
    "enable_console_output",
]
