# Building EDLD

## Running from source

EDLD runs directly from a checkout with no build step.

```sh
git clone https://github.com/drworman/EDLD.git
cd EDLD
pip install -r requirements.txt
python edld.py            # terminal dashboard (default)
python edld.py --gui      # desktop window
python edld.py --terminal # scrolling event log
```

The three interfaces read the same journal, the same config and the same
per-commander data, so you can switch freely between them.

### Optional dependencies

- **PySide6** is needed only for `--gui`. Without it the terminal modes work
  normally and `--gui` exits with an explanatory message.
- **Textual** is needed only for `--tui`. Without it `--terminal` still works.
- **psutil** is needed only for session management. Install it from your distro
  package manager rather than pip — it has C extensions:
  `sudo pacman -S python-psutil` / `sudo apt install python3-psutil` /
  `sudo dnf install python3-psutil`.

## Building a binary

```sh
pip install -r requirements-dev.txt
pyinstaller packaging/edld.spec --noconfirm --clean
```

The artefact lands in `dist/` — `dist/EDLD` on Linux, `dist/EDLD.exe` on
Windows, `dist/EDLD.app` on macOS.

Verify it starts, and that both interfaces load:

```sh
./dist/EDLD --version     # should print the contents of core/version
./dist/EDLD --selftest    # imports each front end and reports
```

Both matter. `--version` proves the process starts; `--selftest` proves the
interfaces are actually intact. A packaged build can start perfectly and still
be missing a module that only fails when the dashboard is drawn — Textual
resolves its widgets through a runtime `__getattr__`, which static analysis
cannot follow, so this has happened. The release workflow runs both on every
platform.

### Linux runtime libraries

Qt needs a handful of X libraries present at runtime. On a bare CI image:

```sh
sudo apt-get install -y libegl1 libxkbcommon-x11-0 libxcb-cursor0 \
  libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-randr0 \
  libxcb-render-util0 libxcb-xinerama0
```

Add `xvfb` if you want to run the GUI headlessly.

### Relinking against your own Qt

This is the LGPLv3 4(d)(1) route, and it is deliberately easy — see
[LICENSING.md](LICENSING.md).

```sh
pip install --force-reinstall /path/to/your/PySide6-wheel
pyinstaller packaging/edld.spec --noconfirm --clean
```

Nothing in the spec pins a Qt version or links it statically, so the binary you
get is equivalent to the official one but built against your Qt.

### A directory layout instead of one file

The spec produces a single file. If you would rather have the Qt shared
libraries as visibly separate files, build with `-D`:

```sh
pyinstaller packaging/edld.spec --noconfirm --clean -D
```

## What the bundle carries beyond the code

Three things are shipped as data because the code alone is not enough:

- **`components/`** — the component sources, in addition to being compiled in.
  `core/plugin_loader.py` discovers components by globbing that directory and
  loads each by file path, giving every one its own namespace and a sandboxed
  `open()`. That needs real files on disk, which a one-file build does not
  otherwise have.
- **A CA bundle** (`certifi`) — a frozen binary carries its own OpenSSL, built
  with the build machine's certificate paths compiled in. Those paths rarely
  exist on the target machine, so without a bundled store every HTTPS call
  fails verification and CAPI, EDDN, EDSM, EDAstro, Inara and Spansh all stop
  working with no visible error. `core/certs.py` points OpenSSL at the bundled
  copy at startup.
- **`licenses/`** — required to accompany the binary by LGPLv3 section 4(b).

Each has already been the cause of a build that looked fine and was not.

## Why the spec lists so many hidden imports

`core/plugin_loader.py` discovers components by walking `components/` at
runtime, and both front ends resolve their dashboard blocks by name. None of
that is visible to PyInstaller's static analysis, so every component and block
is named explicitly in `packaging/build_common.py`, which enumerates the
directories rather than hard-coding a list.

A component missing from that list produces a binary that builds cleanly, starts
cleanly, and shows an empty dashboard. That failure mode is the reason the
release workflow smoke-tests every artefact before publishing it.

Textual is collected wholesale for the same reason from the other direction:
`textual.widgets` imports lazily by a name built at runtime, so nothing static
analysis can see refers to most of its widgets.

## Releases

Tag with a bare `YYYYMMDD` datestamp matching `core/version`:

```sh
echo 20260811 > core/version
git commit -am "Release 20260811"
git tag 20260811
git push origin main --tags
```

The `Release` workflow checks the tag matches the version file, verifies the
checkout contains everything the build needs, then builds and smoke-tests
binaries for Linux, Windows and macOS, signs the artefacts, and publishes a
release with notes taken from `CHANGELOG.md` and checksums attached.

A version with a suffix — `20260811-rc1` — is published as a prerelease. To
build everything without publishing, run the workflow manually from the Actions
tab with `dry_run` left on.
