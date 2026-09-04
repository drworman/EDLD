"""
gui/about.py — About dialog.

Carries three things that have to be here rather than anywhere else:

  * what the program is, and where its source lives (GitHub);
  * the funding links, repeated from the support bar so they are findable
    even with the bar hidden;
  * the third-party attribution LGPLv3 section 4(c) requires — the clause
    says notices must appear "among" the application's own copyright
    notices, and this dialog is where EDLD shows those.

See docs/LICENSING.md for how the rest of the LGPL conditions are met.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QVBoxLayout,
)

from core.palette import rgb
from gui.funding import SupportBar
from gui.theme import stylesheet


def _rule() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setProperty("role", "rule")
    line.setFixedHeight(1)
    return line


class AboutDialog(QDialog):
    """The 'about' window, including attribution and funding notices."""

    def __init__(self, parent, program: str, version: str, author: str,
                 github_repo: str, theme: str = "default") -> None:
        super().__init__(parent)
        c = rgb(theme)
        repo_url = f"https://github.com/{github_repo}"

        self.setWindowTitle(f"About {program}")
        self.setMinimumWidth(520)
        self.setStyleSheet(stylesheet(theme))
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        title = QLabel(program)
        title.setObjectName("aboutTitle")
        lay.addWidget(title)

        subtitle = QLabel(f"version {version}  ·  by {author}")
        subtitle.setObjectName("aboutSubtitle")
        lay.addWidget(subtitle)

        lay.addWidget(_rule())

        blurb = QLabel(
            "A live dashboard for Elite Dangerous.\n\n"
            "EDLD reads the journal files the game writes to your local "
            "filesystem and presents commander, ship, exploration, "
            "exobiology, trade, mission, colonisation and PowerPlay state as "
            "it happens. It runs as a terminal dashboard, a scrolling "
            "terminal log, or this desktop window."
        )
        blurb.setWordWrap(True)
        lay.addWidget(blurb)

        # ── Project home ──────────────────────────────────────────────────────
        project = QLabel(
            f'Project home: <a href="{repo_url}" '
            f'style="color:{c["accent"]}">{github_repo}</a>'
        )
        project.setTextFormat(Qt.RichText)
        project.setOpenExternalLinks(False)
        project.linkActivated.connect(lambda u: QDesktopServices.openUrl(QUrl(u)))
        lay.addWidget(project)

        lay.addWidget(_rule())

        # ── Funding ───────────────────────────────────────────────────────────
        support = SupportBar(theme=theme, program=program)
        lay.addWidget(support)

        lay.addWidget(_rule())

        # ── Attribution ───────────────────────────────────────────────────────
        # LGPLv3 4(a) and 4(c): name the library, state the licence, and point
        # at the bundled texts.
        notices = QLabel(
            "Elite Dangerous is a trademark of Frontier Developments plc. "
            f"{program} is an unofficial community tool, not affiliated with, "
            "endorsed by, or supported by Frontier Developments.\n\n"
            f"{program} is released under the MIT licence. The desktop "
            "interface uses Qt for Python (PySide6) under the LGPL v3; the "
            "terminal interface uses Textual under the MIT licence. Full "
            "licence texts ship in the licenses/ directory of every release "
            "archive, and THIRD-PARTY-NOTICES.md lists every dependency with "
            "relinking instructions."
        )
        notices.setWordWrap(True)
        notices.setProperty("role", "dim")
        lay.addWidget(notices)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)
