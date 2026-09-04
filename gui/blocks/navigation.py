"""
gui/blocks/navigation.py — Navigation block (Qt).

Three tabs in fixed order: FSD, Neutron, Carrier.

FSD + Neutron tabs each present a form (From, To, Range; plus Efficiency for
Neutron) followed by a "Plot" button.  Plotting is asynchronous — the Spansh
API call runs on a background thread and posts the result back to the GUI
thread through a Qt signal, which is the Qt equivalent of the Textual block's
call_from_thread.  Touching widgets from the worker thread would be a crash;
the signal hop is what makes it safe.

Carrier tab is a static read of state.assets_carrier (Fleet section) and
state.pilot_squadron_name (Squadron section, with the documented limitation
that no anonymous API surfaces squadron carrier jump data).
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from gui.block_base import GuiBlock, RowScroll, _fmt_credits


def _fmt_ly(d) -> str:
    try:
        v = float(d)
    except (TypeError, ValueError):
        return "—"
    if v >= 1000:
        return f"{v:,.0f} ly"
    return f"{v:.2f} ly"


class NavigationBlock(GuiBlock):
    BLOCK_TITLE = "NAVIGATION"

    #: Emitted from the plotting worker thread: (prefix, result, is_neutron).
    plot_done = Signal(str, object, bool)

    def _build_body(self, layout) -> None:
        self.plot_done.connect(self._on_plot_done)
        self._inputs: dict[str, QLineEdit] = {}
        self._status: dict[str, object] = {}
        self._results: dict[str, RowScroll] = {}

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.addTab(self._make_plot_tab("fsd", neutron=False), "FSD")
        self._tabs.addTab(self._make_plot_tab("neutron", neutron=True), "Neutron")

        # ── Carrier tab ──────────────────────────────────────────────────────
        # Carrier ROUTING is deferred with no target release — the Spansh
        # fleet-carrier API integration doesn't reliably return results from
        # its accepted POSTs.  This tab continues to surface the live carrier
        # *status* (balance / fuel / cargo) which is genuinely useful; the
        # route-plotting form will be added if and when the API issue is
        # resolved.
        self._carrier_scroll = RowScroll()
        self._tabs.addTab(self._carrier_scroll, "Carrier ⚠")

        layout.addWidget(self._tabs, 1)

    def _make_plot_tab(self, prefix: str, neutron: bool) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        def _inp(key: str, placeholder: str, value: str = "") -> QLineEdit:
            e = QLineEdit()
            e.setPlaceholderText(placeholder)
            if value:
                e.setText(value)
            self._inputs[f"{prefix}-{key}"] = e
            lay.addWidget(e)
            return e

        _inp("from", "From (current system)")
        _inp("to", "To (e.g. Beagle Point)" if neutron else "To (e.g. Colonia)")
        _inp("range", "Laden range, ly")
        if neutron:
            _inp("eff", "Efficiency 1–100", "60")

        btn = QPushButton("Plot Neutron" if neutron else "Plot FSD")
        btn.setProperty("role", "primary")
        btn.clicked.connect(lambda: self._launch_plot(is_neutron=neutron))
        lay.addWidget(btn)

        status = self.text("", "dim")
        self._status[prefix] = status
        lay.addWidget(status)

        results = RowScroll()
        self._results[prefix] = results
        lay.addWidget(results, 1)
        return page

    # ── Plotting ──────────────────────────────────────────────────────────────

    def _launch_plot(self, is_neutron: bool) -> None:
        """Validate inputs, then dispatch the Spansh call on a background
        thread so the GUI stays responsive while it polls."""
        prefix = "neutron" if is_neutron else "fsd"

        def _v(node_id: str) -> str:
            e = self._inputs.get(f"{prefix}-{node_id}")
            return e.text().strip() if e is not None else ""

        src = _v("from")
        if not src:
            cur = (getattr(self.core.state, "pilot_system", None) or "").strip()
            if cur:
                self._inputs[f"{prefix}-from"].setText(cur)
                src = cur
        dst = _v("to")
        range_str = _v("range")
        status = self._status[prefix]

        if not src or not dst or not range_str:
            status.set_text("[red]Source, destination, and range required.[/red]")
            return
        try:
            rng = float(range_str)
        except ValueError:
            status.set_text("[red]Range must be a number.[/red]")
            return
        if rng <= 0 or rng > 1000:
            status.set_text("[red]Range must be 0–1000 ly.[/red]")
            return

        eff = 60
        if is_neutron:
            try:
                eff = int(_v("eff") or "60")
            except ValueError:
                status.set_text("[red]Efficiency must be an integer.[/red]")
                return
            if not 1 <= eff <= 100:
                status.set_text("[red]Efficiency must be 1–100.[/red]")
                return

        # Clear stale results so the user knows we're working.
        self._results[prefix].set_rows([])
        status.set_text("Plotting…")

        # Worker thread — Spansh's route APIs poll for completion 1–60 s.
        def _worker():
            try:
                if is_neutron:
                    result = self.core.plugin_call(
                        "spansh", "plot_neutron_route", src, dst, rng, eff,
                    )
                else:
                    result = self.core.plugin_call(
                        "spansh", "plot_fsd_route", src, dst, rng,
                    )
            except Exception as exc:
                result = {"_error": f"{type(exc).__name__}: {exc}"}
            self.plot_done.emit(prefix, result, is_neutron)

        threading.Thread(target=_worker, daemon=True,
                         name=f"nav-plot-{prefix}").start()

    def _on_plot_done(self, prefix: str, result, is_neutron: bool) -> None:
        status  = self._status.get(prefix)
        results = self._results.get(prefix)
        if status is None or results is None:
            return
        results.set_rows([])

        if not result:
            status.set_text("[yellow]No route returned (timeout or error).[/yellow]")
            return
        if isinstance(result, dict) and result.get("_error"):
            status.set_text(f"[red]Plot failed: {result['_error']}[/red]")
            return

        jumps = result.get("system_jumps") or result.get("jumps") or []
        if not jumps:
            status.set_text("[yellow]No jumps in response.[/yellow]")
            return

        total_jumps    = result.get("total_jumps", len(jumps))
        total_distance = (result.get("distance")
                          or result.get("source_distance")
                          or 0)
        eff_jumps      = result.get("efficient_jumps", total_jumps)
        if is_neutron:
            status.set_text(
                f"[green]{total_jumps} jumps · {total_distance:,.0f} ly · "
                f"{eff_jumps} neutron-boosted[/green]"
            )
        else:
            status.set_text(
                f"[green]{total_jumps} jumps · {total_distance:,.0f} ly[/green]"
            )

        rows = [self.hdr("Waypoints")]
        for i, jump in enumerate(jumps, start=1):
            name = jump.get("system") or jump.get("name") or "—"
            dist = jump.get("distance_jumped") or jump.get("distance") or 0
            note = ""
            if jump.get("neutron_star"):
                note = " [magenta]★[/magenta]"
            elif jump.get("must_refuel"):
                note = " [yellow]⛽[/yellow]"
            elif jump.get("is_supercharged"):
                note = " [cyan]boost[/cyan]"
            rows.append(self.kv(f"{i}. {name}", f"{_fmt_ly(dist)}{note}"))
        results.set_rows(rows)

    # ── Refresh (state-driven content) ────────────────────────────────────────

    def refresh_data(self) -> None:
        # Pre-fill "From" entries with the current system if empty so the
        # user doesn't have to retype it after relocating.
        cur = (getattr(self.core.state, "pilot_system", None) or "").strip()
        if cur:
            for prefix in ("fsd", "neutron"):
                inp = self._inputs.get(f"{prefix}-from")
                if inp is not None and not inp.text().strip():
                    inp.setText(cur)

        # Carrier tab is fully state-driven.
        self._refresh_carrier()

    def _refresh_carrier(self) -> None:
        rows: list = []

        # Carrier routing is deferred (no target release) — keep this notice
        # visible at the top of the tab so it's obvious why no plot form.
        rows.append(self.text(
            "[yellow]⚠ Carrier routing is UNFINISHED — disabled for this "
            "release. Status display below remains live.[/yellow]"
        ))

        rows.append(self.hdr("Fleet carrier"))
        carrier = getattr(self.core.state, "assets_carrier", None)
        if not carrier:
            rows.append(self.text("No carrier on file.", "dim"))
        else:
            rows.append(self.kv("Name",       str(carrier.get("name", "—"))))
            rows.append(self.kv("Callsign",   str(carrier.get("callsign", "—"))))
            rows.append(self.kv("System",     str(carrier.get("system", "—"))))
            rows.append(self.kv("Fuel",       f"{carrier.get('fuel', 0)} t"))
            rows.append(self.kv("Cargo",
                f"{carrier.get('cargo_used', 0)} / "
                f"{carrier.get('cargo_total', 0)} t"))
            rows.append(self.kv("Balance",   _fmt_credits(carrier.get("balance"))))
            rows.append(self.kv("Available", _fmt_credits(carrier.get("available"))))
            rows.append(self.kv("Docking",   str(carrier.get("docking", "—"))))

        rows.append(self.hdr("Squadron carrier"))
        sq_name = getattr(self.core.state, "pilot_squadron_name", "") or ""
        if sq_name:
            rows.append(self.kv("Squadron", sq_name))
            rows.append(self.text(
                "Squadron carrier jump-status data is not available "
                "from the journal or any anonymous API.  This section will "
                "populate once a squadron-data integration ships.",
                "dim",
            ))
        else:
            rows.append(self.text("No squadron on file.", "dim"))

        self._carrier_scroll.set_rows(rows)
