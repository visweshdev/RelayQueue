FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY pyproject.toml requirements.txt /app/
COPY src /app/src
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir --no-deps . \
    && useradd --uid 10001 --create-home relayqueue
COPY alembic.ini /app/
COPY migrations /app/migrations
COPY examples /app/examples
USER relayqueue
CMD ["sh", "-ec", "export PROMETHEUS_MULTIPROC_DIR=$(mktemp -d /tmp/relayqueue-metrics.XXXXXX); exec uvicorn relayqueue.api.main:app --host 0.0.0.0 --port 8000 --workers \"${API_WORKERS:-2}\""]
