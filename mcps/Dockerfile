FROM python:3.11-slim

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.11.24 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY mcps/requirements.txt ./requirements.txt
RUN uv pip install --system --no-cache -r requirements.txt "pgvector>=0.4.0" \
	&& python -c "import pgvector.sqlalchemy"
COPY shared/ ./shared/
COPY mcps/ ./mcps/

ENV PYTHONPATH=/app

# The chart sets each MCP service's command.
CMD ["python", "-m", "uvicorn", "mcps.core.mcp_message:app", "--host", "0.0.0.0", "--port", "8100"]
