"""
gui/funding.py — "Support EDLD Development" bar.

A single quiet strip carrying the three funding destinations from
``.github/FUNDING.yml`` as clickable icons, separated by thin rules.  It reads
that file at runtime rather than hard-coding the URLs, so the funding
configuration has exactly one home and the bar cannot drift out of step with
what GitHub's own Sponsor button offers.

The design brief was "visible but not obnoxious": small monochrome glyphs in
the muted text colour that pick up the accent on hover, on the same bar as the
status line rather than anywhere near the dashboard data.  Nothing animates,
nothing nags, and the bar can be hidden from the View menu.

Icons are recoloured at load time to the active theme's colours, which is why
they ship as SVG with ``currentColor`` fills rather than as PNGs.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from core.palette import rgb

_RES = Path(__file__).parent / "resources"

#: Icon file and display name per funding key understood by FUNDING.yml.
_KNOWN = {
    "patreon": ("patreon.svg", "Patreon", "https://www.patreon.com/{}"),
    "ko_fi":   ("kofi.svg",    "Ko-fi",   "https://ko-fi.com/{}"),
}

#: Icon size in the bar.  Large enough to be recognisable, small enough that
#: the bar reads as chrome rather than as a call to action.
_ICON_PX = 16


def _funding_file() -> Path:
    return Path(__file__).resolve().parents[1] / ".github" / "FUNDING.yml"


def parse_funding(path: Path | None = None) -> list[tuple[str, str, str]]:
    """Return ``[(icon_file, label, url), …]`` parsed from FUNDING.yml.

    A deliberately small parser rather than a YAML dependency: the file has a
    fixed three-line shape that the GitHub schema pins down, and adding PyYAML
    to ship one config read would be a poor trade.  Anything unrecognised is
    skipped, so a key added upstream cannot break the bar.
    """
    p = path or _funding_file()
    out: list[tuple[str, str, str]] = []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return out

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if key in _KNOWN:
            icon, label, url_tmpl = _KNOWN[key]
            handle = value.strip("[]\"' ")
            if handle:
                out.append((icon, label, url_tmpl.format(handle)))
        elif key == "custom":
            # custom: ["https://paypal.me/…"] — possibly several entries.
            for url in re.findall(r'https?://[^\s"\',\]]+', value):
                label = "PayPal" if "paypal" in url.lower() else "Donate"
                icon = "paypal.svg" if "paypal" in url.lower() else "kofi.svg"
                out.append((icon, label, url))
    return out


def _coloured_icon(svg_name: str, colour: str, hover: str) -> QIcon:
    """Render an SVG at two colours into a single QIcon.

    ``currentColor`` in the source is substituted textually before handing the
    markup to the renderer — Qt's SVG module does not implement
    ``currentColor`` itself, so a file relying on it would otherwise render
    black on a black bar.
    """
    icon = QIcon()
    try:
        src = (_RES / svg_name).read_text(encoding="utf-8")
    except OSError:
        return icon

    for state_colour, mode in ((colour, QIcon.Normal), (hover, QIcon.Active)):
        markup = src.replace("currentColor", state_colour)
        renderer = QSvgRenderer(markup.encode("utf-8"))
        pix = QPixmap(_ICON_PX * 2, _ICON_PX * 2)   # 2× for HiDPI
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pix, mode)
    return icon


class SupportBar(QWidget):
    """The "Support EDLD Development" strip."""

    def __init__(self, theme: str = "default", parent: QWidget | None = None,
                 program: str = "EDLD") -> None:
        super().__init__(parent)
        self.setObjectName("supportBar")
        c = rgb(theme)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(6)

        heading = QLabel(f"Support {program} Development")
        heading.setObjectName("supportLabel")
        lay.addWidget(heading)
        lay.addSpacing(4)

        entries = parse_funding()
        for i, (icon_file, label, url) in enumerate(entries):
            if i:
                lay.addWidget(self._separator(c))
            lay.addWidget(self._link_button(icon_file, label, url, c))

        lay.addStretch(1)

        if not entries:
            # No funding file, or nothing parseable in it.  The bar collapses
            # rather than showing a heading with nothing under it.
            self.setVisible(False)

    def _separator(self, c: dict) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        sep.setFixedHeight(_ICON_PX)
        sep.setStyleSheet(f"background:{c['border']}; border:none;")
        return sep

    def _link_button(self, icon_file: str, label: str, url: str,
                     c: dict) -> QPushButton:
        btn = QPushButton()
        btn.setProperty("role", "link")
        btn.setIcon(_coloured_icon(icon_file, c["dim"], c["accent"]))
        btn.setIconSize(QSize(_ICON_PX, _ICON_PX))
        btn.setFlat(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(f"{label} — {url}")
        btn.setAccessibleName(f"Support development via {label}")
        btn.setFixedSize(QSize(_ICON_PX + 10, _ICON_PX + 6))
        btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        return btn
