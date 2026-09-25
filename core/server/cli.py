"""
core/server/cli.py — ``edld --pair``, ``--paired`` and ``--unpair``.

These run as their own short-lived process, usually while EDLD is already
running as a dashboard or a headless service, and act only on files in the
profile's server directory.  See core/server/pairing.py for why.
"""

from __future__ import annotations

import datetime as _dt
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

from core.server import identity as _identity
from core.server import pairing as _pairing


def _listening(port: int) -> bool:
    """Is something accepting connections on this machine's own port?"""
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            continue
    return False


def external_host(settings: dict) -> str:
    """The away-from-home address: ExternalHost, else the DuckDNS name."""
    ext = str(settings.get("ExternalHost", "") or "").strip()
    if not ext and settings.get("DuckDNSDomain"):
        from core.server.duckdns import hostname
        ext = hostname(str(settings.get("DuckDNSDomain")))
    return ext


def _hosts(settings: dict, port: int, external: str) -> list[str]:
    bind = str(settings.get("BindAddress", "") or "").strip()
    if bind and bind not in ("0.0.0.0", "::"):
        hosts = [_pairing.host_port(bind, port)]
    else:
        hosts = [_pairing.host_port(a, port) for a in _pairing.local_addresses()]
    if external:
        # "name:port" keeps its own port, for a router forwarding a different
        # outside port; a bare name or address gets EDLD's.
        has_port = external.count(":") == 1 or external.startswith("[")
        hosts.append(external if has_port else _pairing.host_port(external, port))
    return hosts


@dataclass
class PairingInfo:
    code: str
    expires: float
    link: str
    hosts: list[str]
    fingerprint: str
    name: str
    png: Path | None

    @property
    def until(self) -> str:
        return _dt.datetime.fromtimestamp(self.expires).strftime("%H:%M:%S")

    def qr_text(self) -> str | None:
        return _pairing.qr_text(self.link)

    def qr_png_bytes(self, scale: int = 6) -> bytes | None:
        try:
            import io
            import segno
            buf = io.BytesIO()
            segno.make(self.link, error="m").save(buf, kind="png", scale=scale,
                                                  border=3)
            return buf.getvalue()
        except Exception:
            return None


def new_pairing(directory: Path, settings: dict, name: str,
                external: str | None = None, write_png: bool = True) -> PairingInfo:
    """Open a pairing window and describe it.  Shared by --pair and both
    preferences screens, so all three show the same code in the same way."""
    port = int(settings.get("Port", 0) or 0)
    ident = _identity.load_or_create(directory, name)
    ext = external_host(settings) if external is None else external.strip()
    code, expires = _pairing.issue_ticket(directory)
    hosts = _hosts(settings, port, ext)
    link = _pairing.pairing_link(name, ident.fingerprint, code, hosts)
    info = PairingInfo(code, expires, link, hosts, ident.fingerprint, name, None)
    if write_png:
        # For a machine whose console cannot draw the QR code — a Windows
        # logon task has no console at all.  It carries the code, so it is
        # private and is deleted when the pairing window closes.
        png = directory / _pairing.QR_IMAGE
        data = info.qr_png_bytes(scale=8)
        if data:
            png.write_bytes(data)
            try:
                png.chmod(0o600)
            except OSError:
                pass
            info.png = png
    return info


def pair(directory: Path, settings: dict, name: str, *,
         interactive: bool | None = None, out=None) -> int:
    out = out or sys.stdout
    port = int(settings.get("Port", 0) or 0)
    external = external_host(settings)
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not external and interactive:
        print("Address for use away from home, e.g. yourname.duckdns.org or\n"
              "yourname.duckdns.org:PORT. Leave blank for this network only.\n"
              "(Set Server.ExternalHost in config.toml to skip this question.)",
              file=out)
        try:
            external = input("> ").strip()
        except EOFError:
            external = ""

    info = new_pairing(directory, settings, name, external=external)
    qr = info.qr_text()
    if qr:
        print(qr, file=out)
    print(f"Pair a device with {name}", file=out)
    print(f"  Code:        {info.code}   (valid until {info.until}, one use)", file=out)
    print(f"  Fingerprint: {info.fingerprint}", file=out)
    print("  Addresses:   " + (", ".join(info.hosts) or "(none found)"), file=out)
    if info.png:
        print(f"  QR image:    {info.png}", file=out)
    print(f"  Link:        {info.link}", file=out)
    print("", file=out)
    print("In EDAM: Add computer → scan the QR code, or paste the link.", file=out)
    if port and not _listening(port):
        print(f"\nNote: nothing is listening on port {port} yet. Start EDLD "
              f"with -s (or set Server.Enabled = true) before the code "
              f"expires.", file=out)
    return 0


def paired(directory: Path, out=None) -> int:
    out = out or sys.stdout
    devices = _pairing.DeviceRegistry(directory).all()
    if not devices:
        print("No paired devices.", file=out)
        return 0
    print(f"{'ID':<10}{'Name':<24}{'Paired':<27}Last seen", file=out)
    for d in devices:
        print(f"{_identity.short_id(d['fingerprint']):<10}"
              f"{str(d.get('name', ''))[:23]:<24}"
              f"{str(d.get('paired', '')):<27}{d.get('lastSeen', '')}", file=out)
    return 0


def unpair(directory: Path, ident: str, out=None) -> int:
    out = out or sys.stdout
    gone = _pairing.DeviceRegistry(directory).remove(ident.strip())
    if gone is None:
        print(f"No single paired device matches {ident!r}. "
              f"See edld --paired.", file=out)
        return 1
    print(f"Unpaired {gone.get('name')} ({_identity.short_id(gone['fingerprint'])}). "
          f"A running EDLD disconnects it within a few seconds.", file=out)
    return 0
