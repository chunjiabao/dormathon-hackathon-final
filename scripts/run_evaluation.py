"""Run the offline forecast + anomaly evaluation on the generated synthetic dataset.

    cd apps/api && uv run python ../../scripts/run_evaluation.py [--data ../../data/generated] [--db]

Writes artifacts/evaluation/evaluation.json and docs/evaluation_report.md (generated from the
measured metrics). With --db, also stores an evaluation_runs row (DATABASE_URL).
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

import pandas as pd  # noqa: E402

from app.ml.evaluate import evaluate_all, json_safe  # noqa: E402
from app.ml.report import render_report  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, default=ROOT / "data" / "generated")
    p.add_argument("--out", type=Path, default=ROOT / "artifacts" / "evaluation")
    p.add_argument("--db", action="store_true", help="also persist to evaluation_runs")
    args = p.parse_args()

    manifest = json.loads((args.data / "dataset_manifest.json").read_text())
    daily = pd.read_csv(args.data / "daily_usage_synthetic.csv")
    truth = pd.read_csv(args.data / "anomaly_truth.csv")
    scenario_truth = pd.read_csv(args.data / "scenario_truth.csv")
    t0 = time.time()
    result = json_safe(evaluate_all(daily, truth, manifest, scenario_truth))
    result["runtime_seconds"] = round(time.time() - t0, 1)
    result["anomaly_truth"] = json_safe(truth.to_dict(orient="records"))

    args.out.mkdir(parents=True, exist_ok=True)
    out_file = args.out / "evaluation.json"
    out_file.write_text(json.dumps(result, indent=2) + "\n")
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "evaluation_report.md").write_text(render_report(result), encoding="utf-8")
    print(f"Evaluation written to {out_file} ({result['runtime_seconds']}s)")
    print(json.dumps(result["summary"], indent=2))

    if args.db:
        from sqlalchemy.orm import Session

        from app.db import get_engine
        from app.services.evaluation import store_evaluation

        with Session(get_engine()) as s:
            run = store_evaluation(s, result, str(out_file.relative_to(ROOT)))
            print(f"Stored evaluation_runs row {run.id}")


if __name__ == "__main__":
    main()
