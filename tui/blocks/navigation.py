"""
tui/blocks/navigation.py — Navigation block (Textual).

Three tabs in fixed order: FSD, Neutron, Carrier.

FSD + Neutron tabs each present a form (From, To, Range; plus Efficiency
for Neutron) followed by a "Plot" button.  Plotting is asynchronous —
the Spansh API call runs on a background thread and posts the result
back via Textual's call_from_thread when complete.

Carrier tab is a static read of state.assets_carrier (Fleet section)
and state.pilot_squadron_name (Squadron section, with the
documented limitation that no anonymous API surfaces squadron
carrier jump data).
"""
from __future__ import annotations

import threading

from textual.app        import ComposeResult
from textual.widgets    import Label, TabbedContent, TabPane, Input, Button
from textual.containers import VerticalScroll, Horizontal

from tui.block_base     import TuiBlock, KVRow, SecHdr, _fmt_credits


def _fmt_ly(d) -> str:
    try:
        v = float(d)
    except (TypeError, ValueError):
        return "—"
    if v >= 1000:
        return f"{v:,.0f} ly"
    return f"{v:.2f} ly"


class NavigationBlock(TuiBlock):
    BLOCK_TITLE = "NAVIGATION"

    def _compose_body(self) -> ComposeResult:
        with TabbedContent(id="nav-tabs"):
            # ── FSD tab ──────────────────────────────────────────────────────
            with TabPane("FSD", id="nav-tab-fsd"):
                with VerticalScroll(id="nav-fsd-scroll"):
                    yield Input(placeholder="From (current system)",
                                id="nav-fsd-from")
                    yield Input(placeholder="To (e.g. Colonia)",
                                id="nav-fsd-to")
                    yield Input(placeholder="Laden range, ly",
                                id="nav-fsd-range")
                    yield Button("Plot FSD",
                                 id="nav-fsd-plot", variant="primary")
                    yield Label("", id="nav-fsd-status", classes="dim")
                    yield VerticalScroll(id="nav-fsd-results")

            # ── Neutron tab ──────────────────────────────────────────────────
            with TabPane("Neutron", id="nav-tab-neutron"):
                with VerticalScroll(id="nav-neutron-scroll"):
                    yield Input(placeholder="From (current system)",
                                id="nav-neutron-from")
                    yield Input(placeholder="To (e.g. Beagle Point)",
                                id="nav-neutron-to")
                    yield Input(placeholder="Laden range, ly",
                                id="nav-neutron-range")
                    yield Input(value="60", placeholder="Efficiency 1–100",
                                id="nav-neutron-eff")
                    yield Button("Plot Neutron",
                                 id="nav-neutron-plot", variant="primary")
                    yield Label("", id="nav-neutron-status", classes="dim")
                    yield VerticalScroll(id="nav-neutron-results")

            # ── Carrier tab ──────────────────────────────────────────────────
            # Carrier ROUTING is unfinished and won't ship in this release —
            # the Spansh fleet-carrier API integration doesn't return
            # results from its accepted POSTs (see release notes for
            # 20260515).  This tab continues to surface the live carrier
            # *status* (balance / fuel / cargo) which is genuinely useful;
            # the route-plotting form will be added once the API issue
            # is resolved.
            with TabPane("Carrier⚠", id="nav-tab-carrier"):
                yield VerticalScroll(id="nav-carrier-scroll")

    # ── Button dispatch ───────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "nav-fsd-plot":
            self._launch_plot(is_neutron=False)
        elif btn_id == "nav-neutron-plot":
            self._launch_plot(is_neutron=True)

    def _launch_plot(self, is_neutron: bool) -> None:
        """Validate inputs, then dispatch the Spansh call on a background
        thread so the TUI stays responsive while it polls."""
        prefix = "neutron" if is_neutron else "fsd"

        def _v(node_id: str) -> str:
            try:
                return self.query_one(f"#nav-{prefix}-{node_id}", Input).value.strip()
            except Exception:
                return ""

        src = _v("from")
        if not src:
            cur = (getattr(self.core.state, "pilot_system", None) or "").strip()
            if cur:
                self.query_one(f"#nav-{prefix}-from", Input).value = cur
                src = cur
        dst = _v("to")
        range_str = _v("range")
        status = self.query_one(f"#nav-{prefix}-status", Label)

        if not src or not dst or not range_str:
            status.update("[red]Source, destination, and range required.[/red]")
            return
        try:
            rng = float(range_str)
        except ValueError:
            status.update("[red]Range must be a number.[/red]")
            return
        if rng <= 0 or rng > 1000:
            status.update("[red]Range must be 0–1000 ly.[/red]")
            return

        eff = 60
        if is_neutron:
            try:
                eff = int(_v("eff") or "60")
            except ValueError:
                status.update("[red]Efficiency must be an integer.[/red]")
                return
            if not 1 <= eff <= 100:
                status.update("[red]Efficiency must be 1–100.[/red]")
                return

        # Clear stale results so the user knows we're working.
        try:
            results = self.query_one(f"#nav-{prefix}-results", VerticalScroll)
            results.remove_children()
        except Exception:
            results = None
        status.update("[dim]Plotting…[/dim]")

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
            self.call_from_thread(self._on_plot_done, prefix, result, is_neutron)

        threading.Thread(target=_worker, daemon=True,
                         name=f"nav-plot-{prefix}").start()

    def _on_plot_done(self, prefix: str, result, is_neutron: bool) -> None:
        try:
            status  = self.query_one(f"#nav-{prefix}-status", Label)
            results = self.query_one(f"#nav-{prefix}-results", VerticalScroll)
        except Exception:
            return
        results.remove_children()

        if not result:
            status.update("[yellow]No route returned (timeout or error).[/yellow]")
            return
        if isinstance(result, dict) and result.get("_error"):
            status.update(f"[red]Plot failed: {result['_error']}[/red]")
            return

        jumps = result.get("system_jumps") or result.get("jumps") or []
        if not jumps:
            status.update("[yellow]No jumps in response.[/yellow]")
            return

        total_jumps    = result.get("total_jumps", len(jumps))
        total_distance = (result.get("distance")
                          or result.get("source_distance")
                          or 0)
        eff_jumps      = result.get("efficient_jumps", total_jumps)
        if is_neutron:
            status.update(
                f"[green]{total_jumps} jumps · {total_distance:,.0f} ly · "
                f"{eff_jumps} neutron-boosted[/green]"
            )
        else:
            status.update(
                f"[green]{total_jumps} jumps · {total_distance:,.0f} ly[/green]"
            )

        rows = [SecHdr("Waypoints")]
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
            rows.append(KVRow(f"{i}. {name}", f"{_fmt_ly(dist)}{note}"))
        results.mount(*rows)

    # ── Refresh (state-driven content) ────────────────────────────────────────

    def refresh_data(self) -> None:
        # Pre-fill "From" entries with the current system if empty so the
        # user doesn't have to retype it after relocating.
        cur = (getattr(self.core.state, "pilot_system", None) or "").strip()
        if cur:
            for prefix in ("fsd", "neutron"):
                try:
                    inp = self.query_one(f"#nav-{prefix}-from", Input)
                    if not (inp.value or "").strip():
                        inp.value = cur
                except Exception:
                    pass

        # Carrier tab is fully state-driven.
        self._refresh_carrier()

    def _refresh_carrier(self) -> None:
        try:
            scroll = self.query_one("#nav-carrier-scroll", VerticalScroll)
        except Exception:
            return
        scroll.remove_children()
        rows: list = []

        # Carrier routing is unfinished for 20260515 — keep this notice
        # visible at the top of the tab so it's obvious why no plot form.
        rows.append(Label(
            "[yellow]⚠ Carrier routing is UNFINISHED — disabled for this "
            "release. Status display below remains live.[/yellow]"
        ))

        rows.append(SecHdr("Fleet carrier"))
        carrier = getattr(self.core.state, "assets_carrier", None)
        if not carrier:
            rows.append(Label("[dim]No carrier on file.[/dim]", classes="dim"))
        else:
            rows.append(KVRow("Name",       str(carrier.get("name", "—"))))
            rows.append(KVRow("Callsign",   str(carrier.get("callsign", "—"))))
            rows.append(KVRow("System",     str(carrier.get("system", "—"))))
            rows.append(KVRow("Fuel",       f"{carrier.get('fuel', 0)} t"))
            rows.append(KVRow("Cargo",
                f"{carrier.get('cargo_used', 0)} / "
                f"{carrier.get('cargo_total', 0)} t"))
            rows.append(KVRow("Balance",   _fmt_credits(carrier.get("balance"))))
            rows.append(KVRow("Available", _fmt_credits(carrier.get("available"))))
            rows.append(KVRow("Docking",   str(carrier.get("docking", "—"))))

        rows.append(SecHdr("Squadron carrier"))
        sq_name = getattr(self.core.state, "pilot_squadron_name", "") or ""
        if sq_name:
            rows.append(KVRow("Squadron", sq_name))
            rows.append(Label(
                "[dim]Squadron carrier jump-status data is not available "
                "from the journal or any anonymous API.  This section will "
                "populate once a squadron-data integration ships.[/dim]",
                classes="dim",
            ))
        else:
            rows.append(Label("[dim]No squadron on file.[/dim]", classes="dim"))

        scroll.mount(*rows)
