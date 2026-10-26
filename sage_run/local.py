"""Run a workflow repository as a local Kubernetes instance (Rancher Desktop k3s).

The working tree is mounted into the instance, so workflow edits need no image
build: ``sage-run up`` again rebundles and reloads. ``--source`` builds platform
images from a sage-run checkout for platform development.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from sage_run.deployment import checkout_lock
from sage_run.profiles import CONNECTOR_PROFILES, MCP_PROFILES
from shared.lib.crypto import decrypt_named_secrets
from shared.lib.platform_config import load_platform_config as load_merged_platform_config

DEFAULT_CONTEXT = "rancher-desktop"
# Development key shared by local instances; production keys live only on their hosts.
DEFAULT_DEV_IDENTITY = "~/.config/sage-run/dev.agekey"
IDENTITY_ENV = "SAGE_RUN_AGE_IDENTITY_FILE"
INFRASTRUCTURE_SECRETS = ("LLM_API_KEY", "PG_PASSWORD", "OBJECT_STORE_SECRET_KEY")
SANDBOX_PROFILES = ("local", "ci", "gvisor")
DEPLOYMENT_KEYS = {
    "public_url",
    "sandbox_profile",
    "env",
    "hindsight",
    "extra_hosts",
    "service_env",
    "ui",
    "infrastructure_images",
}
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
    environment: str = ""
    local: bool = True

    @property
    def host(self) -> str:
        return f"{self.name}.localhost"


def instance_name(workflow_repo: Path, explicit: str | None = None) -> str:
    name = explicit or f"{workflow_repo.name.lower()}-dev"
    name = re.sub(r"[^a-z0-9-]+", "-", name).strip("-")
    if not _DNS_LABEL.fullmatch(name):
        raise ValueError(f"Instance name {name!r} is not a valid Kubernetes namespace")
    return name


def load_platform_config(workflow_repo: Path, environment: str = "") -> dict:
    return load_merged_platform_config(workflow_repo / "platform-config.yaml", environment=environment)


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


def deployment_settings(config: dict) -> dict:
    """Validated ``deployment:`` section of the merged platform config."""
    section = config.get("deployment") or {}
    if not isinstance(section, dict):
        raise ValueError("deployment must be a mapping")
    unknown = set(section) - DEPLOYMENT_KEYS
    if unknown:
        raise ValueError(f"deployment has unknown keys: {', '.join(sorted(unknown))}")
    for key in ("env", "extra_hosts", "service_env", "hindsight", "ui", "infrastructure_images"):
        if section.get(key) is not None and not isinstance(section[key], dict):
            raise ValueError(f"deployment.{key} must be a mapping")
    hindsight_env = (section.get("hindsight") or {}).get("env")
    if hindsight_env is not None and not isinstance(hindsight_env, dict):
        raise ValueError("deployment.hindsight.env must be a mapping")
    if set(section.get("infrastructure_images") or {}) - {"postgres", "objectStore", "hindsight"}:
        raise ValueError("deployment.infrastructure_images accepts postgres, objectStore and hindsight")
    ui = section.get("ui") or {}
    if set(ui) - {"host_ip", "host_port"} or ("host_port" in ui and not isinstance(ui["host_port"], int)):
        raise ValueError("deployment.ui accepts host_ip and an integer host_port")
    profile = section.get("sandbox_profile")
    if profile is not None and profile not in SANDBOX_PROFILES:
        raise ValueError(f"deployment.sandbox_profile must be one of {', '.join(SANDBOX_PROFILES)}")
    return section


def _string_map(values: dict) -> dict[str, str]:
    return {str(key): str(value) for key, value in (values or {}).items() if value is not None}


_MCP_URL = re.compile(r"https?://mcp-([a-z0-9-]+):([0-9]+)/")


def workflow_mcps(workflow_repo: Path, config: dict) -> dict[str, dict]:
    """Enabled MCP servers defined in the workflow repo's ``mcps/*/mcp_*.py``.

    Ports come from the ``http://mcp-<id>:<port>/`` URLs workflows use in ``.mcp.json``.
    """
    enabled = {str(item) for item in (config.get("mcps") or {}).get("enabled") or []}
    ports: dict[str, set[int]] = {}
    for mcp_json in sorted(workflow_repo.glob("workflows/*/.mcp.json")):
        for server_id, port in _MCP_URL.findall(mcp_json.read_text(encoding="utf-8")):
            ports.setdefault(server_id, set()).add(int(port))
    servers: dict[str, dict] = {}
    for source in sorted(workflow_repo.glob("mcps/*/mcp_*.py")):
        server_id = source.stem.removeprefix("mcp_").replace("_", "-")
        if server_id not in enabled:
            continue
        if server_id in MCP_PROFILES or server_id in CORE_MCPS:
            raise ValueError(f"Workflow MCP {server_id} conflicts with a platform MCP")
        found = ports.get(server_id, set())
        if len(found) != 1:
            raise ValueError(f"Workflow MCP {server_id}: .mcp.json must reference http://mcp-{server_id}:<port>/ once")
        servers[server_id] = {
            "dir": source.parent.relative_to(workflow_repo).as_posix(),
            "module": source.stem,
            "port": found.pop(),
            "checksum": hashlib.sha256(
                b"".join(
                    path.relative_to(source.parent).as_posix().encode() + b"\0" + path.read_bytes()
                    for path in sorted(source.parent.rglob("*"))
                    if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
                )
            ).hexdigest(),
        }
    return servers


def _infrastructure_values(deployment: dict) -> dict:
    values: dict = {"hindsight": {"env": _string_map((deployment.get("hindsight") or {}).get("env"))}}
    for component, image in (deployment.get("infrastructure_images") or {}).items():
        values.setdefault(component, {})["image"] = str(image)
    return values


def release_manifest() -> dict:
    """Image references published with this package version (empty in source checkouts)."""
    manifest = Path(__file__).with_name("resources") / "release.json"
    return json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}


def release_images(version_tag: str) -> dict:
    """Helm image values for a published release, pinned by digest when the manifest matches."""
    manifest = release_manifest()
    if manifest.get("version") == version_tag and manifest.get("images"):
        return {"tag": version_tag, "overrides": manifest["images"]}
    return {"tag": version_tag}


def render_values(instance: Instance, config: dict) -> dict:
    """Helm values for an instance from its merged platform config. Contains no secrets."""
    mcps, connectors = enabled_components(config)
    deployment = deployment_settings(config)
    env = _string_map(deployment.get("env"))
    public_url = f"http://{instance.host}" if instance.local else str(deployment.get("public_url") or "")
    if public_url:
        env["CONTROL_PLANE_UI_URL"] = public_url
        env["GATEWAY_PUBLIC_BASE_URL"] = public_url
    sandbox_profile = instance.sandbox_profile or str(deployment.get("sandbox_profile") or "gvisor")
    return {
        "configChecksum": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "deployer": {"enabled": True},
        "images": instance.images,
        "workflowRepo": {"hostPath": str(instance.workflow_repo), "source": "local"},
        "env": env,
        "environment": instance.environment,
        "runtime": {"sandboxProfile": sandbox_profile},
        "ingress": {"enabled": True, "host": instance.host},
        "hostAliases": [
            {"ip": str(ip), "hostnames": [str(host)]} for host, ip in (deployment.get("extra_hosts") or {}).items()
        ],
        "serviceEnv": {
            str(name): _string_map(values) for name, values in (deployment.get("service_env") or {}).items()
        },
        "infrastructure": _infrastructure_values(deployment),
        "workflowMcps": workflow_mcps(instance.workflow_repo, config),
        "mcps": {name: {"enabled": name in mcps} for name in MCP_PROFILES.keys() | set(CORE_MCPS)},
        "connectors": {name: {"enabled": name in connectors} for name in CONNECTOR_COMPONENTS},
    }


def bootstrap_secret_data(existing: dict[str, str], identity: str, config: dict) -> dict[str, str]:
    """Instance Secret: the environment key plus infrastructure secrets decrypted from config.

    Database and object-store passwords not yet in config keep their existing (or
    newly generated) values, so running instances keep access to their data.
    """
    platform_secrets = config.get("secrets") or {}
    wanted = {
        name: platform_secrets[name] for name in INFRASTRUCTURE_SECRETS if isinstance(platform_secrets.get(name), dict)
    }
    decrypted = decrypt_named_secrets(wanted, identity=identity)
    if "LLM_API_KEY" not in decrypted:
        raise ValueError("platform config needs an encrypted LLM_API_KEY secret for this environment's key")
    data = dict(existing)
    data["AGE_IDENTITY"] = identity
    data.update(decrypted)
    for key in ("PG_PASSWORD", "OBJECT_STORE_SECRET_KEY"):
        if not data.get(key):
            data[key] = secrets.token_urlsafe(24)
    return data


def read_identity(path: Path) -> str:
    path = path.expanduser()
    if not path.is_file():
        raise ValueError(f"Age key {path} not found; pass --identity or create it with sage-run keygen")
    identity = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("AGE-"))
    if not identity:
        raise ValueError(f"{path} contains no AGE-SECRET-KEY")
    return identity


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


def apply_bootstrap_secret(instance: Instance, identity: str, config: dict) -> None:
    data = bootstrap_secret_data(_existing_secret(instance), identity, config)
    manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": BOOTSTRAP_SECRET, "namespace": instance.name},
        "type": "Opaque",
        "stringData": data,
    }
    _kubectl(instance, "apply", "-f", "-", stdin=json.dumps(manifest), capture=True)


def _chart_path(source: Path | None) -> Path:
    candidates = [source / "sage_run/chart"] if source else []
    candidates.append(Path(__file__).resolve().parent / "chart")
    for candidate in candidates:
        if (candidate / "Chart.yaml").is_file():
            return candidate
    raise ValueError("Helm chart not found; pass --source with a sage-run checkout")


def sync_workflows(instance: Instance) -> None:
    _kubectl(
        instance,
        "-n",
        instance.name,
        "exec",
        "deployment/gateway",
        "-c",
        "gateway",
        "--",
        "python",
        "-m",
        "sage_run",
        "activate",
        "--ref",
        "working-tree",
    )
    print("Workflows activated", flush=True)


def up(
    workflow_repo: Path,
    *,
    source: Path | None = None,
    name: str | None = None,
    context: str = DEFAULT_CONTEXT,
    image_tag: str | None = None,
    identity_file: Path | None = None,
    sandbox_profile: str = "local",
    build: bool = True,
    environment: str = "",
) -> int:
    _require_tools("kubectl", "helm", *(["docker", "git"] if source and build else []))
    workflow_repo = workflow_repo.expanduser().resolve()
    config = load_platform_config(workflow_repo, environment)
    instance = Instance(
        workflow_repo, instance_name(workflow_repo, name), context, sandbox_profile, environment=environment
    )
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
        instance.images = release_images(version("sage-run"))

    identity = read_identity(identity_file or Path(os.environ.get(IDENTITY_ENV, DEFAULT_DEV_IDENTITY)))
    with checkout_lock(workflow_repo):
        return _apply_local_instance(instance, config, identity, source)


def _apply_local_instance(instance: Instance, config: dict, identity: str, source: Path | None) -> int:
    values = render_values(instance, config)

    print(f"Instance {instance.name} (context {instance.context}) from {instance.workflow_repo}", flush=True)
    _kubectl(
        instance,
        "apply",
        "-f",
        "-",
        stdin=json.dumps({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": instance.name}}),
        capture=True,
    )
    apply_bootstrap_secret(instance, identity, config)

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
                instance.context,
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
    selector = f"app.kubernetes.io/component in ({','.join(PLATFORM_COMPONENTS)})"
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
