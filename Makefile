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

.PHONY: phase3-verify phase3-reliability phase3-smoke argo-replay science-maintain training-snapshot verify-snapshot
phase3-verify:
	.venv/bin/python scripts/verify_phase3.py
phase3-reliability:
	.venv/bin/python scripts/verify_phase3_reliability.py
phase3-smoke:
	.venv/bin/python scripts/verify_phase3_smoke.py
argo-replay:
	docker compose exec -T normalizer python -m nautiuq_ml.argo.tools replay --limit 1000
science-maintain:
	docker compose exec -T normalizer python -m nautiuq_ml.argo.tools maintain
training-snapshot:
	@test -n "$(AS_OF)" || (echo 'Supply explicit UTC AS_OF, e.g. make training-snapshot AS_OF=2026-10-02T00:00:00Z'; exit 2)
	docker compose exec -T normalizer python -m nautiuq_ml.argo.tools snapshot --as-of '$(AS_OF)' --max-profiles 500
verify-snapshot:
	@test -n "$(SNAPSHOT_ID)" || (echo 'Supply SNAPSHOT_ID'; exit 2)
	docker compose exec -T normalizer python -m nautiuq_ml.argo.tools verify-snapshot '$(SNAPSHOT_ID)'

.PHONY: phase4-verify phase4-reliability phase4-smoke climatology-build climatology-verify climatology-select climatology-maintain
phase4-verify:
	.venv/bin/python scripts/verify_phase4.py
phase4-reliability:
	.venv/bin/python scripts/verify_phase4_reliability.py
phase4-smoke:
	.venv/bin/python scripts/verify_phase4_smoke.py
climatology-build:
	@test -n "$(SNAPSHOT_ID)" || (echo 'Supply SNAPSHOT_ID'; exit 2)
	docker compose exec -T normalizer python -m nautiuq_ml.climatology.pipeline build '$(SNAPSHOT_ID)'
climatology-verify:
	@test -n "$(REFERENCE_ID)" || (echo 'Supply REFERENCE_ID'; exit 2)
	docker compose exec -T normalizer python -m nautiuq_ml.climatology.pipeline verify '$(REFERENCE_ID)'
climatology-select:
	@test -n "$(REFERENCE_ID)" || (echo 'Supply REFERENCE_ID'; exit 2)
	docker compose exec -T normalizer python -m nautiuq_ml.climatology.pipeline select '$(REFERENCE_ID)'
climatology-maintain:
	docker compose exec -T normalizer python -m nautiuq_ml.climatology.pipeline maintain --limit 500

.PHONY: expected-setup phase5-verify phase5-reliability phase5-smoke expected-build expected-verify expected-select expected-log expected-maintain
expected-setup:
	uv pip install --python .venv/bin/python -r ml/requirements-expected.lock -e ./ml
phase5-verify:
	OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/verify_phase5.py
phase5-reliability:
	.venv/bin/python scripts/verify_phase5_reliability.py
phase5-smoke:
	.venv/bin/python scripts/verify_phase5_smoke.py
expected-build:
	@test -n "$(REFERENCE_ID)" || (echo 'Supply REFERENCE_ID'; exit 2)
	docker compose exec -T -e SOURCE_GIT_COMMIT="$$(git rev-parse HEAD)" ml-inference python -m nautiuq_ml.expected_state.pipeline build '$(REFERENCE_ID)'
expected-verify:
	@test -n "$(MODEL_ID)" || (echo 'Supply MODEL_ID'; exit 2)
	docker compose exec -T ml-inference python -m nautiuq_ml.expected_state.pipeline verify '$(MODEL_ID)'
expected-select:
	@test -n "$(MODEL_ID)" || (echo 'Supply MODEL_ID'; exit 2)
	docker compose exec -T ml-inference python -m nautiuq_ml.expected_state.pipeline select '$(MODEL_ID)'
expected-log:
	@test -n "$(MODEL_ID)" || (echo 'Supply MODEL_ID'; exit 2)
	docker compose exec -T ml-inference python -m nautiuq_ml.expected_state.pipeline log '$(MODEL_ID)'
expected-maintain:
	docker compose exec -T ml-inference python -m nautiuq_ml.expected_state.pipeline maintain --limit 500
