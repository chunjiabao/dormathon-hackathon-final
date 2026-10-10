"""Generate the deterministic synthetic dataset (all rows labelled data_origin=synthetic).

    cd apps/api && uv run python ../../scripts/generate_synthetic.py --seed 42 --days 180 \
        --output ../../data/generated/ [--end-date 2026-10-09]

Same (seed, days, end-date) => byte-identical files. --end-date defaults to yesterday in
Asia/Kuala_Lumpur so the demo history runs up to the present; it is recorded in the manifest.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.ml.synthetic import generate, write  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--end-date", type=date.fromisoformat, default=None)
    p.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "generated")
    args = p.parse_args()
    manifest = write(generate(args.seed, args.days, args.end_date), args.output)
    print(f"Wrote synthetic dataset to {args.output.resolve()}")
    print(f"  period {manifest['start_date']} .. {manifest['end_date']} (seed {manifest['seed']})")
    for k, v in manifest["row_counts"].items():
        print(f"  {k}: {v}")
    print(f"  data quality: {manifest['data_quality']}")


if __name__ == "__main__":
    main()
