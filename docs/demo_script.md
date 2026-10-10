# Three-minute demo

Use mock mode and say so. Forecast metrics use deterministic synthetic history; mock gateway calls are not real Anthropic spend. Keep a local API/database/dashboard fallback available.

- 0:00-0:30: Overview. Explain the RM200 budget, forecast, uncertainty interval, data provenance and projected overrun. Read the current values; do not promise a fixed result after reseeding.
- 0:30-1:00: Usage and Predictions. Show cost drivers, forecast horizon and interval. Explain that estimates use demo pricing, not an invoice.
- 1:00-1:30: Anomalies and Evaluation. Show reason codes and held-out synthetic metrics, including weaker interval coverage and drift limitations.
- 1:30-2:30: Decision Lab. Generate a recommendation, inspect scenario assumptions, approve as owner, then ask a repeated bakery FAQ. Show a cache hit and a personal-order question bypass. Disable the policy and show provider calls resume. Never represent mock replies as live provider verification.
- 2:30-3:00: Audit and Settings. Show approval history and read-only viewer controls. State that savings are estimated avoided calls, and production credentials remain on the backend.

For a measured terminal replay, start with all policies disabled and run `make demo` (or from `apps/api`, `uv run python ../../scripts/demo_replay.py --approve --disable-after`). The replay defaults to mock mode, compares the same ten prompts, checks reduction, and restores disabled policies after the final sequence. On hosted production, provide a short-lived owner token through `TOKENGUARD_OWNER_TOKEN`; never paste it in chat or commit it. Live replay needs explicit `--allow-live` and may bill up to twenty requests.

Before presentation: check readiness, load the dashboard, confirm the owner and viewer, run browser checks, and rehearse once. Do not reset shared data. Local mock replay verified on 2026-10-11: ten identical prompts required 10 provider calls before approval and 3 afterward, with 7 exact FAQ hits and 3 safety bypasses. Policies were disabled afterward. Hosted rehearsal is pending.
