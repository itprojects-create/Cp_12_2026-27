"""Proposal schema: allowlisted kinds only (prereg §1). Parse rejects the rest."""
from __future__ import annotations

from dataclasses import dataclass

ALLOWLIST = ("veto_band_edge", "topK_value", "blackout_window")

_VETO_LEVELS = (0.25, 0.5, 0.75, 1.0)
_TOPK = (30, 50, 70)


def _grid(v: float) -> bool:
    return 0.1 <= v <= 0.9 and abs(v * 20 - round(v * 20)) < 1e-9


@dataclass(frozen=True)
class Proposal:
    kind: str
    params: dict
    rationale: str = ""

    def validate(self) -> "Proposal":
        if self.kind not in ALLOWLIST:
            raise ValueError(f"kind {self.kind!r} not allowlisted — rejected, never evaluated")
        p = self.params
        if self.kind == "veto_band_edge":
            for k in ("band_lo", "band_hi", "veto"):
                if k not in p:
                    raise ValueError(f"veto_band_edge missing {k}")
            if not (_grid(p["band_lo"]) and _grid(p["band_hi"]) and p["band_lo"] < p["band_hi"]):
                raise ValueError("band edges must be on 0.05 grid in [0.1,0.9], lo < hi")
            if p["veto"] not in _VETO_LEVELS:
                raise ValueError("veto must be one of {0.25,0.5,0.75,1.0}")
            if str(p.get("regime", "ANY")) not in ("ANY", "CALM", "ELEVATED", "STRESSED"):
                raise ValueError("bad regime cell")
            if str(p.get("breadth", "ANY")) not in ("ANY", "low", "mid", "high"):
                raise ValueError("bad breadth cell")
        elif self.kind == "topK_value":
            if p.get("K") not in _TOPK:
                raise ValueError("K must be one of {30,50,70}")
        elif self.kind == "blackout_window":
            if not (isinstance(p.get("pre"), int) and 0 <= p["pre"] <= 5):
                raise ValueError("pre must be int in [0,5]")
            if not (isinstance(p.get("post"), int) and 0 <= p["post"] <= 3):
                raise ValueError("post must be int in [0,3]")
        if not self.rationale or len(self.rationale) > 500:
            raise ValueError("rationale required, 1..500 chars (falsifier statement)")
        return self


def parse(kind: str, params: dict, rationale: str = "") -> Proposal:
    return Proposal(kind=kind, params=params, rationale=rationale).validate()
