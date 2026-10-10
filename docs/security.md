# Security and operational limits

Production requires HTTPS Supabase issuer/JWKS, asymmetric signatures, audience/expiry/issuer claims, explicit HTTPS CORS origins, TLS PostgreSQL and at least 32-character chat/fingerprint/scheduler secrets. Development login and reset/seed routes are hidden outside demo mode. Owner mutations are workspace-scoped and audited; chat tokens grant no dashboard access. Database policies and constraints are tested against PostgreSQL.

Raw user prompts are not persisted. Request/client fingerprints are keyed; approved fixture responses can be cached. The daily job aggregates complete days before retention: request metadata is kept for 30 calendar days (rounded to workspace midnight to avoid partial aggregate loss), real daily aggregates for 180 days, expired cache entries are removed. Synthetic fixtures and immutable audit rows are preserved. Retention requires the daily job to run; it is not an automatic database TTL.

The limiter is per-process. Deploy one API instance until a shared rate-limit store is implemented. Public chat can incur charges in live mode; configure provider budget controls and monitor usage. Mock mode is the deployable fallback. Pricing fixtures are demo estimates and have not been freshly verified against a provider invoice.

Frontend runtime dependency audit passes locally after removing unused CLI dependencies and overriding PostCSS. The full audit still reports five high findings in development tooling; do not use untrusted glob input in build/lint jobs. A clean runtime audit does not establish comprehensive security. Docker execution, real Supabase login, hosted isolation, live Anthropic and hosted scheduler verification remain pending.
