"""Offline evaluation of the safe FAQ cache on the labelled query set (no LLM, no DB).

Outcome per query: 'hit' (with an intent) or 'no_hit' (bypass by the safety gate or no confident
match). A false hit is any hit whose intent differs from expected_intent (including every hit on
an item whose expected_intent is null). Primary metric: precision of accepted hits.
"""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from app.services import faq_eligibility
from app.services.cache import match

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
THRESHOLD_GRID = (0.85, 0.88, 0.90, 0.92, 0.95, 0.97, 0.99)


def load_catalog(name: str = "bakery_faq.json") -> tuple[list, list[str]]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    entries = [
        SimpleNamespace(intent_key=e["intent_key"], question=e["question"], aliases=e["aliases"],
                        approved_answer=e["answer"])
        for e in data["entries"]
    ]  # fmt: skip
    return entries, data.get("products", [])


def run_query(entries, products, query: str, threshold: float, use_gate: bool = True) -> dict:
    t0 = time.perf_counter()
    gate = faq_eligibility.check(query, "en", products)
    if use_gate and not gate.eligible:
        out = {"outcome": "no_hit", "decision": f"bypass_{gate.reason}", "intent": None, "similarity": None}
    else:
        d = match(entries, products, query, threshold)
        out = {"outcome": "hit" if d.eligible else "no_hit", "decision": d.decision, "intent": d.intent_key,
               "similarity": None if d.similarity is None else round(d.similarity, 4)}  # fmt: skip
    out["latency_ms"] = (time.perf_counter() - t0) * 1000
    return out


def score(items: list[dict], results: list[dict]) -> dict:
    hits = [(i, r) for i, r in zip(items, results, strict=True) if r["outcome"] == "hit"]
    correct = [1 for i, r in hits if r["intent"] == i["expected_intent"]]
    false_hits = [
        {"query": i["query"], "expected": i["expected_intent"], "got": r["intent"], "similarity": r["similarity"]}
        for i, r in hits if r["intent"] != i["expected_intent"]
    ]  # fmt: skip
    positives = [i for i in items if i["expected_intent"]]
    by_group = {}
    for g in sorted({i["group"] for i in items}):
        gi = [(i, r) for i, r in zip(items, results, strict=True) if i["group"] == g]
        by_group[g] = {
            "n": len(gi),
            "hits": sum(r["outcome"] == "hit" for _, r in gi),
            "correct_hits": sum(r["outcome"] == "hit" and r["intent"] == i["expected_intent"] for i, r in gi),
        }
    return {
        "n": len(items),
        "accepted_hits": len(hits),
        "hit_precision": len(correct) / len(hits) if hits else None,
        "positive_coverage": len(correct) / len(positives) if positives else None,
        "false_hits": len(false_hits),
        "false_hit_examples": false_hits[:10],
        "adversarial_false_hits": sum(1 for f in false_hits if f["expected"] is None),
        "by_group": by_group,
    }


def evaluate_cache(threshold: float = 0.95) -> dict:
    data = json.loads((FIXTURES / "cache_eval_set.json").read_text(encoding="utf-8"))
    items = data["items"]
    entries, products = load_catalog()
    results = [run_query(entries, products, i["query"], threshold) for i in items]
    lat = np.array([r["latency_ms"] for r in results[1:]])  # first call may include model warm-up
    sweep = []
    for t in THRESHOLD_GRID:
        s = score(items, [run_query(entries, products, i["query"], t) for i in items])
        sweep.append({"threshold": t, **{k: s[k] for k in ("hit_precision", "positive_coverage", "false_hits")}})
    # Ablation: what the embedding alone would do without the deterministic gate (shows why the gate exists).
    no_gate = score(items, [run_query(entries, products, i["query"], threshold, use_gate=False) for i in items])
    return {
        "threshold": threshold,
        "margin": 0.03,
        "model": "sentence-transformers/all-MiniLM-L6-v2 (local ONNX)",
        "data_origin": "synthetic (hand-labelled demo queries)",
        **score(items, results),
        "latency_ms": {"median": float(np.median(lat)), "p95": float(np.percentile(lat, 95))},
        "threshold_sweep": sweep,
        "ablation_without_safety_gate": {k: no_gate[k] for k in ("hit_precision", "false_hits", "false_hit_examples")},
        "per_query": [
            {"query": i["query"], "group": i["group"], "expected": i["expected_intent"], **r}
            for i, r in zip(items, results, strict=True)
        ],  # fmt: skip
        "caveat": "Zero false hits on this provided set does not imply zero errors in general.",
    }
