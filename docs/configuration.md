# Configuration

SAGE Run configuration is split into three layers so the workflow-repo
pointer is never circular (you shouldn't need the repo's own config file to
know how to fetch the repo).

| Layer | Owner | Committed? | Holds |
| --- | --- | --- | --- |
| 1. Bootstrap / infra | Operator | No (generated) | Workflow-repo pointer, `AGE_IDENTITY`, one `LLM_API_KEY`, and direct-container secrets (Postgres/object storage). A one-time PAT may be entered for the initial clone but is never written to an artifact. |
| 2. Instance config | Workflow repo | Yes (secrets age-encrypted) | `platform-config.yaml`: GitHub App connections, message bus, MCPs, connectors, memory banks, model profiles, workflow secrets. |
| 3. Workflow packages | Workflow repo | Yes | `workflows/`, shared `skills/`/`hooks/`, custom `mcps/`/`connectors/`. |

Boot sequence: read layer 1 → clone/sync the workflow repo at the pinned ref →
point `PLATFORM_CONFIG_FILE` at the repo's `platform-config.yaml` → load layer
2 → build bundles → run. See [Deployment](deployment.md) for how layer 1 is
generated (`make bootstrap`) and how sync/versioning work.

## Layer 1 — bootstrap / infra settings

These are environment variables read by `shared/lib/config.py`'s `Settings`
class. Env vars always take precedence; unset ones may be overlaid from the
workflow repo's `platform-config.yaml` `config:` section once it has been
fetched (see [Loading order](#loading-order) below) — except
`WORKFLOW_REPO_URL`/`REF`, which are bootstrap-only and never read from
repo-owned config.

### Workflow repository

| Env var | Default | Purpose |
| --- | --- | --- |
| `WORKFLOW_REPO_SOURCE` | `local` | `local` reads the mounted checkout; `remote` fetches the configured Git ref during Sync. |
| `WORKFLOW_REPO_URL` | `""` | Canonical Git URL for a remote source. A local checkout may also set it for GitHub-backed reflection actions. |
| `WORKFLOW_REPO_REF` | `""` | Default Git branch, tag, or SHA for a remote Sync. A UI pin overrides it until changed. |
| `WORKFLOW_REPO_LOCAL_PATH` | `/app/workflows` | Container-side remote clone location or local checkout mount. Compose uses this default. |
| `WORKFLOW_REPO_PATHS` | `""` | Advanced, `os.pathsep`-separated additional workflow roots, primarily for Kubernetes deployments with separately mounted storage. |
| `REPO_PATH` | `""` | Path to a checked-out/mounted workflow repo root. |
| `HOST_REPO_ROOT` | `""` | Host-side bind-mount path used by the Compose convenience override. |

Compose mounts the single workflow checkout at `/app/workflows`, so it does not
set `WORKFLOW_ROOT`, `WORKFLOW_REPO_PATHS`, or `WORKFLOW_REPO_LOCAL_PATH`.
Operators configure the host-side `HOST_WORKFLOW_REPO_PATH` in the generated
`compose.env`; Compose maps it to that fixed container path.

### GitHub App connections

Runtime GitHub access is app-only. Define named installations under
`github.connections` in `platform-config.yaml`. Each connection contains
`web_base_url`, `api_base_url`, `app_id`, `installation_id`, and a
`private_key_secret` reference into the age-encrypted `secrets` mapping. Set
`github.workflow_repo_connection` to the connection used for workflow sync,
version lookup, and reflection PRs.

GitHub.com and each GHES instance require separate GitHub Apps and keys. A
connection represents one App installation rather than only a domain, because
one host may contain multiple installations with different repository access.
Knowledge Sources select a connection by setting `credential_ref` to its exact
name, such as `github-public` or `github-enterprise`; a public source can leave it
empty. GitHub MCP repository aliases use the same connection names.

Grant each App only the repository permissions required by its installation:
`Contents: read and write` for sync plus reflection branches/commits,
`Issues: read and write` for GitHub MCP issue operations, `Pull requests: read
and write` for reflection PRs, and the automatically granted `Metadata: read`.
Do not grant `Workflows` unless the allowed reflection paths are intentionally
expanded to `.github/workflows`.

### Confluence connections

Define named Confluence connections in `platform-config.yaml`. Set
`deployment` to `cloud` (the default) or `data_center`:

```yaml
confluence:
  connections:
    team-wiki:
      base_url: https://example.atlassian.net/wiki
      auth_type: basic
      username: knowledge-reader@example.com
      token_secret: CONFLUENCE_TEAM_TOKEN
    corporate-wiki:
      deployment: data_center
      base_url: https://confluence.example.com/confluence
      auth_type: bearer
      token_secret: CONFLUENCE_DC_TOKEN
secrets:
  CONFLUENCE_TEAM_TOKEN:
    encrypted: "ENC[age,...]"
  CONFLUENCE_DC_TOKEN:
    encrypted: "ENC[age,...]"
```

`credential_ref` on a Confluence source is the exact connection name, not a
token or URL. Cloud connections require a base URL ending in `/wiki` and basic
authentication with the service account's email and API token. Data Center
connections keep the configured context path (for example `/confluence`) and
default to `auth_type: bearer` with a personal access token; `auth_type: basic`
with a `username` is also accepted. Keep tokens age-encrypted; the indexer
resolves them using the existing `AGE_IDENTITY` bootstrap flow. Use HTTPS; HTTP
is accepted only for loopback tests. Connection discovery exposes names and
base URLs, never tokens. Grant the service account read access only to the
pages intended for indexing. The indexed snapshot reflects that account's
access, not the requesting Mattermost user's Confluence permissions. Cloud uses
the REST v2 page APIs; Data Center uses REST v1 content APIs and walks child
pages from each configured root.

### Platform config file

| Env var | Default | Purpose |
| --- | --- | --- |
| `PLATFORM_CONFIG_FILE` | `/app/platform-config.yaml` | Path to the instance's `platform-config.yaml`, read after the workflow repo is fetched. |

### Database

| Env var | Default | Purpose |
| --- | --- | --- |
| `PG_HOST` | `postgres` | Postgres host. |
| `PG_PORT` | `5432` | Postgres port. |
| `PG_DB` | `sage_run` | Database name. |
| `PG_USER` | `sage_run` | Database user. |
| `PG_PASSWORD` | `""` | Database password. |

### Object storage

One provider-neutral abstraction (`shared/lib/object_store.py`) backs both
workflow bundles and agent-memory backups across supported deployment targets.

| Env var | Default | Purpose |
| --- | --- | --- |
| `OBJECT_STORE_PROVIDER` | `s3` | `s3` (MinIO, AWS S3, or any S3-compatible endpoint) or `gcs` (Google Cloud Storage). |
| `OBJECT_STORE_ENDPOINT` | `minio:9000` | Endpoint host:port (`s3` only). |
| `OBJECT_STORE_ACCESS_KEY` | `sage_run` | Access key (`s3` only). |
| `OBJECT_STORE_SECRET_KEY` | `""` | Secret key (`s3` only). |
| `OBJECT_STORE_SECURE` | `False` | Use TLS against the endpoint (`s3` only). |
| `OBJECT_STORE_GCP_PROJECT` | `""` | GCS project id; optional, the client can infer it from ADC. |

### Runtime bundles

| Env var | Default | Purpose |
| --- | --- | --- |
| `RUNTIME_BUNDLE_ROOT` | `""` | Ephemeral local build/cache path for workflow bundles and synced config snapshots. |
| `RUNTIME_BUNDLE_URI_TEMPLATE` | `""` | Static bundle URI template, e.g. `gs://bucket/bundles/{workflow}.tar.gz`. |
| `RUNTIME_BUNDLE_OBJECT_STORE_BUCKET` | `""` | Canonical bucket for immutable workflow release manifests, config snapshots, and bundles; runtimes receive presigned HTTPS bundle URLs. |
| `RUNTIME_BUNDLE_PRESIGNED_URL_EXPIRES_SEC` | `3600` | Presigned URL validity window. |

### Runtime launcher and memory sync

| Env var | Default | Purpose |
| --- | --- | --- |
| `RUNTIME_LAUNCHER` | `docker` | `docker` or `kubernetes`. |
| `MEMORY_SYNC_MODE` | `docker_volume` | `docker_volume` for Compose or `filesystem` for a mounted memory path. Kubernetes Jobs use task-local `/memory` plus object-store restore/upload. |
| `MEMORY_FILESYSTEM_ROOT` | `/memory` | Container path agent memory volumes mount at. |
| `CLAUDE_CODE_THINKING_MODE` | `default` | `default`/`on` leaves provider thinking behavior unchanged; `off`/`disabled` passes Claude Code's explicit thinking-disable switch. Provider support varies. |
| `KUBERNETES_MEMORY_HELPER_IMAGE` | `""` | Image containing `session_manager.memory_sync`; Helm defaults it to the session-manager image. |
| `KUBERNETES_BOOTSTRAP_SECRET` | `""` | Bootstrap Secret name referenced by Kubernetes memory helper Jobs for object-store credentials. Helm sets it from `bootstrap.existingSecret`. |
| `KUBERNETES_NAMESPACE` | `default` | Kubernetes launcher namespace. |
| `SANDBOX_MODE` | `""` | Sandbox profile for agent sessions: `local` (alias `macos`), `ci` (alias `gha`) or `gvisor`. Unknown values fail task launch. |
| `GVISOR_DOCKER_RUNTIME` | `runsc-pr13532` | Docker runtime name used by the `gvisor` profile. |
| `KUBERNETES_RUNTIME_CLASS` | `gvisor` | RuntimeClass used by the `gvisor` profile for Kubernetes session Jobs. |
| `KUBERNETES_RUNTIME_UID` | `1000` | Non-root UID (group 0) for Kubernetes session pods, including memory helpers. |
| `KUBERNETES_RUNTIME_TTL_SEC` | `86400` | `ttlSecondsAfterFinished` for session Jobs; `0` disables it. |

### Gateway / UI

| Env var | Default | Purpose |
| --- | --- | --- |
| `GATEWAY_HOST` | `0.0.0.0` | Gateway bind address. |
| `GATEWAY_PORT` | `8080` | Gateway bind port. |
| `GATEWAY_EVENT_URL` | `http://gateway:8080/events` | Event-collector URL the runtime posts to. |
| `GATEWAY_PUBLIC_BASE_URL` | `""` | Publicly reachable gateway URL for Mattermost approval-action callbacks. |
| `CONTROL_PLANE_UI_URL` | `""` | Public control-plane UI URL. |

### Task admission

| Env var | Default | Purpose |
| --- | --- | --- |
| `PLATFORM_MAX_RUNNING_TASKS` | `3` | Maximum concurrently admitted parent tasks across all workflows. Tasks are selected by `resume_pending`, workflow priority, then FIFO order. This does not cap parallel subagent or model calls inside a running task. |

Set each workflow's `runtime.priority` in `agent.yaml` to `high`, `medium`, or
`low` (or the equivalent `1`, `2`, or `3`). Equal-priority workflows retain FIFO
queue order. `runtime.parallel_workers` remains the per-workflow cap; platform
and workflow caps must both permit a task before it starts.

### Workflow concurrency and priority

Configure the platform-wide ceiling in the workflow repository's
`platform-config.yaml`:

```yaml
config:
  PLATFORM_MAX_RUNNING_TASKS: "3"
```

Configure each workflow in its `agent.yaml`:

```yaml
runtime:
  parallel_workers: 1
  priority: high
```

`PLATFORM_MAX_RUNNING_TASKS` is the maximum number of concurrently running
parent tasks across the entire platform. `parallel_workers` is the maximum for
one workflow. A task starts only when both caps allow it.

`priority` controls selection among eligible queued tasks: `high` runs before
`medium`, which runs before `low`; use `1`, `2`, and `3` as equivalent numeric
forms. Tasks at the same priority retain FIFO order. A workflow at its
`parallel_workers` cap is skipped so the next eligible workflow can run.

These controls govern parent task admission only. A parent task may still launch
parallel subagents, so choose the platform cap below the available model-call
capacity when workflows use subagent fan-out.

### Message bus

Configure the provider only in `platform-config.yaml`:

```yaml
message_bus:
  provider: mattermost # mattermost or slack
  api_url: https://mattermost.example.com
  team_name: operations
  bot_token_secret: message_bus_bot_token
  app_token_secret: message_bus_app_token # Slack Socket Mode only
  action_callback_secret: message_action_callback_secret # Mattermost actions only

secrets:
  message_bus_bot_token:
    encrypted: "ENC[age,...]"
  message_bus_app_token:
    encrypted: "ENC[age,...]"
  message_action_callback_secret:
    encrypted: "ENC[age,...]"
```

Use exactly one of these provider mappings:

```yaml
# Mattermost
message_bus:
  provider: mattermost
  api_url: https://mattermost.example.com
  team_name: operations
  bot_token_secret: message_bus_bot_token
  action_callback_secret: message_action_callback_secret
```

```yaml
# Slack
message_bus:
  provider: slack
  api_url: https://slack.com/api
  bot_token_secret: message_bus_bot_token
  app_token_secret: message_bus_app_token
```

Mattermost needs a bot token, API URL, and an optional `team_name` when channel
names are ambiguous. New posts arrive through `/api/v4/websocket`; outbound
acknowledgements, results, questions, approval cards, and card updates use the
Mattermost REST API. Its interactive approval buttons call
`GATEWAY_PUBLIC_BASE_URL/webhooks/message/actions/approval`; configure an
`action_callback_secret` for that internal callback. Remove any old Mattermost
outgoing-webhook integration.

Slack needs a bot token with `chat:write`, `channels:read`, `groups:read`,
`channels:history`, and `groups:history` scopes (plus access to each configured
channel), and a Socket Mode app token. Enable message events and interactive
components in the Slack app. Message events and approval actions arrive through
Socket Mode; outbound messages and thread-history reads use the Slack Web API.
Slack does not use `action_callback_secret`.

Message-bus settings and secrets are never read from `MESSAGE_BUS_*`
environment variables. The Gateway opens one listener for the configured
`message_bus.provider`; no
separate message connector service is deployed. Mattermost uses
`/api/v4/websocket` for inbound posts and retains the Gateway HTTP
approval-action callback. Slack uses Socket Mode for both message events and
approval actions. The current deployment runs one gateway replica, because a
second replica would create a second live provider consumer.

Inbound provider messages are event-driven, not polled. The runtime does poll
Gateway APIs while waiting for an approval or human answer, but the Gateway
receives the provider event and persists it first.

`message_action_callback_secret` is an internal, independently generated
gateway secret. Mattermost receives it only inside the approval button context
and returns it to the approval callback. It is not a Mattermost token and is
not used for WebSocket authentication.

For `AskUserQuestion`, the runtime asks the gateway to post the prompt. When a
provider inbound message arrives in the same provider/thread, gateway ingress
persists a `user_question_reply` session event. The runtime polls the Gateway
reply API for that event; it never polls Mattermost or Slack threads directly.

Each workflow declares `messaging.channels` and `messaging.trigger_words` in
its `agent.yaml`. A channel may be its provider name (for example,
`operations`) or its provider ID. At gateway startup, configured names are
resolved once to IDs visible to the bot, so incoming provider events route
reliably even when they carry only a channel ID. Give the Slack bot access to
the channel and the `conversations.list` scopes required to enumerate it;
configure an explicit channel ID when the channel cannot be listed.
Matching is case-insensitive and an inbound message must start with a configured
trigger word. Omit neither `messaging.channels` nor `messaging.trigger_words`:
without a matching channel and prefix, no task is created.

For a triggering reply inside an existing Mattermost or Slack thread
(`message_id != thread_id`), routing and sender/alert trust checks run against
the triggering reply first. Only after it passes does the Gateway read thread
history through the provider API and build the task prompt from the latest 10
messages, oldest to newest, including the triggering reply. The trigger prefix
is removed from that final request. Root posts keep the existing single-message
behavior. If history retrieval fails or the bot lacks history permission, task
creation stops rather than running without the required conversation context.

Mattermost hydration uses `GET /api/v4/posts/{root_id}/thread` with the
triggering post's `fromPost` and `fromCreateAt` cursor values; the bot must be
able to read the channel and thread. Slack hydration uses
`conversations.replies`; the bot must be a channel member and have the history
scope appropriate to that channel type (`channels:history` or
`groups:history`). Both providers apply the same latest-10 prompt limit and
record the included count as task metadata under `thread_context_count`.

New tasks created from inbound messages also store the captured sender username
in the nullable, source-neutral `initiator` column. Task list/detail responses
expose it, and task details display "Initiated By" when populated. Generic task
producers can supply `initiator` through `create_task` or `POST /api/tasks`.
Schedules and Pub/Sub leave it null; existing tasks are not backfilled, and
replies, approvals, and alert coalescing do not replace the original initiator.

Mattermost workflows may set `messaging.channel_policies.<configured-channel>`
with `allowed_usernames`. Omit the map or a channel entry to allow all humans
who otherwise match the route; an explicit `allowed_usernames: []` denies all
human invocations on that channel. Matching trims whitespace, removes a leading
`@`, and compares case-insensitively; restricted routes reject missing usernames
before thread hydration or task creation. This policy applies to human
Mattermost invocation only. Existing bot/webhook trust, Slack routing,
clarification replies, and approval authorization are unchanged. See
[Workflow Authoring](workflow-authoring.md#mattermost-human-invocation) for an
example; replies and approvals require separate authorization policy.

### Hindsight memory

| Env var | Default | Purpose |
| --- | --- | --- |
| `HINDSIGHT_URL` | `http://hindsight:8888` | Hindsight service base URL. |
| `HINDSIGHT_REQUEST_RETRIES` | `3` | Retry count for Hindsight API calls. |
| `HINDSIGHT_REQUEST_RETRY_BACKOFF_SEC` | `0.5` | Initial retry backoff. |

### Knowledge embeddings and retrieval

Confluence source configuration accepts `include_descendants` (boolean, default
`true`) and `scrub_patterns` (ordered string list, default empty). The source
form exposes "Include subpages" and a multiline regex field. Uncheck the former
to index exactly the configured pages. Each nonblank regex line is one rule;
all matches are replaced with `[REDACTED]` in listed order. Matching is
case-sensitive unless the pattern includes inline flags, such as `(?i)` or
`(?s)` for matching across newlines. Patterns use the Python `regex` engine's
VERSION0 syntax. At most 100 patterns of 2,000 characters each are accepted;
invalid patterns fail source validation with their rule line number.

Rules scrub normalized body text, including body-derived headings, tables,
code, and links, before hashing, persistence, chunking, keyword indexing, and
embeddings. Page titles, page hierarchy names, and canonical citation URLs are
outside this body-only scope. Each page body has a one-second execution budget;
exceeding it fails synchronization, never bypasses redaction.

The last successful index records the ordered rule signature in version stats
and snapshot identity. A changed signature forces fresh bodies for every
selected page on the next sync, even when Confluence page versions are unchanged.
Existing content/chunk hashes still reuse unchanged vectors. The previous index
continues serving until success. Historical content is not retroactively
scrubbed; normal version-count housekeeping prunes unreferenced revisions and
chunks as history exceeds retention. Regexes reduce exposure but do not guarantee
that every secret or sensitive value is detected.

Hybrid indexing, MCP search, and source-grant enforcement are implemented and
covered by local PostgreSQL, provider-fake, and runtime tests. Before rollout,
verify your endpoint configuration, run an authorized tenant sync, and check
retrieval relevance. Local tests do not certify a live provider or production
scale.

Knowledge indexing and query embedding call the OpenAI-compatible model
endpoint directly at `<base_url>/embeddings`; Hindsight is not an embedding
proxy. The worker and Knowledge MCP must use the same model and dimensions.
GitHub sources retain `code_graph` indexing; Confluence sources use
`hybrid_vector` with pgvector dense search and PostgreSQL full-text search,
fused using reciprocal rank fusion (RRF), not BM25.

| Env var | Settings default | Purpose |
| --- | --- | --- |
| `KNOWLEDGE_EMBEDDINGS_OPENAI_BASE_URL` | `http://model-gateway:1235/v1` | OpenAI-compatible base URL, including `/v1` when required. |
| `KNOWLEDGE_EMBEDDINGS_OPENAI_MODEL` | `""` | Actual embedding model or provider alias, not a chat model. |
| `KNOWLEDGE_EMBEDDINGS_OPENAI_API_KEY` | `""` | Optional dedicated key; the embedding client falls back to bootstrap `LLM_API_KEY`. |
| `KNOWLEDGE_EMBEDDINGS_DIMENSIONS` | `0` | Required positive output dimension for hybrid sources; `0` means unconfigured, not auto-detection. |
| `KNOWLEDGE_EMBEDDINGS_BATCH_SIZE` | `16` | Bounded document embedding batch size. |
| `KNOWLEDGE_EMBEDDINGS_TIMEOUT_SEC` | `60` | Embedding request timeout in seconds. |
| `KNOWLEDGE_RERANK_ENABLED` | `false` | Opt into reranking; leave disabled until measured on your corpus. |
| `KNOWLEDGE_RERANK_BASE_URL` | `http://model-gateway:1235` | Cohere-compatible base URL; retrieval appends `/rerank`. |
| `KNOWLEDGE_RERANK_MODEL` | `""` | Reranker alias when enabled. |
| `KNOWLEDGE_RERANK_TIMEOUT_SEC` | `3` | Rerank request timeout in seconds. |
| `KNOWLEDGE_RERANK_CANDIDATES` | `20` | Maximum fused candidates sent to the reranker. |
| `KNOWLEDGE_REQUIRE_EXPLICIT_SOURCE_GRANTS` | `false` | Require each workflow to declare `knowledge.sources` when enabled. |

Compose passes these variables to both `knowledge-indexer` and `mcp-knowledge`.
Unless explicitly overridden, its embedding URL/model are taken from
`HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL` and
`HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL`, using the existing model-gateway URL
and placeholder embedding alias when those variables are absent. The API key
falls back to bootstrap `LLM_API_KEY`. Set `KNOWLEDGE_EMBEDDINGS_DIMENSIONS`
to the model's verified output size before enabling a hybrid source; Compose
deliberately defaults it to `0`. Do not guess a dimension or assume the
placeholder model exists. These settings do not change Hindsight's defaults.

Helm exposes optional overrides under `knowledge.embeddings` (`openaiBaseUrl`,
`openaiModel`, `dimensions`, `batchSize`, `timeoutSec`), `knowledge.rerank`
(`enabled`, `baseUrl`, `model`, `timeoutSec`, `candidates`), and
`knowledge.requireExplicitSourceGrants`. Null values emit no override, allowing
mounted platform config to supply the setting. `platformEnv` wins over these
chart settings without duplicate environment entries. Both knowledge workloads
continue to receive `LLM_API_KEY` through `bootstrap.existingSecret`/`envFrom`;
do not place API keys in Helm values or print rendered secret data.

Mounted `platform-config.yaml` supports the following canonical snake_case
configuration. These names are separate from Helm's camelCase values. Replace
the model aliases, dimension, and encrypted key with values verified for your
endpoint; `768` here is illustrative, not a default or auto-detected value.

```yaml
knowledge:
  embeddings:
    provider: openai_compatible
    base_url: http://model-gateway:1235/v1
    model: embedding-model
    dimensions: 768
    api_key_secret: knowledge_embedding_key
    batch_size: 16
    timeout_sec: 60
  rerank:
    enabled: false
    base_url: http://model-gateway:1235
    model: reranker-model
    timeout_sec: 3
    candidates: 20
  require_explicit_source_grants: false

secrets:
  knowledge_embedding_key:
    encrypted: "ENC[age,...]"
```

The loader maps `embeddings.base_url` and `embeddings.model` to
`KNOWLEDGE_EMBEDDINGS_OPENAI_BASE_URL` and `KNOWLEDGE_EMBEDDINGS_OPENAI_MODEL`;
`dimensions`, `batch_size`, and `timeout_sec` map to the corresponding
`KNOWLEDGE_EMBEDDINGS_*` settings. Each `rerank` option maps to
`KNOWLEDGE_RERANK_*`, and `require_explicit_source_grants` maps to
`KNOWLEDGE_REQUIRE_EXPLICIT_SOURCE_GRANTS`.

All sections and fields are optional. Omitted or null fields preserve Settings
defaults; specifying only `provider` adds no environment override. The only
supported embedding provider is `openai_compatible` (case and surrounding
whitespace are normalized). Boolean flags must be YAML booleans; dimensions,
batch size, and candidate count must be integers. Dimensions may be `0` while
unconfigured; batch size, candidate count, and finite numeric timeouts must be
positive. Unknown keys, camelCase platform options, malformed values, and
unsupported providers raise a configuration error without including supplied
values. Do not put an inline `api_key` in this section.

`api_key_secret` references a named encrypted entry under `secrets:`. With an
age identity, the loader decrypts only that referenced embedding key and maps
it to `KNOWLEDGE_EMBEDDINGS_OPENAI_API_KEY`, never to the reference name as a
generic environment variable. A missing or malformed secret entry raises a
safe error when decryption is needed. Without an identity, non-secret knowledge
options still load and no secrets are decrypted; the dedicated key remains
unset so the existing caller-owned `LLM_API_KEY` fallback remains available.
The dedicated key is excluded from Settings representations.

Precedence is non-empty process environment, then explicit raw `config:`
environment entries, then typed `knowledge:` options, then Settings defaults.
For example, `config: {KNOWLEDGE_EMBEDDINGS_BATCH_SIZE: 8}` overrides the typed
batch size above. An explicit `config:` entry for the dedicated API key or a
non-empty process environment key skips decryption of the referenced key.
Compose supplies defaults as environment values, so change its input variables
to override those defaults rather than expecting mounted YAML to replace them.
Use a positive verified dimension and identical settings on both services.

Document embedding failures prevent promotion. Query embedding failures may
fall back to lexical retrieval; reranker failures retain the fused order.
Neither a provider benchmark nor production retrieval-quality certification
is implied by deployment wiring or unit tests.

### Housekeeping / retention

| Env var | Default | Purpose |
| --- | --- | --- |
| `HOUSEKEEPING_ENABLED` | `True` | Enable the periodic background job. |
| `HOUSEKEEPING_INTERVAL_SEC` | `3600` | How often it runs. |
| `BACKGROUND_JOB_RUN_HISTORY_LIMIT` | `5` | How many of its own past runs to keep. |
| `TASK_ARCHIVE_AFTER_DAYS` | `14` | Archive completed tasks after N days. |
| `TASK_DELETE_AFTER_DAYS` | `0` | Delete archived tasks after N days (`0` = never). |
| `LEARNING_MEMORY_RETENTION_DAYS` | `30` | Hindsight learning-bank retention. |
| `AGENT_MEMORY_VERSIONS_TO_KEEP` | `10` | Versioned agent-memory snapshots to retain per workflow. |
| `AGENT_MEMORY_RETENTION_DAYS` | `90` | Delete agent-memory snapshots older than N days. |

### Secrets (age encryption)

| Env var | Default | Purpose |
| --- | --- | --- |
| `AGE_PUBLIC_KEY` | `""` | Recipient public key (`age1...`) used to encrypt new secrets. Safe to commit. |
| `AGE_IDENTITY` | `""` | Private key used to decrypt secrets at container-spawn time. Bootstrap-only, never committed. Accepts an armored key string or `file:/path/to/key.txt`. |

### LLM API key

`LLM_API_KEY` is operator-owned and lives only in the bootstrap
layer — it is the single model-access key passed to a model gateway or direct
LiteLLM-compatible endpoint, Hindsight's LLM and embeddings clients, and
referenced from `model_profiles` entries in `platform-config.yaml` as
`${LLM_API_KEY}`. There is no per-provider key variable; a workflow
selects a model via `session.model` in `agent.yaml`, which resolves to a
`model_profiles` entry (or a raw model name). Hindsight can use that same
endpoint for both clients, but its embedding model must still be an actual
embedding model exposed by that endpoint; it is configured independently from
the chat model.

Claude Code prices models it does not know at its default Anthropic model's
rate, so `total_cost_usd` for self-hosted models is wrong unless the profile
declares `model_costs`. The runtime writes those prices into Claude Code's
`~/.claude.json` model-cost cache before each session. The resulting estimate
is stored as `control_plane.sessions.cost_usd` and shown in the session trace
usage tooltip. This cache is an
undocumented Claude Code internal, so re-check cost reporting after CLI
upgrades. The model gateway's own spend log remains the billing source.

### Compose environment files

For Compose deployments, two files are loaded automatically by the
public Makefile:

1. `workflow-repo/deploy/compose.env` is committed and contains **only
  non-secret** production values used before services can read
  `platform-config.yaml` (for example public URLs, host bindings, sandbox
  mode, database names, and Hindsight base URLs/models).
2. `~/.local/state/sage-run/local/compose.env` is generated by `make bootstrap`
  outside Git and contains direct-container secrets and the workflow checkout
  path. Set `BOOTSTRAP_OUTPUT_DIR` to choose another private directory. Explicit UI URL, Gateway URL and sandbox
  overrides apply equally to local and remote workflow sources. Authentication
  and ingress belong to workflow deployment configuration.

The generated file is loaded last. Bootstrap does not rewrite workflow routes,
connector targets, subscriptions, or schedules for local use. Workflows and
connectors start paused; operators must review those settings before resuming.
Application settings and ordinary workflow credentials remain in the workflow
repo's `platform-config.yaml`/`agent.yaml`; services that can decrypt them do
so after startup. Postgres, MinIO, and Hindsight cannot, so their direct
secrets belong in the bootstrap layer.

### Loading order

At import time, `shared/lib/config.py` calls `load_platform_env` (see
`shared/lib/platform_secrets.py`) against `PLATFORM_CONFIG_FILE`, decrypts its
`secrets:` block if `AGE_IDENTITY` is set, and overlays each resulting value
onto `Settings` **only if the corresponding env var isn't already set** — so
an explicit bootstrap env var always wins over the repo's config file.

## Layer 2 — `platform-config.yaml` reference

This file lives in the workflow repo (see
[examples/workflow-repo/platform-config.yaml](../examples/workflow-repo/platform-config.yaml)
for the public template) and is read only after the platform has
cloned/synced the repo.

```yaml
config:            # plain deployment env vars (DB/object-store overrides, custom
                    # workflow env, INSTANCE_NAME, AGE_PUBLIC_KEY, ...)

identity:
  group_mapping:   # optional external identity group -> application group mapping
    platform-admin: [external-platform-admins]
    workflow-operator: [external-workflow-operators]
    task-viewer: [external-task-viewers]

mcps:
  enabled: [...]    # which MCP servers this instance runs
  config:           # per-server policy, keyed by server id (see docs/mcps.md)

connectors:
  enabled: [...]    # which connector instances this deployment runs
  instances:        # instance configs, keyed by instance id (see docs/connectors.md)

message_bus:
  provider: mattermost | slack

runtime_bundles:
  storage: s3
  bucket: sage-run-bundles
  retention_versions: 20

runtime_env:        # env injected into every runtime container; a value of
                    # `null` removes a built-in var instead of setting it
  DISABLE_TELEMETRY: true

default_model_profile: local

model_profiles:      # named env-var bundles selected via agent.yaml session.model
  local:
    ANTHROPIC_BASE_URL: http://local-llm:8000
    ANTHROPIC_AUTH_TOKEN: ${LLM_API_KEY}
    ANTHROPIC_MODEL: some-model-name
    CLAUDE_CODE_THINKING_MODE: default
    CLAUDE_CODE_MAX_OUTPUT_TOKENS: "8192"
    CLAUDE_CODE_MAX_CONTEXT_TOKENS: "65536"
    CLAUDE_CODE_AUTO_COMPACT_WINDOW: "65536"
    CLAUDE_AUTOCOMPACT_PCT_OVERRIDE: "90"
    model_costs:     # optional, USD per million tokens; cache_* default to input
      some-model-name: {input: 0.15, output: 1, cache_read: 0.05}

memory:
  backend: hindsight
  banks:             # workflow name -> Hindsight bank id, per kind
    business:
      my-workflow: incident-rca-my-workflow
    learning:
      my-workflow: workflow-learning-my-workflow

message_bus:
  provider: mattermost
  api_url: https://mattermost.example.com
  bot_token_secret: message_bus_bot_token

secrets:              # age-encrypted platform-wide secrets
  message_bus_bot_token:
    encrypted: "ENC[age,...]"
```

### Identity group mapping

`identity.group_mapping` translates identity-provider group claims into a small,
stable application vocabulary for `GET /api/user-info`:

| Application group | Intended meaning |
| --- | --- |
| `platform-admin` | Platform administration and configuration |
| `workflow-operator` | Workflow and task operation |
| `task-viewer` | Read-only task and operational visibility |

Each key accepts a list of exact external group names. A user receives an
application group when any configured external name matches one of their
incoming groups. Unknown application keys and unmatched external groups are
not returned. If the section is omitted, malformed, or has no matches, the API
returns an empty `groups` list rather than exposing raw identity-provider group
names.

These groups are currently informational identity metadata for the control
plane UI. They do not enforce RBAC or restrict API, workflow, or task access.

`${VAR}` placeholders anywhere in this file are expanded from `config:`
values, decrypted `secrets:` values, and the process environment at load time
(`shared/lib/platform_secrets.py::expand_env_placeholders`).

Reasoning-history handling and sampling controls such as temperature, top-p,
top-k, and presence penalty belong in the model gateway or inference deployment
when the Anthropic-compatible client does not expose them as workflow settings.

### Connections

`connections:` groups the environment variables one integration needs. A
workflow lists the connections it uses in `agent.yaml`, and each of its tasks
receives those variables, so `.mcp.json` headers such as `${SPLUNK_PASSWORD}`
expand exactly as with workflow-level `env`/`secrets`:

```yaml
connections:
  splunk:
    description: Corporate Splunk REST API
    workflows: [online-alerts-investigator]   # optional allow-list
    env:
      SPLUNK_BASE_URL: https://splunk.example.com
      SPLUNK_USERNAME: ops-agent
    secrets:
      SPLUNK_PASSWORD:
        encrypted: ENC[age,...]
        description: Sent only in this workflow's Splunk MCP requests
```

A connection secret without an `encrypted` value is declared but not set; it is
reported by `sage-run validate` and omitted from tasks. A task fails to launch
if its workflow references an unknown connection, a connection whose
`workflows` list excludes it, or two sources for the same variable. Connection
secret names join the sandbox credential deny-list.

### Environment overlays and keys

`platform-config.yaml` holds the base (development/test) configuration, with
secrets encrypted to the development key named by `config.AGE_PUBLIC_KEY`.
`platform-config-<env>.yaml`, for example `platform-config-prod.yaml`, overrides
values for one environment. Set `SAGE_RUN_ENV=prod` (Helm value `environment`)
to merge it: mappings merge recursively, and lists and scalars from the overlay
replace base values. Workflow sync snapshots the merged result for tasks.

Each environment has its own key, and a host holds only its environment's key.
The overlay must therefore name its own `config.AGE_PUBLIC_KEY` and override
every encrypted value in the base; `sage-run validate` rejects an overlay that
reuses the base key or leaves a base ciphertext in place.

```sh
sage-run keygen --out ~/.config/sage-run/keys/<instance>-prod.agekey   # prints the public key
sage-run secret set --env prod --connection splunk --name SPLUNK_PASSWORD
sage-run secret set --env dev --name message_bus_bot_token --value-file /secure/token
```

`secret set` encrypts to the recipient in the selected file, keeps comments and
formatting, and never writes plaintext. Commit the change and deploy it.

### Encrypted secrets

Secrets are age-encrypted (X25519, via the `pyrage` library) and stored as
`ENC[age,<base64-ciphertext>]`. `AGE_PUBLIC_KEY` (safe to commit) encrypts new
values; `AGE_IDENTITY` (bootstrap-only, never committed) decrypts them at
container-spawn time. Use `make set-platform-secret` for shared values in the
configured `platform-config.yaml`, or `make set-workflow-secret
WORKFLOW=<workflow-name>` for values in a workflow's `agent.yaml`. Both commands
prompt securely for the secret name and value, then run `make sync` to rebuild
the active workflow release through the running gateway.

For long values such as base64 credentials, bypass terminal input limits with
`SECRET_NAME` and `SECRET_VALUE_FILE` (supported by both targets):

```bash
make set-workflow-secret WORKFLOW=example-workflow \
  SECRET_NAME=SERVICE_ACCOUNT_B64 SECRET_VALUE_FILE=/secure/path/credential.b64
```

On macOS, a single-line base64 value copied to the clipboard can be passed
without a plaintext file or the secret appearing in shell history:

```bash
pbpaste | tr -d '\r\n' | make set-workflow-secret WORKFLOW=example-workflow \
  SECRET_NAME=SERVICE_ACCOUNT_B64 SECRET_VALUE_FILE=/dev/stdin
```

These options bypass the corresponding prompts; file input is encrypted as-is.

Per-workflow secrets follow the same `encrypted: ENC[...]` shape under a
workflow's own `agent.yaml` `secrets:` block — see
[Workflow authoring](workflow-authoring.md). Prefer [connections](#connections)
for integration credentials, so they are defined once per environment.

## Layer 3 — workflow packages

`workflows/`, shared `skills/`/`hooks/`, and any custom `mcps/`/`connectors/`
the workflow repo ships. See [Workflow authoring](workflow-authoring.md) for
the package layout and bundle assembly rules.
