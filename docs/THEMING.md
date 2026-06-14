# EDLD Theming

The EDLD dashboard (Textual TUI) ships eight built-in colour themes and supports
user-defined custom themes.  A theme is just a palette — a small set of colour
values.  All structural rules (layout, spacing, borders) are fixed in the UI and
are not part of a theme, so switching themes only changes colours.

---

## Selecting a theme

Either set it in your config:

```toml
[UI]
Theme = "default-blue"
```

…or pick it live from **Preferences → Appearance** (Ctrl-O → Appearance).
Theme changes apply immediately.

---

## Built-in themes

| Theme | Accent |
|-------|--------|
| `default` | Orange `#e07b20` — Elite Dangerous orange |
| `default-dark` | Orange `#e07b20` — identical to `default` |
| `default-blue` | Blue `#3d8fd4` |
| `default-green` | Green `#00aa44` |
| `default-purple` | Purple `#9b59b6` |
| `default-red` | Red `#cc3333` |
| `default-yellow` | Yellow `#d4a017` |
| `default-light` | Light background variant |

These palettes are built into the dashboard; no external files are required.

---

## Custom themes

A custom theme is a single CSS file containing one `:root { }` block of colour
variables.  To create one:

1. Copy the template:

   ```
   cp themes/custom-template.css themes/custom/my-theme.css
   ```

2. Edit the colour values in the `:root { }` block of
   `themes/custom/my-theme.css`.  The recognised variables are:

   | Variable | Purpose |
   |----------|---------|
   | `--bg-deep`  | Window background |
   | `--bg-mid`   | Block background |
   | `--bg-panel` | Title-bar background |
   | `--fg`       | Primary text |
   | `--fg-dim`   | Dimmed/secondary text |
   | `--accent`   | Accent (titles, highlights) |
   | `--border`   | Block borders |
   | `--green` / `--amber` / `--red` | Status colours (good / warning / critical) |

   Any variable you omit falls back to a sensible default.

3. Select it by stem name under **Preferences → Appearance** (it appears as
   `Custom: my-theme`), or in config:

   ```toml
   [UI]
   Theme = "custom/my-theme"
   ```

Custom themes live in `themes/custom/` and are discovered automatically at
startup.
