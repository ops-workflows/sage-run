# Workflow Authoring

A **workflow** is a self-contained package the platform assembles into a
runnable bundle and hands to an ephemeral runtime container. Start from
[examples/workflow-repo/workflows/example-workflow/](../examples/workflow-repo/workflows/example-workflow/)
and read its own `README.md` for a guided walkthrough; this document is the
schema/assembly reference.

## Package layout

```
workflows/<name>/
├── agent.yaml       # platform-level config: session, secrets, runtime, schedules
├── settings.json    # Claude Code native settings: permissions, sandbox
├── .mcp.json        # which MCP servers this workflow uses, and their auth headers
├── README.md        # optional, workflow-specific notes
├── CLAUDE.md         # optional, workflow-specific instructions (adds to shared CLAUDE.md)
├── agents/          # optional delegated subagent .md files
├── skills/          # optional SKILL.md reference packages
└── hooks/           # optional hook registration + executables
```

## `agent.yaml`

| Field | Type | Notes |
| --- | --- | --- |
| `name` | string, required | Kebab-case identifier, must match `^[a-z0-9][a-z0-9-]*[a-z0-9]$`. |
| `description` | string, required | Human-readable purpose. |
| `version` | string | Semantic version (`\d+\.\d+\.\d+`). |
| `session.max_turns` | int, default `50` | Turn ceiling before a forced stop (1–200). |
| `session.model` | string | A `model_profiles` name from `platform-config.yaml`, or a raw model name. |
| `env` | object | Non-secret `${VAR}` values available for expansion in `.mcp.json`. |
| `secrets.<NAME>.encrypted` | string, required | `ENC[age,<base64>]` — age-encrypted, decrypted at container launch. |
| `secrets.<NAME>.description` | string | Optional label. |
| `runtime.parallel_workers` | int, default `3` | Concurrent sessions for this workflow (1–10). |
| `runtime.heartbeat_interval_sec` | int, default `30` | Heartbeat frequency (10–120). |
| `runtime.lost_task_timeout_sec` | int, default `300` | Heartbeat-loss timeout before marking a task lost (60–3600). |
| `runtime.runtime_timeout_sec` | int, default `300` | Active-time ceiling per session attempt (60–7200). Time waiting for approvals or clarifications is excluded; those waits have their own deadlines, and waiting tasks do not count toward running-task limits. |
| `runtime.ask_user_question_reminder` | object | `enabled`, `min_turns`, `turn_budget_ratio`, `time_budget_ratio`, `recent_question_turn_window` — nudges the agent to ask before burning its turn/time budget. |
| `runtime.container_image` | string | Override the runtime image for this workflow. |
| `runtime.memory_volumes` | list[string] | Named memory volumes for this workflow. |
| `schedules[]` | array | `name`, `cron` (5-field APScheduler `CronTrigger` syntax), `prompt`, optional `message_channel`, `enabled` (default `true`). Numeric weekdays use APScheduler numbering: Monday is `0` through Sunday `6`. |
| `messaging.channels` | list[string] | Message-bus channel names or provider IDs this workflow listens on. Names are resolved to IDs visible to the configured bot at gateway startup. |
| `messaging.trigger_words` | list[string] | Prefixes that create a task in configured channels (for example, `@agent`). |
| `messaging.channel_policies` | object | Per-configured-channel human Mattermost invocation policy; omit the map or channel entry to allow all; each entry requires `allowed_usernames`, with an empty list denying all humans. |
| `messaging.rules[]` | array | Deterministic alert routes: `id`, `match` (`prefix` or a restricted `regex` without groups, alternation, or `+`), `trusted_senders`, `allow_bot`, `root_posts_only`, `preserve_full_body`, `priority`, `constraints`, and `dedupe`. |
| `messaging.rules[].constraints` | object | `environments`, 12-digit `accounts`, and `labels`. Each `labels` key must appear in the alert as `key=value` or `key: value`, and every occurrence must use an allowed value (case-insensitive), so label order does not matter. |
| `messaging.rules[].dedupe` | list (max 3) | Ordered duplicate policies. Each has `key` (one or more of `sender`, `alert.source`, `alert.identity`, `alert.account`, `label:<name>`), `window_sec` (1–86400), `statuses` (`active` for queued/running/waiting tasks, or `any`), and `action` (`merge` or `reply`). The workflow and rule are always part of the key, so different rules never deduplicate each other. A policy is skipped when any key part is absent from the alert. The first policy that finds a task created within its window absorbs the alert into that task; `merge` does so silently and `reply` also posts a duplicate notice linking the original thread and task in the alert's thread. Without a matching policy, a new task is created. |
| `knowledge.sources` | list[string] | Canonical Knowledge Source aliases this workflow may access; requires the `knowledge` MCP in `.mcp.json`. |

`agent.yaml` is validated against
[schemas/agent-yaml-schema.json](../schemas/agent-yaml-schema.json) —
the gateway's provisioner runs this validation automatically against every
discovered workflow, on every startup and every workflow-repo sync, for every
instance. Malformed `agent.yaml` files are logged as validation warnings; a
workflow repo doesn't need to ship or wire up the schema itself.

Platform-wide secrets (message bus tokens, etc.) belong in
`platform-config.yaml`'s `secrets:`, not here — `agent.yaml` secrets are for
this workflow's own external-system credentials.

### Mattermost human invocation

```yaml
messaging:
  channels: [operations, private-platform]
  trigger_words: ["@ops"]
  channel_policies:
    operations:
      allowed_usernames: [alice, bob]
    private-platform:
      allowed_usernames: []
```

Policies use the channel name or ID as written in `messaging.channels`, before
the gateway resolves channel aliases. Omit `channel_policies` or a channel entry
to retain allow-all behavior for humans who match the route. Each present
channel policy requires `allowed_usernames`; an explicit empty list denies all
human invocations in that channel. Usernames are trimmed, have one leading `@`
removed, and are compared
using case folding; duplicate normalized entries are invalid. A restricted
route denies a human with no username before hydrating a thread or creating a
task. The policy applies only to Mattermost human invocation, not Slack.

Bot and webhook routes still require their existing sender-trust checks;
adding a human allowlist neither trusts nor blocks a bot by itself. Task
clarification replies and approval actions keep their separate authorization
paths and do not inherit this invocation allowlist.

### Knowledge Source access

Hybrid MCP search and source-grant enforcement are implemented and locally
tested. Verify your endpoint configuration and an authorized tenant sync before
rollout; local tests do not certify provider relevance or production scale.

Register sources in the control-plane Knowledge Sources view or through
`POST /platform/knowledge-sources`. One registry supports the source/index
pairs `github`/`code_graph` and `confluence`/`hybrid_vector`; they are not
interchangeable. For example, create a Confluence source using the named
connection from [Configuration](configuration.md#confluence-connections):

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

Alternatively supply `source_config.root_pages` with numeric IDs or page URLs
on the selected connection's exact origin and base path. Do not supply both
root fields. Configured pages are always included; visible descendants are
included only when `include_descendants` is true (the default). Set it to false
to index exactly the selected pages. Optional `scrub_patterns` redact normalized
body content before indexing; the form accepts one regex per line. Rule changes
refetch selected bodies on the next sync and reuse unchanged chunks and vectors.
Titles and citation URLs are not scrubbed, and historical versions are not
retroactively changed. See [Configuration](configuration.md#knowledge-embeddings-and-retrieval)
for limits and body-only scope. Attachments and unsupported content types are not
indexed. GitHub requests instead use
`repository` (`organization/repository`), `credential_ref` naming a GitHub App
connection, `default_ref`, and optional `include_paths`/`exclude_paths`.
Legacy GitHub requests may omit `source_kind`; new requests should name both
kind fields. The API rejects cross-kind fields and unsupported kind pairs.

Run **Sync** or `POST /platform/knowledge-sources/{source_id}/sync` and wait
for a successful promoted version before using it. Source creation does not
make unindexed content available. Grant the canonical aliases in `agent.yaml`:

```yaml
knowledge:
  sources: [team-runbooks, example-service]
```

Declare the server in `.mcp.json` as well:

```json
{
  "mcpServers": {
    "knowledge": {
      "type": "http",
      "url": "http://mcp-knowledge:8108/mcp",
      "headers": {
        "X-Task-Workflow": "${TASK_WORKFLOW}",
        "X-Task-Id": "${TASK_ID}"
      }
    }
  }
}
```

Use `list_sources` to discover live capabilities. `search_knowledge` is for
`hybrid_search`; graph tools are for graph-capable sources. Tokens and provider
URLs never belong in workflow Knowledge MCP headers.

Roll out grants with `KNOWLEDGE_REQUIRE_EXPLICIT_SOURCE_GRANTS=false` first:
workflows declaring the Knowledge MCP but omitting `knowledge.sources` retain
legacy all-source access with a deprecation warning. A declared list restricts
access even in compatibility mode; `sources: []` grants nothing. Add explicit
aliases to every workflow, sync their releases, verify access, then set the
flag to `true` on both knowledge services. Strict mode grants no sources to a
workflow without a list; declaring aliases without the MCP is also insufficient.
The MCP enforces access, not prompts or UI visibility.

## `settings.json`

Native Claude Code settings: `permissions.deny` (glob patterns for blocked
tools), `sandbox.filesystem.allowWrite`/`denyRead`, and
`sandbox.credentials.envVars` (the runtime auto-populates this deny-list from
`agent.yaml` + `platform-config.yaml` secrets — see
[Security](security.md#sandbox-credential-deny-list)). Author explicit
allow-list entries here only for cases that must bypass the automatic deny.

## `.mcp.json`

```json
{
  "mcpServers": {
    "salesforce": {
      "type": "http",
      "url": "http://mcp-salesforce:8100/mcp",
      "headers": {
        "Authorization": "Bearer ${SALESFORCE_TOKEN}",
        "X-Salesforce-Instance-Url": "${SALESFORCE_INSTANCE_URL}"
      }
    }
  }
}
```

Each key is a server id (`message`, `memory`, `platform`, `salesforce`,
`jira`, `splunk`, `cloudwatch`, ...; see [MCP servers](mcps.md)). `${VAR}`
header values are expanded from `agent.yaml` `env`/`secrets`, workflow-level
env, platform `runtime_env`, and task-injection headers (`TASK_ID`,
`TASK_WORKFLOW`, `MESSAGE_CHANNEL`, `MESSAGE_CHANNEL_ID`,
`MESSAGE_THREAD_ID`).

## Skills and hooks

- **Skills** (`skills/<name>/SKILL.md`) are markdown knowledge packages an
  agent invokes via the `Skill` tool. The platform ships shared skills; a
  workflow can add its own, and a workflow-local skill wins over a shared one
  with the same name. Domain knowledge belongs in skills (or agent prompts, or
  Hindsight memory), not hard-coded into instructions.
- **Hooks** (`hooks/hooks.json`) register Claude Code lifecycle hooks for
  workflow-specific side effects. Shared hook executables (e.g. the Hindsight
  auto-recall/auto-retain hooks — see [Memory](memory.md)) are injected into
  the staged workspace at runtime; a workflow only owns the `hooks.json`
  registrations. Reference an injected hook with a relative command such as
  `./hooks/auto_recall_hook.py` since Claude runs from the staged workflow
  root. Keep programmatic side effects in hooks and multi-step reasoning in
  the skill or agent the hook invokes.

## Bundle assembly

`shared/lib/workflow_bundles.py::build_workflow_bundle` merges three layers,
each later layer overwriting (shadowing) the same path in the previous one:

1. **Platform core** — this repo's `CLAUDE.md`, `skills/`, `hooks/`.
2. **Workflow repo shared assets** — the workflow repo's own `CLAUDE.md`,
   `skills/`, `hooks/`.
3. **Workflow-local** — `workflows/<name>/{agent.yaml, settings.json,
   .mcp.json, README.md, CLAUDE.md, agents/, skills/, hooks/}`.

`CLAUDE.md` shadowing is a **whole-file replace, not a merge** — it's a plain
file copy (`shutil.copy2`), so a workflow repo's own root `CLAUDE.md` (layer 2)
entirely replaces the platform's, and a workflow-local `CLAUDE.md` (layer 3)
would replace both. If you want your own instructions *in addition to* the
platform's shared baseline, copy the platform's `CLAUDE.md` content into your
own and add to it — the example repo intentionally ships no root `CLAUDE.md`
so the platform's baseline applies unless you choose to override it. `skills/`
and `hooks/` are directories, so they overlay per-file instead: a same-named
file in a later layer replaces just that file, and everything else merges in.

Bundle build also scans every YAML/JSON file for plaintext-looking secrets
(see [Security](security.md#bundle-integrity)) and fails the build rather than
producing a bundle with a leaked value.

The output is a bundle directory plus `manifest.yaml`:

```yaml
bundle_version: 1
platform_version: "x.y.z"          # from this repo's pyproject.toml
workflow:
  name: my-workflow
  config_hash: "sha256:..."
repo:
  name: local
  url: ""
  ref: ""
  commit: ""
assets:
  core_sha: "sha256:..."
  team_sha: "sha256:..."
  workflow_sha: "sha256:..."
  sources:
    skills/shared-triage/SKILL.md: team
    skills/reflect/SKILL.md: core
    agents/coordinator.md: workflow
  shadowed:
    - {path: "skills/foo/SKILL.md", by: "workflow"}
created_at: "2025-01-15T10:30:00Z"
```

`platform_version` is what [the compatibility check](deployment.md#compatibility-policy)
compares against the running platform at sync time.

`assets.sources` records the final owner of each merged file: `core` for the
public platform, `team` for workflow-repo shared content, and `workflow` for
workflow-local content. Reflection uses this map to consider only `team` and
`workflow` instructions/skills; it never evaluates public `core` skills for
optimization.

## Building a bundle manually

```sh
python scripts/build_workflow_bundle.py my-workflow \
  --workflow-root /path/to/workflow-repo \
  --output-dir dist/bundles \
  --repo-name my-org/my-workflow-repo \
  --repo-url https://github.com/my-org/my-workflow-repo \
  --repo-ref main \
  --repo-commit "$(git rev-parse HEAD)"
```

In normal operation you don't need this — the sync pipeline
(`make bootstrap`'s first sync, `make sync`, or the control-plane UI's **Sync now**) builds
every discovered workflow's bundle automatically. This is mainly useful for
inspecting a bundle locally or debugging assembly/shadowing.
