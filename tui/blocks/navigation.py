"""
tui/blocks/navigation.py — Navigation block (Textual).

Three tabs in fixed order: FSD, Neutron, Carrier.

FSD + Neutron tabs each present a form (From, To, Range; plus Efficiency
for Neutron) followed by a "Plot" button.  Plotting is asynchronous —
the Spansh API call runs on a background thread and posts the result
back via Textual's call_from_thread when complete.

Carrier tab plots fleet-carrier routes through Spansh, with fuel planning.
Full carrier detail lives in the Assets block's Carrier tab.


"""
from __future__ import annotations

import threading
import time

from textual.app        import ComposeResult
from textual.widgets    import Label, Static, TabbedContent, TabPane, Input, Button
from textual.containers import VerticalScroll, Horizontal

from tui.block_base     import TuiBlock, KVRow, SecHdr, _fmt_credits
from core.ui_helpers    import carrier_route_rows, carrier_route_summary


#: How long a footer click result stays on screen before the standing route
#: status reclaims the line.
_FOOTER_MSG_SECONDS = 6.0


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

    def __init__(self, core, **kw) -> None:
        super().__init__(core, **kw)
        self._footer_msg = ""
        self._footer_msg_at = 0.0

    def compose(self) -> ComposeResult:
        yield Label(self.BLOCK_TITLE, classes="block-title")
        yield from self._compose_body()
        # Footer strip, same one-row budget the Cargo block uses.
        with Horizontal(id="nav-footer"):
            yield Static(">> Follow: off", id="nav-follow-btn",
                         classes="footer-lbl")
            yield Static(">> Copy Next", id="nav-copy-btn",
                         classes="footer-lbl")
            yield Static(">> Clear Route", id="nav-clear-btn",
                         classes="footer-lbl")
            yield Label("", id="nav-follow-lbl", classes="dim")

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
            # Fleet-carrier routing plots through Spansh's /api/fleetcarrier
            # /route endpoint.  The form defaults are filled from the live
            # carrier state on refresh so a plot is usually one button press.
            with TabPane("Carrier", id="nav-tab-carrier"):
                with VerticalScroll(id="nav-carrier-scroll"):
                    yield Label("", id="nav-carrier-info", classes="dim")
                    yield Input(placeholder="From (carrier's system)",
                                id="nav-carrier-from")
                    yield Input(placeholder="To (e.g. Colonia)",
                                id="nav-carrier-to")
                    yield Input(placeholder="Cargo used, t",
                                id="nav-carrier-used")
                    yield Input(placeholder="Tritium in tank, t",
                                id="nav-carrier-fuel")
                    yield Button("Plot Carrier",
                                 id="nav-carrier-plot", variant="primary")
                    yield Label("", id="nav-carrier-status", classes="dim")
                    yield VerticalScroll(id="nav-carrier-results")

    # ── Button dispatch ───────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "nav-fsd-plot":
            self._launch_plot(is_neutron=False)
        elif btn_id == "nav-neutron-plot":
            self._launch_plot(is_neutron=True)
        elif btn_id == "nav-carrier-plot":
            self._launch_carrier_plot()

    # ── Carrier plotting ──────────────────────────────────────────────────────

    def _launch_carrier_plot(self) -> None:
        """Validate the carrier form, then plot on a background thread.

        Carrier jobs are far heavier server-side than ship routes — a
        galaxy-crossing route is 40+ jumps — so this can legitimately take
        a couple of minutes.
        """
        def _v(node_id: str) -> str:
            try:
                return self.query_one(f"#nav-carrier-{node_id}", Input).value.strip()
            except Exception:
                return ""

        status = self.query_one("#nav-carrier-status", Label)
        carrier = getattr(self.core.state, "assets_carrier", None) or {}

        src = _v("from") or str(carrier.get("system") or "").strip()
        dst = _v("to")
        if not src or not dst:
            status.update("[red]Source and destination required.[/red]")
            return

        def _int(node_id: str, fallback: int) -> int | None:
            raw = _v(node_id)
            if not raw:
                return fallback
            try:
                return max(int(float(raw)), 0)
            except ValueError:
                return None

        used = _int("used", int(carrier.get("cargo_used") or 0))
        fuel = _int("fuel", int(carrier.get("fuel") or 0))
        if used is None or fuel is None:
            status.update("[red]Cargo and tritium must be numbers.[/red]")
            return

        total_capacity = int(carrier.get("cargo_total") or 25000) or 25000

        try:
            self.query_one("#nav-carrier-results", VerticalScroll).remove_children()
        except Exception:
            pass
        status.update("Plotting carrier route… (can take a minute or two)")

        def _worker():
            try:
                result = self.core.plugin_call(
                    "spansh", "plot_carrier_route", src, dst, used,
                    total_capacity, fuel,
                )
            except Exception as exc:
                result = {"_error": f"{type(exc).__name__}: {exc}"}
            self.app.call_from_thread(self._on_carrier_plot_done, result)

        threading.Thread(target=_worker, daemon=True,
                         name="nav-plot-carrier").start()

    def _on_carrier_plot_done(self, result) -> None:
        try:
            status  = self.query_one("#nav-carrier-status", Label)
            results = self.query_one("#nav-carrier-results", VerticalScroll)
        except Exception:
            return
        results.remove_children()

        if not result:
            status.update("[yellow]No route returned (timeout or error).[/yellow]")
            return
        if isinstance(result, dict) and result.get("_error"):
            status.update(f"[red]Plot failed: {result['_error']}[/red]")
            return
        if not (result.get("jumps") or []):
            status.update("[yellow]No jumps in response.[/yellow]")
            return

        s = carrier_route_summary(result)
        status.update(
            f"[green]{s['jumps']} jumps · {s['distance_ly']:,.0f} ly · "
            f"{s['fuel_total']:,} t tritium[/green]"
        )


        # Persist as the followed route so the footer's Copy Next and the
        # arrival auto-copy work off what was just plotted.
        nav = self.core._plugins.get("navigation")
        if nav is not None:
            try:
                nav.store_route(result, "carrier")
            except Exception as exc:
                from core import debug as _dbg
                _dbg.info(f"  [Nav] could not store plotted route: {exc}")

        rows = [SecHdr("Route")]
        if s["restocks"]:
            rows.append(Label(
                f"[yellow]{s['restocks']} restock stop(s)[/yellow] · "
                f"{s['tritium_sources']} systems with tritium available",
                classes="dim",
            ))
        for label, value in carrier_route_rows(result):
            rows.append(KVRow(label, value))
        results.mount(*rows)

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
        status.update("Plotting…")

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
            # call_from_thread lives on App, not on Widget/MessagePump, so this
            # must go through self.app.  Calling it on the block raised
            # AttributeError on the worker's last line — after the route had
            # already been fetched — killing the daemon thread silently and
            # leaving the status label stuck on "Plotting…" forever.
            self.app.call_from_thread(self._on_plot_done, prefix, result, is_neutron)

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


        # Persist as the followed route so the footer's Copy Next and the
        # arrival auto-copy work off what was just plotted.
        nav = self.core._plugins.get("navigation")
        if nav is not None:
            try:
                nav.store_route(result, "neutron" if is_neutron else "fsd")
            except Exception as exc:
                from core import debug as _dbg
                _dbg.info(f"  [Nav] could not store plotted route: {exc}")

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

    # ── Route-follower footer ─────────────────────────────────────────────────

    def _nav_plugin(self):
        return self.core._plugins.get("navigation")

    def on_click(self, event) -> None:
        btn = str(getattr(event.widget, "id", "") or "")
        if btn not in ("nav-follow-btn", "nav-copy-btn", "nav-clear-btn"):
            return
        event.stop()

        nav = self._nav_plugin()
        if nav is None:
            self._set_follow_msg("[red]Navigation component not loaded.[/red]")
            return

        if btn == "nav-follow-btn":
            on = nav.toggle_follow()
            self._set_follow_msg(
                "Following route — next system copies on arrival."
                if on else "Follow off."
            )
        elif btn == "nav-copy-btn":
            ok, msg = nav.copy_next()
            # Over SSH the clipboard lives on the machine running the
            # terminal, not on this host, so the OS backends above cannot
            # reach it.  Textual's copy_to_clipboard emits OSC 52, which the
            # terminal emulator itself honours — the one mechanism that works
            # remotely.  Belt and braces: both are attempted, and a duplicate
            # copy of the same string is harmless.
            system = getattr(self.core.state, "nav_follow_next", "")
            if system:
                try:
                    self.app.copy_to_clipboard(system)
                    if not ok:
                        ok, msg = True, f"Copied {system} (terminal)"
                except Exception:
                    pass
            self._set_follow_msg(msg if ok else f"[yellow]{msg}[/yellow]")
        else:
            self._set_follow_msg(nav.clear_route())

        self._refresh_footer()

    def _set_follow_msg(self, text: str) -> None:
        """Show a transient result message; it decays back to route status."""
        self._footer_msg = text
        self._footer_msg_at = time.monotonic()
        try:
            self.query_one("#nav-follow-lbl", Label).update(text)
        except Exception:
            pass

    def _refresh_footer(self) -> None:
        nav = self._nav_plugin()
        try:
            toggle = self.query_one("#nav-follow-btn", Static)
            label = self.query_one("#nav-follow-lbl", Label)
        except Exception:
            return

        if nav is None:
            toggle.update(">> Follow: n/a")
            label.update("[dim]Navigation component not loaded.[/dim]")
            return

        s = self.core.state
        on = bool(getattr(s, "nav_follow_enabled", False))
        toggle.update(f">> Follow: {'ON' if on else 'off'}")

        # A click result stays visible briefly, then the standing route
        # status takes the line back.
        if self._footer_msg and (time.monotonic() - self._footer_msg_at) < _FOOTER_MSG_SECONDS:
            return
        self._footer_msg = ""
        label.update(getattr(s, "nav_follow_status", "") or "No route")

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
        self._refresh_footer()

    def _refresh_carrier(self) -> None:
        """Keep the carrier form's defaults in step with the live carrier.

        Only empty fields are filled, so anything typed by hand survives a
        refresh.  Full carrier detail lives in the Assets block's Carrier
        tab; this is just enough context to plot from.
        """
        carrier = getattr(self.core.state, "assets_carrier", None)

        try:
            info = self.query_one("#nav-carrier-info", Label)
        except Exception:
            return

        if not carrier:
            info.update("[dim]No carrier on file — enter values by hand.[/dim]")
            return

        name = str(carrier.get("name") or "Carrier")
        sysm = str(carrier.get("system") or "—")
        fuel = carrier.get("fuel") or 0
        used = carrier.get("cargo_used") or 0
        cap  = carrier.get("cargo_total") or 25000
        info.update(f"{name} · {sysm} · {fuel} t tritium · {used}/{cap} t")

        for node_id, value in (
            ("from", sysm),
            ("used", str(int(used))),
            ("fuel", str(int(fuel))),
        ):
            try:
                inp = self.query_one(f"#nav-carrier-{node_id}", Input)
                if not (inp.value or "").strip() and value and value != "—":
                    inp.value = value
            except Exception:
                pass
