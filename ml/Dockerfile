FROM python:3.12-slim
WORKDIR /app
COPY ml/ ./
RUN pip install --no-cache-dir -r requirements-runtime.lock && pip install --no-cache-dir --no-deps .
USER 10001
CMD ["python", "-m", "nautiq_ml.server"]
