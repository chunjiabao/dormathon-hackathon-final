"""Forecast and classification metrics with explicit zero handling (None = undefined, never faked)."""

import math

import numpy as np


def _arr(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def mae(y, yhat) -> float | None:
    y, yhat = _arr(y), _arr(yhat)
    return float(np.mean(np.abs(y - yhat))) if len(y) else None


def rmse(y, yhat) -> float | None:
    y, yhat = _arr(y), _arr(yhat)
    return float(math.sqrt(np.mean((y - yhat) ** 2))) if len(y) else None


def wape(y, yhat) -> float | None:
    """sum|e| / sum|y|. Undefined (None) when actuals sum to zero."""
    y, yhat = _arr(y), _arr(yhat)
    denom = np.sum(np.abs(y))
    return float(np.sum(np.abs(y - yhat)) / denom) if denom > 0 else None


def smape(y, yhat) -> float | None:
    """mean(2|e| / (|y|+|yhat|)); a pair where both are zero contributes 0 error."""
    y, yhat = _arr(y), _arr(yhat)
    if not len(y):
        return None
    denom = np.abs(y) + np.abs(yhat)
    terms = np.where(denom > 0, 2 * np.abs(y - yhat) / np.where(denom > 0, denom, 1), 0.0)
    return float(np.mean(terms))


def coverage(y, lower, upper) -> float | None:
    y = _arr(y)
    return float(np.mean((y >= _arr(lower)) & (y <= _arr(upper)))) if len(y) else None


def regression_report(y, yhat) -> dict:
    return {"n": len(_arr(y)), "mae": mae(y, yhat), "rmse": rmse(y, yhat), "wape": wape(y, yhat),
            "smape": smape(y, yhat)}  # fmt: skip


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def classification_report(y_true, y_pred) -> dict:
    t, p = np.asarray(y_true, bool), np.asarray(y_pred, bool)
    tp, fp = int(np.sum(t & p)), int(np.sum(~t & p))
    fn, tn = int(np.sum(t & ~p)), int(np.sum(~t & ~p))
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall
        else (0.0 if tp == 0 and (fp or fn) else None)
    )
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "false_positive_rate": _ratio(fp, fp + tn),
    }  # fmt: skip
