# Streamer Stats Overlay

An optional set of small, always-on-top windows that draw over Elite Dangerous
itself.

It is not a second dashboard. EDLD already is one, and it is better at it: a
second screen has room for everything and you can look at it whenever you want.
The overlay exists for the subset you cannot look away for — and for the subset
someone else is looking at, which is where the name comes from. If you are
streaming or recording, this is what puts your commander, your balance and your
session numbers on camera without a scene full of browser sources.

Off by default. Nothing draws over exclusive fullscreen on any platform — run
the game borderless windowed.

| Platform | Status |
|---|---|
| Linux / X11 | **Released.** Requires a running compositor — see below |
| Windows | **Experimental.** Untested; `--overlay-probe` reports what a machine can do |
| macOS | **Experimental.** Untested, and largely moot since Elite does not run natively there |
| Linux / Wayland | Not supported. A Wayland client cannot request always-on-top or place itself absolutely |

The compositor is a dependency on Linux, not a nicety: without one there is no
alpha channel to composite into. EDLD detects the case and falls back to an
opaque panel so the text is readable, but transparency needs `picom` or
equivalent running.

## Quick start

1. Preferences → **Overlay** → *Show overlay* → **On**.
2. In the panel list, set something to **On** — `commander` is a good first
   test because it needs nothing but a loaded commander.
3. **Apply & Save.** The overlay redraws without a restart.

If nothing appears, `python edld.py --overlay-doctor` walks the chain and names
the first link that breaks.

## Panels

A panel belongs to the component that owns its data, so what a panel can show
is whatever that part of EDLD already knows.

| Panel | Shows |
|---|---|
| `commander` | `CMDR <name>` as the header, then squadron and location |
| `ship` | Ship name and ident as the header, what you are currently in, type, value |
| `income` | Credits, and the session's earnings with its rate |
| `powerplay` | Your power and your rank — nothing at all if you are unpledged |
| `cargo` | How full the hold is; both holds when you are in an SRV |
| `survey_compass` | Bearings to surface deposits already recorded on this body |
| `combat`, `exploration`, `exobiology`, `mining`, `trade`, `missions_session`, `odyssey` | That activity's figures |

### Placement

Three zones across the top — **left**, **centre**, **right** — plus
**dock-left** and **dock-right**, separate windows against the side edges, each
a single stacked column. Every zone takes positions 1–9.

### Mode

**On** draws the panel whenever it has anything to draw. **Off** never draws it.
**Auto** lets the panel's own component decide — the survey compass appears
only when you are in an SRV near a recorded deposit, PowerPlay only when you are
pledged, cargo only when there is a hold.

`On` still needs content: it means *always show this*, not *invent something*.

### Shows — career, session, or both

Offered only on panels that have both kinds of figure, because choosing between
career and session where only one exists is a control that does nothing.

- **Session** — this session only. Absent until something happens.
- **Career** — lifetime totals. Drawn from the first frame, whether or not
  anything has happened today.
- **Career (Session: )** — the career figure with the session in parentheses,
  so you can see what today added to the total without doing the subtraction.

### Hidden panels

When an `auto` panel is not currently relevant, its stack either closes up or
holds the space:

- **Collapse** — denser, no wasted screen, but the panels below move when one
  appears or goes, and something that moves has to be re-found rather than
  glanced at.
- **Reserve** — everything stays where you put it, at the cost of gaps.
  Steadier to read, and the better choice with the overlay on camera.

## Appearance

### Spacing

Two layers, and they are different things:

```
Margin   monitor edge  →  window edge   (moves the whole overlay)
Pad      window edge   →  first glyph   (breathing room inside the box)
```

`MarginY` is what moves the top bar down the screen. `DockTop` is the same
measurement for the side windows.

### Type and colour

`FontFamily` takes any installed family by name, plus anything EDLD ships in
`fonts/` and anything you drop in `<data>/fonts/` — those are registered at
startup, so they work without being installed system-wide.

`ColourTheme` offers every EDLD palette plus **Elite Dangerous**, which matches
the cockpit HUD's orange, and **Custom**, which uses the three colour fields
verbatim. Picking a theme changes what is drawn but not what is stored, so
switching back to Custom restores what you had set.

The text shadow is derived from the text: it keeps the ink's hue and drops its
lightness, so it reads as depth rather than as a black fringe. `ShadowOffset` is
capped at 2px, past which it stops being depth and becomes a blurry second copy.

## Where it will not run

The overlay does not start, and says which rule applied, when:

- **Terminal mode** — a scrolling log has no window for an overlay to sit beside.
- **A secondary instance** (`PrimaryInstance = false`) — the overlay belongs on
  the machine running the game.
- **A headless session** — no display at all.

## Diagnostics

| Command | Answers |
|---|---|
| `--overlay-probe` | Can this machine carry an overlay? Reports platform, translucency, click-through, always-on-top, compositing, and the fonts it registered |
| `--overlay-selftest` | Does the renderer draw? A fixed frame for twenty seconds, with no config and no panels involved |
| `--overlay-doctor` | Why is nothing showing? Walks config, placements, available panels and position, and names the first link that breaks |

Under `--trace` the component logs its build and placement count at load, and
every frame with its element count per window.

### Compositing

Per-pixel transparency needs a compositor. i3 does not composite; install
`picom` and start it from your i3 config. Without one the overlay paints an
opaque background so the text is still readable — less pretty, and actually
there. EDLD detects which case applies rather than assuming.
