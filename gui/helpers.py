"""
gui/helpers.py — Standalone GTK4 widget helpers, theme loader, and
                 Powerplay 2.0 rank math.

No imports from core or from other gui submodules — safe to import first.
"""

from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk
except ImportError:
    raise ImportError(
        "PyGObject not found. Install with: pacman -S python-gobject gtk4\n"
        "  or: pip install PyGObject"
    )


# ── Powerplay 2.0 rank helpers ────────────────────────────────────────────────

def pp_merits_for_rank(rank: int) -> int:
    """Return total cumulative merits required to reach the given rank.

    Formula verified against published Powerplay 2.0 tables:
      Ranks 1-5:   fixed thresholds (0, 2000, 5000, 9000, 15000)
      Ranks 6-100: 15000 + (rank-5) * 8000
      Ranks 100+:  775000 + (rank-100) * 8000
    """
    if rank <= 1:   return 0
    if rank == 2:   return 2_000
    if rank == 3:   return 5_000
    if rank == 4:   return 9_000
    if rank == 5:   return 15_000
    if rank <= 100: return 15_000 + (rank - 5) * 8_000
    return 775_000 + (rank - 100) * 8_000


def pp_rank_progress(rank: int, total_merits: int) -> tuple:
    """Return (fraction 0.0-1.0, merits_in_rank, merits_needed, next_rank)."""
    floor    = pp_merits_for_rank(rank)
    ceil     = pp_merits_for_rank(rank + 1)
    span     = ceil - floor
    earned   = max(0, total_merits - floor)
    fraction = min(1.0, earned / span) if span > 0 else 1.0
    return fraction, earned, span, rank + 1


PP_RANK_NAMES = [
    "Harmless", "Mostly Harmless", "Novice", "Competent", "Expert",
    "Master", "Dangerous", "Deadly", "Elite",
    "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]


# ── Theme loader ──────────────────────────────────────────────────────────────

THEMES_DIR     = Path(__file__).parents[1] / "themes"
FONTS_REPO_DIR = Path(__file__).parents[1] / "fonts"   # bundled TTFs in the repo

_THEME_AVATAR_MAP = {
    "default-blue":   "edld_avatar_blue_512.png",
    "default-green":  "edld_avatar_green_512.png",
    "default-purple": "edld_avatar_purple_512.png",
    "default-red":    "edld_avatar_red_512.png",
    "default-yellow": "edld_avatar_yellow_512.png",
    "default-light":  "edld_avatar_light_512.png",
}


def bootstrap_fonts() -> None:
    """Ensure bundled fonts are present in the EDLD data directory and
    registered with PangoCairo for this process.

    On every launch:
      1. Locate the TTF files bundled in the repo's fonts/ directory.
      2. If any are absent from EDLD_DATA_DIR/fonts/, copy them there,
         creating the directory if needed.
      3. Register each TTF with PangoCairo.FontMap so the font is
         available by family name to GTK4 CSS without touching the
         system font directories or requiring a font cache rebuild.

    Fails silently — if Pango is unavailable or files can't be copied,
    EDLD falls back to the system monospace font.
    """
    try:
        from core.state import EDLD_DATA_DIR
        import shutil

        data_fonts_dir = Path(EDLD_DATA_DIR) / "fonts"
        data_fonts_dir.mkdir(parents=True, exist_ok=True)

        # Copy any TTF present in the repo bundle but absent in the data dir
        if FONTS_REPO_DIR.is_dir():
            for src in FONTS_REPO_DIR.glob("*.ttf"):
                dst = data_fonts_dir / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)

        # Register all TTFs in the data fonts dir with PangoCairo
        import gi as _gi
        _gi.require_version("PangoCairo", "1.0")
        from gi.repository import PangoCairo
        fm = PangoCairo.FontMap.get_default()
        for ttf in sorted(data_fonts_dir.glob("*.ttf")):
            try:
                fm.add_font_file(str(ttf))
            except Exception:
                pass  # older Pango without add_font_file — font unavailable

    except Exception:
        pass  # non-fatal — GUI continues with system monospace fallback


def list_monospace_fonts() -> list[str]:
    """Return sorted list of installed monospace font family names.

    Uses Pango's font map, which reflects the same fonts GTK4 will render.
    Returns an empty list if Pango is unavailable (terminal-only mode).
    """
    try:
        import gi as _gi
        _gi.require_version("Pango", "1.0")
        from gi.repository import Pango
        fm = Pango.FontMap.get_default()
        return sorted(
            family.get_name()
            for family in fm.list_families()
            if family.is_monospace()
        )
    except Exception:
        return []


def load_theme(theme_name: str, font_size: int = 14,
               font_family: str = "JetBrains Mono") -> str:
    """Load base.css (structure) + palette CSS for the named theme.

    base.css holds all structural rules and references CSS variables.
    Theme palette files contain only :root { } variable overrides.
    Falls back to default.css if the named palette is not found.

    font_size and font_family are injected as final overrides so they
    always win over any palette-defined defaults.
    """
    base_file    = THEMES_DIR / "base.css"
    palette_file = THEMES_DIR / f"{theme_name}.css"
    if not palette_file.is_file():
        palette_file = THEMES_DIR / "default.css"

    parts = []
    for path in (base_file, palette_file):
        try:
            parts.append(path.read_text(encoding="utf-8"))
        except OSError:
            pass
    # Inject font size as a final :root override — wins over any palette default.
    parts.append(f":root {{ --font-size: {font_size}px; }}")
    # Inject font family directly on the window class — GTK4 CSS does not support
    # font-family via CSS custom properties (var()), so we write a real rule.
    # Fallback chain: user choice → JetBrains Mono → system monospace.
    if font_family and font_family != "monospace":
        family_value = f'"{font_family}", "JetBrains Mono", monospace'
    else:
        family_value = '"JetBrains Mono", monospace'
    parts.append(
        f'.edld-window {{ font-family: {family_value}; }}'
    )
    return "\n".join(parts)


def apply_theme(theme_name: str, font_size: int = 14,
                font_family: str = "JetBrains Mono") -> None:
    """Apply named CSS theme to the GTK display."""
    css      = load_theme(theme_name, font_size, font_family)
    provider = Gtk.CssProvider()
    if css:
        provider.load_from_string(css)
    display = Gdk.Display.get_default()
    if display:
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER,
        )


def avatar_path_for_theme(theme_name: str) -> Path | None:
    """Return the Path to the avatar image for the given theme, or None."""
    fname = _THEME_AVATAR_MAP.get(theme_name, "edld_avatar_512.png")
    p = Path(__file__).parents[1] / "images" / fname
    return p if p.exists() else None


# ── Widget factory helpers ────────────────────────────────────────────────────

def make_label(text: str = "", css_class=None, xalign: float = 0.0,
               wrap: bool = False) -> Gtk.Label:
    """Create a Gtk.Label with optional CSS class(es) and alignment."""
    lbl = Gtk.Label(label=text)
    lbl.set_xalign(xalign)
    lbl.set_wrap(wrap)
    if css_class:
        for cls in (css_class if isinstance(css_class, list) else [css_class]):
            lbl.add_css_class(cls)
    return lbl


def make_section(title: str, title_widget=None) -> tuple[Gtk.Box, Gtk.Box]:
    """Return (outer Box, inner Box) for a labelled panel section.

    If title_widget is given it replaces the plain text header label.
    """
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    outer.add_css_class("panel-section")

    if title_widget is not None:
        header = title_widget
    else:
        header = Gtk.Label(label=title)
        header.set_xalign(0.0)
    header.add_css_class("section-header")
    outer.append(header)

    sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
    sep.add_css_class("section-sep")
    outer.append(sep)

    inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
    inner.add_css_class("section-body")
    outer.append(inner)

    return outer, inner


def make_row(label_text: str,
             value_text: str = "—") -> tuple[Gtk.Box, Gtk.Label]:
    """Return (row Box, value Label) for a key/value display row."""
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    row.add_css_class("data-row")

    key = make_label(label_text, css_class="data-key")
    key.set_hexpand(False)
    row.append(key)

    val = make_label(value_text, css_class="data-value")
    val.set_hexpand(True)
    val.set_xalign(1.0)
    row.append(val)

    return row, val


# ── Health / shield display helpers ──────────────────────────────────────────

def hull_css(pct: int) -> str:
    """Return CSS class name for a hull/shield percentage."""
    if pct > 75:   return "health-good"
    if pct >= 25:  return "health-warn"
    return "health-crit"


def set_health_label(label: Gtk.Label, pct: int | None, suffix: str = "%") -> None:
    """Set a health label's text and apply the appropriate colour class."""
    for cls in ("health-good", "health-warn", "health-crit"):
        label.remove_css_class(cls)
    if pct is None:
        label.set_label("—")
    else:
        label.set_label(f"{pct}{suffix}")
        label.add_css_class(hull_css(pct))


def fmt_shield(shields_up, recharging: bool) -> str:
    """Return human-readable shield status string."""
    if shields_up is None: return "—"
    if shields_up:         return "Up"
    if recharging:         return "Recharging"
    return "Down"


# ── Crew active duration ──────────────────────────────────────────────────────

def fmt_crew_active(delta) -> str:
    """Format a timedelta as human-readable crew active duration.

    Always shows the two most significant non-zero units to the nearest
    complete day.  Examples: '3y 5mo', '11mo 23d', '45d', '<1d'
    """
    total_days = int(delta.total_seconds() // 86400)
    if total_days < 1:
        return "<1d"
    years,     rem_days = divmod(total_days, 365)
    months,    days     = divmod(rem_days, 30)
    parts = []
    if years:              parts.append(f"{years}y")
    if months:             parts.append(f"{months}mo")
    if days and len(parts) < 2: parts.append(f"{days}d")
    return " ".join(parts) if parts else f"{total_days}d"
