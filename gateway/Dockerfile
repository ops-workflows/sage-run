FROM python:3.11-slim

WORKDIR /app

# Git is required to clone/fetch remote workflow repositories during UI Sync.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY pyproject.toml .
COPY README.md LICENSE ./
COPY sage_run/ ./sage_run/
COPY shared/ ./shared/
COPY schemas/ ./schemas/
RUN pip install --no-cache-dir ".[server,connectors,kubernetes]"

# Copy shared library and gateway
COPY CLAUDE.md ./CLAUDE.md
COPY skills/ ./skills/
COPY hooks/ ./hooks/
COPY mcps/ ./mcps/
COPY gateway/ ./gateway/
COPY session-manager/ ./session_manager/
COPY connectors/ ./connectors/
COPY examples/workflow-repo/platform-config.yaml ./platform-config.yaml
RUN mkdir -p /app/workflows

EXPOSE 8080

# The gateway embeds an in-memory APScheduler, so it must run as a single
# process until scheduling is moved into its own dedicated service/job store.
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
