.PHONY: setup up down lint proto build logs migrate phase0-setup phase0 phase0-replay phase0-gate
setup:
	bash scripts/setup.sh
proto:
	bash scripts/generate-proto.sh
up:
	docker compose up -d postgres
	$(MAKE) migrate
	docker compose up --build -d
migrate:
	.venv/bin/python scripts/migrate.py
phase0-setup:
	@if [ ! -x .venv/bin/python ]; then uv venv --python 3.12 .venv; fi
	uv pip install --python .venv/bin/python -r ml/requirements-phase0.lock -e ./ml
phase0: phase0-setup
	OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m nautiq_ml.phase0.cli
phase0-replay:
	OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m nautiq_ml.phase0.cli --offline
phase0-gate:
	OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python -m nautiq_ml.phase0.cli --offline --require-ready
down:
	docker compose down
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


.PHONY: argo-setup ingest reconcile
argo-setup:
	uv pip install --python .venv/bin/python -r ml/requirements-argo.lock -e ./ml
ingest:
	docker compose run --rm ingestion --once
reconcile:
	docker compose run --rm ingestion --once --reconcile
	docker compose exec -T normalizer python -m nautiq_ml.argo.worker repair



.PHONY: argo-replay science-maintain training-snapshot verify-snapshot
argo-replay:
	docker compose exec -T normalizer python -m nautiq_ml.argo.tools replay --limit 1000
science-maintain:
	docker compose exec -T normalizer python -m nautiq_ml.argo.tools maintain
training-snapshot:
	@test -n "$(AS_OF)" || (echo 'Supply explicit UTC AS_OF, e.g. make training-snapshot AS_OF=2026-10-02T00:00:00Z'; exit 2)
	docker compose exec -T normalizer python -m nautiq_ml.argo.tools snapshot --as-of '$(AS_OF)' --max-profiles 500
verify-snapshot:
	@test -n "$(SNAPSHOT_ID)" || (echo 'Supply SNAPSHOT_ID'; exit 2)
	docker compose exec -T normalizer python -m nautiq_ml.argo.tools verify-snapshot '$(SNAPSHOT_ID)'

.PHONY: climatology-build climatology-verify climatology-select climatology-maintain
climatology-build:
	@test -n "$(SNAPSHOT_ID)" || (echo 'Supply SNAPSHOT_ID'; exit 2)
	docker compose exec -T normalizer python -m nautiq_ml.climatology.pipeline build '$(SNAPSHOT_ID)'
climatology-verify:
	@test -n "$(REFERENCE_ID)" || (echo 'Supply REFERENCE_ID'; exit 2)
	docker compose exec -T normalizer python -m nautiq_ml.climatology.pipeline verify '$(REFERENCE_ID)'
climatology-select:
	@test -n "$(REFERENCE_ID)" || (echo 'Supply REFERENCE_ID'; exit 2)
	docker compose exec -T normalizer python -m nautiq_ml.climatology.pipeline select '$(REFERENCE_ID)'
climatology-maintain:
	docker compose exec -T normalizer python -m nautiq_ml.climatology.pipeline maintain --limit 500

.PHONY: expected-setup expected-build expected-verify expected-select expected-log expected-maintain
expected-setup:
	uv pip install --python .venv/bin/python -r ml/requirements-expected.lock -e ./ml
expected-build:
	@test -n "$(REFERENCE_ID)" || (echo 'Supply REFERENCE_ID'; exit 2)
	docker compose exec -T -e SOURCE_GIT_COMMIT="$$(git rev-parse HEAD)" ml-inference python -m nautiq_ml.expected_state.pipeline build '$(REFERENCE_ID)'
expected-verify:
	@test -n "$(MODEL_ID)" || (echo 'Supply MODEL_ID'; exit 2)
	docker compose exec -T ml-inference python -m nautiq_ml.expected_state.pipeline verify '$(MODEL_ID)'
expected-select:
	@test -n "$(MODEL_ID)" || (echo 'Supply MODEL_ID'; exit 2)
	docker compose exec -T ml-inference python -m nautiq_ml.expected_state.pipeline select '$(MODEL_ID)'
expected-log:
	@test -n "$(MODEL_ID)" || (echo 'Supply MODEL_ID'; exit 2)
	docker compose exec -T ml-inference python -m nautiq_ml.expected_state.pipeline log '$(MODEL_ID)'
expected-maintain:
	docker compose exec -T ml-inference python -m nautiq_ml.expected_state.pipeline maintain --limit 500

.PHONY: uncertainty-setup uncertainty-build uncertainty-verify uncertainty-select uncertainty-log uncertainty-maintain uncertainty-monitor uncertainty-benchmark
uncertainty-setup:
	uv pip install --python .venv/bin/python -r ml/requirements-uncertainty.lock -e ./ml
uncertainty-build:
	@test -n "$(MODEL_ID)" || (echo 'Supply selected MODEL_ID'; exit 2)
	docker compose exec -T -e SOURCE_GIT_COMMIT="$$(git rev-parse HEAD)" ml-inference python -m nautiq_ml.uncertainty.pipeline build '$(MODEL_ID)'
uncertainty-verify:
	@test -n "$(INTERVAL_ID)" || (echo 'Supply INTERVAL_ID'; exit 2)
	docker compose exec -T ml-inference python -m nautiq_ml.uncertainty.pipeline verify '$(INTERVAL_ID)'
uncertainty-select:
	@test -n "$(INTERVAL_ID)" || (echo 'Supply INTERVAL_ID'; exit 2)
	docker compose exec -T ml-inference python -m nautiq_ml.uncertainty.pipeline select '$(INTERVAL_ID)'
uncertainty-log:
	@test -n "$(INTERVAL_ID)" || (echo 'Supply INTERVAL_ID'; exit 2)
	docker compose exec -T ml-inference python -m nautiq_ml.uncertainty.pipeline log '$(INTERVAL_ID)'
uncertainty-benchmark:
	@test -n "$(INTERVAL_ID)" || (echo 'Supply INTERVAL_ID'; exit 2)
	docker compose exec -T ml-inference python -m nautiq_ml.uncertainty.pipeline benchmark '$(INTERVAL_ID)'
uncertainty-maintain:
	docker compose exec -T ml-inference python -m nautiq_ml.uncertainty.pipeline maintain --limit 500
uncertainty-monitor:
	docker compose exec -T normalizer python -c 'import json; from nautiq_ml.uncertainty.monitoring import monitor; print(json.dumps(monitor(), sort_keys=True, indent=2))'

.PHONY: anomaly-build anomaly-verify anomaly-select anomaly-log anomaly-maintain anomaly-benchmark
anomaly-build:
	@test -n '$(INTERVAL_ID)' || (echo 'Set INTERVAL_ID to an exact uncertainty release'; exit 1)
	docker compose exec -T -e SOURCE_GIT_COMMIT="$$(git rev-parse HEAD)" ml-inference python -m nautiq_ml.anomaly.pipeline build '$(INTERVAL_ID)'
anomaly-verify:
	@test -n '$(ANOMALY_ID)' || (echo 'Set ANOMALY_ID'; exit 1)
	docker compose exec -T ml-inference python -m nautiq_ml.anomaly.pipeline verify '$(ANOMALY_ID)'
anomaly-select:
	@test -n '$(ANOMALY_ID)' || (echo 'Set ANOMALY_ID'; exit 1)
	docker compose exec -T ml-inference python -m nautiq_ml.anomaly.pipeline select '$(ANOMALY_ID)'
anomaly-log:
	@test -n '$(ANOMALY_ID)' || (echo 'Set ANOMALY_ID'; exit 1)
	docker compose exec -T ml-inference python -m nautiq_ml.anomaly.pipeline log '$(ANOMALY_ID)'
anomaly-benchmark:
	@test -n '$(ANOMALY_ID)' || (echo 'Set ANOMALY_ID'; exit 1)
	docker compose exec -T ml-inference python -m nautiq_ml.anomaly.pipeline benchmark '$(ANOMALY_ID)'
anomaly-maintain:
	docker compose exec -T ml-inference python -m nautiq_ml.anomaly.pipeline maintain --limit 500

.PHONY: fields-setup field-ingest field-refresh field-verify field-maintain field-replay
fields-setup:
	uv pip install --python .venv/bin/python -r ml/requirements-fields.lock -e ./ml
field-ingest:
	@test -n '$(PRODUCT)' || (echo 'Set PRODUCT to a catalog product ID'; exit 1)
	docker compose exec -T -e SOURCE_GIT_COMMIT="$$(git rev-parse HEAD)" field-service python -m nautiq_ml.fields.pipeline ingest '$(PRODUCT)' $(if $(CYCLE),--cycle '$(CYCLE)') $(if $(DAY),--day '$(DAY)') $(if $(HOURS),--hours '$(HOURS)')
field-refresh:
	docker compose exec -T -e SOURCE_GIT_COMMIT="$$(git rev-parse HEAD)" field-service python -m nautiq_ml.fields.pipeline refresh
field-verify:
	@test -n '$(FIELD_ID)' || (echo 'Set FIELD_ID to an immutable field release'; exit 1)
	docker compose exec -T field-service python -m nautiq_ml.fields.pipeline verify '$(FIELD_ID)'
field-maintain:
	docker compose exec -T field-service python -m nautiq_ml.fields.pipeline maintain
field-replay:
	@test -n '$(FIELD_ID)' || (echo 'Set FIELD_ID to an immutable field release'; exit 1)
	docker compose exec -T -e SOURCE_GIT_COMMIT="$$(git rev-parse HEAD)" field-service python -m nautiq_ml.fields.pipeline replay '$(FIELD_ID)'

.PHONY: event-history event-baseline event-thermal event-profiles event-verify event-replay event-maintain event-dataset-verify event-dataset-replay
event-history:
	@test -n '$(START)' -a -n '$(END)' || (echo 'Set explicit START and END UTC dates'; exit 1)
	docker compose run --rm -T -e SOURCE_GIT_COMMIT="$$(git rev-parse HEAD)" event-worker python -m nautiq_ml.events.pipeline history --start '$(START)' --end '$(END)' $(if $(BBOX),--bbox $(BBOX)) $(if $(REFRESH),--refresh)
event-baseline:
	@test -n '$(DATASET_ID)' || (echo 'Set DATASET_ID to retained 1982-2011 daily history'; exit 1)
	docker compose run --rm -T event-worker python -m nautiq_ml.events.pipeline baseline '$(DATASET_ID)'
event-thermal:
	@test -n '$(BASELINE_ID)' -a -n '$(HISTORY_ID)' || (echo 'Set exact BASELINE_ID and HISTORY_ID'; exit 1)
	docker compose run --rm -T -e SOURCE_GIT_COMMIT="$$(git rev-parse HEAD)" event-worker python -m nautiq_ml.events.pipeline thermal '$(BASELINE_ID)' '$(HISTORY_ID)'
event-profiles:
	@test -n '$(ANOMALY_ID)' -a -n '$(START)' -a -n '$(END)' || (echo 'Set exact selected ANOMALY_ID and UTC START/END'; exit 1)
	docker compose run --rm -T -e SOURCE_GIT_COMMIT="$$(git rev-parse HEAD)" event-worker python -m nautiq_ml.events.pipeline profiles '$(ANOMALY_ID)' --start '$(START)' --end '$(END)' $(if $(BBOX),--bbox $(BBOX))
event-verify:
	@test -n '$(RUN_ID)' || (echo 'Set RUN_ID'; exit 1)
	docker compose run --rm -T event-worker python -m nautiq_ml.events.pipeline verify '$(RUN_ID)'
event-replay:
	@test -n '$(RUN_ID)' || (echo 'Set RUN_ID'; exit 1)
	docker compose run --rm -T -e SOURCE_GIT_COMMIT="$$(git rev-parse HEAD)" event-worker python -m nautiq_ml.events.pipeline replay '$(RUN_ID)'
event-maintain:
	docker compose run --rm -T event-worker python -m nautiq_ml.events.pipeline maintain
event-dataset-verify:
	@test -n '$(DATASET_ID)' || (echo 'Set DATASET_ID'; exit 1)
	docker compose run --rm -T event-worker python -m nautiq_ml.events.pipeline verify-dataset '$(DATASET_ID)'
event-dataset-replay:
	@test -n '$(DATASET_ID)' || (echo 'Set DATASET_ID'; exit 1)
	docker compose run --rm -T event-worker python -m nautiq_ml.events.pipeline replay-dataset '$(DATASET_ID)'


.PHONY: operations-setup
operations-setup:
	uv pip install --python .venv/bin/python -r infrastructure/production/requirements.lock

.PHONY: model-monitor
# Read-only: summarizes input drift, outcomes, profile ranks and calibration into an immutable report.
# A flag starts an investigation; nothing is retrained, recalibrated, selected or promoted.
model-monitor:
	docker compose exec -T ml-inference python -m nautiq_ml.monitoring.pipeline $(if $(WINDOW_DAYS),--window-days $(WINDOW_DAYS),)

.PHONY: static-features-experiment
# Offline and unreleased: acquires ETOPO 2022 bathymetry, refits the expected-mean pipeline with and without
# bathymetry/distance-to-coast on identical rows and prints the measured comparison. Creates no release.
static-features-experiment:
	@test -n "$(REFERENCE_ID)" || (echo 'Supply REFERENCE_ID'; exit 2)
	docker compose exec -T ml-inference python -m nautiq_ml.expected_state.static_features --reference-id '$(REFERENCE_ID)'
