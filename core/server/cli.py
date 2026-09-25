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


def _hosts(settings: dict, port: int, external: str) -> list[str]:
    bind = str(settings.get("BindAddress", "") or "").strip()
    if bind and bind not in ("0.0.0.0", "::"):
        hosts = [_pairing.host_port(bind, port)]
    else:
        hosts = [_pairing.host_port(a, port) for a in _pairing.local_addresses()]
    if external:
        hosts.append(external if (":" in external and not external.count(":") > 1)
                     else _pairing.host_port(external, port))
    return hosts


def pair(directory: Path, settings: dict, name: str, *,
         interactive: bool | None = None, out=None) -> int:
    out = out or sys.stdout
    port = int(settings.get("Port", 0) or 0)
    ident = _identity.load_or_create(directory, name)

    external = str(settings.get("ExternalHost", "") or "").strip()
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

    code, expires = _pairing.issue_ticket(directory)
    hosts = _hosts(settings, port, external)
    link = _pairing.pairing_link(name, ident.fingerprint, code, hosts)
    until = _dt.datetime.fromtimestamp(expires).strftime("%H:%M:%S")

    qr = _pairing.qr_text(link)
    if qr:
        print(qr, file=out)
    # For a machine whose console cannot draw the QR code — a Windows logon
    # task has no console at all.  It carries the code, so it is private and
    # is deleted when the pairing window closes.
    png = directory / _pairing.QR_IMAGE
    try:
        import segno
        segno.make(link, error="m").save(str(png), scale=8, border=3)
        try:
            png.chmod(0o600)
        except OSError:
            pass
    except Exception:
        png = None

    print(f"Pair a device with {name}", file=out)
    print(f"  Code:        {code}   (valid until {until}, one use)", file=out)
    print(f"  Fingerprint: {ident.fingerprint}", file=out)
    print("  Addresses:   " + (", ".join(hosts) or "(none found)"), file=out)
    if png:
        print(f"  QR image:    {png}", file=out)
    print(f"  Link:        {link}", file=out)
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
