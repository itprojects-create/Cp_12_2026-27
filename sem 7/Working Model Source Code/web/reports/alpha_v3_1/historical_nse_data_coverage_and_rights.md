# Historical NSE data — coverage, provenance and rights (V3.1 W1.1)

Status: **PASS (with two disclosed gaps)** · Generated: 2026-11-12 ·
Machine source of truth: `reports/alpha_v3_1/pit_source_integrity.json`
(rewritten on every `backend-extension/scripts/wave1_ingest_warehouse.py` run)

This document is the human-readable companion to the V3.1 research warehouse
(`backend-extension/quantplus_intelligence/research_v3/warehouse.py`). It
records what historical data exists, what it may be used for, where it is
known to be missing, and which labels every research output must carry.
Nothing here is synthetic: every figure below is measured from the ingested
warehouse or the immutable source archives.

---

## 1. Sources and provenance

| Source | Path (immutable, read-only) | Rows | SHA-256 (prefix) | Source class | Rights |
|---|---|---|---|---|---|
| NSE EOD bhavcopy 2015–2026 | `D:\Model\NEW DATA\nse_eod_bhavcopy_2015_2026_full.csv.gz` | 5,232,265 bars | `4df01085a17f2bd2…` | `OFFICIAL_EXCHANGE_RECORD` | official NSE records, personal-research use per `D:\Model\NEW DATA\MANIFEST.md` |
| Index membership history | `D:\Model\data\reference\nse_index_membership_history.csv` | 6,525 spells | `75ebfac3b5d1fb22…` | `PRESS_RELEASE_RECONSTRUCTION` | **CC BY 4.0** — attribution carried on every warehouse row |
| Symbol renames | `D:\Model\data\reference\nse_symbol_renames.json` | 40 entries (39 unique) | covered by membership run | rename registry | same dataset as membership (CC BY 4.0) |
| NIFTY 50 total-return index | `D:\Model\NEW DATA\nifty50_tri_history.csv` | 5,385 sessions | `d92d1a975c473209…` | `OFFICIAL_EXCHANGE_RECORD` | official NSE Indices history via niftyindices.com |
| yf_cache vendor snapshots | `D:\QP\agent-service\data\yf_cache\` | 103 symbols | n/a (runtime cache) | `VENDOR_RECONSTRUCTION` | Yahoo Finance snapshots — **fallback only**, never a substitute for an official bar |

Archive build: **2026-09-18** (`MANIFEST.md`: "India market data extraction —
free-source stack"). The bhavcopy archive is the consolidation of the two NSE
formats (pre-2024 legacy / 2024+ UDiFF) fetched from
`nsearchives.nseindia.com`. No source file is ever edited; the warehouse is
derived, rebuildable data.

## 2. Bar coverage

- **2,777 sessions** from **2015-01-01** to **2026-09-17**; **4,675 distinct
  symbols**.
- Series mix: **EQ 4,689,609 · BE 416,032 · BZ 64,266 · ST 62,358** (bars keyed
  by `(session, symbol, series)`; research joins default to EQ).
- Sessions per year: 2015:247 · 2016:246 · 2017:248 · 2018:246 · 2019:244 ·
  2020:250 · 2021:248 · 2022:248 · 2023:245 · **2024:132 (gap, §3)** ·
  2025:248 · 2026:175 (through 2026-09-17).
- Prices are stored **exactly in paise** (Decimal parse; a value that cannot
  be represented exactly is rejected, never rounded).
- Five clocks on every row (blueprint §5.1): economic period = trading
  session; `published_at` = session date (official EOD publication);
  `first_seen_at` = archive capture; **`available_at` = session + 1 local day
  + 15 min IST** (the runtime's disclosed daily-bar completion rule). Every
  join enforces `available_at <= decision`; a 16:00 IST decision therefore
  acts only on the *prior* session's close.

## 3. Known gaps — recorded as non-success states, never interpolated

| Gap | State | Cause | Research consequence |
|---|---|---|---|
| **2024-01-01 → 2024-06-20** | `MISSING_SPAN` (0 sessions ingested) | the 2026-09-18 archive run was partial for H1 2024 (`archive/nse_eod_bhavcopy_103day_partial_2024-06-21_2024-11-18.csv.gz`); ~115 sessions absent | any label/panel window crossing H1 2024 must abstain or disclose the hole; never fill from another vendor without the `VENDOR_RECONSTRUCTION` label |
| **2026-09-18 → present** | `MISSING_SPAN` (official) | archive ends 2026-09-17; newer sessions exist only in yf_cache vendor snapshots | official-bar joins return a typed miss; yf_cache may be used only with `source_class=VENDOR_RECONSTRUCTION` |

Policy: a gap is a **typed, queryable state** (`coverage_report()`), not
silence. No bar is invented, adjusted, backfilled, or borrowed from a later
schedule. `next_session_after()` returns only *observed* sessions, so a
missing span is visible as a jump, never smoothed.

## 4. Point-in-time membership

- 6,525 spells across 42 indices, `valid_from` from **2014-01-01**; index id
  217 = nifty50. Source rows: `press_release` 4,061 · `snapshot_floor` 2,435 ·
  `snapshot` 24 · `merger` 4 · `amendment` 1.
- Knowability classes returned by `members_at()`: **VERIFIED** (strict rows
  only: press_release / merger / amendment), **PARTIAL** (snapshot_floor
  included — a backward-walk *upper bound*, disclosed), **UNKNOWN** (no
  coverage → abstain, never "assume stayed").
- As-of membership is the anti-survivorship mechanism: a decision date only
  sees spells knowable then, so delisted members appear inside their spells
  (tested: `test_asof_index_membership_no_survivorship`).
- **PIT probe (nifty50 @ 2020-01-01):** 50 members (36 weak rows included →
  PARTIAL); panel probe: **50/50 members with bars**. The two members the
  first build honestly excluded (`INDUSTOWER`, `TMPV` — new names that did
  not exist yet in 2020) are resolved by the instrument-identity alias rule
  (§5); they had bars under pre-rename names (`INFRATEL`, `TATAMOTORS`).

## 5. Symbol renames — identity vs naming

The source contains 40 entries; 39 unique after in-file dedup: **25 with a
verified calendar date, 13 undated (`effective_date: null`), 1 placeholder
(`2026-01-XX`, LTIM→LTM: month known, day unknown).** Warehouse policy,
fail-closed on dates:

- **Instrument identity is unconditional.** Bars follow the *instrument*: a
  canonical-symbol query always includes the instrument's pre-rename raw
  symbols (`alias_symbols_at`, deduplicated; no-op rows like MFSL→MFSL are
  dropped). Renames prove "same instrument" with or without a date.
- **Display naming is date-gated and fails closed.** `canonical_symbol()`
  applies a rename only when its effective date is a verified calendar date;
  undated and placeholder renames never retroactively rename history.
- **Verified-action mirroring is gated.** Only verified-dated renames mirror
  into `corporate_actions` as factor-1.0 `symbol_change` rows (verified=1);
  the 25 valid-dated renames collapse to 22 mirrored actions on the
  `(symbol, kind, effective_date)` key (the LTM and MOTHERSON families share
  effective dates). No `2026-01-XX` or undated row is ever mirrored as
  "verified". (An earlier build mirrored the placeholder; the renames block
  is re-derived from the immutable source on every run, so the repair is
  recorded in `pit_source_integrity.json` →
  `sources.nse_index_membership_history.renames`.)
- ISIN (carried on every bar) is the future hard identity; alias-by-rename is
  the fallback until W2 lands ISIN-keyed joins.

## 6. Corporate actions

Unknown or unverifiable actions **abstain** (`adjustment_factor` returns
`UNKNOWN`); no factor is ever guessed. Verified renames mirror as §5. Price
adjustment bases are stamped per bar (`adjustment_basis`), so research never
mixes unadjusted and adjusted series silently.

## 7. Fee coverage

Fee truth derives from verified charge references, not AI-answer tables. The
active schedule (`nse-cm-delivery-2026-03-01`) is effective **2026-03-01
onward**; label windows before that date are **gross-only** with
`charges_status = SCHEDULE_UNAVAILABLE_BEFORE_EFFECTIVE_DATE` and net metrics
`None`. A window is never priced with a later schedule. All fee arithmetic is
integer paise (`economics.py`), reconciled by size/side/date in tests.

## 8. Rights and licensing

- **Bhavcopy / TRI:** official NSE / NSE Indices records assembled
  2026-09-18 for personal research per `MANIFEST.md` ("All sources
  free/public. Personal-research use"). Not for redistribution as a dataset.
- **Membership + renames:** CC BY 4.0. Attribution string carried on **every
  membership row** in the warehouse:
  > Membership: Jha, A. (2026). NSE Historical Membership (Point-in-Time).
  > github.com/aditya-jha/nse-historical-membership. Derived from public NSE
  > Indices Limited press releases and NSE Exchange circulars. CC BY 4.0.
- **yf_cache:** vendor snapshots, fallback only, always labelled
  `VENDOR_RECONSTRUCTION` — a research output that used it must say so.
- No scraped data enters the warehouse from paywalled or ToS-restricted
  sources; tick-by-tick NSE history has no free source (`MANIFEST.md` §4) and
  the W1 labels do not need it (OHLC at decision/exit granularity).

## 9. Labels every research output must carry

| Label | Meaning |
|---|---|
| `RETROSPECTIVE` | backtest over pre-archive history — a reconstruction of contemporaneously published official records, stamped on the source and carried onto every report |
| `OFFICIAL_EXCHANGE_RECORD` | bar from the audited bhavcopy / TRI archive |
| `VENDOR_RECONSTRUCTION` | bar/snapshot from yf_cache fallback |
| `PRESS_RELEASE_RECONSTRUCTION` | membership spell from the CC BY 4.0 dataset |
| `SURVIVOR_BIASED` | **prohibited** — membership is always as-of (`members_at`); a result computed on today's index list may not be presented |
| `SCHEDULE_UNAVAILABLE_BEFORE_EFFECTIVE_DATE` | gross-only window before 2026-03-01 fee truth |

## 10. Rebuild and idempotency

The warehouse DB
(`backend-extension/data/research_v3/warehouse.sqlite3`, ~1.32 GB) is derived
and rebuildable from the immutable sources; append-only with
`INSERT OR IGNORE` everywhere. Idempotency is proven in practice: the
re-ingest run of 2026-11-12 reported **5,232,265 rows, all duplicates
ignored**, with unchanged source hashes. The renames block (single-source
tables `symbol_renames` and renames-sourced `corporate_actions`) is
re-derived from source on every run, so code-gate repairs apply without
touching bars, spells, or the benchmark.

## 11. Open items

1. **2024 H1 gap**: obtain a verified official-bar source for
   2024-01-01→2024-06-20 before any label window that crosses it (W2 must
   exclude those sessions until then).
2. **Corporate actions (split/bonus/dividend/consolidation) unverified**: no
   verified local source exists; adjustment abstains UNKNOWN and no factor is
   ever imputed from price gaps. Until a verified actions dataset is ingested,
   any strategy-vs-TRI comparison over raw prices is NOT economically
   interpretable — the W1 reproduction quantifies 31 contaminated name-month
   windows instead of guessing.
3. **2026-09-18→present**: keep vendor snapshots labelled; ingest a newer
   official archive when available.
4. Membership strict coverage is thin pre-2018 (`snapshot_floor` spells) —
   pre-2018 universes are PARTIAL upper bounds; disclose on every use.
5. ISIN-keyed identity joins land with the W2 strategy panel (alias-by-rename
   is the current fallback).
