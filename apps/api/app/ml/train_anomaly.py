"""Anomaly detection on daily per-application usage (no LLM, no ground-truth labels as features).

Two complementary detectors:
  (a) robust seasonal baseline: median + MAD over strictly-prior reference days (same weekday for
      volume metrics, trailing 28 days for ratio metrics), robust z-scores on positive residuals;
  (b) IsolationForest on standardized deviation-from-baseline vectors, fitted on the training window.
An alert fires when (a) or (b) is extreme AND estimated incremental cost >= the impact floor.
Outages (requests far below baseline) raise an operational alert regardless of cost.
Explanations are diagnostic correlations, not proven causes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from app.ml.features import CHEAPEST_MODEL_PREFIX

SEED = 42
WARMUP_DAYS = 28
VOLUME_METRICS = ("requests", "cost")
RATIO_METRICS = ("in_per_req", "cost_per_req", "expensive_share", "retry_rate")
IF_FEATURES = [f"dev_{m}" for m in (*VOLUME_METRICS, *RATIO_METRICS)]
REASONS = {
    "requests": ("traffic_spike", "request volume"),
    "cost": ("cost_spike", "daily cost"),
    "in_per_req": ("prompt_bloat", "input tokens per request"),
    "cost_per_req": ("model_mix_shift", "cost per request"),
    "expensive_share": ("model_mix_shift", "share of requests on more expensive models"),
    "retry_rate": ("retry_storm", "repeated-request (retry) rate"),
}


@dataclass
class DetectorConfig:
    z_threshold: float = 4.0
    if_quantile: float = 0.99  # 1.0 disables the IsolationForest path
    impact_floor_myr: float = 0.50
    outage_ratio: float = 0.30
    outage_z: float = 3.0


def app_day_features(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.copy()
    d["day"] = pd.to_datetime(d["day"])
    if "retry_requests" not in d:
        d["retry_requests"] = 0
    d["expensive_requests"] = np.where(d["model"].str.startswith(CHEAPEST_MODEL_PREFIX), 0, d["requests"])
    agg = d.groupby(["app_id", "day"])[
        ["requests", "input_tokens", "output_tokens", "cost_myr", "retry_requests", "expensive_requests"]
    ].sum()
    agg = agg.rename(columns={"cost_myr": "cost"}).reset_index()
    days = pd.date_range(agg.day.min(), agg.day.max(), freq="D")
    grid = pd.DataFrame({"app_id": agg.app_id.unique()}).merge(pd.DataFrame({"day": days}), how="cross")
    f = grid.merge(agg, on=["app_id", "day"], how="left").fillna(0.0)
    req = f.requests.where(f.requests > 0)
    f["in_per_req"] = f.input_tokens / req
    f["cost_per_req"] = f.cost / req
    f["expensive_share"] = f.expensive_requests / req
    f["retry_rate"] = f.retry_requests / req
    return f.sort_values(["app_id", "day"]).reset_index(drop=True)


def _robust_ref(values: pd.Series, same_weekday: bool) -> tuple[pd.Series, pd.Series]:
    """Median and MAD of strictly-prior reference values for each position in `values` (one app)."""
    v = values.to_numpy(float)
    n = len(v)
    med, mad = np.full(n, np.nan), np.full(n, np.nan)
    for t in range(n):
        if same_weekday:  # up to 8 previous same-weekday values
            ref = v[[t - 7 * k for k in range(1, 9) if t - 7 * k >= 0]]
        else:  # trailing 28 days
            ref = v[max(0, t - 28) : t]
        ref = ref[~np.isnan(ref)]
        if len(ref) >= (4 if same_weekday else 14):
            med[t] = np.median(ref)
            mad[t] = np.median(np.abs(ref - med[t]))
    return pd.Series(med, index=values.index), pd.Series(mad, index=values.index)


def score_days(features: pd.DataFrame) -> pd.DataFrame:
    """Add expected values, robust z-scores and deviation features for every app-day."""
    out = []
    for _, f in features.groupby("app_id", sort=False):
        f = f.copy()
        for m in (*VOLUME_METRICS, *RATIO_METRICS):
            med, mad = _robust_ref(f[m], same_weekday=m in VOLUME_METRICS)
            scale = 1.4826 * mad + np.maximum(0.05 * np.abs(med), 1e-6)  # floor avoids division by ~0
            f[f"exp_{m}"] = med
            f[f"z_{m}"] = (f[m] - med) / scale
            if m in VOLUME_METRICS:
                f[f"dev_{m}"] = np.log1p(f[m].fillna(0)) - np.log1p(med)
            else:
                f[f"dev_{m}"] = (f[m] - med) / scale
        f["impact_myr"] = f["cost"] - f["exp_cost"]
        out.append(f)
    scored = pd.concat(out).sort_values(["app_id", "day"]).reset_index(drop=True)
    scored["warm"] = scored[[f"exp_{m}" for m in VOLUME_METRICS]].notna().all(axis=1) & (
        scored.groupby("app_id").cumcount() >= WARMUP_DAYS
    )
    return scored


class AnomalyDetector:
    def __init__(self, config: DetectorConfig | None = None):
        self.config = config or DetectorConfig()
        self.forest: IsolationForest | None = None
        self.if_threshold: float | None = None

    def fit(self, scored_train: pd.DataFrame) -> AnomalyDetector:
        x = scored_train[scored_train.warm][IF_FEATURES].fillna(0.0).clip(-20, 20).to_numpy()
        self.forest = IsolationForest(n_estimators=200, random_state=SEED).fit(x)
        self.train_scores = -self.forest.score_samples(x)
        self._set_threshold()
        return self

    def _set_threshold(self) -> None:
        q = self.config.if_quantile
        self.if_threshold = None if q >= 1.0 else float(np.quantile(self.train_scores, q))

    def with_config(self, config: DetectorConfig) -> AnomalyDetector:
        clone = AnomalyDetector(config)
        clone.forest, clone.train_scores = self.forest, self.train_scores
        clone._set_threshold()
        return clone

    def predict(self, scored: pd.DataFrame) -> pd.DataFrame:
        c = self.config
        s = scored.copy()
        x = s[IF_FEATURES].fillna(0.0).clip(-20, 20).to_numpy()
        s["if_score"] = -self.forest.score_samples(x) if self.forest is not None else np.nan
        z_cols = [f"z_{m}" for m in (*VOLUME_METRICS, *RATIO_METRICS)]
        s["max_z"] = s[z_cols].max(axis=1)
        robust = s["max_z"] >= c.z_threshold
        forest = s["if_score"] >= self.if_threshold if self.if_threshold is not None else False
        s["outage"] = s.warm & (s.z_requests <= -c.outage_z) & (s.requests < c.outage_ratio * s.exp_requests)
        s["cost_alert"] = s.warm & ~s.outage & (robust | forest) & (s.impact_myr >= c.impact_floor_myr)
        s["alert"] = s.cost_alert | s.outage
        s["reason_code"] = s.apply(_reason, axis=1, z=c.z_threshold)
        return s


def _reason(row: pd.Series, z: float) -> str | None:
    if row["outage"]:
        return "outage"
    if not row["cost_alert"]:
        return None
    # Fixed priority: per-request mechanisms explain a cost rise better than raw volume does.
    for m in ("expensive_share", "in_per_req", "retry_rate", "cost_per_req", "requests"):
        v = row[f"z_{m}"]
        if pd.notna(v) and v >= z:
            return REASONS[m][0]
    return "cost_spike"


def merge_alert_days(pred: pd.DataFrame) -> pd.DataFrame:
    """Merge contiguous alert days per app into one event to prevent alert flooding."""
    events = []
    for app, f in pred[pred.alert].sort_values("day").groupby("app_id"):
        prev = None
        rows: list[pd.Series] = []
        for _, r in f.iterrows():
            if prev is not None and (r.day - prev).days == 1:
                rows.append(r)
            else:
                if rows:
                    events.append(_event(app, rows))
                rows = [r]
            prev = r.day
        if rows:
            events.append(_event(app, rows))
    cols = [
        "app_id",
        "start",
        "end",
        "days",
        "reason_code",
        "peak_row",
        "impact_myr",
        "max_z",
        "if_score",
        "outage",
    ]
    return pd.DataFrame(events, columns=cols)


def _event(app: str, rows: list[pd.Series]) -> dict:
    peak = max(rows, key=lambda r: (r["outage"], r["impact_myr"]))
    return {
        "app_id": app,
        "start": rows[0].day,
        "end": rows[-1].day,
        "days": len(rows),
        "reason_code": peak["reason_code"],
        "peak_row": peak,
        "impact_myr": float(sum(max(0.0, r["impact_myr"]) for r in rows)),
        "max_z": float(max(r["max_z"] for r in rows)),
        "if_score": float(max(r["if_score"] for r in rows)),
        "outage": bool(peak["outage"]),
    }


def severity(event: dict | pd.Series, floor: float) -> str:
    if event["outage"] or event["impact_myr"] >= 3 * floor * max(1, event["days"]):
        return "high"
    return "medium" if event["impact_myr"] >= 1.5 * floor * max(1, event["days"]) else "low"


def explain(event: dict | pd.Series, app_label: str) -> tuple[str, str, float, float]:
    """Fixed-template explanation from measured values: (metric, text, observed, expected)."""
    r = event["peak_row"]
    code = event["reason_code"]
    metric = {
        "outage": "requests", "traffic_spike": "requests", "cost_spike": "cost", "prompt_bloat": "in_per_req",
        "retry_storm": "retry_rate",
        "model_mix_shift": (
            "expensive_share" if r["z_expensive_share"] >= r["z_cost_per_req"] else "cost_per_req"
        ),
    }[code]  # fmt: skip
    observed, expected = float(r[metric]), float(r[f"exp_{metric}"])
    label = REASONS.get(metric, ("", metric))[1]
    fmt = "{:.1%}" if metric in ("expensive_share", "retry_rate") else "{:,.2f}"
    span = f"{event['start']:%d %b}" + (f" to {event['end']:%d %b}" if event["days"] > 1 else "")
    contributing = [
        REASONS[m][1] for m in ("requests", "in_per_req", "expensive_share", "retry_rate", "cost")
        if m != metric and pd.notna(r[f"z_{m}"]) and r[f"z_{m}"] >= 3
    ]  # fmt: skip
    if code == "outage":
        text = (
            f"{app_label}: request volume fell to {observed:,.0f} vs about {expected:,.0f} expected "
            f"on {span} "
            "(robust same-weekday baseline). Possible service outage or integration fault; check the gateway."
        )
    else:
        text = (
            f"{app_label}: {label} was {fmt.format(observed)} vs {fmt.format(expected)} expected on {span}. "
            f"Estimated incremental cost RM{event['impact_myr']:,.2f} above the robust baseline."
        )
        if contributing:
            text += " Also elevated: " + ", ".join(contributing) + "."
    text += " Diagnostic correlation from usage metrics, not a proven cause."
    return metric, text, observed, expected


def config_dict(c: DetectorConfig) -> dict:
    return asdict(c)
