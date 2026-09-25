"""
tests/test_server_network.py — port mapping and DuckDNS, against fakes.

A fake NAT-PMP gateway, a fake UPnP router (SSDP responder, description XML,
SOAP control URL) and a fake DuckDNS, all on 127.0.0.1.  The code under test
speaks real UDP and HTTP to them; only the other end is pretend.
"""
from __future__ import annotations

import http.server
import socket
import struct
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.server import duckdns, portmap  # noqa: E402


# ── NAT-PMP ───────────────────────────────────────────────────────────────────

class FakePmp:
    def __init__(self, external="1.2.3.7", result=0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.external, self.result = external, result
        self.maps = {}
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(64)
            except OSError:
                return
            if data[:2] == b"\x00\x00":
                self.sock.sendto(struct.pack("!BBHI", 0, 128, self.result, 1)
                                 + socket.inet_aton(self.external), addr)
            elif data[1] == 2:
                _v, _o, _r, internal, external, life = struct.unpack("!BBHHHI", data)
                if life:
                    self.maps[internal] = life
                else:
                    self.maps.pop(internal, None)
                self.sock.sendto(struct.pack("!BBHIHHI", 0, 130, self.result, 1,
                                             internal, external or internal, life), addr)

    def close(self):
        self.sock.close()


def test_natpmp_maps_and_unmaps():
    gw = FakePmp()
    try:
        c = portmap.NatPmp("127.0.0.1", gw.port)
        m = c.map(28510)
        assert (m.method, m.external_port, m.lease_s) == ("NAT-PMP", 28510, 3600)
        assert m.external_ip == "1.2.3.7"
        assert gw.maps == {28510: 3600}
        c.unmap(28510)
        assert gw.maps == {}
    finally:
        gw.close()


def test_natpmp_refusal_is_reported():
    gw = FakePmp(result=2)
    try:
        with pytest.raises(portmap.PortMapError, match="refused"):
            portmap.NatPmp("127.0.0.1", gw.port).map(28510)
    finally:
        gw.close()


def test_natpmp_silence_times_out():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    try:
        with pytest.raises(portmap.PortMapError, match="no answer"):
            portmap.NatPmp("127.0.0.1", s.getsockname()[1], tries=2,
                           first_timeout=0.05).map(28510)
    finally:
        s.close()


# ── UPnP ──────────────────────────────────────────────────────────────────────

DESC = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0"><device>
 <deviceType>urn:schemas-upnp-org:device:InternetGatewayDevice:1</deviceType>
 <deviceList><device><deviceList><device><serviceList><service>
  <serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>
  <controlURL>/ctl/IPConn</controlURL>
 </service></serviceList></device></deviceList></device></deviceList>
</device></root>"""


class FakeRouter:
    def __init__(self, external="1.2.3.9", permanent_only=False, conflict=False,
                 spoof_location=None):
        self.maps: dict = {}
        self.external, self.permanent_only, self.conflict = external, permanent_only, conflict
        router = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = DESC.encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                action = self.headers["SOAPAction"].split("#")[1].strip('"')
                fault = None
                if action == "AddPortMapping":
                    lease = int(body.split("<NewLeaseDuration>")[1].split("<")[0])
                    port = int(body.split("<NewExternalPort>")[1].split("<")[0])
                    client = body.split("<NewInternalClient>")[1].split("<")[0]
                    if router.conflict:
                        fault = 718
                    elif router.permanent_only and lease:
                        fault = 725
                    else:
                        router.maps[port] = (client, lease)
                    out = ""
                elif action == "DeletePortMapping":
                    port = int(body.split("<NewExternalPort>")[1].split("<")[0])
                    router.maps.pop(port, None)
                    out = ""
                else:
                    out = f"<NewExternalIPAddress>{router.external}</NewExternalIPAddress>"
                if fault:
                    xml = (f'<s:Envelope xmlns:s="x"><s:Body><s:Fault><detail><UPnPError>'
                           f'<errorCode>{fault}</errorCode><errorDescription>no'
                           f'</errorDescription></UPnPError></detail></s:Fault></s:Body></s:Envelope>')
                    self.send_response(500)
                else:
                    xml = (f'<s:Envelope xmlns:s="x"><s:Body><u:{action}Response xmlns:u="y">'
                           f'{out}</u:{action}Response></s:Body></s:Envelope>')
                    self.send_response(200)
                data = xml.encode()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers(); self.wfile.write(data)

        self.http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.location = spoof_location or f"http://127.0.0.1:{self.http.server_port}/desc.xml"
        self.ssdp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ssdp.bind(("127.0.0.1", 0))
        self.ssdp_addr = self.ssdp.getsockname()
        threading.Thread(target=self._ssdp, daemon=True).start()

    def _ssdp(self):
        while True:
            try:
                data, addr = self.ssdp.recvfrom(2048)
            except OSError:
                return
            if b"M-SEARCH" in data:
                self.ssdp.sendto(("HTTP/1.1 200 OK\r\nST: x\r\n"
                                  f"LOCATION: {self.location}\r\n\r\n").encode(), addr)

    def close(self):
        self.http.shutdown(); self.ssdp.close()


def _mapper(router, log=None, alert=None):
    # A gateway with nothing listening makes NAT-PMP fail fast, so UPnP runs.
    dead = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); dead.bind(("127.0.0.1", 0))
    m = portmap.PortMapper(28510, log=log, alert=alert, gateway="127.0.0.1",
                           pmp_port=dead.getsockname()[1],
                           ssdp_target=router.ssdp_addr, ssdp_timeout=0.4,
                           pmp_timeout=0.05)
    return m, dead


def test_upnp_maps_and_unmaps():
    r = FakeRouter()
    m, dead = _mapper(r)
    try:
        got = m.map_once()
        assert got.method == "UPnP" and got.external_ip == "1.2.3.9"
        assert r.maps[28510] == ("127.0.0.1", 3600)
        m.mapping = got
        m.stop()
        assert r.maps == {}
    finally:
        r.close(); dead.close()


def test_upnp_permanent_only_router():
    r = FakeRouter(permanent_only=True)
    m, dead = _mapper(r)
    try:
        assert m.map_once().lease_s == 0
        assert r.maps[28510][1] == 0
    finally:
        r.close(); dead.close()


def test_upnp_conflict_says_so():
    r = FakeRouter(conflict=True)
    m, dead = _mapper(r)
    try:
        with pytest.raises(portmap.PortMapError, match="another computer"):
            m.map_once()
    finally:
        r.close(); dead.close()


def test_ssdp_reply_pointing_elsewhere_is_ignored():
    r = FakeRouter(spoof_location="http://198.51.100.5/desc.xml")
    m, dead = _mapper(r)
    try:
        with pytest.raises(portmap.PortMapError, match="no router answered"):
            m.map_once()
    finally:
        r.close(); dead.close()


def test_cgnat_is_reported():
    r = FakeRouter(external="100.64.12.34")
    alerts, logs = [], []
    m, dead = _mapper(r, log=logs.append, alert=alerts.append)
    try:
        m.start()
        deadline = time.monotonic() + 10
        while not alerts and time.monotonic() < deadline:
            time.sleep(0.05)
        assert alerts and "CGNAT" in alerts[0]
        assert "CGNAT" in m.status
    finally:
        m.stop(); r.close(); dead.close()


def test_private_address_classification():
    assert portmap.behind_second_nat("100.64.0.1")
    assert portmap.behind_second_nat("192.168.0.2")
    assert not portmap.behind_second_nat("1.2.3.4")
    assert not portmap.behind_second_nat(None)


# ── DuckDNS ───────────────────────────────────────────────────────────────────

class FakeDuck:
    def __init__(self, answer="OK"):
        self.requests = []
        duck = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                duck.requests.append(self.path)
                body = answer.encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)

        self.http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.http.server_port}/update"


@pytest.mark.parametrize("given", ["cmdr", "CMDR.duckdns.org", "https://cmdr.duckdns.org/"])
def test_domain_normalisation(given):
    assert duckdns.domain_only(given) == "cmdr"
    assert duckdns.hostname(given) == "cmdr.duckdns.org"


def test_duckdns_update_and_no_token_in_logs():
    d = FakeDuck("OK")
    logs, alerts = [], []
    u = duckdns.DuckDNSUpdater("cmdr.duckdns.org", "tok-SECRET", log=logs.append,
                               alert=alerts.append, url=d.url)
    ok, text = u.update_once()
    assert ok and text == "cmdr.duckdns.org updated"
    assert "domains=cmdr" in d.requests[0] and "token=tok-SECRET" in d.requests[0]
    u.start(); time.sleep(0.3); u.stop()
    assert not alerts
    assert all("tok-SECRET" not in line for line in logs)
    d.http.shutdown()


def test_duckdns_refusal_alerts_once():
    d = FakeDuck("KO")
    alerts = []
    u = duckdns.DuckDNSUpdater("cmdr", "bad", alert=alerts.append, url=d.url,
                               interval_s=0.05)
    u.start(); time.sleep(0.4); u.stop()
    assert len(alerts) == 1 and "refused" in alerts[0]
    assert "bad" not in alerts[0]
    d.http.shutdown()


def test_duckdns_needs_both_settings():
    assert not duckdns.DuckDNSUpdater("", "t").configured
    assert not duckdns.DuckDNSUpdater("cmdr", "").configured
