"""
core/layout_model.py — UI-agnostic dashboard layout model.

The single source of truth for what windows exist, what size class each is, and
where they sit.  The Textual TUI derives its composition from this module, and
the Preferences > Display tab edits the assignment it persists — so a window can
be moved, hidden, or swapped without the UI hard-coding its own layout.

Size classes
------------
Windows are grouped into interchangeable classes.  A *position* (slot) accepts
only windows of its own class, which is what keeps the layout from breaking when
the user reassigns one.

    panel    Every interchangeable window (Career, Cargo, Missions, Navigation,
             Colonisation, Exploration, Exobiology, Assets, Engineering)
    compact  Alerts · Crew/SLF   (two halves of one Panel height)
    anchor   Commander           (one Panel height)

Positions
---------
Columns are ``A`` (left), ``B`` (centre), ``C`` (right).  A position is a column
letter plus a 1-based index within that column: ``A1``, ``A2``, ``B3`` …  Each
position carries a size class and a default window.

Heights
-------
Each class has a relative *weight*.  Within a column the occupied positions'
weights are normalised to 100% within each column, so a column always fills
cleanly and empty positions simply reflow — and every window
of a class renders at a consistent proportion.  The weights are the single knob
for tuning standardised box sizes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# ── Size classes ──────────────────────────────────────────────────────────────

PANEL   = "panel"
COMPACT = "compact"
ANCHOR  = "anchor"

SIZE_CLASSES = (PANEL, COMPACT, ANCHOR)

# Relative height weight per class.  Every interchangeable window is PANEL.
# The three fixed centre blocks are sized so Commander spans one Panel and
# Crew + Alerts together span one Panel (two equal COMPACT halves), keeping all
# three columns three Panel-heights tall so rows line up across columns.
CLASS_WEIGHT = {PANEL: 30, COMPACT: 15, ANCHOR: 30}

CLASS_LABEL = {PANEL: "Panel", COMPACT: "Compact", ANCHOR: "Anchor"}

# ── Window registry ─────────────────────────────────────────────────────────
# Every dashboard window, its size class, and its display title.  Exploration
# and Exobiology are registered ahead of their widgets so the Display selector
# can offer them; callers pass an ``available`` set to hide not-yet-built ones.

BLOCK_CLASS = {
    "assets":       PANEL,
    "engineering":  PANEL,
    "career":       PANEL,
    "cargo":        PANEL,
    "exploration":  PANEL,
    "exobiology":   PANEL,
    "missions":     PANEL,
    "navigation":   PANEL,
    "colonisation": PANEL,
    "alerts":       COMPACT,
    "crew_slf":     COMPACT,
    "commander":    ANCHOR,
}

BLOCK_DISPLAY = {
    "assets":       "Assets",
    "engineering":  "Engineering",
    "career":       "Career",
    "cargo":        "Cargo",
    "exploration":  "Exploration",
    "exobiology":   "Exobiology",
    "missions":     "Massacre Mission Stack",
    "navigation":   "Navigation",
    "colonisation": "Colonisation",
    "alerts":       "Alerts",
    "crew_slf":     "Crew / SLF",
    "commander":    "Commander",
}

# ── Columns ───────────────────────────────────────────────────────────────────

COLUMNS = ("A", "B", "C")
COLUMN_TITLE = {"A": "Left", "B": "Centre", "C": "Right"}

# ── Default arrangement ─────────────────────────────────────────────────────
# Each column is an ordered list of (size_class, default_window | None).  This
# reproduces the current on-screen layout; Workstreams C/D change A1/A2 to the
# new windows.

DEFAULT_SLOTS: dict[str, list[tuple[str, Optional[str]]]] = {
    "A": [(PANEL, "career"), (PANEL, "cargo"), (PANEL, "missions")],
    "B": [(ANCHOR, "commander"), (COMPACT, "crew_slf"), (COMPACT, "alerts"), (PANEL, "exploration")],
    "C": [(PANEL, "navigation"), (PANEL, "colonisation"), (PANEL, "exobiology")],
}

ASSIGNMENT_VERSION = 1


# ── Slot helpers ────────────────────────────────────────────────────────────

def slot_ids() -> list[str]:
    """All position ids in display order: A1, A2, …, B1, …, C1, …."""
    out: list[str] = []
    for col in COLUMNS:
        for i in range(len(DEFAULT_SLOTS[col])):
            out.append(f"{col}{i + 1}")
    return out


def slots_in_column(col: str) -> list[str]:
    return [f"{col}{i + 1}" for i in range(len(DEFAULT_SLOTS.get(col, [])))]


def column_of(slot_id: str) -> str:
    return slot_id[0]


def _index_of(slot_id: str) -> int:
    return int(slot_id[1:]) - 1


def slot_class(slot_id: str) -> str:
    return DEFAULT_SLOTS[column_of(slot_id)][_index_of(slot_id)][0]


def default_block(slot_id: str) -> Optional[str]:
    return DEFAULT_SLOTS[column_of(slot_id)][_index_of(slot_id)][1]


def block_class(block: str) -> Optional[str]:
    return BLOCK_CLASS.get(block)


def block_display(block: str) -> str:
    return BLOCK_DISPLAY.get(block, block)


def eligible_blocks(size_class: str, available: Optional[set[str]] = None) -> list[str]:
    """Windows that may occupy a position of ``size_class``.

    ``available`` optionally restricts to windows that currently have a widget
    (so the Display selector hides not-yet-built ones).
    """
    out = [b for b, c in BLOCK_CLASS.items() if c == size_class]
    if available is not None:
        out = [b for b in out if b in available]
    return sorted(out, key=lambda b: block_display(b).lower())


# ── Assignment (position → window) ──────────────────────────────────────────

def default_assignment() -> dict[str, Optional[str]]:
    return {sid: default_block(sid) for sid in slot_ids()}


def normalize_assignment(raw: dict) -> dict[str, Optional[str]]:
    """Return a valid assignment from arbitrary input.

    Enforces the invariants the UIs rely on:
      - every known position is present;
      - a window only occupies a position of its own class (else cleared);
      - a window appears in at most one position (later duplicates cleared);
      - positions absent from ``raw`` (e.g. a position added in a newer model
        version) fall back to their default window when that window is free.
    """
    raw = raw or {}
    result: dict[str, Optional[str]] = {}
    seen: set[str] = set()
    for sid in slot_ids():
        blk = raw[sid] if sid in raw else default_block(sid)
        if (
            blk
            and BLOCK_CLASS.get(blk) == slot_class(sid)
            and blk not in seen
        ):
            result[sid] = blk
            seen.add(blk)
        else:
            result[sid] = None
    return result


# ── Layout derivation ───────────────────────────────────────────────────────

def _apportion(weights: list[int], total: int) -> list[int]:
    """Split ``total`` across ``weights`` as integers summing exactly to total
    (largest-remainder method)."""
    if not weights:
        return []
    s = sum(weights) or 1
    raw = [w / s * total for w in weights]
    floors = [int(x) for x in raw]
    rem = total - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: raw[i] - floors[i], reverse=True)
    for i in order[: max(0, rem)]:
        floors[i] += 1
    return floors


def occupied_slots(assignment: dict) -> dict[str, list[tuple[str, str]]]:
    """Per-column ordered ``[(slot_id, block), …]`` for non-empty positions."""
    out: dict[str, list[tuple[str, str]]] = {}
    for col in COLUMNS:
        col_slots = []
        for sid in slots_in_column(col):
            blk = assignment.get(sid)
            if blk:
                col_slots.append((sid, blk))
        out[col] = col_slots
    return out


def tui_columns(assignment: dict) -> dict[str, list[tuple[str, int]]]:
    """Per-column ordered ``[(block, height_percent), …]`` for the TUI."""
    occ = occupied_slots(assignment)
    out: dict[str, list[tuple[str, int]]] = {}
    for col in COLUMNS:
        slots = occ[col]
        pcts = _apportion([CLASS_WEIGHT[slot_class(sid)] for sid, _ in slots], 100)
        out[col] = [(blk, p) for (sid, blk), p in zip(slots, pcts)]
    return out


def summary(assignment: dict, available: Optional[set[str]] = None) -> list[dict]:
    """Display-tab view: one row per position with its class, current window,
    and eligible windows."""
    rows = []
    for sid in slot_ids():
        cls = slot_class(sid)
        rows.append({
            "slot": sid,
            "column": COLUMN_TITLE[column_of(sid)],
            "class": cls,
            "class_label": CLASS_LABEL[cls],
            "block": assignment.get(sid),
            "eligible": eligible_blocks(cls, available),
        })
    return rows


# ── Persistence ─────────────────────────────────────────────────────────────

def assignment_path() -> Path:
    from core.state import cmdr_data_dir
    return cmdr_data_dir() / "windows.json"


def load_assignment(path: Optional[Path] = None) -> dict[str, Optional[str]]:
    """Load the saved assignment, or the default arrangement when none exists."""
    p = path or assignment_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return normalize_assignment(data.get("slots", {}))
    except Exception:
        return default_assignment()


def save_assignment(assignment: dict, path: Optional[Path] = None) -> None:
    p = path or assignment_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": ASSIGNMENT_VERSION,
            "slots": normalize_assignment(assignment),
        }
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass
