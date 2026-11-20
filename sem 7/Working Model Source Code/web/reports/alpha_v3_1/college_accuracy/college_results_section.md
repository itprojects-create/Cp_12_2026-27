## Results and Discussion

We evaluated binary stock-direction classification on historical point-in-time NIFTY 50 research
rows using four expanding, purged walk-forward validation folds covering 2022–2023. The primary
outcome was the strict sign of the 20-session raw-price return from the next executable open to a
subsequent executable open; zero returns were counted as ties and excluded from binary confusion
denominators. Because these validation periods had already been examined during Quant Plus Wave 3,
all results are classified as **historical out-of-fold development evidence**, not independent
external validation.

On the common complete-case h20 sample (`n=5,071`), the preregistered
logistic candidate achieved **57.56%** accuracy with a decision-date
block-bootstrap 95% interval of **[50.22%, 65.87%]**. Its confusion matrix was
TN=107, FP=2,037,
FN=115, TP=2,812; balanced accuracy
was 50.53%. The fold-training majority baseline achieved
57.72%; the strongest of the three predeclared baselines was
`majority_train` at 57.72%. Thus any value above 50% must be interpreted
against class prevalence and these baselines, not against a coin-flip threshold alone.

Relative to the fold-training majority baseline, logistic h20 differed by
-0.16% (paired clustered 95% interval
[-0.97%,
1.07%]). Logistic h5 differed by
0.16%, with interval
[-1.08%,
1.22%]. Neither interval excludes zero;
there is therefore **no demonstrated accuracy improvement over the training-majority baseline**.

Performance was not temporally stable. Logistic h20 accuracy ranged from
42.51% to
63.92% across
the four folds and was 51.43% in
2022 versus 63.77% in 2023. Logistic
h5 ranged from 44.54%
to 58.98%
across folds. This instability is another reason not to generalise the pooled score.

The study has material limits. Prices are raw and not a complete total-return series; action-shaped
discontinuities are excluded, but the local corporate-action history is incomplete. Historical
membership contains weak snapshot-floor spells, no verified as-of sector map exists, and economic
fees are unavailable for the evaluated years. The h20 labels overlap, leaving approximately
26 effective non-overlapping decision
periods. Multiple candidates were reported in full, so the best-looking row is selection-exposed.
No newly sealed holdout exists, and no result changes the Wave 6 `NO_ELIGIBLE_STRATEGY` state.

Accordingly, the defensible college claim is limited to: *under a fixed retrospective walk-forward
protocol, model and baseline directional accuracies were measured reproducibly on 2022–2023 raw-price
data*. The experiment does not establish forward accuracy, profitable trading, or investment value.
