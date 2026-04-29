"""tui/blocks/engineering.py — Engineering materials inventory block."""
from __future__ import annotations
from textual.app        import ComposeResult
from textual.widgets    import Label, TabbedContent, TabPane
from textual.containers import VerticalScroll
from tui.block_base     import TuiBlock, KVRow

_TABS = [
    ("raw",          "Raw"),
    ("manufactured", "Mfg"),
    ("encoded",      "Enc"),
    ("components",   "Comp"),
    ("items",        "Items"),
    ("consumables",  "Cons"),
    ("data",         "Data"),
]


class EngineeringBlock(TuiBlock):
    BLOCK_TITLE = "ENGINEERING"

    def _compose_body(self) -> ComposeResult:
        with TabbedContent(id="eng-tabs"):
            for key, label in _TABS:
                with TabPane(label, id=f"eng-pane-{key}"):
                    yield VerticalScroll(id=f"eng-scroll-{key}")

    def refresh_data(self) -> None:
        s  = self.state
        lk = getattr(s, "engineering_locker", {})

        buckets = {
            "raw":          getattr(s, "materials_raw",          {}),
            "manufactured": getattr(s, "materials_manufactured", {}),
            "encoded":      getattr(s, "materials_encoded",      {}),
            "components":   lk.get("components", {}),
            "items":        lk.get("items",       {}),
            "consumables":  lk.get("consumables", {}),
            "data":         lk.get("data",        {}),
        }

        for key, items in buckets.items():
            try:
                scroll = self.query_one(f"#eng-scroll-{key}", VerticalScroll)
            except Exception:
                continue

            scroll.remove_children()

            if not items:
                scroll.mount(Label("[dim]— none —[/dim]", classes="dim"))
                continue

            sorted_items = sorted(
                items.items(),
                key=lambda kv: kv[1].get("name_local", kv[0]).lower()
            )
            total = sum(v.get("count", 0) for v in items.values())

            rows: list = [Label(f"[dim]Total: {total}[/dim]")]
            for _, data in sorted_items:
                name  = data.get("name_local", "")
                count = data.get("count", 0)
                rows.append(KVRow(name, str(count)))

            scroll.mount(*rows)
