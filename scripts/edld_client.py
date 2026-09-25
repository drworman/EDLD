#!/usr/bin/env python3
"""
scripts/edld_client.py — a reference client for EDLD's server mode.

Does what the EDAM app does, from a terminal, so the server can be exercised
and the protocol read without a phone:

    edld_client.py pair 'edld://pair?v=1&...'      pair using the link --pair shows
    edld_client.py watch                           connect and print every message
    edld_client.py watch --host 192.168.1.20:28510 try this address instead
    edld_client.py end-session                     ask EDLD to end the game session

The device key, its certificate and the pinned server live in --state
(default ~/.config/edld-client/), exactly as the app keeps them in its own
storage.  Needs the ``cryptography`` package.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import socket
import ssl
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def _fp(cert_der: bytes) -> str:
    spki = x509.load_der_x509_certificate(cert_der).public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return base64.urlsafe_b64encode(hashlib.sha256(spki).digest()).rstrip(b"=").decode()


def _device(state: Path, name: str) -> tuple[Path, Path, bytes]:
    state.mkdir(parents=True, exist_ok=True)
    crt, key = state / "device.crt", state / "device.key"
    if not crt.exists():
        k = ec.generate_private_key(ec.SECP256R1())
        subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        now = dt.datetime.now(dt.timezone.utc)
        c = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj)
             .public_key(k.public_key()).serial_number(x509.random_serial_number())
             .not_valid_before(now - dt.timedelta(days=1))
             .not_valid_after(now + dt.timedelta(days=365 * 20))
             .sign(k, hashes.SHA256()))
        key.write_bytes(k.private_bytes(serialization.Encoding.PEM,
                                        serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
        key.chmod(0o600)
        crt.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    der = x509.load_pem_x509_certificate(crt.read_bytes()).public_bytes(
        serialization.Encoding.DER)
    return crt, key, der


def _split(hp: str) -> tuple[str, int]:
    if hp.startswith("["):
        host, _, port = hp[1:].partition("]:")
    else:
        host, _, port = hp.rpartition(":")
    return host, int(port)


def _connect(hosts: list[str], pin: str, cert=None):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE            # trust is the pin, checked below
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    if cert:
        ctx.load_cert_chain(*cert)
    last = None
    for hp in hosts:
        try:
            host, port = _split(hp)
            raw = socket.create_connection((host, port), timeout=5)
            s = ctx.wrap_socket(raw)
            got = _fp(s.getpeercert(binary_form=True))
            if got != pin:
                s.close()
                raise ssl.SSLError(f"{hp} presented key {got}, expected {pin}")
            print(f"connected to {hp}", file=sys.stderr)
            return s
        except (OSError, ssl.SSLError) as exc:
            last = exc
            print(f"{hp}: {exc}", file=sys.stderr)
    raise SystemExit(f"could not connect: {last}")


def _send(s, msg):
    s.sendall((json.dumps(msg) + "\n").encode())


def cmd_pair(a):
    q = parse_qs(urlparse(a.link).query)
    hosts = q.get("h", []) + ([a.host] if a.host else [])
    server = {"name": q["n"][0], "fingerprint": q["fp"][0], "hosts": hosts}
    _crt, _key, der = _device(a.state, a.name)
    s = _connect(hosts, server["fingerprint"])
    _send(s, {"t": "pair", "v": 1, "code": q["c"][0], "name": a.name,
              "cert": base64.b64encode(der).decode()})
    reply = json.loads(s.makefile("rb").readline() or b"{}")
    print(json.dumps(reply, indent=2))
    if reply.get("t") == "paired":
        (a.state / "server.json").write_text(json.dumps(server, indent=2))


def _session(a):
    server = json.loads((a.state / "server.json").read_text())
    crt, key, _ = _device(a.state, a.name)
    hosts = ([a.host] if a.host else []) + server["hosts"]
    s = _connect(hosts, server["fingerprint"], (str(crt), str(key)))
    _send(s, {"t": "hello", "v": 1, "app": "edld_client", "device": a.name})
    return s, s.makefile("rb")


def cmd_watch(a):
    s, r = _session(a)
    s.settimeout(30)
    last_ping = time.monotonic()
    while True:
        try:
            line = r.readline()
        except (socket.timeout, TimeoutError):
            line = None
        if line == b"":
            print("server closed the connection", file=sys.stderr)
            return
        if line:
            msg = json.loads(line)
            print(json.dumps(msg, indent=None if a.compact else 2,
                             ensure_ascii=False))
        if time.monotonic() - last_ping > 25:
            _send(s, {"t": "ping", "id": int(time.time())})
            last_ping = time.monotonic()


def cmd_end(a):
    s, r = _session(a)
    _send(s, {"t": "cmd", "id": 1, "cmd": "end_session", "confirm": True})
    for line in r:
        msg = json.loads(line)
        if msg.get("t") == "result":
            print(json.dumps(msg, indent=2))
            return


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--state", type=Path,
                   default=Path.home() / ".config" / "edld-client")
    p.add_argument("--name", default=socket.gethostname())
    p.add_argument("--host", help="host:port to try first")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("pair"); sp.add_argument("link"); sp.set_defaults(fn=cmd_pair)
    sw = sub.add_parser("watch"); sw.add_argument("--compact", action="store_true")
    sw.set_defaults(fn=cmd_watch)
    sub.add_parser("end-session").set_defaults(fn=cmd_end)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
