"""
tui/blocks/status.py — Crew / Alerts window (Textual).

Two readouts that are almost never busy at the same time, so they share one
window rather than each holding a slot of their own.  Crew and fighter status
is a short fixed set of rows, empty unless a fighter is deployed or crew is
hired; alerts are empty until something fires.  Crew above, alerts flowing
beneath.

A second tab holds the radio.  An alert that needs a tab change to see is an
alert you miss, so any new alert brings the Crew / Alerts tab back to the
front; the radio carries on playing.  The radio itself lives in core/radio.py
and is shared with the desktop window — this file only draws it.
"""
from __future__ import annotations
from datetime import datetime, timezone
from textual.app       import ComposeResult
from textual.widgets   import Label, Select, Static, TabbedContent, TabPane
from textual.containers import VerticalScroll, Horizontal, Vertical
from rich.text         import Text
from core.radio        import AlertWatcher, RadioController, RadioError
from tui.block_base    import (
    TuiBlock, KVRow, HRule, SecHdr, _health_cls, _fmt_credits,
)

# ── Inline helpers (no UI-framework dependency) ───────────────────────────────────────

def hull_css(pct: int) -> str:
    if pct > 75:  return "health-good"
    if pct >= 25: return "health-warn"
    return "health-crit"

PP_RANK_NAMES = [
    "Harmless", "Mostly Harmless", "Novice", "Competent", "Expert",
    "Master", "Dangerous", "Deadly", "Elite",
    "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V",
]

def fmt_crew_active(delta) -> str:
    total_days = int(delta.total_seconds() // 86400)
    if total_days < 1:
        return "<1d"
    years,  rem_days = divmod(total_days, 365)
    months, days     = divmod(rem_days, 30)
    parts = []
    if years:  parts.append(f"{years}y")
    if months: parts.append(f"{months}mo")
    if days and len(parts) < 2: parts.append(f"{days}d")
    return " ".join(parts) or "<1d"

#: Alert rows kept on screen.  Sized so a burst during combat does not push
#: the crew readout out of the window.
_MAX_ROWS = 5


class StatusBlock(TuiBlock):
    BLOCK_TITLE = "CREW / ALERTS"

    def compose(self) -> ComposeResult:
        with TabbedContent(id="status-tabs"):
            with TabPane("Crew / Alerts", id="status-tab-crew"):
                with Horizontal(id="crew-name-row"):
                    yield Label("", id="crew-name-lbl")
                    yield Label("", id="crew-type-lbl")
                yield Label("", id="crew-rank-lbl", classes="block-title")
                with VerticalScroll():
                    yield KVRow("SLF",    id="kv-slf")
                    yield KVRow("Hired",  id="kv-hired")
                    yield KVRow("Active", id="kv-active")
                    yield KVRow("Paid",   id="kv-paid")
                    # The two halves share a window, so they need a visible
                    # seam.  Without one, an alert reads as another crew row.
                    yield KVRow("", "")
                    yield SecHdr("Alerts")
                    yield HRule()
                    with Vertical(id="status-alerts"):
                        for i in range(_MAX_ROWS):
                            yield Label("", id=f"alert-{i}", classes="alert-entry")
            with TabPane("Radio", id="status-tab-radio"):
                yield RadioPanel(self.core, id="radio-panel")

    def on_mount(self) -> None:
        self._alert_watch = AlertWatcher()

    def refresh_data(self) -> None:
        self._refresh_crew()
        self._refresh_alerts()

    def _refresh_crew(self) -> None:
        s        = self.state
        has_crew = bool(s.crew_name) and s.crew_active

        if not has_crew:
            self._lbl("crew-name-lbl", "No NPC crew")
            self._lbl("crew-type-lbl", "")
            self._lbl("crew-rank-lbl", "")
            self._kv("kv-slf",    "—")
            self._kv("kv-hired",  "—")
            self._kv("kv-active", "—")
            self._kv("kv-paid",   "—")
            return

        # ── Header: CREW: <name> (left)   <model> (<variant>) (right) ───────
        # The fighter's model and its variant are one designation — "GU-97
        # (Gelid G)" — and they belong together. Splitting them, with the
        # model on the header row and the variant parked at the end of the
        # combat-rank line, meant neither line read as a complete answer to
        # "what is this crew flying".
        slf_full = (s.slf_type or "").strip()
        if "(" in slf_full and slf_full.endswith(")"):
            paren       = slf_full.index("(")
            slf_base    = slf_full[:paren].strip()
            slf_variant = slf_full[paren + 1:-1].strip()
        else:
            slf_base    = slf_full
            slf_variant = ""

        if slf_base and slf_variant:
            slf_label = f"{slf_base} ({slf_variant})"
        else:
            slf_label = slf_base or slf_variant

        crew_label = f"CREW: {s.crew_name or 'NPC'}"
        if s.cmdr_in_slf:
            crew_label += "  [IN FIGHTER]"
        self._lbl("crew-name-lbl", crew_label)
        self._lbl("crew-type-lbl", slf_label)

        rank_str = ""
        if s.crew_rank is not None and 0 <= s.crew_rank < len(PP_RANK_NAMES):
            rank_str = f"Combat Rank: {PP_RANK_NAMES[s.crew_rank]}"
        self._lbl("crew-rank-lbl", rank_str)

        # ── SLF status ────────────────────────────────────────────────────────
        has_bay = s.has_fighter_bay
        try:
            self.query_one("#kv-slf", KVRow).display = has_bay
        except Exception:
            pass
        if has_bay:
            all_spent = (
                s.slf_stock_total > 0
                and s.slf_destroyed_count >= s.slf_stock_total
                and not s.slf_docked and not s.slf_deployed
            )
            if s.cmdr_in_slf:
                hull_str = f"{s.slf_hull}%" if s.slf_hull is not None else "—"
                self._kv("kv-slf", f"CMDR Aboard  |  Hull {hull_str}", "val health-good")
            elif s.slf_docked:
                self._kv("kv-slf", "SLF Docked", "val health-good")
            elif s.slf_deployed:
                hull_str = f"Hull {s.slf_hull}%" if s.slf_hull is not None else "Hull —"
                cls = f"val {_health_cls(s.slf_hull)}" if s.slf_hull is not None else "val health-good"
                self._kv("kv-slf", hull_str, cls)
            elif all_spent:
                self._kv("kv-slf", "All Spent", "val health-crit")
            else:
                self._kv("kv-slf", "Destroyed", "val health-crit")

        # ── Context ───────────────────────────────────────────────────────────
        self._kv("kv-hired",
                 s.crew_hire_time.strftime("%d %b %Y") if s.crew_hire_time else "Unknown")
        if s.crew_hire_time:
            delta = datetime.now(timezone.utc) - s.crew_hire_time
            self._kv("kv-active", fmt_crew_active(delta))
        else:
            self._kv("kv-active", "—")

        if s.crew_total_paid and s.crew_total_paid > 0:
            prefix = "" if s.crew_paid_complete else "≥ "
            self._kv("kv-paid", f"{prefix}{_fmt_credits(s.crew_total_paid)}")
        else:
            self._kv("kv-paid", "—")

    def _kv(self, wid: str, text: str, classes: str = "val") -> None:
        try:
            self.query_one(f"#{wid}", KVRow).set_value(text, classes)
        except Exception:
            pass

    def _lbl(self, wid: str, text: str) -> None:
        try:
            self.query_one(f"#{wid}", Label).update(text)
        except Exception:
            pass

    def _refresh_alerts(self) -> None:
        alerts = self.core.plugin_call("alerts", "get_alerts") or []
        watch = getattr(self, "_alert_watch", None)
        if watch is not None and watch.new_since_last(alerts):
            try:
                tabs = self.query_one("#status-tabs", TabbedContent)
                if tabs.active != "status-tab-crew":
                    tabs.active = "status-tab-crew"
            except Exception:
                pass
        for i in range(_MAX_ROWS):
            try:
                lbl = self.query_one(f"#alert-{i}", Label)
            except Exception:
                continue
            if i < len(alerts):
                a       = alerts[i]
                opacity = self.core.plugin_call("alerts", "opacity_for", a) or 1.0
                text    = f"{a.get('emoji', '')}  {a.get('text', '')}"
                lbl.update(f"{text}" if opacity < 0.7 else text)
            else:
                lbl.update("")


# ── Radio tab ─────────────────────────────────────────────────────────────────

class RadioPanel(Vertical):
    """Station list, readout and transport controls.

    Polls the shared player twice a second rather than being called back from
    its threads: the player's worker and audio threads never touch a widget,
    so there is nothing here to marshal onto the app thread.
    """

    POLL_SECONDS = 0.5

    def __init__(self, core, **kw) -> None:
        super().__init__(**kw)
        self._ctl = RadioController(core)
        self._shown_options: list[tuple[str, str]] = []
        self._shown_problems: list[str] = []

    @staticmethod
    def _as_text(options: list[tuple[str, str]]) -> list[tuple[Text, str]]:
        # Station names are the user's own strings; "[Classic] Rock FM" would
        # otherwise be read as markup and lose its first word.
        return [(Text(label), sid) for label, sid in options]

    def compose(self) -> ComposeResult:
        options = self._ctl.options()
        self._shown_options = options
        # Only pass a value that is one of the options.  Textual validates it
        # at mount, and an unknown one takes the whole app down (see the
        # 20260922 CHANGELOG entry on the deposit window).
        with Horizontal(id="radio-select-row"):
            if self._ctl.selected in (sid for _, sid in options):
                yield Select(self._as_text(options), value=self._ctl.selected,
                             id="radio-select", prompt="Choose a station")
            else:
                yield Select(self._as_text(options), id="radio-select",
                             prompt="Choose a station")
            yield Static("+", id="radio-add-btn", classes="footer-lbl radio-edit-btn")
            yield Static("✎", id="radio-edit-btn", classes="footer-lbl radio-edit-btn")
            yield Static("−", id="radio-del-btn", classes="footer-lbl radio-edit-btn")
        with VerticalScroll(id="radio-body"):
            yield KVRow("Status",  id="radio-status")
            yield KVRow("On air",  id="radio-onair")
            yield KVRow("Now",     id="radio-now")
            yield KVRow("Volume",  id="radio-volume")
            yield Vertical(id="radio-problems")
        with Horizontal(id="radio-footer"):
            yield Static("▶ Play", id="radio-play-btn",  classes="footer-lbl")
            yield Static("Vol −",  id="radio-down-btn",  classes="footer-lbl")
            yield Static("Vol +",  id="radio-up-btn",    classes="footer-lbl")
            yield Static("Mute",   id="radio-mute-btn",  classes="footer-lbl")

    def on_mount(self) -> None:
        self._redraw()
        self.set_interval(self.POLL_SECONDS, self._poll)

    def _poll(self) -> None:
        if self._ctl.reload():
            self._sync_options()
        self._redraw()

    def _sync_options(self) -> None:
        options = self._ctl.options()
        try:
            sel = self.query_one("#radio-select", Select)
        except Exception:
            return
        if options != self._shown_options:
            self._shown_options = options
            sel.set_options(self._as_text(options))
        if self._ctl.selected and sel.value != self._ctl.selected:
            sel.value = self._ctl.selected

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "radio-select":
            return
        event.stop()
        value = event.value
        if isinstance(value, str):
            self._ctl.select(value)
            self._redraw()

    def on_click(self, event) -> None:
        wid = str(getattr(event.widget, "id", ""))
        if wid == "radio-add-btn":
            event.stop()
            self._open_add()
            return
        if wid == "radio-edit-btn":
            event.stop()
            self._open_edit()
            return
        if wid == "radio-del-btn":
            event.stop()
            self._open_delete()
            return
        action = {
            "radio-play-btn": self._ctl.toggle_play,
            "radio-down-btn": self._ctl.volume_down,
            "radio-up-btn":   self._ctl.volume_up,
            "radio-mute-btn": self._ctl.toggle_mute,
        }.get(wid)
        if action is None:
            return
        event.stop()
        action()
        self._redraw()

    # ── Adding, editing and deleting ─────────────────────────────────────────

    def _open_add(self) -> None:
        from tui.station_screen import AddStationScreen

        def _done(station_id) -> None:
            if station_id:
                self._sync_options()
                self._redraw()
        self.app.push_screen(AddStationScreen(self._ctl), _done)

    def _open_edit(self) -> None:
        from tui.station_screen import EditStationScreen
        sid = self._ctl.selected
        if not sid:
            return
        try:
            screen = EditStationScreen(self._ctl, sid)
        except RadioError as exc:
            self._notify_error(str(exc))
            return

        def _done(station_id) -> None:
            if station_id:
                self._sync_options()
                self._redraw()
        self.app.push_screen(screen, _done)

    def _open_delete(self) -> None:
        from tui.confirm_modal import ConfirmModal
        sid = self._ctl.selected
        if not sid:
            return
        try:
            title, message = self._ctl.delete_prompt(sid)
        except RadioError as exc:
            self._notify_error(str(exc))
            return

        def _done(ok) -> None:
            if not ok:
                return
            try:
                self._ctl.delete_station(sid)
            except RadioError as exc:
                self._notify_error(str(exc))
            self._sync_options()
            self._redraw()
        self.app.push_screen(ConfirmModal(Text(title), Text(message)), _done)

    def _notify_error(self, message: str) -> None:
        # markup=False keeps "[Radio]" in the message; older Textual has no
        # such argument and does not parse notifications as markup anyway.
        try:
            self.notify(message, severity="error", markup=False)
        except TypeError:
            self.notify(message, severity="error")

    def _redraw(self) -> None:
        # Everything drawn here is plain text, never markup: song titles come
        # from the station and problems quote "[Radio]", both of which
        # Textual would otherwise parse as tags — dropping the text, or
        # raising on something like "[/b]".
        v = self._ctl.view()
        tone = f"val {v['status_tone']}".strip()
        for wid, text, cls in (
            ("radio-status", v["status"], tone),
            ("radio-onair",  v["on_air"], "val"),
            ("radio-now",    v["now"],    "val"),
            ("radio-volume", v["volume"], "val"),
        ):
            try:
                self.query_one(f"#{wid}", KVRow).set_value(Text(text), cls)
            except Exception:
                pass
        try:
            self.query_one("#radio-del-btn", Static).set_class(
                not v["can_delete"], "dim")
            self.query_one("#radio-edit-btn", Static).set_class(
                not v["can_edit"], "dim")
        except Exception:
            pass
        for wid, text in (("radio-play-btn", v["play_label"]),
                          ("radio-mute-btn", v["mute_label"])):
            try:
                self.query_one(f"#{wid}", Static).update(text)
            except Exception:
                pass
        if v["problems"] != self._shown_problems:
            self._shown_problems = v["problems"]
            try:
                box = self.query_one("#radio-problems", Vertical)
            except Exception:
                return
            box.remove_children()
            if v["problems"]:
                box.mount(SecHdr("Config"))
                box.mount_all(Label(Text(p), classes="dim") for p in v["problems"])
