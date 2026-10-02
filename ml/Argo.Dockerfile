FROM python:3.12-slim
WORKDIR /app
COPY ml/requirements-argo.lock ./
RUN pip install --no-cache-dir -r requirements-argo.lock
COPY ml/ ./
COPY packages/source-catalog/argo-training.json /argo-training.json
COPY packages/source-catalog/climatology.json /climatology.json
RUN pip install --no-cache-dir --no-deps .
USER 10001
ENV PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
CMD ["python", "-m", "nautiq_ml.argo.worker"]
