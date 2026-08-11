"""gui/blocks/engineering.py — Engineering materials inventory block (Qt)."""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget

from gui.block_base import GuiBlock, RowScroll

_TABS = [
    ("raw",          "Raw"),
    ("manufactured", "Mfg"),
    ("encoded",      "Enc"),
    ("components",   "Comp"),
    ("items",        "Items"),
    ("consumables",  "Cons"),
    ("data",         "Data"),
]


class EngineeringBlock(GuiBlock):
    BLOCK_TITLE = "ENGINEERING"

    def _build_body(self, layout) -> None:
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._scrolls: dict[str, RowScroll] = {}
        for key, label in _TABS:
            scroll = RowScroll()
            self._scrolls[key] = scroll
            self._tabs.addTab(scroll, label)
        layout.addWidget(self._tabs, 1)

    def refresh_data(self) -> None:
        s = self.state
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
            scroll = self._scrolls.get(key)
            if scroll is None:
                continue

            if not items:
                scroll.set_rows([self.text("— none —", "dim")])
                continue

            sorted_items = sorted(
                items.items(),
                key=lambda kv: kv[1].get("name_local", kv[0]).lower()
            )
            total = sum(v.get("count", 0) for v in items.values())

            rows: list = [self.text(f"Total: {total}")]
            for _, data in sorted_items:
                name = data.get("name_local", "")
                count = data.get("count", 0)
                rows.append(self.kv(name, str(count)))

            scroll.set_rows(rows)
