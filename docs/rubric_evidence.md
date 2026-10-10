# Evidence map

| Capability | Reviewable evidence | Limit |
|---|---|---|
| Forecasting and anomalies | evaluation_report.md, model_card.md; API analytics tests | Synthetic held-out evaluation |
| Approval and safe caching | API cache/decision tests, dashboard.spec.ts owner flow | Local mock provider |
| Tenant isolation and roles | test_tenant_isolation.py, test_auth.py, PostgreSQL integrity tests | Hosted account verification pending |
| Dashboard and mobile | dashboard_verification.md and eight browser tests | Local production frontend |
| Deployment readiness | deployment.md, render.yaml, Dockerfile, CI dashboard job | No hosted URLs or remote CI result yet |
| Reproducible demo | demo_script.md, scripts/demo_replay.py | Local mock replay: 10 calls to 3; hosted rehearsal pending |
| Production hardening | security.md, config/auth/readiness/retention tests | Development dependency findings remain |

Do not mark cloud deployment, real-provider verification or hosted scheduling complete until their URLs/results are recorded.
