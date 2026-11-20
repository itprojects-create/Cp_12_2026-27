# LLM & AI-Agent-Based Stock Trading (Especially Short-Horizon Daily Directional) — Empirical Evidence Audit
*Compiled November 2026. All web-verified this session; pre-2025 findings labeled [pre-2025]. Every claim carries a URL/DOI. "Author-reported" = numbers from the paper's own authors/editors, no independent replication found. "Independent" = separate-party test or audit.*

**Bottom line up front:** After four years of papers, one peer-reviewed result (Lopez-Lira & Tang, now in the *Journal of Financial Economics*, Oct 2026) shows LLM news-sentiment scores capturing a *non-tradable* same-day reaction plus a mild post-news drift on small/negative-signal stocks — and the paper's own v6 revision explicitly reports that strategy returns *decline as LLM adoption rises*. The 2024–2025 "agentic trading" wave (FinMem, FinAgent, TradingAgents) produces impressive backtest headline numbers but a 2026 peer-venue survey of all 19 studies with closed-loop evaluation found only 1/19 reports an explicit transaction-cost model, 1/19 handles survivorship, 15/19 are code-level unreproducible (R0), and 0/19 reaches full reproduction (R3) — i.e., **no agentic-LLM system has produced a reproducible, cost-adjusted, out-of-sample-return verified alpha**. The one real-money "AI picks the stocks" product with public NAV (AIEQ, IBM Watson, live since 2017) trails the S&P 500 ~100% cumulative returns vs ~200% over ~9.5 years as of Aug 2026. Industry deployment is overwhelmingly at the analyst/research layer, not the portfolio-decision layer.

---

## Key Question 1: Key papers and their honest takeaways

### Takeaway
The only LLM-in-equities result that is peer-reviewed at a top finance journal (Lopez-Lira & Tang, JFE Oct 2026) reports sentiment-score *predictability* that has a specific risk-controlled structure (negative news, small caps) and is **already decaying by construction** ("strategy returns decline as LLM adoption rises"); the celebrated 90% "hit rate" is explicitly tagged by the authors as the non-tradable same-day reaction. The famous agentic-trading claims (FinMem, FinAgent, TradingAgents) are author-reported backtests over short single-name/narrow windows, carried in conference venues (AAAI Spring Symposium 2024 / arXiv / NeurIPS 2025 poster), with none independently replicated and most missing costs/protocol details per the 2026 audit survey.

### Cited Findings

**Lopez-Lira & Tang — "Can ChatGPT Forecast Stock Price Movements? Return Predictability and Large Language Models"** [pre-2025 origin (v1 Apr 15, 2023), final JFE publication 2026]
- First posted to arXiv on Apr 15, 2023 (v1); last revised Oct 28, 2025 (v6); SSRN version has been designated "Journal of Financial Economics, forthcoming" — SSRN page: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4412788
- Published: *Journal of Financial Economics*, Vol. 184, Oct 2026, article 104335 — https://doi.org/10.1016/j.jfineco.2026.104335 (listing: https://www.sciencedirect.com/science/article/abs/pii/S0304405X26001066)
- v6 author-reported headline (quoting the abstract): "Using post-knowledge-cutoff headlines, GPT-4 captures initial market responses, achieving approximately 90% portfolio-day hit rates **for the non-tradable initial reaction**. GPT-4 scores also significantly predict the **subsequent drift, especially for small stocks and negative news**… Strategy returns **decline as LLM adoption rises**, consistent with improved price efficiency." — arXiv abstract: https://arxiv.org/abs/2304.07619 — i.e., the authors themselves scope the effect to the (untradable) day-zero reaction plus a small-cap/negative-news drift, and report decay, not a durable tradable alpha.
- Note for the history of this paper's claims: the early (2023, pre-2025) arXiv/SSRN/press-storm versions were widely publicized as ChatGPT predicting stock returns on news headlines; final published framing is much more measured (see above). The SSRN page carries the JFE-forthcoming note: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4412788

**FinGPT — open-source financial LLM for sentiment/data tasks** [pre-2025]
- Defined in "FinGPT: Open-Source Financial Large Language Models" (Yang, Liu, Wang; arXiv 2306.06031, June 2023; SSRN mirror 4489826) — https://arxiv.org/html/2306.06031v2 ; https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4489826
- The data-engineering companion paper was shown at NeurIPS 2023 Datasets & Benchmarks ("Democratizing Internet-scale Data for Financial Large Language Models"): https://neurips.cc/virtual/2023/79667
- FinGPT is, honestly, a *sentiment-classification and data-processing* model stack, not a portfolio agent: its demonstrations are news-sentiment classifiers; the flashy return claims live in separate FinGPT-Benchmark papers (author-reported; see Gaps — I could not verify a specific ROI number this session, so none is asserted here).

**BloombergGPT — Bloomberg's 50B-parameter finance LLM** [pre-2025]
- Claim: "outperforms similarly-sized open models on financial NLP tasks by significant margins" (Bloomberg press release, Mar 30, 2023, *not a journal publication*, no trading P&L disclosed) — https://www.bloomberg.com/company/press/bloomberggpt-50-billion-parameter-llm-tuned-finance/ ; paper: arXiv 2303.17564 — https://www.alphaxiv.org/abs/2303.17564
- Independent counter-evidence: Li et al., "Are ChatGPT and GPT-4 General-Purpose Solvers for Financial Text Analytics?" (EMNLP 2023 Industry Track) found **GPT-4 outperforms BloombergGPT** (e.g., FinQA zero-shot: GPT-4 68.79% vs BloombergGPT 43.41%) and that a fine-tuned BERT still beats 5-shot GPT-4 by ~9% F1 — https://aclanthology.org/2023.emnlp-industry.39.pdf
- Honest takeaway: pre-2025 result — a domain LLM was superseded within 2 months by a general frontier LLM on public benchmarks; no evidence of deployment for trading decisions was ever published.

**FinMem — layered-memory LLM trading agent** [pre-2025 (SSRN Nov 2023), peer presentation 2024]
- Published version: AAAI Spring Symposium (AAAI-SS-24) proceedings, "FinMem: A Performance-Enhanced LLM Trading Agent With Layered Memory and Character Design" — https://ojs.aaai.org/index.php/AAAI-SS/article/view/31290
- Author claim (proceedings abstract): a "cutting-edge LLM agent framework for automated trading, boosting cumulative investment returns" — same URL. Code/data public: https://github.com/pipiku915/finmem-llm-stocktrading
- Honest caution: results are backtests over a limited set of ticker/time-window choices; the 2026 audit survey codes FinMem among the closed-loop studies with missing cost models and split-protocol disclosures (see Key Q3). No independent replication of FinMem's return numbers surfaced in this session.

**FinAgent — multimodal trading agent** [pre-2025 (Feb 2024)]
- "A Multimodal Foundation Agent for Financial Trading: Tool-Augmented, Diversified and Generalist" (Zhang et al., arXiv Feb 2024). Author-reported: "**92.27% annual return on TSLA (84.39% relative improvement)** and averages over **36% profit improvement across six datasets** against 12 baselines" — https://www.researchgate.net/publication/383466825_A_Multimodal_Foundation_Agent_for_Financial_Trading_Tool-Augmented_Diversified_and_Generalist ; secondary summary: https://luneresearch.com/papers/2a7634f0-d239-4acb-b16f-ad3ee35f21da
- Honest caution: headline number is a single ticker in a single period-window interpretation by the authors; not independently replicated in any venue identified this session; and it is one of the specific papers the 2026 ESWA survey flags for missing execution/cost/split protocol.

**TradingAgents — multi-agent LLM trading framework** [2024–2025]
- arXiv 2412.20138 (Dec 2024), Xiao, Sun, Luo, Yang, Sun, Wang (UCLA/Aalborg group) — https://arxiv.org/abs/2412.20138
- Peer-reviewed status: **accepted as a NeurIPS 2025 poster** (OpenReview, "Published: 18 Sept 2025") — https://openreview.net/forum?id=4QPrXwMQt1 (confirmatory search listing: https://openreview.net/search?term=~Yijia_Xiao1)
- Author-reported exposures: framework "improves performance metrics like cumulative returns… versus baseline models" (huggingface summary: https://huggingface.co/papers/2412.20138); the project page claims "**up to 30.5% annualized return (AAPL, June–November 2024 backtest)**" — https://tauric.ai/research/tradingagents — a ~5.5-month window annualized from ~26.62% cumulative return on a single stock (third-party restatement: https://www.ai-tradingagents.com/blog/tradingagents-multi-agent-framework/)
- Authors' own reproducibility disclaimer (official repo README): "**Backtest results are not guaranteed to match any published figure. Returns depend on the model, the temperature, the date range, data quality, and the sampling...**" — https://github.com/tauricresearch/tradingagents

**The Losing Winner: An LLM Agent That Predicts the Market but Loses Money** [2025 — the crucial counterpoint]
- NeurIPS 2025 workshop paper (Generative AI in Finance workshop), Jang, Kim, Zhang — https://neurips.cc/virtual/2025/132549 ; OpenReview: https://openreview.net/forum?id=FzahgVWy59
- Fine-tuning Qwen2.5-3B-Instruct with RLVR on daily BTC 3-class direction gave "**significantly higher classification accuracy**… but …**lower cumulative return than the baseline**," attributed to "objective mismatch and reward hacking" — i.e., direction-accuracy ≠ P&L even in a benign single-instrument setting. (Bitcoin, daily horizon — labeled here as crypto, not equities.)

**2026 audit surveys (independent, peer-venue-tracked syntheses)**
- Xia, You, Wang, Liu, Qi, Wu, Zhang, "Agentic Trading: When LLM Agents Meet Financial Markets" (*Expert Systems with Applications*; arXiv 2605.19337, May 2026; protocol-coded ledger screened through 2026‑03‑09): of 92 candidate records, 77 included, **only 19 qualify as closed-loop empirical trading-agent studies**, and within them: "2/19 report extractable split protocols, **1/19 reports an explicit transaction-cost model**, 1/19 documents universe or survivorship handling, 11/19 report execution timing, 15/19 are R0 [no reproducible artifacts], and **no study reaches R3 reproducibility**" — https://arxiv.org/html/2605.19337v1 and https://arxiv.org/abs/2605.19337
- Zhang & Zhang, "A Review of Large Language Models for Stock Price Forecasting from a Hedge-Fund Perspective" (accepted IEEE conference, May 8–10, 2026; arXiv 2605.05211, Apr 2026) stresses the practical pitfalls "often understated in the literature": "fragility in sentiment analysis, dataset and horizon design, performance evaluation metrics, **data leakage, illiquidity premia, and limits of stock price predictability**" — https://arxiv.org/abs/2605.05211

**Independent replication-type tests of LLM "alpha"** [2025]
- LoGrasso, "Could ChatGPT have earned abnormal returns? A retrospective test from the U.S. stock market," *Modern Finance* 3(3):112–132, published Sep 14, 2025, doi **10.61351/mf.v3i3.327** — https://mf-journal.com/article/view/327
  - Design: GPT-4 asked (with knowledge restricted to pre-selection date) to pick 10 US stocks each July 1, 1985–2021; portfolios held 24 months, price-weighted; alphas tested vs CAPM/FF3/FF5/FF3+mom+rev.
  - Author-reported result: average 24-month cumulative abnormal return 27.24% (p < 0.001) *driven by some standout years* ("positive and significant alphas in only about one out of four years and **never** negative and significant"); regressions on all 888 months put monthly alphas at +0.48% to +0.94% but **statistically insignificant** (all four models, with year fixed effects); betas ≈ 1.02–1.12; selection is dominated by large-cap growth tech (MSFT picked in 34 of 37 years; negative SMB and HML loadings, p < 0.001); turnover ~26%/yr with returns *before* transaction costs.
  - Caveats I flag (inference, below): 2-year holding-period draws on GPT-4's memory of which historical firms became legends; this is a "post-diction potential" risk not fully controlled by the prompt. Not a daily-direction horizon at all (24-month holds).

### Inferences
- The credible, peer-reviewed evidence for an "LLM edge" is **a fast-news reaction phenomenon**, not an agentic-trader phenomenon: same-day initial reactions that are too fast to monetize (authors' own "non-tradable" wording), plus small, systematically concentrated drift in small caps and negative news.
- The celebrated agentic papers (FinMem/FinAgent/TradingAgents) form a literature whose headline returns are single-name or small-short-window artifacts of design choices; none of their return numbers has a public independent replication, and their own repos concede run-to-run non-determinism.
- BloombergGPT's quick obsolescence by GPT-4 (EMNLP 2023) is a warning pattern seen again with every "specialized finance LLM": open general models dominate within months, so any backtest pinned to a December-2024-era model's behavior may be a statement about that snapshot, not a durable edge.
- LoGrasso's result reads as evidence that GPT-4's "stock-picking" is bundled pantomime of textbook large-cap growth factors plus noise — positive expected-but-insignificant alpha and no statistical blowup after benchmarking; not a demonstration of a machine-discovered anomaly.

### Gaps
- I could not verify, in this session, any **independent replication** re-running FinMem, FinAgent, or TradingAgents end-to-end and confirming their returns (the TradingAgents repo itself explicitly disclaims reproducibility). If any exists, it is not surfaced on arXiv/AGU/OpenReview surfaces searched here.
- FinAgent's final peer-review venue (it circulates only on arXiv/luneresearch mirrors) could not be pinned down; treat its venue as "arXiv (Feb 2024), venue unverified."
- The FinGPT-Benchmark papers make in-sample "outstanding ROI" claims (author-reported only); precise numbers were not verified this session to avoid quoting without a URL, so treat any "FinGPT yields +X%" claims found elsewhere as **author-reported, unreplicated** until checked.
- The pre-JFE press-era claims from early L&T versions (2023) of large *tradable* daily returns could not be verified with specific numbers this session; the JFE abstract states only the 90% "portfolio-day hit rate" figure for the *non-tradable initial reaction*.
- No paper found quantifying decimal "sharpe-adjusted net alpha of TradingAgents-style agents in production"; production numbers (if they exist at any fund) are not published.

---

## Key Question 2: Mechanism of the observed edge; alpha decay after publication

### Takeaway
What survives at the published endpoint is news-timestamp-driven, same/next-day underreaction information that is (a) mostly locked into the instant-of-publication price move itself (non-tradable) and (b) largest for small caps and negative news — with the paper's own reporting that **strategies' returns decline as LLM adoption rises**. There's also generic alpha-decay literature (post-publication drift to zero is the norm in quant signals [pre-2025]). There is **no demonstrated mechanism by which an LLM predicts Tuesday's large-cap daily direction out of plain data without news.**

### Cited Findings
- Lopez-Lira & Tang v6 abstract (JFE 2026; arXiv v6 Oct 28, 2025): "accurately predicting stock price movements based on news headlines"; the strategy's return contribution (v6 language): "Strategy returns **decline as LLM adoption rises**, consistent with improved price efficiency" — https://arxiv.org/abs/2304.07619 (finding labeled 2026 publication; phenomenon documented pre-2025).
- Same repo records: "…achieving approximately **90% portfolio-day hit rates for the non-tradable initial reaction**. GPT-4 scores also significantly predict the subsequent drift, especially for **small stocks and negative news**" — same URL. Interpretation: essentially the event-day return is booked within the first move before an analyst-level LLM can be queried per day — consistent with the entire tradable part being the small post-news drift.
- The audit survey (ESWA, 2026) identifies "**Strategy Crowding and Alpha Decay**" as a first-class concern for LLM-agent markets and cites alpha-decay literature in its §11.3 — https://arxiv.org/html/2605.19337v1
- Independent historical-decay context [pre-2025]: López de Prado, "The 10 Reasons Most Machine Learning Funds Fail," *Journal of Portfolio Management* 44(6):120–133 (2018), doi 10.3905/jpm.2018.44.6.120 — cited by the 2026 survey in its look-ahead/leakage section as an established reference for overfitting/leakage traps; available via https://doi.org/10.3905/jpm.2018.44.6.120
- A second independent, non-LL&T test of "ChatGPT alpha" (LoGrasso, *Modern Finance*, Sep 14, 2025, doi 10.61351/mf.v3i3.327) also reports positive-but-insignificant monthly alpha across eight рынkbd888 months (1985–2021, GPT-4 picks, 2-year holds), reinforcing "no durable tradable monthly-day alpha; just mild leakage of known good-firm names." — https://mf-journal.com/article/view/327

### Inferences
- If an LLM-signal edge exists in equities, it lives at **micro-scope (event day) and on the slow end (drag)** — not at day t+1/t+2 broad-market horizon which the practical deployment literature has not demonstrated profitably.
- **Post-publication arbitrage** is already described by the authors themselves (declining returns as adoption rises). The paper does not quantify the post-JFE beta; treat the decay as self-reported direction, not a measured half-life.
- Nothing found demonstrates LLM alpha in **multi-day holding on large caps net of costs**. The one paper explicitly claiming such numbers (TradingAgents, NeurIPS 2025 poster) tests a single name over ~5.5 months and disclaims run-to-run durability (https://github.com/tauricresearch/tradingagents).

### Gaps
- No documented, quantified **post-publication half-life curve** of the L&T signal (no follow-up replication study located).
- No measure of the residual alpha in the L&T drift after **realistic execution** (the drift is reported in "score-sorted portfolio" space; transaction-cost-inclusive net-of-cost figure was not retrievable from the abstract page; per-paper text locked behind JFE paywall).

---

## Key Question 3: Documented failure modes (leakage, hallucination, run-variance, sycophancy, costs, overfitting)

### Takeaway
The 2026 ESWA audit gives the strongest quantified evidence: in 19 closed-loop empirical LLM-trading studies, only **1/19 includes an explicit transaction-cost model**, only **1/19 handles universe/survivorship**, **15/19 are "R0"** (no reproducible artifacts), and **0/19 reach R3**. The survey's own neutral diagnosis: "The literature is likely affected by **survivorship bias at the survey level as well as at the backtest level**." Direction-accuracy ≠ net P&L is demonstrated (NeurIPS 2025 "Losing Winner"). LLM-specific failure modes (hallucination look-ahead, temperature-instability) are named in surveys but are *rarely fronted empirically* (N = 1 and N = 0 respectively, i.e., almost no primary study foregrounds them).

### Cited Findings
- **Protocol incomparability / cost omission / unreproducibility (2026 audit):** "…2/19 studies report extractable time-consistent split protocols, **1/19 reports an explicit transaction-cost model**, 1/19 documents universe or survivorship handling… 15/19 are coded as R0, and no study reaches R3 reproducibility" — Xia et al., ESWA / arXiv 2605.19337, screened through 2026-03-09 — https://arxiv.org/html/2605.19337v1 and https://arxiv.org/abs/2605.19337
- **Survivorship-bias at the survey level and negative results:** "…Few papers report failed prompts, abandoned reward schemes, degraded live performance, or architectures that increased turnover without improving net returns. We therefore interpret the absence of negative results as a reporting limitation…" — same survey, §13.3 "Negative Results and Failed Designs" — https://arxiv.org/html/2605.19337v1
- **Look-ahead bias named, not empirically measured:** the survey's §13.1.2 states look-ahead bias occurs when "models inadvertently access future information during [training/evaluation], producing unrealistic performance estimates" and notes **N = 0 primary studies explicitly foregrounding it**; it prescribes strict time-ordered splits, walk-forward, and cites López de Prado (2018) for degradation-under-proper-time-holdout patterns — https://arxiv.org/html/2605.19337v1
- **Knowledge-cutoff leakage, defensive design:** the only fully-operational countermeasure to LLM-cutoff contamination in a live flagship paper is the L&T v6 design — "**Using post-knowledge-cutoff headlines**" so the model cannot have memorized past-market reactions — https://arxiv.org/abs/2304.07619 (i.e., cutoff leakage is a named risk the leading authors had to engineer around; the implication for a *contaminated* backtest design is: results do not connect to deployable models.)
- **Hallucination→losses:** survey's §13.1.1 documents only **1 of 19 primary studies** explicitly foregrounding hallucination; it spells out loss-creation mechanics: "hallucinated claims propagate through tool calls into downstream actions… a fabricated earnings report can trigger: Erroneous position entry (immediate loss when corrected)… Confidence-based position scaling (larger losses due to false certainty)" — https://arxiv.org/html/2605.19337v1
- **Run-to-run non-reproducibility (temperature, sampling), directly conceded by the code's own maintainers:** "Backtest results are not guaranteed to match any published figure; Returns depend on the model, the **temperature**, the date range, data quality, and the **sampling**…" — TradingAgents official repo README — https://github.com/tauricresearch/tradingagents (2025)
- **Objective mismatch: more accuracy, less money:** "The Losing Winner" — fine-tuned Qwen2.5‑3B + RLVR beat the baseline on classification accuracy but **lost money in trading simulation**; reward was a discrete correct-classification regime not aligned with magnitude/risk of price moves — https://neurips.cc/virtual/2025/132549 ; https://openreview.net/forum?id=FzahgVWy59 (2025)
- **Deflated-Sharpe / backtest-overfitting framework [pre-2025] (canonical methods your own workflow needs):**
  - Bailey & López de Prado, "Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality in Portfolio Strategy Selection" (*JPM*, 2014) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
  - Bailey, Borwein, López de Prado, Zhu, "The Probability of Backtest Overfitting" (*Journal of Computational Finance*, 20(4), 2017) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
  - Bailey, Borwein, López de Prado, Zhu, "Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance" (*Notices of the AMS*, 61(5), May 2014, p. 458) — https://www.ams.org/notices/201405/rnoti-p458.pdf
  - Harvey, Liu, Zhu, "…and the Cross-Section of Expected Returns" (*RFS* 29(1), 2016, doi 10.1093/rfs/hhv059) — the multiple-testing/t-stat haircut framework that prices the false-discovery risk in anomaly-hunting, LLM or otherwise — https://doi.org/10.1093/rfs/hhv059
- **First-quant caution applicable verbatim to LLM agents [pre-2025]:** López de Prado, "The 10 Reasons Most Machine Learning Funds Fail," *JPM* 44(6), 2018, doi 10.3905/jpm.2018.44.6.120 (leakage/backtest-overfitting/cost-understatement patterns) — https://doi.org/10.3905/jpm.2018.44.6.120
- **Sycophancy / prompt-framing sensitivity:** no equity-trading-specific study located this session. Closest evidence: the "Losing Winner" objective-mismatch structure (prompt framing determines reward alignment): https://neurips.cc/virtual/2025/132549 and the LoGrasso "precision needed to induce the GPT-4 model to provide any recommendations" design note in doi 10.61351/mf.v3i3.327 — both indicate prompt-related fragility rather than clean prompt-injection-style sycophancy studies. **Label: Inference-unverified — flag for reader.**

### Inferences
- The normalized target-failure is **overfitting under incomplete leakage-avoidance** — the cost-theft shape churned by backtests is the repeated signal. Combined with the survey's own "survivorship at survey level" quote, the practical inference is: **any agentic-LLM backtest without a time-split-protocol disclosure should be read as probably overfit.**
- The "TradingAgents-style" run-to-run instability (temperature, sampling) means an observed backtest result has an unquantified **posterior variance across re-runs**; averaging over the RNG kills most of the apparently-comfortable edges. The paper-writing authors flag this themselves.
- Hallucination→overconfidence isn't a hypothesis, it is the mechanism by which an agentic trader can deploy leveraged² maths: even 1 hallucination among 50 signals destroys the annual P&L (survey §13.1.1's "confidence-based position scaling" mechanism).
- **Deflated Sharpe should be the standard audit lens** for any LLM-agent backtest: 19 in-sample agentic experiments × 6–12 hyperparameter choices × small windows ≈ a multiple-testing n of hundreds; even a deflated/backtest-overfitting audit would leave several expected false "2-sigma Sharpe" hits. A DSR-correlation analysis of the published agentic backtests is missing from the literature (see Gaps).

### Gaps
- **Sycophancy-to-prompt-framing in an equity-trading context was not found with a direct empirical paper this session.** Open follow-up: a controlled study looping the same news event into LLM agents for both "technical analyst" frame and "value quiz" frames to detect decision-flip rates.
- No direct honest-size replication of Bailey-CL operational Backtest-Overfitting statistics for LLM agent papers (a "Deflated-Sharpe post-backend risk" of, e.g., the FinAgent 92% claim remains unpublished).
- Attribution of LLM agent performance on **execution-level cost attribution** (what would gross alpha remain net of slippage) not present in any of the 19 primary studies the survey coded, except the 1 that did cost modeling (which paper that was couldn't be pinned down this session).

---

## Key Question 4: Industry reality — who actually deploys LLMs in trading, and how

### Takeaway
Verified evidence this session strongly supports the "LLM as analyst/summarizer, not as Portfolio Manager" division: adoption metrics are high for *research integration* (41% of 100+ hedge fund managers rank AI integration a top-3 2026 priority in a Hedgeweek survey) — but the flagship literal "AI picks stocks" product with public live NAV (AIEQ, launched 2017 on IBM Watson, run by EquBot and since managed under Amplify ETFs) has **trailed long-term by ~100 SP percentage points (≈100% vs ≈200% since 2017)** as of 2026 reporting. No disclosed P&L of any LLM-as-decision-maker book was found this session; what deployment exists is research-layer.

### Cited Findings
- **AIEQ live track record (real assets, real NAV, 2017–present):**
  - "Since 2017, **AIEQ gained 100% while the S&P 500 returned nearly 200%**, exposing AI stock-picking's persistent long-term underperformance." (Aug 26, 2026 commentary with cumulative-return data, https://247wallst.com/investing/2026/08/26/can-ai-help-you-beat-the-stock-market-the-answer-may-surprise-you/)
  - Comparison-date-anchored (Jan 2024 → Aug 2026 window): "AIEQ has **trailed [IVV] by close to 12% since January 2024**" — https://seekingalpha.com/article/4915859-aieq-sophisticated-ai-driven-strategy-that-underperforms-reiterate-hold
  - Fund page (Amplify AI Powered Equity ETF; IBM Watson platform): https://amplifyetfs.com/aieq/ ; Morningstar performance page: https://www.morningstar.com/etfs/arcx/aieq/performance
  - Alternative long-view breakdown (independent analytics-site summary, low authority; cite only as supporting view): https://financegrub.com/can-ai-predict-the-stock-market-eight-years-of-a-real-ai-fund/
  - Key discriminating note: AIEQ **is** a genuine deployed AI-portfolio-manager product (not a paper); its NAV vs S&P is the cleanest "LSTM/ensemble/Watson-type model as PM vs index" datapoint — it does NOT measure LLM-agents specifically, but it is the industry's longest-running public "AI layer decides" live test.
- **Hedge-fund manager sentiment on AI (2026 survey):** "According to the Hedgeweek Q1 2026 Global Outlook Survey of more than 100 hedge fund managers, **41% now rank AI integration [into their process among their top priorities]**" — https://hedgeweek.com/news/hedge-funds-rank-ai-as-their-number-top-priority-but-experts-say-they-may-be-ignoring-this-blind-spot
- **How funds actually use LLMs (market-color, July 2026 — industry reporting):** Bloomberg (Jul 1, 2026): "Banks are rolling out AI assistants; hedge funds are **weaving large language models into research and trading**, and financial advisers…" with researchers warning of new risk: "AI, Forging New Risks, Isn't a Market Wizard After All… AI models could make hedge fund trading riskier, Wall Street researchers warn" — https://www.bloomberg.com/news/newsletters/2026-07-01/ai-models-could-make-hedge-fund-trading-riskier-wall-street-researchers-warn (paywalled; headline/lead verified via search snippet)
- **Deployment taxonomy (vendor/SMB secondary summary, backed by AIMA survey data, cite with caution):** LLM use cases at hedge funds = "advisor: summarization, event transcripts, secondary research, compliance prep" (analyst/summarizer layer, not PM): https://sesen.ai/services/llm-use-cases-hedge-funds ; "95% of fund managers use generative AI" (bloguly, self-classified 'consultant' data quality, 2026, author detail is a personal consulting-commodity page — *low-authority source, use as market color only, not as a basis for claims*): https://www.tommasomariaricci.com/blog/ai-for-hedge-funds
- **AI ETF ecosystem context:** AIEQ is the only long-running continuously-listed "AI-managed" ETF product flagged in searches as a benchmark-losing live product (see above); a comprehensive tracker/report of "which brokers use LLMs in execution commentary" did **not** surface in this session's scope.

### Inferences
- The observed reality is qualitative: read-synthesis and summarization in research workflows, and *rare*, tightly-supervised decision-layer inclusion. There is no public LP report or ETF NAV series that validates an LLM-agent in the "daily-trade-direction book" role.
- The strongest **market-based counter-evidence** against "AI-PM" hype is the only live, listed AI-decides product: trailing by ~100 SP-points over ~9.5 years — a real, public, independent reading of the "AI can beat markets" thesis.
- Institutional reporting elsewhere (Bloomberg, July 2026 [above]) points to adoption-risk escalation rather than instant verified alpha (the "risk" they warn of, not the "P&L").

### Gaps
- **No disclosed P&L of any LLM-driven trading book was found** (private funds do not publish; the ETF vehicle is not LLM-dependent per se).
- Specific named hedge funds' deployment contracts (e.g., whether a specific quant shop lets LLM output feed allocation directly) could not be confirmed this session; vendor-service summaries do not substitute for industry reporting.
- No public tracker of LLM-execution-desk or "AI execution commentary" products was found in 2026's to-date reporting (opportunity for a follow-up search: "tradeon" or ISS-native platform disclosures).

---

## Key Question 5: Practitioner/academic consensus — can an agentic LLM daily-forecast system beat the index net of costs on large caps?

### Takeaway
**Nothing found supports "yes."** The consensus documentable in 2025–2026 publication practices + market outcomes + survey evidence is: LLM trading agents "as they are currently published" have **not** demonstrated net-of-cost large-cap alpha, cannot be reproduced at the protocol level (0/19 studies R3), and the flagship market product (AIEQ, one AI-driven PM example) underperforms. The actual deployment consensus is "LLM to analyst, human/quant/stochastic to PM."

### Cited Findings
- ESWA 2026 audit's bottom line (the most "consensus-forming" 2026 statement): "architectural experimentation is expanding rapidly, while comparable evaluation protocols, execution semantics, and reproducible artifacts remain the field's immediate bottlenecks" — https://arxiv.org/html/2605.19337v1
- Hedge-fund-perspective 2026 review (explicitly targeted at practitioners): asks readers to stress-test LLM pipelines under "realistic market frictions" and highlights "**limits of stock price predictability**" as an at-scale pitfall in the same register as data-leakage and illiquidity — https://arxiv.org/abs/2605.05211
- "Losing Winner" NeurIPS-2025 workshop conclusion (per its authors): "…**a cautionary case study**… importance of aligning proxy tasks with the ultimate goal of profit maximization" — https://neurips.cc/virtual/2025/132549
- AIEQ's track record (see Q4 — cited above: ~100% vs ~200% S&P cumulative since 2017, per 247wallst.com Aug 2026; ~12pp deficit vs IVV on the Jan-2024-forward window per Seeking Alpha 2026) — https://247wallst.com/investing/2026/08/26/can-ai-help-you-beat-the-stock-market-the-answer-may-surprise-you/ ; https://seekingalpha.com/article/4915859-aieq-sophisticated-ai-driven-strategy-that-underperforms-reiterate-hold
- Survey-reported deployment priority (41% of >100 managers) points to AI **integration**, not AI *replacement* — i.e., market-structure product-horizontal adoption at analyst layering, see Q4 — https://hedgeweek.com/news/hedge-funds-rank-ai-as-their-number-top-priority-but-experts-say-they-may-be-ignoring-this-blind-spot
- Bloomberg July 2026 (see Q4) frames the deployment as "into research and trading" with new *risk*-surfaces warned of — not as profit-validated — https://www.bloomberg.com/news/newsletters/2026-07-01/ai-models-could-make-hedge-fund-trading-riskier-wall-street-researchers-warn

### Inferences
- Synthesis across (a) JFE's own "returns fall with adoption" result, (b) 0/19 R3 evidence audits, (c) 1/19 cost modeling, (d) the Losing-Winner objective mismatch, (e) AIEQ live underperformance → the body of evidence aligns on a conditional: **"LLMs do not beat markets at daily horizon net of costs when audited properly."** The coherent stated-case is "LLMs are great data **extractors/analyst-multipliers**, and alpha from them must fight classic backtest-overfitting and instance-decay economics."
- A locally-valid hedge-fund view (published by *hedge-fund-perspective* reviewers in 2026) with nothing contradicted in the found record: **stress-test under frictions, distrust overfit backtests, expect decay** — https://arxiv.org/abs/2605.05211

### Gaps
- No 2026 poll/table recording "practitioner consensus statement" (e.g., from Man Group, Citadel, AQR, Point72 on the specific question "can LLM agents beat daily horizon alpha on large caps") — such statements are private; this session located no public quoted stance from the major quant funds on the narrow Q5 claim.
- No live public LLM-agent-money product was found (unlike AIEQ for older ML), so no direct NAV-based practitioner-testwide evidence exists yet for *agentic LLM* PM products as of Nov 2026.
- Exact attribution: which of the 19 survey-identified primary studies was the "1/19 with transaction-cost model" — not pinned down this session; needed if you want the one exemplar to model cost-reporting practice on.

---

## Source-list quick reference (for the report writer)

| Source | URL | Date | Type | Session status |
|---|---|---|---|---|
| Lopez-Lira & Tang, JFE (Mkt-return predictability via ChatGPT) | https://doi.org/10.1016/j.jfineco.2026.104335 ; https://arxiv.org/abs/2304.07619 ; https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4412788 | Oct 2026 (JFE, Vol. 184:104335); arXiv v1 Apr 2023 | Peer-reviewed finance journal | Author-reported numbers; decay self-reported |
| Xia et al., "Agentic Trading" (Evidence-driven audit, 77 papers → 19 closed-loop) | https://arxiv.org/abs/2605.19337 | May 2026 (ESWA) | Survey/audit | Key negative/audit source |
| TradingAgents (NeurIPS 2025 poster) | https://arxiv.org/abs/2412.20138 ; https://github.com/tauricresearch/tradingagents ; https://tauric.ai/research/tradingagents | Dec 2024; NeurIPS 2025 | Peer-reviewed (poster) conference + code | Author-reported; repo disclaims repro. |
| FinMem | https://ojs.aaai.org/index.php/AAAI-SS/article/view/31290 | 2024 | Peer-reviewed symposium | Author-reported |
| FinAgent | https://www.researchgate.net/publication/383466825 | Feb 2024 | arXiv (venue unverified) | Author-reported |
| FinGPT | https://arxiv.org/html/2306.06031v2 ; https://neurips.cc/virtual/2023/79667 | 2023 [pre-2025] | arXiv/workshop | Sentiment-model scope only |
| BloombergGPT | https://www.bloomberg.com/company/press/bloomberggpt-50-billion-parameter-llm-tuned-finance/ ; https://aclanthology.org/2023.emnlp-industry.39.pdf | Mar 2023 vs EMNLP 2023 critique [pre-2025] | Industry + ACL peer-reviewed critique | GPT-4 > BloombergGPT |
| "The Losing Winner" (NeurIPS 2025 workshop) | https://neurips.cc/virtual/2025/132549 ; https://openreview.net/forum?id=FzahgVWy59 | 2025 | Workshop paper | Objective-mismatch evidence |
| LoGrasso "Could ChatGPT earn abnormal returns?" | https://mf-journal.com/article/view/327 (doi 10.61351/mf.v3i3.327) | Sep 2025 | Independent academic test | Monthly alphas insignificant; large-growth tilt |
| AIEQ live record | https://247wallst.com/investing/2026/08/26/can-ai-help-you-beat-the-stock-market-the-answer-may-surprise-you/ ; https://seekingalpha.com/article/4915859-aieq-sophisticated-ai-driven-strategy-that-underperforms-reiterate-hold ; https://amplifyetfs.com/aieq/ ; https://www.morningstar.com/etfs/arcx/aieq/performance | 2026 | Live NAV products + commentary | Best real-money, real-NAV test |
| Hedgeweek Q1 2026 survey | https://hedgeweek.com/news/hedge-funds-rank-ai-as-their-number-top-priority-but-experts-say-they-may-be-ignoring-this-blind-spot | 2026 | Survey reporting | Industry deployment priority |
| Bloomberg, "AI, Forging New Risks, Isn't a Market Wizard After All" | https://www.bloomberg.com/news/newsletters/2026-07-01/ai-models-could-make-hedge-fund-trading-riskier-wall-street-researchers-warn | Jul 2026 | Financial press | "Into research and trading," risk-not-P&L |
| Hedge-fund-perspective LLM forecasting review | https://arxiv.org/abs/2605.05211 | Apr 2026 (IEEE conf May 2026) | Review | Names data-leakage, frictions, predictability limits |
| Bailey & LdP, Deflated Sharpe [pre-2025] | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551 | 2014 | Methods paper | Backtest-overfitting canon |
| Bailey et al., PBO [pre-2025] | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253 | 2017 [pre-2025] | Methods paper | Walk-forward overfitting probability |
| Bailey et al., Pseudo-Mathematics [pre-2025] | https://www.ams.org/notices/201405/rnoti-p458.pdf | 2014 [pre-2025] | AMS Notices essay | Backtest-overfit math |
| Harvey, Liu, Zhu, Cross-Section [pre-2025] | https://doi.org/10.1093/rfs/hhv059 | 2016 [pre-2025] | RFS paper | Multiple-testing haircut |
| López de Prado, 10 Reasons ML funds fail [pre-2025] | https://doi.org/10.3905/jpm.2018.44.6.120 | 2018 [pre-2025] | JPM paper | The trap list |
