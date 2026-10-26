"""Command-line entry point for SAGE Run operators."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sage-run")
    parser.add_argument("--version", action="store_true", help="Show the installed package version")
    commands = parser.add_subparsers(dest="command")
    in_cluster = commands.add_parser("deploy-in-cluster", help="Run the namespace deployment Job")
    in_cluster.add_argument("--ref", required=True)
    backup = commands.add_parser("backup", help="Create and rotate namespace recovery sets")
    backup.add_argument("--kind", required=True, choices=("nightly", "deployment"))
    activate = commands.add_parser("activate", help="Activate the already prepared workflow checkout")
    activate.add_argument("--ref", required=True)
    validate = commands.add_parser("validate", help="Validate an existing workflow repository")
    validate.add_argument("workflow_repo", type=Path, nargs="?", default=Path.cwd())
    for action, description in (
        ("up", "Create or update the local Kubernetes instance from the working tree"),
        ("down", "Remove the local instance's workloads (volumes are kept)"),
        ("status", "Show the local instance's workloads"),
    ):
        local = commands.add_parser(action, help=description)
        local.add_argument("workflow_repo", type=Path, nargs="?", default=Path.cwd())
        local.add_argument("--instance", help="Instance and namespace name (default: <repo folder>-dev)")
        local.add_argument("--context", default="rancher-desktop", help="kubectl context")
        if action == "up":
            local.add_argument("--source", type=Path, help="Build platform images from this sage-run checkout")
            local.add_argument("--image-tag", help="Use existing local images with this tag")
            local.add_argument("--no-build", action="store_true", help="With --source, reuse already built images")
            local.add_argument("--identity", type=Path, help="Age key file (default: ~/.config/sage-run/dev.agekey)")
            local.add_argument("--sandbox", default="local", choices=("local", "ci", "gvisor"))
            local.add_argument("--env", default="", help="Config overlay to use, e.g. prod (default: base config)")
        if action == "down":
            local.add_argument("--purge", action="store_true", help="Also delete the namespace and its volumes")
    deploy = commands.add_parser("deploy", help="Deploy a pushed commit to a k3s host over SSH")
    deploy.add_argument("workflow_repo", type=Path, nargs="?", default=Path.cwd())
    deploy.add_argument("--host", required=True, help="SSH host (e.g. a ~/.ssh/config alias)")
    deploy.add_argument("--env", default="prod", help="Config overlay (default: prod)")
    deploy.add_argument("--ref", default="main", help="main or a v-prefixed tag on origin (default: main)")
    deploy.add_argument("--instance", help="Namespace (default: repository folder name)")
    deploy.add_argument("--image-tag", help="Use images already loaded on the host with this tag")
    deploy.add_argument("--plan", action="store_true", help="Show what would be deployed and stop")
    keygen = commands.add_parser("keygen", help="Generate an environment age key (private file, public key printed)")
    keygen.add_argument("--out", type=Path, required=True, help="New private key file (mode 0600)")
    secret = commands.add_parser("secret", help="Manage encrypted config values")
    secret_commands = secret.add_subparsers(dest="secret_command", required=True)
    secret_set = secret_commands.add_parser("set", help="Encrypt a value into platform-config[-ENV].yaml")
    secret_set.add_argument("workflow_repo", type=Path, nargs="?", default=Path.cwd())
    secret_set.add_argument("--env", default="dev", help="dev (platform-config.yaml) or an overlay such as prod")
    secret_set.add_argument("--name", required=True, help="Variable name, e.g. SPLUNK_PASSWORD")
    secret_set.add_argument("--connection", help="Store in this connection instead of platform secrets")
    secret_set.add_argument("--value-file", type=Path, help="Read the value from a file instead of a prompt")
    args = parser.parse_args(argv)
    if args.version:
        print(f"sage-run {version('sage-run')}")
        return 0
    if args.command in {"deploy-in-cluster", "backup", "activate"}:
        from sage_run.backups import create_backup
        from sage_run.deployment import checkout_lock
        from sage_run.incluster import activate_checkout, deploy_in_cluster
        from shared.lib.config import settings

        try:
            if args.command == "deploy-in-cluster":
                return deploy_in_cluster(args.ref)
            if args.command == "activate":
                import asyncio

                asyncio.run(activate_checkout(args.ref))
            else:
                checkout = Path(settings.workflow_repo_local_path)
                with checkout_lock(checkout):
                    create_backup(namespace=settings.kubernetes_namespace, kind=args.kind, checkout=checkout)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "validate":
        from sage_run.validation import validate_workflow_repo_report

        report = validate_workflow_repo_report(args.workflow_repo.expanduser())
        for warning in report.warnings:
            print(f"warning: {warning}")
        for error in report.errors:
            print(error)
        return int(bool(report.errors))
    if args.command == "deploy":
        from sage_run.remote import deploy as remote_deploy

        try:
            return remote_deploy(
                args.workflow_repo,
                host=args.host,
                environment=args.env.strip().lower(),
                ref=args.ref,
                name=args.instance,
                image_tag=args.image_tag,
                version=version("sage-run"),
                plan_only=args.plan,
            )
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.command == "keygen":
        from sage_run.keys import generate_key

        try:
            print(generate_key(args.out))
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "secret":
        from sage_run.keys import read_value, set_secret

        try:
            path = set_secret(
                args.workflow_repo.expanduser().resolve(),
                environment=args.env.strip().lower(),
                name=args.name,
                value=read_value(args.value_file),
                connection=args.connection,
            )
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Updated {path}; review and commit it.")
        return 0
    if args.command in {"up", "down", "status"}:
        from sage_run import local

        try:
            if args.command == "up":
                return local.up(
                    args.workflow_repo,
                    source=args.source,
                    name=args.instance,
                    context=args.context,
                    image_tag=args.image_tag,
                    identity_file=args.identity,
                    sandbox_profile=args.sandbox,
                    build=not args.no_build,
                    environment=args.env.strip().lower(),
                )
            if args.command == "down":
                return local.down(args.workflow_repo, name=args.instance, context=args.context, purge=args.purge)
            return local.status(args.workflow_repo, name=args.instance, context=args.context)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            return local.main_error(exc)
    parser.print_help()
    return 0
