"""
tests/test_release_workflow.py — the release workflow builds from any branch.

A manual run (workflow_dispatch) on dev built every binary and then failed all
three smoke tests: the workflow's VERSION is the ref name, which on a branch is
"dev", and the binary — correctly — reported the version file. Every job that
names or checks a version now takes it from the verify job, which reads the
version file; these pin that, and the check that stops a release shipping a
sheet manifest built for another version.

Read as text rather than parsed, so the test needs nothing beyond the standard
library.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


def _jobs() -> dict[str, str]:
    body = WORKFLOW.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([A-Za-z_][\w-]*):\s*$", body, flags=re.M)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}


def test_every_job_that_uses_the_version_takes_it_from_the_version_file():
    jobs = _jobs()
    users = [name for name, text in jobs.items() if "env.VERSION" in text]
    assert users, "no job uses env.VERSION — has the workflow changed shape?"
    for name in users:
        text = jobs[name]
        assert re.search(r"^    env:\n(?:      .*\n)*?      VERSION: \$\{\{ needs\.verify\.outputs\.version \}\}",
                         text, re.M), (
            f"job {name!r} uses env.VERSION but does not set it from "
            f"needs.verify.outputs.version; on a branch run it would be the branch name")
        needs = re.search(r"^    needs: \[([^\]]*)\]", text, re.M)
        assert needs and "verify" in needs.group(1), (
            f"job {name!r} must list verify in needs to read its output")


def test_a_manual_run_can_build_a_branch_without_publishing():
    assert re.search(r"^  workflow_dispatch:\n    inputs:\n      dry_run:", WORKFLOW, re.M)
    publish = _jobs()["release"]
    assert "github.ref_type == 'tag' && !inputs.dry_run" in publish


def test_verify_refuses_a_stale_sheet_bundle():
    assert "python3 sheets/build_bundle.py --check" in _jobs()["verify"]
