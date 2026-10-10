"""Forecasters: three baselines and a HistGradientBoosting candidate (recursive multi-step).

All models share one interface on a segment panel (day, app_id, request_category, <target>):
    model.fit(history, target).predict(history, horizon_days)
        -> DataFrame[day, app_id, request_category, yhat]
`history` must only contain days strictly before the first horizon day.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from app.ml.features import CATEGORICAL, FEATURES, SEG, category_codes, make_features

SEED = 42


class NaiveLast:
    """Previous-day value, held flat over the horizon."""

    name = "naive_previous_day"

    def fit(self, history: pd.DataFrame, target: str) -> NaiveLast:
        self.target = target
        return self

    def predict(self, history: pd.DataFrame, horizon_days) -> pd.DataFrame:
        last = history.sort_values("day").groupby(SEG)[self.target].last().rename("yhat").reset_index()
        return last.merge(pd.DataFrame({"day": pd.to_datetime(horizon_days)}), how="cross")


class SeasonalNaive:
    """Value from the same weekday in the most recent observed week (t-7, t-14, ...)."""

    name = "seasonal_naive_7"

    def fit(self, history: pd.DataFrame, target: str) -> SeasonalNaive:
        self.target = target
        return self

    def predict(self, history: pd.DataFrame, horizon_days) -> pd.DataFrame:
        last_day = history.day.max()
        recent = history[history.day > last_day - pd.Timedelta(days=7)]
        recent = recent.assign(dow=recent.day.dt.dayofweek)[[*SEG, "dow", self.target]]
        days = pd.DataFrame({"day": pd.to_datetime(horizon_days)})
        days["dow"] = days.day.dt.dayofweek
        out = recent.merge(days, on="dow").rename(columns={self.target: "yhat"})
        return out[["day", *SEG, "yhat"]]


class RollingMean:
    name = "rolling_mean_7"

    def fit(self, history: pd.DataFrame, target: str) -> RollingMean:
        self.target = target
        return self

    def predict(self, history: pd.DataFrame, horizon_days) -> pd.DataFrame:
        last_day = history.day.max()
        recent = history[history.day > last_day - pd.Timedelta(days=7)]
        mean = recent.groupby(SEG)[self.target].mean().rename("yhat").reset_index()
        return mean.merge(pd.DataFrame({"day": pd.to_datetime(horizon_days)}), how="cross")


MEAN28 = FEATURES.index("mean28")


class GBMRecursive:
    """HistGradientBoosting with lag/rolling features, predicted recursively.

    Default target is log1p(y). Alternatives were compared on the VALIDATION window only and
    rejected (workspace WAPE): log 0.214 (chosen), log+Duan smearing 0.218, log-ratio to the
    trailing 28-day mean 0.257, log-ratio+smearing 0.262. They remain available as options.
    """

    name = "hist_gradient_boosting"

    def __init__(
        self, max_iter: int = 150, learning_rate: float = 0.08, max_leaf_nodes: int = 15,
        target_mode: str = "log", smearing: bool = False,
    ):  # fmt: skip
        self.params = {"max_iter": max_iter, "learning_rate": learning_rate, "max_leaf_nodes": max_leaf_nodes}
        self.target_mode, self.smearing = target_mode, smearing

    def _long(self, history: pd.DataFrame) -> pd.DataFrame:
        return history[["day", *SEG, self.target, "exp_share"]].rename(columns={self.target: "y"})

    def _offset(self, X: np.ndarray) -> np.ndarray:
        return np.log1p(X[:, MEAN28]) if self.target_mode == "log_ratio" else 0.0

    def fit(self, history: pd.DataFrame, target: str) -> GBMRecursive:
        self.target = target
        self.codes = category_codes(history)
        feats = make_features(self._long(history), self.codes).dropna(subset=["lag14", "mean28"])
        X = feats[FEATURES].to_numpy(float)
        z = np.log1p(feats["y"].to_numpy(float)) - self._offset(X)
        self.model = HistGradientBoostingRegressor(
            **self.params,
            categorical_features=[FEATURES.index(c) for c in CATEGORICAL],
            random_state=SEED,
        )
        self.model.fit(X, z)
        resid = z - self.model.predict(X)
        self.smear = float(np.mean(np.exp(resid))) if self.smearing else 1.0
        self.n_train_rows = len(feats)
        return self

    def _predict_rows(self, X: np.ndarray) -> np.ndarray:
        log_pred = self.model.predict(X) + self._offset(X)
        return np.clip(np.exp(log_pred) * self.smear - 1, 0, None)

    def predict(self, history: pd.DataFrame, horizon_days) -> pd.DataFrame:
        long = self._long(history).sort_values([*SEG, "day"])
        seg_keys, ys, shares = [], [], []
        for key, grp in long.groupby(SEG, sort=False):
            seg_keys.append(key)
            ys.append(list(grp["y"].to_numpy(float)))
            shares.append(list(grp["exp_share"].to_numpy(float)))
        out = []
        for day in pd.to_datetime(horizon_days):
            X = np.array(
                [
                    end_features(y, s, day, self.codes["app"].get(k[0], -1), self.codes["cat"].get(k[1], -1))
                    for k, y, s in zip(seg_keys, ys, shares, strict=True)
                ]
            )
            yhat = self._predict_rows(X)
            for i, v in enumerate(yhat):
                ys[i].append(float(v))  # feed predictions back for the next step
                observed = [x for x in shares[i] if not np.isnan(x)]
                shares[i].append(observed[-1] if observed else np.nan)  # model mix frozen at last state
            out.append(pd.DataFrame(seg_keys, columns=SEG).assign(day=day, yhat=yhat))
        return pd.concat(out, ignore_index=True)[["day", *SEG, "yhat"]]


def end_features(y: list[float], share: list[float], day: pd.Timestamp, app_code: int, cat_code: int) -> list[float]:
    """FEATURES for the day after the end of `y`; identical semantics to make_features (tested)."""
    a = np.asarray(y, float)
    n = len(a)

    def lag(k: int) -> float:
        return a[n - k] if n >= k else np.nan

    def window(w: int, min_periods: int, fn) -> float:
        vals = a[max(0, n - w) :]
        return fn(vals) if len(vals) >= min_periods else np.nan

    mean7 = window(7, 3, np.mean)
    mean28 = window(28, 14, np.mean)
    s = np.asarray(share[-7:], float)
    s = s[~np.isnan(s)]
    return [
        lag(1), lag(7), lag(14),
        mean7, window(14, 7, np.mean), mean28,
        window(7, 3, lambda v: np.std(v, ddof=1)), window(14, 3, lambda v: np.std(v, ddof=1)),
        mean7 / mean28 - 1 if mean28 and mean28 > 0 else np.nan,
        day.dayofweek, day.day, int(day.dayofweek >= 5),
        float(np.mean(s)) if len(s) else np.nan,
        app_code, cat_code,
    ]  # fmt: skip


MODEL_FACTORIES = {
    NaiveLast.name: NaiveLast,
    SeasonalNaive.name: SeasonalNaive,
    RollingMean.name: RollingMean,
    GBMRecursive.name: GBMRecursive,
}
BASELINE_FOR_SELECTION = SeasonalNaive.name
CANDIDATE = GBMRecursive.name


def fit_predict(name: str, history: pd.DataFrame, target: str, horizon_days) -> pd.DataFrame:
    pred = MODEL_FACTORIES[name]().fit(history, target).predict(history, horizon_days)
    pred["yhat"] = pred["yhat"].clip(lower=0)
    return pred
