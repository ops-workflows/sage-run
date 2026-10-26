FROM python:3.11-slim

WORKDIR /app

# Git is required to clone/fetch remote workflow repositories during UI Sync.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Helm and kubectl for the in-cluster deployer Job (same image), pinned and checksum-verified.
ARG TARGETARCH
ARG HELM_VERSION=v4.0.5
ARG KUBECTL_VERSION=v1.36.5
RUN set -eu; \
    case "${TARGETARCH:-amd64}" in \
      amd64) helm_sha=730e4e9fbff94168249ddd0b9b1b8c357b7f64815462dd88c6b39f09bf18b814; kubectl_sha=33bc88a24c3b09cf55bfd59e6ca977881b61fc3f25ab65bc80c65b430248648e ;; \
      arm64) helm_sha=206a7747702d13994a93629eaed4259bd9d0aec6e23ca52d640f47f7edfdc863; kubectl_sha=88fc1aca8fd0c1b44fe379f67c39bd6858bdfc50241dc55775f84d0f5b31da3a ;; \
      *) echo "unsupported architecture ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*; \
    curl -fsSL -o /tmp/helm.tgz "https://get.helm.sh/helm-${HELM_VERSION}-linux-${TARGETARCH:-amd64}.tar.gz"; \
    echo "${helm_sha}  /tmp/helm.tgz" | sha256sum -c -; \
    tar -xzf /tmp/helm.tgz -C /tmp "linux-${TARGETARCH:-amd64}/helm"; \
    install -m 0755 "/tmp/linux-${TARGETARCH:-amd64}/helm" /usr/local/bin/helm; \
    curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH:-amd64}/kubectl"; \
    echo "${kubectl_sha}  /usr/local/bin/kubectl" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/kubectl; \
    rm -rf /tmp/helm.tgz "/tmp/linux-${TARGETARCH:-amd64}"

# Install dependencies
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
