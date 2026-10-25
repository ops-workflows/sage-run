FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends tar && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
COPY README.md LICENSE ./
COPY sage_run/ ./sage_run/
COPY shared/ ./shared/
COPY schemas/ ./schemas/
RUN pip install --no-cache-dir ".[server,connectors]"

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
