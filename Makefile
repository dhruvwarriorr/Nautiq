.PHONY: setup up down test lint proto build smoke logs migrate test-migrations phase0-setup phase0 phase0-replay phase0-gate
setup:
	bash scripts/setup.sh
proto:
	bash scripts/generate-proto.sh
up:
	docker compose up -d postgres
	$(MAKE) migrate
	docker compose up --build -d
	$(MAKE) smoke
migrate:
	.venv/bin/python scripts/migrate.py
test-migrations:
	.venv/bin/python scripts/verify_migrations.py
phase0-setup:
	@if [ ! -x .venv/bin/python ]; then uv venv --python 3.12 .venv; fi
	uv pip install --python .venv/bin/python -r ml/requirements-phase0.lock -e ./ml
phase0: phase0-setup
	OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m nautiuq_ml.phase0.cli
phase0-replay:
	OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m nautiuq_ml.phase0.cli --offline
phase0-gate:
	OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m nautiuq_ml.phase0.cli --offline --require-ready
smoke:
	bash -c 'set -a; source .env; set +a; .venv/bin/python scripts/smoke.py'
down:
	docker compose down
test:
	cd services/api && go test -race ./...
	cd services/ingestion && go test -race ./...
	@if [ -d ml/tests ]; then OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest ml/tests; else echo "Existing Python tests are absent in this checkout; Phase 2 has separate verification commands."; fi
	@if [ -d apps/web/tests ]; then cd apps/web && npm test; else echo "Existing frontend tests are absent in this checkout; run phase2-smoke for the data slice."; fi
lint:
	cd services/api && test -z "$$(gofmt -l cmd internal)" && go vet ./...
	cd services/ingestion && test -z "$$(gofmt -l cmd)" && go vet ./...
	.venv/bin/ruff check ml scripts
	cd apps/web && npm run lint
	docker compose config --quiet
build:
	cd services/api && go build ./...
	cd services/ingestion && go build -o /dev/null ./...
	cd apps/web && npm run build
logs:
	docker compose logs --tail=100 -f

.PHONY: argo-setup ingest reconcile phase2-smoke phase2-verify
argo-setup:
	uv pip install --python .venv/bin/python -r ml/requirements-argo.lock -e ./ml
ingest:
	docker compose run --rm ingestion --once
reconcile:
	docker compose run --rm ingestion --once --reconcile
	docker compose exec -T normalizer python -m nautiuq_ml.argo.worker repair
phase2-smoke:
	.venv/bin/python scripts/verify_phase2.py
phase2-verify:
	.venv/bin/python scripts/verify_argo_parser.py
	.venv/bin/python scripts/verify_argo_ingestion.py

.PHONY: phase2-reliability
phase2-reliability:
	.venv/bin/python scripts/verify_phase2_reliability.py

.PHONY: phase2-broker
phase2-broker:
	.venv/bin/python scripts/verify_phase2_broker.py
