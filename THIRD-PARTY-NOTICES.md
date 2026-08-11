# Third-party notices

ED Live Dashboard (EDLD) is distributed under the MIT licence (see `LICENSE`).
It incorporates or depends on the components listed below. Where a licence
requires its text to accompany distribution, that text is in `licenses/` and
ships inside every release archive and every binary.

| Component | Licence | Used by | Bundled in binaries |
|---|---|---|---|
| **PySide6 / Qt** | **LGPL v3** | desktop interface (`--gui`) | yes |
| **Textual** | MIT | terminal dashboard (`--tui`) | yes |
| **Rich** | MIT | pulled in by Textual | yes |
| **discord-webhook** | MIT | Discord notifications | yes |
| **cryptography** | Apache 2.0 | Frontier CAPI token storage | yes |
| **psutil** | BSD 3-Clause | session management (optional) | only when installed |
| **PyInstaller** | GPL 2.0 with bootloader exception | build tool | no — not shipped |

Only PySide6 constrains how EDLD is packaged. See
[docs/LICENSING.md](docs/LICENSING.md) for the full reasoning and for how each
LGPLv3 condition is met.

## Qt for Python (PySide6)

Copyright © The Qt Company Ltd. Licensed under the GNU Lesser General Public
License version 3. The full texts are bundled:

- `licenses/LGPL-3.0-only.txt`
- `licenses/GPL-3.0-only.txt` (LGPLv3 incorporates the GPLv3 by reference)

Qt is **never statically linked**. PyInstaller stores the Qt shared libraries
inside the executable's archive; they are extracted to a temporary directory at
launch and loaded dynamically by the operating system's normal mechanism. You
may replace them with your own build of Qt — see
[docs/BUILDING.md](docs/BUILDING.md) for the commands.

## Textual and Rich

Copyright © Will McGugan and contributors. MIT licence. Used for the terminal
dashboard and for the console markup the dashboard blocks emit.

## Elite Dangerous

Elite Dangerous is a trademark of Frontier Developments plc. EDLD reads the
journal files the game writes to the local filesystem, in the documented format
Frontier publishes for exactly this purpose. It does not modify the game, inject
code, read process memory, or interact with Frontier's servers other than
through the Companion API using the commander's own credentials.

EDLD is an unofficial community tool, not affiliated with, endorsed by, or
supported by Frontier Developments plc.
