"""Workflow/config deployment in a Job independent of the Gateway process."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
from importlib.metadata import version
from pathlib import Path

from sage_run.backups import create_backup
from sage_run.deployment import EXTRA_KINDS, checkout_lock, extra_manifests, owned_extras, validate_ref
from sage_run.local import BOOTSTRAP_SECRET, RELEASE_NAME, Instance, _chart_path, bootstrap_secret_data, render_values
from sage_run.remote import materialise
from shared.lib.config import settings
from shared.lib.platform_config import load_platform_config


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


def _phase(message: str, *, commit: str = "") -> None:
    print(f"==> {message}", flush=True)
    job = os.environ.get("SAGE_RUN_DEPLOY_JOB")
    if job:
        annotations = [f"sage-run/phase={message}"]
        if commit:
            annotations.append(f"sage-run/commit={commit}")
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


def validate_platform_pin(tree: Path, running_version: str) -> None:
    project_file = tree / "pyproject.toml"
    if not project_file.exists():
        return  # Existing repositories predate the dependency-pin rollout.
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))
    for dependency in (project.get("project") or {}).get("dependencies") or []:
        if dependency.lower().replace("_", "-").startswith("sage-run") and dependency != f"sage-run=={running_version}":
            raise ValueError(f"Platform version change requires CLI upgrade; running sage-run=={running_version}")


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


def _helm_values(values: dict) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "values.json"
        path.write_text(json.dumps(values), encoding="utf-8")
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


def deploy_in_cluster(ref: str) -> int:
    from sqlalchemy.exc import SQLAlchemyError

    checkout = Path(settings.workflow_repo_local_path)
    namespace = settings.kubernetes_namespace
    remote = settings.workflow_repo_source.strip().lower() != "local"
    ref = validate_ref(ref, remote=remote)
    if not settings.workflow_repo_managed:
        raise ValueError("This instance has not enabled deployment-managed checkouts")
    with checkout_lock(checkout), tempfile.TemporaryDirectory() as temporary:
        _phase("preflight")
        original_commit = _git(checkout, "rev-parse", "HEAD")
        if remote and _git(checkout, "status", "--porcelain"):
            raise ValueError("Serving checkout has local changes; resolve drift before deploying")
        current = json.loads(_run("helm", "get", "values", RELEASE_NAME, "-n", namespace, "-o", "json", capture=True))
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
        tree = Path(temporary) / "tree" if remote else checkout
        if remote:
            materialise(checkout, commit, tree)
        wanted_extras = extra_manifests(tree, host_checkout=host_checkout, namespace=namespace)
        old_extras = owned_extras(inventory["items"], namespace, desired=wanted_extras)
        if any(kind == "PersistentVolumeClaim" for kind, _ in old_extras.keys() - wanted_extras.keys()):
            raise ValueError("Removing an extra PVC requires an explicit storage migration")
        validate_platform_pin(tree, version("sage-run"))
        from sage_run.validation import validate_workflow_repo_report

        report = validate_workflow_repo_report(tree)
        if report.errors:
            raise ValueError("Workflow validation failed: " + "; ".join(report.errors))
        config = load_platform_config(tree / "platform-config.yaml", environment=os.environ.get("SAGE_RUN_ENV", ""))
        raw_secret = _run("kubectl", "-n", namespace, "get", "secret", BOOTSTRAP_SECRET, "-o", "json", capture=True)
        secret = json.loads(raw_secret)
        old_data = {key: base64.b64decode(value).decode() for key, value in secret.get("data", {}).items()}
        new_data = bootstrap_secret_data(old_data, settings.age_identity, config)
        for name in ("PG_PASSWORD", "OBJECT_STORE_SECRET_KEY"):
            if new_data[name] != old_data[name]:
                raise ValueError(f"{name} rotation needs a coordinated infrastructure migration; not a workflow deploy")
        instance = Instance(
            tree, namespace, sandbox_profile="", local=not remote, environment=os.environ.get("SAGE_RUN_ENV", "")
        )
        changes = render_values(instance, config)
        changes["images"] = current["images"]
        changes["workflowRepo"] = {**current["workflowRepo"], "ref": ref if remote else ""}
        changes["ingress"] = current.get("ingress", {"enabled": False})
        values = merge_values(current, changes)
        # Explicit enable maps must replace old maps, otherwise removed MCPs survive a recursive merge.
        for key in ("mcps", "connectors", "workflowMcps", "env", "serviceEnv", "hostAliases"):
            values[key] = changes[key]
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
        _phase("backup", commit=commit)
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
            _phase("apply", commit=commit)
            if remote:
                _git(checkout, "checkout", "--detach", commit)
            if new_data != old_data:
                _run("kubectl", "-n", namespace, "apply", "-f", "-", stdin=json.dumps(wanted_secret), capture=True)
            _helm_values(values)
            for document in wanted_extras.values():
                _run("kubectl", "-n", namespace, "apply", "-f", "-", stdin=json.dumps(document), capture=True)
            for kind, name in old_extras.keys() - wanted_extras.keys():
                _run("kubectl", "-n", namespace, "delete", kind, name, capture=True)
            _phase("activate", commit=commit)
            asyncio.run(activate_checkout(ref))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, SQLAlchemyError):
            _phase("recovering", commit=commit)
            if remote:
                _git(checkout, "checkout", "--detach", original_commit)
            _run("kubectl", "-n", namespace, "apply", "-f", "-", stdin=json.dumps(previous_secret), capture=True)
            _helm_values(current)
            for kind, name in wanted_extras.keys() - old_extras.keys():
                _run("kubectl", "-n", namespace, "delete", kind, name, "--ignore-not-found", capture=True)
            for document in old_extras.values():
                _run("kubectl", "-n", namespace, "apply", "-f", "-", stdin=json.dumps(document), capture=True)
            asyncio.run(activate_checkout(str(current["workflowRepo"].get("ref") or "working-tree")))
            _phase("failed; previous checkout and Helm values restored", commit=commit)
            raise
        _phase("complete", commit=commit)
        print(f"Deployed {commit[:12]} ({ref}); platform images unchanged", flush=True)
    return 0
