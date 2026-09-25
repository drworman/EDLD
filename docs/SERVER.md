# Server mode — EDLD for the EDAM mobile client

EDLD can serve what it knows to your phone or tablet. The EDAM app shows your
commander, squadron and ship across the top, and the Status, Cargo, Session,
Career and Alerts panels below, the same figures the dashboards show. It is
made for glancing at: open the app, see where things stand, put the phone away.

> **Status: experimental.** This lives on the `exp/server-mode` branch. The
> protocol may change before it reaches `main`.

---

## Starting it

```bash
edld -s                  # terminal event log, plus the server
edld -s --tui            # terminal dashboard, plus the server
edld -s --gui            # desktop window, plus the server
edld -s --headless       # no interface at all, for running as a service
```

`-s` on its own runs the terminal event log. Name an interface and you get
that interface and the server, in one process. Setting `Enabled = true` in
`[Server]` does the same as passing `-s` every time.

`--headless` prints nothing after startup; diagnostics go to the log file named
on its first line. It is what to use for a service:

- **Linux:** a `systemd --user` unit running `edld -s --headless`.
- **Windows:** a Task Scheduler task triggered *At log on* for your own
  account, running `EDLD.exe -s --headless`. Not a Windows Service: a service
  runs in another session as another account and cannot see your Saved Games
  folder. Keep EDLD in the same folder across updates — Windows Firewall ties
  its rule to the program's path and will ask again if it moves.

If the server cannot start — the port is taken, a package is missing — EDLD
says so on the terminal, in the log and in the Alerts pane, and carries on
without it.

## Settings

```toml
[Server]
Enabled         = false
Port            = 28510
BindAddress     = ""        # blank: every interface, IPv6 and IPv4
ExternalHost    = ""        # e.g. yourname.duckdns.org
AllowEndSession = false
```

Each profile is its own server, with its own identity and its own paired
devices, so two profiles running at once need two ports:
`EDP2.Server.Port = 28511` in the profile section.

## Pairing a device

Run this on the computer, in a second terminal if EDLD is already running:

```bash
edld --pair              # or: edld -p PROFILE --pair
```

It prints a QR code, a one-time code, the server's fingerprint, the addresses
it found, and a link. In EDAM, choose **Add computer** and scan the code, or
paste the link. The app shows the addresses it will try and lets you add or
change them before saving, because only you know how your network is set up.

If `ExternalHost` is not set, `--pair` asks for the address to use away from
home; leave it blank for this network only. A PNG of the QR code is also
written beside the server's files, for a machine whose console cannot draw it;
it is deleted when the code is used or expires.

The code is valid for five minutes, works once, and is destroyed after five
wrong attempts. Running `--pair` again replaces it.

```bash
edld --paired            # list paired devices
edld --unpair hNzebMq-   # remove one, by the ID --paired shows
```

A running EDLD disconnects an unpaired device within a few seconds; nothing
needs restarting.

## Reaching EDLD

**On the same network** nothing else is needed. The app tries the addresses in
the pairing code in order.

**Away from home**, the app needs an address that reaches your computer from
the internet:

1. **A name that follows your address.** Your home address can change;
   [DuckDNS](https://www.duckdns.org) gives you a free name, such as
   `yourname.duckdns.org`, and keeps it pointed at your address. Set it up by
   following DuckDNS's own instructions for your system, then put the name in
   `ExternalHost`.
2. **A forwarded port.** In your router's settings, forward TCP port 28510 (or
   whatever `Port` is) to this computer's LAN address. Routers name this
   *port forwarding*, *virtual server* or *NAT rules*.
3. Pair again, or edit the address in the app.

If the phone works on Wi-Fi at home but not away, the forward is the thing to
check. If it works away but not at home using the DuckDNS name, your router
does not support *NAT loopback*; that is why the app keeps your LAN address
too and tries both.

**If your provider uses CGNAT** — common with Starlink, 4G/5G home internet
and some fibre providers — no router setting can make your computer reachable
from outside. Some providers give you a public address on request. Otherwise,
install [Tailscale](https://tailscale.com) (free for personal use) on the
computer and the phone, and put the computer's Tailscale name or address in
`ExternalHost`. IPv6, where both ends have it, can also avoid the problem.

## Security

- Everything is encrypted with TLS 1.3.
- The phone trusts EDLD because the pairing code carried EDLD's public-key
  fingerprint. An impostor on the network cannot present that key, so the very
  first connection is safe even on public Wi-Fi.
- EDLD trusts the phone because the phone's own key was registered while you
  held a valid code. A device that was never paired, or has been unpaired, is
  refused during the TLS handshake, before it can send a single message.
- The only thing an unpaired connection can do is offer a pairing code, and
  only while one from `--pair` is open.
- **Ending the game session** from a device is off unless `AllowEndSession` is
  true, and even then only works in Solo, the same rule session management
  applies to its own triggers. The device must confirm, and the reason is
  recorded as *ended from <device name>*.
- EDLD never looks for devices, never scans your network and never contacts
  `ExternalHost`: it answers devices that come to it. Its own LAN address is
  found by asking the operating system which interface it would use, which
  sends nothing.
- Nothing is sent anywhere except to devices you paired. Indevlin runs no
  service in between.

Files, per profile, in `<data dir>/server/<profile>/`:

| File | What |
|---|---|
| `server.key` | EDLD's private key (owner-only permissions) |
| `server.crt` | EDLD's certificate, whose key the devices pin |
| `devices.json` | paired devices: name, key fingerprint, certificate, dates |
| `pairing.json` | the open pairing code, hashed; present only while one is open |

Deleting the directory unpairs every device and gives EDLD a new identity.

---

## Protocol, version 1

TLS 1.3 over TCP. One JSON object per line, UTF-8, no line longer than 1 MiB.
Every message has a type, `t`. `scripts/edld_client.py` is a working client.

### Pairing link

`edld://pair?v=1&n=<name>&fp=<fingerprint>&c=<code>&h=<host:port>[&h=...]`

`fp` is base64url (no padding) of the SHA-256 of the server certificate's DER
SubjectPublicKeyInfo. IPv6 hosts are bracketed.

### Pairing

On a connection presenting **no** client certificate, having checked the
server's key against `fp`:

```json
→ {"t":"pair","v":1,"code":"ABCDE12345","name":"Pixel 8","cert":"<base64 DER>"}
← {"t":"paired","device":{"id":"hNzebMq-","name":"Pixel 8"},
   "server":{"name":"EDLD on devstation01 (EDP1)","fingerprint":"..."}}
```

or `{"t":"error","code":...}` with `no-ticket`, `expired`, `wrong-code`,
`locked` or `bad-cert`. The server closes the connection either way. The
certificate must be EC P-256/384/521, RSA of 2048 bits or more, or Ed25519,
and inside its validity dates; self-signed is expected.

### Session

Connect presenting the device certificate, then:

```json
→ {"t":"hello","v":1,"app":"edamc","appVersion":"0.1.0"}
← {"t":"welcome","v":1,"server":{"name":...,"edld":"20260923"},
   "device":{"id":...,"name":...},"features":["snapshot","panels","end_session"]}
← {"t":"snapshot","v":1,"seq":12,"ts":"...","header":{...},"panels":[...]}
← {"t":"panels","seq":13,"ts":"...","upsert":[...],"remove":["id"],"header":{...}}
```

A `panels` message carries whole panels that changed, the ids of panels that
went away, and the header only if it changed. It is sent only when something
changed. Apply them in `seq` order; if one is missed, send
`{"t":"snapshot"}` for a fresh copy.

The client sends `{"t":"ping","id":n}` every 30 s (answered with
`{"t":"pong","id":n}`); a connection silent for 90 s is closed. Send
`{"t":"bye"}` before leaving.

### Header

```json
{"cmdr":"MERRICK CALBRUIN",
 "squadron":{"name":"MINING AND LOGISTICS LTD","tag":"MALL","rank":"Executive Director"},
 "ship":{"name":"Prospect","ident":"MC-01","type":"Type-10 Defender"},
 "system":"Sol","location":"Abraham Lincoln","mode":"Solo",
 "game":{"running":true,"lastEvent":"2026-09-24T18:52:15+00:00"},
 "monitorError":null,
 "endSession":{"available":false,"reason":"only available in Solo"}}
```

Any of these may be null while EDLD does not know yet. `game.running` is the
authority on whether Elite is running; show "game not running" from it rather
than guessing from the age of `lastEvent`.

### Panels

```json
{"id":"career.combat","title":"Combat","group":"career","order":501,
 "rows":[{"label":"Kills","value":"3,191","rate":null,"kind":"kv"}]}
```

`group` is `status`, `vessel`, `session` or `career`; `order` sorts within the
whole list. Row `kind`: `kv` label and value, `sub` a sub-heading, `line` a
full-width line of text in `value`. `rate` is an optional right-hand figure
such as `22.5 /hr`. An alert row carries `ts`, when it happened, for the
client to show as "4m ago". Values arrive formatted; the client displays them
as given.

### Commands

```json
→ {"t":"cmd","id":1,"cmd":"end_session","confirm":true}
← {"t":"result","id":1,"ok":true}
← {"t":"result","id":1,"ok":false,"error":"refused","message":"only available in Solo"}
```

### Errors

`{"t":"error","code":...,"message":...}`: `not-paired`, `already-paired`,
`revoked`, `version`, `protocol`, `unknown`. After `not-paired` or `revoked`,
the device should forget the pairing and offer to pair again.
