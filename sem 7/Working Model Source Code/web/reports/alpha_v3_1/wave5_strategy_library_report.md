# W5 versioned strategy library

Generated from immutable contracts at 2026-11-14T09:05:10.030883+00:00. Every entry is a **hypothesis**, not an endorsement or profitable-strategy claim.

| Strategy / version | Source | DSL status | Lifecycle | Economic / forward eligibility |
|---|---|---|---|---|
| `near-52w-high-price-momentum` `1.0.0` | [The 52-Week High and Momentum Investing](https://doi.org/10.1111/j.1540-6261.2004.00695.x) | executable W2 StrategySpec/1 | `RESEARCH_DIAGNOSTIC` | diagnostic `RUNNABLE_DIAGNOSTIC`; economics `DATA_BLOCKED`; forward `DATA_BLOCKED` |
| `nse-inspired-6-12m-price-momentum` `1.0.0` | [Nifty200 Momentum 30 Index methodology/background](https://niftyindices.com/indices/equity/strategy-indices/nifty200-momentum-30-index-static) | executable W2 StrategySpec/1 | `RESEARCH_DIAGNOSTIC` | diagnostic `RUNNABLE_DIAGNOSTIC`; economics `DATA_BLOCKED`; forward `DATA_BLOCKED` |
| `post-earnings-announcement-drift` `1.0.0` | [Post-Earnings-Announcement Drift: Delayed Price Response or Risk Premium?](https://doi.org/10.2307/2491062) | NOT_IMPLEMENTED_SPEC_CONTRACT | `DATA_BLOCKED` | diagnostic `DATA_BLOCKED`; economics `DATA_BLOCKED`; forward `DATA_BLOCKED` |

## Eligibility reading

- 52-week-high and separate 6/12-month momentum variants compile into the existing W2 allowlisted DSL. Their W2 attachments are historical diagnostics with blocked economics; no edge was established.
- The momentum template is methodology-inspired and explicitly **not** Nifty200 Momentum 30 replication: universe, composite scoring, weighting and official constituents differ.
- PEAD is a typed blocked fixture: `DATA_BLOCKED_EVENT_CORPUS` and `NOT_IMPLEMENTED_SPEC_CONTRACT`. No event clause is silently discarded.
- Missing action history, fee history, strict membership and a never-revealed holdout prevent economic/forward eligibility. W2's revealed holdout is permanently refused.

## Revision semantics

`dsl_hash` addresses normalized StrategySpec data; `semantic_hash` addresses the complete citation/requirements/lifecycle revision. A parameter, DSL or semantic-version change mints a new revision; prior study/run references remain immutable.
