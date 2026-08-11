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

Verify it starts:

```sh
./dist/EDLD --version     # should print the contents of core/version
```

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

## Why the spec lists so many hidden imports

`core/plugin_loader.py` discovers components by walking `components/` at
runtime, and both front ends resolve their dashboard blocks by name. None of
that is visible to PyInstaller's static analysis, so every component and block
is named explicitly in `packaging/build_common.py`, which enumerates the
directories rather than hard-coding a list.

A component missing from that list produces a binary that builds cleanly, starts
cleanly, and shows an empty dashboard. That failure mode is the reason the
release workflow smoke-tests every artefact before publishing it.

## Releases

Tag with a bare `YYYYMMDD` datestamp matching `core/version`:

```sh
echo 20260810 > core/version
git commit -am "Release 20260810"
git tag 20260810
git push origin main --tags
```

The `Release` workflow verifies the tag matches the version file, builds and
smoke-tests binaries for Linux, Windows and macOS, signs the source tarball, and
publishes everything with checksums.
