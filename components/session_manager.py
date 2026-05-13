"""
components/session_manager.py — Session flush notification shim.

Receives plugin_call("session_manager", "flush_session", reason) calls
and emits a Discord alert so the player has a record of why the session ended.
Also queues a GUI status update if a session management block is present.
"""

from core.plugin_loader import BasePlugin


class SessionManagerPlugin(BasePlugin):
    PLUGIN_NAME    = "session_manager"
    PLUGIN_DISPLAY = "Session Manager"
    PLUGIN_VERSION = "1.0.0"

    SUBSCRIBED_EVENTS = []   # no journal events — receives plugin_call only

    def on_load(self, core) -> None:
        super().on_load(core)

    def flush_session(self, reason: str = "") -> None:
        """Signal a session flush. Emits a Discord notification with the reason."""
        core = self.core
        msg = f"Session ended: {reason}" if reason else "Session ended"
        core.emitter.emit(
            msg_term=f"[session_manager] {msg}",
            msg_discord=f"🛑 **{msg}**",
            emoji="🛑", sigil="!! TERM",
            timestamp=core.state.event_time,
            loglevel=2,
        )
        # Notify GUI queue so the session management block can update its status label
        gq = core.gui_queue
        if gq:
            gq.put(("session_flush", reason))
