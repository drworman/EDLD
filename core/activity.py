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
