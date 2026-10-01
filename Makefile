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
	OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m pytest ml/tests
	cd apps/web && npm test
lint:
	cd services/api && test -z "$$(gofmt -l cmd internal)" && go vet ./...
	.venv/bin/ruff check ml scripts
	cd apps/web && npm run lint
	docker compose config --quiet
build:
	cd services/api && go build ./...
	cd apps/web && npm run build
logs:
	docker compose logs --tail=100 -f
