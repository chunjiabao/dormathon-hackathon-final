"""Deterministic hybrid synthetic dataset generator (MASTER_BUILD_PACK §9).

Every row is labelled data_origin='synthetic'. Output depends only on (seed, days, end_date):
the same inputs always produce byte-identical files. Ground-truth anomaly labels and scenario
truth are written to separate files and must never be used as model features.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

GENERATOR_VERSION = "synthetic-v1"
LOCAL_TZ = ZoneInfo("Asia/Kuala_Lumpur")
CATEGORIES = ("static_faq", "order_enquiry", "complex_support", "other")
HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-5-20250929"
OPUS = "claude-opus-4-1-20250805"
MORE_EXPENSIVE = {HAIKU: SONNET, SONNET: OPUS, OPUS: OPUS}
N_FAQ_INTENTS = 10
PARAPHRASE_VARIANTS = 60

# Per-app traffic profile. Base = mean daily requests per category at day 0.
APPS: dict[str, dict] = {
    "bakery_demo": {
        "base": {"static_faq": 95, "order_enquiry": 23, "complex_support": 9, "other": 17},
        "weekly": [1.0, 0.95, 0.95, 1.0, 1.1, 1.3, 1.15],  # Mon..Sun
        "mix": {HAIKU: 0.92, SONNET: 0.08},
        "peaks": {"days_of_month": (1, 2, 3), "mult": 1.12, "label": "month-start campaign"},
        "trend_per_day": 0.0022,
    },
    "tuition_demo": {
        "base": {"static_faq": 46, "order_enquiry": 8, "complex_support": 23, "other": 19},
        "weekly": [1.1, 1.1, 1.1, 1.05, 1.0, 0.7, 0.65],
        "mix": {HAIKU: 0.55, SONNET: 0.45},
        "peaks": {"days_of_month": (), "mult": 1.0, "label": "none"},
        "trend_per_day": 0.0015,
    },
    "retail_demo": {
        "base": {"static_faq": 63, "order_enquiry": 36, "complex_support": 15, "other": 19},
        "weekly": [0.95, 0.9, 0.9, 0.95, 1.1, 1.35, 1.3],
        "mix": {HAIKU: 0.75, SONNET: 0.22, OPUS: 0.03},
        "peaks": {"days_of_month": (25, 26, 27, 28), "mult": 1.2, "label": "payday"},
        "trend_per_day": 0.0018,
    },
}

# (median input tokens, sigma, median output tokens, sigma) per category; lognormal, clipped.
TOKENS = {
    "static_faq": (550, 0.30, 90, 0.40),
    "order_enquiry": (750, 0.35, 140, 0.45),
    "complex_support": (1400, 0.40, 320, 0.45),
    "other": (700, 0.40, 160, 0.50),
}
FAQ_ELIGIBLE_SHARE = 0.78  # share of static_faq requests that are safe to answer from an approved FAQ
PARAPHRASE = {"alias": (0.45, 1.0), "close": (0.40, 0.85), "hard": (0.15, 0.20)}  # (share, matcher recall)
CACHE_OVERHEAD_PER_LOOKUP_MYR = 0.00005  # local embedding + DB lookup (assumption)
CACHE_FIXED_DAILY_MYR = 0.20  # share of hosting/DB attributable to the cache (assumption)


@dataclass(frozen=True)
class EventSpec:
    kind: str
    app: str
    start: int  # day index at the 180-day reference scale
    duration: int


# Scheduled so later events are held out: ~10 in train, 5 in validation, 8 in test (70/15/15 split).
EVENT_SCHEDULE = [
    EventSpec("A1", "bakery_demo", 20, 2),
    EventSpec("A2", "tuition_demo", 35, 3),
    EventSpec("A7", "bakery_demo", 41, 1),
    EventSpec("A3", "retail_demo", 50, 5),
    EventSpec("A4", "bakery_demo", 62, 2),
    EventSpec("A5", "tuition_demo", 75, 2),
    EventSpec("A7", "retail_demo", 90, 1),
    EventSpec("A1", "retail_demo", 100, 2),
    EventSpec("A6", "tuition_demo", 105, 14),
    EventSpec("A2", "bakery_demo", 114, 3),
    EventSpec("A1", "tuition_demo", 128, 2),
    EventSpec("A3", "bakery_demo", 133, 5),
    EventSpec("A4", "retail_demo", 140, 2),
    EventSpec("A7", "tuition_demo", 145, 1),
    EventSpec("A5", "bakery_demo", 150, 2),
    EventSpec("A2", "retail_demo", 155, 3),
    EventSpec("A1", "bakery_demo", 158, 2),
    EventSpec("A6", "retail_demo", 159, 14),
    EventSpec("A7", "bakery_demo", 161, 1),
    EventSpec("A4", "tuition_demo", 164, 2),
    EventSpec("A3", "tuition_demo", 168, 5),
    EventSpec("A5", "retail_demo", 174, 2),
    EventSpec("A2", "tuition_demo", 176, 3),
]

EVENT_META = {
    "A1": ("requests", "3x request traffic spike (campaign/viral demand)", 3.0, "business_spend", "yes"),
    "A2": (
        "input_tokens_per_request",
        "4x average input tokens (prompt bloat)",
        4.0,
        "technical_fault",
        "yes",
    ),
    "A3": (
        "cost_per_request",
        "60% of traffic shifted to a more expensive model",
        0.6,
        "technical_fault",
        "yes",
    ),
    "A4": ("retry_rate", "35% of requests retried once (retry storm)", 0.35, "technical_fault", "yes"),
    "A5": ("requests", "near-zero usage (service outage)", 0.03, "operational_outage", "yes"),
    "A6": (
        "cost",
        "gradual +2%/day cost increase over 14 days (drift, persists)",
        0.02,
        "business_spend",
        "drift",
    ),
    "A7": ("requests", "benign one-day weekend promotion (1.8x)", 1.8, "benign", "no"),
}


def _seeded(seed: int, name: str) -> np.random.Generator:
    """Independent deterministic stream per component so adding one doesn't shift others."""
    digest = hashlib.sha256(f"{seed}:{name}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "little"))


def split_bounds(days: int) -> tuple[int, int]:
    """Chronological 70/15/15 split: train [0,a), validation [a,b), test [b,days)."""
    return round(days * 0.70), round(days * 0.85)  # round: int(180 * 0.70) == 125 in floating point


def _schedule(days: int, day_dates: list[date]) -> list[dict]:
    events = []
    for i, spec in enumerate(EVENT_SCHEDULE, start=1):
        start = round(spec.start * days / 180)
        if spec.kind == "A7":  # promotions land on a weekend day
            while day_dates[min(start, days - 1)].weekday() < 5 and start < days - 1:
                start += 1
        end = min(start + spec.duration - 1, days - 1)
        events.append({"event_id": f"E{i:02d}", "kind": spec.kind, "app": spec.app, "start": start, "end": end})
    return events


def generate(seed: int = 42, days: int = 180, end_date: date | None = None) -> dict:
    """Return {'requests', 'daily', 'anomaly_truth', 'scenario_truth', 'manifest'}."""
    if days < 120:
        raise ValueError("days must be >= 120 to fit the event schedule and splits")
    if end_date is None:
        end_date = datetime.now(LOCAL_TZ).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=days - 1)
    day_dates = [start_date + timedelta(days=i) for i in range(days)]
    pricing = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "pricing.json").read_text())
    fx = 4.70
    rates = {m["model"]: (m["input_usd_per_million"], m["output_usd_per_million"]) for m in pricing["models"]}
    events = _schedule(days, day_dates)
    train_end, val_end = split_bounds(days)

    # ---- daily expected counts per (app, category, day) with temporal correlation ----
    count_rows = []
    rng_noise = _seeded(seed, "noise")
    for app, prof in APPS.items():
        z = np.zeros(days)
        eps = rng_noise.normal(0, 0.07, days)
        for t in range(1, days):
            z[t] = 0.6 * z[t - 1] + eps[t]  # AR(1) on log scale: no independent daily jumps
        for cat in CATEGORIES:
            cat_noise = rng_noise.normal(0, 0.03, days)
            for t, d in enumerate(day_dates):
                mu = prof["base"][cat] * prof["weekly"][d.weekday()] * (1 + prof["trend_per_day"]) ** t
                if d.day in prof["peaks"]["days_of_month"]:
                    mu *= prof["peaks"]["mult"]
                mu *= np.exp(z[t] + cat_noise[t])
                for ev in events:
                    if ev["app"] == app and ev["start"] <= t <= ev["end"]:
                        mu *= {"A1": 3.0, "A5": 0.03, "A7": 1.8}.get(ev["kind"], 1.0)
                count_rows.append((app, cat, t, mu))

    rng_count = _seeded(seed, "counts")
    mus = np.array([r[3] for r in count_rows])
    counts = rng_count.poisson(mus * rng_count.gamma(50.0, 1 / 50.0, len(mus)))  # mild overdispersion

    app_arr = np.repeat([r[0] for r in count_rows], counts)
    cat_arr = np.repeat([r[1] for r in count_rows], counts)
    day_arr = np.repeat([r[2] for r in count_rows], counts)
    n = len(app_arr)

    # ---- per-request attributes ----
    rng_req = _seeded(seed, "requests")
    hour = np.clip(rng_req.normal(13.5, 3.5, n), 7.0, 23.0)
    seconds = (hour * 3600).astype(np.int64)
    model = np.empty(n, dtype=object)
    for app, prof in APPS.items():
        idx = np.flatnonzero(app_arr == app)
        names, probs = zip(*prof["mix"].items(), strict=True)
        model[idx] = rng_req.choice(names, size=len(idx), p=probs)

    in_tok = np.empty(n)
    out_tok = np.empty(n)
    for cat, (in_med, in_sd, out_med, out_sd) in TOKENS.items():
        idx = np.flatnonzero(cat_arr == cat)
        in_tok[idx] = rng_req.lognormal(np.log(in_med), in_sd, len(idx))
        out_tok[idx] = rng_req.lognormal(np.log(out_med), out_sd, len(idx))
    in_tok = np.clip(in_tok, 50, 8000)
    out_tok = np.clip(out_tok, 5, 1024)

    scenario = np.full(n, "baseline", dtype=object)
    drift_mult = np.ones(n)
    for ev in events:
        in_ev = (app_arr == ev["app"]) & (day_arr >= ev["start"]) & (day_arr <= ev["end"])
        if ev["kind"] != "A6":
            scenario[in_ev] = ev["event_id"]
        if ev["kind"] == "A2":
            in_tok[in_ev] *= 4.0
        elif ev["kind"] == "A3":
            shift = in_ev & (rng_req.random(n) < 0.6)
            model[shift] = [MORE_EXPENSIVE[m] for m in model[shift]]
        elif ev["kind"] == "A6":
            # +2%/day compounding over the window; the higher level persists afterwards.
            after = (app_arr == ev["app"]) & (day_arr >= ev["start"])
            k = np.minimum(day_arr - ev["start"] + 1, ev["end"] - ev["start"] + 1)
            drift_mult[after] *= 1.02 ** k[after]
            scenario[in_ev] = ev["event_id"]
    in_tok *= drift_mult
    out_tok *= drift_mult

    # FAQ intent structure (used only for cache scenario truth; never a forecasting feature)
    is_faq = cat_arr == "static_faq"
    intent_probs = 1 / np.arange(1, N_FAQ_INTENTS + 1) ** 1.1
    intent_probs /= intent_probs.sum()
    intent = np.where(is_faq, rng_req.choice(N_FAQ_INTENTS, n, p=intent_probs), -1)
    eligible = is_faq & (rng_req.random(n) < FAQ_ELIGIBLE_SHARE)
    pclass_names = list(PARAPHRASE)
    pclass = rng_req.choice(pclass_names, n, p=[PARAPHRASE[p][0] for p in pclass_names])
    variant = rng_req.integers(0, PARAPHRASE_VARIANTS, n)
    fingerprint = np.where(
        is_faq,
        np.char.add(np.char.add(app_arr.astype(str), ":faq"), (intent * 1000 + variant).astype(str)),
        np.char.add("u", rng_req.integers(0, 2**62, n).astype(str)),
    )
    recognized = eligible & (rng_req.random(n) < np.array([PARAPHRASE[p][1] for p in pclass]))
    is_extreme = rng_req.random(n) < 0.0005  # legitimate very large requests (kept, flagged)
    in_tok[is_extreme] *= rng_req.uniform(10, 25, is_extreme.sum())

    df = pd.DataFrame(
        {
            "app_id": app_arr,
            "request_category": cat_arr,
            "day_index": day_arr,
            "seconds": seconds,
            "model": model.astype(str),
            "input_tokens": np.round(in_tok).astype(np.int64),
            "output_tokens": np.round(out_tok).astype(np.int64),
            "cache_eligible": eligible,
            "faq_intent": intent,
            "paraphrase_class": np.where(is_faq, pclass, ""),
            "matcher_recognizes": recognized,
            "fingerprint": fingerprint,
            # Hashed client/session id: retries reuse it, different customers asking the same FAQ don't.
            "client_fingerprint": np.char.add("c", rng_req.integers(0, 2**62, n).astype(str)),
            "is_retry": False,
            "is_extreme_legit": is_extreme,
            "scenario_id": scenario.astype(str),
        }
    )

    # A4 retry storms: 35% of requests in the window are retried once, 1-30 s later (each call billed).
    retry_parts = []
    for ev in events:
        if ev["kind"] != "A4":
            continue
        mask = (df.app_id == ev["app"]) & df.day_index.between(ev["start"], ev["end"])
        src = df[mask & (rng_req.random(len(df)) < 0.35)].copy()
        src["seconds"] = src["seconds"] + rng_req.integers(1, 31, len(src))
        src["is_retry"] = True
        retry_parts.append(src)
    df = pd.concat([df, *retry_parts], ignore_index=True)
    df = df.sort_values(["day_index", "seconds", "app_id", "fingerprint"], kind="stable").reset_index(drop=True)

    in_rate = df.model.map(lambda m: rates[m][0]).to_numpy(float)
    out_rate = df.model.map(lambda m: rates[m][1]).to_numpy(float)
    df["cost_myr"] = np.round((df.input_tokens * in_rate + df.output_tokens * out_rate) / 1e6 * fx, 8)

    local_midnight = pd.Timestamp(start_date, tz=LOCAL_TZ)
    occurred = local_midnight + pd.to_timedelta(df.day_index, unit="D") + pd.to_timedelta(df.seconds, unit="s")
    df["occurred_at"] = occurred.dt.tz_convert("UTC")
    df["request_id"] = [f"syn-{i:07d}" for i in range(len(df))]

    # ---- A8 data-quality defects (robustness, not alerts) ----
    rng_dq = _seeded(seed, "data_quality")
    lag = pd.to_timedelta(rng_dq.uniform(0, 5, len(df)), unit="s")
    delayed = rng_dq.random(len(df)) < 0.01
    lag = lag.where(~delayed, pd.to_timedelta(rng_dq.uniform(3600, 48 * 3600, len(df)), unit="s"))
    df["recorded_at"] = df["occurred_at"] + lag
    missing = rng_dq.random(len(df)) < 0.004
    df["output_tokens"] = df["output_tokens"].astype("Float64")
    df.loc[missing, ["output_tokens", "cost_myr"]] = pd.NA
    dup_idx = np.flatnonzero(rng_dq.random(len(df)) < 0.003)
    df = pd.concat([df, df.iloc[dup_idx]], ignore_index=True)
    # Log order = arrival order, so delayed rows appear out of order by occurred_at.
    df = df.sort_values(["recorded_at", "request_id"], kind="stable").reset_index(drop=True)
    df["data_origin"] = "synthetic"
    df["day"] = (pd.Timestamp(start_date) + pd.to_timedelta(df.day_index, unit="D")).dt.date

    requests = df[
        [
            "request_id", "occurred_at", "recorded_at", "day", "app_id", "request_category", "model",
            "input_tokens", "output_tokens", "cost_myr", "cache_eligible", "faq_intent", "paraphrase_class",
            "matcher_recognizes", "fingerprint", "client_fingerprint", "is_retry", "is_extreme_legit",
            "scenario_id", "data_origin",
        ]
    ]  # fmt: skip

    from app.ml.clean import clean_requests, daily_from_requests

    clean, dq_report = clean_requests(requests)
    daily = daily_from_requests(clean)
    dq_report.update(
        {
            "injected_missing_output_rows": int(missing.sum()),
            "injected_duplicate_rows": len(dup_idx),
            "injected_delayed_rows": int(delayed.sum()),
            "injected_extreme_legit_rows": int(is_extreme.sum()),
        }
    )

    anomaly_truth = _anomaly_truth(events, day_dates, train_end, val_end, dq_report)
    scenario_truth = _scenario_truth(clean)
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "data_origin": "synthetic",
        "disclaimer": "Fully synthetic. Not derived from any real customer, business or API account.",
        "seed": seed,
        "days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "timezone": str(LOCAL_TZ),
        "splits": {
            "train": [day_dates[0].isoformat(), day_dates[train_end - 1].isoformat()],
            "validation": [day_dates[train_end].isoformat(), day_dates[val_end - 1].isoformat()],
            "test": [day_dates[val_end].isoformat(), day_dates[-1].isoformat()],
        },
        "pricing_version": pricing["version"],
        "fx_myr_per_usd_demo": fx,
        "applications": list(APPS),
        "categories": list(CATEGORIES),
        "assumptions": {
            "count_model": "Poisson-gamma (k=50) around base x weekday x trend x peaks x exp(AR(1) noise, phi=0.6)",
            "tokens": "lognormal per category, clipped (input 50-8000, output 5-1024)",
            "model_mix": {a: p["mix"] for a, p in APPS.items()},
            "trend_per_day": {a: p["trend_per_day"] for a, p in APPS.items()},
            "peaks": {a: p["peaks"]["label"] for a, p in APPS.items()},
            "faq_eligible_share_of_static_faq": FAQ_ELIGIBLE_SHARE,
            "paraphrase_mix_and_matcher_recall": PARAPHRASE,
            "cache_overhead_per_lookup_myr": CACHE_OVERHEAD_PER_LOOKUP_MYR,
            "cache_fixed_daily_myr": CACHE_FIXED_DAILY_MYR,
        },
        "row_counts": {
            "requests_raw": len(requests),
            "requests_clean": len(clean),
            "daily_usage": len(daily),
            "anomaly_events": int((anomaly_truth.kind != "A8").sum()),
        },
        "data_quality": dq_report,
    }
    return {
        "requests": requests,
        "daily": daily,
        "anomaly_truth": anomaly_truth,
        "scenario_truth": scenario_truth,
        "manifest": manifest,
    }


def _anomaly_truth(events, day_dates, train_end, val_end, dq_report) -> pd.DataFrame:
    rows = []
    for ev in events:
        metric, mechanism, magnitude, klass, expected = EVENT_META[ev["kind"]]
        split = "train" if ev["start"] < train_end else "validation" if ev["start"] < val_end else "test"
        rows.append(
            {
                "event_id": ev["event_id"],
                "kind": ev["kind"],
                "app_id": ev["app"],
                "metric": metric,
                "start_date": day_dates[ev["start"]].isoformat(),
                "end_date": day_dates[ev["end"]].isoformat(),
                "mechanism": mechanism,
                "magnitude": magnitude,
                "event_class": klass,
                "alert_expected": expected,
                "split": split,
            }
        )
    for name in ("missing_values", "duplicated_rows", "delayed_records", "out_of_order", "extreme_legit"):
        rows.append(
            {
                "event_id": f"DQ-{name}",
                "kind": "A8",
                "app_id": "all",
                "metric": "data_quality",
                "start_date": day_dates[0].isoformat(),
                "end_date": day_dates[-1].isoformat(),
                "mechanism": f"injected {name.replace('_', ' ')}",
                "magnitude": None,
                "event_class": "data_quality",
                "alert_expected": "no",
                "split": "all",
            }
        )
    return pd.DataFrame(rows)


def _scenario_truth(clean: pd.DataFrame) -> pd.DataFrame:
    """Potential outcomes on the same demand stream: no cache vs approved-FAQ semantic cache.

    A request is avoided only if it is FAQ-eligible AND the matcher recognizes it (missed hits stay
    billed). Overhead: per-lookup cost for every static_faq lookup + fixed daily share.
    """
    g = clean.assign(
        hit=clean.cache_eligible & clean.matcher_recognizes,
        lookup=clean.request_category == "static_faq",
    )
    g = g.assign(avoided=np.where(g.hit, g.cost_myr, 0.0))
    out = (
        g.groupby(["day", "app_id"])
        .agg(
            requests=("request_id", "size"),
            static_faq_requests=("lookup", "sum"),
            eligible_requests=("cache_eligible", "sum"),
            true_hits=("hit", "sum"),
            baseline_cost_myr=("cost_myr", "sum"),
            avoided_cost_myr=("avoided", "sum"),
        )
        .reset_index()
    )
    out["overhead_myr"] = out.static_faq_requests * CACHE_OVERHEAD_PER_LOOKUP_MYR + CACHE_FIXED_DAILY_MYR
    out["cached_cost_myr"] = out.baseline_cost_myr - out.avoided_cost_myr + out.overhead_myr
    out["true_net_savings_myr"] = out.baseline_cost_myr - out.cached_cost_myr
    out["data_origin"] = "synthetic"
    return out.round(6)


def write(result: dict, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    files = {
        "requests_synthetic.csv": result["requests"],
        "daily_usage_synthetic.csv": result["daily"],
        "anomaly_truth.csv": result["anomaly_truth"],
        "scenario_truth.csv": result["scenario_truth"],
    }
    hashes = {}
    for name, frame in files.items():
        path = output / name
        frame.to_csv(path, index=False, lineterminator="\n")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {**result["manifest"], "files_sha256": hashes}
    (output / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n")
    return manifest
