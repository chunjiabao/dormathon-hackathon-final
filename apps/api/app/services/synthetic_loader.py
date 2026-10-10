"""Load a generated synthetic dataset into a workspace (data_origin='synthetic' only).

The dataset manifest and injected anomaly ground truth are stored in evaluation_runs
(method 'synthetic_dataset') so the dashboard can show provenance and explain synthetic
anomalies by their known injection mechanism. Ground truth is never used by detectors.
"""

import json
from pathlib import Path

import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.models import DailyUsage, EvaluationRun, Workspace
from app.services.history import app_maps

DATASET_METHOD = "synthetic_dataset"


def load_synthetic(session: Session, ws: Workspace, data_dir: Path, generated: dict | None = None) -> dict:
    """Replace the workspace's synthetic daily_usage with the dataset in data_dir (or `generated`)."""
    if generated is None:
        manifest = json.loads((data_dir / "dataset_manifest.json").read_text())
        daily = pd.read_csv(data_dir / "daily_usage_synthetic.csv")
        truth = pd.read_csv(data_dir / "anomaly_truth.csv")
    else:
        manifest, daily, truth = generated["manifest"], generated["daily"], generated["anomaly_truth"]
    _, name_to_id = app_maps(session, ws.id)
    missing = set(daily.app_id) - set(name_to_id)
    if missing:
        raise ValueError(f"workspace has no applications named {sorted(missing)}")
    session.execute(delete(DailyUsage).where(DailyUsage.workspace_id == ws.id, DailyUsage.data_origin == "synthetic"))
    rows = [
        {
            "workspace_id": ws.id, "application_id": name_to_id[r.app_id], "day": pd.Timestamp(r.day).date(),
            "request_category": r.request_category, "model": r.model, "requests": int(r.requests),
            "input_tokens": int(r.input_tokens), "output_tokens": int(r.output_tokens),
            "cost_myr": round(float(r.cost_myr), 6), "cache_hits": int(r.cache_hits),
            "retry_requests": int(r.retry_requests), "data_origin": "synthetic",
        }
        for r in daily.itertuples()
    ]  # fmt: skip
    session.execute(insert(DailyUsage), rows)
    session.execute(
        delete(EvaluationRun).where(EvaluationRun.workspace_id == ws.id, EvaluationRun.method == DATASET_METHOD)
    )
    truth_records = json.loads(truth.to_json(orient="records"))
    session.add(
        EvaluationRun(
            workspace_id=ws.id,
            dataset_version=f"{manifest['generator_version']}:{manifest['start_date']}..{manifest['end_date']}",
            seed=manifest["seed"],
            method=DATASET_METHOD,
            metrics_json={"manifest": manifest, "anomaly_truth": truth_records},
            artifact_path=None,
            data_origin="synthetic",
        )
    )
    session.commit()
    return {"rows": len(rows), "start_date": manifest["start_date"], "end_date": manifest["end_date"]}


def dataset_record(session: Session, workspace_id) -> EvaluationRun | None:
    return session.scalar(
        select(EvaluationRun).where(EvaluationRun.workspace_id == workspace_id, EvaluationRun.method == DATASET_METHOD)
    )
