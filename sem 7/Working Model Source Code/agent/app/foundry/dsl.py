"""Constrained Strategy DSL (migration §6).

LLMs never emit executable code into the trading system. They emit DSL
programs — data — which compile into deterministic callables. Anything outside
the allowlist (arbitrary code, I/O, orders, leverage/risk overrides) fails at
parse time. Every compiled program has a stable fingerprint (§7).

Row context (deterministic dict supplied by the evaluator):
  regime, breadth (low|mid|high), veto_raw, ret_5d, dist_high, price, volume,
  delivery_z, blackout (bool), plus any feature the RANK op reads.

Compiled evaluation yields an overlay (never an order):
  {"veto": [0,1], "pass": bool, "weight_mult": (0,1], "rank_score": float,
   "caps": [...], "holds": {...}}
WEIGHT_TRANSFORM multipliers are capped at 1.0 at compile time (R2: the DSL
cannot upsize, by construction, not by convention).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.research.fingerprints import strategy_logic_fingerprint

ALLOWED_OPS = (
    "RANK", "FILTER", "VETO", "REGIME_FILTER", "UNIVERSE_FILTER",
    "ENTRY_FILTER", "EXIT_FILTER", "WEIGHT_TRANSFORM", "RISK_CAP",
    "EXPOSURE_CAP", "TURNOVER_LIMIT", "MIN_HOLD", "MAX_HOLD", "VOL_TARGET",
    "LIQUIDITY_FILTER", "EVENT_BLACKOUT", "ENSEMBLE_WEIGHT",
)

REJECTED_OPS = (
    "EXECUTE_ARBITRARY_CODE", "IMPORT_MODULE", "NETWORK_ACCESS",
    "FILE_WRITE", "SHELL_COMMAND", "DYNAMIC_EVAL", "DIRECT_ORDER",
    "LEVERAGE_OVERRIDE", "RISK_OVERRIDE",
)

_FILTER_OPS = ("FILTER", "REGIME_FILTER", "UNIVERSE_FILTER", "ENTRY_FILTER",
               "EXIT_FILTER", "LIQUIDITY_FILTER")


def _cell_ok(params: dict, row: dict) -> bool:
    if params.get("regime", "ANY") != "ANY" and row.get("regime") != params["regime"]:
        return False
    if params.get("breadth", "ANY") != "ANY" and row.get("breadth") != params["breadth"]:
        return False
    return True


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(f"DSL rejected: {msg}")


def validate_op(op: dict) -> dict:
    """Parse + validate one op. Returns normalized op. Raises on anything
    outside the allowlist or any out-of-range param."""
    if not isinstance(op, dict) or "op" not in op:
        raise ValueError("DSL rejected: op must be {op, params}")
    name = op["op"]
    if name in REJECTED_OPS or (name not in ALLOWED_OPS):
        raise ValueError(f"DSL rejected: op {name!r} is not allowlisted — never evaluated")
    p = dict(op.get("params", {}))
    if name == "RANK":
        _check(p.get("feature"), "RANK needs feature")
        _check(p.get("direction", "high") in ("high", "low"), "RANK direction high|low")
    elif name == "VETO":
        for k in ("band_lo", "band_hi", "veto"):
            _check(k in p, f"VETO missing {k}")
        _check(0.0 <= p["band_lo"] < p["band_hi"] <= 1.0, "VETO band in [0,1], lo<hi")
        _check(p["veto"] in (0.25, 0.5, 0.75, 1.0), "VETO veto in {0.25,0.5,0.75,1.0}")
        _check(str(p.get("regime", "ANY")) in ("ANY", "CALM", "ELEVATED", "STRESSED"),
               "VETO bad regime cell")
        _check(str(p.get("breadth", "ANY")) in ("ANY", "low", "mid", "high"),
               "VETO bad breadth cell")
    elif name in _FILTER_OPS:
        _check("field" in p and "op" in p and "value" in p,
               f"{name} needs {{field, op, value}}")
        _check(p["op"] in ("gt", "gte", "lt", "lte", "eq", "neq"),
               f"{name} bad comparator")
    elif name == "WEIGHT_TRANSFORM":
        _check("mult" in p, "WEIGHT_TRANSFORM needs mult")
        _check(0.0 < p["mult"] <= 1.0,
               "WEIGHT_TRANSFORM mult must be in (0,1] — the DSL cannot upsize (R2)")
    elif name in ("RISK_CAP", "EXPOSURE_CAP"):
        _check("cap" in p and 0.0 < p["cap"] <= 1.0, f"{name} cap must be in (0,1]")
    elif name == "TURNOVER_LIMIT":
        _check("delta" in p and 0.0 < p["delta"] <= 0.10, "TURNOVER_LIMIT delta in (0,0.10]")
    elif name in ("MIN_HOLD", "MAX_HOLD"):
        _check(isinstance(p.get("days"), int) and p["days"] >= 0, f"{name} days int >= 0")
    elif name == "VOL_TARGET":
        _check("target" in p and 0.0 < p["target"] <= 0.50, "VOL_TARGET in (0,0.50]")
    elif name == "EVENT_BLACKOUT":
        _check(isinstance(p.get("pre"), int) and 0 <= p["pre"] <= 5, "EVENT_BLACKOUT pre 0..5")
        _check(isinstance(p.get("post"), int) and 0 <= p["post"] <= 3, "EVENT_BLACKOUT post 0..3")
    elif name == "ENSEMBLE_WEIGHT":
        _check("weight" in p and 0.0 <= p["weight"] <= 1.0, "ENSEMBLE_WEIGHT in [0,1]")
    return {"op": name, "params": p}


def validate_program(program: dict) -> dict:
    if not isinstance(program, dict) or not program.get("ops"):
        raise ValueError("DSL rejected: program needs a non-empty ops list")
    if len(program["ops"]) > 64:
        raise ValueError("DSL rejected: >64 ops (complexity cap)")
    return {"ops": [validate_op(o) for o in program["ops"]]}


def _cmp(op: str, a: float, b: float) -> bool:
    return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b,
            "eq": a == b, "neq": a != b}[op]


@dataclass(frozen=True)
class CompiledStrategy:
    ops: tuple
    fingerprint: str

    def evaluate_row(self, row: dict) -> dict:
        """Deterministic row overlay. Pure function of (ops, row)."""
        out = {"veto": 0.0, "pass": True, "weight_mult": 1.0,
               "rank_score": 0.0, "caps": [], "holds": {}}
        for op in self.ops:
            name, p = op["op"], op["params"]
            if name == "VETO":
                if _cell_ok(p, row) and p["band_lo"] <= row.get("veto_raw", -1) < p["band_hi"]:
                    out["veto"] = max(out["veto"], float(p["veto"]))
            elif name in _FILTER_OPS:
                if _cell_ok(p, row):
                    try:
                        ok = _cmp(p["op"], float(row.get(p["field"], float("nan"))),
                                  float(p["value"]))
                    except (TypeError, ValueError):
                        ok = False  # missing/non-numeric field fails closed (§25)
                    out["pass"] = out["pass"] and ok
            elif name == "RANK":
                try:
                    v = float(row.get(p["feature"], 0.0))
                except (TypeError, ValueError):
                    v = 0.0
                out["rank_score"] = v if p.get("direction", "high") == "high" else -v
            elif name == "WEIGHT_TRANSFORM":
                out["weight_mult"] = min(out["weight_mult"], float(p["mult"]))
            elif name in ("RISK_CAP", "EXPOSURE_CAP", "VOL_TARGET", "TURNOVER_LIMIT",
                          "ENSEMBLE_WEIGHT"):
                out["caps"].append({"op": name, **p})
            elif name in ("MIN_HOLD", "MAX_HOLD"):
                out["holds"][name] = p["days"]
            elif name == "EVENT_BLACKOUT":
                if row.get("blackout", False):
                    out["pass"] = False
        out["weight_mult"] = min(1.0, max(0.0, out["weight_mult"]))
        out["veto"] = min(1.0, max(0.0, out["veto"]))
        return out


def compile_program(program: dict) -> CompiledStrategy:
    """Validate + compile. Raises on anything unallowlisted. Fingerprint is
    stable: identical programs -> identical fingerprints."""
    norm = validate_program(program)
    ops = tuple((o["op"], tuple(sorted(o["params"].items()))) for o in norm["ops"])
    return CompiledStrategy(ops=tuple(norm["ops"]),
                            fingerprint=strategy_logic_fingerprint(norm))


def from_foundry_proposal(proposal) -> dict:
    """Adapt existing allowlisted foundry kinds into DSL programs (§2 bridge).
    proposal: foundry Proposal (kind/params). Returns a DSL program dict."""
    kind, p = proposal.kind, proposal.params
    if kind == "veto_band_edge":
        return {"ops": [{"op": "VETO", "params": {
            "band_lo": p["band_lo"], "band_hi": p["band_hi"], "veto": p["veto"],
            "regime": p.get("regime", "ANY"), "breadth": p.get("breadth", "ANY")}}]}
    if kind == "topK_value":
        return {"ops": [{"op": "RANK", "params": {"feature": "momentum_60",
                                                  "direction": "high",
                                                  "top_k": p["K"]}}]}
    if kind == "blackout_window":
        return {"ops": [{"op": "EVENT_BLACKOUT",
                         "params": {"pre": p["pre"], "post": p["post"]}}]}
    raise ValueError(f"no DSL mapping for kind {kind!r}")
