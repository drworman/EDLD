# EDLD Mission Bootstrap

When EDLD starts, it needs to know which massacre missions you have active and what they're worth. The game's `Missions` journal event at login contains the active mission list but frequently omits reward values — and if EDLD is launched mid-session, that event may not appear in the current journal at all.

EDLD resolves this by scanning **all available journal files** in chronological order after preload completes, replaying `MissionAccepted`, `MissionCompleted`, `MissionAbandoned`, `MissionFailed`, and `MissionRedirected` events to reconstruct exactly which missions are active, what they're worth, and how many have had their kill quota met. Missions whose `Expiry` timestamp has passed are filtered out automatically.

This means your stack value and completion count are accurate from the moment monitoring goes live, regardless of when or how EDLD was started — mid-session, after a relog, or with missions accepted in a previous game session.

---

## Kill Credit Limitation

The journal does not provide enough information to accurately attribute kills to specific missions when multiple missions share the same target faction. The `MissionRedirected` event is the only reliable signal that a mission's kill quota has been fully met.

As a result, EDLD tracks **completion count** (missions redirected / total active) rather than incremental kill credit per mission. Stack value and completion count are accurate; per-mission kill progress is not tracked.
