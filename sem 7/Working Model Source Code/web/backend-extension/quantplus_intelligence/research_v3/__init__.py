"""Quant Plus V3.1 research plane: read-only evidence, versioned economics, falsifiable runs.

W0 scope (per QUANTPLUS_V3_1_UNIFIED_RECOVERY_BLUEPRINT §14):
- economics: integer-paise fee adapter mirroring the tested web paper book
  (src/lib/paper-fees.ts) and versioned return metrics that keep benchmark-relative
  excess separate from absolute net cash P&L.
Later modules (warehouse, runner, challenger, ...) are added with their waves only;
nothing here mutates accounts, risk limits or broker endpoints.
"""
