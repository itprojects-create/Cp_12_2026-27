"""Pytest safety plugin for a full service-suite run without provider traffic.

Exactly one known live-network test is marked skipped.  No other node is
filtered, selected, monkeypatched or reclassified.
"""
from __future__ import annotations

import pytest


LIVE_NODE = "tests/test_technical.py::test_technical_pit_live"


def pytest_collection_modifyitems(config, items):
    del config
    for item in items:
        if item.nodeid == LIVE_NODE:
            item.add_marker(pytest.mark.skip(
                reason="W5 offline verification: live provider calls prohibited"))
