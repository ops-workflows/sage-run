FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
	&& apt-get install --no-install-recommends -y git \
	&& rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.24 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# Locked dependencies first: this layer changes only with pyproject.toml/uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --extra server --extra connectors -o /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt
COPY README.md LICENSE ./
COPY sage_run/ ./sage_run/
COPY shared/ ./shared/
COPY schemas/ ./schemas/
RUN uv pip install --system --no-cache --no-deps .

COPY connectors/servicenow-connector/ ./connectors/servicenow-connector/

ENV PYTHONPATH=/app

CMD ["python", "/app/connectors/servicenow-connector/main.py"]
