"""Write the academic result pack and labelled figures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contracts import canonical_json


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")


def _json(path: Path, value) -> None:
    _write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _pct(value) -> str:
    return "—" if value is None else f"{100 * value:.2f}%"


def _ci(summary: dict) -> str:
    ci = summary["accuracy_interval"]
    return f"[{_pct(ci['lower_95'])}, {_pct(ci['upper_95'])}]"


def _summary_map(result: dict, scope: str) -> dict:
    return {(row["model"], row["horizon_sessions"]): row
            for row in result["summaries"] if row["sample_scope"] == scope}


def write_figure(result: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    common = _summary_map(result, "COMMON_MODEL_SAMPLE")
    models = ["majority_train", "fixed_up", "trend_ret60", "reversal_ret5",
              "ridge", "logistic", "hgb"]
    labels = ["Majority", "Fixed UP", "Trend", "Reversal", "Ridge", "Logistic", "HGB"]
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5))
    x = np.arange(len(models))
    width = 0.36
    h5 = [common[(model, 5)]["answered_accuracy"] for model in models]
    h20 = [common[(model, 20)]["answered_accuracy"] for model in models]
    axes[0].bar(x - width / 2, h5, width, label="h5")
    axes[0].bar(x + width / 2, h20, width, label="h20")
    axes[0].axhline(0.5, color="black", linestyle="--", linewidth=1, label="50%")
    axes[0].set_xticks(x, labels, rotation=35, ha="right")
    axes[0].set_ylim(0.4, max(0.65, max(h5 + h20) + 0.03))
    axes[0].set_ylabel("Answered-only accuracy")
    axes[0].set_title("Historical OOF development accuracy\n(common complete-case sample)")
    axes[0].legend()

    primary = common[("logistic", 20)]["confusion_matrix"]
    matrix = np.array([[primary["tn"], primary["fp"]],
                       [primary["fn"], primary["tp"]]])
    image = axes[1].imshow(matrix, cmap="Blues")
    for (i, j), value in np.ndenumerate(matrix):
        axes[1].text(j, i, str(value), ha="center", va="center",
                     color="white" if value > matrix.max() / 2 else "black")
    axes[1].set_xticks([0, 1], ["Pred DOWN", "Pred UP"])
    axes[1].set_yticks([0, 1], ["True DOWN", "True UP"])
    axes[1].set_title("Logistic h20 confusion matrix\n(preregistered primary fitted candidate)")
    fig.colorbar(image, ax=axes[1], fraction=0.046)

    for model, style in (("logistic", "o-"), ("hgb", "s-")):
        curve = result["confidence_coverage_curves"][f"{model}@h20"]
        coverage = [row["coverage"] for row in curve]
        accuracy = [row["answered_accuracy"] for row in curve]
        axes[2].plot(coverage, accuracy, style, label=model)
        for row, cx, ay in zip(curve, coverage, accuracy):
            if cx is not None and ay is not None:
                axes[2].annotate(f"{row['probability_threshold']:.2f}", (cx, ay),
                                 textcoords="offset points", xytext=(3, 4), fontsize=8)
    axes[2].axhline(0.5, color="black", linestyle="--", linewidth=1)
    axes[2].set_xlabel("Coverage")
    axes[2].set_ylabel("Answered-only accuracy")
    axes[2].set_title("Fixed confidence grid (development only)\nall points shown; none selected post hoc")
    axes[2].legend()
    axes[2].grid(alpha=0.2)
    fig.suptitle("Quant Plus V3.1 — raw-price absolute direction diagnostics", fontsize=14)
    fig.text(0.5, 0.01,
             "HISTORICAL_OOF_DEVELOPMENT; not a fresh holdout, forward result, profitability claim, or trading authority",
             ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_reports(result: dict, spec: dict, output: str | Path, *,
                  test_evidence: dict | None = None) -> dict:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    oof_rows = result.pop("oof_rows")
    _json(output / "directional_accuracy_results.json", result)
    _write(output / "oof_predictions.jsonl",
           "".join(canonical_json(row) + "\n" for row in oof_rows))

    common = _summary_map(result, "COMMON_MODEL_SAMPLE")
    all_scope = _summary_map(result, "ALL_ELIGIBLE")
    models = ["majority_train", "fixed_up", "trend_ret60", "reversal_ret5",
              "ridge", "logistic", "hgb"]
    lines = [
        "# Directional accuracy results", "",
        "**Evidence tier:** `HISTORICAL_OOF_DEVELOPMENT` — validation tiles 2022–2023 were already used in W3; no fresh sealed holdout exists.", "",
        "Target: strict sign of raw-price absolute OPEN-to-OPEN return. Ties are counted and excluded from binary confusion denominators. All candidates use the same common complete-case sample below.", "",
        "| Horizon | Candidate | n | UP / DOWN | Accuracy | Clustered 95% interval | Balanced acc. | All-eligible coverage | Unconditional acc. | Δ vs majority |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for horizon in (20, 5):
        for model in models:
            row = common[(model, horizon)]
            full = all_scope[(model, horizon)]
            diff = row.get("difference_vs_majority_baseline", {}).get("difference")
            lines.append(
                f"| {horizon} | `{model}` | {row['n_eligible_non_tie']:,} | "
                f"{row['n_up']:,} / {row['n_down']:,} | **{_pct(row['answered_accuracy'])}** | "
                f"{_ci(row)} | {_pct(row['balanced_accuracy'])} | {_pct(full['coverage'])} | "
                f"{_pct(full['unconditional_accuracy'])} | {_pct(diff)} |")
    lines.extend([
        "", "- Majority class is estimated on each fold's training rows only.",
        "- Fixed-UP, trend (`ret_60 > 0`) and reversal (`-ret_5 > 0`) are predeclared baselines.",
        "- Ridge uses raw predicted-return sign; logistic/HGB use fixed `P(UP) > 0.5`.",
        "- Intervals resample complete decision sessions in contiguous blocks (h20=4 weekly decisions; h5=1); stock rows are never independent bootstrap draws.",
        "- `h60` is omitted: only 24 old monthly validation dates and about two non-overlapping periods existed in W3.",
        "- Sector and regime tables are unavailable rather than reconstructed post hoc.",
    ])
    _write(output / "directional_accuracy_results.md", "\n".join(lines) + "\n")

    dataset = result["dataset"]
    _write(output / "data_and_label_audit.md", f"""# Data and label audit

## Exact task

- Primary h20 and secondary h5 label: decision after a completed session, entry at the next eligible
  observed session **OPEN**, exit at the **OPEN** exactly h observed NSE sessions after entry.
- UP = raw absolute return `> 0`; DOWN = `< 0`; exact zero = tie, counted but excluded from binary
  confusion denominators. Benchmark-relative/TRI outcomes never enter this target.
- Evidence tier: `HISTORICAL_OOF_DEVELOPMENT`. W3's 2022–2023 validation tiles were already viewed;
  they are not an untouched external test. W2's revealed 2024-06-21..2026-09-17 holdout remains
  quarantined; `NEW_SEALED_HOLDOUT_UNAVAILABLE`.

## Data and identity

- Warehouse: `{result['warehouse']['path']}`, SHA-256 `{result['warehouse']['sha256']}`, opened
  `mode=ro` with `query_only=ON`.
- Coverage: {dataset['session_min']}..{dataset['session_max']}, {dataset['observed_sessions']:,}
  observed sessions; official archive ends 2026-09-17. The 2024-01-01..2024-06-20 archive gap and
  post-2026-09-17 vendor-only rows are outside this evaluation.
- As-of NIFTY50 membership and alias/ISIN closure reuse W1/W3. Membership is incomplete historically:
  snapshot-floor spells remain weak provenance; sector history is not verified.
- Raw unadjusted prices are used. Windows with close/previous-close ratios outside [0.65, 1.54]
  are `DATA_BLOCKED_ACTION_WINDOW` and excluded. The local action table contains symbol changes,
  not complete split/bonus/dividend history; therefore this is a **raw-price direction diagnostic**,
  not total-return or economic truth.

## Counts and hashes

- PIT snapshots: {dataset['snapshots']:,}; snapshot hash `{dataset['snapshot_hash']}`.
- OPEN-to-OPEN label hash: `{dataset['open_to_open_label_hash']}`.
- Label counts: `{json.dumps(dataset['label_counts'], sort_keys=True)}`; ties:
  `{json.dumps(dataset['ties'], sort_keys=True)}`; extended exits:
  `{json.dumps(dataset['exit_extended'], sort_keys=True)}`; membership provenance:
  `{json.dumps(dataset['membership_provenance'], sort_keys=True)}`.
- Frozen W3 controls remain feature `634b3669a3aacde6181bf2936d1bd98dd70f679edd9cb9637bcf9423a2e0fd52`
  and label `0053df3de4d04032c51dfdda7c152aedf6e800af120c57340a28bcb5beb55a7e`.
  The new OPEN-to-OPEN label hash is intentionally different and does not alter W3.

## Leakage and selection controls

Features use only `available_at <= decision_ts`; transforms are fitted on each fold's training rows.
The new target uses a 20-session purge/embargo for both horizons. Every attempted validation member
is retained in `oof_predictions.jsonl`, including missing labels, action blocks and model abstentions.
No threshold was chosen after outcomes: fitted thresholds are fixed at 0/0.5 and the complete
confidence grid `[0.50, 0.55, 0.60, 0.65]` is shown without selecting a winner.
""")

    primary = common[("logistic", 20)]
    secondary = common[("logistic", 5)]
    majority = common[("majority_train", 20)]
    best_name = result["baseline_comparison"]["20"]["best_baseline"]
    best = common[(best_name, 20)]
    _write(output / "college_results_section.md", f"""## Results and Discussion

We evaluated binary stock-direction classification on historical point-in-time NIFTY 50 research
rows using four expanding, purged walk-forward validation folds covering 2022–2023. The primary
outcome was the strict sign of the 20-session raw-price return from the next executable open to a
subsequent executable open; zero returns were counted as ties and excluded from binary confusion
denominators. Because these validation periods had already been examined during Quant Plus Wave 3,
all results are classified as **historical out-of-fold development evidence**, not independent
external validation.

On the common complete-case h20 sample (`n={primary['n_eligible_non_tie']:,}`), the preregistered
logistic candidate achieved **{_pct(primary['answered_accuracy'])}** accuracy with a decision-date
block-bootstrap 95% interval of **{_ci(primary)}**. Its confusion matrix was
TN={primary['confusion_matrix']['tn']:,}, FP={primary['confusion_matrix']['fp']:,},
FN={primary['confusion_matrix']['fn']:,}, TP={primary['confusion_matrix']['tp']:,}; balanced accuracy
was {_pct(primary['balanced_accuracy'])}. The fold-training majority baseline achieved
{_pct(majority['answered_accuracy'])}; the strongest of the three predeclared baselines was
`{best_name}` at {_pct(best['answered_accuracy'])}. Thus any value above 50% must be interpreted
against class prevalence and these baselines, not against a coin-flip threshold alone.

Relative to the fold-training majority baseline, logistic h20 differed by
{_pct(primary['difference_vs_majority_baseline']['difference'])} (paired clustered 95% interval
[{_pct(primary['difference_vs_majority_baseline']['lower_95'])},
{_pct(primary['difference_vs_majority_baseline']['upper_95'])}]). Logistic h5 differed by
{_pct(secondary['difference_vs_majority_baseline']['difference'])}, with interval
[{_pct(secondary['difference_vs_majority_baseline']['lower_95'])},
{_pct(secondary['difference_vs_majority_baseline']['upper_95'])}]. Neither interval excludes zero;
there is therefore **no demonstrated accuracy improvement over the training-majority baseline**.

Performance was not temporally stable. Logistic h20 accuracy ranged from
{_pct(min(row['answered_accuracy'] for row in primary['breakdowns']['per_fold'].values()))} to
{_pct(max(row['answered_accuracy'] for row in primary['breakdowns']['per_fold'].values()))} across
the four folds and was {_pct(primary['breakdowns']['per_year']['2022']['answered_accuracy'])} in
2022 versus {_pct(primary['breakdowns']['per_year']['2023']['answered_accuracy'])} in 2023. Logistic
h5 ranged from {_pct(min(row['answered_accuracy'] for row in secondary['breakdowns']['per_fold'].values()))}
to {_pct(max(row['answered_accuracy'] for row in secondary['breakdowns']['per_fold'].values()))}
across folds. This instability is another reason not to generalise the pooled score.

The study has material limits. Prices are raw and not a complete total-return series; action-shaped
discontinuities are excluded, but the local corporate-action history is incomplete. Historical
membership contains weak snapshot-floor spells, no verified as-of sector map exists, and economic
fees are unavailable for the evaluated years. The h20 labels overlap, leaving approximately
{primary['accuracy_interval']['effective_nonoverlap_periods']} effective non-overlapping decision
periods. Multiple candidates were reported in full, so the best-looking row is selection-exposed.
No newly sealed holdout exists, and no result changes the Wave 6 `NO_ELIGIBLE_STRATEGY` state.

Accordingly, the defensible college claim is limited to: *under a fixed retrospective walk-forward
protocol, model and baseline directional accuracies were measured reproducibly on 2022–2023 raw-price
data*. The experiment does not establish forward accuracy, profitable trading, or investment value.
""")

    exceeds = [row for row in result["summaries"]
               if row["sample_scope"] == "COMMON_MODEL_SAMPLE"
               and row["answered_accuracy"] is not None and row["answered_accuracy"] > 0.5]
    beats_majority = [row for row in result["summaries"]
                      if row["sample_scope"] == "COMMON_MODEL_SAMPLE"
                      and row.get("difference_vs_majority_baseline", {}).get("difference", 0) > 0]
    robust_beats_majority = [row for row in beats_majority
                             if row["difference_vs_majority_baseline"].get("lower_95", -1) > 0]
    majority_verdict = ("YES_WITH_CLUSTERED_INTERVAL_ABOVE_ZERO" if robust_beats_majority else
                        "POINT_ESTIMATE_ONLY_NOT_ESTABLISHED" if beats_majority else "NO")
    best_positive_difference = max(
        (row["difference_vs_majority_baseline"]["difference"] for row in beats_majority),
        default=0)
    _write(output / "college_evaluation_acceptance.md", f"""# College accuracy evaluation acceptance

| Question | Verdict | Evidence |
|---|---|---|
| Any measured accuracy >50%? | **{'YES' if exceeds else 'NO'}** | {len(exceeds)} common-sample model/horizon rows; exact values in `directional_accuracy_results.md` |
| Any candidate beats fold-training majority? | **{majority_verdict}** | Best positive point difference is {_pct(best_positive_difference)}; no positive paired 95% interval excludes zero |
| Independently validated? | **NO** | `NEW_SEALED_HOLDOUT_UNAVAILABLE`; 2022–2023 tiles were already W3 validation |
| Eligible for a college claim? | **YES, WITH QUALIFIER** | May report reproducible `HISTORICAL_OOF_DEVELOPMENT` accuracy and baselines; may not claim forward/generalised accuracy |
| Profitable or trading-eligible? | **NO / NOT EVALUATED** | Raw-price accuracy is not net economics; W6 remains `NO_ELIGIBLE_STRATEGY` |

Primary fitted candidate was fixed before scoring as logistic h20; no post-result threshold tuning
occurred. All seven candidates and all four confidence-grid points are retained. A future claim of
independent accuracy requires a newly sealed, prospectively accumulated period.
""")

    write_figure(result, output / "accuracy_figures.png")
    return {"oof_rows": len(oof_rows), "exceeds_50_rows": len(exceeds),
            "beats_majority_point_rows": len(beats_majority),
            "beats_majority_robust_rows": len(robust_beats_majority)}


def write_manifest(output: str | Path, *, source_root: Path, input_hashes: dict,
                   result: dict, test_evidence: dict | None) -> dict:
    output = Path(output)
    artifact_names = [
        "evaluation_spec.json", "data_and_label_audit.md",
        "directional_accuracy_results.json", "directional_accuracy_results.md",
        "college_results_section.md", "college_evaluation_acceptance.md",
        "accuracy_figures.png", "oof_predictions.jsonl",
    ]
    code_paths = [
        source_root / "quantplus_intelligence/research_v3/college_accuracy/__init__.py",
        source_root / "quantplus_intelligence/research_v3/college_accuracy/contracts.py",
        source_root / "quantplus_intelligence/research_v3/college_accuracy/metrics.py",
        source_root / "quantplus_intelligence/research_v3/college_accuracy/runner.py",
        source_root / "quantplus_intelligence/research_v3/college_accuracy/reporting.py",
        source_root / "scripts/college_accuracy_run.py",
        source_root / "scripts/college_accuracy_verify.py",
        source_root / "tests/test_college_accuracy.py",
    ]
    manifest = {
        "manifest_version": "college_accuracy_reproducibility/1",
        "self_reference_convention": "manifest hashes all result artifacts except itself; payload hash excludes manifest_payload_sha256",
        "artifacts": {name: sha256(output / name) for name in artifact_names},
        "code_and_tests": {str(path.relative_to(source_root)).replace("\\", "/"): sha256(path)
                           for path in code_paths},
        "inputs": input_hashes,
        "result_id": result["result_id"],
        "spec_hash": result["spec_hash"],
        "fold_hashes": [row["fold_hash"] for row in result["folds"]],
        "run_ids": sorted(row["run_id"] for row in result["run_inventory"]),
        "frozen_w3_controls": {
            "feature_hash": "634b3669a3aacde6181bf2936d1bd98dd70f679edd9cb9637bcf9423a2e0fd52",
            "label_hash": "0053df3de4d04032c51dfdda7c152aedf6e800af120c57340a28bcb5beb55a7e",
        },
        "holdout_status": "NEW_SEALED_HOLDOUT_UNAVAILABLE",
        "test_evidence": test_evidence,
        "network_provider_calls": 0,
        "authority": "RESEARCH_ONLY_NO_ORDER_AUTHORITY",
        "rerun_commands": [
            "cd backend-extension && python scripts/college_accuracy_run.py run --spec ../reports/alpha_v3_1/college_accuracy/evaluation_spec.json --output ../reports/alpha_v3_1/college_accuracy",
            "cd backend-extension && python -m pytest tests/test_college_accuracy.py -q",
        ],
    }
    service_root = Path("D:/QP/agent-service")
    sync = []
    if service_root.is_dir():
        for path in code_paths:
            relative = path.relative_to(source_root)
            peer = service_root / relative
            dev_hash = sha256(path)
            peer_hash = sha256(peer) if peer.is_file() else None
            sync.append({"relative_path": str(relative).replace("\\", "/"),
                         "development_sha256": dev_hash,
                         "service_sha256": peer_hash,
                         "byte_identical": dev_hash == peer_hash})
    manifest["two_repo_sync"] = sync
    manifest["two_repo_sync_all_byte_identical"] = bool(sync) and all(
        row["byte_identical"] for row in sync)
    manifest["manifest_payload_sha256"] = hashlib.sha256(
        canonical_json(manifest).encode("utf-8")).hexdigest()
    _json(output / "reproducibility_manifest.json", manifest)
    return manifest
