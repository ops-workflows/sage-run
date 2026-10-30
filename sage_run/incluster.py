"""Workflow/config deployment in a Job independent of the Gateway process."""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import os
import shutil
import subprocess
import tempfile
from importlib.metadata import version
from pathlib import Path

from sage_run.backups import create_backup
from sage_run.deployment import (
    EXTRA_KINDS,
    TARGET_VERSION_ANNOTATION,
    build_deployment_plan,
    checkout_lock,
    deployment_plan,
    extra_manifests,
    owned_extras,
    validate_ref,
    validate_upgrade_path,
    verify_config_secrets,
)
from sage_run.local import (
    BOOTSTRAP_SECRET,
    RELEASE_NAME,
    Instance,
    _chart_path,
    bootstrap_secret_data,
    release_images,
    render_values,
)
from sage_run.remote import materialise
from shared.lib.config import settings
from shared.lib.platform_config import load_platform_config, overlay_path, read_yaml_mapping, secrets_not_overridden


def _run(*command: str, stdin: str | None = None, capture: bool = False, env: dict | None = None) -> str:
    result = subprocess.run(  # noqa: S603 - fixed executables and validated operator refs
        [shutil.which(command[0]) or command[0], *command[1:]],
        input=stdin,
        text=True,
        check=True,
        capture_output=capture,
        env=env,
        timeout=1800,
    )
    return result.stdout or ""


def _git(checkout: Path, *arguments: str, env: dict | None = None) -> str:
    return _run(
        "git", "-c", f"safe.directory={checkout}", "-C", str(checkout), *arguments, capture=True, env=env
    ).strip()


def _phase(message: str, *, commit: str = "", target_version: str = "") -> None:
    print(f"==> {message}", flush=True)
    job = os.environ.get("SAGE_RUN_DEPLOY_JOB")
    if job:
        annotations = [f"sage-run/phase={message}"]
        if commit:
            annotations.append(f"sage-run/commit={commit}")
        if target_version:
            annotations.append(f"{TARGET_VERSION_ANNOTATION}={target_version}")
        _run(
            "kubectl",
            "-n",
            settings.kubernetes_namespace,
            "annotate",
            "job",
            job,
            *annotations,
            "--overwrite",
            capture=True,
        )


def _fetch_commit(checkout: Path, ref: str) -> str:
    from shared.lib.github_app import github_git_auth_environment, github_installation_token
    from shared.lib.platform_secrets import load_workflow_repo_github_connection

    connection = load_workflow_repo_github_connection(settings.platform_config_file)
    if not connection:
        raise ValueError("Remote deployment requires workflow_repo.github_connection")
    if _git(checkout, "remote", "get-url", "origin") != settings.workflow_repo_url.strip():
        raise ValueError("Serving checkout origin does not match the configured workflow repository")
    token = github_installation_token(
        connection, platform_config_file=settings.platform_config_file, age_identity=settings.age_identity or None
    )
    source_ref = "refs/heads/main" if ref == "main" else f"refs/tags/{ref}"
    with github_git_auth_environment(token) as env:
        _git(checkout, "fetch", "--no-tags", "origin", source_ref, env=dict(env))
    return _git(checkout, "rev-parse", "--verify", "FETCH_HEAD^{commit}")


def _fetch_commit_nonmutating(checkout: Path, ref: str, temp_root: Path) -> tuple[Path, str]:
    """Fetch ref without writing to a read-only checkout mount when running in Gateway."""
    git_dir = checkout / ".git"
    if os.access(git_dir, os.W_OK):
        return checkout, _fetch_commit(checkout, ref)
    mirror = temp_root / "repo.git"
    _run("git", "init", "--bare", str(mirror), capture=True)
    alternates = mirror / "objects" / "info" / "alternates"
    alternates.parent.mkdir(parents=True, exist_ok=True)
    alternates.write_text(f"{git_dir / 'objects'}\n", encoding="utf-8")
    origin_url = _git(checkout, "remote", "get-url", "origin")
    _git(mirror, "remote", "add", "origin", origin_url)
    return mirror, _fetch_commit(mirror, ref)


def validate_platform_pin(tree: Path, running_version: str) -> str:
    from sage_run.validation import ValidationReport, validate_dependency_pin

    project_file = tree / "pyproject.toml"
    if not project_file.exists():
        return running_version  # Existing repositories predate the dependency-pin rollout.
    pin_report = ValidationReport()
    pinned_version = validate_dependency_pin(tree, pin_report)
    if pin_report.errors:
        raise ValueError(
            f"[pin] {'; '.join(pin_report.errors)} (or use CLI upgrade; running sage-run=={running_version})"
        )
    target_version = pinned_version or running_version
    validate_upgrade_path(running_version, target_version)
    return target_version


def resolve_target_images(
    current_images: dict,
    *,
    current_version: str,
    target_version: str,
    tree: Path | None = None,
) -> dict:
    """Resolve platform workload images for the desired pinned sage-run version."""
    if not target_version or target_version == current_version:
        return copy.deepcopy(current_images)
    resolved = copy.deepcopy(current_images)
    if tree is not None and (tree / "image-digests.json").is_file():
        overrides = json.loads((tree / "image-digests.json").read_text(encoding="utf-8"))
        resolved["tag"] = target_version
        resolved["overrides"] = overrides
        return resolved
    target_release = release_images(target_version)
    resolved["tag"] = target_release.get("tag", target_version)
    resolved["overrides"] = copy.deepcopy(target_release.get("overrides", {}))
    return resolved


def resolve_service_image(images: dict, component: str = "gateway") -> str:
    """Resolve a component's effective container image reference from Helm values."""
    override = (images.get("overrides") or {}).get(component)
    if override:
        return str(override)
    registry = str(images.get("registry") or "ghcr.io/ops-workflows").rstrip("/")
    prefix = str(images.get("prefix") if images.get("prefix") is not None else "sage-run-")
    tag = str(images.get("tag") or version("sage-run"))
    return f"{registry}/{prefix}{component}:{tag}" if registry else f"{prefix}{component}:{tag}"


def _handover_to_target_version(
    target_version: str,
    *,
    ref: str,
    expected_commit: str | None = None,
) -> int | None:
    """Optionally hand over execution to the target version's CLI in an isolated uv environment."""
    if os.environ.get("SAGE_RUN_HANDOVER_ENABLED") != "1":
        return None
    if os.environ.get("SAGE_RUN_HANDOVER_VERSION") == target_version:
        return None
    command = [
        "uv",
        "run",
        "--isolated",
        "--with",
        f"sage-run=={target_version}",
        "python",
        "-m",
        "sage_run",
        "deploy-in-cluster",
        "--ref",
        ref,
    ]
    if expected_commit:
        command.extend(["--expected-commit", expected_commit])
    env = {**os.environ, "SAGE_RUN_HANDOVER_VERSION": target_version}
    _run(*command, env=env)
    return 0


def merge_values(existing: dict, changes: dict) -> dict:
    result = dict(existing)
    for key, value in changes.items():
        result[key] = merge_values(result.get(key, {}), value) if isinstance(value, dict) else value
    return result


async def activate_checkout(ref: str) -> None:
    from gateway.provisioner import run_provisioner_scan
    from shared.lib.db import async_session_factory
    from shared.lib.workflow_repo_sync import sync_workflow_repo

    async with async_session_factory() as session:
        result = await sync_workflow_repo(session, prepared_ref=ref)
    if result.status != "ok":
        raise ValueError(f"Bundle activation failed: {result.error or result.bundle_errors}")
    await run_provisioner_scan()


def _helm_values(
    values: dict,
    *,
    previous_values: dict | None = None,
    old_extras: dict[tuple[str, str], dict] | None = None,
    wanted_extras: dict[tuple[str, str], dict] | None = None,
) -> dict[str, list[str]]:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "values.json"
        path.write_text(json.dumps(values), encoding="utf-8")
        previous = _run("helm", "get", "manifest", RELEASE_NAME, "-n", settings.kubernetes_namespace, capture=True)
        desired = _run(
            "helm",
            "template",
            RELEASE_NAME,
            str(_chart_path(None)),
            "-n",
            settings.kubernetes_namespace,
            "-f",
            str(path),
            "--is-upgrade",
            capture=True,
        )
        chart_plan = deployment_plan(previous, desired)
        full_plan = deployment_plan(previous, desired, old_extras=old_extras, wanted_extras=wanted_extras)
        print("Helm resource plan: " + json.dumps(full_plan, sort_keys=True), flush=True)
        if not any(chart_plan.values()) and values == previous_values:
            print("No Helm changes; activating bundles/configuration in place", flush=True)
            return full_plan
        _run(
            "helm",
            "upgrade",
            RELEASE_NAME,
            str(_chart_path(None)),
            "-n",
            settings.kubernetes_namespace,
            "-f",
            str(path),
            "--wait",
            "--timeout",
            "15m",
        )
        return full_plan


def _compose_candidate_values(
    current: dict,
    *,
    tree: Path,
    namespace: str,
    remote: bool,
    environment: str,
    ref: str,
    config: dict,
    running_version: str,
    target_version: str,
) -> dict:
    instance = Instance(tree, namespace, sandbox_profile="", local=not remote, environment=environment)
    changes = render_values(instance, config)
    changes["images"] = resolve_target_images(
        current.get("images") or {},
        current_version=running_version,
        target_version=target_version,
        tree=tree,
    )
    changes["workflowRepo"] = {**current.get("workflowRepo", {}), "ref": ref if remote else ""}
    changes["ingress"] = current.get("ingress", {"enabled": False})
    values = merge_values(current, changes)
    # Explicit enable maps must replace old maps, otherwise removed MCPs survive a recursive merge.
    for key in ("mcps", "connectors", "workflowMcps", "env", "serviceEnv", "hostAliases", "configChecksums"):
        values[key] = changes[key]
    if "deployer" in current:
        values["deployer"] = current["deployer"]
    if remote:
        ui = (config.get("deployment") or {}).get("ui") or {}
        values["controlPlaneUi"] = {
            **current.get("controlPlaneUi", {}),
            "hostIP": str(ui.get("host_ip") or ""),
            "hostPort": int(ui.get("host_port") or 0),
        }
    if values.get("infrastructure") != current.get("infrastructure", {}):
        raise ValueError("Infrastructure changes require a CLI platform upgrade, not a workflow deployment")
    return values


def _validate_desired_tree_and_config(
    tree: Path,
    *,
    running_version: str,
    environment: str,
    identity: str | None = None,
) -> tuple[str, dict]:
    target_version = validate_platform_pin(tree, running_version)
    from sage_run.validation import validate_workflow_repo_report

    report = validate_workflow_repo_report(tree)
    if report.errors:
        raise ValueError("[validation] Workflow validation failed: " + "; ".join(report.errors))
    base_file = tree / "platform-config.yaml"
    if environment and base_file.exists():
        overlay_file = overlay_path(base_file, environment)
        if overlay_file.exists():
            missing = secrets_not_overridden(read_yaml_mapping(base_file), read_yaml_mapping(overlay_file))
            if missing:
                raise ValueError(
                    f"[secrets] Overlay {overlay_file.name} must override encrypted base secrets: " + ", ".join(missing)
                )
    config = load_platform_config(base_file, environment=environment)
    if identity:
        verify_config_secrets(config, identity=identity, tree=tree, environment=environment)
    return target_version, config


def plan_in_cluster(ref: str) -> dict:
    """Compute a live pre-confirmation deployment plan without mutating checkout or cluster state."""
    checkout = Path(settings.workflow_repo_local_path)
    namespace = settings.kubernetes_namespace
    remote = settings.workflow_repo_source.strip().lower() != "local"
    ref = validate_ref(ref, remote=remote)
    if not settings.workflow_repo_managed:
        raise ValueError("This instance has not enabled deployment-managed checkouts")
    running_version = version("sage-run")
    environment = os.environ.get("SAGE_RUN_ENV", "")
    original_commit = _git(checkout, "rev-parse", "HEAD")
    if remote and _git(checkout, "status", "--porcelain"):
        raise ValueError("[drift] Serving checkout has local changes; resolve drift before deploying")

    with tempfile.TemporaryDirectory() as temporary:
        temp_root = Path(temporary)
        if remote:
            source_repo, commit = _fetch_commit_nonmutating(checkout, ref, temp_root)
            tree = temp_root / "tree"
            materialise(source_repo, commit, tree)
        else:
            commit = original_commit
            tree = checkout

        previous_config = (
            load_platform_config(checkout / "platform-config.yaml", environment=environment)
            if (checkout / "platform-config.yaml").exists()
            else {}
        )
        identity = settings.age_identity or os.environ.get("AGE_IDENTITY") or None
        target_version, config = _validate_desired_tree_and_config(
            tree,
            running_version=running_version,
            environment=environment,
            identity=identity,
        )

        try:
            current = json.loads(
                _run("helm", "get", "values", RELEASE_NAME, "-n", namespace, "-o", "json", capture=True)
            )
            host_checkout = str((current.get("workflowRepo") or {}).get("hostPath") or checkout)
            inventory = json.loads(
                _run("kubectl", "-n", namespace, "get", ",".join(EXTRA_KINDS), "-o", "json", capture=True)
            )
            wanted_extras = extra_manifests(tree, host_checkout=host_checkout, namespace=namespace)
            old_extras = owned_extras(inventory.get("items", []), namespace, desired=wanted_extras)
            previous_manifest = _run("helm", "get", "manifest", RELEASE_NAME, "-n", namespace, capture=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            # Fallback when called from the read-only Gateway ServiceAccount without Helm Secret RBAC.
            host_checkout = str(checkout)
            current_instance = Instance(
                checkout, namespace, sandbox_profile="", local=not remote, environment=environment
            )
            current = render_values(current_instance, previous_config)
            current["images"] = release_images(running_version)
            current["workflowRepo"] = {
                "hostPath": host_checkout,
                "source": settings.workflow_repo_source,
                "url": settings.workflow_repo_url,
                "ref": settings.workflow_repo_ref,
            }
            current["deployer"] = {"enabled": True}
            current["backups"] = {"enabled": True}
            wanted_extras = extra_manifests(tree, host_checkout=host_checkout, namespace=namespace)
            old_extras = extra_manifests(checkout, host_checkout=host_checkout, namespace=namespace)
            prev_values_path = temp_root / "previous-values.json"
            prev_values_path.write_text(json.dumps(current), encoding="utf-8")
            previous_manifest = _run(
                "helm",
                "template",
                RELEASE_NAME,
                str(_chart_path(None)),
                "-n",
                namespace,
                "-f",
                str(prev_values_path),
                "--is-upgrade",
                capture=True,
            )

        recorded_commit = str((current.get("workflowRepo") or {}).get("commit") or "")
        if remote and recorded_commit and recorded_commit != original_commit:
            raise ValueError(
                f"[drift] Serving checkout HEAD {original_commit[:12]} does not match release commit "
                f"{recorded_commit[:12]}; resolve drift before deploying"
            )

        values = _compose_candidate_values(
            current,
            tree=tree,
            namespace=namespace,
            remote=remote,
            environment=environment,
            ref=ref,
            config=config,
            running_version=running_version,
            target_version=target_version,
        )
        values_path = temp_root / "desired-values.json"
        values_path.write_text(json.dumps(values), encoding="utf-8")
        desired_manifest = _run(
            "helm",
            "template",
            RELEASE_NAME,
            str(_chart_path(None)),
            "-n",
            namespace,
            "-f",
            str(values_path),
            "--is-upgrade",
            capture=True,
        )
        return build_deployment_plan(
            previous_manifest,
            desired_manifest,
            old_extras=old_extras,
            wanted_extras=wanted_extras,
            previous_tree=checkout,
            desired_tree=tree,
            previous_config=previous_config,
            desired_config=config,
            ref=ref,
            current_commit=original_commit,
            target_commit=commit,
            current_version=running_version,
            target_version=target_version,
        )


def deploy_in_cluster(ref: str, *, expected_commit: str | None = None) -> int:
    from sqlalchemy.exc import SQLAlchemyError

    checkout = Path(settings.workflow_repo_local_path)
    namespace = settings.kubernetes_namespace
    remote = settings.workflow_repo_source.strip().lower() != "local"
    ref = validate_ref(ref, remote=remote)
    if not settings.workflow_repo_managed:
        raise ValueError("This instance has not enabled deployment-managed checkouts")
    running_version = version("sage-run")
    environment = os.environ.get("SAGE_RUN_ENV", "")
    with checkout_lock(checkout), tempfile.TemporaryDirectory() as temporary:
        _phase("preflight")
        original_commit = _git(checkout, "rev-parse", "HEAD")
        if remote and _git(checkout, "status", "--porcelain"):
            raise ValueError("[drift] Serving checkout has local changes; resolve drift before deploying")
        current = json.loads(_run("helm", "get", "values", RELEASE_NAME, "-n", namespace, "-o", "json", capture=True))
        recorded_commit = str((current.get("workflowRepo") or {}).get("commit") or "")
        if remote and recorded_commit and recorded_commit != original_commit:
            raise ValueError(
                f"[drift] Serving checkout HEAD {original_commit[:12]} does not match release commit "
                f"{recorded_commit[:12]}; resolve drift before deploying"
            )
        host_checkout = str(current["workflowRepo"].get("hostPath") or "")
        inventory = json.loads(
            _run(
                "kubectl",
                "-n",
                namespace,
                "get",
                ",".join(EXTRA_KINDS),
                "-o",
                "json",
                capture=True,
            )
        )
        commit = _fetch_commit(checkout, ref) if remote else original_commit
        if expected_commit and commit != expected_commit:
            raise ValueError(
                f"[drift] Target ref {ref} moved from expected commit {expected_commit[:12]} to {commit[:12]}; "
                "re-run plan before deploying"
            )
        tree = Path(temporary) / "tree" if remote else checkout
        if remote:
            materialise(checkout, commit, tree)
        wanted_extras = extra_manifests(tree, host_checkout=host_checkout, namespace=namespace)
        old_extras = owned_extras(inventory["items"], namespace, desired=wanted_extras)
        if any(kind == "PersistentVolumeClaim" for kind, _ in old_extras.keys() - wanted_extras.keys()):
            raise ValueError("Removing an extra PVC requires an explicit storage migration")
        target_version, config = _validate_desired_tree_and_config(
            tree,
            running_version=running_version,
            environment=environment,
            identity=None,
        )
        if target_version != running_version:
            handover_rc = _handover_to_target_version(target_version, ref=ref, expected_commit=expected_commit)
            if handover_rc is not None:
                return handover_rc
        raw_secret = _run("kubectl", "-n", namespace, "get", "secret", BOOTSTRAP_SECRET, "-o", "json", capture=True)
        secret = json.loads(raw_secret)
        old_data = {key: base64.b64decode(value).decode() for key, value in secret.get("data", {}).items()}
        active_identity = settings.age_identity or old_data.get("AGE_IDENTITY") or None
        if active_identity:
            verify_config_secrets(config, identity=active_identity, tree=tree, environment=environment)
        new_data = bootstrap_secret_data(old_data, settings.age_identity, config)
        for name in ("PG_PASSWORD", "OBJECT_STORE_SECRET_KEY"):
            if new_data[name] != old_data[name]:
                raise ValueError(f"{name} rotation needs a coordinated infrastructure migration; not a workflow deploy")
        values = _compose_candidate_values(
            current,
            tree=tree,
            namespace=namespace,
            remote=remote,
            environment=environment,
            ref=ref,
            config=config,
            running_version=running_version,
            target_version=target_version,
        )
        _phase("backup", commit=commit, target_version=target_version)
        if (current.get("backups") or {}).get("enabled"):
            create_backup(namespace=namespace, kind="deployment", checkout=checkout)
        elif remote:
            raise ValueError("Production deployment requires backups.enabled and a backup mount")
        previous_secret = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": BOOTSTRAP_SECRET},
            "data": secret["data"],
        }
        wanted_secret = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": BOOTSTRAP_SECRET},
            "stringData": new_data,
        }
        try:
            _phase("apply", commit=commit, target_version=target_version)
            if remote:
                _git(checkout, "checkout", "--detach", commit)
            if new_data != old_data:
                _run("kubectl", "-n", namespace, "apply", "-f", "-", stdin=json.dumps(wanted_secret), capture=True)
            _helm_values(values, previous_values=current, old_extras=old_extras, wanted_extras=wanted_extras)
            for document in wanted_extras.values():
                _run("kubectl", "-n", namespace, "apply", "-f", "-", stdin=json.dumps(document), capture=True)
            for kind, name in old_extras.keys() - wanted_extras.keys():
                _run("kubectl", "-n", namespace, "delete", kind, name, capture=True)
            _phase("activate", commit=commit, target_version=target_version)
            asyncio.run(activate_checkout(ref))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, SQLAlchemyError):
            _phase("recovering", commit=commit, target_version=target_version)
            if remote:
                _git(checkout, "checkout", "--detach", original_commit)
            _run("kubectl", "-n", namespace, "apply", "-f", "-", stdin=json.dumps(previous_secret), capture=True)
            _helm_values(current)
            for kind, name in wanted_extras.keys() - old_extras.keys():
                _run("kubectl", "-n", namespace, "delete", kind, name, "--ignore-not-found", capture=True)
            for document in old_extras.values():
                _run("kubectl", "-n", namespace, "apply", "-f", "-", stdin=json.dumps(document), capture=True)
            asyncio.run(activate_checkout(str(current["workflowRepo"].get("ref") or "working-tree")))
            _phase("failed; previous checkout and Helm values restored", commit=commit, target_version=target_version)
            raise
        _phase("complete", commit=commit, target_version=target_version)
        if target_version != running_version:
            print(f"Deployed {commit[:12]} ({ref}); platform images updated to {target_version}", flush=True)
        else:
            print(f"Deployed {commit[:12]} ({ref}); platform images unchanged", flush=True)
    return 0
