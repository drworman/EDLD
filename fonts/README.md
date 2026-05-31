# EDLD Bundled Fonts

This directory contains the JetBrains Mono typeface, bundled with EDLD
as the default GUI font.

**License:** SIL Open Font License 1.1 — see LICENSE.txt
**Source:** https://www.jetbrains.com/lp/mono/
**Version:** 2.304

## Files

- `JetBrainsMono-Regular.ttf`
- `JetBrainsMono-Bold.ttf`
- `JetBrainsMono-Italic.ttf`
- `JetBrainsMono-BoldItalic.ttf`

## How EDLD uses these fonts

On first launch EDLD copies these files into its own data directory
(`~/.local/share/EDLD/fonts/`) and registers them with PangoCairo for the running process.
No system font directories are written and no font cache rebuild is needed.

If files are missing here EDLD falls back to the system monospace font.

## Obtaining the fonts

Download from the JetBrains Mono GitHub releases page:
https://github.com/JetBrains/JetBrainsMono/releases/latest

Extract the four Static/ TTF files listed above into this directory.
