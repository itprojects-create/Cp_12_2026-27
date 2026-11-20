"""Policy genomes: mutation ONLY inside preregistered ranges (prereg_evo_founders.md §1).

A genome is pure data (no code, no prompts) so every variant is auditable and
reproducible. v4-as-shipped == {50, 1.0, on, 1.0, 0.015}.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

GENOME_RANGES = {
    "topK": (30, 50, 70),
    "veto_strictness": (0.5, 1.0, 2.0),
    "vix_gate": ("on", "off"),
    "gross_cap": (0.5, 1.0),
    "turnover_delta": (0.010, 0.015, 0.020),
}
GENE_ORDER = ("topK", "veto_strictness", "vix_gate", "gross_cap", "turnover_delta")

# F4 control arm: v3 target pipeline (no rank cut) with veto disabled.
V3_NO_TOPK = "v3_no_topk"


@dataclass(frozen=True)
class Genome:
    topK: int = 50
    veto_strictness: float = 1.0
    vix_gate: str = "on"
    gross_cap: float = 1.0
    turnover_delta: float = 0.015
    veto_off: bool = False  # F4 control only; never arises by mutation

    def validate(self) -> "Genome":
        for gene in GENE_ORDER:
            if getattr(self, gene) not in GENOME_RANGES[gene]:
                raise ValueError(f"gene {gene}={getattr(self, gene)!r} outside prereg range")
        if not isinstance(self.veto_off, bool):
            raise ValueError("veto_off must be bool")
        return self

    def diff_genes(self, other: "Genome") -> list[str]:
        a, b = asdict(self), asdict(other)
        return sorted(k for k in a if a[k] != b[k])


FOUNDERS: tuple[tuple[str, Genome], ...] = (
    ("F1-v4-as-shipped", Genome(50, 1.0, "on", 1.0, 0.015)),
    ("F2-narrow-focus", Genome(30, 1.0, "on", 1.0, 0.015)),
    ("F3-wide-net", Genome(70, 1.0, "on", 1.0, 0.015)),
    ("F4-v3-narrow-control", Genome(50, 1.0, "on", 1.0, 0.015, veto_off=True)),
    ("F5-no-vix", Genome(50, 1.0, "off", 1.0, 0.015)),
    ("F6-strict-veto", Genome(50, 2.0, "on", 1.0, 0.015)),
    ("F7-loose-veto", Genome(50, 0.5, "on", 1.0, 0.015)),
    ("F8-low-gross", Genome(50, 1.0, "on", 0.5, 0.020)),
)


def mutate(parent: Genome, max_children: int = 2) -> list[Genome]:
    """Single-gene steps to adjacent allowed values (prereg §1). veto_off never
    arises by mutation (control arm is born, not bred). Deterministic order."""
    parent.validate()
    kids: list[Genome] = []
    base = asdict(parent)
    base["veto_off"] = False
    for gene in GENE_ORDER:
        allowed = GENOME_RANGES[gene]
        i = allowed.index(base[gene])
        for j in (i - 1, i + 1):
            if 0 <= j < len(allowed):
                g = dict(base)
                g[gene] = allowed[j]
                kid = Genome(**g).validate()
                if kid not in kids and kid != parent:
                    kids.append(kid)
            if len(kids) >= max_children:
                return kids
    return kids


def breadth_bucket(breadth: float) -> str:
    """Regime-fingerprint axis: low <0.40, mid, high >0.60 (matches veto table)."""
    if breadth < 0.40:
        return "low"
    if breadth > 0.60:
        return "high"
    return "mid"


def fingerprint(vix_regime: str, trend: str, breadth: float) -> str:
    return f"{vix_regime}|{trend}|{breadth_bucket(breadth)}"
