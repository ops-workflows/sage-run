# Memory and Learning

Agents keep three distinct kinds of memory. They are separate systems with
separate lifecycles — don't conflate them.

| Tier | What it is | Lifetime | Backed by |
| --- | --- | --- | --- |
| Long-term memory | Cross-session incident knowledge and retrieval | Persists across all sessions | Hindsight service |
| Per-agent project memory | Claude Code's own project-memory files | Persists per workflow across sessions | Memory volume + object-storage backup |
| Prompt/context | `CLAUDE.md`, agents, skills | Changes only via repo edits | The bundle |

## Long-term memory (Hindsight)

Workflows retain findings, recall similar past incidents, and reflect on
patterns through the `memory` MCP server (see [MCP servers](mcps.md)). Two
shipped hooks make the common cases automatic so agents don't have to
remember to call the tools:

| Hook | Event | Behavior |
| --- | --- | --- |
| `hooks/auto_recall_hook.py` | `SessionStart` | Queries long-term memory for entries relevant to the coordinator task prompt and injects them as invisible `additionalContext` (labeled `[Long-term memory — similar past incidents]`), so the main agent starts with that context without an explicit `recall_similar` call. It skips subagents. |
| `hooks/retain_incident_hook.py` | `Stop` or `SubagentStop` | Writes a business-facing RCA record, a workflow-learning trace, or both according to `RETAIN_MEMORY_SCOPE`. This lets workflows retain a final coordinator synthesis separately from partial specialist traces. Never blocks the session. |

Retention ignores events other than `Stop` and `SubagentStop`. A coordinator
`Stop` can occur while a background specialist is still running; workflows can
set `RETAIN_RESULT_PREFIX` on their Stop command to require the final response
heading. Messages without that prefix are skipped without retention or a
timeline hook event. Leave it unset on specialist SubagentStop commands when
their completed findings should still be retained as learning traces.

Explicit tools remain available for targeted retrieval — e.g. a digest
workflow calls `recall_for_digest` over a recent window, and the weekly
reflection run calls `reflect_patterns`.

### Weekly reflection

The [`skills/reflect`](../skills/reflect/SKILL.md) skill drives a scheduled
weekly run: it calls `reflect_patterns` on the workflow-learning bank over the
last 7 days, looks for recurring investigation problems (tool loops, wrong or
weak parameters, missing/stale skills, signals that reliably led to
resolution), and — when warranted — proposes durable skill/instruction updates
as a GitHub PR through the `platform` MCP. It is deliberately about *workflow
behavior*, not business incident themes.

Hindsight reflection model calls have a 120-second timeout by default, configured
with `HINDSIGHT_API_REFLECT_LLM_TIMEOUT` in Compose or
`infrastructure.hindsight.reflectLlmTimeout` in Helm. The `reflect_patterns` MCP
tool waits up to 150 seconds for the Hindsight HTTP response; other memory tools
retain their 30-second HTTP timeout. Reflection can make multiple model calls
and retries, so the 150-second client timeout does not guarantee that every
reflection will complete.

### Memory banks

Each workflow routes to its own Hindsight banks so knowledge stays isolated.
Bank routing is configured in `platform-config.yaml` under `memory.banks`,
per kind (`business` and `learning`):

```yaml
memory:
  backend: hindsight
  banks:
    business:
      customer-support: support-history
      infrastructure-ops: infrastructure-history
    learning:
      customer-support: customer-support-learning
      infrastructure-ops: infrastructure-ops-learning
```

The `memory` MCP (backed by Hindsight) resolves the right bank server-side
from the `X-Task-Workflow` request header; a workflow without a mapping falls
back to the `incident-rca` (business) and `workflow-learning` (learning)
defaults.

The control-plane memory explorer lists only banks explicitly configured under
`memory.banks`, with their workflow mappings and live availability. Defaults and
historical banks that are not configured are not added to the explorer; their
stored Hindsight data is unchanged. To inspect a default bank, configure an
explicit mapping to it.

`memory.backend: hindsight` identifies the only supported long-term-memory
backend today. It does not replace `HINDSIGHT_URL`: gateway health/API calls,
the session manager's runtime environment, hooks, and `mcp-memory` all use
that URL to reach the Hindsight service.

## Per-agent project memory

This is Claude Code's native project memory, persisted across ephemeral
sessions:

- At runtime it appears as ordinary files under the workspace's project-memory
  directory; agents discover and update it with standard file tools (`Glob`,
  `Grep`, `Read`, `Write`) rather than a special memory tool. `MEMORY.md` is a
  convention, not a magic file — other note files can live beside it.
- session-manager backs project memory up to object storage after each session
  (`agent-memory/{agent}/latest.tar.gz` plus a timestamped version) and
  restores it before the next session. Compose uses a named Docker volume as a
  cache; Kubernetes Jobs use a task-local `emptyDir` at `/memory`, restored by
  an init helper and uploaded by a completion helper, so no Kubernetes memory
  PVC is required.
- `MEMORY_SYNC_MODE` controls the local service path (`docker_volume` or
  `filesystem`). Kubernetes runtime Jobs always use the object-store helper
  flow described above — see [Configuration](configuration.md).

Housekeeping prunes old agent-memory versions and expired learning-memory per
the retention settings in [Configuration](configuration.md), while leaving
business RCA memory intact.

## Prompt/context

`CLAUDE.md`, `agents/`, and `skills/` are curated, repo-authored knowledge
merged into the bundle — not memory-volume state. They change only through
repository edits or PRs (including the reflection PRs above). See
[Workflow authoring](workflow-authoring.md) for how these are assembled and
how shared vs. workflow-local assets take precedence.
