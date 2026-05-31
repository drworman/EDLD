"""
gui/blocks/assets.py — Commander assets block widget.

Three-tab view: Wallet | Ships | Modules.

Ships tab
---------
Lists current ship (★) followed by stored ships.  Clicking any row opens a
Gtk.Popover showing type, name, ident, system, estimated value, and hot status.

Modules tab
-----------
Lists stored modules with their system location.  Clicking a row shows a
popover with full detail: slot, system, mass, value, hot status.

Wallet tab
----------
Live credit balance with ship and module counts as quick summary stats.

Data comes from MonitorState fields set by builtins/assets/plugin.py.
"""

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
except ImportError:
    raise ImportError("PyGObject / GTK4 not found.")

from gui.block_base import BlockWidget


_TABS = [
    ("wallet",   "Wallet"),
    ("ships",    "Ships"),
    ("modules",  "Modules"),
    ("carrier",  "Fleet Carrier"),
]


def _fmt_credits(val) -> str:
    if val is None:
        return "—"
    try:
        v = int(val)
    except (TypeError, ValueError):
        return "—"
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}B cr"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M cr"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K cr"
    return f"{v} cr"



# Slot prefix → hardware category, display order
_SLOT_CATEGORIES = [
    # Hardpoints — journal slot names are Size-prefixed (LargeHardpoint1, etc.)
    ("TinyHardpoint",   "Utility Mounts"),   # must come before the bare Hardpoint match
    ("HugeHardpoint",   "Hardpoints"),
    ("LargeHardpoint",  "Hardpoints"),
    ("MediumHardpoint", "Hardpoints"),
    ("SmallHardpoint",  "Hardpoints"),
    ("Hardpoint",       "Hardpoints"),        # catch-all for bare "Hardpoint1" from CAPI
    # Core internal
    ("Armour",          "Core Internal"),
    ("PowerPlant",      "Core Internal"),
    ("MainEngines",     "Core Internal"),
    ("FrameShiftDrive", "Core Internal"),
    ("LifeSupport",     "Core Internal"),
    ("PowerDistributor","Core Internal"),
    ("Radar",           "Core Internal"),
    ("FuelTank",        "Core Internal"),
    # Optional / Military
    ("Slot",            "Optional Internal"),
    ("Military",        "Military"),
    # Optional internals with non-Slot prefix
    ("PlanetaryApproachSuite", "Optional Internal"),
    ("EngineColour",    "Livery"),
    ("WeaponColour",    "Livery"),
    ("ShipCockpit",     "Livery"),
    ("CargoHatch",      "Optional Internal"),
    # Livery
    ("PaintJob",        "Livery"),
    ("Bobble",          "Livery"),
    ("Decal",           "Livery"),
    ("ShipName",        "Livery"),
    ("ShipID",          "Livery"),
    ("VesselVoice",     "Livery"),
    ("StringLights",    "Livery"),
    ("ShipKitSpoiler",  "Livery"),
    ("ShipKitWings",    "Livery"),
    ("ShipKitTail",     "Livery"),
    ("ShipKitBumper",   "Livery"),
]
_CATEGORY_ORDER = [
    "Hardpoints", "Core Internal", "Optional Internal",
    "Military", "Utility Mounts", "Livery",
]

def _slot_to_category(slot: str) -> str:
    for prefix, cat in _SLOT_CATEGORIES:
        if slot.startswith(prefix):
            return cat
    return "Other"



from data.engineering import (
    BLUEPRINT_NAMES  as _BLUEPRINT_NAMES,
    EXP_EFFECT_NAMES as _EXP_EFFECT_NAMES,
    normalise_eng_name as _normalise_eng_name,
)
def _module_category_from_name(internal: str) -> str:
    """Return the hardware category for a module based on its internal name."""
    raw = (internal or "").lower()
    # Strip localisation wrapper first
    import re as _re
    m = _re.match(r"^\$(.+)_name;$", raw)
    if m:
        raw = m.group(1)

    if raw.startswith("hpt_"):
        # Utility mounts are tiny hardpoints
        if "chafflauncher" in raw or "electroniccountermeasure" in raw or \
           "heatsinklauncher" in raw or "plasmapointdefence" in raw or \
           "shieldbooster" in raw or "antiunknownshutdown" in raw or \
           "xenoscanner" in raw or "causticchafflauncher" in raw or \
           "datalinkscanner" in raw or "cargoScanner" in raw.lower() or \
           "killwarrantscanner" in raw or "subsurfacedisplacement" in raw:
            return "Utility Mounts"
        return "Hardpoints"
    if _re.match(r"^.+_armour_grade\d$", raw):
        return "Core Internal"
    if raw.startswith("int_") or raw.startswith("ext_"):
        raw_inner = raw[4:]
        _CORE = ("engine", "hyperdrive", "powerplant", "powerdistributor",
                 "lifesupport", "sensors", "fueltank", "radar",
                 "shieldgenerator", "armor", "armour")
        for c in _CORE:
            if raw_inner.startswith(c):
                return "Core Internal"
        return "Optional Internal"
    return "Other"

def _populate_ship_modules(mod_box: "Gtk.Box", loadout: list,
                            sep: "Gtk.Widget", hdr: "Gtk.Widget") -> None:
    """Clear and repopulate the modules sub-box in a ship popover.

    Modules are grouped by hardware category (Hardpoints, Core Internal, etc.)
    and sorted by slot within each category.  Engineering is shown inline.
    Module names are normalised from internal slot-key format.
    """
    child = mod_box.get_first_child()
    while child:
        nxt = child.get_next_sibling()
        mod_box.remove(child)
        child = nxt

    # Filter out empty slots and cosmetic-only items
    _SKIP_SLOTS = frozenset({
        "PaintJob", "Bobble", "VesselVoice", "EngineColour", "WeaponColour",
        "ShipCockpit", "CargoHatch",
    })
    _SKIP_PREFIXES = ("Decal", "ShipName", "ShipID", "ShipKitSpoiler",
                      "ShipKitWings", "ShipKitTail", "ShipKitBumper",
                      "StringLights", "Bobble")
    def _is_display_module(m):
        slot = m.get("slot", "")
        if not m.get("name_internal", ""):
            return False
        if slot in _SKIP_SLOTS:
            return False
        if any(slot.startswith(p) for p in _SKIP_PREFIXES):
            return False
        return True
    visible = [m for m in loadout if _is_display_module(m)]
    has = bool(visible)
    sep.set_visible(has)
    hdr.set_visible(has)
    if not has:
        return

    # Group by category
    from collections import defaultdict as _dd
    groups: dict = _dd(list)
    for mod in visible:
        slot = mod.get("slot", "")
        cat  = _slot_to_category(slot)
        groups[cat].append(mod)

    # Render in defined order, then any unexpected categories
    all_cats = list(_CATEGORY_ORDER) + [c for c in groups if c not in _CATEGORY_ORDER]

    for cat in all_cats:
        mods = groups.get(cat)
        if not mods:
            continue
        # Category header
        cat_lbl = Gtk.Label(label=cat.upper())
        cat_lbl.set_xalign(0.0)
        cat_lbl.add_css_class("data-key")
        cat_lbl.set_margin_top(5)
        mod_box.append(cat_lbl)

        for mod in sorted(mods, key=lambda m: m.get("slot", "")):
            # Use name_display (already normalised by normalise_module_name),
            # falling back to normalising name_internal directly here.
            name = mod.get("name_display", "") or mod.get("name_internal", "")
            if not name:
                continue

            eng  = mod.get("engineering") or {}
            bp   = eng.get("BlueprintName", "")
            lvl  = eng.get("Level")
            exp  = eng.get("ExperimentalEffect", "")

            line = name
            if bp:
                eng_s = _normalise_eng_name(bp)
                if lvl: eng_s += f" G{lvl}"
                if exp:  eng_s += f" / {_normalise_eng_name(exp)}"
                line = f"{name}  [{eng_s}]"

            lbl = Gtk.Label(label=line)
            lbl.set_xalign(0.0)
            lbl.add_css_class("data-value")
            lbl.set_margin_start(10)
            lbl.set_hexpand(True)
            lbl.set_wrap(True)
            lbl.set_size_request(280, -1)
            mod_box.append(lbl)

class AssetsBlock(BlockWidget):
    BLOCK_TITLE = "ASSETS"
    BLOCK_CSS   = "assets-block"

    def build(self, parent: Gtk.Box) -> None:
        body = self._build_section(parent)
        body.set_spacing(0)

        self._layout_stack = Gtk.Stack()
        self._layout_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self._layout_stack.set_vexpand(True)
        self._layout_stack.set_hexpand(True)
        body.append(self._layout_stack)

        self._tab_btns:   dict[str, Gtk.Button] = {}
        self._active_tab: str = "wallet"
        self._sections:   dict[str, dict] = {}

        self._build_tabbed_layout()
        self._layout_stack.set_visible_child_name("tabbed")

    # ── Tab scaffold ──────────────────────────────────────────────────────────

    def _build_tabbed_layout(self) -> None:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.set_vexpand(True)

        tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tab_bar.add_css_class("mat-tab-bar")
        page.append(tab_bar)
        page.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.NONE)
        stack.set_vexpand(True)
        stack.set_hexpand(True)
        page.append(stack)
        self._tab_stack = stack

        self._tab_labels: dict[str, Gtk.Label] = {}
        for cat, label in _TABS:
            btn = Gtk.Button()
            btn.add_css_class("mat-tab-btn")
            btn.set_hexpand(True)
            btn.set_can_focus(False)
            tab_bar.append(btn)
            lbl = Gtk.Label(label=label)
            lbl.add_css_class("mat-tab-label")
            btn.set_child(lbl)
            btn.connect("clicked", self._on_tab_click, cat)
            self._tab_btns[cat] = btn
            self._tab_labels[cat] = lbl

            if cat == "wallet":
                tab_page = self._build_wallet_tab()
            elif cat == "carrier":
                tab_page = self._build_carrier_tab()
            else:
                scroll, list_box, empty_lbl = self._make_section_scroll()
                self._sections[cat] = {
                    "list_box":  list_box,
                    "empty_lbl": empty_lbl,
                    "rows":      {},   # key -> (container, n_lbl, s_lbl)
                }
                tab_page = scroll
            stack.add_named(tab_page, cat)

        self._set_active_tab("wallet")
        self._layout_stack.add_named(page, "tabbed")

    def _build_wallet_tab(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(4)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_margin_bottom(6)
        scroll.set_child(box)

        def _row(key: str, label: str, dim: bool = False) -> Gtk.Label:
            """Append a key/value row; return the value label."""
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            k = Gtk.Label(label=label)
            k.add_css_class("data-key")
            k.set_xalign(0.0)
            k.set_hexpand(True)
            v = Gtk.Label(label="—")
            v.add_css_class("fg-dim" if dim else "data-value")
            v.set_xalign(1.0)
            row.append(k)
            row.append(v)
            box.append(row)
            self._wallet_rows[key] = v
            return v

        def _section(title: str) -> None:
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            hbox.set_margin_top(8)
            hbox.set_margin_bottom(2)
            lbl = Gtk.Label(label=title)
            lbl.add_css_class("section-header")
            lbl.set_xalign(0.0)
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            sep.set_hexpand(True)
            sep.set_valign(Gtk.Align.CENTER)
            hbox.append(lbl)
            hbox.append(sep)
            box.append(hbox)

        self._wallet_rows: dict[str, Gtk.Label] = {}

        # ── Currencies ────────────────────────────────────────────────────
        _section("Currencies")
        _row("credits", "Credits")

        # ── Fleet ─────────────────────────────────────────────────────────
        _section("Fleet")
        _row("ships_value",   "Ships")
        _row("modules_value", "Modules")

        # ── Carrier ───────────────────────────────────────────────────────
        _section("Fleet Carrier")
        _row("carrier_balance", "Balance")            # carrier account balance
        _row("carrier_hull",    "Hull")                # fixed decommission return
        _row("carrier_cargo",   "Market listings")   # value of FC cargo listed for sale
        _row("carrier_fredits", "Fredits", dim=True)   # stub — future currency

        # ── Assets At Risk ─────────────────────────────────────────────────
        _section("Assets At Risk")
        _row("risk_bounties", "Bounties")
        _row("risk_bonds",    "Combat bonds")
        _row("risk_trade",    "Trade vouchers")
        _row("risk_carto",    "Cartography (est.)")
        _row("risk_exobio",   "Exobiology (est.)")

        # ── Net Worth ─────────────────────────────────────────────────────
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        nw_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        nw_row.set_margin_top(4)
        k = Gtk.Label(label="Net Worth")
        k.add_css_class("section-header")
        k.set_xalign(0.0)
        k.set_hexpand(True)
        v = Gtk.Label(label="—")
        v.add_css_class("data-value")
        v.set_xalign(1.0)
        nw_row.append(k)
        nw_row.append(v)
        box.append(nw_row)
        self._wallet_rows["net_worth"] = v

        # Initially hide Fredits and carrier hull (no data yet)
        self._wallet_rows["carrier_hull"].get_parent().set_visible(False)
        self._wallet_rows["carrier_fredits"].get_parent().set_visible(False)

        return scroll

    def _refresh_wallet(self, state) -> None:
        """Populate all wallet tab rows from current state."""
        r = self._wallet_rows

        # Credits
        bal = getattr(state, "assets_balance", None)
        r["credits"].set_label(_fmt_credits(bal))

        # Ships value — sum hull+loadout value of all known ships
        current_ship   = getattr(state, "assets_current_ship",   None)
        stored_ships   = getattr(state, "assets_stored_ships",   [])
        stored_modules = getattr(state, "assets_stored_modules", [])
        current_id = (current_ship or {}).get("ship_id")
        all_stored = [s for s in stored_ships if s.get("ship_id") != current_id]
        all_ships  = ([current_ship] if current_ship else []) + all_stored
        ships_val  = sum(s.get("value", 0) for s in all_ships if s)
        r["ships_value"].set_label(_fmt_credits(ships_val) if ships_val else "—")

        # Modules value
        mods_val = sum(m.get("value", 0) for m in stored_modules)
        r["modules_value"].set_label(_fmt_credits(mods_val) if mods_val else "—")

        # Carrier — show balance as a proxy for hull value until we can compute return
        carrier = getattr(state, "assets_carrier", None)
        if carrier:
            # Carrier cargo: galactic avg value of FC materials stock
            fc_mats = getattr(state, "assets_fc_materials", None) or []
            carrier_cargo_val = sum(
                m.get("price", 0) * m.get("stock", 0)
                for m in fc_mats
            )
            r["carrier_cargo"].set_label(
                _fmt_credits(carrier_cargo_val) if carrier_cargo_val else "—"
            )
        else:
            r["carrier_cargo"].set_label("—")
        if carrier:
            ctype = carrier.get("carrier_type", "FleetCarrier")
            decom = 24_850_000_000 if "Squadron" in ctype else 4_850_000_000
            r["carrier_hull"].set_label(_fmt_credits(decom))
            r["carrier_balance"].set_label(
                _fmt_credits(carrier.get("balance")) if carrier.get("balance") else "—"
            )
        r["carrier_hull"].get_parent().set_visible(carrier is not None)
        r["carrier_balance"].get_parent().set_visible(carrier is not None)

        # At Risk
        bounties = getattr(state, "holdings_bounties",    0)
        bonds    = getattr(state, "holdings_bonds",       0)
        trade    = getattr(state, "holdings_trade",       0)
        carto    = getattr(state, "holdings_cartography", 0)
        exobio   = getattr(state, "holdings_exobiology",  0)

        def _risk(key: str, val: int) -> None:
            lbl = r[key]
            lbl.set_label(_fmt_credits(val) if val else "—")
            lbl.get_parent().set_visible(True)

        _risk("risk_bounties", bounties)
        _risk("risk_bonds",    bonds)
        _risk("risk_trade",    trade)
        _risk("risk_carto",    carto)
        _risk("risk_exobio",   exobio)

        # Net Worth
        # Start with Frontier's Statistics-sourced total wealth (credits+ships+modules+carrier)
        # and add what it misses: cargo hold value, carrier cargo, at-risk holdings.
        # ARX excluded (not tracked) — holds no credits value in-game.
        total_wealth = getattr(state, "assets_total_wealth", None)
        cargo_items  = getattr(state, "cargo_items", [])
        cargo_val    = sum(
            item.get("sell_price", 0) * item.get("qty", item.get("count", 0))
            for item in cargo_items
            if isinstance(item, dict)
        )
        risk_total = bounties + bonds + trade + carto + exobio
        carrier_cargo_val2 = sum(
            m.get("price", 0) * m.get("stock", 0)
            for m in (getattr(state, "assets_fc_materials", None) or [])
        )

        if carrier:
            _ctype = carrier.get("carrier_type", "FleetCarrier")
            carrier_hull_val = 24_850_000_000 if "Squadron" in _ctype else 4_850_000_000
        else:
            carrier_hull_val = 0
        if total_wealth is not None:
            nw = int(total_wealth) + cargo_val + carrier_cargo_val2 + risk_total + carrier_hull_val
            r["net_worth"].set_label(_fmt_credits(nw))
        else:
            # Fall back to computed sum
            nw_parts = [
                bal or 0, ships_val, mods_val,
                cargo_val, carrier_cargo_val2, carrier_hull_val, risk_total,
            ]
            nw = sum(int(x) for x in nw_parts)
            r["net_worth"].set_label(_fmt_credits(nw) if nw else "—")

        # Dynamic tab titles
        n_ships = len(all_ships)
        n_mods  = len(stored_modules)
        if hasattr(self, "_tab_labels"):
            if n_ships:
                self._tab_labels["ships"].set_label(f"Ships ({n_ships})")
            else:
                self._tab_labels["ships"].set_label("Ships")
            if n_mods:
                self._tab_labels["modules"].set_label(f"Modules ({n_mods})")
            else:
                self._tab_labels["modules"].set_label("Modules")

    # ── Carrier tab helpers ────────────────────────────────────────────────────
    # ── Carrier tab helpers ────────────────────────────────────────────────────

    def _carrier_section(self, body: "Gtk.Box", title: str) -> None:
        """Append a section header + separator and start a new aligned grid."""
        lbl = Gtk.Label(label=title)
        lbl.add_css_class("data-key")
        lbl.set_xalign(0.0)
        lbl.set_margin_top(6)
        lbl.set_margin_bottom(2)
        body.append(lbl)
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        body.append(sep)
        # Create a fresh grid so key labels within each section share a column.
        self._carrier_current_grid = Gtk.Grid()
        self._carrier_current_grid.set_column_spacing(8)
        self._carrier_current_grid.set_row_spacing(2)
        self._carrier_current_grid.set_margin_top(2)
        self._carrier_current_grid_row = 0
        body.append(self._carrier_current_grid)

    def _carrier_row(self, body: "Gtk.Box", key: str, label: str) -> None:
        """Attach a key/value row to the current section grid."""
        if not hasattr(self, "_carrier_current_grid"):
            # Identity section (before first _carrier_section call) —
            # initialise the first grid using body as the container.
            self._carrier_current_grid = Gtk.Grid()
            self._carrier_current_grid.set_column_spacing(8)
            self._carrier_current_grid.set_row_spacing(2)
            self._carrier_current_grid.set_margin_top(2)
            self._carrier_current_grid_row = 0
            body.append(self._carrier_current_grid)
        gr = self._carrier_current_grid_row
        k_lbl = self.make_label(label, css_class="data-key")
        k_lbl.set_xalign(0.0)
        self._carrier_current_grid.attach(k_lbl, 0, gr, 1, 1)
        v_lbl = self.make_label("—", css_class="data-value")
        v_lbl.set_xalign(1.0)
        v_lbl.set_hexpand(True)
        self._carrier_current_grid.attach(v_lbl, 1, gr, 1, 1)
        self._carrier_current_grid_row += 1
        self._carrier_rows[key] = v_lbl


    _CARRIER_STATES = {
        "normaloperation": "Normal Operation",
        "inmaintenance":   "In Maintenance",
        "debtstate":       "Debt / Suspended",
        "lost":            "Decommissioned",
    }
    _CARRIER_THEMES = {
        "default":   "Default",
        "tactical":  "Tactical",
        "corsair":   "Corsair",
        "bling":     "Prestige",
        "winter":    "Winter",
        "spring":    "Spring",
        "summer":    "Summer",
        "autumn":    "Autumn",
    }

    def _build_carrier_tab(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._carrier_none_lbl = Gtk.Label(label="No fleet carrier on record")
        self._carrier_none_lbl.add_css_class("data-key")
        self._carrier_none_lbl.set_xalign(0.5)
        self._carrier_none_lbl.set_margin_top(8)
        outer.append(self._carrier_none_lbl)

        # Scrollable detail area — hidden until carrier data is present
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add_css_class("mat-tab-scroll")
        self._carrier_detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._carrier_detail_box.set_vexpand(True)
        self._carrier_detail_box.set_margin_start(6)
        self._carrier_detail_box.set_margin_end(12)
        self._carrier_detail_box.set_margin_top(4)
        self._carrier_detail_box.set_margin_bottom(4)
        scroll.set_child(self._carrier_detail_box)
        scroll.set_visible(False)
        outer.append(scroll)
        self._carrier_scroll = scroll

        self._carrier_rows: dict[str, Gtk.Label] = {}
        if hasattr(self, "_carrier_current_grid"):
            del self._carrier_current_grid
        body = self._carrier_detail_box

        # ── Identity ─────────────────────────────────────────────────────────
        self._carrier_row(body, "name",          "Name")
        self._carrier_row(body, "callsign",       "Callsign")
        self._carrier_row(body, "system",         "System")
        self._carrier_row(body, "fuel",           "Fuel")
        self._carrier_row(body, "carrier_state",  "State")
        self._carrier_row(body, "theme",          "Theme")

        # ── Access ────────────────────────────────────────────────────────────
        self._carrier_section(body, "ACCESS")
        self._carrier_row(body, "docking",        "Docking")
        self._carrier_row(body, "notorious",      "Notorious")

        # ── Finance ───────────────────────────────────────────────────────────
        self._carrier_section(body, "FINANCE")
        self._carrier_row(body, "balance",        "Balance")
        self._carrier_row(body, "reserve",        "Reserve")
        self._carrier_row(body, "available",      "Available")
        self._carrier_row(body, "tax_refuel",     "Tax: Refuel")
        self._carrier_row(body, "tax_repair",     "Tax: Repair")
        self._carrier_row(body, "tax_rearm",      "Tax: Rearm")
        self._carrier_row(body, "tax_pioneer",    "Tax: Supplies")
        self._carrier_row(body, "maintenance",     "Upkeep/wk")
        self._carrier_row(body, "maintenance_wtd", "Upkeep so far")

        # ── Cargo ─────────────────────────────────────────────────────────────
        self._carrier_section(body, "CARGO")
        self._carrier_row(body, "cargo_cap_row",   "Total space")
        self._carrier_row(body, "cargo_crew_row",  "Crew/services")
        self._carrier_row(body, "cargo_used_row",  "Cargo stored")
        self._carrier_row(body, "cargo_free_row",  "Cargo free")
        self._carrier_row(body, "cargo_value_row", "Market listings")

        # ── Storage ───────────────────────────────────────────────────────────
        self._carrier_section(body, "STORAGE")
        self._carrier_row(body, "ship_packs",     "Ship Packs")
        self._carrier_row(body, "module_packs",   "Module Packs")
        self._carrier_row(body, "micro_row",      "Micro-resources")

        # ── Services ──────────────────────────────────────────────────────────
        self._carrier_section(body, "SERVICES")
        self._carrier_services_lbl = Gtk.Label(label="—")
        self._carrier_services_lbl.add_css_class("data-key")
        self._carrier_services_lbl.set_xalign(0.0)
        self._carrier_services_lbl.set_wrap(True)
        self._carrier_services_lbl.set_margin_top(2)
        self._carrier_services_lbl.set_margin_bottom(4)
        body.append(self._carrier_services_lbl)

        return outer

    def _make_section_scroll(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.add_css_class("mat-tab-scroll")

        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        list_box.set_vexpand(True)
        list_box.set_margin_end(12)
        scroll.set_child(list_box)

        empty_lbl = Gtk.Label(label="— none —")
        empty_lbl.add_css_class("data-key")
        empty_lbl.set_xalign(0.5)
        empty_lbl.set_margin_top(6)
        empty_lbl.set_margin_bottom(4)
        list_box.append(empty_lbl)
        return scroll, list_box, empty_lbl

    # ── Tab switching ─────────────────────────────────────────────────────────

    def _on_tab_click(self, _btn, cat: str) -> None:
        self._set_active_tab(cat)

    def _set_active_tab(self, cat: str) -> None:
        self._active_tab = cat
        self._tab_stack.set_visible_child_name(cat)
        for key, btn in self._tab_btns.items():
            if key == cat:
                btn.add_css_class("mat-tab-active")
            else:
                btn.remove_css_class("mat-tab-active")

    def on_resize(self, w: int, h: int) -> None:
        super().on_resize(w, h)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        state = self.core.state

        stored_modules = getattr(state, "assets_stored_modules", [])

        self._refresh_wallet(state)

        current_ship   = getattr(state, "assets_current_ship",   None)
        stored_ships   = getattr(state, "assets_stored_ships",   [])
        current_id = (current_ship or {}).get("ship_id")
        if current_id is not None:
            stored_ships = [s for s in stored_ships if s.get("ship_id") != current_id]
        all_ships = ([current_ship] if current_ship else []) + stored_ships

        self._refresh_ships(all_ships)
        # Hide the Modules tab entirely when we have no stored module data.
        # StoredModules only fires when the player opens outfitting; until then
        # the list is empty and showing an empty tab creates a false impression.
        self._tab_btns["modules"].set_visible(bool(stored_modules))
        if stored_modules:
            self._refresh_modules(stored_modules)
        self._refresh_carrier(getattr(state, "assets_carrier", None))

    # ── Carrier tab ─────────────────────────────────────────────────────────────────

    # Service name → display label
    _SVC_LABELS = {
        "blackmarket":         "Black Market",
        "commodities":         "Commodities",
        "workshop":            "Workshop",
        "refuel":              "Refuel",
        "repair":              "Repair",
        "rearm":               "Rearm",
        "shipyard":            "Shipyard",
        "exploration":         "Cartographics",
        "voucherredemption":   "Redemption",
        "pioneersupplies":     "Pioneer Supplies",
        "bartender":           "Bartender",
        "vistagenomics":       "Vista Genomics",
        "socialspace":         "Social Space",
    }
    # Statuses that count as the service being active
    _SVC_ACTIVE = {"ok", "faction"}
    # Internal/infrastructure services to suppress from the display list
    _SVC_HIDDEN = {
        "carriermanagement", "stationmenu", "dock", "crewlounge",
        "contacts", "carrierfuel", "engineer", "livery",
        "registeringcolonisation",
    }

    def _refresh_carrier(self, carrier: dict | None) -> None:
        has = carrier is not None
        self._carrier_none_lbl.set_visible(not has)
        self._carrier_scroll.set_visible(has)
        if not has:
            return

        def _s(key, default="\u2014"):
            v = carrier.get(key, default)
            return str(v) if v is not None else default

        def _cr(key):
            return _fmt_credits(carrier.get(key))

        def _pct_val(key):
            v = carrier.get(key, 0)
            try:
                f = float(v)
                return f"{f:.1f}%" if f != int(f) else f"{int(f)}%"
            except (TypeError, ValueError):
                return "\u2014"

        # ── Identity ─────────────────────────────────────────────────────────
        self._carrier_rows["name"].set_label(_s("name"))
        self._carrier_rows["callsign"].set_label(_s("callsign"))
        self._carrier_rows["system"].set_label(_s("system"))
        fuel = int(carrier.get("fuel", 0) or 0)
        self._carrier_rows["fuel"].set_label(f"{fuel}/1000  ({fuel // 10}%)")
        raw_state = (carrier.get("carrier_state") or "").lower().replace("_", "")
        state_nice = self._CARRIER_STATES.get(raw_state,
                         (carrier.get("carrier_state") or "\u2014").replace("_", " ").title())
        self._carrier_rows["carrier_state"].set_label(state_nice)
        raw_theme = (carrier.get("theme") or "").lower().replace("_", "")
        theme_nice = self._CARRIER_THEMES.get(raw_theme,
                         (carrier.get("theme") or "\u2014").replace("_", " ").title())
        self._carrier_rows["theme"].set_label(theme_nice)

        # ── Access ────────────────────────────────────────────────────────────
        docking = carrier.get("docking", "\u2014") or "\u2014"
        self._carrier_rows["docking"].set_label(
            docking.replace("squadronfriends", "Squadron + Friends")
                   .replace("_", " ").title()
        )
        notorious = carrier.get("notorious", False)
        self._carrier_rows["notorious"].set_label(
            "Allowed" if notorious else "Not Allowed"
        )

        # ── Finance ───────────────────────────────────────────────────────────
        self._carrier_rows["balance"].set_label(_cr("balance"))
        bal     = int(carrier.get("balance",  0) or 0)
        reserve = int(carrier.get("reserve",  0) or 0)
        res_pct = (reserve * 100 // bal) if bal else 0
        self._carrier_rows["reserve"].set_label(
            f"{_fmt_credits(reserve)}  ({res_pct}%)" if reserve else "\u2014"
        )
        self._carrier_rows["available"].set_label(_cr("available"))
        self._carrier_rows["tax_refuel"].set_label(_pct_val("tax_refuel"))
        self._carrier_rows["tax_repair"].set_label(_pct_val("tax_repair"))
        self._carrier_rows["tax_rearm"].set_label(_pct_val("tax_rearm"))
        self._carrier_rows["tax_pioneer"].set_label(_pct_val("tax_pioneer"))
        maint = int(carrier.get("maintenance",     0) or 0)
        mwtd  = int(carrier.get("maintenance_wtd", 0) or 0)
        self._carrier_rows["maintenance"].set_label(
            _fmt_credits(maint) if maint else "\u2014"
        )
        self._carrier_rows["maintenance_wtd"].set_label(
            _fmt_credits(mwtd) if mwtd else "\u2014"
        )

        # ── Cargo ─────────────────────────────────────────────────────────────
        ctotal = int(carrier.get("cargo_total", 0) or 0)
        ccrew  = int(carrier.get("cargo_crew",  0) or 0)
        cused  = int(carrier.get("cargo_used",  0) or 0)
        cfree  = int(carrier.get("cargo_free",  0) or 0)
        self._carrier_rows["cargo_cap_row"].set_label(
            f"{ctotal:,} t" if ctotal else "\u2014"
        )
        self._carrier_rows["cargo_crew_row"].set_label(
            f"{ccrew:,} t" if ccrew else "\u2014"
        )
        if cused or cfree:
            self._carrier_rows["cargo_used_row"].set_label(f"{cused:,} t")
            self._carrier_rows["cargo_free_row"].set_label(f"{cfree:,} t")
        else:
            self._carrier_rows["cargo_used_row"].set_label("0 t")
            self._carrier_rows["cargo_free_row"].set_label(f"{cfree:,} t")

        # Market listings — value of items actively listed for sale on FC market
        fc_mats = getattr(self.state, "assets_fc_materials", None) or []
        inv_val  = sum(m.get("price", 0) * m.get("stock", 0) for m in fc_mats)
        self._carrier_rows["cargo_value_row"].set_label(
            _fmt_credits(inv_val) if inv_val else "—"
        )

        # ── Storage ───────────────────────────────────────────────────────────
        sp = int(carrier.get("ship_packs",   0) or 0)
        mp = int(carrier.get("module_packs", 0) or 0)
        self._carrier_rows["ship_packs"].set_label(str(sp) if sp else "\u2014")
        self._carrier_rows["module_packs"].set_label(str(mp) if mp else "\u2014")
        mt = int(carrier.get("micro_total", 0) or 0)
        mu = int(carrier.get("micro_used",  0) or 0)
        mf = int(carrier.get("micro_free",  0) or 0)
        self._carrier_rows["micro_row"].set_label(
            f"{mu}/{mt}  ({mf} free)" if mt else "\u2014"
        )

        # ── Services ──────────────────────────────────────────────────────────
        svcs = carrier.get("services") or {}
        active = sorted(
            self._SVC_LABELS.get(k, k.replace("_", " ").title())
            for k, v in svcs.items()
            if v in self._SVC_ACTIVE and k not in self._SVC_HIDDEN
        )
        unavailable = sorted(
            self._SVC_LABELS.get(k, k.replace("_", " ").title())
            for k, v in svcs.items()
            if v == "unavailable" and k not in self._SVC_HIDDEN
        )
        unmanned = sorted(
            self._SVC_LABELS.get(k, k.replace("_", " ").title())
            for k, v in svcs.items()
            if v == "unmanned" and k not in self._SVC_HIDDEN
        )
        parts = []
        if active:
            parts.append("\u2705 " + ",  ".join(active))
        if unmanned:
            parts.append("\U0001f6ab Unmanned: " + ",  ".join(unmanned))
        if unavailable:
            parts.append("\u274c N/A: " + ",  ".join(unavailable))
        self._carrier_services_lbl.set_label(
            "\n".join(parts) if parts else "\u2014"
        )


    # ── Ships tab ─────────────────────────────────────────────────────────────

    def _refresh_ships(self, ships: list) -> None:
        sec = self._sections.get("ships")
        if sec is None:
            return
        list_box  = sec["list_box"]
        empty_lbl = sec["empty_lbl"]
        rows      = sec["rows"]

        seen = set()
        for ship in ships:
            key = ship.get("_key", "")
            seen.add(key)

            type_disp  = ship.get("type_display", "Unknown")
            name       = ship.get("name", "")
            is_current = ship.get("current", False)
            star       = "  \u2605" if is_current else ""

            ident = ship.get("ident", "") or ""
            ident_str = f" [{ident}]" if ident else ""
            if name:
                line1 = f"{name}{ident_str}  ({type_disp}){star}"
            else:
                line1 = f"{type_disp}{ident_str}{star}"
            line2 = ship.get("system", "\u2014")
            if ship.get("hot"):
                line2 = "\U0001f534 HOT  " + line2

            if key in rows:
                container, n_lbl, s_lbl = rows[key]
                n_lbl.set_label(line1)
                s_lbl.set_label(line2)
                self._update_ship_popover(container, ship)
            else:
                container = self._make_ship_row(key, ship, line1, line2, list_box)
                rows[key] = (container, container._n_lbl, container._s_lbl)

        for key in list(rows.keys()):
            if key not in seen:
                container, _, _ = rows.pop(key)
                if hasattr(container, "_popover"):
                    container._popover.unparent()
                list_box.remove(container)

        empty_lbl.set_visible(len(seen) == 0)

    def _make_ship_row(self, key, ship, line1, line2, list_box):
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        btn = Gtk.Button()
        btn.add_css_class("assets-row-btn")
        btn.set_can_focus(False)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        inner.set_margin_top(2)
        inner.set_margin_bottom(2)
        inner.set_margin_start(4)

        n_lbl = self.make_label(line1, css_class="data-value")
        n_lbl.set_wrap(False)
        n_lbl.set_ellipsize(3)
        s_lbl = self.make_label(line2, css_class="data-key")
        s_lbl.set_wrap(False)
        s_lbl.set_ellipsize(3)
        inner.append(n_lbl)
        inner.append(s_lbl)
        btn.set_child(inner)
        container.append(btn)

        container._n_lbl = n_lbl
        container._s_lbl = s_lbl

        popover = self._build_ship_popover(ship)
        popover.set_parent(btn)
        container._popover = popover
        btn.connect("clicked", lambda b, p=popover: p.popup())

        list_box.append(container)
        return container

    def _build_ship_popover(self, ship):
        """Build a scrollable ship detail popover using a Box layout.

        Uses a Box instead of Grid so we can dynamically add/clear the
        fitted-modules section in _update_ship_popover without rebuilding.
        """
        popover = Gtk.Popover()
        popover.add_css_class("assets-detail-popover")
        popover.set_autohide(True)

        # Outer scroll wrapper so popover stays on-screen for large loadouts
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(520)
        scroll.set_propagate_natural_height(True)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.set_margin_top(8)
        outer.set_margin_bottom(8)
        outer.set_margin_start(10)
        outer.set_margin_end(12)
        scroll.set_child(outer)

        def _kv_row(key, val, box):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            kl = Gtk.Label(label=key)
            kl.set_xalign(0.0)
            kl.add_css_class("data-key")
            kl.set_size_request(52, -1)
            vl = Gtk.Label(label=str(val))
            vl.set_xalign(0.0)
            vl.add_css_class("data-value")
            vl.set_hexpand(True)
            row.append(kl)
            row.append(vl)
            box.append(row)
            return vl  # return val label for later update

        id_rows = [
            ("Type",   ship.get("type_display", "\u2014")),
            ("Name",   ship.get("name", "") or "\u2014"),
            ("Ident",  ship.get("ident", "") or "\u2014"),
            ("System", ship.get("system", "\u2014")),
            ("Value",  _fmt_credits(ship.get("value"))),
            ("Rebuy",  _fmt_credits(ship.get("rebuy"))),
            ("Hull",   f"{ship.get('hull', 100)}%" if ship.get("hull") is not None else "\u2014"),
            ("Status", "\U0001f534 HOT" if ship.get("hot") else "Clean"),
        ]
        val_labels = {}
        for k, v in id_rows:
            val_labels[k] = _kv_row(k, v, outer)

        # Modules sub-box — cleared and repopulated on each update
        mod_sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        mod_sep.set_margin_top(6)
        mod_sep.set_margin_bottom(2)
        outer.append(mod_sep)

        mod_hdr = Gtk.Label(label="FITTED MODULES")
        mod_hdr.add_css_class("data-key")
        mod_hdr.set_xalign(0.0)
        mod_hdr.set_margin_bottom(2)
        outer.append(mod_hdr)

        mod_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.append(mod_box)

        popover._val_labels = val_labels
        popover._mod_box    = mod_box
        popover._mod_sep    = mod_sep
        popover._mod_hdr    = mod_hdr
        popover.set_child(scroll)

        # Populate modules section with initial data
        _populate_ship_modules(mod_box, ship.get("loadout") or [], mod_sep, mod_hdr)
        return popover

    def _update_ship_popover(self, container, ship):
        try:
            pop = container._popover
            vl  = pop._val_labels
            vl["Type"].set_label(ship.get("type_display", "\u2014"))
            vl["Name"].set_label(ship.get("name", "") or "\u2014")
            vl["Ident"].set_label(ship.get("ident", "") or "\u2014")
            vl["System"].set_label(ship.get("system", "\u2014"))
            if "Hull" in vl:
                _h = ship.get("hull")
                vl["Hull"].set_label(f"{_h}%" if _h is not None else "\u2014")
            vl["Value"].set_label(_fmt_credits(ship.get("value")))
            if "Rebuy" in vl:
                vl["Rebuy"].set_label(_fmt_credits(ship.get("rebuy")))
            vl["Status"].set_label("\U0001f534 HOT" if ship.get("hot") else "Clean")
            # Rebuild module list (loadout may have arrived after popover was created)
            _populate_ship_modules(
                pop._mod_box,
                ship.get("loadout") or [],
                pop._mod_sep,
                pop._mod_hdr,
            )
        except Exception as _ex:
            import traceback as _tb
            _tb.print_exc()
            pass

    # ── Modules tab ───────────────────────────────────────────────────────────

    def _refresh_modules(self, modules: list) -> None:
        sec = self._sections.get("modules")
        if sec is None:
            return
        list_box  = sec["list_box"]
        empty_lbl = sec["empty_lbl"]
        rows      = sec["rows"]   # key -> (container, n_lbl, s_lbl)

        # Only re-render when module data actually changes.
        # Full re-render destroys widget rows, closing any open popovers.
        fp = tuple((m.get("_key",""), m.get("name_display",""),
                    m.get("system",""), bool(m.get("hot")),
                    m.get("engineering",{}).get("BlueprintName",""),
                    m.get("engineering",{}).get("Level"))
                   for m in (modules or []))
        if fp == sec.get("_last_fp") and sec.get("cat_headers") is not None:
            return  # nothing changed — leave widgets intact
        sec["_last_fp"] = fp

        # Full re-render grouped by category.
        # Remove all existing item rows and category headers.
        for key, (container, _n, _s) in list(rows.items()):
            try:
                if hasattr(container, "_popover"):
                    pop = container._popover
                    try: pop.popdown()
                    except Exception: pass
                    try: pop.unparent()
                    except Exception: pass
            except Exception:
                pass
            try: list_box.remove(container)
            except Exception: pass
        rows.clear()
        # Remove category header widgets (stored in sec dict under "cat_headers")
        for hdr in sec.get("cat_headers", []):
            list_box.remove(hdr)
        sec["cat_headers"] = []

        if not modules:
            empty_lbl.set_visible(True)
            return
        empty_lbl.set_visible(False)

        # Group modules by hardware category derived from internal name
        from collections import defaultdict as _dd
        groups: dict = _dd(list)
        _SKIP_MOD_PREFIXES = ("decal_", "nameplate_", "paintjob_", "bobble_",
                              "voicepack_", "enginecustomisation_", "weaponcustomisation_")
        for mod in modules:
            ni = mod.get("name_internal", "").lower()
            if any(ni.startswith(p) for p in _SKIP_MOD_PREFIXES):
                continue  # skip cosmetic-only stored modules
            # Also skip cargo hatch and cockpit module
            if ni in ("modularcargobaydoor", ""):
                continue
            if "cockpit" in ni:
                continue
            cat = _module_category_from_name(mod.get("name_internal", ""))
            groups[cat].append(mod)

        _CAT_ORDER = [
            "Hardpoints", "Core Internal", "Optional Internal",
            "Utility Mounts", "Other",
        ]
        all_cats = _CAT_ORDER + [c for c in groups if c not in _CAT_ORDER]

        for cat in all_cats:
            mods_in_cat = groups.get(cat)
            if not mods_in_cat:
                continue

            # Category header label
            cat_lbl = Gtk.Label(label=cat.upper())
            cat_lbl.set_xalign(0.0)
            cat_lbl.add_css_class("data-key")
            cat_lbl.set_margin_top(4)
            cat_lbl.set_margin_start(4)
            list_box.append(cat_lbl)
            sec["cat_headers"].append(cat_lbl)

            # Sort by name within category
            for mod in sorted(mods_in_cat, key=lambda m: m.get("name_display", "")):
                key = mod.get("_key", "")

                line1 = mod.get("name_display", "Unknown")
                _eng  = mod.get("engineering") or {}
                _bp   = _eng.get("BlueprintName", "")
                _lvl  = _eng.get("Level")
                _exp  = _eng.get("ExperimentalEffect", "")
                if _bp:
                    _e = _normalise_eng_name(_bp)
                    if _lvl: _e += f" G{_lvl}"
                    if _exp: _e += f" / {_normalise_eng_name(_exp)}"
                    line2 = _e
                else:
                    line2 = mod.get("system", "\u2014")
                if mod.get("hot"):
                    line2 = "\U0001f534 HOT  " + line2

                container = self._make_mod_row(key, mod, line1, line2, list_box)
                rows[key] = (container, container._n_lbl, container._s_lbl)

    def _make_mod_row(self, key, mod, line1, line2, list_box):
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        btn = Gtk.Button()
        btn.add_css_class("assets-row-btn")
        btn.set_can_focus(False)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        inner.set_margin_top(2)
        inner.set_margin_bottom(2)
        inner.set_margin_start(4)

        n_lbl = self.make_label(line1, css_class="data-value")
        n_lbl.set_ellipsize(3)
        s_lbl = self.make_label(line2, css_class="data-key")
        s_lbl.set_ellipsize(3)
        inner.append(n_lbl)
        inner.append(s_lbl)
        btn.set_child(inner)
        container.append(btn)

        container._n_lbl = n_lbl
        container._s_lbl = s_lbl

        popover = self._build_mod_popover(mod)
        popover.set_parent(btn)
        container._popover = popover
        btn.connect("clicked", lambda b, p=popover: p.popup())

        list_box.append(container)
        return container

    def _build_mod_popover(self, mod):
        popover = Gtk.Popover()
        popover.add_css_class("assets-detail-popover")
        popover.set_autohide(True)

        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(3)
        grid.set_margin_top(8)
        grid.set_margin_bottom(8)
        grid.set_margin_start(10)
        grid.set_margin_end(10)

        mass = mod.get("mass", 0.0)
        _eng = mod.get("engineering") or {}
        _bp  = _eng.get("BlueprintName") or _eng.get("blueprint_name", "")
        _lvl = _eng.get("Level") or _eng.get("level")
        _exp = _eng.get("ExperimentalEffect") or _eng.get("experimental", "")
        _eng_str = "\u2014"
        if _bp:
            _eng_str = _bp.replace("_", " ").strip()
            if _lvl is not None: _eng_str += f" G{_lvl}"
            if _exp: _eng_str += f" / {_exp.replace(chr(95), chr(32)).strip()}"
        rows_data = [
            ("Module",  mod.get("name_display", "\u2014")),
            ("Slot",    mod.get("slot", "") or "\u2014"),
            ("System",  mod.get("system", "\u2014")),
            ("Mass",    f"{mass:.1f} t" if mass else "\u2014"),
            ("Value",   _fmt_credits(mod.get("value"))),
            ("Eng",     _eng_str),
            ("Status",  "\U0001f534 HOT" if mod.get("hot") else "Clean"),
        ]
        for i, (k, v) in enumerate(rows_data):
            key_lbl = Gtk.Label(label=k)
            key_lbl.set_xalign(0.0)
            key_lbl.add_css_class("data-key")
            val_lbl = Gtk.Label(label=str(v))
            val_lbl.set_xalign(0.0)
            val_lbl.add_css_class("data-value")
            grid.attach(key_lbl, 0, i, 1, 1)
            grid.attach(val_lbl, 1, i, 1, 1)

        popover._val_labels = {k: grid.get_child_at(1, i)
                                for i, (k, _) in enumerate(rows_data)}
        popover.set_child(grid)
        return popover

    def _update_mod_popover(self, container, mod):
        try:
            vl = container._popover._val_labels
            mass = mod.get("mass", 0.0)
            _eng = mod.get("engineering") or {}
            _bp  = _eng.get("BlueprintName") or _eng.get("blueprint_name", "")
            _lvl = _eng.get("Level") or _eng.get("level")
            _exp = _eng.get("ExperimentalEffect") or _eng.get("experimental", "")
            _eng_str = "\u2014"
            if _bp:
                _eng_str = _bp.replace("_", " ").strip()
                if _lvl is not None: _eng_str += f" G{_lvl}"
                if _exp: _eng_str += f" / {_exp.replace(chr(95), chr(32)).strip()}"
            vl["Module"].set_label(mod.get("name_display", "\u2014"))
            vl["Slot"].set_label(mod.get("slot", "") or "\u2014")
            vl["System"].set_label(mod.get("system", "\u2014"))
            vl["Mass"].set_label(f"{mass:.1f} t" if mass else "\u2014")
            vl["Value"].set_label(_fmt_credits(mod.get("value")))
            if "Eng" in vl: vl["Eng"].set_label(_eng_str)
            vl["Status"].set_label("\U0001f534 HOT" if mod.get("hot") else "Clean")
        except Exception:
            pass
