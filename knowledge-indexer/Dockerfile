FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY README.md LICENSE ./
COPY sage_run/ ./sage_run/
COPY shared/ ./shared/
COPY schemas/ ./schemas/
RUN pip install --no-cache-dir ".[server,knowledge-indexer]" \
    && python -c "import bs4; import pgvector.sqlalchemy"

COPY knowledge-indexer/ ./knowledge_indexer/

RUN mkdir -p /var/lib/sage-run/knowledge-indexer

CMD ["python", "-m", "knowledge_indexer.main"]
