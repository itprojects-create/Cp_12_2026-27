# College accuracy evaluation acceptance

| Question | Verdict | Evidence |
|---|---|---|
| Any measured accuracy >50%? | **YES** | 14 common-sample model/horizon rows; exact values in `directional_accuracy_results.md` |
| Any candidate beats fold-training majority? | **POINT_ESTIMATE_ONLY_NOT_ESTABLISHED** | Best positive point difference is 0.16%; no positive paired 95% interval excludes zero |
| Independently validated? | **NO** | `NEW_SEALED_HOLDOUT_UNAVAILABLE`; 2022–2023 tiles were already W3 validation |
| Eligible for a college claim? | **YES, WITH QUALIFIER** | May report reproducible `HISTORICAL_OOF_DEVELOPMENT` accuracy and baselines; may not claim forward/generalised accuracy |
| Profitable or trading-eligible? | **NO / NOT EVALUATED** | Raw-price accuracy is not net economics; W6 remains `NO_ELIGIBLE_STRATEGY` |

Primary fitted candidate was fixed before scoring as logistic h20; no post-result threshold tuning
occurred. All seven candidates and all four confidence-grid points are retained. A future claim of
independent accuracy requires a newly sealed, prospectively accumulated period.
