"""Request-log cleaning and daily aggregation, shared by synthetic and real data paths.

Handles: duplicated rows (by request_id), missing output tokens (segment-median imputation,
counted), out-of-order / delayed records (ordered and bucketed by occurred_at, not arrival time),
and extreme-but-legitimate requests (kept). Retries are inferred from the log itself
(same app + message fingerprint + client fingerprint within RETRY_WINDOW_S), never from labels.
Without a client fingerprint, popular FAQs asked by different people would look like retries.
"""

import json
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

RETRY_WINDOW_S = 60
LOCAL_TZ = ZoneInfo("Asia/Kuala_Lumpur")


@lru_cache
def _rates() -> dict[str, tuple[float, float]]:
    pricing = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "pricing.json").read_text())
    return {m["model"]: (m["input_usd_per_million"], m["output_usd_per_million"]) for m in pricing["models"]}


def clean_requests(raw: pd.DataFrame, fx: float = 4.70) -> tuple[pd.DataFrame, dict]:
    df = raw.drop_duplicates(subset="request_id", keep="first").copy()
    report = {"duplicates_removed": len(raw) - len(df)}

    out = pd.to_numeric(df["output_tokens"], errors="coerce")
    missing = out.isna()
    medians = out.groupby([df.app_id, df.request_category, df.model]).transform("median")
    df["output_tokens"] = out.fillna(medians).fillna(out.median()).round().astype(np.int64)
    df["output_imputed"] = missing.to_numpy()
    rates = _rates()
    in_rate = df.model.map(lambda m: rates[m][0]).astype(float)
    out_rate = df.model.map(lambda m: rates[m][1]).astype(float)
    recomputed = ((df.input_tokens * in_rate + df.output_tokens * out_rate) / 1e6 * fx).round(8)
    df["cost_myr"] = pd.to_numeric(df["cost_myr"], errors="coerce").fillna(recomputed)
    report["missing_output_imputed"] = int(missing.sum())

    occurred = pd.to_datetime(df["occurred_at"], utc=True)
    if "recorded_at" in df:
        recorded = pd.to_datetime(df["recorded_at"], utc=True)
        report["out_of_order_rows"] = int((occurred.diff().dt.total_seconds() < 0).sum())
        report["delayed_over_1h_rows"] = int(((recorded - occurred).dt.total_seconds() > 3600).sum())
    df["occurred_at"] = occurred
    df["day"] = occurred.dt.tz_convert(LOCAL_TZ).dt.date
    df = df.sort_values(["occurred_at", "request_id"], kind="stable").reset_index(drop=True)
    if "is_extreme_legit" in df:
        report["extreme_legit_rows_kept"] = int(df.is_extreme_legit.sum())
    return df, report


def mark_retries(df: pd.DataFrame) -> pd.Series:
    """True when the same app+fingerprint(+client) was seen within RETRY_WINDOW_S before this request."""
    keys = ["app_id", "fingerprint"]
    if "client_fingerprint" in df and df["client_fingerprint"].notna().all():
        keys.append("client_fingerprint")
    ordered = df.sort_values([*keys, "occurred_at"], kind="stable")
    gap = ordered.groupby(keys).occurred_at.diff().dt.total_seconds()
    return (gap <= RETRY_WINDOW_S).reindex(df.index).fillna(False).astype(bool)


def daily_from_requests(clean: pd.DataFrame, data_origin: str = "synthetic") -> pd.DataFrame:
    df = clean.assign(retry=mark_retries(clean))
    cache_hit = df["cache_status"].isin(["exact_hit", "semantic_hit"]) if "cache_status" in df else False
    df = df.assign(cache_hit=cache_hit)
    daily = (
        df.groupby(["day", "app_id", "request_category", "model"])
        .agg(
            requests=("request_id", "size"),
            input_tokens=("input_tokens", "sum"),
            output_tokens=("output_tokens", "sum"),
            cost_myr=("cost_myr", "sum"),
            cache_hits=("cache_hit", "sum"),
            retry_requests=("retry", "sum"),
        )
        .reset_index()
    )
    daily["cost_myr"] = daily["cost_myr"].round(6)
    daily["data_origin"] = data_origin
    return daily
