"""Seed the demo workspace end to end (idempotent).

    cd apps/api && uv run python ../../scripts/seed_demo.py [--end-date YYYY-MM-DD] [--evaluate] [--predict]

1. bootstrap workspace/apps/FAQ/pricing;
2. generate the deterministic synthetic dataset (seed 42, 180 days ending yesterday unless given);
3. replace the workspace's synthetic daily_usage + store dataset manifest and injected ground truth;
4. --evaluate: run the offline evaluation and store it (thresholds for anomaly detection);
5. --predict: aggregate real traffic, run the forecast and anomaly detection.
"""

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy.orm import Session  # noqa: E402

from app.db import get_engine  # noqa: E402
from app.ml.synthetic import generate, write  # noqa: E402
from app.services.seed import bootstrap_demo  # noqa: E402
from app.services.synthetic_loader import load_synthetic  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--end-date", type=date.fromisoformat, default=None)
    p.add_argument("--data", type=Path, default=ROOT / "data" / "generated")
    p.add_argument("--evaluate", action="store_true")
    p.add_argument("--predict", action="store_true")
    args = p.parse_args()

    result = generate(args.seed, args.days, args.end_date)
    manifest = write(result, args.data)
    print(f"Generated synthetic dataset {manifest['start_date']}..{manifest['end_date']} -> {args.data}")
    with Session(get_engine()) as s:
        ws = bootstrap_demo(s)
        loaded = load_synthetic(s, ws, args.data, generated=result)
        print(f"Loaded {loaded['rows']} synthetic daily_usage rows into workspace '{ws.slug}'")

    if args.evaluate:
        subprocess.run(  # noqa: S603 - fixed local script
            [sys.executable, str(ROOT / "scripts" / "run_evaluation.py"), "--data", str(args.data), "--db"],
            check=True,
        )
    if args.predict:
        from app.jobs.predict import run_for_workspace

        with Session(get_engine()) as s:
            ws = bootstrap_demo(s)
            print(json.dumps(run_for_workspace(s, ws), indent=2, default=str))


if __name__ == "__main__":
    main()
