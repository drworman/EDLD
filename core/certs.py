"""
core/certs.py — make HTTPS work in a packaged build.

A PyInstaller binary carries its own copy of OpenSSL, and that copy was
compiled on the build machine with the build machine's certificate paths baked
in. Those paths rarely exist on the machine the binary ends up running on:
Debian keeps its store in one place, Arch another, Fedora another again, and
macOS does not use an OpenSSL-style store at all. OpenSSL then finds no trust
anchors and every verification fails with

    [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate

The symptom is easy to misread, because nothing crashes. EDLD keeps running
and every network feature quietly stops: CAPI never returns a profile, so the
Commander window loses its squadron line and its ranks; EDDN, EDSM, EDAstro
and Inara silently stop uploading; Spansh searches return nothing. Each failure
is logged on its own line as an unremarkable warning, and none of them says
"none of this is going to work".

The fix is to ship a certificate bundle and point OpenSSL at it. Both are done
here: ``certifi``'s bundle is included in the binary by
``packaging/build_common.py``, and ``install()`` sets the environment variables
OpenSSL reads before anything opens a connection.

Running from source needs none of this — the system store is already correct —
so ``install()`` does nothing unless the process is frozen.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: Where build_common.py places the bundle inside the binary.
_BUNDLED_NAME = "cacert.pem"
_BUNDLED_DIR = "certs"


def _candidates() -> list[Path]:
    """Possible locations for the bundled certificate file, best first."""
    out: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        root = Path(meipass)
        out.append(root / _BUNDLED_DIR / _BUNDLED_NAME)
        out.append(root / _BUNDLED_NAME)
        # certifi's own hook may have placed it here instead.
        out.append(root / "certifi" / _BUNDLED_NAME)
    return out


def bundled_path() -> Path | None:
    """Return the bundled CA file if this is a frozen build and it exists."""
    if not getattr(sys, "frozen", False):
        return None
    for path in _candidates():
        if path.is_file():
            return path
    return None


def install() -> str | None:
    """Point OpenSSL at the bundled CA store. Returns the path used, or None.

    A user who has deliberately set ``SSL_CERT_FILE`` — to trust a corporate
    proxy's root, for instance — keeps their setting; theirs is more likely to
    be right for their network than ours.
    """
    if not getattr(sys, "frozen", False):
        return None

    existing = os.environ.get("SSL_CERT_FILE")
    if existing and Path(existing).is_file():
        return existing

    path = bundled_path()
    if path is None:
        return None

    resolved = str(path)
    os.environ["SSL_CERT_FILE"] = resolved
    # requests and anything else built on urllib3 read this one instead.
    os.environ.setdefault("REQUESTS_CA_BUNDLE", resolved)
    # SSL_CERT_DIR is consulted alongside SSL_CERT_FILE; pointing it at the
    # bundle's directory stops OpenSSL falling back to a build-machine path
    # that does not exist here.
    os.environ.setdefault("SSL_CERT_DIR", str(path.parent))
    return resolved


def diagnose() -> str:
    """One line describing where certificate verification will look.

    Written to the diagnostic log at startup. When somebody reports that
    uploads stopped working, this is the line that answers it immediately
    instead of after a round of guessing.
    """
    import ssl

    if not getattr(sys, "frozen", False):
        paths = ssl.get_default_verify_paths()
        return (f"TLS: system trust store "
                f"(cafile={paths.cafile}, capath={paths.capath})")

    active = os.environ.get("SSL_CERT_FILE")
    if active and Path(active).is_file():
        return f"TLS: bundled trust store at {active}"
    paths = ssl.get_default_verify_paths()
    return (
        "TLS: no bundled trust store found — HTTPS will likely fail with "
        "CERTIFICATE_VERIFY_FAILED and every network feature (CAPI, EDDN, "
        "EDSM, EDAstro, Inara, Spansh) will be silently unavailable. "
        f"OpenSSL default: cafile={paths.cafile}, capath={paths.capath}"
    )
