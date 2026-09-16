"""
core/activity.py — Activity provider protocol for the Session Stats block.

Activity components implement ActivityProviderMixin and call
core.register_session_provider(self) in their on_load().

session_stats iterates registered providers to build the Summary tab and
dynamically create per-activity tabs.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class ActivityProviderMixin:
    """
    Mixin for components that contribute data to the Session Stats block.

    Implementing components should:
      1. Inherit from both BasePlugin and ActivityProviderMixin.
      2. Call core.register_session_provider(self) in on_load().
      3. Override get_summary_rows(), get_tab_rows(), tab_title, has_activity().

    Data format
    -----------
    get_summary_rows() and get_tab_rows() return lists of row dicts:

        {"label": str, "value": str, "rate": str | None}

    label  — left-aligned key (e.g. "Kills")
    value  — right-aligned total (e.g. "142")
    rate   — right-aligned /hr string (e.g. "22.5 /hr") or None to omit
    """

    # Override in subclass — used as the tab label in the session stats block
    ACTIVITY_TAB_TITLE: str = "Activity"

    def get_summary_rows(self) -> list[dict]:
        """Rows to show in the Summary tab. Return [] if nothing to report."""
        return []

    def get_tab_rows(self) -> list[dict]:
        """Rows to show in this activity's own tab. Return [] if nothing."""
        return []

    def has_activity(self) -> bool:
        """Return True if there is any non-zero activity to display."""
        return False

    # ── overlay ───────────────────────────────────────────────────────────────
    #
    # An activity component already answers both questions the overlay needs.
    # ``has_activity()`` is the relevance test — it is what decides whether this
    # activity gets a tab in the session block at all — and
    # ``get_summary_rows()`` is already the condensed subset, because that is
    # exactly what the Summary tab needs it to be. Asking components to
    # reimplement either for the overlay would be writing a second answer to a
    # question they have already answered, and the two would drift.
    #
    # So the default panel is the summary rows, trimmed to what fits over a
    # game. A component overrides ``overlay_panel()`` only when the overlay
    # wants something the dashboard does not show — cargo's two holds, the
    # survey compass's bearings — not merely to have a panel at all.

    #: How many summary rows survive the trip to the overlay. The dashboard has
    #: a column; the overlay has a corner of someone's game.
    OVERLAY_MAX_ROWS: int = 4

    @property
    def OVERLAY_PANELS(self) -> tuple[str, ...]:
        """Panel ids this component offers.

        Derived from the plugin name so an activity component contributes a
        panel without declaring anything.
        """
        name = getattr(self, "PLUGIN_NAME", "") or ""
        return (name,) if name else ()

    #: Career section in ``core.summary_model.career_sections`` that
    #: corresponds to this activity, when there is one. A component whose
    #: figures are session-only leaves it None and its scope setting is never
    #: offered, because a choice between career and session is meaningless
    #: where only one of the two exists.
    CAREER_SECTION: str | None = None

    #: How much of each row to show. Overridden per panel from config; see
    #: components/overlay.py.
    OVERLAY_SCOPE: str = "session"

    def overlay_career_rows(self, core) -> list[dict]:
        """This activity's career rows, or empty if it has no career figures."""
        # Falls back to the activity's own tab title, which matches the career
        # section name for most of them. An activity with no matching section
        # simply has no career figures, and that is the same answer.
        section = getattr(self, "CAREER_SECTION", None) \
            or getattr(self, "ACTIVITY_TAB_TITLE", None)
        if not section or core is None:
            return []
        try:
            from core.summary_model import career_sections
            for block in career_sections(core) or []:
                if str(block.get("title", "")) == section:
                    return [r for r in block.get("rows", []) if r.get("value")]
        except Exception:
            return []
        return []

    def overlay_has_career(self, core) -> bool:
        """Whether a career/session choice means anything for this activity.

        Asked by the preferences page so the scope picker is only offered where
        both halves exist — a dropdown choosing between career and session on
        an activity that has only one of them is a control that does nothing.
        """
        return bool(self.overlay_career_rows(core))

    def overlay_panel(self, panel_id: str, ctx):
        """Default panel: this activity's rows, at the configured scope."""
        if panel_id != getattr(self, "PLUGIN_NAME", None):
            return None
        scope = str(getattr(self, "OVERLAY_SCOPE", "session") or "session")
        core = getattr(self, "core", None)

        try:
            session_rows = self.get_summary_rows() or [] \
                if self.has_activity() else []
        except Exception:
            session_rows = []
        career_rows = self.overlay_career_rows(core) if scope != "session" else []

        if scope == "career":
            rows, session_by_label = career_rows, {}
        elif scope == "both":
            # Career is the figure, session is the parenthetical. A commander
            # who wants both wants to know what today added to the total, not
            # to read two separate numbers and do the subtraction.
            rows = career_rows or session_rows
            session_by_label = {str(r.get("label", "")): r for r in session_rows}
        else:
            rows, session_by_label = session_rows, {}

        if not rows:
            return None

        from core.overlay_panels import Panel
        out: list[tuple[str, str]] = []
        for row in rows[:max(1, int(self.OVERLAY_MAX_ROWS))]:
            label = str(row.get("label", "") or "")
            value = str(row.get("value", "") or "")
            rate = row.get("rate")
            # The rate is the half of a session row worth covering a game for —
            # a total is knowable afterwards, a rate is only interesting now.
            if rate:
                value = f"{value}  {rate}"
            twin = session_by_label.get(label)
            if twin and twin is not row and twin.get("value"):
                value = f"{value} (Session: {twin['value']})"
            out.append((label, value))
        return Panel(id=panel_id,
                     title=str(getattr(self, "ACTIVITY_TAB_TITLE", "") or
                               panel_id).upper(),
                     rows=out)

    def _duration_seconds(self) -> float:
        """Seconds elapsed since session_start_time (wall clock).

        Uses datetime.now(utc) so the value advances in real time even
        between journal events — important for rate calculations.
        Returns 0.0 if session_start_time is not yet set.
        """
        start = getattr(self, "session_start_time", None)
        if not start:
            return 0.0
        from datetime import datetime, timezone
        return (datetime.now(timezone.utc) - start).total_seconds()

    def on_session_reset(self) -> None:
        """Called when a new gaming session begins. Reset all counters."""
        pass

    def on_summary(self) -> None:
        """Called each time a quarter-hour summary fires.

        Activity components that use a monotonic summary timestamp as a fallback
        reference for idle-alert timing should override this to refresh that
        timestamp.  The default is a no-op — only activity_combat needs it.
        """
        pass
