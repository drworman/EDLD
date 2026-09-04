"""
gui/blocks/navigation.py — Navigation block (Qt).

Three tabs in fixed order: FSD, Neutron, Carrier.

FSD + Neutron tabs each present a form (From, To, Range; plus Efficiency for
Neutron) followed by a "Plot" button.  Plotting is asynchronous — the Spansh
API call runs on a background thread and posts the result back to the GUI
thread through a Qt signal, which is the Qt equivalent of the Textual block's
call_from_thread.  Touching widgets from the worker thread would be a crash;
the signal hop is what makes it safe.

Carrier tab plots fleet-carrier routes through Spansh, with fuel planning.
Full carrier detail lives in the Assets block's Carrier tab.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from gui.block_base import GuiBlock, RowScroll, _fmt_credits
from core.ui_helpers import carrier_route_rows, carrier_route_summary


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
    #: Emitted from the carrier worker thread: (result,).  Separate signal
    #: because the carrier result has its own shape and renderer.
    carrier_plot_done = Signal(object)

    def _build_body(self, layout) -> None:
        self.plot_done.connect(self._on_plot_done)
        self.carrier_plot_done.connect(self._on_carrier_plot_done)
        self._inputs: dict[str, QLineEdit] = {}
        self._status: dict[str, object] = {}
        self._results: dict[str, RowScroll] = {}

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.addTab(self._make_plot_tab("fsd", neutron=False), "FSD")
        self._tabs.addTab(self._make_plot_tab("neutron", neutron=True), "Neutron")
        self._tabs.addTab(self._make_carrier_tab(), "Carrier")

        layout.addWidget(self._tabs, 1)

    def _make_carrier_tab(self) -> QWidget:
        """Fleet-carrier plot form.

        Same shape as the ship tabs, with carrier-specific fields.  Defaults
        are filled from the live carrier on refresh; full carrier detail
        lives in the Assets block's Carrier tab.
        """
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        self._carrier_info = self.text("", "dim")
        lay.addWidget(self._carrier_info)

        def _inp(key: str, placeholder: str) -> None:
            e = QLineEdit()
            e.setPlaceholderText(placeholder)
            self._inputs[f"carrier-{key}"] = e
            lay.addWidget(e)

        _inp("from", "From (carrier's system)")
        _inp("to", "To (e.g. Colonia)")
        _inp("used", "Cargo used, t")
        _inp("fuel", "Tritium in tank, t")

        btn = QPushButton("Plot Carrier")
        btn.setProperty("role", "primary")
        btn.clicked.connect(self._launch_carrier_plot)
        lay.addWidget(btn)

        status = self.text("", "dim")
        self._status["carrier"] = status
        lay.addWidget(status)

        results = RowScroll()
        self._results["carrier"] = results
        lay.addWidget(results, 1)
        return page

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

    # ── Carrier plotting ──────────────────────────────────────────────────────

    def _launch_carrier_plot(self) -> None:
        """Validate the carrier form, then plot on a background thread.

        Carrier jobs are far heavier server-side than ship routes — a
        galaxy-crossing route is 40+ jumps — so this can legitimately take
        a couple of minutes.
        """
        def _v(key: str) -> str:
            e = self._inputs.get(f"carrier-{key}")
            return e.text().strip() if e is not None else ""

        status = self._status["carrier"]
        carrier = getattr(self.core.state, "assets_carrier", None) or {}

        src = _v("from") or str(carrier.get("system") or "").strip()
        dst = _v("to")
        if not src or not dst:
            status.set_text("[red]Source and destination required.[/red]")
            return

        def _int(key: str, fallback: int) -> int | None:
            raw = _v(key)
            if not raw:
                return fallback
            try:
                return max(int(float(raw)), 0)
            except ValueError:
                return None

        used = _int("used", int(carrier.get("cargo_used") or 0))
        fuel = _int("fuel", int(carrier.get("fuel") or 0))
        if used is None or fuel is None:
            status.set_text("[red]Cargo and tritium must be numbers.[/red]")
            return

        total_capacity = int(carrier.get("cargo_total") or 25000) or 25000

        self._results["carrier"].set_rows([])
        status.set_text("Plotting carrier route… (can take a minute or two)")

        def _worker():
            try:
                result = self.core.plugin_call(
                    "spansh", "plot_carrier_route", src, dst, used,
                    total_capacity, fuel,
                )
            except Exception as exc:
                result = {"_error": f"{type(exc).__name__}: {exc}"}
            self.carrier_plot_done.emit(result)

        threading.Thread(target=_worker, daemon=True,
                         name="nav-plot-carrier").start()

    def _on_carrier_plot_done(self, result) -> None:
        status  = self._status.get("carrier")
        results = self._results.get("carrier")
        if status is None or results is None:
            return
        results.set_rows([])

        if not result:
            status.set_text("[yellow]No route returned (timeout or error).[/yellow]")
            return
        if isinstance(result, dict) and result.get("_error"):
            status.set_text(f"[red]Plot failed: {result['_error']}[/red]")
            return
        if not (result.get("jumps") or []):
            status.set_text("[yellow]No jumps in response.[/yellow]")
            return

        s = carrier_route_summary(result)
        status.set_text(
            f"[green]{s['jumps']} jumps · {s['distance_ly']:,.0f} ly · "
            f"{s['fuel_total']:,} t tritium[/green]"
        )

        rows = [self.hdr("Route")]
        if s["restocks"]:
            rows.append(self.text(
                f"[yellow]{s['restocks']} restock stop(s)[/yellow] · "
                f"{s['tritium_sources']} systems with tritium available",
                "dim",
            ))
        for label, value in carrier_route_rows(result):
            rows.append(self.kv(label, value))
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
        """Keep the carrier form's defaults in step with the live carrier.

        Only empty fields are filled, so anything typed by hand survives a
        refresh.  Full carrier detail lives in the Assets block's Carrier tab.
        """
        carrier = getattr(self.core.state, "assets_carrier", None)
        if not carrier:
            self._carrier_info.set_text(
                "[dim]No carrier on file — enter values by hand.[/dim]")
            return

        name = str(carrier.get("name") or "Carrier")
        sysm = str(carrier.get("system") or "—")
        fuel = carrier.get("fuel") or 0
        used = carrier.get("cargo_used") or 0
        cap  = carrier.get("cargo_total") or 25000
        self._carrier_info.set_text(
            f"{name} · {sysm} · {fuel} t tritium · {used}/{cap} t")

        for key, value in (
            ("from", sysm),
            ("used", str(int(used))),
            ("fuel", str(int(fuel))),
        ):
            inp = self._inputs.get(f"carrier-{key}")
            if inp is not None and not inp.text().strip() and value and value != "—":
                inp.setText(value)
