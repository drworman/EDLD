"""
tests/test_config_defaults.py — config defaults, the example file, and backfill.

EDLD gets a config two ways: it ships ``example.config.toml`` as a commented
reference, and it writes a default one from ``CFG_DEFAULTS_*`` when none
exists.  Both had drifted from the defaults — the example was missing keys and
two whole sections, and the generated file omitted three sections entirely, so
a new install got a config that did not mention them at all.

These tests derive what should be present from the defaults themselves, so a
setting added in a future release fails here rather than being noticed only
when a user reports the warning.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.config as C  # noqa: E402
from core.config import backfill_config_defaults  # noqa: E402

EXAMPLE = ROOT / "example.config.toml"

#: Sections the example file is expected to document, and their defaults.
DOCUMENTED = {
    "Settings":  {**C.CFG_DEFAULTS_SETTINGS, **C.CFG_DEFAULTS_EXTRA},
    "Discord":   C.CFG_DEFAULTS_DISCORD,
    "UI":        C.CFG_DEFAULTS_UI,
    "LogLevels": C.CFG_DEFAULTS_NOTIFY,
    "EDDN":      C.CFG_DEFAULTS_EDDN,
    "EDSM":      C.CFG_DEFAULTS_EDSM,
    "EDAstro":   C.CFG_DEFAULTS_EDASTRO,
    "Inara":     C.CFG_DEFAULTS_INARA,
    "CAPI":      C.CFG_DEFAULTS_CAPI,
    "Colonisation": C.CFG_DEFAULTS_COLONISATION,
}


@pytest.fixture(scope="module")
def example_text() -> str:
    return EXAMPLE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def example_parsed() -> dict:
    return tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_example_config_is_valid_toml(example_parsed):
    assert example_parsed


@pytest.mark.parametrize("section", sorted(DOCUMENTED))
def test_example_documents_every_section(section, example_text):
    assert f"[{section}]" in example_text, (
        f"example.config.toml has no [{section}] section")


@pytest.mark.parametrize(
    "section,key",
    [(s, k) for s, d in DOCUMENTED.items() for k in d],
)
def test_example_mentions_every_default_key(section, key, example_text):
    """Every default must appear, set or commented out.

    Credentials and paths are deliberately left commented in the example, so
    presence of the name is the bar rather than an active assignment.
    """
    assert key in example_text, (
        f"{section}.{key} is a default but never appears in "
        f"example.config.toml — a user cannot discover it")


def test_example_keeps_its_documentation(example_text):
    """The example earns its keep through comments; guard against regeneration."""
    comments = sum(1 for line in example_text.splitlines()
                   if line.strip().startswith("#"))
    assert comments > 100, f"only {comments} comment lines left"


# ── The generated default ─────────────────────────────────────────────────────

def test_generated_default_covers_every_section():
    """edld.py builds a config from the defaults when none exists.

    It previously omitted CAPI, Colonisation and SessionMgmt.
    """
    source = (ROOT / "edld.py").read_text(encoding="utf-8")
    start = source.index("_default_cfg = {")
    # The first "}" belongs to a nested dict literal, so match braces.
    depth, end = 0, start
    for end in range(start, len(source)):
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
            if depth == 0:
                break
    block = source[start:end + 1]
    for section in ("Settings", "Discord", "UI", "LogLevels", "EDDN", "EDSM",
                    "EDAstro", "Inara", "CAPI", "Colonisation", "SessionMgmt"):
        assert f'"{section}"' in block, (
            f"generated default config omits [{section}]")


# ── Backfill ──────────────────────────────────────────────────────────────────

MINIMAL = """\
[Settings]
UseUTC = false

[LogLevels]
Died = 3

[EDP1]
Settings.UseUTC = true
Discord.WebhookURL = "https://example.invalid/hook"
"""


def _write(tmp_path, text) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_backfill_adds_missing_keys(tmp_path):
    p = _write(tmp_path, MINIMAL)
    added = backfill_config_defaults(p)
    assert any(a.startswith("LogLevels.") for a in added)
    parsed = tomllib.loads(p.read_text(encoding="utf-8"))
    for key in C.CFG_DEFAULTS_NOTIFY:
        assert key in parsed["LogLevels"]


def test_backfill_is_idempotent(tmp_path):
    p = _write(tmp_path, MINIMAL)
    backfill_config_defaults(p)
    assert backfill_config_defaults(p) == []


def test_backfill_never_changes_an_existing_value(tmp_path):
    p = _write(tmp_path, MINIMAL)
    backfill_config_defaults(p)
    parsed = tomllib.loads(p.read_text(encoding="utf-8"))
    assert parsed["LogLevels"]["Died"] == 3
    assert parsed["Settings"]["UseUTC"] is False


def test_backfill_leaves_profiles_alone(tmp_path):
    """A profile is a sparse override; filling it in would defeat the point."""
    p = _write(tmp_path, MINIMAL)
    before = tomllib.loads(p.read_text(encoding="utf-8"))["EDP1"]
    backfill_config_defaults(p)
    after = tomllib.loads(p.read_text(encoding="utf-8"))["EDP1"]
    assert before == after


def test_backfill_skips_credentials_and_paths(tmp_path):
    """Writing ApiKey = "" into someone's config is noise, not help."""
    p = _write(tmp_path, MINIMAL)
    added = backfill_config_defaults(p)
    for name in ("ApiKey", "WebhookURL", "JournalFolder", "CommanderName",
                 "RemoteKillHost", "UploaderID"):
        assert not any(a.endswith("." + name) for a in added), name


def test_backfill_does_not_invent_absent_sections(tmp_path):
    p = _write(tmp_path, MINIMAL)
    backfill_config_defaults(p)
    parsed = tomllib.loads(p.read_text(encoding="utf-8"))
    assert "EDSM" not in parsed
    assert "Inara" not in parsed


def test_backfill_preserves_comments(tmp_path):
    """The example is a commented reference; a rewrite would destroy it."""
    text = "# leading note\n[LogLevels]\n# why Died is 3\nDied = 3\n"
    p = _write(tmp_path, text)
    backfill_config_defaults(p)
    out = p.read_text(encoding="utf-8")
    assert "# leading note" in out
    assert "# why Died is 3" in out


def test_backfill_output_still_parses(tmp_path, example_text):
    """Run it against the real example file, comments and profiles and all."""
    p = _write(tmp_path, example_text)
    backfill_config_defaults(p)
    parsed = tomllib.loads(p.read_text(encoding="utf-8"))
    assert "LogLevels" in parsed and "Settings" in parsed


def test_backfill_on_a_missing_file_is_harmless(tmp_path):
    assert backfill_config_defaults(tmp_path / "nope.toml") == []


def test_backfill_clears_the_startup_warnings(tmp_path):
    """The user-visible symptom: a warning per missing key on every launch."""
    p = _write(tmp_path, MINIMAL)
    backfill_config_defaults(p)
    parsed = tomllib.loads(p.read_text(encoding="utf-8"))
    missing = [k for k in C.CFG_DEFAULTS_NOTIFY if k not in parsed["LogLevels"]]
    assert not missing


# ── Carrier jump levels specifically ──────────────────────────────────────────

@pytest.mark.parametrize("key", ["CarrierJumpScheduled", "CarrierJumpCancelled",
                                 "CarrierJumpComplete"])
def test_carrier_jump_levels_exist_and_are_documented(key, example_text):
    assert key in C.CFG_DEFAULTS_NOTIFY
    assert key in example_text
