"""
core/palette.py — UI-agnostic colour palettes.

The single source of truth for EDLD's colour schemes.  Both front ends read
from here:

  * ``tui/theme.py``  substitutes these values into the Textual CSS
  * ``gui/theme.py``  substitutes them into the Qt stylesheet

Keeping the palettes out of either UI module means a theme added here appears
in both front ends at once, and neither front end has to import the other (the
GUI must work on a machine with no Textual installed, and vice versa).

Palette keys carry their Textual ``$`` sigil because the TUI substitutes them
directly into CSS text.  ``rgb()`` returns the same values without the sigil
for callers that want plain names.
"""

from __future__ import annotations

from pathlib import Path

# ── Colour palettes ───────────────────────────────────────────────────────────

PALETTES: dict[str, dict[str, str]] = {
    # ── Default (Elite orange) ────────────────────────────────────────────────
    # Backgrounds carry a warm orange-amber tint matching the accent.
    # Accent #e07b20 — Elite Dangerous orange.
    "default": {
        "$bg":       "#120f0b",   # warm near-black, slight orange tint
        "$block-bg": "#1c1810",   # warm dark block fill
        "$title-bg": "#241e16",   # warm title / panel bar
        "$fg":       "#e8ddd0",   # warm off-white
        "$dim":      "#7a6a52",   # warm amber-brown muted text
        "$accent":   "#e07b20",   # Elite orange
        "$border":   "#3d2e18",   # dark amber-brown border
        "$green":    "#57e389",
        "$amber":    "#f8e45c",
        "$red":      "#e05c5c",
    },
    # ── Default Green ─────────────────────────────────────────────────────────
    # Backgrounds carry a cool forest-green tint.
    # Accent #00aa44 — green.
    "default-green": {
        "$bg":       "#0b0f0d",   # very dark, subtle green tint
        "$block-bg": "#141c18",   # dark green-tinted block fill
        "$title-bg": "#1a2420",   # green title / panel bar
        "$fg":       "#d4e4da",   # cool, slightly green-tinted white
        "$dim":      "#567060",   # muted green-gray
        "$accent":   "#00aa44",   # ED green
        "$border":   "#1e3428",   # dark forest-green border
        "$green":    "#57e389",
        "$amber":    "#f8e45c",
        "$red":      "#e05c5c",
    },
    # ── Default Blue ──────────────────────────────────────────────────────────
    # Accent #3d8fd4 — blue.
    "default-blue": {
        "$bg":       "#0c0e14",
        "$block-bg": "#141820",
        "$title-bg": "#1a2030",
        "$fg":       "#d0d8e8",
        "$dim":      "#556070",
        "$accent":   "#3d8fd4",
        "$border":   "#253050",
        "$green":    "#57e389",
        "$amber":    "#f8e45c",
        "$red":      "#e05c5c",
    },
    # ── Default Purple ────────────────────────────────────────────────────────
    # Accent #9b59b6 — purple.
    "default-purple": {
        "$bg":       "#0e0d14",
        "$block-bg": "#17151f",
        "$title-bg": "#201c28",
        "$fg":       "#dcd8e8",
        "$dim":      "#60587a",
        "$accent":   "#9b59b6",
        "$border":   "#302845",
        "$green":    "#57e389",
        "$amber":    "#f8e45c",
        "$red":      "#e05c5c",
    },
    # ── Default Red ───────────────────────────────────────────────────────────
    # Accent #cc3333 — red.
    "default-red": {
        "$bg":       "#130e0e",
        "$block-bg": "#1e1414",
        "$title-bg": "#261818",
        "$fg":       "#e8d8d8",
        "$dim":      "#7a5858",
        "$accent":   "#cc3333",
        "$border":   "#3d2020",
        "$green":    "#57e389",
        "$amber":    "#f8e45c",
        "$red":      "#e05c5c",
    },
    # ── Default Yellow ────────────────────────────────────────────────────────
    # Accent #d4a017 — yellow.
    "default-yellow": {
        "$bg":       "#110f08",
        "$block-bg": "#1a1810",
        "$title-bg": "#231f14",
        "$fg":       "#ede8d4",
        "$dim":      "#7a7050",
        "$accent":   "#d4a017",
        "$border":   "#3a3018",
        "$green":    "#57e389",
        "$amber":    "#f8e45c",
        "$red":      "#e05c5c",
    },
    "default-light": {
        "$bg":       "#f0f2f5",
        "$block-bg": "#ffffff",
        "$title-bg": "#e4e8f0",
        "$fg":       "#1a1e28",
        "$dim":      "#888ea0",
        "$accent":   "#005faa",
        "$border":   "#c8cdd8",
        "$green":    "#1a7a3a",
        "$amber":    "#b07000",
        "$red":      "#cc2222",
    },
}
PALETTES["default-dark"] = PALETTES["default"]

#: Display names for the built-in themes, in the order the preferences
#: selectors present them.  Shared so the TUI and GUI offer the same list.
THEME_CHOICES: list[tuple[str, str]] = [
    ("EDLD Default",        "default"),
    ("EDLD Default Dark",   "default-dark"),
    ("EDLD Default Green",  "default-green"),
    ("EDLD Default Blue",   "default-blue"),
    ("EDLD Default Purple", "default-purple"),
    ("EDLD Default Red",    "default-red"),
    ("EDLD Default Yellow", "default-yellow"),
    ("EDLD Default Light",  "default-light"),
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_custom_palette(css_path) -> dict | None:
    """Parse a custom theme CSS file and extract a palette dict."""
    import re as _re
    try:
        block_m = _re.search(
            r":root\s*\{([^}]+)\}",
            Path(css_path).read_text(encoding="utf-8"),
            _re.DOTALL,
        )
        if not block_m:
            return None
        block = block_m.group(1)

        def _v(name, default=""):
            m = _re.search(rf"--{name}\s*:\s*([^;]+);", block)
            return m.group(1).strip() if m else default

        return {
            "$bg":       _v("bg-deep",  "#0d0f12"),
            "$block-bg": _v("bg-mid",   "#161a1f"),
            "$title-bg": _v("bg-panel", "#1c2128"),
            "$fg":       _v("fg",       "#d8dce5"),
            "$dim":      _v("fg-dim",   "#606878"),
            "$accent":   _v("accent",   "#aaaaaa"),
            "$border":   _v("border",   "#2a3040"),
            "$green":    _v("green",    "#57e389"),
            "$amber":    _v("amber",    "#f8e45c"),
            "$red":      _v("red",      "#e05c5c"),
        }
    except Exception:
        return None


def list_custom_themes() -> list[tuple[str, str]]:
    """Return ``[(theme_id, stem)]`` for .css files in ``themes/custom/``."""
    try:
        custom_dir = _repo_root() / "themes" / "custom"
        return [
            (f"custom/{f.stem}", f.stem)
            for f in sorted(custom_dir.glob("*.css"))
        ]
    except Exception:
        return []


def palette_for(theme_name: str) -> dict[str, str]:
    """Return the palette dict for a theme id, falling back to ``default``.

    Handles the ``custom/<stem>`` form by parsing the matching CSS file, so
    both front ends resolve a custom theme identically.
    """
    if theme_name and theme_name.startswith("custom/"):
        css_file = _repo_root() / "themes" / f"{theme_name}.css"
        return load_custom_palette(css_file) or PALETTES["default"]
    return PALETTES.get(theme_name, PALETTES["default"])


def rgb(theme_name: str) -> dict[str, str]:
    """Palette for a theme with the ``$`` sigils stripped from the keys.

    ``rgb("default")["accent"]`` is the same colour as
    ``palette_for("default")["$accent"]``; the sigil-free form reads better in
    the Qt stylesheet builder, which has no use for Textual's variable syntax.
    """
    return {k.lstrip("$"): v for k, v in palette_for(theme_name).items()}
