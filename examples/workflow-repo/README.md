# Example Workflow Repo

This directory mirrors the exact structure a **workflow repo** must have to
work with SAGE Run. Copy it (or just the pieces you need) to
bootstrap your own workflow repo:

```sh
cp -r examples/workflow-repo /path/to/my-workflow-repo
```

Keep `sage-run` checked out beside the copied repository, then run `make lint`
to check Python, JSON/YAML syntax, and workflow package schemas. Run
`make format` to apply Ruff fixes and Python formatting. Set `SAGE_RUN_DIR` when
the platform checkout is elsewhere.

See [docs/workflow-authoring.md](../../docs/workflow-authoring.md) for the
full package/bundle reference, [docs/configuration.md](../../docs/configuration.md)
for the config-layer model, and the platform root
[README.md](../../README.md) for how to point a running platform at your repo.

## What's here

```
examples/workflow-repo/
├── platform-config.yaml           # instance config template (mcps, connectors,
│                                   # message bus, memory banks, model profiles)
├── litellm.config.example.yaml    # model-gateway (LiteLLM) config template
├── connectors/
│   ├── README.md                  # how to enable/configure/add a connector
│   └── custom-connector-example/  # minimal skeleton to copy and adapt
├── mcps/
│   ├── README.md                  # how to enable/configure/add an MCP server
│   └── custom-mcp-example/        # minimal FastMCP skeleton to copy and adapt
├── skills/
│   ├── README.md                  # repo-wide shared skills (precedence vs. platform/workflow-local)
│   └── custom-skill-example/      # minimal skeleton to copy and adapt
├── deploy/
│   ├── README.md                  # the "convenience" sibling-checkout deploy mode
│   ├── docker-compose.override.yml
│   └── k8s-values.yaml
└── workflows/
    └── example-workflow/          # copy-and-fill workflow package template
        ├── agent.yaml             # platform-only config: secrets, runtime, schedules
        ├── settings.json          # Claude-native permissions + sandbox
        ├── .mcp.json              # MCP servers this workflow uses
        ├── agents/                # delegated agent prompts
        ├── skills/                # domain-knowledge packages
        └── hooks/                 # hook registrations
```

`workflows/example-workflow/` is a **copy-and-fill template** — its
`agent.yaml`, `.mcp.json`, `settings.json`, and `agents/*.md` still contain
`{PLACEHOLDER}` values (`{WORKFLOW_NAME}`, `{MAIN_AGENT}`, `{ROLE}`, ...). It
is not meant to run as-is; see its own
[README.md](workflows/example-workflow/README.md) for the fill-in steps. Its
`settings.json` demonstrates a `permissions.ask` entry (approval-gated tool
calls) and a populated `sandbox.network.allowedDomains` matching the MCP
servers wired in its `.mcp.json` — customize both for the servers your own
workflow actually uses. Adding integrations (Salesforce, Splunk, connectors,
...) shipped by the platform is documented in
[docs/mcps.md](../../docs/mcps.md) and [docs/connectors.md](../../docs/connectors.md);
adding your own custom MCP server or connector is documented in
[mcps/README.md](mcps/README.md) and [connectors/README.md](connectors/README.md)
in this example.

This example intentionally ships no root `CLAUDE.md`. If you add one to your
own workflow repo, it **replaces** (not merges with) the platform's shared
`CLAUDE.md` in the bundle — see
[Bundle assembly](../../docs/workflow-authoring.md#bundle-assembly).

## Knowledge Sources and Invocation Policy

The starter declares the Knowledge MCP and grants the `team-runbooks` source
alias. Replace that alias with registered sources, or use `sources: []` to
grant nothing. The service-account Confluence connection is instance-owned:
replace the `team-wiki` URL/email and age-encrypted token in
`platform-config.yaml`, never in workflow MCP headers.

Before indexing, configure a real embedding model and its verified positive
output dimension on both the indexer and Knowledge MCP. The examples deliberately
leave dimensions at `0` and reranking disabled. Compose reuses Hindsight's
embedding endpoint/model from `deploy/compose.env.example`; Helm uses the matching
`knowledge.embeddings` overrides in `deploy/k8s-values.yaml`. Both use the existing
bootstrap `LLM_API_KEY` unless a dedicated encrypted key is configured.

Register this example through the Knowledge Sources view or
`POST /platform/knowledge-sources`, replacing the page ID with an accessible page:

```json
{
    "source_kind": "confluence",
    "index_kind": "hybrid_vector",
    "canonical_alias": "team-runbooks",
    "display_name": "Team Runbooks",
    "credential_ref": "team-wiki",
    "source_config": {
        "root_page_ids": ["123456"],
        "include_descendants": true,
        "scrub_patterns": ["(?i)api[_-]?key\\s*[:=]\\s*\\S+"],
        "body_format": "storage",
        "lexical_config": "simple"
    },
    "sync_policy": {"interval_sec": 3600},
    "enabled": true
}
```

Run Sync and wait for successful promotion before retrieval. Set
`include_descendants` to false to index only selected pages. The source form
accepts one scrub regex per line; rules affect normalized bodies, not titles,
hierarchy names, or citation URLs. Changed rules refetch selected bodies on the
next sync and reuse unchanged chunks/vectors; they do not purge historical data.
See [Configuration](../../docs/configuration.md#knowledge-embeddings-and-retrieval)
for regex limits, retention, and deployment precedence.

The workflow template also contains a commented Mattermost `channel_policies`
example: omitted policies allow otherwise-matching humans, named usernames
restrict invocation, and an empty list denies humans on that channel. Existing
bot/webhook trust and reply/approval authorization are separate. Message-created
tasks record the sender in the generic `initiator` field; schedules and Pub/Sub
leave it empty, and coalescing preserves the original initiator.

## `agent.yaml` validation

The platform validates every discovered `agent.yaml` against
[schemas/agent-yaml-schema.json](../../schemas/agent-yaml-schema.json)
automatically — the gateway's provisioner runs this on every startup and every
workflow-repo sync, for every instance. A malformed `agent.yaml` is logged as
a validation warning; nothing in your workflow repo needs to ship or wire up
the schema itself.
