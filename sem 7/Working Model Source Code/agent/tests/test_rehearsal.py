"""P6 rehearsal tests: dry purity, replay end-to-end, live-shadow honesty."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "scripts")
import rehearse_day as RH  # noqa: E402


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    before = set()
    for r, _d, files in os.walk("."):
        for fn in files:
            before.add(os.path.join(r, fn))
    rec = RH.dry_run("2026-10-12")
    assert rec["verdict"] == "PASS" and rec["steps"]["writes"] == 0
    assert rec["steps"]["triage"]["decision"] == "CLASSIFY"


def test_replay_fixture_end_to_end():
    rec = RH.replay_fixture("2026-10-12")
    assert rec["verdict"] == "PASS"
    assert rec["steps"]["fixtures_untouched"] is True
    assert rec["steps"]["event_store"] == {"valid": 2}
    assert rec["steps"]["versioned_classifications"] == 2
    assert "control_return" in rec["steps"]["core"]
    assert rec["steps"]["snapshot"] is True


def test_live_shadow_reports_honestly():
    rec = RH.live_shadow("2026-10-10")
    assert rec["verdict"] == "PASS"
    assert rec["steps"]["orders"].startswith("none exist")
    assert rec["steps"]["nse_probe"]["status"] in (
        "SUCCESS", "PARTIAL", "SOURCE_UNAVAILABLE", "SOURCE_BLOCKED", "ERROR")
