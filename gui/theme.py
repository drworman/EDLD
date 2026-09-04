"""
gui/theme.py — Qt stylesheet built from the shared EDLD palettes.

The GUI renders the same themes as the TUI.  Both read
``core/palette.py``; this module turns a palette into a Qt Style Sheet, the
way ``tui/theme.py`` turns the same palette into Textual CSS.

The visual target is the TUI, not a generic desktop application: dark warm
background, accent-coloured block titles on a bar, key text dim and value text
bright, and health colours carrying the same meaning in both front ends.  A
commander who moves between the two should recognise the dashboard instantly.

Qt Style Sheets support a useful subset of CSS.  Notably absent are custom
properties, so the palette is substituted into an f-string rather than
declared once at the top.
"""

from __future__ import annotations

from core.palette import rgb

#: Point sizes.  Slightly larger than a default desktop UI because the
#: dashboard is glanced at from across a desk while the game has focus.
FONT_SIZES = {
    "title":   11,
    "section":  9,
    "body":     10,
    "small":    9,
}

#: The monospace stack used for value columns.  The TUI gets column alignment
#: for free from the terminal grid; the GUI has to ask for it, and several
#: blocks (Cargo, Missions, Ship Health) pad their values to fixed widths on
#: the assumption that a monospace face will render them aligned.
MONO_FAMILIES = '"DejaVu Sans Mono", "Consolas", "Menlo", "Courier New", monospace'


def stylesheet(theme_name: str = "default") -> str:
    """Return the complete Qt Style Sheet for ``theme_name``."""
    c = rgb(theme_name)
    f = FONT_SIZES
    return f"""
QWidget {{
    background-color: {c['bg']};
    color: {c['fg']};
    font-size: {f['body']}pt;
}}
QMainWindow, QDialog {{ background-color: {c['bg']}; }}

/* ── Dashboard blocks ──────────────────────────────────────────────────── */

QFrame#block {{
    background-color: {c['block-bg']};
    border: 1px solid {c['border']};
    border-radius: 3px;
}}
QLabel#blockTitle {{
    background-color: {c['title-bg']};
    color: {c['accent']};
    font-size: {f['title']}pt;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 3px 8px;
    border-bottom: 1px solid {c['border']};
}}

/* ── Rows ──────────────────────────────────────────────────────────────── */

QLabel[role="key"]  {{ color: {c['dim']}; background: transparent; }}
QLabel[role="val"]  {{
    color: {c['fg']};
    background: transparent;
    font-family: {MONO_FAMILIES};
}}
QLabel[role="section"] {{
    color: {c['accent']};
    background: transparent;
    font-size: {f['section']}pt;
    font-weight: 600;
    letter-spacing: 1px;
    padding-top: 4px;
}}
QLabel[role="dim"]    {{ color: {c['dim']}; background: transparent; }}
QLabel[role="hdrkey"] {{
    color: {c['accent']};
    background: transparent;
    font-weight: 600;
}}
QLabel[health="good"] {{ color: {c['green']}; }}
QLabel[health="warn"] {{ color: {c['amber']}; }}
QLabel[health="crit"] {{ color: {c['red']}; }}
QLabel[role="highlight"] {{ color: {c['accent']}; }}

QFrame[role="rule"] {{
    background-color: {c['border']};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

/* ── Tabs ──────────────────────────────────────────────────────────────── */

QTabWidget::pane {{
    border: none;
    border-top: 1px solid {c['border']};
    background: {c['block-bg']};
}}
QTabBar {{ qproperty-drawBase: 0; background: {c['title-bg']}; }}
QTabBar::tab {{
    background: {c['title-bg']};
    color: {c['dim']};
    padding: 3px 9px;
    margin: 0;
    border: none;
    border-right: 1px solid {c['border']};
    font-size: {f['small']}pt;
}}
QTabBar::tab:selected {{
    color: {c['accent']};
    font-weight: 600;
    background: {c['block-bg']};
}}
QTabBar::tab:hover:!selected {{ color: {c['fg']}; }}

/* ── Scroll areas ──────────────────────────────────────────────────────── */

QScrollArea {{ background: {c['block-bg']}; border: none; }}
QScrollArea > QWidget > QWidget {{ background: {c['block-bg']}; }}
QScrollBar:vertical {{
    background: {c['block-bg']};
    width: 9px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {c['border']};
    min-height: 24px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{ background: {c['accent']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{
    background: {c['block-bg']};
    height: 9px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {c['border']};
    min-width: 24px;
    border-radius: 4px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

/* ── Controls ──────────────────────────────────────────────────────────── */

QPushButton {{
    background-color: {c['title-bg']};
    border: 1px solid {c['border']};
    border-radius: 3px;
    padding: 4px 12px;
    color: {c['fg']};
}}
QPushButton:hover  {{ border-color: {c['accent']}; }}
QPushButton:pressed{{ background-color: {c['border']}; }}
QPushButton:disabled {{ color: {c['dim']}; border-color: {c['border']}; }}
QPushButton[role="primary"] {{
    background-color: {c['accent']};
    border: 1px solid {c['accent']};
    color: {c['bg']};
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background-color: {c['fg']}; }}
QPushButton[role="link"] {{
    background: transparent;
    border: none;
    padding: 2px 4px;
    color: {c['dim']};
}}
QPushButton[role="link"]:hover {{ color: {c['accent']}; }}

QLineEdit, QSpinBox, QComboBox {{
    background-color: {c['bg']};
    border: 1px solid {c['border']};
    border-radius: 3px;
    padding: 3px 6px;
    color: {c['fg']};
    selection-background-color: {c['accent']};
    selection-color: {c['bg']};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
QComboBox::drop-down {{ border: none; width: 16px; }}
QComboBox QAbstractItemView {{
    background-color: {c['block-bg']};
    border: 1px solid {c['border']};
    color: {c['fg']};
    selection-background-color: {c['accent']};
    selection-color: {c['bg']};
    outline: none;
}}

/* ── Menus ─────────────────────────────────────────────────────────────── */

QMenuBar {{
    background-color: {c['title-bg']};
    color: {c['fg']};
    border-bottom: 1px solid {c['border']};
}}
QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
QMenuBar::item:selected {{ background: {c['accent']}; color: {c['bg']}; }}
QMenu {{
    background-color: {c['block-bg']};
    border: 1px solid {c['border']};
    color: {c['fg']};
}}
QMenu::item {{ padding: 4px 22px; }}
QMenu::item:selected {{ background: {c['accent']}; color: {c['bg']}; }}
QMenu::item:disabled {{ color: {c['dim']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 3px 0; }}

/* ── Status bar and notices ────────────────────────────────────────────── */

QStatusBar {{
    background-color: {c['title-bg']};
    color: {c['dim']};
    border-top: 1px solid {c['border']};
}}
QStatusBar::item {{ border: none; }}
QLabel#updateNotice {{
    background-color: {c['title-bg']};
    color: {c['amber']};
    padding: 3px 8px;
    font-weight: 600;
}}

/* ── Support bar ───────────────────────────────────────────────────────── */

QWidget#supportBar {{ background-color: {c['title-bg']}; }}
QLabel#supportLabel {{
    color: {c['dim']};
    font-size: {f['small']}pt;
    letter-spacing: 1px;
}}
QLabel[role="supportSep"] {{ color: {c['border']}; }}

/* ── Dialogs ───────────────────────────────────────────────────────────── */

QLabel#aboutTitle {{
    color: {c['accent']};
    font-size: 17pt;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#aboutSubtitle {{ color: {c['dim']}; font-size: {f['small']}pt; }}
QGroupBox {{
    border: 1px solid {c['border']};
    border-radius: 3px;
    margin-top: 16px;
    padding: 10px 10px 8px 10px;
    background-color: {c['block-bg']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 2px 6px;
    color: {c['accent']};
    font-size: {f['small']}pt;
    font-weight: 600;
}}
QListWidget {{
    background-color: {c['bg']};
    border: 1px solid {c['border']};
    color: {c['fg']};
    outline: none;
}}
QListWidget::item {{ padding: 3px 6px; }}
QListWidget::item:selected {{ background: {c['accent']}; color: {c['bg']}; }}
QSplitter::handle {{ background: {c['bg']}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical   {{ height: 3px; }}
QToolTip {{
    background-color: {c['title-bg']};
    color: {c['fg']};
    border: 1px solid {c['accent']};
    padding: 3px;
}}
"""


def health_class(pct) -> str:
    """Map a 0–100 health percentage to a stylesheet ``health`` property.

    Thresholds match ``tui/block_base._health_cls`` exactly so a hull at 30%
    is amber in both front ends.
    """
    if pct is None:
        return ""
    try:
        v = float(pct)
    except (TypeError, ValueError):
        return ""
    if v > 75:
        return "good"
    if v >= 25:
        return "warn"
    return "crit"


def classes_to_props(classes: str) -> dict[str, str]:
    """Translate a TUI CSS class string into Qt property values.

    Blocks pass class strings like ``"val health-crit"`` or ``"val dim"``
    straight through from the ported TUI code.  Returning properties rather
    than a stylesheet fragment keeps the styling in one place.
    """
    parts = set((classes or "").split())
    props: dict[str, str] = {"role": "val"}
    if "health-good" in parts:
        props["health"] = "good"
    elif "health-warn" in parts:
        props["health"] = "warn"
    elif "health-crit" in parts:
        props["health"] = "crit"
    if "dim" in parts:
        props["role"] = "dim"
    if "highlight" in parts:
        props["role"] = "highlight"
    return props
