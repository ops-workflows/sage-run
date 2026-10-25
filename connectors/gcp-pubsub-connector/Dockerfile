FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY README.md LICENSE ./
COPY sage_run/ ./sage_run/
COPY shared/ ./shared/
COPY schemas/ ./schemas/
RUN pip install --no-cache-dir ".[server,connectors]"

COPY connectors/gcp-pubsub-connector/ ./connectors/gcp-pubsub-connector/

ENV PYTHONPATH=/app

CMD ["python", "/app/connectors/gcp-pubsub-connector/main.py"]