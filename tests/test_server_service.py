"""
tests/test_server_service.py — server mode end to end, over real TLS.

Each test runs the real listener on 127.0.0.1 and talks to it the way the
Android client will: TLS 1.3, the server pinned by public-key fingerprint, the
device authenticated by a self-signed EC P-256 certificate of the kind Android's
keystore produces.  Nothing is mocked below the socket.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import socket
import ssl
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("cryptography")

from cryptography import x509                                       # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization    # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec            # noqa: E402
from cryptography.x509.oid import NameOID                           # noqa: E402

from core.server import identity, pairing, service                  # noqa: E402


# ── A device, as Android would make one ───────────────────────────────────────

class Device:
    def __init__(self, tmp: Path, name: str = "Pixel", key_usage: bool = False):
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        b = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
             .public_key(key.public_key())
             .serial_number(x509.random_serial_number())
             .not_valid_before(dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc))
             .not_valid_after(dt.datetime(2048, 1, 1, tzinfo=dt.timezone.utc)))
        if key_usage:
            b = b.add_extension(x509.KeyUsage(
                digital_signature=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=False, crl_sign=False,
                encipher_only=False, decipher_only=False), critical=True)
        cert = b.sign(key, hashes.SHA256())
        self.name = name
        self.der = cert.public_bytes(serialization.Encoding.DER)
        self.cert_path = tmp / f"{name}.crt"
        self.key_path = tmp / f"{name}.key"
        self.cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        self.key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))

    @property
    def cert_b64(self) -> str:
        return base64.b64encode(self.der).decode()


class Conn:
    """A client connection that pins the server the way the app does."""

    def __init__(self, port: int, pin: str, device: Device | None = None):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE        # trust comes from the pin below
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        if device is not None:
            ctx.load_cert_chain(str(device.cert_path), str(device.key_path))
        raw = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.sock = ctx.wrap_socket(raw)
        got = identity.spki_fingerprint_der(self.sock.getpeercert(binary_form=True))
        assert got == pin, "server key does not match the pin"
        self.reader = self.sock.makefile("rb")

    def send(self, msg: dict) -> None:
        self.sock.sendall((json.dumps(msg) + "\n").encode())

    def recv(self, timeout: float = 5) -> dict | None:
        self.sock.settimeout(timeout)
        line = self.reader.readline()
        return json.loads(line) if line else None

    def recv_type(self, t: str, timeout: float = 5) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = self.recv(max(0.1, deadline - time.monotonic()))
            assert msg is not None, f"closed while waiting for {t}"
            if msg.get("t") == t:
                return msg
        raise AssertionError(f"no {t} message")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


# ── A running EDLD, minus the game ────────────────────────────────────────────

class FakeKsw:
    OVERLAY_PANELS = ()

    def __init__(self):
        self.calls = []

    def flush_session(self, reason=""):
        self.calls.append(reason)


class FakeAlerts:
    OVERLAY_PANELS = ()

    def __init__(self):
        self.items = [{"emoji": "⚠", "text": "Shields down",
                       "mono_time": time.monotonic()}]

    def get_alerts(self):
        return list(self.items)


def _core():
    state = SimpleNamespace(
        pilot_name="MERRICK CALBRUIN", pilot_squadron_name="MINING AND LOGISTICS LTD",
        pilot_squadron_tag="MALL", pilot_squadron_rank="Executive Director",
        ship_name="Prospect", ship_ident="MC-01", pilot_ship="Type-10 Defender",
        pilot_system="Sol", pilot_location="Abraham Lincoln", pilot_mode="Solo",
        event_time=dt.datetime.now(dt.timezone.utc), monitor_error="",
        ship_hull=100, ship_shields=True, ship_shields_recharging=False,
        fuel_current=32.0, fuel_tank_size=64, docked=False, landed=False,
        supercruise=False, on_foot=False, star_system="Sol", suit_name="",
    )
    return SimpleNamespace(state=state, session_providers=[],
                           _plugins={"ksw": FakeKsw(), "alerts": FakeAlerts()})


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "TICK_S", 0.1)
    made = []

    def make(**settings):
        cfg = {"Port": 0, "BindAddress": "127.0.0.1", "AllowEndSession": False}
        cfg.update(settings)
        core = _core()
        srv = service.ServerService(core, directory=tmp_path / "server",
                                    settings=cfg, name="EDLD test")
        srv.builder.game_running = lambda: True
        srv.start()
        made.append(srv)
        return srv, core

    yield make
    for s in made:
        s.stop()


def _pair(srv, dev: Device) -> dict:
    code, _ = pairing.issue_ticket(srv.directory)
    c = Conn(srv.bound[1], srv.identity.fingerprint)
    c.send({"t": "pair", "v": 1, "code": code, "cert": dev.cert_b64,
            "name": dev.name})
    reply = c.recv()
    c.close()
    return reply


def _hello(srv, dev: Device) -> Conn:
    c = Conn(srv.bound[1], srv.identity.fingerprint, dev)
    c.send({"t": "hello", "v": 1, "app": "test"})
    return c


# ── Pairing ───────────────────────────────────────────────────────────────────

def test_unpaired_hello_is_refused(server, tmp_path):
    srv, _ = server()
    c = Conn(srv.bound[1], srv.identity.fingerprint)
    c.send({"t": "hello", "v": 1})
    assert c.recv()["code"] == "not-paired"


def test_pairing_needs_an_open_ticket(server, tmp_path):
    srv, _ = server()
    c = Conn(srv.bound[1], srv.identity.fingerprint)
    c.send({"t": "pair", "code": "AAAAA-AAAAA", "cert": Device(tmp_path).cert_b64})
    assert c.recv()["code"] == "no-ticket"


def test_wrong_code_then_lockout(server, tmp_path):
    srv, _ = server()
    dev = Device(tmp_path)
    code, _ = pairing.issue_ticket(srv.directory)
    for i in range(pairing.MAX_ATTEMPTS):
        c = Conn(srv.bound[1], srv.identity.fingerprint)
        c.send({"t": "pair", "code": "00000-00000", "cert": dev.cert_b64})
        want = "locked" if i == pairing.MAX_ATTEMPTS - 1 else "wrong-code"
        assert c.recv()["code"] == want
        c.close()
    # The right code is no good once the ticket is gone.
    c = Conn(srv.bound[1], srv.identity.fingerprint)
    c.send({"t": "pair", "code": code, "cert": dev.cert_b64})
    assert c.recv()["code"] == "no-ticket"


@pytest.mark.parametrize("key_usage", [False, True])
def test_pair_then_connect(server, tmp_path, key_usage):
    """Both certificate shapes Android can produce are accepted."""
    srv, _ = server()
    dev = Device(tmp_path, key_usage=key_usage)
    reply = _pair(srv, dev)
    assert reply["t"] == "paired"
    assert reply["server"]["fingerprint"] == srv.identity.fingerprint
    c = _hello(srv, dev)
    welcome = c.recv_type("welcome")
    assert welcome["device"]["name"] == "Pixel"
    snap = c.recv_type("snapshot")
    h = snap["header"]
    assert h["cmdr"] == "MERRICK CALBRUIN"
    assert h["squadron"]["name"] == "MINING AND LOGISTICS LTD"
    assert h["ship"]["ident"] == "MC-01"
    ids = {p["id"] for p in snap["panels"]}
    assert {"status", "alerts"} <= ids
    c.close()


def test_code_is_single_use(server, tmp_path):
    srv, _ = server()
    code, _ = pairing.issue_ticket(srv.directory)
    for n, want in ((1, "paired"), (2, "no-ticket")):
        c = Conn(srv.bound[1], srv.identity.fingerprint)
        c.send({"t": "pair", "code": code, "cert": Device(tmp_path, f"D{n}").cert_b64})
        assert c.recv()["t" if want == "paired" else "code"] == want
        c.close()


def test_never_paired_certificate_fails_the_handshake(server, tmp_path):
    srv, _ = server()
    _pair(srv, Device(tmp_path, "Known"))
    stranger = Device(tmp_path, "Stranger")
    with pytest.raises((ssl.SSLError, OSError, AssertionError, TypeError)):
        c = _hello(srv, stranger)
        c.recv_type("welcome", timeout=2)


def test_client_rejects_the_wrong_server_key(server, tmp_path):
    srv, _ = server()
    with pytest.raises(AssertionError, match="does not match the pin"):
        Conn(srv.bound[1], "not-the-fingerprint")


# ── Updates ───────────────────────────────────────────────────────────────────

def test_changes_are_pushed_while_connected(server, tmp_path):
    srv, core = server()
    dev = Device(tmp_path)
    _pair(srv, dev)
    c = _hello(srv, dev)
    c.recv_type("snapshot")
    core.state.ship_hull = 42
    msg = c.recv_type("panels")
    status = [p for p in msg["upsert"] if p["id"] == "status"][0]
    assert any(r["value"] == "42%" for r in status["rows"])
    core.state.pilot_system = "Achenar"
    msg = c.recv_type("panels")
    assert msg["header"]["system"] == "Achenar"
    c.close()


def test_nothing_is_sent_when_nothing_changed(server, tmp_path):
    srv, _ = server()
    dev = Device(tmp_path)
    _pair(srv, dev)
    c = _hello(srv, dev)
    c.recv_type("snapshot")
    with pytest.raises((socket.timeout, TimeoutError)):
        c.recv(timeout=0.6)
    c.close()


def test_ping(server, tmp_path):
    srv, _ = server()
    dev = Device(tmp_path)
    _pair(srv, dev)
    c = _hello(srv, dev)
    c.recv_type("snapshot")
    c.send({"t": "ping", "id": 7})
    assert c.recv_type("pong")["id"] == 7
    c.close()


# ── Revocation ────────────────────────────────────────────────────────────────

def test_revocation_from_another_process(server, tmp_path):
    srv, _ = server()
    dev = Device(tmp_path)
    _pair(srv, dev)
    c = _hello(srv, dev)
    c.recv_type("snapshot")
    # edld --unpair runs in its own process and only edits the file.
    fp = identity.spki_fingerprint_der(dev.der)
    time.sleep(0.05)       # distinct mtime on coarse filesystems
    assert pairing.DeviceRegistry(srv.directory).remove(fp[:8]) is not None
    assert c.recv_type("error")["code"] == "revoked"
    c.close()
    with pytest.raises((ssl.SSLError, OSError, AssertionError, TypeError)):
        c2 = _hello(srv, dev)
        c2.recv_type("welcome", timeout=2)


# ── Ending the session ────────────────────────────────────────────────────────

def _end(c, confirm=True):
    c.send({"t": "cmd", "id": 1, "cmd": "end_session", "confirm": confirm})
    return c.recv_type("result")


def test_end_session_is_off_by_default(server, tmp_path):
    srv, core = server()
    dev = Device(tmp_path)
    _pair(srv, dev)
    c = _hello(srv, dev)
    snap = c.recv_type("snapshot")
    assert snap["header"]["endSession"]["available"] is False
    r = _end(c)
    assert r["ok"] is False and r["error"] == "refused"
    assert core._plugins["ksw"].calls == []
    c.close()


def test_end_session_solo_only(server, tmp_path):
    srv, core = server(AllowEndSession=True)
    dev = Device(tmp_path)
    _pair(srv, dev)
    c = _hello(srv, dev)
    c.recv_type("snapshot")
    core.state.pilot_mode = "Open"
    r = _end(c)
    assert r["ok"] is False and "Solo" in r["message"]
    assert core._plugins["ksw"].calls == []
    core.state.pilot_mode = "Solo"
    assert _end(c, confirm=False)["error"] == "unconfirmed"
    r = _end(c)
    assert r["ok"] is True
    assert core._plugins["ksw"].calls == ["ended from Pixel"]
    c.close()
