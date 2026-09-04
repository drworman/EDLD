"""
components/mining.py — Mining session tracking.

Tracks prospected asteroids (with content distribution and per-commodity
yield % statistics), refined tonnage and tonnes-per-hour, real-time
refinement RPM via a rolling window, collection and prospector limpet
counts, and duplicate/already-mined asteroid detection.

Income from selling mined cargo is tracked by the trade component.

Tab title: Mining
"""

import time
from collections import deque

from core.plugin_loader import BasePlugin
from core.activity import ActivityProviderMixin
from core.emit import fmt_credits

# Rolling window for RPM calculation (seconds)
_RPM_WINDOW = 10


def _canonicalise(raw: str) -> str:
    """Strip $..._name; localisation wrapper and lowercase."""
    s = (raw or "").strip().lower()
    if s.startswith("$") and s.endswith(";"):
        inner = s[1:-1]
        if inner.endswith("_name"):
            s = inner[:-5]
        else:
            s = inner
    return s


def _content_label(raw: str) -> str:
    """Return High / Medium / Low from the Content field."""
    s = (raw or "").lower()
    if "high"   in s: return "High"
    if "medium" in s: return "Medium"
    if "low"    in s: return "Low"
    return "Unknown"


def _ring_class(raw: str) -> str:
    """Turn eRingClass_Metalic into "Metallic".

    The journal's spellings are internal and inconsistent ("Metalic" has one
    l, "MetalRich" is camel case), so they are mapped rather than prettified
    by string surgery.
    """
    key = (raw or "").replace("eRingClass_", "").strip().lower()
    return {
        "metalic":   "Metallic",
        "metallic":  "Metallic",
        "metalrich": "Metal-rich",
        "rocky":     "Rocky",
        "icy":       "Icy",
    }.get(key, key.title())


def _prospect_key(materials: list[dict]) -> tuple:
    """
    Deterministic key for a set of prospected materials.
    Used to detect duplicate prospecting of the same asteroid.
    """
    return tuple(sorted(
        (_canonicalise(m.get("Name", "")), round(m.get("Proportion", 0.0), 1))
        for m in materials
    ))


class ActivityMiningPlugin(BasePlugin, ActivityProviderMixin):
    PLUGIN_NAME         = "mining"
    PLUGIN_DISPLAY      = "Mining Activity"
    PLUGIN_VERSION      = "2.0.0"
    PLUGIN_DESCRIPTION  = "Tracks prospecting, refined tonnage, yield quality, and limpet efficiency."
    ACTIVITY_TAB_TITLE  = "Mining"

    SUBSCRIBED_EVENTS = [
        "MiningRefined",
        "ProspectedAsteroid",
        "LaunchDrone",
        # Limpet stock lives in Cargo as the "drones" commodity — the only
        # place the journal reports it.  Running dry ends a session, so the
        # remaining count is the single most actionable number here.
        "Cargo",
        # Raw materials picked up while mining are a real part of the haul
        # and were previously invisible.
        "MaterialCollected",
        # Ring context: what you are sitting in and whether it is worth
        # sitting in.  Reserve level and ring class come from the parent
        # body's Scan; hotspots from the ring's surface scan.
        "Scan",
        "SAASignalsFound",
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        core.register_session_provider(self)
        self._reset_counters()

    def _reset_counters(self) -> None:
        self.tonnes_refined:        float = 0.0
        self.asteroids_prospected:  int   = 0
        self.limpets_collection:    int   = 0
        self.limpets_prospector:    int   = 0
        self.duplicates:            int   = 0
        self.already_mined:         int   = 0
        self.session_start_time           = None

        # Content distribution: High / Medium / Low / Unknown → count
        self.content_counts: dict[str, int] = {}

        # Per-commodity yield % samples from ProspectedAsteroid
        # key: canonical commodity name, value: list of float proportions
        self.yield_samples: dict[str, list[float]] = {}

        # Per-commodity refined tonnes (for tab breakdown)
        self.material_tally: dict[str, float] = {}

        # Duplicate detection: set of prospect keys seen this session
        self._seen_keys: set[tuple] = set()

        # Rolling window of MiningRefined timestamps for RPM
        self._recent_refines: deque = deque()
        self.max_rpm: float = 0.0

        # Limpet stock, observed from Cargo events
        self.limpets_remaining: int | None = None
        self.limpets_start:     int | None = None

        # Raw materials collected while mining (MaterialCollected)
        self.materials_collected: dict[str, int] = {}

        # Ring context for wherever we are mining
        self.ring_name:     str = ""
        self.ring_type:     str = ""
        self.reserve_level: str = ""
        self.hotspots: dict[str, int] = {}

    def on_session_reset(self) -> None:
        self._reset_counters()

    def _update_rpm(self) -> float:
        """Recompute RPM from the rolling window; prune stale entries."""
        now    = time.monotonic()
        cutoff = now - _RPM_WINDOW
        while self._recent_refines and self._recent_refines[0] < cutoff:
            self._recent_refines.popleft()
        count = len(self._recent_refines)
        rpm   = (count * 60.0) / _RPM_WINDOW if _RPM_WINDOW else 0.0
        if rpm > self.max_rpm:
            self.max_rpm = rpm
        return rpm

    def _tph(self) -> float | None:
        """Tonnes per hour since session start, or None if insufficient data."""
        if self.session_start_time is None or self.tonnes_refined <= 0:
            return None
        state = self.core.state
        if not state.event_time:
            return None
        elapsed = (state.event_time - self.session_start_time).total_seconds()
        if elapsed < 60:
            return None
        return self.tonnes_refined / (elapsed / 3600.0)

    def on_event(self, event: dict, state) -> None:
        ev      = event.get("event")
        logtime = event.get("_logtime")
        gq      = self.core.gui_queue

        match ev:

            case "MiningRefined":
                if self.session_start_time is None:
                    self.session_start_time = logtime
                raw_name   = event.get("Type_Localised") or event.get("Type", "Unknown")
                canon_name = _canonicalise(event.get("Type", ""))
                display    = raw_name.strip() if raw_name.strip() else canon_name
                self.tonnes_refined += 1.0
                self.material_tally[display] = self.material_tally.get(display, 0.0) + 1.0
                self._recent_refines.append(time.monotonic())
                self._update_rpm()
                if gq: gq.put(("stats_update", None))

            case "ProspectedAsteroid":
                if self.session_start_time is None:
                    self.session_start_time = logtime

                self.asteroids_prospected += 1

                # Content distribution
                content = _content_label(event.get("Content_Localised") or event.get("Content", ""))
                self.content_counts[content] = self.content_counts.get(content, 0) + 1

                # Already-mined detection (Remaining < 100 %)
                remaining = event.get("Remaining", 100.0)
                if remaining is not None and remaining < 99.9:
                    self.already_mined += 1

                # Duplicate detection via material composition hash
                materials = event.get("Materials", [])
                key = _prospect_key(materials)
                if key in self._seen_keys:
                    self.duplicates += 1
                else:
                    self._seen_keys.add(key)

                # Accumulate yield % samples per commodity
                for mat in materials:
                    name = (mat.get("Name_Localised") or mat.get("Name", "")).strip()
                    pct  = float(mat.get("Proportion", 0.0))
                    if name and pct > 0:
                        if name not in self.yield_samples:
                            self.yield_samples[name] = []
                        self.yield_samples[name].append(pct)

            case "LaunchDrone":
                dtype = event.get("Type", "")
                if dtype == "Collection":
                    self.limpets_collection += 1
                elif dtype == "Prospector":
                    self.limpets_prospector += 1

            case "Cargo":
                # Limpets are carried as the "drones" commodity.  A Cargo
                # event with no Inventory is the summary form written when
                # the full list went to Cargo.json; ignore those rather than
                # reading them as "zero limpets".
                inventory = event.get("Inventory")
                if not isinstance(inventory, list):
                    return
                drones = 0
                for item in inventory:
                    if _canonicalise(item.get("Name", "")) == "drones":
                        drones = int(item.get("Count", 0) or 0)
                        break
                self.limpets_remaining = drones
                # Highest stock seen this session is the best available
                # estimate of what we set out with, since a restock mid-run
                # should not make consumption look negative.
                if self.limpets_start is None or drones > self.limpets_start:
                    self.limpets_start = drones
                if gq: gq.put(("stats_update", None))

            case "MaterialCollected":
                name = (event.get("Name_Localised")
                        or event.get("Name", "")).strip()
                if name:
                    count = int(event.get("Count", 1) or 1)
                    self.materials_collected[name] = (
                        self.materials_collected.get(name, 0) + count)

            case "Scan":
                # The ring we are mining belongs to a body whose Scan carries
                # the reserve level; the ring's class comes from the matching
                # entry in that body's Rings list.
                reserve = (event.get("ReserveLevel") or "").replace(
                    "Resources", "").strip()
                if reserve:
                    self.reserve_level = reserve
                body = str(getattr(state, "pilot_body", "") or "")
                for ring in (event.get("Rings") or []):
                    if str(ring.get("Name", "")) == body:
                        self.ring_name = body
                        self.ring_type = _ring_class(ring.get("RingClass", ""))
                        break

            case "SAASignalsFound":
                # Hotspots in the ring: the reason to be in this ring rather
                # than the identical-looking one next door.
                body = str(event.get("BodyName", "") or "")
                if body:
                    self.ring_name = body
                for sig in (event.get("Signals") or []):
                    name = (sig.get("Type_Localised")
                            or sig.get("Type", "")).strip()
                    if name:
                        self.hotspots[name] = int(sig.get("Count", 0) or 0)

    # ── ActivityProviderMixin ─────────────────────────────────────────────────

    def has_activity(self) -> bool:
        return self.tonnes_refined > 0 or self.asteroids_prospected > 0

    def _refined_value_est(self) -> int:
        mean_prices = getattr(self.core.state, "cargo_mean_prices", {}) or {}
        total = 0
        for material, tonnes in self.material_tally.items():
            price = mean_prices.get(material.lower(), 0)
            total += price * tonnes
        return total

    def ring_context(self) -> str:
        """One-line description of where we're mining, or "" if unknown.

        Reserve level is the number that decides whether a ring is worth
        working, so it leads when present.
        """
        parts = [p for p in (self.reserve_level, self.ring_type) if p]
        if self.hotspots:
            top = sorted(self.hotspots.items(), key=lambda kv: -kv[1])
            parts.append(", ".join(
                f"{name} x{n}" if n > 1 else name for name, n in top[:3]))
        return " · ".join(parts)

    def cargo_fill(self) -> tuple[int, int] | None:
        """(tonnes carried, capacity), or None when capacity is unknown."""
        state = self.core.state
        cap = int(getattr(state, "cargo_capacity", 0) or 0)
        if cap <= 0:
            return None
        items = getattr(state, "cargo_items", {}) or {}
        carried = sum(int((v or {}).get("count", 0) or 0) for v in items.values())
        return carried, cap

    def get_summary_rows(self) -> list[dict]:
        rows = []
        tph  = self._tph()
        if self.tonnes_refined > 0:
            value_est = self._refined_value_est()
            rate_parts = []
            if tph is not None:
                rate_parts.append(f"{tph:.1f} t/hr")
            if value_est:
                rate_parts.append(f"{fmt_credits(value_est)} est.")
            rows.append({
                "label": "Tonnes refined",
                "value": f"{self.tonnes_refined:.0f} t",
                "rate":  "  ".join(rate_parts) if rate_parts else None,
            })
        if self.asteroids_prospected > 0:
            rpm = self._update_rpm()
            rpm_str = f"{rpm:.0f} RPM" if rpm > 0 else (f"max {self.max_rpm:.0f} RPM" if self.max_rpm > 0 else None)
            # Hit rate is what tells you whether the ring is worth staying in.
            hit = None
            high = self.content_counts.get("High", 0)
            if self.asteroids_prospected:
                hit = f"{high / self.asteroids_prospected * 100:.0f}% high"
            rows.append({
                "label": "Prospected",
                "value": str(self.asteroids_prospected),
                "rate":  "  ".join(x for x in (rpm_str, hit) if x) or None,
            })

        # Cargo fill — the thing that decides when the run ends.
        fill = self.cargo_fill()
        if fill and self.tonnes_refined > 0:
            carried, cap = fill
            rows.append({
                "label": "Cargo",
                "value": f"{carried} / {cap} t",
                "rate":  f"{carried / cap * 100:.0f}% full" if cap else None,
            })

        # Limpets remaining — the other thing that ends a run.
        if self.limpets_remaining is not None and (
                self.limpets_prospector or self.limpets_collection):
            used = None
            if self.limpets_start is not None:
                used = max(self.limpets_start - self.limpets_remaining, 0)
            rows.append({
                "label": "Limpets left",
                "value": str(self.limpets_remaining),
                "rate":  f"{used} used" if used else None,
            })

        # Where this was mined.  Without it the numbers above have no
        # context — 180 t is excellent in a depleted ring and mediocre in a
        # pristine one.
        ring = self.ring_context()
        if ring and rows:
            rows.append({"label": "Ring", "value": ring, "rate": None})
        return rows

    def get_tab_rows(self) -> list[dict]:
        rows = self.get_summary_rows()

        # Ring context leads: reserve level and hotspots decide whether the
        # numbers below are good or bad for where you are.
        ring = self.ring_context()
        if ring or self.ring_name:
            rows.append({"label": "─── Ring ───", "value": "", "rate": None})
            if self.ring_name:
                rows.append({"label": "  Body", "value": self.ring_name, "rate": None})
            if self.reserve_level:
                rows.append({"label": "  Reserves", "value": self.reserve_level, "rate": None})
            if self.ring_type:
                rows.append({"label": "  Type", "value": self.ring_type, "rate": None})
            for name, n in sorted(self.hotspots.items(), key=lambda kv: -kv[1]):
                rows.append({"label": f"  {name}",
                             "value": f"{n} hotspot{'s' if n != 1 else ''}",
                             "rate": None})

        # Content distribution
        if self.content_counts:
            parts = []
            for label in ("High", "Medium", "Low", "Unknown"):
                n = self.content_counts.get(label, 0)
                if n:
                    parts.append(f"{label}: {n}")
            if parts:
                rows.append({
                    "label": "Content",
                    "value": "  ".join(parts),
                    "rate":  None,
                })

        # Already-mined and duplicates
        if self.already_mined > 0:
            rows.append({"label": "Already mined", "value": str(self.already_mined), "rate": None})
        if self.duplicates > 0:
            rows.append({"label": "Duplicates",    "value": str(self.duplicates),    "rate": None})

        # Limpets
        if self.limpets_prospector > 0 or self.limpets_collection > 0:
            rows.append({"label": "─── Limpets ───", "value": "", "rate": None})
            if self.limpets_prospector > 0:
                # Prospector efficiency: asteroids per limpet
                eff = (f"{self.asteroids_prospected / self.limpets_prospector:.1f}/limpet"
                       if self.limpets_prospector > 0 and self.asteroids_prospected > 0 else None)
                rows.append({"label": "  Prospector", "value": str(self.limpets_prospector), "rate": eff})
            if self.limpets_collection > 0:
                coll_eff = (f"{self.tonnes_refined / self.limpets_collection:.1f} t/limpet"
                            if self.tonnes_refined > 0 else None)
                rows.append({"label": "  Collection", "value": str(self.limpets_collection), "rate": coll_eff})

        # Per-commodity yield stats
        if self.yield_samples:
            rows.append({"label": "─── Yield % by commodity ───", "value": "", "rate": None})
            for name in sorted(self.yield_samples, key=lambda n: -len(self.yield_samples[n])):
                samples = self.yield_samples[name]
                n_ast   = len(samples)
                mn      = min(samples)
                avg     = sum(samples) / n_ast
                mx      = max(samples)
                pct_ast = (n_ast / self.asteroids_prospected * 100.0) if self.asteroids_prospected else 0.0
                rows.append({
                    "label": f"  {name}",
                    "value": f"{n_ast} ast ({pct_ast:.0f}%)",
                    "rate":  f"{mn:.1f}–{avg:.1f}–{mx:.1f}%",
                })

        # Refined material breakdown
        if self.material_tally:
            rows.append({"label": "─── Refined ───", "value": "", "rate": None})
            for mat, count in sorted(self.material_tally.items(), key=lambda x: -x[1]):
                rows.append({"label": f"  {mat}", "value": f"{count:.0f} t", "rate": None})

        # Raw materials picked up alongside the ore.  Not tonnage, but part
        # of what the session produced.
        if self.materials_collected:
            rows.append({"label": "─── Materials ───", "value": "", "rate": None})
            for mat, count in sorted(self.materials_collected.items(),
                                     key=lambda x: -x[1]):
                rows.append({"label": f"  {mat}", "value": str(count), "rate": None})

        return rows
