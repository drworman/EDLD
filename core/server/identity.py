"""
core/server/identity.py — the server's key pair and certificate.

Each profile gets its own identity, generated on first use and kept beside the
paired-device registry.  Devices do not trust it because a CA vouches for it;
they trust it because its fingerprint was in the QR code they scanned.  That is
why the certificate is self-signed, long-lived, and never needs a hostname: the
pin is on the public key, so the same pairing works whether the device reaches
EDLD by LAN address, DuckDNS name or IPv6.

The fingerprint is the SHA-256 of the DER SubjectPublicKeyInfo, base64url
without padding.  Pinning the key rather than the certificate means a future
re-issue of the certificate over the same key does not break any pairing.

``cryptography`` is imported lazily: a user who never enables server mode never
needs it, and one who does gets a sentence saying what to install rather than
an ImportError at startup.
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import os
import socket
from dataclasses import dataclass
from pathlib import Path

KEY_FILE = "server.key"
CERT_FILE = "server.crt"


class ServerDependencyError(RuntimeError):
    """A package server mode needs is not installed."""


def _crypto():
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, rsa, ed25519
        from cryptography.x509.oid import NameOID
    except ImportError as exc:                          # pragma: no cover
        raise ServerDependencyError(
            "Server mode needs the 'cryptography' package: "
            "pip install cryptography  (Arch: pacman -S python-cryptography)"
        ) from exc
    return x509, hashes, serialization, ec, rsa, ed25519, NameOID


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def spki_fingerprint_der(cert_der: bytes) -> str:
    """Fingerprint of a certificate's public key: SHA-256 over the SPKI."""
    x509, _h, serialization, *_ = _crypto()
    cert = x509.load_der_x509_certificate(cert_der)
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return b64url(hashlib.sha256(spki).digest())


def short_id(fingerprint: str) -> str:
    """The first eight characters, which is what a person reads and types."""
    return fingerprint[:8]


def describe_device_cert(cert_der: bytes) -> tuple[bool, str]:
    """Is this certificate acceptable as a device identity?

    Accepts the key types Android's keystore produces (EC P-256 by default)
    and anything at least as strong.  Returns ``(ok, reason)``.
    """
    x509, _h, _s, ec, rsa, ed25519, _n = _crypto()
    try:
        cert = x509.load_der_x509_certificate(cert_der)
    except Exception as exc:
        return False, f"not a certificate ({type(exc).__name__})"
    key = cert.public_key()
    if isinstance(key, ec.EllipticCurvePublicKey):
        if key.curve.name not in ("secp256r1", "secp384r1", "secp521r1"):
            return False, f"unsupported curve {key.curve.name}"
    elif isinstance(key, rsa.RSAPublicKey):
        if key.key_size < 2048:
            return False, f"RSA key too small ({key.key_size} bits)"
    elif not isinstance(key, ed25519.Ed25519PublicKey):
        return False, f"unsupported key type {type(key).__name__}"
    now = _dt.datetime.now(_dt.timezone.utc)
    try:
        not_after = cert.not_valid_after_utc
        not_before = cert.not_valid_before_utc
    except AttributeError:                              # cryptography < 42
        not_after = cert.not_valid_after.replace(tzinfo=_dt.timezone.utc)
        not_before = cert.not_valid_before.replace(tzinfo=_dt.timezone.utc)
    if not (not_before <= now <= not_after):
        return False, "certificate is outside its validity period"
    return True, ""


def der_to_pem(cert_der: bytes) -> str:
    body = base64.encodebytes(cert_der).decode("ascii")
    return f"-----BEGIN CERTIFICATE-----\n{body}-----END CERTIFICATE-----\n"


@dataclass
class Identity:
    directory: Path
    key_path: Path
    cert_path: Path
    fingerprint: str
    name: str
    created: bool = False       # generated during this call


def default_server_name(profile: str | None) -> str:
    host = socket.gethostname().split(".")[0] or "this computer"
    return f"EDLD on {host}" + (f" ({profile})" if profile else "")


def _write_private(path: Path, data: bytes) -> None:
    """Write a file readable by its owner only, before any bytes land in it."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(path), flags, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_or_create(directory: Path, name: str) -> Identity:
    """Load this profile's identity, generating one the first time."""
    x509, hashes, serialization, ec, _r, _e, NameOID = _crypto()
    directory.mkdir(parents=True, exist_ok=True)
    key_path = directory / KEY_FILE
    cert_path = directory / CERT_FILE
    created = False

    if not (key_path.is_file() and cert_path.is_file()):
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name[:64])])
        now = _dt.datetime.now(_dt.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - _dt.timedelta(days=1))
            .not_valid_after(now + _dt.timedelta(days=365 * 25))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                           critical=True)
            .sign(key, hashes.SHA256())
        )
        _write_private(key_path, key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        created = True

    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    fp = spki_fingerprint_der(cert.public_bytes(serialization.Encoding.DER))
    return Identity(directory, key_path, cert_path, fp, name, created)
