"""
tests/test_trace_redaction.py — no credentials in the --trace header.

The trace header dumps the effective config on every launch, and those logs
get attached to bug reports.  Before this, ``WebhookURL`` was written in full:
a Discord webhook URL is a bearer credential, so anyone holding the log could
post to the channel.

The redaction keeps the diagnostic value — whether a credential is configured
— without the value itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.debug import _format_toml_block, _is_secret_key, _redact  # noqa: E402

#: A realistic secret value per credential-shaped key.
SECRET = "s3cr3t-VALUE-do-not-log"


@pytest.mark.parametrize(
    "key",
    [
        "WebhookURL", "webhook_url", "Webhook-URL",
        "InaraAPIKey", "api_key", "ApiToken",
        "CapiRefreshToken", "access_token",
        "Password", "passwd", "ClientSecret",
        "AuthCode", "Credential",
    ],
)
def test_credential_keys_are_classified_secret(key):
    assert _is_secret_key(key), f"{key} should be treated as a credential"


@pytest.mark.parametrize(
    "key",
    [
        "UseUTC", "TruncateNames", "ForumChannel", "Identity",
        "Timestamp", "UserID", "Enabled", "MinScanLevel",
        "UploadCarrierEvents", "WarnCooldown",
    ],
)
def test_ordinary_keys_are_not_redacted(key):
    assert not _is_secret_key(key)
    assert _redact(key, "plain") == "plain"


def test_secret_value_never_appears_in_output():
    cfg = {
        "Discord": {"Identity": True, "WebhookURL": SECRET},
        "Integrations": {"InaraAPIKey": SECRET, "EDAstro": True},
    }
    out = "\n".join(_format_toml_block(cfg))
    assert SECRET not in out
    # Non-secret keys still render normally, so the dump stays useful.
    assert "Identity = true" in out
    assert "EDAstro = true" in out


def test_redaction_distinguishes_set_from_empty():
    """Whether a credential is configured is the diagnostic signal worth keeping."""
    assert "set" in _redact("WebhookURL", SECRET)
    assert "empty" in _redact("WebhookURL", "")


def test_redaction_applies_to_top_level_scalars_too():
    out = "\n".join(_format_toml_block({"WebhookURL": SECRET}))
    assert SECRET not in out


def test_real_world_webhook_shape_is_redacted():
    """A full Discord webhook URL, the exact shape that leaked."""
    url = ("https://discord.com/api/webhooks/1462560202837594234/"
           "YkLi-JhmQNzXaoNkiqU9gUS8zBcymM3R2r9XM0JdKG6SsRnP2kgWlUYqI2yMX6eipdGf")
    out = "\n".join(_format_toml_block({"Discord": {"WebhookURL": url}}))
    for fragment in (url, "1462560202837594234", "YkLi-JhmQNzXaoNkiqU9"):
        assert fragment not in out


# ── Profile sections ──────────────────────────────────────────────────────────
#
# A profile holds its overrides as nested tables, so the key beside each
# credential in the dump is the section name.  Redaction that only looked one
# level down let every profile-level credential through in full.

def test_profile_nested_credentials_are_redacted():
    """The exact shape of a real [EDP1] profile dump."""
    cfg = {
        "EDP1": {
            "Settings": {"JournalFolder": "/home/cmdr/journals"},
            "EDSM": {"ApiKey": SECRET, "CommanderName": "MERRICK"},
            "Inara": {"ApiKey": SECRET},
            "Colonisation": {"ApiKey": SECRET},
            "Discord": {"WebhookURL": SECRET},
            "SurfaceSurvey": {"Token": SECRET},
        },
    }
    out = "\n".join(_format_toml_block(cfg))
    assert SECRET not in out
    # The dump still answers the diagnostic question for each of them.
    assert out.count("<redacted — set>") == 5
    # And ordinary nested values survive, so the dump stays useful.
    assert "/home/cmdr/journals" in out
    assert "MERRICK" in out


def test_redaction_walks_any_depth():
    cfg = {"P": {"A": {"B": {"C": {"api_key": SECRET, "ok": 1}}}}}
    out = "\n".join(_format_toml_block(cfg))
    assert SECRET not in out
    assert "'ok': 1" in out


def test_secret_named_table_is_redacted_whole():
    """A table whose own name is credential-shaped hides every value in it."""
    out = "\n".join(_format_toml_block({"P": {"Auth": {"user": SECRET,
                                                        "pass": SECRET}}}))
    assert SECRET not in out
    assert "2 key(s)" in out


def test_tables_inside_lists_are_redacted():
    out = "\n".join(_format_toml_block(
        {"P": {"Hooks": [{"WebhookURL": SECRET}, "plain"]}}))
    assert SECRET not in out
    assert "plain" in out
