FROM postgres:17-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends python3-venv && rm -rf /var/lib/apt/lists/* && python3 -m venv /opt/ops
COPY infrastructure/production/requirements.lock /requirements.lock
RUN /opt/ops/bin/pip install --no-cache-dir -r /requirements.lock
COPY ml/nautiq_ml/ /app/nautiq_ml/
COPY infrastructure/production/ /production/
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["/opt/ops/bin/python", "-m", "nautiq_ml.operations.backup"]
