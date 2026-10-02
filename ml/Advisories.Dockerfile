FROM python:3.12-slim AS dependencies
WORKDIR /app
ENV PIP_DEFAULT_TIMEOUT=60
COPY ml/requirements-fields.lock ./
RUN --mount=type=cache,target=/root/.cache/pip apt-get update && apt-get install -y --no-install-recommends build-essential && pip wheel -r requirements-fields.lock -w /wheels
FROM python:3.12-slim
WORKDIR /app
ENV PIP_DEFAULT_TIMEOUT=60
COPY --from=dependencies /wheels /wheels
COPY ml/requirements-fields.lock ./
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libgomp1 && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir --no-index --find-links=/wheels -r requirements-fields.lock && rm -rf /wheels
COPY ml/ ./
COPY packages/source-catalog/fields.json /fields.json
COPY packages/source-catalog/advisories.json /advisories.json
RUN pip install --no-cache-dir --no-deps .
USER 10001
ENV PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
CMD ["python", "-m", "nautiq_ml.advisories.pipeline", "refresh"]
