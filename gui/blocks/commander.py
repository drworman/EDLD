"""gui/blocks/commander.py — Commander / ship / location / vitals block (Qt)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTabWidget, QWidget,
)

from gui.block_base import GuiBlock, RowScroll, _health_cls
from gui.markup import to_html
from core.state import FUEL_CRIT_THRESHOLD, FUEL_WARN_THRESHOLD, CAPI_RANK_SKILLS

# ── Inline helpers (no UI-framework dependency) ───────────────────────────────

def fmt_shield(shields_up, recharging: bool) -> str:
    if shields_up is None: return "—"
    if shields_up:         return "Up"
    if recharging:         return "Recharging"
    return "Down"


def hull_css(pct: int) -> str:
    if pct > 75:  return "health-good"
    if pct >= 25: return "health-warn"
    return "health-crit"


def _pp_merits_for_rank(rank: int) -> int:
    if rank <= 1:   return 0
    if rank == 2:   return 2_000
    if rank == 3:   return 5_000
    if rank == 4:   return 9_000
    if rank == 5:   return 15_000
    if rank <= 100: return 15_000 + (rank - 5) * 8_000
    return 775_000 + (rank - 100) * 8_000


def pp_rank_progress(rank: int, total_merits: int) -> tuple:
    floor = _pp_merits_for_rank(rank)
    ceil  = _pp_merits_for_rank(rank + 1)
    span  = ceil - floor
    earned = max(0, total_merits - floor)
    fraction = min(1.0, earned / span) if span > 0 else 1.0
    return fraction, earned, span, rank + 1


class CommanderBlock(GuiBlock):
    BLOCK_TITLE = "COMMANDER"

    def _build_body(self, layout) -> None:
        self._hdr1 = QLabel()
        self._hdr1.setTextFormat(Qt.RichText)
        self._hdr1.setProperty("role", "hdrkey")
        self._hdr1.setContentsMargins(6, 0, 6, 0)
        self._hdr2 = QLabel()
        self._hdr2.setTextFormat(Qt.RichText)
        self._hdr2.setProperty("role", "hdrkey")
        self._hdr2.setContentsMargins(6, 0, 6, 0)
        layout.addWidget(self._hdr1)
        layout.addWidget(self._hdr2)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        info = RowScroll()
        self._r: dict[str, object] = {}

        def _row(key, wid):
            r = self.kv(key)
            self._r[wid] = r
            info.add_row(r)

        _row("Shields", "kv-shields")
        _row("Hull", "kv-hull")
        _row("Fuel", "kv-fuel")
        info.add_row(self.rule())
        _row("Mode", "kv-mode")
        _row("Home System", "kv-home")
        _row("Current System", "kv-system")
        _row("Location", "kv-body")
        info.add_row(self.rule())
        _row("Power", "kv-pp")
        _row("PP Rank", "kv-pprank")
        self._tabs.addTab(info, "Info")

        self._ranks = RowScroll()
        self._tabs.addTab(self._ranks, "Ranks")
        layout.addWidget(self._tabs, 1)

        footer = QWidget()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(6, 2, 6, 2)
        fl.setSpacing(8)
        self._home_btn = QPushButton("Set Home")
        self._home_btn.setProperty("role", "link")
        self._home_btn.clicked.connect(self._on_set_home)
        self._home_lbl = QLabel()
        self._home_lbl.setProperty("role", "dim")
        self._home_lbl.setTextFormat(Qt.RichText)
        self._home_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fl.addWidget(self._home_btn, 0)
        fl.addWidget(self._home_lbl, 1)
        layout.addWidget(footer)

    # ── Footer: home search ───────────────────────────────────────────────────

    def _on_set_home(self) -> None:
        cmdr_plugin = self.core._plugins.get("commander")
        spansh      = self.core._plugins.get("spansh")
        if not spansh:
            return

        from gui.search_dialog import SearchDialog

        def _on_select(result: dict | None) -> None:
            if not result or not cmdr_plugin:
                return
            cmdr_plugin.set_home_location(
                result.get("name", ""),
                result.get("system", ""),
                result.get("star_pos"),
            )
            name = result.get("name", "")
            self._home_lbl.setText(to_html(f"→ {name}" if name else "",
                                           self.palette_map))
            self.refresh_data()

        dlg = SearchDialog(
            parent       = self.window(),
            title        = "Set Home Location",
            placeholder  = "System or station name…",
            search_fn    = spansh.search_home,
            result_label = lambda r: (
                f"{'🚉' if r.get('is_station') else '⭐'} {r['name']}"
                + (f"  {r.get('system', '')}" if r.get("is_station") else "")
            ),
            theme        = self.theme,
        )
        dlg.accepted_result.connect(_on_select)
        dlg.exec()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_data(self) -> None:
        s = self.state

        # ── Header ────────────────────────────────────────────────────────────
        # Line 1: CMDR <n> - <VESSEL> (<DETAIL>)
        # Line 2: <SQUADRON RANK> - <SQUADRON NAME> [<TAG>]
        vessel_mode  = getattr(s, "vessel_mode",  "ship")
        srv_type     = getattr(s, "srv_type",     "")
        suit_name    = getattr(s, "suit_name",    "")
        suit_loadout = getattr(s, "suit_loadout", "")
        name         = s.pilot_name or ""

        if name:
            if vessel_mode == "on_foot":
                suit_str   = suit_name.upper() if suit_name else "ON FOOT"
                detail_str = suit_loadout.upper() if suit_loadout else ""
                hdr1 = (f"CMDR {name} - {detail_str} ({suit_str})"
                        if detail_str else f"CMDR {name} - {suit_str}")
            elif vessel_mode == "srv":
                hdr1 = f"CMDR {name} - {srv_type.upper() or 'SRV'}"
            else:
                ship_type = (s.pilot_ship or "").upper()
                parts     = [p.upper() for p in [s.ship_name, s.ship_ident] if p]
                detail    = " - ".join(parts)
                suffix    = " [IN FIGHTER]" if s.cmdr_in_slf else ""
                if detail and ship_type:
                    hdr1 = f"CMDR {name} - {detail} ({ship_type}){suffix}"
                elif ship_type:
                    hdr1 = f"CMDR {name} - {ship_type}{suffix}"
                else:
                    hdr1 = f"CMDR {name}{suffix}"
        else:
            hdr1 = "COMMANDER"

        # Line 2: squadron identity — reads the commander state fields.
        # The TUI escapes the opening bracket so Rich does not eat it; here
        # the tag is written plainly and the converter preserves it.
        sq_rank = getattr(s, "pilot_squadron_rank", "")
        sq_name = getattr(s, "pilot_squadron_name", "")
        sq_tag  = getattr(s, "pilot_squadron_tag",  "")
        if sq_name:
            tag_part  = f" [{sq_tag.upper()}]" if sq_tag else ""
            rank_part = f"{sq_rank.upper()} - " if sq_rank else ""
            hdr2 = f"{rank_part}{sq_name.upper()}{tag_part}"
        else:
            hdr2 = ""

        # The squadron tag renders as [SOL] and the fighter marker as
        # [IN FIGHTER]; the converter passes unrecognised bracketed tokens
        # through as literal text, so both survive intact.
        self._hdr1.setText(to_html(hdr1, self.palette_map))
        self._hdr2.setText(to_html(hdr2, self.palette_map))

        # ── Shields ───────────────────────────────────────────────────────────
        if vessel_mode == "on_foot":
            sh = "Up" if getattr(s, "suit_shields", True) else "Down"
            sh_cls = "val health-good" if getattr(s, "suit_shields", True) else "val health-crit"
        elif vessel_mode == "srv":
            sh, sh_cls = "—", "val"
        else:
            sh = fmt_shield(s.ship_shields, s.ship_shields_recharging)
            if s.ship_shields is None:
                sh_cls = "val"
            elif not s.ship_shields:
                sh_cls = "val health-warn" if s.ship_shields_recharging else "val health-crit"
            else:
                sh_cls = "val health-good"
        self._kv("kv-shields", sh, sh_cls)

        # ── Hull ──────────────────────────────────────────────────────────────
        hull_row = self._r.get("kv-hull")
        if hull_row is not None:
            hull_row.set_key("Health" if vessel_mode == "on_foot" else "Hull")
        if vessel_mode == "on_foot":
            self._kv("kv-hull", "—")
        elif vessel_mode == "srv":
            hull_pct = getattr(s, "srv_hull", 100)
            self._kv("kv-hull", f"{hull_pct}%", f"val {_health_cls(hull_pct)}")
        else:
            hull_pct = s.ship_hull
            if hull_pct is not None:
                self._kv("kv-hull", f"{hull_pct}%", f"val {_health_cls(hull_pct)}")
            else:
                self._kv("kv-hull", "—")

        # ── Fuel ─────────────────────────────────────────────────────────────
        fuel_current = s.fuel_current
        fuel_tank    = s.fuel_tank_size
        if fuel_current is not None and fuel_tank and fuel_tank > 0:
            fuel_pct = fuel_current / fuel_tank * 100
            fuel_str = f"{fuel_pct:.0f}%"
            burn = getattr(s, "fuel_burn_rate", None)
            if burn and burn > 0:
                secs = (fuel_current / burn) * 3600
                h, m = int(secs // 3600), int((secs % 3600) // 60)
                fuel_str += f"  (~{h}h {m}m)" if h > 0 else f"  (~{m}m)"
            if fuel_current < fuel_tank * FUEL_CRIT_THRESHOLD:
                fuel_cls = "val health-crit"
            elif fuel_current < fuel_tank * FUEL_WARN_THRESHOLD:
                fuel_cls = "val health-warn"
            else:
                fuel_cls = "val health-good"
            self._kv("kv-fuel", fuel_str, fuel_cls)
        else:
            self._kv("kv-fuel", "—")

        # ── Location ─────────────────────────────────────────────────────────
        self._kv("kv-mode", s.pilot_mode or "—")
        self._kv("kv-system", s.pilot_system or "—")

        # Home
        cmdr_plugin = self.core._plugins.get("commander") if self.core else None
        if cmdr_plugin:
            home = cmdr_plugin.get_home_location()
            if home:
                home_name = home["name"]
                home_sys  = home.get("system", home_name)
                is_stn    = home.get("is_station", home_name != home_sys and bool(home_sys))
                if is_stn and home_sys and home_sys != home_name:
                    display = f"{home_name}  ({home_sys})"
                else:
                    display = home_name
                dist = cmdr_plugin.home_distance_ly(getattr(s, "pilot_star_pos", None))
                if dist is not None:
                    display += f"  |  {dist:,.0f} ly"
                self._kv("kv-home", display)
                self._home_lbl.setText(
                    to_html(f"→ {home['name']}", self.palette_map))
            else:
                self._kv("kv-home", "unknown")
        else:
            self._kv("kv-home", "—")

        # Body
        if s.pilot_body:
            body_str = s.pilot_body
            if s.pilot_system and body_str.startswith(s.pilot_system):
                body_str = body_str[len(s.pilot_system):].lstrip()
            self._kv("kv-body", body_str or "—")
        else:
            self._kv("kv-body", "—")

        # ── Powerplay ─────────────────────────────────────────────────────────
        self._kv("kv-pp", s.pp_power or "—")
        if s.pp_rank:
            merits = s.pp_merits_total
            if merits is not None:
                frac, earned, span, nxt = pp_rank_progress(s.pp_rank, merits)
                self._kv("kv-pprank", f"Rank {s.pp_rank}  {int(frac*100)}%")
            else:
                self._kv("kv-pprank", f"Rank {s.pp_rank}")
        else:
            self._kv("kv-pprank", "—")

        # ── Ranks tab ─────────────────────────────────────────────────────────
        capi_ranks = getattr(s, "capi_ranks", None)
        capi_prog  = getattr(s, "capi_rank_progress", None) or {}
        if capi_ranks:
            rows: list = []
            for capi_key, display_lbl, table in CAPI_RANK_SKILLS:
                idx = capi_ranks.get(capi_key)
                if idx is None:
                    continue
                rank_name = table[idx] if 0 <= idx < len(table) else str(idx)
                prog = capi_prog.get(capi_key)
                val  = f"{rank_name}  +{prog}%" if prog is not None else rank_name
                rows.append(self.kv(display_lbl, val))
            self._ranks.set_rows(rows)
        else:
            self._ranks.set_rows([self.text("Awaiting CAPI data…", "dim")])

    def _kv(self, wid: str, text: str, classes: str = "val") -> None:
        row = self._r.get(wid)
        if row is not None:
            row.set_value(text, classes)
