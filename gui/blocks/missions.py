"""
gui/blocks/missions.py — Mission Stack block.

Shows the full massacre stack analysis: per-faction kill counts, rewards,
delta-to-max, stack height, and warnings. Data is sourced directly from
state.mission_detail_map which is now persisted through restarts.

Live session kill progress (kills_this_session per mission) is shown when
available, giving real-time kill-to-completion tracking.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from core.emit import fmt_credits
from gui.block_base import BlockWidget


def _strip_target_type(raw: str) -> str:
    s = raw or ""
    if s.startswith("$") and s.endswith(";"):
        inner = s[1:-1]
        if "_" in inner:
            s = inner.rsplit("_", 1)[-1]
    return s.strip()


class MissionsBlock(BlockWidget):
    BLOCK_TITLE = "Mission Stack"
    BLOCK_CSS   = "missions-block"

    DEFAULT_COL    = 0
    DEFAULT_ROW    = 6
    DEFAULT_WIDTH  = 8
    DEFAULT_HEIGHT = 4

    def build(self, parent: Gtk.Box) -> None:
        body = self._build_section(parent)
        self._scroll_body = self._make_scroll_body(body)

    def _make_row(self) -> tuple[Gtk.Box, Gtk.Label, Gtk.Label, Gtk.Label]:
        """Create a 3-column data row: label | value | rate."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.add_css_class("data-row")
        lbl  = Gtk.Label()
        lbl.add_css_class("data-key")
        lbl.set_xalign(0.0)
        lbl.set_hexpand(True)
        val  = Gtk.Label()
        val.add_css_class("data-value")
        val.set_xalign(1.0)
        rate = Gtk.Label()
        rate.add_css_class("stat-line")
        rate.set_xalign(1.0)
        row.append(lbl)
        row.append(val)
        row.append(rate)
        return row, lbl, val, rate

    def _clear(self) -> None:
        child = self._scroll_body.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._scroll_body.remove(child)
            child = nxt

    def _append_grid_row(self, grid: Gtk.Grid, row_idx: int,
                          label: str, value: str, rate: str | None = None) -> int:
        lbl = Gtk.Label(label=label)
        lbl.add_css_class("data-key")
        lbl.set_xalign(0.0)
        lbl.set_hexpand(True)
        grid.attach(lbl, 0, row_idx, 1, 1)

        if rate is not None:
            val_lbl = Gtk.Label(label=value)
            val_lbl.add_css_class("data-value")
            val_lbl.set_xalign(1.0)
            grid.attach(val_lbl, 1, row_idx, 1, 1)

            pipe = Gtk.Label(label="|")
            pipe.add_css_class("data-key")
            pipe.set_xalign(0.5)
            grid.attach(pipe, 2, row_idx, 1, 1)

            rate_lbl = Gtk.Label(label=rate)
            rate_lbl.add_css_class("stat-line")
            rate_lbl.set_xalign(1.0)
            grid.attach(rate_lbl, 3, row_idx, 1, 1)
        else:
            val_lbl = Gtk.Label(label=value)
            val_lbl.add_css_class("data-value")
            val_lbl.set_xalign(1.0)
            grid.attach(val_lbl, 1, row_idx, 3, 1)

        return row_idx + 1

    def _append_section_header(self, grid: Gtk.Grid, title: str, row_idx: int) -> int:
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.set_margin_top(4)
        hbox.set_margin_bottom(2)
        lbl = Gtk.Label(label=title)
        lbl.add_css_class("section-header")
        lbl.set_xalign(0.0)
        hbox.append(lbl)
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_hexpand(True)
        sep.set_valign(Gtk.Align.CENTER)
        hbox.append(sep)
        grid.attach(hbox, 0, row_idx, 4, 1)
        return row_idx + 1

    def refresh(self) -> None:
        self._clear()
        s = self.state

        detail = getattr(s, "mission_detail_map", {})
        if not detail:
            lbl = Gtk.Label(label="No active massacre missions")
            lbl.add_css_class("data-key")
            lbl.set_xalign(0.0)
            self._scroll_body.append(lbl)
            return

        # ── Build analysis ────────────────────────────────────────────────────
        factions:        dict[str, dict] = {}
        target_factions: set[str]        = set()
        target_types:    set[str]        = set()
        total_reward     = 0
        total_wing       = 0

        for mid, info in detail.items():
            src      = info.get("faction", "Unknown")
            kc       = int(info.get("kill_count", 0))
            reward   = int(info.get("reward", 0))
            is_wing  = bool(info.get("wing", False))
            tgt_f    = info.get("target_faction", "")
            tgt_t    = _strip_target_type(info.get("target_type", ""))
            sess_k   = int(info.get("kills_this_session", 0))

            if src not in factions:
                factions[src] = {"kill_count": 0, "reward": 0, "wing_reward": 0,
                                 "session_kills": 0}
            factions[src]["kill_count"]    += kc
            factions[src]["reward"]        += reward
            factions[src]["session_kills"] += sess_k
            if is_wing:
                factions[src]["wing_reward"] += reward

            total_reward += reward
            if is_wing:
                total_wing += reward
            if tgt_f:
                target_factions.add(tgt_f)
            if tgt_t:
                target_types.add(tgt_t)

        heights      = sorted((v["kill_count"] for v in factions.values()), reverse=True)
        stack_height = heights[0] if heights else 0
        second_h     = heights[1] if len(heights) > 1 else stack_height
        n_missions   = len(getattr(s, "active_missions", []))
        done         = getattr(s, "missions_complete", 0)
        remaining    = n_missions - done

        # ── Grid layout ───────────────────────────────────────────────────────
        grid = Gtk.Grid()
        grid.set_column_spacing(4)
        grid.set_row_spacing(1)
        grid.add_css_class("stats-grid")
        self._scroll_body.append(grid)
        row = 0

        # Header row: mission count | total value
        settings   = self.core.app_settings
        full_stack = settings.get("FullStackSize", 20)
        row = self._append_grid_row(grid, row,
                                    "Active missions",
                                    f"{n_missions}/{full_stack}",
                                    None)

        # Completion status
        if done > 0 or remaining == 0:
            if remaining == 0:
                status_val = f"{done}/{n_missions}"
                status_lbl = Gtk.Label(label="Complete")
                status_lbl.add_css_class("data-key")
                status_lbl.add_css_class("status-ready")
                status_lbl.set_xalign(0.0)
                status_lbl.set_hexpand(True)
                grid.attach(status_lbl, 0, row, 1, 1)
                sv = Gtk.Label(label=status_val)
                sv.add_css_class("data-value")
                sv.add_css_class("status-ready")
                sv.set_xalign(1.0)
                grid.attach(sv, 1, row, 3, 1)
            else:
                row = self._append_grid_row(grid, row,
                                            "Redirected",
                                            f"{done}/{n_missions}", None)
            row += 1

        # Per-faction breakdown
        row = self._append_section_header(grid, "By source faction", row)

        for faction in sorted(factions, key=lambda f: -factions[f]["kill_count"]):
            info   = factions[faction]
            kc     = info["kill_count"]
            rew_f  = info["reward"]
            wing_f = info["wing_reward"]

            delta = stack_height - kc
            if delta == 0:
                delta_str = f"Δ{second_h - kc:+d}" if second_h != kc else "★ max"
            else:
                delta_str = f"Δ{-delta:+d}"

            rew_f_str = f"{rew_f/1_000_000:.1f}M"
            if wing_f and wing_f != rew_f:
                rew_f_str += f" ({wing_f/1_000_000:.1f}M wing)"

            val_str  = f"{kc} kills"

            row = self._append_grid_row(grid, row,
                                        f"  {faction}", val_str,
                                        f"{rew_f_str}  {delta_str}")

        # Stack height — shows computed kill height | total credit value of stack.
        # Wing missions noted in parentheses when present.
        rew_str  = fmt_credits(total_reward) if total_reward else "—"
        if total_wing:
            rew_str += f" ({fmt_credits(total_wing)} wing)"
        row = self._append_grid_row(grid, row,
                                    "Stack height",
                                    str(stack_height),
                                    rew_str)

        # Warnings
        if len(target_factions) > 1:
            row = self._append_grid_row(grid, row,
                                        f"  ⚠ Mixed targets: {', '.join(sorted(target_factions))}",
                                        "", None)
        if len(target_types) > 1:
            row = self._append_grid_row(grid, row,
                                        f"  ⚠ Mixed types: {', '.join(sorted(target_types))}",
                                        "", None)
