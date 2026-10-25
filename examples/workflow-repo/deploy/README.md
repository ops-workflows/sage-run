# Deployment (Example)

This directory shows how to run the public platform's base stack against a
workflow repo checked out as a sibling directory of `sage-run`.
This is one of two supported deployment modes — see
[docs/deployment.md](../../../docs/deployment.md) for the other (`make
bootstrap` targeting a remote/pinned workflow repo).

## Docker Compose

The base `deploy/docker-compose.yml` already covers everything a workflow repo
needs — pointing at your repo, and every MCP server/connector the platform
ships — via env vars and `COMPOSE_PROFILES`. **No compose override is needed**
unless you're adding a *custom* MCP server or connector (see
[docker-compose.override.yml](docker-compose.override.yml) for that case).

Run `make bootstrap` in `sage-run/` first (see its
`docs/deployment.md`) to generate a private `compose.env` (default
`~/.local/state/sage-run/local/`) with the operator bootstrap
layer (`AGE_IDENTITY`, `LLM_API_KEY`, workflow-repo pointer, pointed
at your repo's local path). Copy [compose.env.example](compose.env.example) to
your workflow repo as `deploy/compose.env` and set its non-secret values. Then
from `sage-run/`, run:

```sh
make up
```

The Makefile loads `deploy/compose.env` first, then the generated private
`compose.env`, and derives the required profiles from `platform-config.yaml`.

### Adding your own custom MCP server or connector

If your workflow repo defines its own MCP server or connector (see
[mcps/custom-mcp-example/](../mcps/custom-mcp-example/) and
[connectors/custom-connector-example/](../connectors/custom-connector-example/)),
those don't exist in the base compose file and do need an override. After
`make bootstrap`, the public Makefile automatically loads the workflow repo's
`deploy/docker-compose.override.yml` when it exists:

```sh
COMPOSE_PROFILES=custom-example make up
```

Set these when the repos are not sibling directories:

```sh
export HOST_WORKFLOW_REPO_PATH=/path/to/my-workflow-repo
```

## Kubernetes (Helm)

Run the repository as a local Kubernetes instance with `sage-run up` (see
[docs/deployment.md](../../../docs/deployment.md#kubernetes-deployment)). The
chart takes its values from this repository: MCP servers and connectors from
`platform-config.yaml`, knowledge and Hindsight settings from
`deploy/compose.env`. No separate values file is needed.
