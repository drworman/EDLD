"""
core/server/pairing.py — pairing tickets, the device registry, pairing links.

Everything here is file-based on purpose.  ``edld --pair`` is usually run as a
second command while EDLD is already running as a service or a dashboard, and
the two processes share nothing but the data directory.  The pairing command
writes a ticket; the running server reads it when a device presents a code.
Revoking a device is an edit to ``devices.json``, which the server notices on
its next connection.  No socket, pipe or signal is needed between them, and
pairing works whether or not the server happens to be running yet.

The ticket
----------
A pairing code is ten characters of Crockford base32 (about fifty bits),
shown as ``XXXXX-XXXXX``.  Only its SHA-256 is stored.  A ticket lasts five
minutes, is consumed by the first successful pairing, and is destroyed after
five wrong guesses, so the code cannot be brute-forced across the window.

The link
--------
``edld://pair?v=1&n=<name>&fp=<fingerprint>&c=<code>&h=<host:port>...``

``fp`` is the server's public-key fingerprint.  A device that pairs from the
link pins it, which is what makes the first connection safe on an untrusted
network: an impostor cannot present that key.  Each ``h`` is an address the
device may try, in order.  The device lets the commander add or edit addresses
before saving, because only they know how their network is set up.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import os
import secrets
import socket
import time
from pathlib import Path
from urllib.parse import urlencode

TICKET_FILE = "pairing.json"
DEVICES_FILE = "devices.json"
TICKET_TTL_S = 300
MAX_ATTEMPTS = 5

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"          # Crockford base32
_NORMALISE = str.maketrans({"O": "0", "I": "1", "L": "1", "U": "V"})


# ── Codes ─────────────────────────────────────────────────────────────────────

def new_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def normalise_code(code: str) -> str:
    return "".join(c for c in str(code).upper() if c.isalnum()).translate(_NORMALISE)


def _hash(code: str) -> str:
    return hashlib.sha256(normalise_code(code).encode("ascii")).hexdigest()


def _atomic_write_json(path: Path, data: dict, private: bool = False) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(data, indent=2)
    if private:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ── Tickets ───────────────────────────────────────────────────────────────────

def issue_ticket(directory: Path, ttl_s: int = TICKET_TTL_S) -> tuple[str, float]:
    """Open a pairing window.  Returns ``(code, expires_epoch)``.

    Issuing a new ticket replaces any earlier one, so only the most recently
    shown code is ever valid.
    """
    directory.mkdir(parents=True, exist_ok=True)
    code = new_code()
    expires = time.time() + ttl_s
    _atomic_write_json(directory / TICKET_FILE, {
        "code_sha256": _hash(code),
        "expires": expires,
        "attempts": 0,
    }, private=True)
    return code, expires


QR_IMAGE = "pairing-qr.png"


def cancel_ticket(directory: Path) -> None:
    """Close the pairing window, and remove the QR image that carried its code."""
    for name in (TICKET_FILE, QR_IMAGE):
        try:
            (directory / name).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def check_ticket(directory: Path, code: str) -> tuple[bool, str]:
    """Test a presented code against the open ticket.

    Returns ``(ok, reason)``.  A correct code consumes the ticket.  A wrong one
    counts against it, and the ticket is destroyed at :data:`MAX_ATTEMPTS`.
    """
    path = directory / TICKET_FILE
    try:
        ticket = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False, "no-ticket"
    except (OSError, ValueError):
        cancel_ticket(directory)
        return False, "no-ticket"

    if time.time() > float(ticket.get("expires", 0)):
        cancel_ticket(directory)
        return False, "expired"

    if hmac.compare_digest(str(ticket.get("code_sha256", "")), _hash(code)):
        cancel_ticket(directory)
        return True, ""

    attempts = int(ticket.get("attempts", 0)) + 1
    if attempts >= MAX_ATTEMPTS:
        cancel_ticket(directory)
        return False, "locked"
    ticket["attempts"] = attempts
    _atomic_write_json(path, ticket, private=True)
    return False, "wrong-code"


# ── Device registry ───────────────────────────────────────────────────────────

class DeviceRegistry:
    """The paired devices, persisted to ``devices.json``.

    Re-read whenever the file changes on disk, so a revocation made by another
    EDLD process (``edld --unpair``) takes effect without a restart.
    """

    def __init__(self, directory: Path):
        self.path = directory / DEVICES_FILE
        self._mtime: float | None = None
        self._devices: list[dict] = []
        self.reload(force=True)

    def reload(self, force: bool = False) -> bool:
        """Re-read the file if it changed.  Returns True when it did."""
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            mtime = None
        if not force and mtime == self._mtime:
            return False
        self._mtime = mtime
        devices: list[dict] = []
        if mtime is not None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                devices = [d for d in data.get("devices", [])
                           if isinstance(d, dict) and d.get("fingerprint")
                           and d.get("cert")]
            except (OSError, ValueError):
                devices = []
        self._devices = devices
        return True

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.path, {"devices": self._devices})
        try:
            self._mtime = self.path.stat().st_mtime
        except OSError:
            pass

    def all(self) -> list[dict]:
        return list(self._devices)

    def get(self, fingerprint: str) -> dict | None:
        for d in self._devices:
            if d.get("fingerprint") == fingerprint:
                return d
        return None

    def add(self, fingerprint: str, cert_b64: str, name: str) -> dict:
        now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        self._devices = [d for d in self._devices
                         if d.get("fingerprint") != fingerprint]
        dev = {"fingerprint": fingerprint, "cert": cert_b64,
               "name": (name or "Device")[:64], "paired": now, "lastSeen": now}
        self._devices.append(dev)
        self._save()
        return dev

    def remove(self, ident: str) -> dict | None:
        """Remove by fingerprint or by any unambiguous prefix of one."""
        matches = [d for d in self._devices
                   if str(d.get("fingerprint", "")).startswith(ident)]
        if len(matches) != 1:
            return None
        gone = matches[0]
        self._devices = [d for d in self._devices if d is not gone]
        self._save()
        return gone

    def touch(self, fingerprint: str, min_interval_s: float = 600) -> None:
        """Record a connection, at most every ten minutes per device."""
        dev = self.get(fingerprint)
        if dev is None:
            return
        now = _dt.datetime.now(_dt.timezone.utc)
        try:
            last = _dt.datetime.fromisoformat(dev.get("lastSeen", ""))
            if (now - last).total_seconds() < min_interval_s:
                return
        except ValueError:
            pass
        dev["lastSeen"] = now.isoformat(timespec="seconds")
        self._save()


# ── Addresses and links ───────────────────────────────────────────────────────

def local_addresses() -> list[str]:
    """This machine's primary LAN addresses, IPv4 first.

    Found by asking the OS which interface it would route through: a UDP
    socket is "connected" to a documentation-range address, which only sets
    the socket's default destination.  No packet is sent and nothing on the
    network is probed or scanned.
    """
    out: list[str] = []
    for family, probe in ((socket.AF_INET, "192.0.2.1"),
                          (socket.AF_INET6, "2001:db8::1")):
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as s:
                s.connect((probe, 9))
                addr = s.getsockname()[0]
            if addr and not addr.startswith(("127.", "::1", "fe80")):
                out.append(addr)
        except OSError:
            pass
    return out


def host_port(host: str, port: int) -> str:
    host = host.strip()
    if ":" in host and not host.startswith("["):
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def pairing_link(name: str, fingerprint: str, code: str,
                 hosts: list[str]) -> str:
    params = [("v", "1"), ("n", name), ("fp", fingerprint),
              ("c", normalise_code(code))]
    params += [("h", h) for h in hosts]
    return "edld://pair?" + urlencode(params)


def qr_text(data: str) -> str | None:
    """A terminal rendering of ``data`` as a QR code, or None without segno."""
    try:
        import segno
    except ImportError:
        return None
    import io
    buf = io.StringIO()
    segno.make(data, error="m").terminal(out=buf, compact=True, border=2)
    return buf.getvalue()
