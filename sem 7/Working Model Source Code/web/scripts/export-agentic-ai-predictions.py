"""Export the local agentic forecast ledger to a dependency-free XLSX workbook.

Usage:
    python scripts/export-agentic-ai-predictions.py
    python scripts/export-agentic-ai-predictions.py --ledger D:\\QP\\agent-service\\data\\forecast_ledger.sqlite3

The exporter uses only the Python standard library so it remains usable in the
backend runtime without installing an Excel package.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = Path(r"D:\QP\agent-service\data\forecast_ledger.sqlite3")
DEFAULT_REPORTS = Path(r"D:\QP\agent-service\data\forecast_reports")
DEFAULT_BASELINE = Path(r"D:\QP\agent-service\data\baseline_analysis.json")
DEFAULT_OUTPUT = ROOT / "reports" / "agentic-ai-predictions.xlsx"
DEFAULT_BRIEF = ROOT / "reports" / "agentic-ai-predictions-tomorrow.md"


def _safe_float(value):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _score(p, outcome):
    if p is None or outcome is None:
        return None, None
    y = int(outcome.get("outperformed", 0))
    p = float(p)
    brier = (p - y) ** 2
    bounded = min(max(p, 1e-6), 1 - 1e-6)
    log_loss = -math.log(bounded if y else 1 - bounded)
    return brier, log_loss


def _prediction_class(card):
    if card.get("abstain"):
        return "Abstain"
    p = _safe_float(card.get("p_outperform"))
    if p is None:
        return "Unavailable"
    if p >= 0.55:
        return "Outperform lean"
    if p <= 0.45:
        return "Underperform lean"
    return "No clear edge"


def load_records(path: Path):
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT seq, card_id, symbol, as_of, horizon, matures_on, payload, recorded_at, "
        "settled_at, outcome, hash FROM forecast_ledger ORDER BY seq"
    ).fetchall()
    extras = {
        row[0]: json.loads(row[1])
        for row in conn.execute("SELECT card_id, payload FROM forecast_extras")
    }
    conn.close()
    records = []
    for row in rows:
        seq, card_id, symbol, as_of, horizon, matures_on, payload, recorded_at, settled_at, outcome, digest = row
        records.append(
            {
                "seq": seq,
                "card_id": card_id,
                "symbol": symbol,
                "as_of": as_of,
                "horizon": horizon,
                "matures_on": matures_on,
                "card": json.loads(payload),
                "recorded_at": recorded_at,
                "settled_at": settled_at,
                "outcome": json.loads(outcome) if outcome else None,
                "hash": digest,
                "extras": extras.get(card_id) or {},
            }
        )
    return records


def _metrics(records):
    settled = [r for r in records if r["settled_at"]]
    scored = [r for r in settled if not r["card"].get("abstain") and r["card"].get("p_outperform") is not None]
    pairs = [(float(r["card"]["p_outperform"]), int(r["outcome"]["outperformed"])) for r in scored]
    briers = [(p - y) ** 2 for p, y in pairs]
    logs = []
    for p, y in pairs:
        p = min(max(p, 1e-6), 1 - 1e-6)
        logs.append(-math.log(p if y else 1 - p))
    accuracy = sum(int((p >= 0.5) == bool(y)) for p, y in pairs) / len(pairs) if pairs else None
    brier = sum(briers) / len(briers) if briers else None
    baseline = sum((0.5 - y) ** 2 for _, y in pairs) / len(pairs) if pairs else None
    return {
        "locked": len(records),
        "settled": len(settled),
        "scored": len(scored),
        "abstained": sum(bool(r["card"].get("abstain")) for r in records),
        "open": sum(not r["settled_at"] for r in records),
        "accuracy": accuracy,
        "brier": brier,
        "brier_skill": (1 - brier / baseline) if brier is not None and baseline else None,
        "log_loss": sum(logs) / len(logs) if logs else None,
    }


def _by(records, key):
    groups = defaultdict(list)
    for record in records:
        groups[key(record)].append(record)
    return groups


def _cell(value, style=0):
    if value is None:
        return f'<c s="{style}"/>'
    if isinstance(value, bool):
        value = "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            return ""
        return f'<c s="{style}" t="n"><v>{value}</v></c>'
    text = escape(str(value))
    return f'<c s="{style}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _row(values, styles=None, row_number=None):
    styles = styles or [0] * len(values)
    cells = "".join(_cell(value, styles[i] if i < len(styles) else 0) for i, value in enumerate(values))
    attr = f' r="{row_number}"' if row_number else ""
    return f"<row{attr}>{cells}</row>"


def _sheet_xml(rows, widths=None, freeze=None, autofilter=None):
    widths = widths or []
    cols = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{width}" customWidth="1"/>'
        for i, width in enumerate(widths)
    )
    view = "<sheetView workbookViewId=\"0\">"
    if freeze:
        view += f'<pane ySplit="{freeze}" topLeftCell="A{freeze + 1}" activePane="bottomLeft" state="frozen"/>'
    view += "</sheetView>"
    filt = f'<autoFilter ref="{autofilter}"/>' if autofilter else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetViews>{view}</sheetViews><cols>{cols}</cols><sheetData>{''.join(rows)}</sheetData>{filt}"
        "</worksheet>"
    )


def _styles():
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="5">
    <numFmt numFmtId="164" formatCode="0.0%"/>
    <numFmt numFmtId="165" formatCode="0.0000"/>
    <numFmt numFmtId="166" formatCode="0.000%"/>
    <numFmt numFmtId="167" formatCode="0.00"/>
    <numFmt numFmtId="168" formatCode="0"/>
  </numFmts>
  <fonts count="4">
    <font><sz val="11"/><name val="Aptos"/></font>
    <font><b/><sz val="18"/><color rgb="FFFFFFFF"/><name val="Aptos Display"/></font>
    <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Aptos"/></font>
    <font><b/><sz val="11"/><color rgb="FF17324D"/><name val="Aptos"/></font>
  </fonts>
  <fills count="5">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF17324D"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF2F6B8A"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFEAF2F7"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left style="thin"><color rgb="FFD9E2EA"/></left><right style="thin"><color rgb="FFD9E2EA"/></right><top style="thin"><color rgb="FFD9E2EA"/></top><bottom style="thin"><color rgb="FFD9E2EA"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="12">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" applyFont="1" applyFill="1"/>
    <xf numFmtId="0" fontId="2" fillId="3" borderId="0" applyFont="1" applyFill="1"/>
    <xf numFmtId="0" fontId="3" fillId="4" borderId="0" applyFont="1" applyFill="1"/>
    <xf numFmtId="168" fontId="0" fillId="0" borderId="1" applyBorder="1"/>
    <xf numFmtId="165" fontId="0" fillId="0" borderId="1" applyBorder="1"/>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="1" applyBorder="1"/>
    <xf numFmtId="166" fontId="0" fillId="0" borderId="1" applyBorder="1"/>
    <xf numFmtId="167" fontId="0" fillId="0" borderId="1" applyBorder="1"/>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" applyBorder="1"/>
    <xf numFmtId="0" fontId="0" fillId="4" borderId="1" applyBorder="1" applyFill="1"/>
    <xf numFmtId="0" fontId="3" fillId="0" borderId="1" applyBorder="1" applyFont="1"/>
  </cellXfs>
</styleSheet>'''


def _workbook_xml(sheet_names):
    sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, name in enumerate(sheet_names, 1)
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <fileVersion appName="Quant Plus"/>
  <workbookPr defaultThemeVersion="164011"/>
  <bookViews><workbookView xWindow="0" yWindow="0" windowWidth="22000" windowHeight="12000"/></bookViews>
  <sheets>{sheets}</sheets>
  <calcPr calcMode="auto"/>
</workbook>'''


def _workbook_rels(count):
    sheets = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, count + 1)
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {sheets}
  <Relationship Id="rId{count + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''


def _content_types(count):
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, count + 1)
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  {overrides}
</Types>'''


def _root_rels():
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''


def _summary_sheet(records, generated):
    metrics = _metrics(records)
    horizons = _by(records, lambda r: r["horizon"])
    models = _by(records, lambda r: r["card"].get("model_version", "unknown"))
    rows = []
    rows.append(_row(["Quant Plus Agentic AI Predictions", None], [1, 1]))
    rows.append(_row(["Generated UTC", generated], [3, 9]))
    rows.append(_row(["Source", str(DEFAULT_LEDGER)], [3, 9]))
    rows.append(_row(["Interpretation", "Forward-scored research ledger; not investment advice."], [3, 10]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Ledger overview"], [11]))
    rows.append(_row(["Metric", "Value", "Meaning"], [2, 2, 2]))
    overview = [
        ("Locked forecast cards", metrics["locked"], "All cards recorded before their outcome matured."),
        ("Settled outcomes", metrics["settled"], "Cards whose forward horizon has completed."),
        ("Scored non-abstaining forecasts", metrics["scored"], "Only these are included in probability metrics."),
        ("Abstentions", metrics["abstained"], "No directional probability was emitted; excluded from accuracy."),
        ("Unsettled cards", metrics["open"], "Still waiting for their forward horizon."),
        ("Provisional accuracy", metrics["accuracy"], "Directional hit rate; sample is too small for a reliable claim."),
        ("Brier score", metrics["brier"], "Lower is better; scored non-abstaining cards only."),
        ("Brier skill vs 50/50", metrics["brier_skill"], "Positive means better than the constant 0.5 baseline."),
        ("Log loss", metrics["log_loss"], "Lower is better; scored non-abstaining cards only."),
    ]
    for label, value, meaning in overview:
        style = 6 if label in {"Provisional accuracy", "Brier skill vs 50/50"} else 5 if label in {"Brier score", "Log loss"} else 4
        if label in {"Provisional accuracy", "Brier skill vs 50/50"}:
            style = 6
        rows.append(_row([label, value, meaning], [9, style, 9]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Horizon inventory"], [11]))
    rows.append(_row(["Horizon", "Locked", "Answerable", "Abstained", "Settled", "Scored", "Mean p", "Mean |p-0.5|"], [2] * 8))
    for horizon in (5, 20):
        group = horizons.get(horizon, [])
        answerable = [r for r in group if not r["card"].get("abstain") and r["card"].get("p_outperform") is not None]
        scored = [r for r in group if r["settled_at"] and not r["card"].get("abstain") and r["card"].get("p_outperform") is not None]
        mean_p = sum(r["card"]["p_outperform"] for r in answerable) / len(answerable) if answerable else None
        mean_distance = sum(abs(r["card"]["p_outperform"] - 0.5) for r in answerable) / len(answerable) if answerable else None
        rows.append(_row([horizon, len(group), len(answerable), len(group) - len(answerable), sum(bool(r["settled_at"]) for r in group), len(scored), mean_p, mean_distance], [4, 4, 4, 4, 4, 4, 6, 6]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Model versions"], [11]))
    rows.append(_row(["Model version", "Locked", "Answerable", "Abstained", "Mean p", "5D", "20D"], [2] * 7))
    for model, group in sorted(models.items()):
        answerable = [r for r in group if not r["card"].get("abstain") and r["card"].get("p_outperform") is not None]
        mean_p = sum(r["card"]["p_outperform"] for r in answerable) / len(answerable) if answerable else None
        rows.append(_row([model, len(group), len(answerable), len(group) - len(answerable), mean_p, sum(r["horizon"] == 5 for r in group), sum(r["horizon"] == 20 for r in group)], [9, 4, 4, 4, 6, 4, 4]))
    rows.append(_row([None], [0]))
    rows.append(_row(["What the data says now"], [11]))
    notes = [
        "The ledger has 303 locked cards, split across 5-session and 20-session horizons.",
        "Only 2 cards have matured; 1 non-abstaining card is currently scored.",
        "The current 100% provisional accuracy is 1 correct result out of 1 scored forecast and must not be treated as predictive proof.",
        "The original forecast-v1 cards and the forecast-v2-horizon-gated cards are kept together and labeled in the Predictions sheet.",
        "Abstentions are preserved as a system behavior and are not silently counted as wrong predictions.",
        "The probability target is stock excess performance versus NIFTY 50 over the stated number of trading sessions.",
    ]
    for note in notes:
        rows.append(_row(["• " + note], [10]))
    return _sheet_xml(rows, [34, 22, 76], freeze=6)


def _historical_results(path: Path):
    """Load the archived, separately identified AI evaluation results."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    results = []
    for name, report in payload.items():
        agent = (report.get("scores") or {}).get("agent") or {}
        results.append({
            "report": name.removeprefix("eval_report_").removesuffix(".json"),
            "decisive": agent.get("n_decisive"),
            "correct": agent.get("n_correct"),
            "accuracy": agent.get("accuracy"),
            "best_constant_accuracy": report.get("best_constant_accuracy"),
            "beats_best_constant": report.get("beats_best_constant", False),
        })
    return results


def _latest_batch(records):
    if not records:
        return None, []
    latest = max(record["as_of"] for record in records)
    return latest, [record for record in records if record["as_of"] == latest]


def _tomorrow_sheet(records, baseline_path: Path, generated):
    latest, batch = _latest_batch(records)
    historical = _historical_results(baseline_path)
    rows = []
    rows.append(_row(["Tomorrow presentation brief — Quant Plus", None], [1, 1]))
    rows.append(_row(["Use this label", "Frozen forward forecast snapshot; live outcomes are pending."], [3, 10]))
    rows.append(_row(["Generated UTC", generated], [3, 9]))
    rows.append(_row(["Latest completed cutoff", latest or "—"], [3, 9]))
    rows.append(_row(["Model", "forecast-v2-horizon-gated"], [3, 9]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Current snapshot"], [11]))
    rows.append(_row(["Metric", "Value", "Presentation meaning"], [2, 2, 2]))
    for horizon in (5, 20):
        group = [r for r in batch if r["horizon"] == horizon]
        answerable = [r for r in group if not r["card"].get("abstain") and r["card"].get("p_outperform") is not None]
        maturities = sorted({r["matures_on"] for r in group})
        rows.append(_row([f"{horizon}-session cards", len(group), "Locked forecasts from the same point-in-time cutoff."], [3, 4, 10]))
        rows.append(_row([f"{horizon}-session answerable", len(answerable), "Directional probabilities available for ranking; not settled results."], [3, 4, 10]))
        rows.append(_row([f"{horizon}-session abstentions", len(group) - len(answerable), "The system withheld a directional probability when evidence was insufficient."], [3, 4, 10]))
        rows.append(_row([f"{horizon}-session maturity", ", ".join(maturities) or "—", "Earliest date at which forward scoring can begin."], [3, 9, 10]))
    rows.append(_row(["All ledger cards", len(records), "Historical locked cards, including earlier model versions."], [3, 4, 10]))
    rows.append(_row(["Settled / scored", f"{_metrics(records)['settled']} / {_metrics(records)['scored']}", "Only settled non-abstaining rows count in accuracy metrics."], [3, 9, 10]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Strongest current probability leans"], [11]))
    rows.append(_row(["Horizon", "Symbol", "P(outperform)", "Class", "Matures", "Vol forecast", "Disagreement", "Robustness"], [2] * 8))
    for horizon in (5, 20):
        group = [r for r in batch if r["horizon"] == horizon and not r["card"].get("abstain") and r["card"].get("p_outperform") is not None]
        group.sort(key=lambda r: abs(float(r["card"]["p_outperform"]) - 0.5), reverse=True)
        for record in group[:5]:
            card = record["card"]
            rows.append(_row([
                horizon, record["symbol"], _safe_float(card.get("p_outperform")), _prediction_class(card), record["matures_on"],
                _safe_float(card.get("vol_forecast")), _safe_float(card.get("disagreement")), _safe_float(card.get("robustness")),
            ], [4, 9, 6, 10, 9, 7, 5, 6]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Historical evidence to disclose"], [11]))
    if historical:
        accuracies = [r["accuracy"] for r in historical if r["accuracy"] is not None]
        rows.append(_row(["Archived AI evaluations", len(historical), "Separate historical configurations; do not pool as current v2 performance."], [3, 4, 10]))
        rows.append(_row(["Archived accuracy range", f"{min(accuracies):.1%} to {max(accuracies):.1%}", "Observed range across the archived reports."], [3, 9, 10]))
        rows.append(_row(["Archived mean accuracy", sum(accuracies) / len(accuracies), "Descriptive mean only; reports reuse scenario families."], [3, 6, 10]))
        rows.append(_row(["Beat best constant baseline", f"{sum(bool(r['beats_best_constant']) for r in historical)}/{len(historical)}", "No archived report beat its best constant baseline."], [3, 9, 10]))
    else:
        rows.append(_row(["Archived AI evaluations", "Unavailable", str(baseline_path)], [3, 9, 10]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Exact wording for the results question"], [11]))
    for note in [
        "The system has produced a frozen, inspectable forward forecast set, not a completed accuracy study.",
        "The latest snapshot contains ranked 5-session and 20-session probability leans plus explicit abstentions.",
        "Current forward results are pending; the first large 5-session group matures on 2026-11-09 and the 20-session group on 2026-12-02.",
        "Archived AI evaluations did not beat their best constant baselines, so the project does not claim a proven forecasting edge.",
        "The engineering result is the auditable workflow: point-in-time cutoff, horizon-specific probability, abstention, hash-chain and later settlement.",
    ]:
        rows.append(_row(["• " + note], [10]))
    return _sheet_xml(rows, [30, 20, 18, 22, 16, 16, 16, 14], freeze=6)


def _predictions_sheet(records):
    headers = [
        "Seq", "Symbol", "Horizon sessions", "As-of cutoff", "Recorded UTC", "Matures on", "Settled UTC",
        "Model version", "Benchmark", "Status", "Forecast class", "P(outperform)", "Abstain reason",
        "Q10 excess", "Q50 excess", "Q90 excess", "Vol forecast", "Event shock p", "Disagreement",
        "Robustness", "Outcome excess", "Outperformed", "Brier", "Log loss", "Ledger hash",
    ]
    rows = [_row(headers, [2] * len(headers))]
    for record in records:
        card = record["card"]
        outcome = record["outcome"] or {}
        p = _safe_float(card.get("p_outperform"))
        brier, log_loss = _score(p, outcome if record["settled_at"] and not card.get("abstain") else None)
        status = "Settled" if record["settled_at"] else "Open"
        if card.get("abstain"):
            status = "Settled abstention" if record["settled_at"] else "Open abstention"
        q = card.get("quantiles") or {}
        values = [
            record["seq"], record["symbol"], record["horizon"], record["as_of"], record["recorded_at"], record["matures_on"], record["settled_at"],
            card.get("model_version"), card.get("benchmark"), status, _prediction_class(card), p, card.get("abstain_reason"),
            _safe_float(q.get("0.1")), _safe_float(q.get("0.5")), _safe_float(q.get("0.9")), _safe_float(card.get("vol_forecast")),
            _safe_float(card.get("p_event_shock")), _safe_float(card.get("disagreement")), _safe_float(card.get("robustness")),
            _safe_float(outcome.get("excess_return")) if record["settled_at"] else None,
            outcome.get("outperformed") if record["settled_at"] else None, brier, log_loss, record["hash"],
        ]
        styles = [4, 9, 4, 9, 9, 9, 9, 9, 9, 10, 10, 6, 9, 6, 6, 6, 7, 6, 5, 6, 6, 4, 5, 5, 9]
        rows.append(_row(values, styles))
    return _sheet_xml(rows, [8, 16, 16, 23, 27, 14, 27, 25, 14, 18, 20, 16, 28, 13, 13, 13, 14, 14, 14, 13, 15, 13, 13, 13, 66], freeze=1, autofilter=f"A1:Y{len(rows)}")


def _votes_sheet(records):
    headers = ["Seq", "Symbol", "Horizon", "As-of cutoff", "Model version", "Forecaster", "Origin", "p used", "Raw p", "Weight", "Abstain", "Reason / note"]
    rows = [_row(headers, [2] * len(headers))]
    for record in records:
        votes = record["extras"].get("votes") or []
        if not votes:
            votes = [
                {"forecaster": c.get("forecaster"), "p": c.get("raw_p", c.get("p")), "abstain": False, "reason": c.get("note", "")}
                for c in record["card"].get("contributions", [])
            ]
        contributions = {c.get("forecaster"): c for c in record["card"].get("contributions", [])}
        for vote in votes:
            name = vote.get("forecaster", "")
            contribution = contributions.get(name, {})
            origin = "Classical" if name in {"momentum", "reversal"} else "LLM"
            rows.append(_row([
                record["seq"], record["symbol"], record["horizon"], record["as_of"], record["card"].get("model_version"),
                name, origin, _safe_float(contribution.get("p", vote.get("p"))), _safe_float(vote.get("p")),
                _safe_float(contribution.get("weight")), bool(vote.get("abstain")), vote.get("reason") or contribution.get("note", ""),
            ], [4, 9, 4, 9, 9, 9, 9, 6, 6, 5, 9, 9]))
    return _sheet_xml(rows, [8, 16, 11, 23, 25, 22, 12, 13, 13, 12, 10, 54], freeze=1, autofilter=f"A1:L{len(rows)}")


def _settled_sheet(records):
    headers = ["Seq", "Symbol", "Horizon", "Model version", "p outperform", "Forecast class", "Abstained", "Outcome excess", "Outperformed", "Scored?", "Brier", "Log loss", "Recorded UTC", "Settled UTC"]
    rows = [_row(headers, [2] * len(headers))]
    for record in records:
        if not record["settled_at"]:
            continue
        card = record["card"]
        outcome = record["outcome"] or {}
        p = _safe_float(card.get("p_outperform"))
        brier, log_loss = _score(p, outcome if not card.get("abstain") else None)
        rows.append(_row([
            record["seq"], record["symbol"], record["horizon"], card.get("model_version"), p, _prediction_class(card), bool(card.get("abstain")),
            _safe_float(outcome.get("excess_return")), outcome.get("outperformed"), "Yes" if brier is not None else "No", brier, log_loss,
            record["recorded_at"], record["settled_at"],
        ], [4, 9, 4, 9, 6, 10, 9, 6, 4, 9, 5, 5, 9, 9]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Scoring note", "The abstaining ADANIPORTS outcome is shown but excluded from accuracy, Brier, and log loss."], [3, 10]))
    return _sheet_xml(rows, [8, 16, 11, 25, 15, 20, 12, 16, 14, 12, 12, 12, 27, 27], freeze=1, autofilter=f"A1:N{len(rows) - 2}")


def _methodology_sheet(records, generated):
    rows = []
    rows.append(_row(["Methodology and data lineage"], [1]))
    rows.append(_row(["Item", "Description"], [2, 2]))
    items = [
        ("Generated", generated),
        ("Workbook source", str(DEFAULT_LEDGER)),
        ("Target", "Probability that the stock outperforms NIFTY 50 over the stated number of trading sessions."),
        ("Forecast horizons", "5 and 20 trading sessions."),
        ("Point-in-time rule", "Evidence is cut off at the last completed bar; intraday forecast locking is refused."),
        ("Abstention rule", "Empty or contradictory evidence may abstain. Abstentions remain visible and are not scored as wrong."),
        ("Probability scoring", "Brier = (p - outcome)^2. Log loss uses the emitted probability and the binary outperformance outcome."),
        ("Baseline", "Brier skill is compared with a constant 0.5 probability on the same scored rows."),
        ("Aggregation", "Code aggregates forecaster votes. Unproven LLM probabilities are bounded to 0.35–0.65 until 30 forward-settled labels."),
        ("Model versions", "forecast-v1 is the earlier ledger model; forecast-v2-horizon-gated adds horizon-conditioned classical signals and calibration safeguards."),
        ("Ledger integrity", "Cards are hash-chained and recorded before outcomes; settlement is exactly once."),
        ("Current evidence", "303 locked cards, 2 settled outcomes, and 1 scored non-abstaining card. Accuracy is therefore provisional."),
        ("Operational meaning", "This workbook is a historical research record, not a trading instruction or investment advice."),
    ]
    for label, value in items:
        rows.append(_row([label, value], [3, 10]))
    rows.append(_row([None], [0]))
    rows.append(_row(["Workbook tabs"], [11]))
    for name, description in [
        ("Summary", "Headline counts, provisional scoring, horizon inventory, and model versions."),
        ("Predictions", "One row per locked forecast card, including probability, risk, outcome, and ledger hash."),
        ("Votes", "Forecaster-level inputs and abstentions where persisted."),
        ("Settled Results", "Only matured cards and their realized forward outcomes."),
        ("Methodology", "Definitions, lineage, and caveats."),
    ]:
        rows.append(_row([name, description], [3, 10]))
    return _sheet_xml(rows, [28, 105], freeze=2)


def _latest_report(name: str):
    files = sorted(DEFAULT_REPORTS.glob(f"{name}_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _tournament_stats(ledger_path: Path):
    conn = sqlite3.connect(ledger_path)
    rows = conn.execute(
        "SELECT horizon, COUNT(*), COUNT(DISTINCT day), COUNT(DISTINCT sector) "
        "FROM forecast_tournaments GROUP BY horizon ORDER BY horizon"
    ).fetchall()
    conn.close()
    return rows


def _diagnostics_sheet(ledger_path: Path):
    rows = []
    rows.append(_row(["Diagnostics and operational gates"], [1]))
    rows.append(_row(["Job / signal", "Status or coverage", "Key result", "Interpretation"], [2, 2, 2, 2]))
    settle = _latest_report("settle")
    bridge = None
    bridge_files = sorted((DEFAULT_REPORTS / "bridge").glob("bridge-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if bridge_files:
        try:
            bridge = json.loads(bridge_files[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            bridge = None
    risk = _latest_report("risk_bench") or {}
    metalabel = _latest_report("metalabel") or {}
    event = _latest_report("event_study") or {}
    crowding = _latest_report("crowding") or {}
    blind = _latest_report("blind_gap") or {}
    bridge_h = (bridge or {}).get("gate", {}).get("horizons", {}).get("5", {})
    if not bridge_h:
        bridge_h = (bridge or {}).get("gate", {}).get("horizons", {}).get(5, {})
    rows.extend([
        _row(["Settlement", "Complete", f"Newly settled: {(settle or {}).get('settled', 0)}; chain checked: {(settle or {}).get('chain', {}).get('checked', '—')}", "No new cards were due at export time."], [9, 10, 9, 10]),
        _row(["Profitability bridge", bridge_h.get("state", "—"), f"5D settled: {bridge_h.get('settled', '—')}; need: {bridge_h.get('need_for_halt_end', '—')}; intents: {(bridge or {}).get('intents', 0)}", "Trade gate remains closed until forward evidence clears the pre-registered threshold."], [9, 10, 9, 10]),
        _row(["Risk benchmark", risk.get("status", "—"), f"Settled: {risk.get('settled', risk.get('n', '—'))}; needed: {risk.get('needed', '—')}", "Volatility comparison is waiting for enough matured cards."], [9, 10, 9, 10]),
        _row(["Meta-label", metalabel.get("status", "—"), f"Joined labels: {metalabel.get('joined', '—')}; needed: {metalabel.get('needed', '—')}", "Sizing model is not promoted without forward labels."], [9, 10, 9, 10]),
        _row(["Event study", "Ready / empty", f"Events seen: {event.get('events_seen', '—')}; matured: {event.get('matured', '—')}", "No event type has enough forward evidence to enter the forecast."], [9, 10, 9, 10]),
        _row(["Crowding test", crowding.get("verdict", "—"), f"Crowded: {crowding.get('n_crowded', '—')}; normal: {crowding.get('n_normal', '—')}", "The pre-registered volatility hypothesis remains untested."], [9, 10, 9, 10]),
        _row(["Blind gap", "Diagnostic", f"Mean named-vs-blind gap: {blind.get('mean_gap', '—')}; suspect count: {sum(len(v.get('suspect', [])) for v in (blind.get('per_symbol') or {}).values() if isinstance(v, dict))}", "No blind-gap result promotes a signal; this is a contamination diagnostic."], [9, 10, 9, 10]),
    ])
    rows.append(_row([None], [0]))
    rows.append(_row(["Tournament coverage"], [11]))
    rows.append(_row(["Horizon", "Rows", "Days", "Sectors", "Interpretation"], [2] * 5))
    for horizon, count, days, sectors in _tournament_stats(ledger_path):
        rows.append(_row([horizon, count, days, sectors, "Ranking evidence is stored; IC gate still needs 45 settled days."], [4, 4, 4, 4, 10]))
    return _sheet_xml(rows, [24, 18, 60, 74], freeze=2)


def _markdown_brief(records, baseline_path: Path, generated: str) -> str:
    latest, batch = _latest_batch(records)
    historical = _historical_results(baseline_path)
    metrics = _metrics(records)
    lines = [
        "# Quant Plus — Agentic AI prediction brief",
        "",
        "> **Presentation status:** frozen forward forecast snapshot. Current outcomes are pending settlement.",
        "",
        f"- Generated UTC: `{generated}`",
        f"- Latest completed cutoff: `{latest or '—'}`",
        "- Model: `forecast-v2-horizon-gated`",
        "- Target: probability that a stock outperforms NIFTY 50 over the stated trading-session horizon.",
        "",
        "## What can be shown tomorrow",
        "",
        "The latest batch contains the model's point-in-time forecast cards, ranked probability leans, risk estimates, and explicit abstentions. These are valid predictions to demonstrate, but they are not yet accuracy results because their forward horizons have not completed.",
        "",
        "| Horizon | Cards | Answerable | Abstained | Maturity |",
        "|---:|---:|---:|---:|---|",
    ]
    for horizon in (5, 20):
        group = [r for r in batch if r["horizon"] == horizon]
        answerable = [r for r in group if not r["card"].get("abstain") and r["card"].get("p_outperform") is not None]
        maturity = ", ".join(sorted({r["matures_on"] for r in group})) or "—"
        lines.append(f"| {horizon} sessions | {len(group)} | {len(answerable)} | {len(group) - len(answerable)} | {maturity} |")
    lines += [
        "",
        f"Across the full ledger there are **{metrics['locked']} locked cards**, **{metrics['settled']} settled outcomes**, and **{metrics['scored']} scored non-abstaining forecasts**. Any current accuracy figure is provisional until a meaningful settled sample exists.",
        "",
        "## Strongest current probability leans",
        "",
        "These are model rankings for demonstration, not trade instructions.",
        "",
        "| Horizon | Symbol | P(outperform) | Class | Matures | Vol forecast | Disagreement |",
        "|---:|---|---:|---|---|---:|---:|",
    ]
    for horizon in (5, 20):
        group = [r for r in batch if r["horizon"] == horizon and not r["card"].get("abstain") and r["card"].get("p_outperform") is not None]
        group.sort(key=lambda r: abs(float(r["card"]["p_outperform"]) - 0.5), reverse=True)
        for record in group[:5]:
            card = record["card"]
            lines.append(
                f"| {horizon} | {record['symbol']} | {float(card['p_outperform']):.2%} | {_prediction_class(card)} | {record['matures_on']} | {float(card.get('vol_forecast') or 0):.2%} | {float(card.get('disagreement') or 0):.2%} |"
            )
    lines += ["", "## Historical result to disclose", ""]
    if historical:
        accuracies = [r["accuracy"] for r in historical if r["accuracy"] is not None]
        lines += [
            f"The archived forward evaluations contain **{len(historical)} reports**. Agent accuracy ranged from **{min(accuracies):.1%} to {max(accuracies):.1%}** with a descriptive mean of **{sum(accuracies) / len(accuracies):.1%}**. **{sum(bool(r['beats_best_constant']) for r in historical)}/{len(historical)}** beat the best constant baseline.",
            "",
            "These archived configurations are separate from the current `forecast-v2-horizon-gated` forward ledger and must not be presented as current live accuracy.",
        ]
    else:
        lines.append(f"Archived source unavailable: `{baseline_path}`")
    lines += [
        "",
        "## Suggested 5-minute demonstration",
        "",
        "1. Open the `Tomorrow Brief` tab in `agentic-ai-predictions.xlsx`.",
        "2. Show the latest cutoff, the two horizons, and why the system abstains on many cards.",
        "3. Open `Predictions` and inspect one high-probability lean, its model version, risk estimate, maturity date, and ledger hash.",
        "4. Open `Votes` to show classical momentum/reversal anchors and the separate forecaster inputs.",
        "5. Finish with the `Settled Results` and `Diagnostics` tabs: explain that settlement is forward-only and the trade bridge remains HALT until evidence accumulates.",
        "",
        "## Answer if asked for accuracy",
        "",
        "> We have a working, auditable forward forecast ledger, but the current v2 sample has not matured enough to claim predictive accuracy. We show the live predictions now, preserve abstentions, and score them only after the defined 5-session or 20-session horizon. Earlier archived tests did not beat their constant baselines, so we do not claim a proven edge.",
        "",
        "Source workbook: `reports/agentic-ai-predictions.xlsx`.",
    ]
    return "\n".join(lines) + "\n"


def write_workbook(records, output: Path, ledger_path: Path, baseline_path: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat()
    sheets = {
        "Summary": _summary_sheet(records, generated),
        "Tomorrow Brief": _tomorrow_sheet(records, baseline_path, generated),
        "Predictions": _predictions_sheet(records),
        "Votes": _votes_sheet(records),
        "Settled Results": _settled_sheet(records),
        "Methodology": _methodology_sheet(records, generated),
        "Diagnostics": _diagnostics_sheet(ledger_path),
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types(len(sheets)))
        archive.writestr("_rels/.rels", _root_rels())
        archive.writestr("xl/workbook.xml", _workbook_xml(list(sheets)))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(sheets)))
        archive.writestr("xl/styles.xml", _styles())
        for index, xml in enumerate(sheets.values(), 1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", xml)
    DEFAULT_BRIEF.write_text(_markdown_brief(records, baseline_path, generated), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if not args.ledger.exists():
        raise SystemExit(f"Forecast ledger not found: {args.ledger}")
    records = load_records(args.ledger)
    write_workbook(records, args.out, args.ledger, args.baseline)
    print(json.dumps({"written": str(args.out), "brief": str(DEFAULT_BRIEF), **_metrics(records)}, indent=2))


if __name__ == "__main__":
    main()
