# Starter Workflow Repository

Copy this directory into a standalone repository to create a new SAGE Run instance.

## Structure

```text
pyproject.toml                  # Exact sage-run==<release> dependency and dev tools
uv.lock                         # Committed dependency lockfile (uv sync --frozen)
Makefile                        # Thin installed-dependency wrappers for sage-run, ruff, pytest
platform-config.yaml            # Base / development configuration
platform-config-prod.yaml       # Production overlay (merged over platform-config.yaml)
workflows/
  example-workflow/             # Replace with your workflows
    agent.yaml
    settings.json
    .mcp.json
    agents/
    skills/
    hooks/
mcps/
  README.md                     # Custom MCP convention
  custom-mcp-example/           # Optional repo-local MCP server (delete if unused)
tests/                          # Workflow and custom MCP unit tests
```

## Setup and Validation

Install the locked environment (no sibling `sage-run` checkout required):

```bash
uv sync --frozen
make validate
make lint
make test
make ci
```

To upgrade the pinned platform version, update `sage-run==<release>` in `pyproject.toml`, run `uv lock`, verify with `make ci`, and commit both `pyproject.toml` and `uv.lock`.

## Local Development (`up`, `down`, `status`, `dev`)

Generate a gitignored repository-local development age key and encrypt your development `LLM_API_KEY` into `platform-config.yaml`:

```bash
uv run sage-run keygen --out ./dev.agekey
# Copy the printed public key to config.AGE_PUBLIC_KEY in platform-config.yaml
make secret-set ENV=dev NAME=LLM_API_KEY
make secret-set ENV=dev CONNECTION=custom-example NAME=CUSTOM_EXAMPLE_TOKEN
```

Start, inspect, or remove the local Kubernetes instance in Rancher Desktop:

```bash
make up
make status
make down
```

To test against an unpublished local `sage-run` checkout without modifying `pyproject.toml` or `uv.lock`:

```bash
make dev SAGE_RUN_SOURCE=../sage-run
# Or run multiple isolated local instances against one modified platform checkout:
make dev SAGE_RUN_SOURCE=../sage-run INSTANCE=workflow-a
```

## Planning and Deployment (`ENV`, `TARGET`, `REF`)

- **Local (`TARGET` unset, `ENV` unset or `dev`)**:
  - `make plan`: validates the working tree and prints the local instance target.
  - `make deploy`: applies the local working tree to Rancher Desktop (`make up`).
- **Remote SSH (`TARGET=<ssh-host>`, default `ENV=prod`, default `REF=main`)**:
  - `make plan TARGET=<ssh-host> ENV=prod REF=main`: materializes the committed `REF`, validates pin/lock agreement and configuration, and prints the remote deployment plan without mutating the host.
  - `make deploy TARGET=<ssh-host> ENV=prod REF=main`: deploys the pushed `REF` (`main` or a `v`-prefixed tag on `origin`) with `platform-config-prod.yaml` to `<ssh-host>` over SSH.
  - Passing `ENV=prod` without `TARGET` fails fast so production overlays are never applied to a local cluster by mistake.
