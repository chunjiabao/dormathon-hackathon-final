# TokenGuard developer commands. Requires: docker, uv, node/npm.
UV ?= uv
API = apps/api
WEB = apps/web

.PHONY: install db db-local migrate bootstrap api web dev seed train test lint smoke demo

install:
	cd $(API) && $(UV) sync
	cd $(WEB) && npm install

db:
	docker compose up -d --wait db

# Docker-free alternative: embedded Postgres 16 + pgvector. Prints a DATABASE_URL to put in .env.
db-local:
	cd $(API) && $(UV) run python scripts/local_db.py

migrate: db
	cd $(API) && $(UV) run alembic upgrade head

bootstrap:
	cd $(API) && $(UV) run python -m app.jobs.bootstrap

smoke:
	python scripts/smoke_test.py --base-url http://localhost:8000

api:
	cd $(API) && $(UV) run uvicorn app.main:app --reload --port 8000

web:
	cd $(WEB) && npm run dev

dev: install migrate bootstrap
	$(MAKE) -j2 api web

# Deterministic synthetic history (seed 42, 180 days ending yesterday) loaded into the demo workspace.
seed:
	cd $(API) && $(UV) run python ../../scripts/seed_demo.py

# Offline evaluation (stores thresholds), then aggregate real traffic, forecast and anomaly detection.
train:
	cd $(API) && $(UV) run python ../../scripts/run_evaluation.py --db
	cd $(API) && $(UV) run python -m app.jobs.predict

lint:
	cd $(API) && $(UV) run ruff check . && $(UV) run ruff format --check .
	cd $(WEB) && npm run lint && npm run typecheck

test: lint
	cd $(API) && $(UV) run pytest
	cd $(WEB) && npm run build

demo:
	cd $(API) && $(UV) run python ../../scripts/demo_replay.py --approve --disable-after
