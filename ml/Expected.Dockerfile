FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY ml/requirements-uncertainty.lock ./
RUN pip install --no-cache-dir -r requirements-uncertainty.lock
COPY ml/ ./
COPY packages/source-catalog/expected-state.json /expected-state.json
COPY packages/source-catalog/uncertainty.json /uncertainty.json
RUN pip install --no-cache-dir --no-deps . && mkdir -p /tracking && chown 10001:10001 /tracking
USER 10001
ENV PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MLFLOW_HTTP_REQUEST_TIMEOUT=15 MLFLOW_HTTP_REQUEST_MAX_RETRIES=1
CMD ["python", "-m", "nautiq_ml.server"]
