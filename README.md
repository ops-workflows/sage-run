# SAGE Run

**The governed agent platform for enterprise IT operations.**

SAGE Run (**S**ecure **A**gent **G**overnance & **E**xecution) is a workflow runtime and
control plane for AI agents that perform asynchronous IT operations work: it
queues incoming work, launches an isolated Claude Code agent per task with the
tools and memory that workflow needs, brokers human
approvals/clarifications, and gives you a web UI over all of it. Workflow
implementations (prompts, skills, connector instances, integration policy)
live in your own workflow repository; this repo is the platform they run on.

## Capabilities

- **Workflow packages and bundle assembly** — a workflow is `agent.yaml` +
  `settings.json` + `.mcp.json` + skills/hooks/agents, merged with shared
  platform/team assets into a versioned, checksummed bundle.
- **Claude Code runtime harness** — ephemeral per-task containers with
  subagents, human-in-the-loop approvals, a built-in clarification
  (`AskUserQuestion`) flow, and a sandboxed-credential deny-list so secrets
  never reach the model's shell.
- **MCP server framework** — a public catalog of core (message, memory,
  platform self-service) and integration (Salesforce, Jira, Splunk,
  CloudWatch) servers, plus a pattern for adding your own.
- **Source connectors and task queue** — pluggable ingestion adapters (Pub/Sub,
  ServiceNow polling, ...) that turn external events into queued tasks, with
  alert coalescing.
- **Two-way messaging and human oversight** — agents and operators can
  exchange threaded messages, start work from configured keywords, request
  clarifications, and approve or reject sensitive actions. Mattermost and Slack
  are supported through real-time provider integrations and a pluggable
  messaging interface.
- **Hindsight memory integration** — long-term recall and pattern reflection
  across past incidents, plus per-agent memory volumes backed up to object
  storage.
- **Knowledge Sources** — workflow-scoped access to immutable, commit-pinned
  source repositories, indexed into searchable code and symbol graphs.
- **Web control plane** — tasks, session replay, schedules, approvals,
  analytics, and platform catalogs (MCPs, connectors, memory, workflow-repo
  sync/versioning).
- **Kubernetes instances** from a workflow checkout: published, digest-pinned
  platform images in production and local source builds for development.
  Provider-neutral object storage supports `s3` and `gcs`.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full component
breakdown and a diagram of the request/task flow (connector or webhook →
task queue → session-manager → runtime container → MCP servers/message
bus/approvals → completion → memory sync → control-plane UI).

## Quick start

Start with your own configured workflow checkout, not a platform clone on the
production server. The [starter](examples/workflow-repo/) is a copy-and-fill
template; configure model access, encrypted credentials and the environment key
before running it.

```sh
cd /path/to/my-workflows
# Local: Rancher Desktop Kubernetes/Moby, kubectl, Helm, configured dev key.
uvx --from 'sage-run==1.0.1' sage-run up .
# Production: prepared k3s host and host-only production key.
uvx --from 'sage-run==1.0.1' sage-run deploy . \
  --host my-agent --env prod --ref main
```

See [Deployment and operations](docs/deployment.md) for first-time keys,
server preparation, local platform development, updates and recovery.
Production deploy currently targets single-node k3s over SSH. UI Deploy now,
selective service reload and scheduled full backups are **not implemented yet**;
the UI still offers workflow Sync. Legacy Compose tooling remains for
unmigrated instances and is not the recommended new-instance path.

## Documentation

| Doc | Covers |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Components and the request/task flow. |
| [docs/configuration.md](docs/configuration.md) | Base/prod overlays, named connections, encrypted secrets, deployment settings and service env reference. |
| [docs/connectors.md](docs/connectors.md) | Connector model, available connectors, and how to add one. |
| [docs/mcps.md](docs/mcps.md) | Core vs. integration MCP servers and their config. |
| [docs/memory.md](docs/memory.md) | Long-term memory (Hindsight), per-agent project memory, hooks, and weekly reflection. |
| [docs/deployment.md](docs/deployment.md) | First install, host prerequisites, local development, CLI/UI update limits, portability, backups and releases. |
| [docs/security.md](docs/security.md) | Permissions, sandbox/credential controls, bundle integrity, approvals, encrypted secrets. |
| [docs/workflow-authoring.md](docs/workflow-authoring.md) | How to build a workflow package (agent.yaml, skills, hooks) and its bundle. |

## Public and private boundary

This repository intentionally ships no company-specific workflows, Salesforce
policies, private connectors, customer memory-bank maps, or private
deployment overrides — those belong in a workflow repository. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Development

```sh
python -m pytest -q tests/unit          # unit suite, no infra required
python -m ruff check .                  # lint
python -m ruff format --check .         # format check
cd control-plane-ui && npm ci && npm run build   # control-plane UI
```

`make tests` runs the full unit + service (real Postgres) + runtime (real
Docker) suite; see the Makefile (`make help`) for every target.

## Roadmap and contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to contribute.

## License

Copyright 2026 Vishal Goel and SAGE Run contributors. SAGE Run's original code
and documentation are licensed under Apache License 2.0, unless otherwise
indicated. See [LICENSE](LICENSE) for the complete terms.

Third-party dependencies, bundled software, container base images, and service
images retain their own licenses and applicable terms. This includes the Claude
Agent SDK and Claude Code CLI; SAGE Run's Apache-2.0 license does not relicense
these components or waive their requirements.
