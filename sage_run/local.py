"""Run a workflow repository as a local Kubernetes instance (Rancher Desktop k3s).

The working tree is mounted into the instance, so workflow edits need no image
build: ``sage-run up`` again rebundles and reloads. ``--source`` builds platform
images from a sage-run checkout for platform development.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import httpx
import yaml

from sage_run.profiles import CONNECTOR_PROFILES, MCP_PROFILES

DEFAULT_CONTEXT = "rancher-desktop"
DEFAULT_BOOTSTRAP_ENV = Path("~/.local/state/sage-run/local/compose.env")
RELEASE_NAME = "sage-run"
BOOTSTRAP_SECRET = "sage-run-bootstrap"  # noqa: S105 - Secret resource name, not a credential
CORE_MCPS = ("message", "memory", "knowledge", "platform")
# component -> (Dockerfile, build context), relative to the sage-run checkout
IMAGE_BUILDS = {
    "gateway": ("gateway/Dockerfile", "."),
    "session-manager": ("session-manager/Dockerfile", "."),
    "knowledge-indexer": ("knowledge-indexer/Dockerfile", "."),
    "mcp": ("mcps/Dockerfile", "."),
    "agent-runtime": ("runtime/Dockerfile", "."),
    "control-plane-ui": ("control-plane-ui/Dockerfile", "control-plane-ui"),
    "servicenow-connector": ("connectors/servicenow-connector/Dockerfile", "."),
    "gcp-pubsub-connector": ("connectors/gcp-pubsub-connector/Dockerfile", "."),
}
CONNECTOR_COMPONENTS = {"servicenow": "servicenow-connector", "gcp-pubsub": "gcp-pubsub-connector"}
PLATFORM_COMPONENTS = ("gateway", "session-manager", "knowledge-indexer", "mcp", "connector", "control-plane-ui")
_DNS_LABEL = re.compile(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?")


@dataclass
class Instance:
    workflow_repo: Path
    name: str
    context: str = DEFAULT_CONTEXT
    sandbox_profile: str = "local"
    images: dict = field(default_factory=dict)

    @property
    def host(self) -> str:
        return f"{self.name}.localhost"


def instance_name(workflow_repo: Path, explicit: str | None = None) -> str:
    name = explicit or f"{workflow_repo.name.lower()}-dev"
    name = re.sub(r"[^a-z0-9-]+", "-", name).strip("-")
    if not _DNS_LABEL.fullmatch(name):
        raise ValueError(f"Instance name {name!r} is not a valid Kubernetes namespace")
    return name


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_platform_config(workflow_repo: Path) -> dict:
    config = yaml.safe_load((workflow_repo / "platform-config.yaml").read_text(encoding="utf-8")) or {}
    if not isinstance(config, dict):
        raise ValueError("platform-config.yaml must contain a mapping")
    return config


def enabled_components(config: dict) -> tuple[set[str], set[str]]:
    """Return (platform MCP ids, connector ids) the instance needs."""
    mcps = set(CORE_MCPS)
    for server_id in (config.get("mcps") or {}).get("enabled") or []:
        if server_id in MCP_PROFILES:
            mcps.add(server_id)
    connectors: set[str] = set()
    section = config.get("connectors") or {}
    instances = section.get("instances") or {}
    for instance_id in section.get("enabled") or []:
        connector_type = (instances.get(instance_id) or {}).get("type")
        if connector_type in CONNECTOR_PROFILES:
            connectors.add(connector_type)
    return mcps, connectors


def render_values(instance: Instance, config: dict, deployment_env: dict[str, str]) -> dict:
    """Helm values for a local instance. Contains no secrets."""
    mcps, connectors = enabled_components(config)
    env = {key: value for key, value in deployment_env.items() if key.startswith("KNOWLEDGE_")}
    env["CONTROL_PLANE_UI_URL"] = f"http://{instance.host}"
    env["GATEWAY_PUBLIC_BASE_URL"] = f"http://{instance.host}"
    hindsight_env = {key: value for key, value in deployment_env.items() if key.startswith("HINDSIGHT_API_")}
    return {
        "images": instance.images,
        "workflowRepo": {"hostPath": str(instance.workflow_repo), "source": "local"},
        "env": env,
        "runtime": {"sandboxProfile": instance.sandbox_profile},
        "ingress": {"enabled": True, "host": instance.host},
        "infrastructure": {"hindsight": {"env": hindsight_env}},
        "mcps": {name: {"enabled": name in mcps} for name in MCP_PROFILES.keys() | set(CORE_MCPS)},
        "connectors": {name: {"enabled": name in connectors} for name in CONNECTOR_COMPONENTS},
    }


def bootstrap_secret_data(existing: dict[str, str], bootstrap_env: dict[str, str]) -> dict[str, str]:
    """Merge operator keys with existing (or newly generated) local infrastructure passwords."""
    data = dict(existing)
    for key in ("AGE_IDENTITY", "LLM_API_KEY"):
        if bootstrap_env.get(key):
            data[key] = bootstrap_env[key]
        if not data.get(key):
            raise ValueError(f"{key} is required: set it in the bootstrap env file")
    for key in ("PG_PASSWORD", "OBJECT_STORE_SECRET_KEY"):
        data.setdefault(key, secrets.token_urlsafe(24))
    return data


def dev_image_tag(source: Path) -> str:
    sha = _run(["git", "-C", str(source), "rev-parse", "--short=12", "HEAD"], capture=True).strip()
    dirty = _run(["git", "-C", str(source), "status", "--porcelain"], capture=True).strip()
    if dirty:
        return f"dev-{sha}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    return f"dev-{sha}"


def _run(command: list[str], *, capture: bool = False, stdin: str | None = None) -> str:
    result = subprocess.run(  # noqa: S603 - fixed tool argument vectors, no shell
        command,
        check=True,
        text=True,
        input=stdin,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout or ""


def _require_tools(*tools: str) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        raise ValueError(f"Missing required tools: {', '.join(missing)}")


def build_images(source: Path, tag: str, components: list[str]) -> None:
    for component in components:
        dockerfile, context = IMAGE_BUILDS[component]
        print(f"Building sage-run-{component}:{tag}", flush=True)
        _run(
            [
                "docker",
                "build",
                "-t",
                f"sage-run-{component}:{tag}",
                "-f",
                str(source / dockerfile),
                str(source / context),
            ]
        )


def _kubectl(instance: Instance, *args: str, capture: bool = False, stdin: str | None = None) -> str:
    return _run(["kubectl", "--context", instance.context, *args], capture=capture, stdin=stdin)


def _existing_secret(instance: Instance) -> dict[str, str]:
    try:
        raw = _kubectl(
            instance,
            "-n",
            instance.name,
            "get",
            "secret",
            BOOTSTRAP_SECRET,
            "-o",
            "json",
            "--ignore-not-found",
            capture=True,
        )
    except subprocess.CalledProcessError:
        return {}
    if not raw.strip():
        return {}
    data = json.loads(raw).get("data") or {}
    return {key: base64.b64decode(value).decode("utf-8") for key, value in data.items()}


def apply_bootstrap_secret(instance: Instance, bootstrap_env: dict[str, str]) -> None:
    data = bootstrap_secret_data(_existing_secret(instance), bootstrap_env)
    manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": BOOTSTRAP_SECRET, "namespace": instance.name},
        "type": "Opaque",
        "stringData": data,
    }
    _kubectl(instance, "apply", "-f", "-", stdin=json.dumps(manifest), capture=True)


def _chart_path(source: Path | None) -> Path:
    candidates = [source / "deploy/k8s/sage-run"] if source else []
    candidates.append(Path(__file__).resolve().parents[1] / "deploy/k8s/sage-run")
    for candidate in candidates:
        if (candidate / "Chart.yaml").is_file():
            return candidate
    raise ValueError("Helm chart not found; pass --source with a sage-run checkout")


def sync_workflows(instance: Instance, timeout_sec: float = 120) -> None:
    # *.localhost may not resolve for every client; Traefik routes on the Host header.
    url = "http://127.0.0.1/api/platform/workflow-repo/sync"
    deadline = time.monotonic() + timeout_sec
    while True:
        try:
            response = httpx.post(url, headers={"Host": instance.host}, timeout=60)
            if response.status_code < 500:
                response.raise_for_status()
                print("Workflows synced", flush=True)
                return
        except httpx.HTTPError as exc:
            if time.monotonic() > deadline:
                raise ValueError(f"Workflow sync failed: {exc}") from exc
        if time.monotonic() > deadline:
            raise ValueError(f"Workflow sync failed with HTTP {response.status_code}")
        time.sleep(3)


def up(
    workflow_repo: Path,
    *,
    source: Path | None = None,
    name: str | None = None,
    context: str = DEFAULT_CONTEXT,
    image_tag: str | None = None,
    bootstrap_env_file: Path | None = None,
    sandbox_profile: str = "local",
    build: bool = True,
) -> int:
    _require_tools("kubectl", "helm", *(["docker", "git"] if source and build else []))
    workflow_repo = workflow_repo.expanduser().resolve()
    config = load_platform_config(workflow_repo)
    instance = Instance(workflow_repo, instance_name(workflow_repo, name), context, sandbox_profile)
    _, connectors = enabled_components(config)

    if source:
        source = source.expanduser().resolve()
        tag = image_tag or dev_image_tag(source)
        components = [c for c in IMAGE_BUILDS if not c.endswith("-connector")]
        components += [CONNECTOR_COMPONENTS[c] for c in sorted(connectors)]
        if build:
            build_images(source, tag, components)
        instance.images = {"registry": "", "tag": tag, "pullPolicy": "Never"}
    elif image_tag:
        instance.images = {"registry": "", "tag": image_tag, "pullPolicy": "Never"}
    else:
        instance.images = {"tag": version("sage-run")}

    env_path = (bootstrap_env_file or DEFAULT_BOOTSTRAP_ENV).expanduser()
    bootstrap_env = read_env_file(env_path) if env_path.is_file() else {}
    deployment_env_path = workflow_repo / "deploy/compose.env"
    deployment_env = read_env_file(deployment_env_path) if deployment_env_path.is_file() else {}

    print(f"Instance {instance.name} (context {context}) from {workflow_repo}", flush=True)
    _kubectl(
        instance,
        "apply",
        "-f",
        "-",
        stdin=json.dumps({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": instance.name}}),
        capture=True,
    )
    apply_bootstrap_secret(instance, bootstrap_env)

    values = render_values(instance, config, deployment_env)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(values, handle)
        values_file = handle.name
    try:
        _run(
            [
                "helm",
                "upgrade",
                "--install",
                RELEASE_NAME,
                str(_chart_path(source)),
                "--kube-context",
                context,
                "--namespace",
                instance.name,
                "-f",
                values_file,
                "--wait",
                "--timeout",
                "15m",
            ]
        )
    finally:
        Path(values_file).unlink(missing_ok=True)
    # Platform services read configuration at startup; restart them so working-tree
    # config changes apply. Infrastructure (Postgres, MinIO, Hindsight) keeps running.
    selector = f"app.kubernetes.io/component in ({','.join(PLATFORM_COMPONENTS)})"
    _kubectl(instance, "-n", instance.name, "rollout", "restart", "deployment", "-l", selector, capture=True)
    _kubectl(instance, "-n", instance.name, "rollout", "status", "deployment", "-l", selector, "--timeout=10m")
    sync_workflows(instance)
    print(f"Ready: http://{instance.host}", flush=True)
    return 0


def down(workflow_repo: Path, *, name: str | None = None, context: str = DEFAULT_CONTEXT, purge: bool = False) -> int:
    _require_tools("kubectl", "helm")
    workflow_repo = workflow_repo.expanduser().resolve()
    instance = Instance(workflow_repo, instance_name(workflow_repo, name), context)
    _run(
        [
            "helm",
            "uninstall",
            RELEASE_NAME,
            "--kube-context",
            context,
            "--namespace",
            instance.name,
            "--ignore-not-found",
        ]
    )
    if purge:
        _kubectl(instance, "delete", "namespace", instance.name, "--ignore-not-found")
    else:
        print(f"Kept volumes and secrets in namespace {instance.name}; use --purge to delete them.")
    return 0


def status(workflow_repo: Path, *, name: str | None = None, context: str = DEFAULT_CONTEXT) -> int:
    _require_tools("kubectl")
    workflow_repo = workflow_repo.expanduser().resolve()
    instance = Instance(workflow_repo, instance_name(workflow_repo, name), context)
    print(f"Instance {instance.name}: http://{instance.host}")
    _kubectl(instance, "-n", instance.name, "get", "pods,jobs", "-o", "wide")
    return 0


def main_error(exc: Exception) -> int:
    print(f"error: {exc}", file=sys.stderr)
    return 1
