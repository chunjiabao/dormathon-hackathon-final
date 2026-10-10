# Synthetic demo without Supabase

No Supabase, Render, Vercel or Anthropic account is required. PostgreSQL + pgvector stores the local demo data; the embedded database option runs without Docker. Forecast history is synthetic; chatbot provider replies are mock. Mock gateway requests are separately labelled and are not provider spend.

## Start from the repository root (PowerShell)

Copy `.env.example` to `.env` if it does not exist. Set `ANTHROPIC_MODE=mock`, `APP_ENV=development`, `DEMO_MODE=true`, and leave all Supabase and Anthropic keys empty. Set `ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:3100"]`.

In a database terminal:

```powershell
cd apps/api
uv sync
uv run python scripts/local_db.py
```

Copy the printed DATABASE_URL into the ignored root `.env`. Keep the database available. In a second terminal, from the repository root:

```powershell
cd apps/api
uv run alembic upgrade head
uv run python ../../scripts/seed_demo.py --evaluate --predict
uv run uvicorn app.main:app --port 8000 --no-access-log
```

In a third terminal, from the repository root:

```powershell
cd apps/web
npm ci
npm run build
npm run start -- --port 3100
```

Open http://localhost:3100/login and choose the demo owner or viewer. Backend readiness is http://localhost:8000/api/v1/health. Current local database and seed already exist, so do not reseed unless you want to regenerate this workspace's synthetic history. Evaluation can take several minutes on a new machine.

## Rehearse and verify

From the repository root, while API/database are running:

```powershell
apps/api/.venv/Scripts/python.exe scripts/smoke_test.py --no-chat
apps/api/.venv/Scripts/python.exe scripts/demo_replay.py --approve --disable-after
```

Start with all policies disabled. The verified replay produces seven safe FAQ hits and three bypasses after approval (10 provider calls before, 3 afterward), then disables policies. Follow demo_script.md for the three-minute presentation.

For automated browser tests, stop the frontend on port 3100 first; Playwright starts its own server. From `apps/web`, install Chromium once using `npx playwright install chromium`, then run `npm run test:dashboard`. Keep API/database running. CI uses an isolated PostgreSQL container and mock provider; no cloud credentials are required.

## Verification recorded 2026-10-11

API suite passed against PostgreSQL; frontend lint, types and production build passed; all eight browser checks passed on the refreshed API; runtime npm audit reports zero vulnerabilities; local smoke checks passed; measured mock replay reduced provider calls from 10 to 3. Five high development-tool dependency findings remain documented in security.md. Docker/cloud/live-provider checks are outside this local demo scope and remain unverified.
