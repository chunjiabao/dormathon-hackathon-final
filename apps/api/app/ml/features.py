"""Leakage-safe feature construction.

Every feature for day t is computed from values strictly before t (shift(1) before any rolling
window). Injected anomaly labels and scenario truth are never inputs.
"""

import numpy as np
import pandas as pd

SEG = ["app_id", "request_category"]
CHEAPEST_MODEL_PREFIX = "claude-haiku"
FEATURES = [
    "lag1", "lag7", "lag14", "mean7", "mean14", "mean28", "std7", "std14", "trend",
    "dow", "dom", "is_weekend", "exp_share7", "app_code", "cat_code",
]  # fmt: skip
CATEGORICAL = ["dow", "app_code", "cat_code"]


def segment_panel(daily: pd.DataFrame) -> pd.DataFrame:
    """(day, app_id, request_category) panel summed over models and origins, on a complete day grid.

    Days with no rows inside the observed range are genuine zeros (e.g. outages).
    """
    d = daily.copy()
    d["day"] = pd.to_datetime(d["day"])
    d["expensive_requests"] = np.where(d["model"].str.startswith(CHEAPEST_MODEL_PREFIX), 0, d["requests"])
    agg = (
        d.groupby(["day", *SEG])[["requests", "input_tokens", "output_tokens", "cost_myr", "expensive_requests"]]
        .sum()
        .reset_index()
    )
    days = pd.date_range(agg.day.min(), agg.day.max(), freq="D")
    segs = agg[SEG].drop_duplicates()
    grid = segs.merge(pd.DataFrame({"day": days}), how="cross")
    panel = grid.merge(agg, on=["day", *SEG], how="left").fillna(0.0)
    panel["exp_share"] = np.where(panel.requests > 0, panel.expensive_requests / panel.requests.clip(lower=1), np.nan)
    return panel.sort_values([*SEG, "day"]).reset_index(drop=True)


def make_features(long: pd.DataFrame, codes: dict[str, dict[str, int]]) -> pd.DataFrame:
    """Add FEATURES to a long frame with columns day, app_id, request_category, y, exp_share."""
    df = long.sort_values([*SEG, "day"]).copy()
    g = df.groupby(SEG, sort=False)
    prev = g["y"].shift(1)
    df["lag1"] = prev
    df["lag7"] = g["y"].shift(7)
    df["lag14"] = g["y"].shift(14)
    gp = prev.groupby([df[c] for c in SEG], sort=False)
    for w in (7, 14, 28):
        df[f"mean{w}"] = gp.transform(lambda s, w=w: s.rolling(w, min_periods=max(3, w // 2)).mean())
    for w in (7, 14):
        df[f"std{w}"] = gp.transform(lambda s, w=w: s.rolling(w, min_periods=3).std())
    df["trend"] = df["mean7"] / df["mean28"].where(df["mean28"] > 0) - 1
    share_prev = g["exp_share"].shift(1)
    df["exp_share7"] = share_prev.groupby([df[c] for c in SEG], sort=False).transform(
        lambda s: s.rolling(7, min_periods=1).mean()
    )
    df["dow"] = df["day"].dt.dayofweek
    df["dom"] = df["day"].dt.day
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df["app_code"] = df["app_id"].map(codes["app"]).fillna(-1).astype(int)
    df["cat_code"] = df["request_category"].map(codes["cat"]).fillna(-1).astype(int)
    return df


def category_codes(panel: pd.DataFrame) -> dict[str, dict[str, int]]:
    return {
        "app": {a: i for i, a in enumerate(sorted(panel.app_id.unique()))},
        "cat": {c: i for i, c in enumerate(sorted(panel.request_category.unique()))},
    }
