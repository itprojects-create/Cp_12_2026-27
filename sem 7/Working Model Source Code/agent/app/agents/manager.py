"""Research Manager (sonnet synthesis) + Devil's Advocate (sonnet falsification)."""
from __future__ import annotations
import json
from app import schemas as S
from app.agents._util import call_json, evidence_ledger

def run_manager(reports: list[S.AnalystReport], turns: list[S.DebateTurn], session_id: str) -> S.Thesis:
    ledger = evidence_ledger(reports)
    log = "\n".join(f"{t.stance}: {t.argument} (d={t.confidence_delta:+.2f})" for t in turns)
    system = ("You are the Research Manager. Synthesize ONE thesis by WEIGHT of evidence, not by veto. "
              "The EVIDENCE LEDGER below is computed deterministically in code: read its TALLY line "
              "(bullish/bearish/neutral signal counts, signal_margin, mean_conf) as given — never "
              "recount or guess these numbers, and trust the numbers over the prose when they disagree. "
              "An abstaining analyst (low confidence / 'no data') counts as NEUTRAL and must NOT "
              "override constructive analysts. "
              "Choose long only when bullish evidence clearly outweighs (mean conf >= 0.60 with at "
              "least 2 more bullish than bearish signals); short symmetrically. "
              "Choose flat as the honest answer when evidence is thin (mean conf < 0.50 or margin < 2) "
              "or when the market base-rate conflicts (index DOWN for a long, UP for a short). "
              "No-edge honesty is required — a forced trade on ambiguity is an error. "
              "State the market base-rate prior (index trend + breadth as given, else neutral) in one "
              "line, and state one falsifier (the concrete observation that would kill your thesis) "
              "in one line. "
              "Weigh the events/catalyst analyst for timing: a large recent surprise supports "
              "continuation, while results due within days are a risk flag that can cap conviction. "
              "Weigh delivery evidence the same way: accumulation (z>=+1) supports longs, "
              "distribution (z<=-1) argues against them. "
              "First state one line for the bull case and one for the bear case, then decide. "
               "direction MUST be one of long|short|flat. conviction is a number 0-1. "
               "Classify the thesis's primary causal mechanism as exactly one of: "
               "MOMENTUM_CONTINUATION (trend/drift persists), MEAN_REVERSION (price "
               "reverts toward a prior level), EVENT_DRIVEN (a specific catalyst/event "
               "drives the move), or OTHER. Set this in the mechanism_type field. This "
               "is a structural classification, not a confidence judgment — classify "
               "based on the STATED reasoning in the thesis, not on whether you think "
               "it's correct. "
               "Return ONLY Thesis JSON: {direction, conviction, key_evidence[], key_risks[], mechanism_type}. "
               "Never return an empty object.")
    return call_json("research_manager", session_id, system,
                     f"EVIDENCE LEDGER:\n{ledger}\ndebate:\n{log}", S.Thesis)

def build_devil_prompt(thesis: S.Thesis, reports: list[S.AnalystReport],
                       exhaustion: S.RawExhaustionSignals | None = None) -> tuple[str, str]:
    """Devil's Advocate v5 prompt. Shared by run_devils_advocate and the reachability probe.

    exhaustion is the pass-through dict the Technical Analyst computed (Part A) —
    raw numeric facts in their own payload field, never narrative, never recomputed.
    """
    digest = "\n".join(f"[{r.agent} conf={r.confidence:.2f}] {r.summary}" for r in reports)
    context = {
        "macro": next((r.summary for r in reports if r.agent == "macro"), "(no macro report)"),
        "events": next((r.summary for r in reports if r.agent == "events"), "(no events report)"),
    }
    system = (
        "Devil's Advocate — Thesis Challenge Agent (v5)\n"
        "ROLE: You receive a synthesized Thesis built from a completed Bull/Bear debate. "
        "Your job is NOT to find a reason for caution — the debate already surfaced and weighed "
        "the risks. Your job is to determine whether the thesis, AS ARGUED, survives a genuine "
        "attempt to break it using evidence the debate did NOT already account for.\n"
        "CALIBRATION CONTRACT: HEALTHY must be a reachable, commonly-reached verdict. A "
        "competently-argued thesis backed by sufficient evidence and already-priced-in risks "
        "should be HEALTHY most of the time. If you notice yourself reaching for WEAKENED as a "
        "default posture of caution, that is miscalibration — stop and re-run the test below. "
        "WEAKENED and BROKEN must be earned with a specific, named, NEW piece of counter-evidence "
        "— never uncertainty, unpredictability, or 'risks exist.' Every thesis has risks; that "
        "fact alone is never grounds for anything below HEALTHY.\n"
        "DECISION PROCEDURE (follow in order): "
        "1. Restate the thesis's core causal claim in one sentence. "
        "2. List the risks the thesis ALREADY acknowledges in key_risks. Anything you raise that "
        "duplicates one of these is NOT new evidence — do not use it to downgrade. "
        "3. Search the evidence for exactly one outcome: "
        "(a) BROKEN — a specific concrete fact directly contradicting the causal claim; "
        "(b) WEAKENED — a specific NEW factor (not in key_risks) that meaningfully reduces the "
        "odds, naming the factor, its mechanism, and whether conviction shifts high->moderate or "
        "moderate->low (vague 'conditions could change' is not a factor); "
        "(c) HEALTHY — you searched for (a) and (b) and found no sufficient grounds. HEALTHY is "
        "the default outcome of a genuine search that comes up empty, not something requiring "
        "positive evidence in favor. "
        "4. Before finalizing WEAKENED/BROKEN: if your objection would apply equally to the "
        "OPPOSITE thesis, it is not direction-specific — discard it and re-run step 3. "
        "5. Verdict uses ONLY factors passing step 4.\n"
        "VALID NEW EVIDENCE: direct price-action contradiction of the setup; a concrete dated "
        "upcoming event not weighed in key_risks; a regime signal undercutting the claimed "
        "MECHANISM (not generic risk); numerical inconsistency between key_evidence and the data.\n"
        "RAW SIGNAL OVERRIDE (read carefully — it changes what 'duplicate' means): you also "
        "receive raw_exhaustion_signals: flush_flag, blowoff_flag, ret_5d_pct, "
        "dist_from_20d_low_pct, dist_from_20d_high_pct. These are numeric facts, not analyst "
        "narrative. A sentence in key_risks that generically mentions 'reversal risk' or "
        "'exhaustion risk' does NOT count as already pricing in a SPECIFIC numeric signal — "
        "narrative acknowledgment and numeric contradiction are different things, and the "
        "duplicate-risk rule in step 2 excludes only genuine duplicates of the SAME specific "
        "claim, not the general topic. Apply explicitly: LONG thesis + blowoff_flag true "
        "(already up sharply over 5 days near/above its own 90th-percentile move) directly "
        "contradicts a 'further upside from here' claim — grounds for BROKEN unless the thesis "
        "argues, with a distinct fresh catalyst, why the move continues anyway (not just "
        "'momentum'). SHORT thesis + flush_flag true — same BROKEN grounds unless a distinct "
        "fresh catalyst is explicitly argued. Absence of either flag is NOT evidence for "
        "HEALTHY on its own; continue the normal step-3 procedure.\n"
        "NEVER COUNTS: 'markets are unpredictable'; restating a key_risk; low conviction alone; "
        "general skepticism about momentum/drift as a category; hedging words in analyst reports.\n"
        "SELF-CHECK: would this same objection flag nearly every thesis sharing a feature? If yes, "
        "it is categorical bias — discard and return to step 3.\n"
        "WORKED EXAMPLES (calibrate your verdict distribution — HEALTHY, WEAKENED, BROKEN must "
        "each be genuinely reachable): "
        "Example 1 HEALTHY: LONG on post-earnings drift, +18% surprise, no exhaustion flags, next "
        "earnings >60 days out, VIX normal, key_risks notes 'surprise could be one-time'. Raw: "
        "flush=false, blowoff=false. Nothing new beyond priced-in risks, no override. HEALTHY — "
        "the common case for a competently-argued, uncontradicted thesis. "
        "Example 2 WEAKENED: LONG on sector rotation, key_risks silent on regulation. New fact: a "
        "specific regulatory ruling on this exact subsector due in 8 days, mentioned nowhere. "
        "Genuinely new, direction-relevant, undebated — but not a direct contradiction. WEAKENED, "
        "naming the ruling and date. "
        "Example 3 BROKEN: LONG on 'breakout momentum continuation'. Raw: blowoff=true, "
        "ret_5d=+11.2% above its own 90th-percentile move, at/above the 20-day high. key_risks "
        "says only 'market could pull back' with no mechanism. Per RAW SIGNAL OVERRIDE: the "
        "causal claim (further upside) is directly contradicted by a numeric fact the thesis "
        "never specifically engages. BROKEN.\n"
        "OUTPUT (strict JSON, no prose outside the object): "
        "{status: one of HEALTHY|WEAKENED|BROKEN, "
        "core_claim_restated: one sentence from step 1 (10+ chars), "
        "new_evidence_considered: [specific factors, empty if HEALTHY], "
        "duplicate_risks_discarded: [key_risks you did NOT count], "
        "direction_symmetry_check_passed: boolean, "
        "raw_override_applied: boolean (true iff the RAW SIGNAL OVERRIDE rule decided this verdict), "
        "reasons: [one per factor, only for WEAKENED/BROKEN]}. "
        "All keys REQUIRED, never an empty object, never markdown.")
    user = (f"Thesis: {thesis.model_dump_json()}\n"
            f"Original analyst evidence:\n{digest}\n"
            f"Market context (VIX, index trend, upcoming calendar events): {json.dumps(context)}\n"
            f"raw_exhaustion_signals: "
            f"{exhaustion.model_dump_json() if exhaustion is not None else 'unavailable (no exhaustion data for this session)'}")
    return system, user


def run_devils_advocate(thesis: S.Thesis, reports: list[S.AnalystReport], session_id: str,
                        exhaustion: S.RawExhaustionSignals | None = None) -> S.Challenge:
    system, user = build_devil_prompt(thesis, reports, exhaustion)
    return call_json("devils_advocate", session_id, system, user, S.Challenge)

