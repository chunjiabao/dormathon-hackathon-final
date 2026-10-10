"""Rolling-origin backtesting and residual-based (split-conformal style) intervals.

Each origin retrains on data strictly before the origin and forecasts forward recursively.
Intervals use relative absolute residual quantiles measured on a calibration window; coverage
may degrade under distribution shift (anomalies, drift), which test-period coverage reports.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.ml.features import SEG
from app.ml.metrics import coverage, regression_report
from app.ml.train_forecast import BASELINE_FOR_SELECTION, CANDIDATE, MODEL_FACTORIES, fit_predict

INTERVAL_LEVEL = 0.90
MIN_REL_FLOOR = 0.25  # MYR; avoids exploding relative errors when the prediction is ~0


def rolling_backtest(
    panel: pd.DataFrame, model: str, target: str, origins: list[pd.Timestamp], horizon: int,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:  # fmt: skip
    """Rows: origin, day, h (1-based), app_id, request_category, y, yhat."""
    end = end or panel.day.max()
    parts = []
    for origin in origins:
        days = pd.date_range(origin, min(origin + pd.Timedelta(days=horizon - 1), end), freq="D")
        if not len(days):
            continue
        history = panel[panel.day < origin]
        pred = fit_predict(model, history, target, days)
        actual = panel[panel.day.isin(days)][["day", *SEG, target]].rename(columns={target: "y"})
        m = actual.merge(pred, on=["day", *SEG], how="left")
        m["origin"] = origin
        m["h"] = (m.day - origin).dt.days + 1
        parts.append(m)
    return pd.concat(parts, ignore_index=True)


def total_by_day(bt: pd.DataFrame) -> pd.DataFrame:
    return bt.groupby(["origin", "day", "h"], as_index=False)[["y", "yhat"]].sum()


def _rel_err(y, yhat) -> np.ndarray:
    return np.abs(np.asarray(y) - np.asarray(yhat)) / np.maximum(np.asarray(yhat), MIN_REL_FLOOR)


def calibrate(bt: pd.DataFrame, level: float = INTERVAL_LEVEL) -> dict:
    """Relative-error quantiles: per segment-day by horizon, and for cumulative totals by length L."""
    seg_q = {}
    for h, grp in bt.groupby("h"):
        seg_q[int(h)] = float(np.quantile(_rel_err(grp.y, grp.yhat), level))
    tot = total_by_day(bt).sort_values(["origin", "day"])
    tot["cum_y"] = tot.groupby("origin").y.cumsum()
    tot["cum_yhat"] = tot.groupby("origin").yhat.cumsum()
    cum_q = {}
    for h, grp in tot.groupby("h"):
        cum_q[int(h)] = float(np.quantile(_rel_err(grp.cum_y, grp.cum_yhat), level))
    # Enforce non-decreasing quantiles in horizon (uncertainty should not shrink further out).
    for q in (seg_q, cum_q):
        running = 0.0
        for h in sorted(q):
            running = max(running, q[h])
            q[h] = running
    return {"level": level, "segment_daily_rel": seg_q, "cumulative_total_rel": cum_q,
            "n_origins": int(bt.origin.nunique())}  # fmt: skip


def quantile_for(q: dict[int, float], h: int) -> tuple[float, bool]:
    """Quantile for horizon h; beyond the calibrated range, reuse the largest and flag extrapolation."""
    if not q:
        return 1.0, True
    if h in q:
        return q[h], False
    return q[max(q)], h > max(q)


def interval(yhat, q: float):
    yhat = np.asarray(yhat, float)
    return np.clip(yhat * (1 - q), 0, None), yhat * (1 + q)


def score(bt: pd.DataFrame) -> dict:
    tot = total_by_day(bt)
    out = {
        "segment_daily": regression_report(bt.y, bt.yhat),
        "workspace_daily": regression_report(tot.y, tot.yhat),
    }
    for label, lo, hi in (("h1", 1, 1), ("h2_7", 2, 7), ("h8_14", 8, 14)):
        sub = tot[tot.h.between(lo, hi)]
        out[f"workspace_daily_{label}"] = regression_report(sub.y, sub.yhat)
    return out


def interval_coverage(bt: pd.DataFrame, cal: dict) -> dict:
    lo, hi = [], []
    for h, yhat in zip(bt.h, bt.yhat, strict=True):
        q, _ = quantile_for(cal["segment_daily_rel"], int(h))
        lo.append(max(0.0, yhat * (1 - q)))
        hi.append(yhat * (1 + q))
    tot = total_by_day(bt).sort_values(["origin", "day"])
    tot["cum_y"] = tot.groupby("origin").y.cumsum()
    tot["cum_yhat"] = tot.groupby("origin").yhat.cumsum()
    qs = [quantile_for(cal["cumulative_total_rel"], int(h))[0] for h in tot.h]
    return {
        "nominal": cal["level"],
        "segment_daily": coverage(bt.y, lo, hi),
        "cumulative_total": coverage(
            tot.cum_y, np.clip(tot.cum_yhat * (1 - np.array(qs)), 0, None), tot.cum_yhat * (1 + np.array(qs))
        ),
    }


def select_model(scores: dict[str, dict], metric: str = "wape") -> tuple[str, str]:
    """Candidate ships only if it beats seasonal naive on workspace-level WAPE; else the baseline ships."""
    cand = scores[CANDIDATE]["workspace_daily"][metric]
    base = scores[BASELINE_FOR_SELECTION]["workspace_daily"][metric]
    if cand is not None and base is not None and cand < base:
        return (
            CANDIDATE,
            f"{CANDIDATE} WAPE {cand:.3f} < {BASELINE_FOR_SELECTION} WAPE {base:.3f} on calibration",
        )
    return BASELINE_FOR_SELECTION, (
        f"{CANDIDATE} did not beat {BASELINE_FOR_SELECTION} on calibration WAPE ({cand} vs {base}); shipping baseline"
    )


ALL_MODELS = list(MODEL_FACTORIES)
