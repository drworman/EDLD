"""
core/data_migrate.py — Moving cross-commander data out of commanders/<fid>/.

Some of what EDLD stores is a fact about a commander and some of it is a fact
about the galaxy.  A commodity's galactic average is the same number whoever
reads it off a market board, and a surface mining deposit is in the same place
whoever finds it, so neither has any business living under a commander id.
Stored there, a second commander started from nothing and the two copies then
drifted apart with no way to tell which was current.

``explo.db`` has always sat at the data root for exactly this reason.  This
module moves the rest of it into ``<EDLD_DATA_DIR>/data/`` and runs once.

The commodity ledger merge
--------------------------
This is not a file move.  Every commander directory may hold its own
``cargo.commodities.csv``, and they have to become one file without losing an
observation.  Per commodity:

    first_seen    earliest of the two — when *anyone* first saw it
    last_updated  latest of the two
    mean_price    from whichever row has the later last_updated
    updates       the sum

That last one is the trap.  The obvious merge picks a winning row and takes its
counters with it, which quietly discards the other commander's observation
count; the number that comes out still looks entirely plausible, which is why
it would never have been noticed.  Every merge is logged with the row count so
the arithmetic is checkable after the fact.

A migration that has run leaves a marker, so the second start does nothing.
Source files are left in place rather than deleted: nothing here is
irreplaceable enough to justify removing a commander's only copy on the
strength of a migration that has just run for the first time.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

MARKER_NAME = ".migrated-to-shared"

_LEDGER_BASENAME = "cargo.commodities.csv"
_LEDGER_COLUMNS  = ("name", "id", "name_localised", "category",
                    "category_localised", "mean_price", "first_seen",
                    "last_updated", "updates")


def _int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip() or default)
    except (TypeError, ValueError):
        return default


def _read_ledger(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                name = (row.get("name") or "").strip().lower()
                if name:
                    rows[name] = row
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    return rows


def _merge_row(have: dict, incoming: dict) -> dict:
    """Combine two records of the same commodity.  Neither side is authoritative."""
    out = dict(have)
    a_seen, b_seen = have.get("first_seen", ""), incoming.get("first_seen", "")
    out["first_seen"] = min(x for x in (a_seen, b_seen) if x) if (a_seen or b_seen) else ""

    a_upd, b_upd = have.get("last_updated", ""), incoming.get("last_updated", "")
    if b_upd > a_upd:
        out["last_updated"] = b_upd
        out["mean_price"]   = incoming.get("mean_price", have.get("mean_price", ""))
    # Sum the observation counts.  See the module docstring.
    out["updates"] = str(_int(have.get("updates")) + _int(incoming.get("updates")))
    # Fill in anything the older row never had.
    for col in ("id", "name_localised", "category", "category_localised"):
        if not out.get(col) and incoming.get(col):
            out[col] = incoming[col]
    return out


def _write_ledger(path: Path, rows: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(_LEDGER_COLUMNS),
                           extrasaction="ignore")
        w.writeheader()
        for name in sorted(rows):
            w.writerow({c: rows[name].get(c, "") for c in _LEDGER_COLUMNS})
    tmp.replace(path)


def migrate_to_shared(data_root: Path, shared: Path, log=None) -> dict:
    """Consolidate cross-commander data into ``shared``.  Idempotent.

    Returns a summary dict: ``{"ran": bool, "sources": int, "commodities": int,
    "merged": int}``.  Never raises — a failed migration leaves the per-commander
    files exactly where they were and says so, because the alternative is EDLD
    refusing to start over a housekeeping task.
    """
    def say(msg: str) -> None:
        if log:
            log(msg)

    summary = {"ran": False, "sources": 0, "commodities": 0, "merged": 0}
    marker = shared / MARKER_NAME
    if marker.exists():
        return summary

    try:
        shared.mkdir(parents=True, exist_ok=True)
        target = shared / _LEDGER_BASENAME
        merged: dict[str, dict] = _read_ledger(target) if target.is_file() else {}
        collisions = 0
        sources = 0

        cmdr_root = data_root / "commanders"
        candidates = sorted(cmdr_root.glob(f"*/data/{_LEDGER_BASENAME}")) \
            if cmdr_root.is_dir() else []

        for src in candidates:
            rows = _read_ledger(src)
            if not rows:
                continue
            sources += 1
            for name, row in rows.items():
                if name in merged:
                    merged[name] = _merge_row(merged[name], row)
                    collisions += 1
                else:
                    merged[name] = row
            say(f"commodity ledger: merged {len(rows)} row(s) from "
                f"{src.parent.parent.name}")

        if merged:
            _write_ledger(target, merged)
            say(f"commodity ledger consolidated — {len(merged)} commodities "
                f"from {sources} commander store(s), {collisions} merged")

        marker.write_text(json.dumps({
            "sources": sources,
            "commodities": len(merged),
            "merged": collisions,
        }), encoding="utf-8")

        summary.update(ran=True, sources=sources,
                       commodities=len(merged), merged=collisions)
        return summary

    except Exception as exc:
        say(f"migration to shared data directory failed — "
            f"{type(exc).__name__}: {exc}; per-commander files left in place")
        return summary


def shared_ledger_path() -> Path:
    """Where the commodity ledger lives now."""
    from core.state import shared_data_dir
    return shared_data_dir() / _LEDGER_BASENAME
