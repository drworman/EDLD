"""
core/server/portmap.py — ask the router to forward EDLD's port.

Off unless ``[Server] PortMapping = true``.  When on, EDLD asks the router for
one TCP port — its own, forwarded to this computer — using the two standard
ways home routers offer:

NAT-PMP (RFC 6886)
    One UDP request to the default gateway on port 5351.  Apple routers and
    many others.
UPnP IGD
    An SSDP search on the local network for an Internet Gateway Device, then
    two SOAP requests to the router's control URL.  Most consumer routers,
    including Netgear's.

That is the whole of the network traffic, and it is the same thing games and
consoles do to open their ports.  Nothing else on the network is contacted,
and only a router that answers from a private address is trusted — an SSDP
reply pointing anywhere else is ignored.

The mapping is leased, renewed at half its lifetime, and removed when EDLD
stops.  A router that only offers permanent mappings gets one, and it is still
removed on a clean exit.

What the router reports as its external address is checked too.  A private or
shared address there (``100.64.0.0/10`` in particular) means another NAT sits
between the router and the internet — carrier-grade NAT, or a second router —
and no mapping on this router can make EDLD reachable from outside.  That is
reported, because the alternative is a commander wondering why a port they
were told was open never answers.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable

DESCRIPTION = "EDLD"
LEASE_S = 3600

SSDP_ADDR = ("239.255.255.250", 1900)
_SEARCH_TARGETS = (
    "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
    "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
)
_WAN_SERVICES = (
    "urn:schemas-upnp-org:service:WANIPConnection:2",
    "urn:schemas-upnp-org:service:WANIPConnection:1",
    "urn:schemas-upnp-org:service:WANPPPConnection:1",
)


class PortMapError(RuntimeError):
    pass


@dataclass
class Mapping:
    method: str             # "NAT-PMP" or "UPnP"
    external_port: int
    internal_port: int
    lease_s: int            # 0: permanent
    external_ip: str | None = None


def is_private(ip: str | None) -> bool:
    try:
        a = ipaddress.ip_address(ip or "")
    except ValueError:
        return False
    return a.is_private or a.is_link_local or a in ipaddress.ip_network("100.64.0.0/10")


def behind_second_nat(external_ip: str | None) -> bool:
    """The router's own 'external' address is not a public one."""
    return bool(external_ip) and is_private(external_ip)


def local_ip_towards(host: str) -> str:
    """This machine's address on the interface that reaches ``host``.

    A UDP socket "connected" to the router only chooses a route; no packet is
    sent.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((host, 9))
        return s.getsockname()[0]


# ── The default gateway ───────────────────────────────────────────────────────

def default_gateway() -> str | None:
    """The IPv4 default gateway, read from the OS routing table."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/net/route", encoding="ascii") as fh:
                for line in fh.readlines()[1:]:
                    f = line.split()
                    if len(f) > 3 and f[1] == "00000000" and int(f[3], 16) & 2:
                        return socket.inet_ntoa(struct.pack("<L", int(f[2], 16)))
            return None
        if sys.platform == "win32":
            out = subprocess.run(
                ["route", "print", "-4", "0.0.0.0"], capture_output=True,
                text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            m = re.search(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)",
                          out, re.MULTILINE)
            return m.group(1) if m else None
        out = subprocess.run(["route", "-n", "get", "default"], capture_output=True,
                             text=True, timeout=5).stdout
        m = re.search(r"gateway:\s*(\d+\.\d+\.\d+\.\d+)", out)
        return m.group(1) if m else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


# ── NAT-PMP ───────────────────────────────────────────────────────────────────

_PMP_ERRORS = {1: "unsupported version", 2: "refused by the router's settings",
               3: "network failure", 4: "out of resources", 5: "unsupported opcode"}


class NatPmp:
    def __init__(self, gateway: str, port: int = 5351, tries: int = 3,
                 first_timeout: float = 0.25):
        self.gateway, self.port = gateway, port
        self.tries, self.first_timeout = tries, first_timeout

    def _call(self, request: bytes, want_op: int, size: int) -> bytes:
        timeout = self.first_timeout
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for _ in range(self.tries):
                s.sendto(request, (self.gateway, self.port))
                s.settimeout(timeout)
                try:
                    while True:
                        data, addr = s.recvfrom(64)
                        if addr[0] != self.gateway or len(data) < size:
                            continue
                        if data[0] != 0 or data[1] != want_op:
                            continue
                        result = struct.unpack("!H", data[2:4])[0]
                        if result:
                            raise PortMapError(
                                f"NAT-PMP: {_PMP_ERRORS.get(result, f'error {result}')}")
                        return data
                except (socket.timeout, TimeoutError):
                    timeout *= 2
        raise PortMapError("NAT-PMP: no answer from the router")

    def external_ip(self) -> str:
        data = self._call(b"\x00\x00", 128, 12)
        return socket.inet_ntoa(data[8:12])

    def map(self, port: int, lease_s: int = LEASE_S) -> Mapping:
        req = struct.pack("!BBHHHI", 0, 2, 0, port, port, lease_s)
        data = self._call(req, 130, 16)
        _i, external, lifetime = struct.unpack("!HHI", data[8:16])
        m = Mapping("NAT-PMP", external, port, lifetime)
        try:
            m.external_ip = self.external_ip()
        except PortMapError:
            pass
        return m

    def unmap(self, port: int) -> None:
        self._call(struct.pack("!BBHHHI", 0, 2, 0, port, 0, 0), 130, 16)


# ── UPnP IGD ──────────────────────────────────────────────────────────────────

def ssdp_search(timeout: float = 2.5, target=SSDP_ADDR) -> list[str]:
    """LOCATION URLs of gateway devices that answered, from private hosts only."""
    found: list[str] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        for st in _SEARCH_TARGETS:
            msg = ("M-SEARCH * HTTP/1.1\r\n"
                   f"HOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
                   'MAN: "ssdp:discover"\r\nMX: 2\r\n'
                   f"ST: {st}\r\n\r\n").encode("ascii")
            s.sendto(msg, target)
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            s.settimeout(left)
            try:
                data, addr = s.recvfrom(4096)
            except (socket.timeout, TimeoutError):
                break
            m = re.search(rb"^location:\s*(\S+)", data, re.IGNORECASE | re.MULTILINE)
            if not m:
                continue
            loc = m.group(1).decode("ascii", "replace")
            host = urllib.parse.urlparse(loc).hostname
            # Only a router on this network. A reply steering EDLD to some
            # other host is not something to go and fetch.
            if host != addr[0] or not is_private(host):
                continue
            if loc not in found:
                found.append(loc)
    return found


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def control_url(location: str, timeout: float = 5) -> tuple[str, str]:
    """``(control_url, service_type)`` of the WAN connection service."""
    with urllib.request.urlopen(location, timeout=timeout) as r:
        root = ET.fromstring(r.read())
    base = location
    for el in root.iter():
        if _local(el.tag) == "URLBase" and (el.text or "").strip():
            base = el.text.strip()
    for want in _WAN_SERVICES:
        for svc in root.iter():
            if _local(svc.tag) != "service":
                continue
            fields = {_local(c.tag): (c.text or "").strip() for c in svc}
            if fields.get("serviceType") == want and fields.get("controlURL"):
                url = urllib.parse.urljoin(base, fields["controlURL"])
                if urllib.parse.urlparse(url).hostname != urllib.parse.urlparse(location).hostname:
                    raise PortMapError("UPnP: control URL is not on the router")
                return url, want
    raise PortMapError("UPnP: the router offers no WAN connection service")


class Upnp:
    def __init__(self, control: str, service: str, timeout: float = 5):
        self.control, self.service, self.timeout = control, service, timeout
        self.router = urllib.parse.urlparse(control).hostname or ""

    def _soap(self, action: str, args: dict) -> dict:
        body = "".join(f"<{k}>{v}</{k}>" for k, v in args.items())
        envelope = (
            '<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            f'<s:Body><u:{action} xmlns:u="{self.service}">{body}</u:{action}>'
            "</s:Body></s:Envelope>").encode("utf-8")
        req = urllib.request.Request(self.control, data=envelope, method="POST", headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{self.service}#{action}"'})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                root = ET.fromstring(r.read())
        except urllib.error.HTTPError as e:
            try:
                root = ET.fromstring(e.read())
                code = next((el.text for el in root.iter()
                             if _local(el.tag) == "errorCode"), None)
                desc = next((el.text for el in root.iter()
                             if _local(el.tag) == "errorDescription"), "")
            except ET.ParseError:
                code, desc = str(e.code), ""
            raise PortMapError(f"UPnP {action}: error {code} {desc}".strip()) from None
        return {_local(el.tag): (el.text or "") for el in root.iter()}

    def external_ip(self) -> str | None:
        return self._soap("GetExternalIPAddress", {}).get("NewExternalIPAddress") or None

    def map(self, port: int, lease_s: int = LEASE_S) -> Mapping:
        client = local_ip_towards(self.router)
        args = {"NewRemoteHost": "", "NewExternalPort": port, "NewProtocol": "TCP",
                "NewInternalPort": port, "NewInternalClient": client,
                "NewEnabled": 1, "NewPortMappingDescription": DESCRIPTION,
                "NewLeaseDuration": lease_s}
        try:
            self._soap("AddPortMapping", args)
        except PortMapError as e:
            if "725" not in str(e):            # OnlyPermanentLeasesSupported
                if "718" in str(e):
                    raise PortMapError(
                        f"UPnP: port {port} is already forwarded to another "
                        f"computer on the router") from None
                raise
            args["NewLeaseDuration"] = lease_s = 0
            self._soap("AddPortMapping", args)
        m = Mapping("UPnP", port, port, lease_s)
        try:
            m.external_ip = self.external_ip()
        except PortMapError:
            pass
        return m

    def unmap(self, port: int) -> None:
        self._soap("DeletePortMapping", {"NewRemoteHost": "", "NewExternalPort": port,
                                         "NewProtocol": "TCP"})


# ── The part EDLD runs ────────────────────────────────────────────────────────

class PortMapper:
    """Map the port, keep it mapped, and unmap it on stop.

    ``status`` is a sentence for the preferences page and the log: what was
    mapped, how, and what the router said its external address is — or why
    nothing was.
    """

    def __init__(self, port: int, *, log: Callable[[str], None] | None = None,
                 alert: Callable[[str], None] | None = None,
                 gateway: str | None = None, pmp_port: int = 5351,
                 ssdp_target=SSDP_ADDR, ssdp_timeout: float = 2.5,
                 pmp_timeout: float = 0.25):
        self.port = port
        self._log = log or (lambda m: None)
        self._alert = alert or (lambda m: None)
        self._gateway = gateway
        self._pmp_port = pmp_port
        self._ssdp_target = ssdp_target
        self._ssdp_timeout = ssdp_timeout
        self._pmp_timeout = pmp_timeout
        self._stop = threading.Event()
        self._client = None
        self.mapping: Mapping | None = None
        self.status = "not started"

    def start(self) -> None:
        threading.Thread(target=self._run, name="edld-portmap", daemon=True).start()

    def map_once(self) -> Mapping:
        errors = []
        gw = self._gateway or default_gateway()
        if gw:
            try:
                pmp = NatPmp(gw, self._pmp_port, first_timeout=self._pmp_timeout)
                m = pmp.map(self.port)
                self._client = pmp
                return m
            except (PortMapError, OSError) as e:
                errors.append(str(e))
        try:
            for loc in ssdp_search(self._ssdp_timeout, self._ssdp_target):
                try:
                    url, svc = control_url(loc)
                    up = Upnp(url, svc)
                    m = up.map(self.port)
                    self._client = up
                    return m
                except (PortMapError, OSError, ET.ParseError) as e:
                    errors.append(str(e))
            if not any(e.startswith("UPnP") for e in errors):
                errors.append("UPnP: no router answered the search")
        except OSError as e:
            errors.append(f"UPnP: {e}")
        raise PortMapError("; ".join(errors) or "no method available")

    def _describe(self, m: Mapping) -> str:
        where = f" — router's external address {m.external_ip}" if m.external_ip else ""
        lease = "permanent until EDLD exits" if m.lease_s == 0 else f"renewed every {m.lease_s // 2 // 60} min"
        return f"Port {m.external_port} forwarded by {m.method} ({lease}){where}"

    def _run(self) -> None:
        reported = None
        while not self._stop.is_set():
            try:
                m = self.map_once()
                self.mapping = m
                self.status = self._describe(m)
                if reported != "ok":
                    self._log(f"[server] {self.status}")
                    if behind_second_nat(m.external_ip):
                        warn = (f"The router reports a private external address "
                                f"({m.external_ip}): your provider or a second "
                                f"router is doing NAT too, so port forwarding "
                                f"cannot reach this computer from outside. See "
                                f"docs/SERVER.md on CGNAT.")
                        self.status += " — but see the warning about CGNAT"
                        self._log(f"[server] {warn}")
                        self._alert(warn)
                    reported = "ok"
                wait = (m.lease_s // 2) if m.lease_s else 1800
            except Exception as e:
                self.mapping = None
                self.status = f"Could not forward port {self.port}: {e}"
                if reported != self.status:
                    self._log(f"[server] {self.status}")
                    self._alert(f"Port forwarding failed: {e}. Forward port "
                                f"{self.port} on the router by hand, or see "
                                f"docs/SERVER.md.")
                    reported = self.status
                wait = 600
            self._stop.wait(max(60, wait))

    def stop(self) -> None:
        self._stop.set()
        client, self._client = self._client, None
        if client is not None and self.mapping is not None:
            try:
                client.unmap(self.port)
                self._log(f"[server] removed the port {self.port} forward")
            except Exception as e:
                self._log(f"[server] could not remove the port forward: {e}")
        self.mapping = None
