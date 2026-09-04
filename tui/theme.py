"""
tui/theme.py — Textual CSS for the EDLD TUI.

Colours match the theme requested via [UI] Theme config key.
The DEFAULT_CSS string is always loaded; colour overrides are
appended per-theme in apply_theme().
"""

# ── Structural CSS (layout, spacing — no colours) ─────────────────────────────
#
# Column layout and block heights come from the shared layout model
# (core/layout_model.py), so every block's size follows its size class and the
# Display tab can reassign windows.  Each block's height percentage is generated
# at build time by _height_css() from the model's per-column apportionment.
#
# Textual is fully terminal-resolution aware — at very narrow widths
# (< 100 cols) the three columns will compress; below the cargo /
# career blocks' minimum useful width they'll horizontally scroll
# rather than break, which is preferable to hard-clipping content.

STRUCTURAL_CSS = """
/* Screen stacks Header / dashboard / Footer vertically. */
Screen {
    layout: vertical;
}

/* Dashboard fills the space between header and footer. */
#dashboard {
    layout: horizontal;
    width: 100%;
    height: 1fr;
}

/* Column widths: left 34% : centre 32% : right 34%. */
#col-left   { width: 34%; height: 100%; }
#col-centre { width: 32%; height: 100%; }
#col-right  { width: 34%; height: 100%; }

/* Blocks: no auto-height, no margin (border provides visual separation). */
TuiBlock {
    border: solid $border;
    background: $block-bg;
    margin: 0;
    height: auto;
    padding: 0;
}

/* Inner scrollable / tabbed content fills remaining space after the title bar. */
TuiBlock > VerticalScroll { height: 1fr; }
TuiBlock > TabbedContent  { height: 1fr; }

/* Per-block heights are generated from the shared layout model and appended to
   the CSS at build time (see build_css / _height_css), so block heights
   follow the size classes and the Display tab can reassign windows. */

.block-title {
    background: $title-bg;
    color: $accent;
    text-style: bold;
    padding: 0 1;
    border-bottom: solid $border;
}

/* Update-available notice bar — sits between Textual header and dashboard.
   Height toggled in Python: 0 when empty, 1 when an update is available. */
#update-notice-bar {
    height: 0;
    background: $title-bg;
    padding: 0 1;
}


.kv-row {
    height: 1;
    padding: 0 1;
}

.key  { color: $dim; width: 1fr; }
.val  { color: $fg; width: auto; text-align: right; }

.health-good { color: $green;  }
.health-warn { color: $amber;  }
.health-crit { color: $red; text-style: bold; }

.status-ready  { color: $green; }
.status-active { color: $amber; }
.dim           { color: $fg;    }
.highlight     { color: $amber; }

.section-hdr {
    color: $accent;
    text-style: bold;
    padding: 0 1;
    margin-top: 0;
}
/* Commander headers are block-title / block-hdr2 — margin handled by class */

.sep {
    color: $border;
    padding: 0 1;
}

.alert-entry { padding: 0 1; height: 1; }

/* ── Navigation block: compact single-row inputs and buttons ───────────────── */
/* Textual's default Input/Button are height 3 with a border ("chunky").  In the
   Navigation routing tabs we collapse them to a single row each. */
#nav-tabs Input {
    height: 1;
    border-top: none;
    border-bottom: none;
    border-left: solid $dim;
    border-right: solid $dim;
    padding: 0 1;
    margin: 0 0 1 0;
    background: $bg;
}
#nav-tabs Input:focus {
    border-left: solid $accent;
    border-right: solid $accent;
    background: $bg;
}
#nav-tabs Button {
    height: 1;
    min-height: 1;
    border: none;
    padding: 0 2;
    margin: 0 0 1 0;
}

/* ── SepRow colour (resolved here where palette substitution runs) ─────────── */
SepRow { color: $border; }

/* ── Preferences screen ─────────────────────────────────────────────────────── */
PreferencesScreen {
    align: center middle;
}

#prefs-outer {
    width: 92%;
    height: 92%;
    background: $block-bg;
    border: solid $accent;
}

#prefs-outer TabbedContent { height: 1fr; }

#pref-btn-row {
    height: 3;
    padding: 0 1;
    align: right middle;
}

#pref-restart-note {
    width: 1fr;
    color: $amber;
}

/* Each pref row is height: auto so text-input rows expand to 3 rows naturally */
.pref-row {
    padding: 0 1;
    layout: horizontal;
    height: auto;
}

/* Label in each row: 45% width, text vertically centred within the row */
.pref-row .key {
    width: 45%;
    color: $dim;
    content-align: left middle;
}

.pref-section { padding: 0 1; margin-top: 1; color: $accent; text-style: bold; }
.pref-note    { padding: 0 1; color: $dim; }

/* Long text / password inputs: fill remaining width, clearly bordered */
.pref-input    { width: 1fr; border: round $dim; background: $bg; color: $fg; }

/* Medium inputs: commander names, uploader IDs */
.pref-input-sm { width: 24; border: round $dim; background: $bg; color: $fg; }

/* Notification level digit (0–3): 1-row, visible via contrasting background */
.pref-level    { height: 1; width: 3; border: none; background: $border; color: $fg; }

/* Theme selector */
.pref-select   { width: 1fr; }

/* Accent border on focused input */
PreferencesScreen Input:focus { border: round $accent; }

/* Notification level selector — compact width, one per event row */
/* Boolean On/Off selector — just wide enough for "On" / "Off" + arrow */
.pref-bool-sel  { width: 12; }

/* Notification level selector */
.pref-notif-sel { width: 22; }

/* Terse hint text below a field */
.pref-hint { padding: 0 2; color: $dim; height: 1; }

/* Ensure each tab's scroll area fills the available pane height */
#prefs-outer TabPane { height: 1fr; }
#prefs-outer TabPane > VerticalScroll { height: 1fr; }

/* Prevent bare Horizontal containers from expanding inside pref-rows */
.pref-row > Horizontal { height: auto; width: auto; }

PreferencesScreen Switch { height: 1; }
PreferencesScreen Button { height: 3; margin-left: 1; }

/* ── Reports screen ──────────────────────────────────────────────────────────── */

#reports-outer {
    width: 95%;
    height: 95%;
    layout: horizontal;
}

#reports-sidebar {
    width: 24;
    height: 100%;
    background: $block-bg;
    border: solid $accent;
}

#reports-sidebar .block-title { width: 100%; }

#reports-content {
    width: 1fr;
    height: 100%;
    background: $block-bg;
    border: solid $accent;
}

.reports-sidebar-btn {
    width: 100%;
    height: 1;
    border: none;
    background: $block-bg;
    color: $dim;
    padding: 0 1;
}

.reports-sidebar-btn:hover    { background: $title-bg; color: $fg; }
.reports-sidebar-btn.-active  { background: $title-bg; color: $accent; text-style: bold; }

#reports-scroll { height: 1fr; }

/* Section header fused with primary value (HdrRow) */
.hdr-key {
    color: $accent;
    text-style: bold;
    width: 1fr;
}

/* Block footer strip — use Static labels, not Buttons */
.footer-lbl {
    height: 1;
    padding: 0 1;
    color: $dim;
    background: $title-bg;
}
.footer-lbl:hover { color: $accent; }

/* Cargo header: title left, price-source label right — both get block-title bg */
#cargo-hdr-row {
    height: auto;
    layout: horizontal;
}
#cargo-title     { width: 1fr; }
#cargo-price-src { width: auto; text-align: right; }

#cargo-footer, #cmdr-footer {
    height: 1;
    background: $title-bg;
}

/* ── Search modal ──────────────────────────────────────────────────────────── */
SearchModal { align: center middle; }

#search-outer {
    width: 70%;
    height: 70%;
    background: $block-bg;
    border: solid $accent;
    padding: 1 2;
}

#search-title  { width: 100%; }
#search-hint   { width: 100%; margin-bottom: 1; }
#search-input  { width: 100%; margin-bottom: 0; }
#search-status { width: 100%; height: 1; }
#search-results { height: 1fr; margin-top: 1; }

.search-result-btn {
    width: 100%;
    height: 1;
    border: none;
    background: $block-bg;
    color: $fg;
    padding: 0 1;
    text-align: left;
}
.search-result-btn:hover { background: $title-bg; color: $accent; }

/* Commander: hdr1 has title-bg but NO bottom border — hdr2 supplies that */
#cmdr-hdr1 { border-bottom: none; }

/* Crew name row: Horizontal with two Labels acting as block title */
#crew-name-row {
    height: auto;
    background: $title-bg;
    padding: 0 1;
    layout: horizontal;
    border-bottom: solid $border;
}
#crew-name-lbl { color: $accent; text-style: bold; width: 1fr; }
#crew-type-lbl { color: $accent; text-align: right; }

/* Crew rank line: block-title class supplies background + border-bottom */
#crew-rank-lbl { padding: 0 1; height: 1; }

Footer { color: $dim; background: $bg; }
Header { color: $accent; background: $bg; text-style: bold; }

TabbedContent ContentSwitcher { height: 1fr; }
TabPane { padding: 0; }
Tab     { background: $title-bg; color: $dim; }
Tab.-active { color: $accent; text-style: bold; }
"""

# ── Colour palettes ────────────────────────────────────────────────────────────
# The palettes themselves live in core/palette.py so the Qt GUI can render the
# same themes without importing anything from this module (and therefore
# without requiring Textual to be installed).  Re-exported under the original
# private name so nothing else in the TUI needs to change.

from core.palette import PALETTES as _PALETTES  # noqa: E402


def _load_custom_palette(css_path) -> dict | None:
    """Parse a custom theme CSS file and extract a TUI palette dict."""
    from core.palette import load_custom_palette
    return load_custom_palette(css_path)


def list_custom_themes() -> list[tuple[str, str]]:
    """Return [(theme_id, stem)] for .css files in themes/custom/."""
    from core.palette import list_custom_themes as _lct
    return _lct()


def build_css(theme_name: str) -> str:
    """Return the full CSS string for a given theme name."""
    if theme_name.startswith("custom/"):
        from pathlib import Path as _P
        css_file = _P(__file__).parents[1] / "themes" / f"{theme_name}.css"
        palette  = _load_custom_palette(css_file) or _PALETTES["default"]
    else:
        palette = _PALETTES.get(theme_name, _PALETTES["default"])
    css = STRUCTURAL_CSS
    for var, colour in palette.items():
        css = css.replace(var, colour)
    return css + "\n" + _height_css()


# Map a layout-model window name to its Textual DOM id.  Single source of the
# id mapping, shared with tui/app.py.
BLOCK_DOM_ID = {
    "assets":       "block-assets",
    "engineering":  "block-eng",
    "colonisation": "block-colon",
    "commander":    "block-commander",
    "crew_slf":     "block-crew",
    "alerts":       "block-alerts",
    "cargo":        "block-cargo",
    "missions":     "block-missions",
    "navigation":   "block-nav",
    "career":       "block-career",
    "session":      "block-session",
    "ship_health":  "block-ship-health",
    "exploration":  "block-exploration",
    "exobiology":   "block-exobiology",
}


def _height_css(assignment=None) -> str:
    """Per-block ``height`` rules generated from the shared layout model.

    Appended to the themed CSS so block heights follow the standardised size
    classes and the current position assignment, with each column normalised
    to 100%.
    """
    try:
        from core import layout_model
        asn = assignment if assignment is not None else layout_model.load_assignment()
        cols = layout_model.tui_columns(asn)
        lines = []
        for col in layout_model.COLUMNS:
            for block, pct in cols[col]:
                dom = BLOCK_DOM_ID.get(block)
                if dom:
                    lines.append(f"#{dom} {{ height: {pct}%; }}")
        return "\n".join(lines)
    except Exception:
        return ""
