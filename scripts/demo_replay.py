"""Reproducible request replay: the same FAQ-heavy prompt sequence before and after cache approval.

    python scripts/demo_replay.py --base-url http://localhost:8000 [--approve] [--disable-after]

Counts provider calls vs cache hits for an identical sequence. In mock mode no money is spent;
in live mode every non-cached request is a real (billed) Anthropic call, so keep the list short.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PROMPTS = [
    "What time do you open?",
    "When are you open?",
    "Do you open on Sunday?",
    "Do you deliver?",
    "How much is Chocolate Cake?",
    "What cakes do you have?",
    "Is my order ready?",
    "Do you deliver to my address?",
    "Can I order a cake for 50 people?",
    "What are your opening hours?",
]


def call(base, method, path, body=None, token=None):
    if urllib.parse.urlsplit(base).scheme not in {"http", "https"}:
        raise ValueError("API URL must use HTTP or HTTPS")
    req = urllib.request.Request(
        f"{base}/api/v1{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
    )
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} failed with HTTP {e.code}") from e


def replay(base, label):
    _, sess = call(base, "POST", "/chat/session")
    provider, hits, rows = 0, 0, []
    for p in PROMPTS:
        _, r = call(
            base,
            "POST",
            "/chat",
            {"application_id": sess["application_id"], "message": p},
            sess["token"],
        )
        hit = r["cache_status"] in ("exact_hit", "semantic_hit")
        hits += hit
        provider += not hit
        rows.append(
            f"    {r['cache_status']:12s} {r.get('cache_decision') or '':38s} {p}"
        )
    print(
        f"{label}: {provider} provider calls, {hits} cache hits out of {len(PROMPTS)} requests"
    )
    print("\n".join(rows))
    return provider, hits


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--base-url", default="http://localhost:8000")
    a.add_argument(
        "--approve",
        action="store_true",
        help="generate + approve the recommendation (dev login)",
    )
    a.add_argument("--disable-after", action="store_true")
    a.add_argument(
        "--allow-live",
        action="store_true",
        help="explicitly permit billed replay calls",
    )
    args = a.parse_args()
    base = args.base_url.rstrip("/")
    _, health = call(base, "GET", "/health")
    if health["dependencies"]["anthropic"]["mode"] != "mock" and not args.allow_live:
        sys.exit(
            "Replay requires mock mode unless --allow-live is explicitly supplied."
        )
    token = os.environ.get("TOKENGUARD_OWNER_TOKEN")
    if args.approve:
        if not token:
            _, tok = call(base, "POST", "/auth/dev-login", {"role": "owner"})
            token = tok["access_token"]
        _, pols = call(base, "GET", "/policies", None, token)
        if any(p["enabled"] for p in pols["items"]):
            sys.exit(
                "Start with all demo policies disabled to measure a valid baseline."
            )
    before = replay(base, "BEFORE")
    if args.approve:
        call(base, "POST", "/forecasts/run", {}, token)
        _, rec = call(base, "POST", "/recommendations/generate", None, token)
        print(f"\nRecommendation: {rec['action_type']}\n  {rec['rationale']}\n")
        if rec["action_type"] != "enable_semantic_cache":
            sys.exit("Nothing to approve.")
        status, res = call(
            base,
            "POST",
            f"/recommendations/{rec['id']}/approve",
            {"expected_version": rec["version"]},
            token,
        )
        print(f"Approve -> HTTP {status}, status {res.get('status')}\n")
    try:
        after = replay(base, "AFTER")
    finally:
        if args.disable_after and args.approve:
            _, pols = call(base, "GET", "/policies", None, token)
            for policy in pols["items"]:
                if policy["enabled"]:
                    call(base, "POST", f"/policies/{policy['id']}/disable", None, token)
            print("Policies disabled (provider calls resume).")
    print(f"\nProvider calls: {before[0]} -> {after[0]} for the identical sequence.")
    if args.approve and not (after[0] < before[0] and after[1] > before[1]):
        sys.exit("Replay did not demonstrate fewer provider calls and more cache hits.")


if __name__ == "__main__":
    main()
