"""Command-line entry point for SAGE Run operators."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sage-run")
    parser.add_argument("--version", action="store_true", help="Show the installed package version")
    commands = parser.add_subparsers(dest="command")
    bootstrap = commands.add_parser("bootstrap", help="Generate private operator bootstrap configuration")
    bootstrap.add_argument(
        "--output-dir", type=Path, required=True, help="Private instance state directory outside Git"
    )
    validate = commands.add_parser("validate", help="Validate an existing workflow repository")
    validate.add_argument("workflow_repo", type=Path, nargs="?", default=Path.cwd())
    profiles = commands.add_parser("profiles", help="Print optional Compose profiles for a workflow repository")
    profiles.add_argument("workflow_repo", type=Path, nargs="?", default=Path.cwd())
    args = parser.parse_args(argv)
    if args.version:
        print(f"sage-run {version('sage-run')}")
        return 0
    if args.command == "bootstrap":
        from sage_run.bootstrap import main as bootstrap_main

        return bootstrap_main(output_dir=args.output_dir.expanduser().resolve())
    if args.command == "validate":
        from sage_run.validation import validate_workflow_repo

        errors = validate_workflow_repo(args.workflow_repo.expanduser())
        for error in errors:
            print(error)
        return int(bool(errors))
    if args.command == "profiles":
        from sage_run.profiles import workflow_profiles

        try:
            print(",".join(workflow_profiles(args.workflow_repo.expanduser())))
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    parser.print_help()
    return 0
