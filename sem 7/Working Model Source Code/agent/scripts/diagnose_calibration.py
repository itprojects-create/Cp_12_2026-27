"""Calibration inversion diagnostic (read-only, no eval tokens spent).

Pools every decisive session across ALL stored eval_report_*.json files and checks
whether mean size(correct) < mean size(wrong) is real/consistent/exploitable or a
small-n artifact. Reads eval JSONs + SQLite checkpoints (SELECT only). Writes
data/calibration_diagnostic.json. No prompts, gates, or schemas touched.
"""
from __future__ import annotations
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import sqlite_conn


def prompt_of(rep: dict, path: str) -> str:
    notes = rep.get("notes", "") or ""
    m = re.search(r"prompt\s+([A-Za-z0-9._-]+)", notes)
    if m:
        return m.group(1).rstrip(".,")
    # Legacy notes without the word "prompt": "Official v4 run ...", "prompt v2." era
    m2 = re.search(r"[Oo]fficial\s+(v[\d.]+)", notes)
    if m2:
        return m2.group(1).rstrip(".,")
    return "unknown:" + os.path.basename(path)


def set_of(rep: dict) -> str:
    s = rep.get("scenario_set") or ""
    if s:
        return s
    return "v1-2023-2024"  # first two reports predate scenario_set recording; both are orig-24


def ranks(xs: list[float]) -> list[float]:
    """Average-tie ranks (1-based). Pure python, no scipy dependency."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 3:
        return None
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None  # constant vector: correlation undefined
    return cov / (va ** 0.5 * vb ** 0.5)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    return pearson(ranks(xs), ranks(ys))


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def fmt(x: float | None) -> str:
    return f"{x:.4f}" if x is not None else "n/a"


def rho_str(r: float | None) -> str:
    return f"{r:+.3f}" if r is not None else "n/a"


def main() -> None:
    conn = sqlite_conn()
    paths = sorted(glob.glob("data/eval_report_*.json"))
    rows: list[dict] = []
    for path in paths:
        rep = json.load(open(path, encoding="utf-8"))
        prompt = prompt_of(rep, path)
        sset = set_of(rep)
        for r in rep.get("results", []):
            if r.get("label") not in ("long", "short"):
                continue  # decisive only
            sid = r["session"]
            ck = dict(conn.execute(
                "SELECT stage, payload FROM checkpoints WHERE session_id=?", (sid,)).fetchall())
            thesis_raw = json.loads(ck["thesis"]) if "thesis" in ck else {}
            prop_raw = json.loads(ck["proposal"]) if "proposal" in ck else {}
            risk_raw = json.loads(ck["risk"]) if "risk" in ck else {}
            chal_raw = json.loads(ck["challenge"]) if "challenge" in ck else {}
            dec_raw = json.loads(ck["decision"]) if "decision" in ck else {}
            mech = thesis_raw.get("mechanism_type", "pre-M3 (n/a)")
            # Pre-M3 payloads lack the key entirely (default OTHER only at model
            # layer); keep them out of the mechanism breakdown, not lumped as OTHER.
            mech_known = "mechanism_type" in thesis_raw
            rows.append({
                "report": os.path.basename(path),
                "prompt": prompt,
                "scenario_set": sset,
                "instrument": r["instrument"],
                "as_of": r["as_of"],
                "session": sid,
                "label": r["label"],
                "action": r["action"],
                "correct": bool(r["correct"]),
                "size_eval": float(r.get("size", 0.0)),  # FinalDecision.size as scored
                "size_ckpt": float(dec_raw.get("size", r.get("size", 0.0))) if dec_raw else float(r.get("size", 0.0)),
                "conviction": float(thesis_raw.get("conviction", float("nan"))) if thesis_raw else float("nan"),
                "thesis_direction": thesis_raw.get("direction", "?"),
                "mechanism_type": mech if mech_known else "pre-M3 (n/a)",
                "mechanism_known": mech_known,
                "proposal_size": float(prop_raw.get("size_pct", float("nan"))) if prop_raw else float("nan"),
                "risk_agg": float(risk_raw.get("risk_agg", {}).get("adjusted_size", float("nan"))) if risk_raw else float("nan"),
                "risk_con": float(risk_raw.get("risk_con", {}).get("adjusted_size", float("nan"))) if risk_raw else float("nan"),
                "risk_neu": float(risk_raw.get("risk_neu", {}).get("adjusted_size", float("nan"))) if risk_raw else float("nan"),
                "challenge": chal_raw.get("status", r.get("thesis_status", "?")),
                "fwd_ret": r.get("fwd_ret"),
            })

    dec = rows
    ok = [x for x in dec if x["correct"]]
    bad = [x for x in dec if not x["correct"]]
    sizes_ok = [x["size_eval"] for x in ok]
    sizes_bad = [x["size_eval"] for x in bad]
    conv_ok = [x["conviction"] for x in ok if x["conviction"] == x["conviction"]]
    conv_bad = [x["conviction"] for x in bad if x["conviction"] == x["conviction"]]
    prop_ok = [x["proposal_size"] for x in ok if x["proposal_size"] == x["proposal_size"]]
    prop_bad = [x["proposal_size"] for x in bad if x["proposal_size"] == x["proposal_size"]]
    y = [1.0 if x["correct"] else 0.0 for x in dec]
    sz = [x["size_eval"] for x in dec]
    cv = [x["conviction"] if x["conviction"] == x["conviction"] else float("nan") for x in dec]

    print(f"pooled decisive n={len(dec)} (correct={len(ok)}, wrong={len(bad)}) across {len(paths)} reports")
    inv = (mean(sizes_ok) or 0) < (mean(sizes_bad) or 0)
    print(f"mean size correct={fmt(mean(sizes_ok))} vs wrong={fmt(mean(sizes_bad))} "
          f"-> {'INVERTED' if inv else 'not inverted'}")
    print(f"mean conviction correct={fmt(mean(conv_ok))} vs wrong={fmt(mean(conv_bad))}")
    print(f"mean proposal_size correct={fmt(mean(prop_ok))} vs wrong={fmt(mean(prop_bad))}")
    print(f"spearman(size, correct)={rho_str(spearman(sz, y))}")
    cv_pairs = [(c, t) for c, t in zip(cv, y) if c == c]
    print(f"spearman(conviction, correct)={rho_str(spearman([c for c, _ in cv_pairs], [t for _, t in cv_pairs]))} (n={len(cv_pairs)})")
    ps = [(x["proposal_size"], 1.0 if x["correct"] else 0.0) for x in dec
          if x["proposal_size"] == x["proposal_size"]]
    print(f"spearman(proposal_size, correct)={rho_str(spearman([a for a, _ in ps], [b for _, b in ps]))} (n={len(ps)})")

    # Gate-convention cross-check: the official gate metric pools ALL sessions
    # (flat labels included), not just decisive. Recompute pooled both ways so
    # the discrepancy (if any) is visible as data.
    all_rows: list[dict] = []
    for path in paths:
        rep = json.load(open(path, encoding="utf-8"))
        for r in rep.get("results", []):
            all_rows.append({"correct": bool(r["correct"]), "size": float(r.get("size", 0.0))})
    all_ok = [x["size"] for x in all_rows if x["correct"]]
    all_bad = [x["size"] for x in all_rows if not x["correct"]]
    print(f"gate-convention pooled ALL sessions n={len(all_rows)} "
          f"mean_ok={fmt(mean(all_ok))} mean_bad={fmt(mean(all_bad))} "
          f"-> {'INVERTED' if (mean(all_ok) or 0) < (mean(all_bad) or 0) else 'not inverted'}")

    # (c) per prompt version
    print("\n-- by prompt version --")
    per_prompt = {}
    for p in sorted({x["prompt"] for x in dec}):
        sub = [x for x in dec if x["prompt"] == p]
        o = [x for x in sub if x["correct"]]
        w = [x for x in sub if not x["correct"]]
        rho = spearman([x["size_eval"] for x in sub], [1.0 if x["correct"] else 0.0 for x in sub])
        per_prompt[p] = {"n": len(sub), "n_ok": len(o),
                         "mean_ok": mean([x["size_eval"] for x in o]),
                         "mean_bad": mean([x["size_eval"] for x in w]), "spearman": rho}
        print(f"  {p:6s} n={len(sub):3d} ok={len(o):2d} mean_ok={fmt(per_prompt[p]['mean_ok'])} "
              f"mean_bad={fmt(per_prompt[p]['mean_bad'])} spearman={rho_str(rho)}")

    # (d) per mechanism (M3-known only)
    print("\n-- by mechanism_type (M3-known sessions only) --")
    per_mech = {}
    known = [x for x in dec if x["mechanism_known"]]
    print(f"  sessions with mechanism recorded: {len(known)}/{len(dec)}")
    for m in sorted({x["mechanism_type"] for x in known}):
        sub = [x for x in known if x["mechanism_type"] == m]
        o = [x for x in sub if x["correct"]]
        w = [x for x in sub if not x["correct"]]
        rho = spearman([x["size_eval"] for x in sub], [1.0 if x["correct"] else 0.0 for x in sub])
        per_mech[m] = {"n": len(sub), "n_ok": len(o),
                       "mean_ok": mean([x["size_eval"] for x in o]),
                       "mean_bad": mean([x["size_eval"] for x in w]), "spearman": rho}
        print(f"  {m:22s} n={len(sub):3d} ok={len(o):2d} mean_ok={fmt(per_mech[m]['mean_ok'])} "
              f"mean_bad={fmt(per_mech[m]['mean_bad'])} spearman={rho_str(rho)}")
    pre = [x for x in dec if not x["mechanism_known"]]
    if pre:
        o = [x for x in pre if x["correct"]]
        w = [x for x in pre if not x["correct"]]
        print(f"  {'pre-M3 (n/a)':22s} n={len(pre):3d} ok={len(o):2d} "
              f"mean_ok={fmt(mean([x['size_eval'] for x in o]))} mean_bad={fmt(mean([x['size_eval'] for x in w]))} "
              f"spearman={rho_str(spearman([x['size_eval'] for x in pre], [1.0 if x['correct'] else 0.0 for x in pre]))}")

    # (e) exploitability: sort by size desc, top vs bottom half accuracy
    print("\n-- exploitability (sort by size desc) --")
    srt = sorted(dec, key=lambda x: -x["size_eval"])
    half = len(srt) // 2
    top, bot = srt[:half], srt[len(srt) - half:]
    for name, grp in (("top-half (largest size)", top), ("bottom-half (smallest size)", bot)):
        acc = sum(1 for x in grp if x["correct"]) / len(grp) if grp else float("nan")
        print(f"  {name:26s} n={len(grp):3d} accuracy={acc:.3f} mean_size={fmt(mean([x['size_eval'] for x in grp]))}")
    srtc = sorted([x for x in dec if x["conviction"] == x["conviction"]], key=lambda x: -x["conviction"])
    h2 = len(srtc) // 2
    for name, grp in (("top-half (highest conviction)", srtc[:h2]), ("bottom-half (lowest conviction)", srtc[len(srtc) - h2:])):
        acc = sum(1 for x in grp if x["correct"]) / len(grp) if grp else float("nan")
        print(f"  {name:26s} n={len(grp):3d} accuracy={acc:.3f} mean_conv={fmt(mean([x['conviction'] for x in grp]))}")

    # per-report calibration table (consistency view)
    print("\n-- per-report calibration (mean size correct vs wrong) --")
    per_report = {}
    for path in paths:
        rep = json.load(open(path, encoding="utf-8"))
        sub = [x for x in dec if x["report"] == os.path.basename(path)]
        o = [x for x in sub if x["correct"]]
        w = [x for x in sub if not x["correct"]]
        per_report[os.path.basename(path)] = {
            "prompt": prompt_of(rep, path), "set": set_of(rep),
            "n_dec": len(sub), "mean_ok": mean([x["size_eval"] for x in o]),
            "mean_bad": mean([x["size_eval"] for x in w]),
            "inverted": (mean([x["size_eval"] for x in o]) or 0) < (mean([x["size_eval"] for x in w]) or 0),
        }
        pr = per_report[os.path.basename(path)]
        print(f"  {pr['prompt']:6s} {os.path.basename(path)} n={pr['n_dec']:2d} "
              f"ok={fmt(pr['mean_ok'])} bad={fmt(pr['mean_bad'])} {'INVERTED' if pr['inverted'] else 'ok'}")

    out = {"n_decisive_pooled": len(dec), "n_correct": len(ok), "n_wrong": len(bad),
           "mean_size_correct": mean(sizes_ok), "mean_size_wrong": mean(sizes_bad),
           "mean_conviction_correct": mean(conv_ok), "mean_conviction_wrong": mean(conv_bad),
           "spearman_size_correct": spearman(sz, y),
           "per_prompt": per_prompt, "per_mechanism": per_mech, "per_report": per_report,
           "top_half_accuracy": sum(1 for x in top if x["correct"]) / len(top) if top else None,
           "bottom_half_accuracy": sum(1 for x in bot if x["correct"]) / len(bot) if bot else None,
           "rows": rows}
    with open("data/calibration_diagnostic.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nwrote data/calibration_diagnostic.json")


if __name__ == "__main__":
    main()
