"""Layered memory + calibration for veto context (NEWW_PLAN Day 3).

FinMem-adapted with PIT discipline: every recall filters available_at <= as_of,
every training row comes from settled (realized) outcomes only.
Prereg: data/prereg_day3_memory_calibration.md — thresholds change by amendment only.
"""
from __future__ import annotations
