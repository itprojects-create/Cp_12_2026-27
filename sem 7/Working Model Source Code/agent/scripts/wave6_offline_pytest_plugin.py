"""Wave 6 full-service verification policy: one known live test is skipped.

No test is deselected, monkeypatched, xfailed, or reclassified. The plugin is
copied into the service repo so production verification never imports a script
from the development checkout.
"""
from __future__ import annotations

import pytest

LIVE_NODE = "tests/test_technical.py::test_technical_pit_live"


def pytest_collection_modifyitems(config, items):
    del config
    for item in items:
        if item.nodeid == LIVE_NODE:
            item.add_marker(pytest.mark.skip(
                reason="W6 offline verification: live provider/model calls prohibited"))
