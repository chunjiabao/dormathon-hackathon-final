# Cloud deployment runbook

Target repository: https://github.com/jeremytey/dormathon-hackathon-final.
Selected Supabase project: `bcackoibrckzfwbcsgth`. Project URL: `https://bcackoibrckzfwbcsgth.supabase.co`. JWKS URL: `https://bcackoibrckzfwbcsgth.supabase.co/auth/v1/.well-known/jwks.json`. Project access and credentials are not yet connected.

Prepared on 2026-10-11. No hosted deployment or live-provider check has been completed.

## 1. Supabase
Create or select a project. Copy its TLS database URL from Connect; use a direct connection or the session pooler on port 5432 for this long-lived API. Use the session pooler when the host needs IPv4. Change the scheme to `postgresql+psycopg://` and append `sslmode=require` (use `&` if a query already exists). URL-encode the password. Do not commit it.

Enable an asymmetric JWT signing key (RS256 or ES256), create the owner in Auth, and copy the owner's UUID. Set `SUPABASE_URL=https://<project>.supabase.co` and `SUPABASE_JWKS_URL=https://<project>.supabase.co/auth/v1/.well-known/jwks.json`.

## 2. Render API
Import `render.yaml` from the selected repository branch. The Docker build root is `apps/api`; migrations and bootstrap run at startup. Configure every `sync: false` environment variable in the dashboard. Set `OWNER_AUTH_USER_ID` to the Supabase owner UUID. Set `ALLOWED_ORIGINS` to a JSON array containing the exact HTTPS Vercel origin. Keep `APP_ENV=production` and `DEMO_MODE=false`. Generated secrets must contain at least 32 characters.

Use mock mode for the first deployment (`ANTHROPIC_MODE=mock`). Configure the Anthropic key securely only when ready for a billed verification. Production readiness returns HTTP 503 when PostgreSQL is unavailable. Docker image execution remains unverified locally because Docker is unavailable on this machine.

Seed synthetic history from a trusted operator checkout, with production environment variables set securely in that process: from `apps/api`, run `uv run alembic upgrade head`, then `uv run python ../../scripts/seed_demo.py --evaluate --predict`. These scripts are outside the backend Docker build root. They are not public HTTP routes. Reseeding replaces this workspace's synthetic history; select the intended demo project first.

## 3. Vercel dashboard
Import the repository and set Root Directory to `apps/web`. Enable inclusion of files outside the root directory so the build can read `docs/model_card.md`. Set `NEXT_PUBLIC_API_BASE_URL` to the Render HTTPS origin, `NEXT_PUBLIC_SUPABASE_URL` to the project URL, and `NEXT_PUBLIC_SUPABASE_ANON_KEY` to its public anon key. Never put the service role key, database password, scheduler secret, or Anthropic key in frontend variables. Rebuild after changing public variables. Add the final Vercel origin to Render's CORS allowlist and Supabase Auth redirect URLs.

## 4. Scheduled job
Use a private external scheduler to POST `/api/v1/jobs/daily` once daily after Kuala Lumpur midnight (for example 00:15 MYT / 16:15 UTC). Send `X-Scheduler-Secret` from the scheduler's secret store. This aggregates completed days, forecasts, detects anomalies, then expires metadata/cache. Never embed the secret in a URL or repository workflow. Manual owner forecast execution is the fallback if the scheduler is unavailable.

## 5. Verification and rollback
Run `scripts/smoke_test.py --base-url <API origin> --no-chat`; verify readiness, login with the real owner, and verify viewer read-only access, all dashboard pages, approval/cache-hit/bypass/disable behavior, and CORS. Confirm dev login and demo seed return 404. A real-provider check must use an uncached request and confirm provider metadata; mock success does not prove Anthropic connectivity. Record both deployed URLs, commit SHA, and results before marking Phase 5 complete.

Rollback Vercel and Render to the previous successful commit. Back up the database before migrations; application rollback does not undo schema changes. Do not run demo reset against shared production data. Keep the local mock demo as a fallback.

## Platform references
- [Supabase database connections](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Supabase JWT verification](https://supabase.com/docs/guides/auth/jwts)
- [Render monorepo builds](https://render.com/docs/monorepo-support)
- [Render readiness checks](https://render.com/docs/health-checks)
- [Vercel monorepo configuration](https://vercel.com/docs/monorepos/monorepo-faq)
