# TokenGuard architecture

The Next.js dashboard authenticates with Supabase and sends bearer JWTs to FastAPI. FastAPI validates the project's JWKS, then authorizes every workspace resource through membership. Owner actions write an immutable policy audit; viewers can inspect but cannot approve or edit.

Public BakeryBot receives a short-lived token scoped to one workspace/application. The gateway classifies each request, checks approved FAQ cache policy and safety exclusions, and serves an exact/semantic hit or makes one provider request. Provider usage drives estimated MYR cost; mock mode is explicitly identified. No raw user prompt is stored. pgvector supports approved FAQ matching.

PostgreSQL stores workspace data, request metadata, daily aggregates, model results, scenarios and audits. The daily job aggregates completed workspace days, runs forecasting and anomaly detection, then applies retention. Offline evaluation uses a deterministic synthetic dataset and held-out windows. Synthetic history and gateway traffic retain separate provenance.

Render hosts the Docker API; Supabase hosts PostgreSQL/Auth; Vercel builds the dashboard from apps/web with access to the repository model card. Backend secrets stay in backend/scheduler environment stores. See deployment.md for prerequisites and unverified hosted steps.
