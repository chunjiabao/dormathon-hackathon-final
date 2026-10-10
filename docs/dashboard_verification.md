# Dashboard verification

Phase 4 uses the real local FastAPI/PostgreSQL stack with the offline mock Anthropic provider. Start a seeded API before running browser checks. The checks use port **3100**, so an older app already listening on 3000 cannot be reused accidentally.

## Prepare the API (PowerShell, from the repository root)

```powershell
cd apps/api
# Docker-free option: start the existing embedded database and set DATABASE_URL from its printed value.
$env:DATABASE_URL = (.venv/Scripts/python.exe scripts/local_db.py).Trim()
$env:ANTHROPIC_MODE = "mock"
$env:ALLOWED_ORIGINS = '["http://localhost:3000","http://localhost:3100"]'
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m app.jobs.bootstrap
# If history/evaluation/forecast are absent, create them (synthetic demo data only):
.venv/Scripts/python.exe ../../scripts/seed_demo.py --evaluate --predict
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep that terminal running. `uv run` may replace `.venv/Scripts/python.exe` when uv is available. The browser checks expect completed forecast/evaluation records and initially disabled demo policies for the activation test. The activation test skips when a policy is already enabled rather than changing that existing policy. Tests add mock request metadata, recommendations/scenarios and immutable audit entries; do not run against customer or production data.

## Verify the frontend (another terminal)

```powershell
cd apps/web
npm ci
npx playwright install chromium
npm run lint
npm run typecheck
npm run build
npm run test:dashboard
```

Playwright starts and stops the production frontend on `http://localhost:3100`. Its configuration rejects reuse of an existing server on that port. The API permits both development port 3000 and test port 3100 through the explicit CORS setting above. To reuse a locally installed Chromium instead of downloading one, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to its `chrome.exe` before running the tests.

The eight checks cover all screens and evaluation tabs, viewer restrictions, mobile navigation and CSV export, chat reconnection/mock labels, scenario error recovery, owner approval/cache/bypass/disable, all screens at 360px, and budget persistence/restoration. Approval checks disable their activated demo policies afterward; budget checks restore the original budget.

Screenshots are saved under `artifacts/phase4/`; failure traces and browser snapshots under `apps/web/test-results/`. Both are git-ignored. No Anthropic API charges are incurred.

## Local preview

After building, run `npm run start -- --port 3100` with the mock API still running. Visit `http://localhost:3100/login` and choose the demo owner or viewer. For development, run `npm run dev` and use port 3000 with a freshly restarted frontend.

Hosted Supabase authentication, live Anthropic calls, browser CI orchestration and deployment verification remain Phase 5 work.
