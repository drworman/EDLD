"""
core/server — EDLD's server mode, for the EDAM mobile client.

A paired device connects, receives a snapshot of what EDLD knows, and then
receives changes for as long as it stays connected.  Nothing is pushed to a
device that is not connected, nothing leaves the machine except to a device the
commander paired, and EDLD never looks for devices: it only answers the ones
that come to it.

Modules
-------
identity   the server's key and certificate, and fingerprints
pairing    one-time pairing tickets, the paired-device registry, pairing links
protocol   message framing and the snapshot/panel model sent to devices
service    the listener, per-connection handling, and change publishing

See docs/SERVER.md for the protocol and the security model.
"""

PROTOCOL_VERSION = 1
