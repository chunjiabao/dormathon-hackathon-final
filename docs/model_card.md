# Model Card: TokenGuard cost forecaster and anomaly detector

Measured results live in [evaluation_report.md](evaluation_report.md), which `scripts/run_evaluation.py` generates. This card describes the models and how to read those results. It does not repeat any numbers, so it cannot drift out of date.

## Intended use
- Forecast an SME's Anthropic API spend for the rest of the current calendar month, plus a 7-day look-ahead, and flag budget risk.
- Flag statistically unusual daily usage per application, explaining it from observed and expected values.
- Out of scope: guaranteeing spend, billing reconciliation, judging answer quality, and any automated action. Every intervention needs owner approval.

## Forecaster
| Item | Detail |
|---|---|
| Target | Daily estimated cost (MYR) per application × request category. Requests are forecast with the same model; tokens = predicted requests × trailing 28-day tokens per request |
| Candidate | `HistGradientBoostingRegressor` on `log1p(cost)`, recursive multi-step, `random_state=42` |
| Features | lags t-1/t-7/t-14; 7/14/28-day rolling means and 7/14-day standard deviations of strictly prior values; trend (mean7/mean28); day of week, day of month, weekend flag; 7-day expensive-model share (frozen at its last observed value when forecasting); application and category codes |
| Never used | injected anomaly labels, scenario truth, any value on or after the predicted day (tested in `tests/test_forecast.py`) |
| Baselines | previous-day naive, seasonal naive (t-7), 7-day rolling mean |
| Selection rule | The candidate ships only if it beats seasonal naive on workspace-level WAPE in the selection window. The offline evaluation selects on the validation split. Each production run reselects on that workspace's last 28 complete days. |
| Intervals | 90% empirical: relative absolute-residual quantiles by horizon from the calibration backtest, kept non-decreasing in horizon. Lower bounds are clipped at zero, and the month-end lower bound never drops below money already spent |
| Month-end total | actual cost for complete days this month (counted once) + forecast for every remaining day |
| Budget risk | deterministic: `lower > budget` means high-confidence overrun, `forecast > budget` means projected overrun, `upper > budget` means possible overrun. No probabilities are claimed |

Design alternatives compared on validation only and rejected: a log-ratio target against the 28-day mean, and Duan smearing (see the `GBMRecursive` docstring).

## Anomaly detector
| Item | Detail |
|---|---|
| Unit | application-day |
| (a) Robust baseline | median and MAD of strictly prior reference days: the same weekday over the last 8 weeks for volumes (requests, cost), and the trailing 28 days for ratios (input tokens/request, cost/request, expensive-model share, retry rate). Robust z-scores |
| (b) IsolationForest | 200 trees on deviation-from-baseline vectors, fitted on the training window only |
| Alert rule | (robust z ≥ threshold OR forest score ≥ training-score quantile) AND estimated incremental cost ≥ impact floor. Outages (requests below 30% of expected with z ≤ -3) raise an operational alert regardless of cost |
| Threshold choice | grid sweep on the validation split (best day-level F1, ties go to fewer false alerts); test metrics are reported once |
| Retries | the same message fingerprint and the same client fingerprint (an HMAC of the chat session) within 60 s. Without the client key, popular FAQs asked by different people would look like retries |
| Explanations | fixed templates using observed vs expected values and other elevated metrics, labelled as diagnostic correlation, not cause |
| Reason codes | outage > model_mix_shift > prompt_bloat > retry_storm > traffic_spike > cost_spike (fixed priority) |

## Data
All training and evaluation data is **synthetic** (seed 42, 180 days, 3 apps × 4 categories) from `app/ml/synthetic.py`. See [data_dictionary.md](data_dictionary.md) and `data/generated/dataset_manifest.json`. Production runs train on whatever the workspace holds (synthetic history plus real gateway traffic), and every forecast run records the origin mix in `data_mix_json`.

## Known limitations
- Synthetic data reflects the generator's assumptions. Metrics on it do not transfer to real traffic.
- Tree models cannot extrapolate a rising level beyond the training range, so sustained drift is under-forecast. Look at the test-period bias and the month-end recall in the evaluation report.
- Interval coverage falls below nominal under distribution shift (anomalies, drift). The evaluation reports measured coverage.
- Month-end overrun metrics come from very few distinct months, and origins within a month are correlated.
- A simpler baseline can beat the candidate on some windows. The selection rule and test tables show this openly.
- English-only demo, single currency, a fixed demo FX rate (not live).
