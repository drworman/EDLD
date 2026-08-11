# Licensing

**Short version:** EDLD is MIT. You can do essentially anything with it. The one
obligation that needs care is Qt's LGPL, and it is met by publishing the source
and shipping the licence texts.

## EDLD itself — MIT

Everything in this repository written for EDLD is under the
[MIT licence](../LICENSE). Use it, fork it, sell it, embed it in something
proprietary. Keep the copyright notice.

## Dependencies

| Component | Licence | Bundled in binaries |
|---|---|---|
| PySide6 / Qt | **LGPL v3** | yes |
| Textual | MIT | yes |
| Rich | MIT | yes |
| discord-webhook | MIT | yes |
| cryptography | Apache 2.0 | yes |
| psutil | BSD 3-Clause | yes |
| certifi | MPL 2.0 | yes — CA bundle, shipped unmodified as data |
| PyInstaller | GPL 2.0 with bootloader exception | build tool only, not shipped |

Only PySide6 constrains how EDLD is packaged. certifi is MPL 2.0, whose
copyleft is file-level: it attaches to the covered files, not to a work that
ships alongside them, and the bundle is included unmodified as data. It places
no condition on EDLD's own licence.

## Why PySide6 and not PyQt

PyQt6 is GPL-or-commercial. Using it would force EDLD itself to be GPL, which
conflicts with keeping the project permissive.

PySide6 is Qt's own binding and is **LGPL v3**. The LGPL explicitly permits a
work under any licence — MIT included — to use the library, subject to
conditions that are straightforward for a project like this one.

## Meeting the LGPL

LGPLv3 section 4 governs a "Combined Work" — an application that uses an LGPL
library. Its conditions, and how EDLD meets each:

**4(a) — Give notice that the library is used.**
`THIRD-PARTY-NOTICES.md` and the About dialog in the desktop interface.

**4(b) — Include a copy of the GPL and the LGPL.**
`licenses/LGPL-3.0-only.txt` and `licenses/GPL-3.0-only.txt` are bundled inside
every binary and included in every release archive. A hyperlink does not satisfy
this; an actual copy is required. This is the condition most often missed.

**4(c) — Display attribution where the application shows copyright notices.**
The About dialog (Help → About) names Qt for Python, states the LGPL, and points
at the bundled texts.

**4(d) — Let the recipient relink against their own Qt.**
Two options; EDLD relies on **4(d)(1)**: convey the application code in a form
that permits recombining it with a modified version of the library.

This is where a Python application is in an unusually comfortable position.
"Relinking" for EDLD is not a link step at all — it is `pip install PySide6` and
`python edld.py --gui`. Since:

- the complete source is public under the MIT licence,
- the exact PyInstaller specification used for the official binaries is in
  `packaging/`, and
- PySide6 is a standard package anyone can install, patch, or build from source,

anyone receiving a binary can rebuild an equivalent one against their own Qt.
[BUILDING.md](BUILDING.md) gives the commands. That satisfies 4(d)(1).

**4(e) — Installation Information.**
Not applicable. This clause applies to User Products with installed firmware,
not to downloadable desktop software.

### On single-file binaries

A single-file PyInstaller build is compatible with all of the above. It does not
statically link Qt: the Qt shared libraries are stored in the executable's
archive, extracted to a temporary directory at launch, and loaded dynamically by
the operating system's normal mechanism.

Two rules keep this true, and both are enforced in `packaging/`:

- **Never statically link Qt.** Nothing in the build does this today; do not add
  it.
- **UPX stays disabled.** It also corrupts signed Qt libraries on Windows, so
  there are two reasons.

### If you fork EDLD and distribute binaries

You inherit the LGPL obligations. Concretely:

1. Keep your source public and genuinely buildable, including your packaging
   configuration.
2. Keep `licenses/` inside your bundles.
3. Keep `THIRD-PARTY-NOTICES.md` accurate for whatever you actually ship.
4. Do not statically link Qt.

If you make your fork's source private, you lose the 4(d)(1) route and must
instead satisfy 4(d)(0), which is considerably more work. Keeping the source
open is by far the easier path.

## A note on the terminal interface

The terminal dashboard uses Textual, which is MIT and carries no such
conditions. A build that ships only `--tui` and `--terminal` would have no LGPL
obligations at all. The official binaries include the desktop interface, so they
do.

## Adding a dependency

Before adding one, check its licence. Acceptable: MIT, BSD, Apache 2.0, ISC, and
similar permissive terms; or LGPL where the library is dynamically linked and the
source stays public.

Not acceptable: GPL or AGPL, which would force EDLD's own licence to change, and
anything with a non-commercial or field-of-use restriction, which would stop it
being open source at all.

Record every addition in `THIRD-PARTY-NOTICES.md`, and add the licence text to
`licenses/` if the licence requires a copy to accompany distribution.

## Elite Dangerous

Elite Dangerous is a trademark of Frontier Developments plc. EDLD reads journal
files the game writes to the local filesystem, in the documented format Frontier
publishes for exactly this purpose. It does not modify the game, inject code, or
read process memory.

EDLD is an unofficial community tool, not affiliated with, endorsed by, or
supported by Frontier Developments plc. Do not imply otherwise in a fork.

## Not legal advice

This document explains the reasoning behind the project's licensing choices. It
was written by the project's contributors, who are not lawyers. If you are
redistributing EDLD in a context where the answer matters commercially, take your
own advice.
