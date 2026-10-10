# TokenGuard AI — Master Implementation Build Pack

**Version:** 1.0 | **Project:** Predict Early, Decide Better | **Delivery target:** 24-hour hackathon MVP | **Coding agent:** generic (Cursor, Claude Code, Codex, Kiro, etc.)

## 0. EXECUTION INSTRUCTIONS FOR THE CODING AGENT

You are the lead full-stack engineer, ML engineer, data engineer, designer, QA engineer, and deployment engineer. Build this specification as a functioning monorepo. Do not stop at mockups, pseudocode, or a README. Implement every P0 acceptance criterion, run automated tests, and report factual results. Make routine engineering decisions yourself. Do not ask the human to choose packages, colors, endpoints, schemas, hosting settings, or algorithms. Ask only for secrets, account access, authorization, or actions that inherently require the human. Never fabricate credentials, metrics, real API calls, deployments, or performance. If a third-party account is unavailable, provide working local/demo fallback and explicit setup steps. Do not use LLM APIs for forecasting, anomaly detection, intervention ranking, embeddings, or recommendations. Only the bakery chatbot's actual uncached response generation may call Anthropic.

Read this file entirely before coding. If the `frontend-design` skill is available, invoke it before UI work. Retrieve the Notion `DESIGN.md` from getdesign.md if available; if unavailable, use the explicit visual rules below and document that the external design reference could not be read. Do not block implementation on that external resource. Build real functionality first, then polish. Maintain `IMPLEMENTATION_STATUS.md` with working/not-working/deferred and verified evidence. Finish with a concise runbook and exact commands.

## 1. GOAL AND SUCCESS DEFINITION

TokenGuard is a predictive AI cost intelligence and decision-support platform. Its core causal loop is: (1) observe existing Anthropic API usage; (2) forecast request volume, token consumption, and month-end cost; (3) flag future budget risk and statistically abnormal usage; (4) attribute the forecast to applications/models/eligible FAQ segments; (5) simulate how safe interventions would alter **the same forecast**; (6) recommend the feasible intervention with highest estimated net savings subject to quality and safety gates; (7) require explicit workspace-owner approval; (8) activate the policy and track actual outcomes against a credible counterfactual. The intervention engine must not call an LLM.

The delivered product has three working surfaces: **BakeryBot** (customer-facing sample chat), **TokenGuard Dashboard** (owner-facing), and **TokenGuard Backend** (gateway, usage ledger, caching, forecasting, anomaly detection, recommendation engine, API, scheduled jobs). A full working local demo is mandatory; public cloud deployment is required when the user supplies credentials/accounts.

### Scope: P0 versus P1

**P0 required:** sign-in and workspace; bakery FAQ chatbot; real Anthropic chat through gateway; safe cache exact + semantic matches; token/cost ledger; seeded synthetic history labelled as synthetic; live real traffic kept separate; forecasts with held-out evaluation; anomalous traffic scenarios and measured precision/recall; cost driver breakdown; single-intervention semantic-cache simulation and recommendation; explicit enable/disable approval; savings measurement; complete dashboard; tests; deployment configs; reproducible 3-minute demo.

**P1 if time permits:** provider-native prompt caching measurement/simulation; model-routing simulation (not automatic activation); multi-tenant onboarding beyond one demo workspace; advanced alerts and export. P1 must not delay P0.

**Non-goals:** universal OpenAI-compatible proxy; WhatsApp integration; autonomous provider switching; guaranteeing savings or semantic correctness; real payments/billing; training an LLM; storing customer secrets or personal conversations for optimisation.

## 2. FIXED ASSUMPTIONS

- Timezone for dashboard: Asia/Kuala_Lumpur; store timestamps UTC. Default display currency MYR; provider rates may be USD, converted with an explicitly configured fixed demo FX rate and labelled estimate. Never imply the demo FX rate is live.
- Budget: RM200 per calendar month, configurable by owner. Forecast horizon: remaining days in the current month; additional next-7-day estimate.
- Demo business: `Sweet Crumbs Bakery`, Malaysia, fictitious. FAQ corpus is synthetic, static, versioned, and safe for caching. Products: Vanilla Cloud Cake (RM55), Midnight Chocolate Cake (RM70), Red Velvet Cake (RM75). Sizes and availability are not guaranteed; no actual orders, payments, or personal customer records are processed. Hours Mon–Sat 10:00–18:00, closed Sunday; pickup available; delivery within an illustrative service area with fees confirmed manually. Explicitly label all business facts demo-only.
- Anthropic default model: `claude-haiku-4-5-20251001`, configurable via `ANTHROPIC_MODEL`. Validate support on startup; fail with actionable configuration message if unavailable. Do not silently switch providers.
- Anthropic API key is server-only. TokenGuard never exposes it to browsers. TokenGuard frontend authenticates to its own backend. No real payment processing.
- Synthetic dataset: 180 days, 3 app IDs (bakery_demo, tuition_demo, retail_demo), 4 traffic segments, deterministic random seed 42; label every synthetic row and prediction trained on synthetic data.
- Default semantic cache threshold 0.95 cosine; **not a guarantee** of answer equivalence. Static FAQ allowlist, canonical intent/answer ID, tenant/workspace isolation, knowledge-base version matching, locale matching, TTL, and conservative fallbacks are required. Cache only after passing these gates. For 24-hour MVP, use a small deterministic FAQ intent catalog and local embeddings; no LLM classification.
- Forecast model can train on synthetic + real data but report the breakdown. Synthetic and real datasets must never be presented as equivalent evidence. Real request records may be insufficient for standalone model training during the hackathon.

## 3. ARCHITECTURE AND REQUEST FLOW

```text
Next.js Dashboard ----JWT----> FastAPI /api/v1/* ---> Supabase PostgreSQL
         |                             |                 | pgvector
         |                             |                 +-- usage + forecast + policy + audit
BakeryBot frontend --JWT or signed demo token--> POST /api/v1/chat
                                       |
                                       v
                               Tenant / rate limit
                                       |
                               FAQ eligibility check
                                       |
                            Exact / semantic cache lookup
                                /             \
                         safe cache hit      cache miss
                              |                  |
                         return answer    Anthropic Messages API
                              |                  |
                              +---- usage ledger + cost estimation
                                               |
                                daily aggregation / model training
                                               |
                                 forecast + anomaly detector
                                               |
                              cost drivers + what-if simulator
                                               |
                             recommendation + owner approval
                                               |
                                  policy change + audit
```

Use direct Anthropic SDK in a typed service adapter. Support streaming as P1; P0 non-streaming response is acceptable. Backend uses SQLAlchemy 2.x + Alembic + psycopg for PostgreSQL; Supabase Auth JWT validation via JWKS and issuer/audience validation. Use database service credentials only in backend. For local tests use PostgreSQL via Docker Compose (pgvector image) and mock Anthropic provider; no Supabase credentials required. The hosted deployment uses Supabase Postgres and Auth.

**Separation of concerns:** prediction uses only past data; cost-driver attribution uses model forecasts per segment; simulation transforms future forecasted eligible demand; recommendation is deterministic; policy activation is an explicit authenticated action. No AI-generated explanatory prose is necessary: use fixed explanation templates populated from actual metrics.

## 4. REPOSITORY TREE

```text
tokenguard/
  README.md
  MASTER_BUILD_PACK.md
  IMPLEMENTATION_STATUS.md
  .env.example
  .gitignore
  docker-compose.yml
  Makefile
  render.yaml
  vercel.json (only if necessary)
  docs/
    architecture.md
    data_dictionary.md
    security.md
    model_card.md
    demo_script.md
    deployment.md
    evaluation_report.md
    rubric_evidence.md
  apps/
    web/
      package.json
      next.config.ts
      tailwind.config.ts (if required by version)
      components.json
      app/
        (auth)/login/page.tsx
        (dashboard)/layout.tsx
        (dashboard)/overview/page.tsx
        (dashboard)/predictions/page.tsx
        (dashboard)/anomalies/page.tsx
        (dashboard)/decisions/page.tsx
        (dashboard)/usage/page.tsx
        (dashboard)/evaluation/page.tsx
        (dashboard)/settings/page.tsx
        demo/chat/page.tsx
      components/
        app-sidebar.tsx
        topbar.tsx
        metric-card.tsx
        forecast-chart.tsx
        anomaly-table.tsx
        driver-breakdown.tsx
        scenario-comparison.tsx
        recommendation-card.tsx
        approval-dialog.tsx
        demo-chat.tsx
        data-source-badge.tsx
      lib/api.ts
      lib/auth.ts
      lib/types.ts
      lib/format.ts
      tests/
    api/
      pyproject.toml
      Dockerfile
      alembic.ini
      alembic/versions/
      app/
        main.py
        config.py
        db.py
        auth.py
        models.py
        schemas.py
        api/{health,chat,usage,forecasts,anomalies,decisions,policies,evaluation,settings,demo}.py
        services/{anthropic_adapter,costing,usage_logger,faq_eligibility,embeddings,cache,forecast,anomaly,drivers,simulator,recommender,measurement,seed}.py
        jobs/{aggregate,train,evaluate,predict}.py
        ml/{features,train_forecast,train_anomaly,backtest,metrics}.py
        fixtures/{bakery_faq.json,pricing.json}
      tests/{test_auth,test_chat,test_cache,test_forecast,test_anomaly,test_simulator,test_approval,test_tenant_isolation,test_api}.py
  scripts/
    generate_synthetic.py
    seed_demo.py
    run_evaluation.py
    smoke_test.py
    demo_replay.py
  data/
    generated/.gitkeep
  artifacts/
    .gitkeep
  .github/workflows/ci.yml
```

No generated secrets, raw customer prompts, or private datasets in git. Commit synthetic seed script, not necessarily large generated CSV. Provide one-command generation.

## 5. DATABASE SCHEMA (POSTGRESQL)

Create Alembic migrations. All tenant tables include `workspace_id`, and backend queries must always scope by authenticated workspace. UUID PKs default `gen_random_uuid()`; timestamps timestamptz UTC. Index time-series columns and workspace foreign keys. pgvector extension enabled where supported; otherwise fall back to exact FAQ matching with a documented warning (do not claim semantic caching works).

1. `workspaces(id uuid PK, name text, slug text UNIQUE, monthly_budget_myr numeric(12,4), currency text DEFAULT 'MYR', timezone text DEFAULT 'Asia/Kuala_Lumpur', knowledge_version int DEFAULT 1, created_at timestamptz)`.
2. `workspace_members(id uuid PK, workspace_id uuid FK, auth_user_id uuid, role text CHECK IN ('owner','viewer'), UNIQUE(workspace_id,auth_user_id))`.
3. `applications(id uuid PK, workspace_id uuid FK, name text, app_key_hash text UNIQUE, is_active bool, created_at timestamptz)`; application API keys hashed, shown once, rotated on demand; demo chat may instead use a signed short-lived scoped token.
4. `api_requests(id uuid PK, workspace_id uuid FK, application_id uuid FK, occurred_at timestamptz, provider text, model text, request_category text, input_tokens int, output_tokens int, cache_read_tokens int DEFAULT 0, cache_write_tokens int DEFAULT 0, estimated_cost_myr numeric(14,8), cache_status text CHECK IN ('miss','exact_hit','semantic_hit','bypass','error'), latency_ms int, provider_request_id text NULL, data_origin text CHECK IN ('real','synthetic'), request_fingerprint text, pricing_version text, error_code text NULL)`; no raw user message by default.
5. `faq_entries(id uuid PK, workspace_id uuid FK, application_id uuid FK, intent_key text, question text, approved_answer text, locale text, knowledge_version int, cacheable bool, expires_at timestamptz NULL, embedding vector(384) NULL, UNIQUE(application_id,intent_key,locale,knowledge_version))`.
6. `response_cache(id uuid PK, workspace_id uuid FK, application_id uuid FK, faq_entry_id uuid FK, normalized_query_hash text, query_embedding vector(384), answer text, locale text, knowledge_version int, expires_at timestamptz, created_at timestamptz, last_hit_at timestamptz, hit_count int DEFAULT 0)`; do not cache arbitrary user-specific LLM responses.
7. `daily_usage(id uuid PK, workspace_id uuid FK, application_id uuid FK, day date, request_category text, model text, requests int, input_tokens bigint, output_tokens bigint, cost_myr numeric(14,6), cache_hits int, data_origin text, UNIQUE(workspace_id,application_id,day,request_category,model,data_origin))`.
8. `forecast_runs(id uuid PK, workspace_id uuid FK, generated_at timestamptz, horizon_end date, training_cutoff date, model_name text, model_version text, data_mix_json jsonb, metrics_json jsonb, assumptions_json jsonb, forecast_total_myr numeric(14,4), observed_to_date_myr numeric(14,4), predicted_remaining_myr numeric(14,4), budget_myr numeric(14,4), lower_myr numeric(14,4), upper_myr numeric(14,4), status text)`.
9. `forecast_points(id uuid PK, forecast_run_id uuid FK, day date, application_id uuid FK, request_category text, predicted_requests numeric, predicted_input_tokens numeric, predicted_output_tokens numeric, predicted_cost_myr numeric, lower_cost_myr numeric, upper_cost_myr numeric)`.
10. `anomaly_events(id uuid PK, workspace_id uuid FK, application_id uuid FK, detected_at timestamptz, day date, metric text, observed_value numeric, expected_value numeric, severity text, anomaly_score numeric, reason_code text, explanation text, is_synthetic bool, acknowledged_at timestamptz NULL)`.
11. `scenario_runs(id uuid PK, workspace_id uuid FK, forecast_run_id uuid FK, created_at timestamptz, scenario_type text, assumptions_json jsonb, baseline_cost_myr numeric, projected_cost_myr numeric, gross_savings_myr numeric, overhead_myr numeric, net_savings_myr numeric, quality_status text, uncertainty_json jsonb)`.
12. `recommendations(id uuid PK, workspace_id uuid FK, forecast_run_id uuid FK, scenario_run_id uuid FK, action_type text, rationale text, status text CHECK IN ('proposed','approved','rejected','enabled','disabled'), created_at timestamptz, decided_at timestamptz NULL, decided_by uuid NULL)`.
13. `policies(id uuid PK, workspace_id uuid FK, application_id uuid FK, policy_type text, enabled bool DEFAULT false, similarity_threshold numeric DEFAULT 0.95, faq_only bool DEFAULT true, ttl_hours int DEFAULT 24, approved_by uuid NULL, approved_at timestamptz NULL, updated_at timestamptz)`.
14. `policy_audit(id uuid PK, workspace_id uuid FK, application_id uuid FK, actor_user_id uuid, action text, old_value jsonb, new_value jsonb, created_at timestamptz)`.
15. `evaluation_runs(id uuid PK, workspace_id uuid FK NULL, evaluated_at timestamptz, dataset_version text, seed int, method text, metrics_json jsonb, artifact_path text, data_origin text)`.
16. `pricing_catalog(id uuid PK, provider text, model text, effective_from date, input_usd_per_million numeric, output_usd_per_million numeric, cache_read_usd_per_million numeric NULL, cache_write_usd_per_million numeric NULL, source_url text, verified_at timestamptz, version text)`.

Required integrity rules: nonnegative tokens/cost; unique request idempotency; no cross-tenant FK references (enforce in service logic and test); soft-delete or retention policy for usage; cascade cache entries on FAQ deletion; policy audit immutable. Supabase RLS should deny direct client access to sensitive operational tables; frontend calls backend for workspace-scoped data. Backend uses server-only DB credentials.

## 6. API CONTRACT

All paths prefix `/api/v1`. OpenAPI generated at `/docs` in development, disabled or protected in production. Consistent JSON errors: `{error:{code,message,request_id}}`. Pagination `{items,next_cursor}`. All owner endpoints require verified Supabase Auth JWT + membership; demo chat uses a restricted demo token or authenticated user. Rate limit by application, IP, and workspace. Validate inputs with Pydantic.

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | readiness and dependency summary (no secrets) |
| POST | `/chat` | bakery chat; `{application_id,message,locale,conversation_id?}` -> `{reply,cache_status,usage:{input_tokens,output_tokens},estimated_cost_myr,request_id}` |
| GET | `/overview?workspace_id=` | current cost, budget, cache hits, forecast, alerts |
| GET | `/usage/daily?workspace_id=&from=&to=` | aggregated usage and origin labels |
| GET | `/usage/requests?workspace_id=&cursor=` | safe request metadata only |
| POST | `/forecasts/run` | owner-only trigger forecast; idempotent per run key |
| GET | `/forecasts/latest?workspace_id=` | latest forecast with bounds and provenance |
| GET | `/forecasts/{id}/drivers` | category-level cost contributions |
| GET | `/anomalies?workspace_id=` | anomalies with severity, score, explanation |
| POST | `/anomalies/{id}/acknowledge` | acknowledge alert |
| POST | `/scenarios/compare` | evaluate no action, semantic caching, optionally prompt caching and routing |
| GET | `/recommendations?workspace_id=` | proposed/approved actions |
| POST | `/recommendations/{id}/approve` | owner approval with optimistic version check |
| POST | `/recommendations/{id}/reject` | owner rejection |
| POST | `/policies/{id}/disable` | owner emergency disable |
| GET | `/policies?workspace_id=` | active policies |
| GET | `/evaluation/latest` | honest model and cache quality metrics |
| POST | `/demo/reset` | local/dev only, never enabled publicly |
| POST | `/demo/seed` | local/dev only, idempotent synthetic seed |
| GET | `/settings/workspace` | budget, currency, data source summary |
| PATCH | `/settings/workspace` | update budget and preferences |

Example `POST /scenarios/compare` request:
```json
{"workspace_id":"<uuid>","forecast_run_id":"<uuid>","actions":["none","semantic_cache"],"assumptions":{"eligible_spend_share":0.35,"expected_hit_rate":0.70,"cache_overhead_myr":7.0}}
```
Return assumptions, method, uncertainty, quality status, scenario IDs, and net savings. **Do not allow browser clients to submit arbitrary cost forecasts as trusted evidence**; always load the persisted forecast and compute server-side.

## 7. ANTHROPIC CHATBOT BEHAVIOR

Use `anthropic` Python SDK with server-side model configuration. BakeryBot answers from a short, static FAQ knowledge base embedded into its system prompt; no claims about actual ordering or inventory. It must decline to collect payment details, and for custom orders direct users to the fictional bakery's staff. Chat input max 1,000 chars, server-side timeout 25s, max output tokens 250, safe error response. Store only hashes and metadata by default. In the demo, present the cache status and estimated API cost under each answer, but keep that UI clearly separated from the customer reply.

A cache hit MUST NOT call Anthropic. A miss calls Anthropic exactly once, records actual token usage from response metadata, calculates estimated cost, and returns the answer. Errors must not be cached. Request retry only on transient errors with bounded exponential backoff and idempotency where possible. Avoid double billing counts for retries: record each actual provider call or reconcile as needed. Provider price rates are configurable and versioned; never hardcode unverified current prices.

## 8. SAFE SEMANTIC CACHE (CRITICAL)

Pipeline:
1. Normalize whitespace and case for exact lookup; never strip meaningful numbers, dates, negations, or product names.
2. Reject requests containing likely PII, account-specific identifiers, order status, dynamic availability, current dates, discounts, prices not tied to approved FAQ, multiple questions, or negation/ambiguous changes. Use deterministic denylist/patterns; false negatives remain possible, so limit caching to approved FAQ intents.
3. Only consider a query cacheable if it maps to an approved static FAQ entry with matching workspace, application, locale, knowledge version, and valid TTL. Intent assignment is conservative: exact FAQ phrase/approved aliases first, then local embedding similarity to an approved FAQ; require best similarity >=0.95 and a margin >=0.03 over second-best different intent; if ambiguous bypass.
4. Use `sentence-transformers/all-MiniLM-L6-v2` locally (384 dimensions); cosine similarity on normalized vectors. Verify threshold empirically against positive/negative query pairs. This model is English-oriented; demo locale `en` only.
5. Answer from **approved FAQ answer**, not arbitrary historic generated output, on eligible cache hit. This is safer and deterministic. For uncached non-FAQ requests, call Anthropic.
6. Default TTL 24h, configurable; invalidate all related cache entries when FAQ or knowledge version changes. Do not cache personalized answers.
7. Log exact hit / semantic hit / bypass / miss separately. Log the similarity score without raw query text; never log full prompts in production by default.
8. Cache quality evaluation: labelled pairs `same_safe_answer` vs `different_answer`, measure precision of accepted hits (primary), recall/coverage, false-hit count, and latency. For launch, zero false hits in the provided adversarial test set; do not claim zero general error.

Adversarial tests MUST include: `What time do you open?` vs `When do you open?` (eligible); `Do you open on Sunday?` vs `Are you open Saturday?` (different answers); `Do you deliver?` vs `Do you deliver to my address?` (second not safely reusable); `How much is Chocolate Cake?` vs `How much is Vanilla Cake?`; `Is my order ready?`; `Can you refund order #1234?`; `Do you have stock today?`; `What are your hours tomorrow?`; multilingual requests; conflicting product names; negative phrasing. If embedding model cannot reliably distinguish any of these, bypass and/or require deterministic intent matching.

## 9. HYBRID DATASET GENERATOR

Implement `python scripts/generate_synthetic.py --seed 42 --days 180 --output data/generated/` generating `requests_synthetic.csv`, `daily_usage_synthetic.csv`, `anomaly_truth.csv`, `scenario_truth.csv`, and `dataset_manifest.json`. Use deterministic NumPy RNG; each synthetic row has `data_origin=synthetic`, `scenario_id`, and a manifest describing assumptions. Real gateway logs are stored separately with `data_origin=real`. No user-uploaded or private real data is required.

Generate 180 days × 3 applications × 4 request categories (`static_faq`, `order_enquiry`, `complex_support`, `other`). Include weekly seasonality (weekends different), upward trends, payday/campaign peaks, random noise, model mix, input/output token distributions, FAQ-repeat probabilities, token price variation by model, cacheable share, and rare abnormal events. Set realistic positive count distributions (Poisson or negative binomial), positive token distributions (lognormal clipped), and derive cost from actual token counts and versioned rates. Preserve temporal correlation; avoid independently random daily costs.

Inject **labelled anomalies** with explicit start/end dates and magnitudes:
- A1: 3x request traffic spike for 2 days (campaign/viral demand).
- A2: 4x average input tokens for 3 days (prompt bloat).
- A3: shift 60% of traffic to a more expensive model for 5 days (model mix change).
- A4: 35% repeated retries for 2 days (retry storm).
- A5: near-zero usage for 2 days (service outage; distinguish from high-cost anomalies).
- A6: slow gradual 2% per-day cost increase over 14 days (drift, not necessarily point anomaly).
- A7: benign one-day weekend promotion spike (hard negative, should avoid excessive false alerts).
- A8: missing values, duplicated rows, delayed records, out-of-order timestamps, and extreme but legitimate large requests.

For anomaly labels, record event ID, app, metric, date range, injected mechanism, and whether alert is expected. Ensure not every anomaly appears in training: hold out later events for evaluation. Include 20+ independent labelled events/segments through varied injections; separate abnormal **business spending** from technical faults. For causal demonstration, preserve the known injection mechanism so dashboard can explain synthetic anomalies accurately. Never present synthetic ground truth as discovered from real customers.

For intervention scenarios, simulate caching using **request-level eligibility** and repeated FAQ intent distribution. Generate potential outcomes under no-cache vs caching with the same demand stream, including cache infrastructure overhead and missed hits. Do not assume all semantically similar questions have identical answers. Record true counterfactual savings in the synthetic simulator for evaluation of what-if estimates.

## 10. FORECASTING DESIGN AND EVALUATION

**Forecast target:** daily API cost per `(workspace, application, category)` for next 7 days; aggregate forecasts through month-end. Also predict daily requests and token volumes or use decomposed cost model. Forecast should include known current month actuals plus remaining forecast, not forecast the whole month from scratch.

**Features:** date/day-of-week, lagged daily requests/cost/tokens at t-1/t-7/t-14, 7/14/28-day rolling means and standard deviations calculated using data strictly prior to prediction day, category, model mix, cache eligibility fraction, and observed trend. Do not use future target values or injected anomaly labels as features. Do not train on target leakage columns or future outcomes.

**Baselines:** naive previous-day, seasonal naive t-7, and rolling 7-day mean. **Candidate model:** HistGradientBoostingRegressor with encoded categories (or separate models per segment if easier). Train on first 70% chronologically, validate on next 15%, test on final 15%. Use rolling-origin backtesting with at least 3 forecast origins on held-out period, retraining or carefully freezing per origin. Compare MAE, RMSE, WAPE (with explicit zero handling), sMAPE, month-end overrun classification precision/recall, and interval coverage. Choose candidate only if it improves a relevant primary metric over seasonal naive; otherwise ship the honest baseline as production forecast and show candidate results.

**Prediction intervals:** use residual-based conformal-style bounds from validation residuals; state assumptions and note coverage may degrade under distribution shift. Clip lower costs at zero. Display central estimate plus lower/upper interval and data provenance.

**Budget risk:** deterministic threshold `forecast_month_end > budget`; also flag `lower_bound > budget` as high-confidence risk, `upper_bound > budget` as possible risk. Avoid fake probability unless calibrated probabilistic forecasting exists.

**Cost driver attribution:** sum segment-level predicted remaining costs and compare with segment-level recent baseline. Report share of predicted spend and incremental cost vs reference; do not assert causation solely from feature importance. Reconcile all segments to overall forecast within rounding tolerance. For a business owner, use templates like `Static FAQs account for RM X (Y%) of projected spending, RM Z above their recent run rate.`

**Model artifacts:** persist via joblib only if generated internally; record training cutoff, version, features, metrics, seed, and data composition. No untrusted deserialization. Training jobs run manually and on schedule; prediction should work with prebuilt demo artifacts immediately.

## 11. ANOMALY DETECTION AND FALSE-POSITIVE EVALUATION

Use two complementary methods: (a) robust seasonal baseline using day-of-week median and MAD, threshold on positive residual (cost/requests/tokens), with minimum absolute impact threshold; (b) IsolationForest on standardized historical daily feature vectors (request count, input/output tokens per request, cost/request, model share, retry rate), trained only on training window. Alert if robust detector signals or IsolationForest score is extreme AND estimated financial impact exceeds configured floor, except outages get operational alert. Prevent alert flooding by merging contiguous days of same event.

Compute on held-out labelled synthetic data: precision, recall, F1, false-positive rate, false alerts per 30 days, detection delay, confusion matrix, and performance on benign promotion spikes. Provide a threshold sweep and choose threshold on validation set, not test. Never report injected anomaly labels as model features. Explain alerts with observed vs expected values and contributing metrics; label explanations as correlation/diagnostic, not proven causal mechanism for real data.

Dashboard: date, severity, type, observed vs expected, estimated incremental cost, explanation, confidence/limitations, acknowledge. Allow no-data/insufficient-history status. Do not use fabricated confidence percentages.

## 12. WHAT-IF SIMULATOR (NO LLM CALLS)

Use **the persisted forecast** as input, not a second independent projection. For each forecasted segment/day calculate baseline requests, token volumes, and cost. Apply an intervention's eligibility, estimated effectiveness, and overhead to those exact forecasted units. Sum across days/segments and compare to unchanged baseline.

Semantic caching gross savings per segment = `predicted_eligible_requests × expected_safe_hit_rate × predicted_mean_avoidable_provider_cost_per_request`. If cached responses still incur some provider costs, subtract those explicitly. Net savings = gross savings - additional embedding/DB/hosting overhead - any other attributable costs. Use historical safe cache hits or a representative replay to estimate hit rate; if none, use a clearly labelled assumption and sensitivity range, not a verified prediction. When caching is enabled, use measured cache hit rates with smoothing and minimum sample count. Never assume caching saves the entire forecasted FAQ category automatically.

Provider-native prompt caching (P1): only estimate for actual repeated prefixes eligible under Anthropic caching rules and pricing; subtract cache-write premiums, account for expiry. Do not equate it with semantic response caching. Model routing (P1): use model-specific price and measured quality qualification; never auto-enable. Combined scenarios calculate eligible request overlap at request/segment level; do not simply add independent savings.

Scenario response includes `baseline_forecast`, `scenario_forecast`, `gross_savings`, `overhead`, `net_savings`, `assumptions`, `lower/upper_savings_sensitivity`, `quality_gate`, and `evidence_type` (measured/synthetic/assumed). Rank only interventions passing quality gates and positive net savings. If all fail or evidence insufficient, recommend `No safe intervention yet; collect more data`. This is a valid and desirable decision.

**Recommendation rationale example:** `Projected month-end spending is RM280 against RM200 budget. Static FAQ traffic contributes RM110. With a measured 70% safe hit rate and RM7 estimated overhead, enabling approved FAQ caching could reduce forecast to approximately RM210. This does not fully eliminate budget overrun; monitor after activation.` Never claim it reaches budget if it does not.

## 13. APPROVAL, MEASUREMENT, AND SAFETY

All recommendations are initially `proposed`. Only `owner` may approve, reject, enable, or disable; use explicit confirmation modal displaying assumptions, savings estimate, quality risks, and reversible policy. Record actor, timestamp, old/new settings in immutable audit log. Viewer cannot modify. On approval, transactionally update policy and recommendation. Provide one-click emergency disable. No automatic provider/model change.

After enablement, measure: total real provider calls, eligible requests, exact/semantic hits, safe-hit precision on test cases, estimated avoided provider cost, extra embedding/database costs, net observed cost. Estimate counterfactual with a controlled holdout if enough volume: deterministic 10% of eligible requests bypass cache (hash-based assignment) **only with owner opt-in**; otherwise report observational estimated savings and label them as such. For demo, use reproducible request replay with identical request sequence and mocked provider cost accounting, plus a small set of genuine Anthropic calls if key supplied. Do not spend real money just to demonstrate a large saving.

Privacy/security: avoid storing raw customer messages; do not log API keys; sanitize error traces; redact identifiers; rate-limit and protect demo endpoint; input length caps; prevent cross-workspace cache reuse; short retention policy (default 30 days request metadata, 180 days aggregates); CORS allowlist; no wildcard origins in production; security headers; auth checks on every workspace resource; secret scanning; safe migration/rollback.

## 14. FRONTEND DESIGN SYSTEM AND SCREENS

**Visual brief:** Notion-inspired, clean light theme. Use shadcn/ui + Tailwind CSS + Lucide React. Reference Notion `DESIGN.md` from getdesign.md if available. Use `frontend-design` skill if installed. Colors: canvas `#FAFAF9`, white cards `#FFFFFF`, primary text `#202124`, muted `#71717A`, border `#E7E7E5`, blue accent `#2563EB`, soft blue tint `#EFF6FF`, warning amber `#D97706`, danger `#DC2626`, success `#15803D`. System sans or Inter, 14px base, spacious 24px card padding, 8–12px radii, minimal shadows, 1px borders. Accessible AA contrast, keyboard support, responsive sidebar/drawer, 360px mobile and 1440px desktop. Charts Recharts, no distracting gradients or neon. Distinguish observed/synthetic/forecast data with visible labels. Skeletons, empty/error states, tooltips explaining assumptions, and units on every chart.

Navigation: **Overview**, **Predictions**, **Anomalies**, **Decision Lab**, **Usage Explorer**, **Evaluation**, **Demo Chatbot**, **Settings**. Sidebar top logo + workspace switcher (one workspace P0), bottom data provenance and environment badge. Topbar date range, workspace budget, refresh, user menu.

**Overview:** headline `Predict early. Spend smarter.`; cards Current Spend, Month-End Forecast, Budget Risk, Potential Net Savings; cumulative actual-vs-forecast chart with uncertainty band and budget line; top predicted cost drivers; latest anomaly; recommended action card; active policy and cache hit rate; provenance badge `Demo synthetic history + live traffic`.

**Predictions:** daily forecast chart; observed-to-date vs remaining forecast; forecast interval; segment cost breakdown; projected budget-crossing date (only if daily curve crosses); baseline comparison table; model training cutoff; `How forecast works` explanation drawer; insufficient-data state.

**Anomalies:** severity filters, chronological anomaly table, sparkline of observed/expected, estimated impact, reason codes, acknowledge, false-positive discussion, examples of benign spikes. Never show a fake 99% confidence label.

**Decision Lab:** baseline forecast on left; selectable semantic cache scenario on right; sliders for eligible share, safe hit rate, and overhead with defaults from measured data and a visible `assumed` indicator; resulting cost and savings update immediately; sensitivity low/base/high; quality checklist; recommendation reasoning; `Approve & Enable` modal (owner only) and `Disable` control; audit history.

**Usage Explorer:** filter by app/model/category/date/data origin; daily tokens, costs, requests, cache hits; sortable request metadata (no raw prompts); CSV export of sanitized aggregates.

**Evaluation:** forecast metrics vs baselines, backtest plot, anomaly confusion matrix/precision/recall/false alerts per 30 days, semantic-cache adversarial accuracy, synthetic-vs-real data proportions, limitations, model card link. Include no-result placeholders until evaluation genuinely runs.

**Demo Chatbot:** branded Sweet Crumbs bakery card, message bubbles, sample clickable prompts (hours, delivery, cakes, Sunday, order status), cache status pill `Anthropic call / safe cache hit / bypass`, request tokens and estimated cost; demo-only banner. Provide at least one cache hit and one safe bypass scenario.

**Settings:** monthly budget, default currency, app integration info, active cache policy, similarity threshold visible but owner edits restricted to safe range 0.95–0.99, TTL, FAQ version, API key rotation, delete demo data, dataset origin legend.

**Required components:** Card, Badge, Button, Dialog, Tabs, Table, Tooltip, Select, Slider, Switch, Skeleton, Toast/Sonner, ChartContainer, Form, Alert, DropdownMenu, Sheet. No dead buttons; every control must have working action or be visibly disabled with explanation.

## 15. TEST PLAN AND EVALUATION EVIDENCE

### Unit tests
- Pricing formula uses actual provider input/output tokens and versioned price; cache hits charge zero **provider** tokens but account for local overhead.
- Forecast temporal feature generation does not leak future values; nonnegative forecasts; segment totals reconcile to overall total; month-to-date actuals are included exactly once.
- Simulator baseline is identical to forecast run; no double-counting; negative savings -> no recommendation; quality failure -> no recommendation; uncertainty displayed.
- Cache exact hit, semantic safe hit, near-match different answer bypass, PII bypass, expired entry bypass, cross-tenant bypass, FAQ version invalidation, provider failure no-cache.
- Approval only owner; viewer denied; idempotent approval; disable restores provider calls; policy audit created.
- Dataset deterministic for seed 42; anomaly labels and injection dates reproducible; synthetic provenance retained.

### Integration tests
- Mock Anthropic adapter counts calls: first eligible FAQ request miss (if no approved answer policy) or safe FAQ answer; repeat safe request must not increase Anthropic calls; non-FAQ calls Anthropic; backend records correct usage and cost.
- Local Postgres migrations run on clean database; all CRUD endpoints return expected contracts; authenticated workspace A cannot read/modify B.
- Seed 180 days; train model; run forecast; detect injected anomalies; generate scenario; approve; activate; replay queries; measure difference.

### End-to-end tests (Playwright)
- Login -> Overview -> Predictions -> Decision Lab -> Approve -> Demo Chatbot -> Evaluation.
- Verify forecast values match backend, scenario update changes estimates, confirmation modal works, policy state persists, error states display, mobile nav works.

### Quality gates
- Backend `ruff`, `pytest`; frontend `eslint`, `tsc --noEmit`, `next build`, Playwright smoke; CI GitHub Actions. Tests must not call real Anthropic or require cloud accounts. Real-provider smoke test optional behind explicit environment flag and capped request count.
- Report measured forecasting metrics, anomaly precision/recall/false positives, cache safe-hit precision and savings simulation error. If models underperform baseline, report honestly and use baseline. No invented accuracy targets or claimed savings.

## 16. CLOUD DEPLOYMENT

**Local:** `docker compose up -d db`; `cd apps/api && uv sync && alembic upgrade head && uv run uvicorn app.main:app --reload`; `cd apps/web && npm install && npm run dev`; seed synthetic data; train/evaluate; test mock provider mode. Add `make dev`, `make seed`, `make train`, `make test`, `make demo` wrappers and document exact commands.

**Cloud:** Supabase project for PostgreSQL + Auth + pgvector; Render Python web service for FastAPI with health check, environment variables and migrations; Render scheduled job or authenticated scheduler endpoint for daily aggregation/forecast; Vercel for Next.js frontend. Configure Vercel env `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`; Render env `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_JWKS_URL` (or verified JWT settings), `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `APP_ENV`, `ALLOWED_ORIGINS`, `MYR_PER_USD_DEMO`, `DEMO_MODE=false`, `PRICING_CATALOG_VERSION`, `SCHEDULER_SECRET`. Never put service-role or Anthropic keys in NEXT_PUBLIC variables. Use TLS-only production endpoints. Confirm Render filesystem persistence assumptions; use DB for durable state and small checked-in FAQ fixtures. Verify Render plan constraints and scheduled-job availability at deployment time; if unavailable, provide manual secure job endpoint and document limitation.

**Secret handling:** `.env.example` contains placeholders only. `.gitignore` excludes `.env*` except `.env.example`, model artifacts if sensitive, local data. For deployment, human must provide Anthropic API key, Supabase URL/keys, Render/Vercel access; coding agent must not claim deployment succeeded without actual URL and HTTP smoke check.

## 17. IMPLEMENTATION PHASES / AGENT WORK ORDER

**Phase 0 — Scaffold (0–1.5h):** monorepo, lint/test/build, env example, Docker, README, theme tokens, route skeleton. Verify clean local boot.

**Phase 1 — Database & Gateway (1.5–5h):** migrations, auth, workspace, FAQ fixture, Anthropic adapter, `/chat`, cost ledger, mocked provider tests. Verify one real request only if key provided.

**Phase 2 — Data & ML (5–9h):** synthetic generator, daily aggregation, baseline and candidate forecast, backtests, anomaly injections/detector, model cards, artifacts. Verify metrics saved and never fabricated.

**Phase 3 — Decision & Cache (9–13h):** safe FAQ cache, what-if, cost driver breakdown, recommendation, approval, policy audit, measurement. Verify approved policy changes actual call count in tests.

**Phase 4 — Dashboard (13–18h):** implement all P0 screens with functional API wiring, responsive visual polish, empty/loading/error states, sample prompt flows.

**Phase 5 — E2E, Deploy, Demo (18–24h):** run CI, Playwright, security checks, cloud deployment with available credentials, prepare seeded demo and pitch; if cloud blocked, provide working local fallback and truthful blocker report.

These are target allocations, not a promise that everything will fit exactly. Prioritize end-to-end correctness over P1 features.

### Work protocol
At the end of each phase, update `IMPLEMENTATION_STATUS.md` with completed files, commands run, test counts, unresolved blockers, and next phase. Continue automatically. Do not wait for confirmation except credential/account authorization. If something fails, fix and rerun; do not paper over failures with screenshots or static mock results.

## 18. 3-MINUTE JUDGE DEMO (SCRIPT)

**0:00–0:25 Problem:** `Small businesses can build AI chatbots quickly but cannot anticipate API overspending. Reactive dashboards show the bill after it happens. TokenGuard predicts risk and recommends a preventive decision.` Show CakeBot and budget RM200.

**0:25–0:55 Live traffic:** Ask bakery chatbot `What time do you open?`; then `When are you open?` (safe eligible repeat), show cache hit and avoided provider call. Ask `Is my order ready?`, show cache bypass. Display real vs synthetic labels.

**0:55–1:30 Predict:** Show forecast RM280 vs RM200 budget (demo-seeded example), uncertainty band, segment breakdown, and anomalous spike. Explain backtesting against seasonal naive and false-positive evaluation. Explicitly label example values synthetic if so.

**1:30–2:10 Decide:** Open Decision Lab; demonstrate baseline RM280 and semantic caching estimate RM210 (illustrative), assumptions, net savings after overhead, quality gate. Show why static FAQs were targeted **because of the forecast**, not because an unrelated report found them. Show that budget may still be exceeded after action.

**2:10–2:35 Act:** Owner approves caching; policy audit updates; replay identical safe FAQ prompts and show provider call reduction. Show no LLM used for optimisation recommendation.

**2:35–3:00 Prove & close:** Show evaluation page: forecast vs baseline, anomaly false positives, cache safe-hit tests, and observed/simulated savings labelled accurately. Close: `TokenGuard turns AI cost forecasts into measurable, quality-aware preventive actions.`

**Demo resilience:** seed a deterministic scenario for exact visuals, cache local test responses, keep a recorded walkthrough as backup but do not present recording as live. Never fabricate a live API request. If Anthropic key missing, label mock mode clearly.

## 19. RUBRIC EVIDENCE MATRIX

| Criterion (20 each) | Required deliverable/evidence |
|---|---|
| Problem Clarity & Value Proposition | One-sentence SME pain, budget risk, measured/illustrative impact, target customer, constraints |
| Predictive Rigor & Data Robustness | 180-day deterministic dataset, injected labelled anomalies, temporal split, baseline comparison, MAE/RMSE/WAPE, false positives, noisy-data robustness, provenance |
| Decision Support & Actionability | Forecast-linked cost driver, what-if scenario based on same forecast, net savings + quality gates, approval workflow, measurement |
| Explainability & Trust | Segment contributions, assumptions, interval, source badges, anomaly reasons, honest uncertainty, privacy controls, reversible action |
| Live Execution, Prototype & Pitch | Working chatbot, gateway, dashboard, forecast, decision activation, tests, cloud URL if credentials supplied, 3-minute script |

The rubric values reflect the user-provided rubric context. If a newer official rubric is supplied, update this matrix without changing the project's core objective.

## 20. ACCEPTANCE CRITERIA (ALL P0 MUST PASS)

1. `make dev` launches usable local UI/API/database with documented setup.
2. `make seed` creates deterministic 180-day synthetic dataset and manifest with explicit synthetic labels.
3. BakeryBot answers at least five approved FAQ intents and forwards ineligible queries to Anthropic when configured.
4. At least one safe repeated query avoids a second Anthropic call; adversarial queries bypass.
5. Gateway records actual token metadata and estimated cost without raw message persistence.
6. Dashboard shows actual-vs-synthetic provenance and budget/cost/forecast with no fake values.
7. Forecast is derived from historical data with leakage-safe backtesting and at least two baseline comparisons.
8. Predicted segment costs reconcile to overall month-end forecast.
9. Anomaly evaluation includes held-out labels, false positives and detection delay.
10. Decision simulation transforms the saved forecast and subtracts estimated overhead.
11. Recommendation explains its assumptions, risks and why it was selected; may recommend no action.
12. Only owner can approve; approved policy changes cache behavior; disable reverses it; audit persisted.
13. Evaluation reports are generated by code from measured runs and accessible in UI.
14. Unit, integration and E2E tests pass; CI configuration exists.
15. Cloud deployment instructions are complete; actual deployment only marked done after smoke test.
16. Demo completes in three minutes with deterministic scenario and honest data labels.

## 21. EXPECTED FINAL AGENT RESPONSE

When implementation finishes, return: (a) exact working local commands, (b) public frontend/backend URLs if genuinely deployed, (c) account/secret setup actions requiring human intervention, (d) completed vs deferred features, (e) automated test results and evidence, (f) actual ML metrics and dataset provenance, (g) screenshots or demo recording path if generated, (h) limitations, (i) precise next steps. Do not claim 100% complete unless all 16 acceptance criteria pass.

## 22. INITIAL IMPLEMENTATION COMMAND FOR THE AGENT

> Read `MASTER_BUILD_PACK.md` completely and implement TokenGuard AI as a working monorepo. Start Phase 0 immediately and proceed through Phase 5 without asking me routine decisions. Follow all P0 acceptance criteria, prioritizing the prediction → cost-driver → simulation → approval → measurement loop. Use the specified Notion-inspired design, and invoke `frontend-design` skill if available. Use mock Anthropic mode until I supply an API key. Do not fabricate metrics, savings, real traffic, or deployment status. At every phase, update `IMPLEMENTATION_STATUS.md`; run tests and fix failures. Ask me only when real credentials or account authorization are essential.
