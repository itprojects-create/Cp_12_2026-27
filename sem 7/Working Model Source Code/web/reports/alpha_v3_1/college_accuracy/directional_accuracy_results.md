# Directional accuracy results

**Evidence tier:** `HISTORICAL_OOF_DEVELOPMENT` — validation tiles 2022–2023 were already used in W3; no fresh sealed holdout exists.

Target: strict sign of raw-price absolute OPEN-to-OPEN return. Ties are counted and excluded from binary confusion denominators. All candidates use the same common complete-case sample below.

| Horizon | Candidate | n | UP / DOWN | Accuracy | Clustered 95% interval | Balanced acc. | All-eligible coverage | Unconditional acc. | Δ vs majority |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 | `majority_train` | 5,071 | 2,927 / 2,144 | **57.72%** | [49.63%, 66.04%] | 50.00% | 100.00% | 57.71% | 0.00% |
| 20 | `fixed_up` | 5,071 | 2,927 / 2,144 | **57.72%** | [49.93%, 66.30%] | 50.00% | 100.00% | 57.71% | 0.00% |
| 20 | `trend_ret60` | 5,071 | 2,927 / 2,144 | **51.53%** | [46.80%, 55.66%] | 50.29% | 99.52% | 51.35% | -6.19% |
| 20 | `reversal_ret5` | 5,071 | 2,927 / 2,144 | **50.03%** | [47.20%, 52.91%] | 50.89% | 99.96% | 49.92% | -7.69% |
| 20 | `ridge` | 5,071 | 2,927 / 2,144 | **54.49%** | [48.56%, 60.63%] | 49.70% | 97.97% | 53.38% | -3.23% |
| 20 | `logistic` | 5,071 | 2,927 / 2,144 | **57.56%** | [50.22%, 65.87%] | 50.53% | 97.97% | 56.39% | -0.16% |
| 20 | `hgb` | 5,071 | 2,927 / 2,144 | **55.02%** | [48.96%, 61.66%] | 49.58% | 100.00% | 54.54% | -2.70% |
| 5 | `majority_train` | 5,077 | 2,742 / 2,335 | **54.01%** | [49.24%, 58.88%] | 50.00% | 100.00% | 53.96% | 0.00% |
| 5 | `fixed_up` | 5,077 | 2,742 / 2,335 | **54.01%** | [49.06%, 58.82%] | 50.00% | 100.00% | 53.96% | 0.00% |
| 5 | `trend_ret60` | 5,077 | 2,742 / 2,335 | **50.80%** | [48.03%, 53.59%] | 50.15% | 99.50% | 50.60% | -3.21% |
| 5 | `reversal_ret5` | 5,077 | 2,742 / 2,335 | **50.96%** | [48.23%, 53.70%] | 51.40% | 99.96% | 51.04% | -3.05% |
| 5 | `ridge` | 5,077 | 2,742 / 2,335 | **53.63%** | [50.24%, 57.17%] | 51.44% | 97.97% | 52.55% | -0.37% |
| 5 | `logistic` | 5,077 | 2,742 / 2,335 | **54.17%** | [50.01%, 58.31%] | 50.71% | 97.97% | 53.07% | 0.16% |
| 5 | `hgb` | 5,077 | 2,742 / 2,335 | **53.30%** | [49.89%, 56.74%] | 50.69% | 100.00% | 53.43% | -0.71% |

- Majority class is estimated on each fold's training rows only.
- Fixed-UP, trend (`ret_60 > 0`) and reversal (`-ret_5 > 0`) are predeclared baselines.
- Ridge uses raw predicted-return sign; logistic/HGB use fixed `P(UP) > 0.5`.
- Intervals resample complete decision sessions in contiguous blocks (h20=4 weekly decisions; h5=1); stock rows are never independent bootstrap draws.
- `h60` is omitted: only 24 old monthly validation dates and about two non-overlapping periods existed in W3.
- Sector and regime tables are unavailable rather than reconstructed post hoc.
