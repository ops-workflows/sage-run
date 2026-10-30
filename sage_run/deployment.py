"""Namespace-scoped deployment Jobs and the shared single-checkout lock."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import yaml

DEPLOY_JOB = "sage-run-deploy"
DEPLOY_LABEL = "sage-run/deployment"
REF_ANNOTATION = "sage-run/ref"
EXPECTED_COMMIT_ANNOTATION = "sage-run/expected-commit"
TARGET_VERSION_ANNOTATION = "sage-run/target-version"
MIN_SUPPORTED_UPGRADE_VERSION = "1.0.0"
RELOADABLE_CONFIG_KEYS = (
    "connections",
    "runtime_env",
    "model_profiles",
    "default_model_profile",
    "mcps",
    "connectors",
    "memory",
    "message_bus",
    "approvals",
    "schedules",
    "github",
    "confluence",
    "identity",
)
EXTRA_KINDS = (
    "Deployment",
    "StatefulSet",
    "Service",
    "Ingress",
    "NetworkPolicy",
    "ConfigMap",
    "Secret",
    "ServiceAccount",
    "Role",
    "RoleBinding",
    "PersistentVolumeClaim",
    "Job",
    "CronJob",
)
_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def configuration_checksums(config: dict, *, workloads: Iterable[str], workflow_mcps: Iterable[str]) -> dict[str, str]:
    """Hash startup-only inputs; task settings and reloadable policies stay out of pod templates."""
    from shared.lib.platform_secrets import _message_bus_secret_names, _structured_secret_names

    dynamic = {
        "connections",
        "runtime_env",
        "model_profiles",
        "default_model_profile",
        "mcps",
        "connectors",
        "deployment",
        "message_bus",
        "knowledge",
        "memory",
        "github",
        "confluence",
        "identity",
    }
    common = {key: value for key, value in config.items() if key not in dynamic}
    secrets = config.get("secrets") or {}
    common["secrets"] = {name: value for name, value in secrets.items() if name not in _structured_secret_names(config)}
    custom = {f"mcp-{name}" for name in workflow_mcps}
    checksums = {}
    for workload in workloads:
        inputs = {"startup": common}
        if workload in {"gateway", "session-manager", "mcp-message"}:
            inputs["message_bus"] = config.get("message_bus")
            inputs["message_secrets"] = {name: secrets.get(name) for name in _message_bus_secret_names(config)}
        if workload in {"gateway", "knowledge-indexer", "mcp-knowledge"}:
            knowledge = config.get("knowledge") or {}
            inputs["knowledge"] = knowledge
            name = (knowledge.get("embeddings") or {}).get("api_key_secret")
            inputs["embedding_secret"] = secrets.get(name)
        if workload in custom:
            inputs["policy"] = ((config.get("mcps") or {}).get("config") or {}).get(workload.removeprefix("mcp-"))
        checksums[workload] = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    return checksums


def _extra_rolls_or_updates(before: dict, after: dict) -> str | None:
    if before == after:
        return None
    old_spec, new_spec = before.get("spec") or {}, after.get("spec") or {}
    old_annotations = ((old_spec.get("template") or {}).get("metadata") or {}).get("annotations") or {}
    new_annotations = ((new_spec.get("template") or {}).get("metadata") or {}).get("annotations") or {}
    old_checksum = old_annotations.get("sage-run/source-checksum")
    new_checksum = new_annotations.get("sage-run/source-checksum")
    if after["kind"] in {"Deployment", "StatefulSet", "DaemonSet"}:
        if old_checksum and new_checksum:
            replicas_changed = "replicas" in new_spec and old_spec.get("replicas") != new_spec.get("replicas")
            if old_checksum == new_checksum and not replicas_changed:
                return None
            return "roll"
        if old_spec.get("template") != new_spec.get("template") or old_spec.get("replicas") != new_spec.get("replicas"):
            return "roll"
    return "update"


def deployment_plan(
    previous: str,
    desired: str,
    *,
    old_extras: dict[tuple[str, str], dict] | None = None,
    wanted_extras: dict[tuple[str, str], dict] | None = None,
) -> dict[str, list[str]]:
    """Report resource actions without exposing manifest values or secret contents."""

    def resources(manifest: str) -> dict[str, dict]:
        return {f"{item['kind']}/{item['metadata']['name']}": item for item in yaml.safe_load_all(manifest) if item}

    if (
        old_extras
        and wanted_extras is not None
        and any(kind == "PersistentVolumeClaim" for kind, _ in old_extras.keys() - wanted_extras.keys())
    ):
        raise ValueError("Removing an extra PVC requires an explicit storage migration")

    old, new = resources(previous), resources(desired)
    old_ext = {f"{kind}/{name}": doc for (kind, name), doc in (old_extras or {}).items()}
    new_ext = {f"{kind}/{name}": doc for (kind, name), doc in (wanted_extras or {}).items()}

    plan: dict[str, list[str]] = {"create": [], "roll": [], "update": [], "delete": []}
    plan["create"] = sorted((new.keys() - old.keys()) | (new_ext.keys() - old_ext.keys()))
    plan["delete"] = sorted((old.keys() - new.keys()) | (old_ext.keys() - new_ext.keys()))
    for key in sorted(old.keys() & new.keys()):
        before, after = old[key], new[key]
        if before == after:
            continue
        old_spec, new_spec = before.get("spec") or {}, after.get("spec") or {}
        rolls = after["kind"] in {"Deployment", "StatefulSet", "DaemonSet"} and (
            old_spec.get("template") != new_spec.get("template") or old_spec.get("replicas") != new_spec.get("replicas")
        )
        plan["roll" if rolls else "update"].append(key)
    for key in sorted(old_ext.keys() & new_ext.keys()):
        action = _extra_rolls_or_updates(old_ext[key], new_ext[key])
        if action:
            plan[action].append(key)
    plan["roll"].sort()
    plan["update"].sort()
    return plan


def workflow_bundle_hashes(tree: Path | None) -> dict[str, str]:
    """Deterministic content hash for each workflow directory in a repository tree."""
    if tree is None or not tree.is_dir():
        return {}
    hashes: dict[str, str] = {}
    for agent_yaml in sorted((tree / "workflows").glob("*/agent.yaml")):
        workflow_dir = agent_yaml.parent
        digest = hashlib.sha256()
        for path in sorted(workflow_dir.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            digest.update(path.relative_to(workflow_dir).as_posix().encode("utf-8") + b"\0" + path.read_bytes())
        hashes[workflow_dir.name] = digest.hexdigest()
    return hashes


def workflow_bundle_plan(previous_tree: Path | None, desired_tree: Path | None) -> dict[str, list[str]]:
    """Classify workflow bundles into create/update/delete."""
    if previous_tree is None and desired_tree is None:
        return {"create": [], "update": [], "delete": []}
    old = workflow_bundle_hashes(previous_tree)
    new = workflow_bundle_hashes(desired_tree)
    return {
        "create": sorted(new.keys() - old.keys()),
        "update": sorted(name for name in (old.keys() & new.keys()) if old[name] != new[name]),
        "delete": sorted(old.keys() - new.keys()),
    }


def config_reload_plan(previous_config: dict | None, desired_config: dict | None) -> list[str]:
    """Identify reloadable platform-config sections that changed between revisions."""
    if previous_config is None or desired_config is None:
        return []
    changed: list[str] = []
    for key in RELOADABLE_CONFIG_KEYS:
        if (previous_config.get(key) or None) != (desired_config.get(key) or None):
            changed.append(key)
    return sorted(changed)


def build_deployment_plan(
    previous_manifest: str,
    desired_manifest: str,
    *,
    ref: str = "working-tree",
    current_commit: str | None = None,
    target_commit: str | None = None,
    current_version: str = "",
    target_version: str = "",
    previous_values: dict | None = None,
    desired_values: dict | None = None,
    old_extras: dict[tuple[str, str], dict] | None = None,
    wanted_extras: dict[tuple[str, str], dict] | None = None,
    previous_tree: Path | None = None,
    current_tree: Path | None = None,
    desired_tree: Path | None = None,
    previous_config: dict | None = None,
    current_config: dict | None = None,
    desired_config: dict | None = None,
    migrations: list[str] | None = None,
    drift: list[str] | None = None,
) -> dict:
    """Build the shared reconciliation plan used by local, SSH, and in-cluster entry points."""
    resolved_prev_tree = previous_tree if previous_tree is not None else current_tree
    resolved_prev_config = previous_config if previous_config is not None else current_config
    chart_resources = deployment_plan(previous_manifest, desired_manifest)
    resources = deployment_plan(
        previous_manifest,
        desired_manifest,
        old_extras=old_extras,
        wanted_extras=wanted_extras,
    )
    extra_resources = deployment_plan("", "", old_extras=old_extras, wanted_extras=wanted_extras)
    resolved_target_version = target_version or current_version
    version_changed = bool(current_version and resolved_target_version and current_version != resolved_target_version)
    helm_upgrade_required = bool(
        any(chart_resources.values())
        or (previous_values is not None and desired_values is not None and previous_values != desired_values)
        or (not previous_manifest.strip() and bool(desired_manifest.strip()))
    )
    workflows = workflow_bundle_plan(resolved_prev_tree, desired_tree)
    reloads_set = set(config_reload_plan(resolved_prev_config, desired_config))
    if resolved_prev_tree is not None and desired_tree is not None and any(workflows.values()):
        reloads_set.add("workflow_bundles")
    migrations_list = list(migrations or [])
    if version_changed:
        ver_mig = f"platform_version:{current_version}->{resolved_target_version}"
        if ver_mig not in migrations_list:
            migrations_list.append(ver_mig)
    return {
        "ref": ref,
        "current_commit": current_commit or "",
        "target_commit": target_commit or "",
        "current_version": current_version,
        "target_version": resolved_target_version,
        "version_changed": version_changed,
        "version_change": version_changed,
        "helm_upgrade_required": helm_upgrade_required,
        "resources": resources,
        "chart_resources": chart_resources,
        "extra_resources": extra_resources,
        "workflows": workflows,
        "reloads": sorted(reloads_set),
        "migrations": migrations_list,
        "drift": list(drift or []),
    }


def format_deployment_plan(plan: dict) -> str:
    """Format a live deployment plan for CLI and Job log output without secret values."""
    cur_commit = (plan.get("current_commit") or "none")[:12]
    tgt_commit = (plan.get("target_commit") or plan.get("ref") or "working-tree")[:12]
    cur_ver = plan.get("current_version") or "unknown"
    tgt_ver = plan.get("target_version") or cur_ver
    ver_note = " (upgrade)" if (plan.get("version_changed") or plan.get("version_change")) else ""
    resources = plan.get("resources") or {}
    workflows = plan.get("workflows") or {}
    wf_summary = (
        f"+{len(workflows.get('create') or [])} "
        f"~{len(workflows.get('update') or [])} "
        f"-{len(workflows.get('delete') or [])}"
    )
    reloads = ", ".join(plan.get("reloads") or []) or "none"
    migrations = ", ".join(plan.get("migrations") or []) or "none"
    lines = [
        f"Deployment plan ({plan.get('ref', 'working-tree')}): commit {cur_commit} -> {tgt_commit}; "
        f"Platform version: {cur_ver} -> {tgt_ver}{ver_note}",
        "Helm resource plan: " + json.dumps(resources, sort_keys=True),
    ]
    for action in ("create", "roll", "update", "delete"):
        items = resources.get(action) or []
        if items:
            lines.append(f"  {action}: {', '.join(items)}")
    lines.extend(
        [
            f"  workflows ({wf_summary}): " + json.dumps({k: v for k, v in workflows.items() if v}, sort_keys=True),
            f"  in-place reloads: {reloads}; migrations: {migrations}",
        ]
    )
    for item in plan.get("drift") or []:
        lines.append(f"  drift: {item}")
    return "\n".join(lines)


def _version_tuple(raw: str) -> tuple[int, int, int] | None:
    match = _SEMVER_RE.match((raw or "").strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def validate_upgrade_path(current_version: str, target_version: str) -> None:
    """Ensure the platform version transition is supported and never downgrades."""
    cur = _version_tuple(current_version)
    tgt = _version_tuple(target_version)
    min_ver = _version_tuple(MIN_SUPPORTED_UPGRADE_VERSION)
    if cur is not None and min_ver is not None and cur < min_ver:
        raise ValueError(
            f"[upgrade] Upgrading from sage-run=={current_version} below "
            f"{MIN_SUPPORTED_UPGRADE_VERSION} is not supported"
        )
    if cur is not None and tgt is not None and tgt < cur:
        raise ValueError(
            f"[upgrade] Platform version downgrade from {current_version} to {target_version} is not supported; "
            "restore from backup instead"
        )


def collect_encrypted_secrets(
    config: dict,
    *,
    tree: Path | None = None,
    environment: str = "",
) -> dict[str, dict]:
    """Collect all encrypted secret mappings from platform secrets, connections, and workflow bundles."""
    from shared.lib.platform_config import load_platform_config

    collected: dict[str, dict] = {}
    for name, spec in (config.get("secrets") or {}).items():
        if isinstance(spec, dict) and isinstance(spec.get("encrypted"), str):
            collected[str(name)] = spec
    for conn_name, conn in (config.get("connections") or {}).items():
        if not isinstance(conn, dict):
            continue
        for sec_name, spec in (conn.get("secrets") or {}).items():
            if isinstance(spec, dict) and isinstance(spec.get("encrypted"), str):
                collected[f"connections.{conn_name}.secrets.{sec_name}"] = spec
    if tree and (tree / "workflows").is_dir():
        for agent_file in sorted((tree / "workflows").glob("*/agent.yaml")):
            wf_name = agent_file.parent.name
            wf_cfg = load_platform_config(agent_file, environment=environment)
            for sec_name, spec in (wf_cfg.get("secrets") or {}).items():
                if isinstance(spec, dict) and isinstance(spec.get("encrypted"), str):
                    collected[f"workflows.{wf_name}.secrets.{sec_name}"] = spec
    return collected


def verify_config_secrets(
    config: dict,
    *,
    identity: str | None = None,
    require_llm_key: bool = False,
    tree: Path | None = None,
    environment: str = "",
) -> dict[str, str]:
    """Validate encrypted secret structure and recipient decryptability without leaking plaintexts."""
    from shared.lib.crypto import decrypt_named_secrets

    platform_secrets = config.get("secrets") or {}
    if require_llm_key:
        llm_spec = platform_secrets.get("LLM_API_KEY")
        llm_enc = str((llm_spec or {}).get("encrypted") or "") if isinstance(llm_spec, dict) else ""
        if not (llm_enc.startswith("ENC[age,") or llm_enc.startswith("ENC[plain,")):
            raise ValueError("[secrets] platform config needs an encrypted LLM_API_KEY secret for this environment")

    all_secrets = collect_encrypted_secrets(config, tree=tree, environment=environment)
    age_ciphertexts: dict[str, str] = {}
    for label, spec in all_secrets.items():
        value = str(spec.get("encrypted") or "").strip()
        if value.startswith("ENC[age,"):
            age_ciphertexts[label] = value
        if identity:
            try:
                decrypted = decrypt_named_secrets({label: spec}, identity=identity)
            except Exception as exc:
                raise ValueError(
                    f"[secrets] Secret {label!r} cannot be decrypted with the active environment age identity"
                ) from exc
            if label not in decrypted:
                raise ValueError(
                    f"[secrets] Secret {label!r} cannot be decrypted with the active environment age identity"
                )
    return age_ciphertexts


def preflight_desired_tree(
    tree: Path,
    *,
    environment: str = "",
    current_version: str = "",
    identity: str | None = None,
    require_llm_key: bool = False,
    validate_repo: bool = True,
    allow_version_handover: bool = True,
) -> tuple[dict, str]:
    """Run full desired-ref preflight before any checkout or serving state mutation."""
    from sage_run.validation import ValidationReport, validate_dependency_pin, validate_workflow_repo_report
    from shared.lib.platform_config import load_platform_config, overlay_path, read_yaml_mapping, secrets_not_overridden

    pin_report = ValidationReport()
    pinned_version = validate_dependency_pin(tree, pin_report)
    if pin_report.errors:
        if current_version and pinned_version and pinned_version != current_version:
            raise ValueError(
                f"[pin] Platform version change requires committed uv.lock ({'; '.join(pin_report.errors)}) "
                f"or CLI upgrade; running sage-run=={current_version}"
            )
        raise ValueError("[pin] " + "; ".join(pin_report.errors))

    target_version = pinned_version or current_version
    if current_version and target_version:
        validate_upgrade_path(current_version, target_version)
        if not allow_version_handover and target_version != current_version:
            raise ValueError(
                f"[upgrade] Platform version change requires CLI upgrade; running sage-run=={current_version}"
            )

    if validate_repo:
        report = validate_workflow_repo_report(tree)
        if report.errors:
            raise ValueError("[validation] Workflow validation failed: " + "; ".join(report.errors))

    base_file = tree / "platform-config.yaml"
    if environment and base_file.exists():
        overlay_file = overlay_path(base_file, environment)
        if overlay_file.exists():
            missing_overrides = secrets_not_overridden(read_yaml_mapping(base_file), read_yaml_mapping(overlay_file))
            if missing_overrides:
                raise ValueError(
                    f"[secrets] Overlay {overlay_file.name} must override encrypted base secrets: "
                    + ", ".join(missing_overrides)
                )

    config = load_platform_config(base_file, environment=environment)
    verify_config_secrets(
        config,
        identity=identity,
        require_llm_key=require_llm_key,
        tree=tree,
        environment=environment,
    )
    return config, target_version


def extra_manifests(tree: Path, *, host_checkout: str, namespace: str) -> dict[tuple[str, str], dict]:
    """Render only namespace-scoped extras; hash checkout-backed subPath files."""
    resources = {}
    for path in sorted((tree / "deploy/k8s").glob("*.yaml")):
        rendered = path.read_text(encoding="utf-8").replace("${WORKFLOW_REPO_PATH}", host_checkout)
        for document in yaml.safe_load_all(rendered):
            if not document:
                continue
            metadata = document.setdefault("metadata", {})
            if document.get("kind") not in EXTRA_KINDS or metadata.get("namespace", namespace) != namespace:
                raise ValueError(f"{path.name}: extra manifests must use supported resources in {namespace}")
            name = metadata.get("name")
            if not name:
                raise ValueError(f"{path.name}: extra manifest needs metadata.name")
            metadata["namespace"] = namespace
            metadata.setdefault("labels", {})["sage-run/extra"] = namespace
            template = document.get("spec", {}).get("template")
            if template:
                digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode())
                pod = template.get("spec") or {}
                checkout_volumes = {
                    item["name"]
                    for item in pod.get("volumes", [])
                    if (item.get("hostPath") or {}).get("path") == host_checkout
                }
                for container in pod.get("containers", []):
                    for mount in container.get("volumeMounts", []):
                        if mount["name"] not in checkout_volumes or not mount.get("subPath"):
                            continue
                        source = (tree / mount["subPath"]).resolve()
                        if not source.is_relative_to(tree.resolve()) or not source.is_file():
                            raise ValueError(f"{path.name}: checkout subPath must name a file inside the repository")
                        digest.update(source.read_bytes())
                template.setdefault("metadata", {}).setdefault("annotations", {})["sage-run/source-checksum"] = (
                    digest.hexdigest()
                )
            key = (document["kind"], name)
            if key in resources:
                raise ValueError(f"Duplicate extra manifest: {key}")
            resources[key] = document
    return resources


def owned_extras(
    items: list[dict], namespace: str, *, desired: dict[tuple[str, str], dict]
) -> dict[tuple[str, str], dict]:
    resources = {}
    for item in items:
        metadata = item.get("metadata") or {}
        key = (item["kind"], metadata["name"])
        if metadata.get("labels", {}).get("sage-run/extra") != namespace:
            if key in desired:
                raise ValueError(
                    f"{key[0]}/{key[1]} exists without this instance's extra ownership; "
                    f"review it before explicitly labeling sage-run/extra={namespace}"
                )
            continue
        document = copy.deepcopy(item)
        document.pop("status", None)
        document["metadata"] = {
            key: value for key, value in metadata.items() if key in {"name", "namespace", "labels", "annotations"}
        }
        resources[key] = document
    return resources


def validate_ref(ref: str, *, remote: bool) -> str:
    ref = ref.strip()
    if not remote:
        if ref not in {"", "working-tree"}:
            raise ValueError("Local deployment uses the working tree, not a remote ref")
        return "working-tree"
    if ref != "main" and not re.fullmatch(r"v[A-Za-z0-9][A-Za-z0-9._-]{0,126}", ref):
        raise ValueError("Production deployment requires main or a v-prefixed tag")
    return ref


@contextmanager
def checkout_lock(checkout: Path) -> Iterator[None]:
    """Atomic mkdir also serializes macOS and Linux across Rancher's shared mount."""
    git_dir = checkout / ".git"
    if not git_dir.is_dir():
        raise ValueError("Deployment needs a Git checkout with a mounted .git directory")
    guard = git_dir / "sage-run-deploy.lock.d"
    try:
        guard.mkdir()
    except FileExistsError as exc:
        raise ValueError(
            f"Another deployment or backup owns {guard}; if stale, stop all writers before removing this directory"
        ) from exc
    # shortcut: forced termination leaves a guard; clear it only after all writers stop.
    try:
        yield
    finally:
        guard.rmdir()


def job_manifest(
    gateway: dict,
    *,
    namespace: str,
    ref: str,
    expected_commit: str | None = None,
    target_version: str | None = None,
    target_image: str | None = None,
) -> dict:
    """Reuse the running Gateway's mounts, networking and secrets, optionally targeting a new image/commit."""
    name = f"{DEPLOY_JOB}-{uuid4().hex[:12]}"
    template = copy.deepcopy(gateway["spec"]["template"])
    spec = template["spec"]
    container = next(item for item in spec["containers"] if item["name"] == "gateway")
    container.pop("ports", None)
    for field in ("readinessProbe", "livenessProbe", "startupProbe"):
        container.pop(field, None)
    container["name"] = "deploy"
    if target_image:
        container["image"] = target_image
    command = ["python", "-m", "sage_run", "deploy-in-cluster", "--ref", ref]
    if expected_commit:
        command.extend(["--expected-commit", expected_commit])
    container["command"] = command
    container.setdefault("env", []).append({"name": "SAGE_RUN_DEPLOY_JOB", "value": name})
    container.pop("args", None)
    spec["containers"] = [container]
    spec.pop("initContainers", None)
    spec["serviceAccountName"] = "sage-run-deployer"
    spec["restartPolicy"] = "Never"
    for mount in container.get("volumeMounts", []):
        if mount["name"] == "workflow-repo":
            mount["readOnly"] = False
    environment = {item["name"]: item.get("value", "") for item in container.get("env", [])}
    backup_path = environment.get("SAGE_RUN_BACKUP_HOST_PATH")
    if backup_path:
        spec.setdefault("volumes", []).append(
            {"name": "backups", "hostPath": {"path": backup_path, "type": "DirectoryOrCreate"}}
        )
        container.setdefault("volumeMounts", []).append(
            {"name": "backups", "mountPath": "/var/backups/sage-run/managed"}
        )
    if environment.get("SAGE_RUN_BACKUP_HINDSIGHT") == "true":
        spec.setdefault("volumes", []).append(
            {"name": "backup-hindsight", "persistentVolumeClaim": {"claimName": "hindsight-data", "readOnly": True}}
        )
        container.setdefault("volumeMounts", []).append(
            {"name": "backup-hindsight", "mountPath": "/var/lib/sage-run/backup-hindsight", "readOnly": True}
        )
    # hostPath and local-path PVCs must stay on the serving node.
    node = (gateway.get("metadata", {}).get("annotations") or {}).get("sage-run/node")
    if node:
        spec["nodeName"] = node
    template["metadata"] = {"labels": {DEPLOY_LABEL: "true"}}
    annotations = {REF_ANNOTATION: ref}
    if expected_commit:
        annotations[EXPECTED_COMMIT_ANNOTATION] = expected_commit
    if target_version:
        annotations[TARGET_VERSION_ANNOTATION] = target_version
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {DEPLOY_LABEL: "true"},
            "annotations": annotations,
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 3600,
            "ttlSecondsAfterFinished": 604800,
            "template": template,
        },
    }


def job_status(job: dict) -> dict:
    status = job.get("status") or {}
    conditions = status.get("conditions") or []
    failed = next((item for item in conditions if item.get("type") == "Failed" and item.get("status") == "True"), None)
    complete = any(item.get("type") == "Complete" and item.get("status") == "True" for item in conditions)
    metadata = job["metadata"]
    annotations = metadata.get("annotations") or {}
    return {
        "id": metadata["name"],
        "ref": annotations.get(REF_ANNOTATION, ""),
        "status": "failed" if failed else "succeeded" if complete else "running" if status.get("active") else "pending",
        "started_at": status.get("startTime") or metadata.get("creationTimestamp"),
        "finished_at": status.get("completionTime") or (failed or {}).get("lastTransitionTime"),
        "error": (failed or {}).get("message") or (failed or {}).get("reason"),
        "commit": annotations.get("sage-run/commit"),
        "expected_commit": annotations.get(EXPECTED_COMMIT_ANNOTATION),
        "target_version": annotations.get(TARGET_VERSION_ANNOTATION),
        "phase": annotations.get("sage-run/phase", "queued"),
    }
