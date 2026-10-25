FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends tar && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY --from=ghcr.io/astral-sh/uv:0.11.24 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# Locked dependencies first: this layer changes only with pyproject.toml/uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --extra server --extra connectors --extra kubernetes -o /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt
COPY README.md LICENSE ./
COPY sage_run/ ./sage_run/
COPY shared/ ./shared/
COPY schemas/ ./schemas/
RUN uv pip install --system --no-cache --no-deps .

# Copy shared library and session manager
COPY CLAUDE.md ./CLAUDE.md
COPY skills/ ./skills/
COPY hooks/ ./hooks/
COPY mcps/ ./mcps/
COPY gateway/ ./gateway/
COPY session-manager/ ./session_manager/
COPY examples/workflow-repo/platform-config.yaml ./platform-config.yaml
RUN mkdir -p /app/workflows

# Create volumes directory
RUN mkdir -p /volumes

CMD ["python", "-m", "session_manager.main"]
