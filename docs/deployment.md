# Deployment

## Clone the platform

Clone the public platform repository on the deployment host. This example uses
`/home/ubuntu/sage-run`; choose a writable checkout path for your deployment user.

```sh
git -c credential.helper= clone \
   https://github.com/ops-workflows/sage-run.git \
   /home/ubuntu/sage-run

cd /home/ubuntu/sage-run
```

The repository is public, so this HTTPS clone requires no credentials or PAT.
`-c credential.helper=` disables configured credential helpers only for this
command; it does not change Git configuration for later commands. If cloning a
private repository instead, enter your username and PAT at Git's prompts rather
than putting the PAT in the URL or command line.

Run `make init` for source development. It installs the `dev`, `server` and
`kubernetes` extras; service Dockerfiles also request `server` explicitly, and
the Gateway and session-manager images include the Kubernetes client. A plain operator
package install does not install the Claude Agent SDK, database drivers, web
server or indexing libraries. This dependency split does not change model
configuration or runtime capabilities.

## Bootstrap (`make bootstrap`)

`make bootstrap` runs the packaged `sage-run bootstrap` command, a guided prompt that produces
the **layer 1** bootstrap artifact described in
[Configuration](configuration.md). For a remote source it clones or refreshes
the initial local checkout, but never modifies its `platform-config.yaml`.

Prompts:

1. **Deployment target** — `compose` or `kubernetes`.
2. **Workflow source** — `remote` (git URL + ref + initial checkout path) or
   `local` (an existing filesystem checkout path). Compose bind-mounts the
   checkout; Kubernetes uses the checkout's config for cold start and then
   performs remote syncs with the configured GitHub App.
3. **One-time clone PAT** (remote only, optional for public repositories). It
   is supplied to Git only through a temporary `GIT_ASKPASS` process and is
   never written to `compose.env`, a Kubernetes Secret, the Git remote URL, or
   platform config. All subsequent workflow sync, Knowledge Source sync,
   version lookup, reflection PR, and GitHub MCP operations use the named
   GitHub App connections in `platform-config.yaml`.
   Kubernetes bootstrap also prompts for the target namespace; use the same
   namespace with `helm upgrade`.
4. **Compose host overrides** — optional Gateway URL, UI URL and sandbox
   (`macos` or `gvisor`). Blank entries retain workflow deployment settings.
   No host policy is inferred from package source or workflow source.
5. **AGE identity** — an armored
   `AGE-SECRET-KEY-...` string or a path to a key file. A path is read into
   the generated secret artifact so it works inside containers.
6. **LLM API key** — one
   key shared by runtime model profiles and Hindsight's LLM/embeddings clients.
7. **Postgres password** and **object-store secret key** —
   direct-container secrets required by Compose infrastructure.

Generated artifacts live under `~/.local/state/sage-run/local` by default,
outside the platform and workflow checkouts. Set `BOOTSTRAP_OUTPUT_DIR` to a
different private directory for another instance. Bootstrap refuses to overwrite
an existing artifact; back it up and move it aside before regenerating it.

Generated artifact per target, relative to that private directory:

| Target | Artifact | Apply |
| --- | --- | --- |
| `compose` | `compose.env` | `make up` |
| `kubernetes` | `dist/bootstrap/k8s-secret.sh` | run the script to create/update bootstrap and `platform-config.yaml` Secrets |

The installed CLI can generate the same artifacts from any working directory:

```sh
sage-run bootstrap --output-dir "$HOME/.local/state/sage-run/local"
```

This command generates configuration only. It does not start Compose or apply
Kubernetes resources. Compose files are created with mode `0600`; Kubernetes
scripts are private executables with mode `0700`. Existing files and symlinks
are not overwritten.

To preserve an existing checkout-root `compose.env`, copy it to the private
directory with mode `0600` rather than regenerating credentials. The original
file is no longer loaded by default. An explicit
`COMPOSE_BOOTSTRAP_ENV_FILE=/absolute/path/to/compose.env` selects another
existing file without copying it. Source builds and the platform Makefile still require the platform checkout.

## Validate a Workflow Repository

```sh
sage-run validate /path/to/workflow-repo
```

Omitting the path validates the current directory. The command checks JSON/YAML
syntax and workflow package structure against the schema included in the
installed package. It ignores Git metadata and installed dependency directories,
returns a nonzero status on errors, and does not fetch repositories, decrypt
secrets or contact a running platform. Gateway uses the same package checks.

## Authentication and Ingress

SAGE Run does not currently provide browser authentication or public ingress.
Workflow repositories and production deployment configurations own those
concerns and can add only the components required by their environment. For
example, a public-cloud load balancer can provide OIDC-based access control, a
local proxy such as Envoy can integrate with an OIDC provider, or a deployment
can intentionally expose the platform without browser authentication.

The public hostname and gateway callback base URL must both use HTTPS whenever
Mattermost approval callbacks are enabled. Any ingress layer that permits the
callback must allow `POST /webhooks/message/actions/approval`; Gateway verifies
the signed callback context for that route.

## Register a GitHub App

Use a separate GitHub App registration for each GitHub.com or GitHub Enterprise
Server host. The helper requires Python 3.11+ and a browser signed in as an
organization owner or a member allowed to manage organization GitHub Apps:

```sh
make create-github-app
```

It prompts for an organization URL (for example `https://github.com/acme` or
`https://ghes.example.com/platform-ops`) and an App name. Organization
settings URLs and `host/organization` paths also work. It opens a local form;
choose **Continue to GitHub**, review the name, then **Create GitHub App**.
Registration is not a headless REST operation: GitHub's
[manifest handshake](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest)
requires browser approval. The script then exchanges the one-time code through
the REST API without a PAT or stored `gh` credentials. GHES uses `/api/v3` and
normal TLS verification; trust the instance's CA on the machine running the
helper rather than disabling verification.

The manifest grants repository **Contents, Issues, and Pull Requests: write**
and **Metadata: read**, with no subscribed events. The App is private to its
owning organization, webhooks are inactive, and user OAuth authorization is not
requested. These are service-identity defaults, not a clone of any existing
App's unexposed administrative settings. The homepage is the target organization
URL. The loopback redirect is only for registration, not a runtime OAuth callback.

Credentials are saved in a unique directory under
`~/.config/sage-run/github-apps/<host>/`. The directory has mode `0700`, and
files have mode `0600`:

- `private-key.pem`: App private key for SAGE authentication.
- `credentials.json`: complete API response, including the PEM, client secret,
  and webhook secret if supplied. Treat this entire file as a secret.
- `connection.json`: web/API base URLs, App ID, installation/settings URLs,
  and a suggested private-key secret name. It is connection metadata, not a
  complete `platform-config.yaml`; `installation_id` is initially unset.

The script never prints secret values or overwrites existing output directories.
Keep these plaintext files out of Git and encrypt the PEM with
`scripts/set_secret.py --scope shared --name github_app_private_key --value-file
/path/to/private-key.pem`, supplying the instance's `--identity` and
`--platform-file`. Set the connection's `private_key_secret` to the same secret
name, then securely archive or remove the plaintext credential files.

Open the printed installation URL and choose **Only select repositories**,
including the workflow repository and any repositories the workflows need.
Copy the installation ID from the resulting installation URL into the named
connection's `installation_id`. An App ID and an installation ID are different.
Choose that connection for `github.workflow_repo_connection` when appropriate.

For an SSH deployment host, forward the helper's loopback port from your
workstation, then run the command in that SSH session:

```sh
ssh -L 8765:127.0.0.1:8765 ubuntu@your-host
cd /home/ubuntu/sage-run
make create-github-app GITHUB_APP_ARGS="--no-browser"
```

Open the printed `http://127.0.0.1:8765/register/...` URL in your workstation's
browser. No public listener or firewall change is needed. Use `--port` and a
matching forward if that port is occupied. Browser approval times out after
600 seconds; `--timeout` can extend it up to GitHub's one-hour handshake limit.
`GITHUB_APP_ARGS="--help"` lists all options, including `--org`, `--name`, and
`--output-dir` (which must be a new directory). Cancellation never deletes an
already-registered App; inspect its settings before retrying after an error.

## Kubernetes deployment

`sage_run/chart` is a namespace-scoped chart: one release per namespace,
with Services named as in Compose (`gateway`, `postgres`, `minio`,
`hindsight`, `control-plane-ui`, `mcp-<id>`), so workflow `.mcp.json` URLs and
platform defaults work unchanged. It mounts the instance's single workflow
checkout at `/app/workflows` (a host path for local development, or a PVC) and
reads `platform-config.yaml` from it. Postgres, MinIO (with its buckets) and
Hindsight run in the namespace by default. Session Jobs run as the non-root
runtime user with the selected sandbox profile (`runtime.sandboxProfile`).

### Local instance (Rancher Desktop)

Enable Kubernetes in Rancher Desktop with the `moby` engine, so locally built
images are visible to the cluster. From a workflow repository:

```sh
make up      # build platform images from ../sage-run and install the instance
make status
make down    # keep volumes; `sage-run down --purge` deletes the namespace
```

`make up` runs `sage-run up . --source ../sage-run`, which:

- builds platform images tagged `dev-<commit>` (plus a timestamp when the tree
  is dirty) from the platform checkout;
- creates namespace `<repo folder>-dev` and its `sage-run-bootstrap` Secret
  from the development key (`~/.config/sage-run/dev.agekey`, `--identity` or
  `SAGE_RUN_AGE_IDENTITY_FILE`) and the `LLM_API_KEY`, `PG_PASSWORD` and
  `OBJECT_STORE_SECRET_KEY` platform secrets it decrypts from
  `platform-config.yaml` (missing passwords are generated once and kept);
- enables the MCP servers and connectors listed in `platform-config.yaml`,
  applies its `deployment:` settings, mounts the working tree, and exposes
  `http://<instance>.localhost` through the cluster's Traefik;
- restarts platform services so working-tree configuration applies, and syncs
  workflows. A fresh instance starts with workflows and connectors paused.

Run `make up` again after edits. Several workflow repositories run side by side
as separate namespaces.

### Production instance (k3s host over SSH)

A production host runs single-node k3s with the patched gVisor runtime
(RuntimeClass `gvisor`, see [Security](security.md)) and holds the instance's
age key at `/etc/sage-run/<instance>/age.key` (root, 0600). Generate the key on
the host (`sudo age-keygen -o /etc/sage-run/<instance>/age.key`) and put its
public key in `platform-config-prod.yaml`; the private key never leaves the host.

From the workflow repository on a workstation:

```sh
sage-run deploy --host <ssh-host> --env prod --ref main --plan   # review
sage-run deploy --host <ssh-host> --env prod --ref main
```

Deploy requires `--ref` to be pushed to `origin` at the same commit. It:

1. streams that commit as a git bundle into `/var/lib/sage-run/<instance>/workflow-repo`
   and sets `origin` (no clone credentials on the host);
2. builds the `sage-run-bootstrap` Secret on the host: the host key decrypts the
   `LLM_API_KEY`, `PG_PASSWORD` and `OBJECT_STORE_SECRET_KEY` platform secrets
   (only ciphertexts leave the workstation);
3. installs Helm on the host if needed (pinned, checksum-verified) and upgrades
   the release with the chart and the release's digest-pinned images;
4. applies `deploy/k8s/*.yaml` from the commit (`${WORKFLOW_REPO_PATH}` is the
   host checkout), restarts platform services and syncs workflows.

Afterwards, workflow-only changes merged to the deployed ref can be applied
with the control plane's **Sync now**, which fetches through the instance's
GitHub App connection; platform, configuration and MCP changes use
`sage-run deploy` again. `deployment.ui` (`host_ip`, `host_port`) publishes the
UI on a node address when there is no ingress controller.

## Which services actually start

Compose gates every optional MCP server and connector behind a profile (see
`deploy/docker-compose.yml`'s `profiles:` entries). `make up` derives the
profile set with `sage-run profiles`, which reads the instance's
`platform-config.yaml`
and maps its `mcps.enabled`, `connectors.enabled` (by connector `type`), and
`model_profiles` (by `ANTHROPIC_BASE_URL`) to the matching profile names:

```sh
make up
# Computed COMPOSE_PROFILES=gcp-pubsub,model-gateway,salesforce
```

The workflow repo owns a committed `deploy/compose.env` with non-secret
production coordinates. `make bootstrap` writes a separate private
`compose.env` under `BOOTSTRAP_OUTPUT_DIR` with bootstrap secrets and the workflow checkout path,
and explicit host overrides when supplied. The Makefile loads committed defaults
first and the generated file second.

Workflow Repo **Sync** is the release boundary for workflow packages and
repo-owned per-task runtime settings. After a successful sync, the selected
revision's `platform-config.yaml` is snapshotted with the workflow bundles; new
tasks use that snapshot for model profiles, context limits, and runtime env.
Running tasks retain their launch environment. This behavior is identical for
local-directory and remote Git workflow sources.

Sync does not reconcile long-running service topology. Changes to `mcps.enabled`
or `connectors.enabled` still require an operator deployment action: run
`make down && make up` for Compose, or update Helm/Kubernetes manifests through the
deployment control plane. The Workflow Repo UI should surface this requirement
when those settings change.

Legacy Compose database, volume, bucket, runtime-path, and Hindsight storage
identifiers must be changed through the verified backup and cutover procedure in
[SAGE Run Stateful Identifier Migration](sage-run-stateful-identifier-migration.md),
not by direct replacement in a running deployment.

Kubernetes (Helm) does **not** have an equivalent automatic derivation today:

- The Helm chart's `mcps.<id>.enabled` / `connectors.<id>.enabled` booleans in
  `values.yaml` directly gate which templates render — but the chart never
  reads `platform-config.yaml` itself, so these booleans have to be kept in
  sync with it by hand.

For remote private workflow repositories, the Helm chart uses an ephemeral
clone cache in Gateway and session-manager plus object storage as the durable
release transport. A successful UI Sync uploads immutable bundles and the
matching `platform-config.yaml`, then advances the active release pointer.
New tasks resolve both from that one release; no workflow-repo PVC is needed.
Kubernetes runtime Jobs use an `emptyDir` mounted at `/memory`; a helper
restores agent memory from object storage before the runtime starts and uploads
it after the runtime signals completion. PostgreSQL, self-hosted MinIO, and
Hindsight remain the only chart-managed components that need durable PVCs.

Large Knowledge Source repositories can require more memory during Graphify
extraction than a default local Docker VM provides. The Compose
`knowledge-indexer` has no container memory limit, so increasing a Compose
limit does not increase available memory; size the Docker Desktop or Rancher
Desktop VM instead. A 16 GiB VM is a practical starting point for large source
trees. For Kubernetes, give the `knowledge-indexer` pod a corresponding memory
request and limit through the deployment's resource policy.

## Local development (uncommitted working tree)

In the bootstrap prompt, choose the `local` workflow source so
`HOST_WORKFLOW_REPO_PATH` points at a plain filesystem checkout. **Sync now**
rebuilds the bundle from whatever is currently on disk — no git fetch, no
commit, no pinned tag required. Object storage is optional in this mode; a
local `RUNTIME_BUNDLE_ROOT` works fine.
When the workflow repository contains `deploy/docker-compose.override.yml`,
the Makefile loads it after the public base stack.

For a remote Compose source, the gateway manages the mounted workflow-repository
checkout: **Sync now** fetches the configured or pinned ref and checks out its
resolved commit before building bundles. Mount the repository root (including
`.git`), not its `workflows/` subdirectory. The gateway can update that checkout;
the session manager consumes the same checkout read-only, so workflow details
and newly built task bundles describe the same revision.

## `make` targets

| Target | Does |
| --- | --- |
| `init` | `uv sync --extra dev --extra server --extra kubernetes`. |
| `bootstrap` | Run `sage-run bootstrap` interactively, writing to `BOOTSTRAP_OUTPUT_DIR` outside Git. |
| `sync` | Rebuild the active platform/workflow release through `GATEWAY_URL` (default `http://localhost:8080`). |
| `set-platform-secret` | Interactively encrypt a secret in the configured `platform-config.yaml`, then sync. |
| `set-workflow-secret WORKFLOW=<name>` | Interactively encrypt a secret in the selected workflow's `agent.yaml`, then sync. |
| `compose-build` | Build all Compose services. |
| `runtime-build` | Build the `sage-run-agent-runtime` image. |
| `build` | `runtime-build` + `compose-build`. |
| `up` / `down` | Start/stop the local Compose stack. |
| `restart` | `down` + `build` + `up`. |
| `restart-<service>` | Rebuild and recreate one service, e.g. `make restart-postgres`. |
| `ensure-test-db` | Create the dedicated Postgres test database if missing. |
| `unit-tests` | `tests/unit` (no infra). |
| `service-tests` | `tests/service` against real Postgres. |
| `runtime-tests` | `tests/runtime` against real Postgres + Docker. |
| `tests` | All three suites. |
| `clean-test-containers` | Remove dangling test session containers. |
| `format` / `lint` | ruff fix+format / ruff check+format-check. |

## Deployment artifacts (`deploy/`)

- `deploy/docker-compose.yml` — the public base stack (Postgres, MinIO,
  gateway, session-manager, runtime image, control-plane UI, core MCPs).
   Mounts `HOST_WORKFLOW_REPO_PATH` and derives its `platform-config.yaml`
   (default `../examples/workflow-repo`),
  and `RUNTIME_BUNDLE_ROOT`. Optional profiles: `model-gateway`, `local-llm`,
   `salesforce`, `splunk`, `cloudwatch`, `gcp-logging`, `github`, `jira`, `servicenow`,
   `gcp-pubsub`.
- `sage_run/chart` — Kubernetes (Helm) chart for one instance per
   namespace; `sage-run up` renders its values from the workflow repository
   (see [Kubernetes deployment](#kubernetes-deployment)).

Private/customer deployments should commit non-secret Compose/Kubernetes values
in the workflow repo (`deploy/compose.env`) and use
the generated bootstrap artifact for secrets, rather than editing the public
base stack or adding a Compose override for shipped services.

## Workflow bundles

A **bundle** is the assembled, runnable package for one workflow: `CLAUDE.md`,
`agent.yaml`, `settings.json`, `.mcp.json`, `agents/`, `skills/`, `hooks/`,
and a `manifest.yaml`, merged from the platform core, the workflow repo's
shared assets, and the workflow itself (see
[Workflow authoring](workflow-authoring.md) for assembly/precedence detail).

Every supported launcher (Docker and Kubernetes) consumes the same contract:

| Env var | Meaning |
| --- | --- |
| `WORKFLOW_BUNDLE_PATH` | A mounted local bundle directory. |
| `WORKFLOW_BUNDLE_URI` | `file://`, `s3://`, `gs://`, or a presigned `https://` URL the runtime fetches and extracts. |
| `WORKFLOW_BUNDLE_CHECKSUM` | `sha256:<hex>` of the bundle's `manifest.yaml`; the runtime refuses to start if this doesn't match. |

Bundles are uniformly object-storage-backed: when
`RUNTIME_BUNDLE_OBJECT_STORE_BUCKET` is set, session-manager uploads a freshly
built bundle and generates a short-lived presigned https URL for
`WORKFLOW_BUNDLE_URI`, so the runtime container needs no cloud SDK — just
plain https plus the standard library `tarfile`.

## Sync and versioning

Sync — whether the initial bootstrap sync, `make sync`, or the UI **Sync now**
button — runs one pipeline (`shared/lib/workflow_repo_sync.py::sync_workflow_repo`):

1. Fetch the source at the effective ref (pinned ref if set, else the
   bootstrap `WORKFLOW_REPO_REF`) — or read the current working tree in
   local-path mode.
2. Discover `workflows/*/agent.yaml`.
3. Rebuild every bundle and check `manifest.yaml`'s `platform_version` against
   the running platform's version (see [Compatibility policy](#compatibility-policy)).
4. Upload bundles to object storage, if configured.
5. Persist the result — synced ref/commit, discovered workflows, any bundle
   errors, sync status/error, timestamp — to the `control_plane.workflow_repo_state`
   singleton row.

For a remote source, Sync fetches the configured ref (such as `main`) or a
version pinned from the UI. A pin stays in effect for later syncs until changed.
Local-path mode never fetches and simply rebuilds from the mounted files. Sync
never touches bootstrap secrets (repo URL/PAT,
`AGE_IDENTITY`, `LLM_API_KEY`); changing those means re-running
`make bootstrap`.

### Compatibility policy

Compatible within a major version: if a bundle's `platform_version` major
component is newer than the running platform's, that bundle is blocked
("incompatible"); if older, it's built with a warning; if equal, it's OK.

### Gateway endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /api/platform/workflow-repo` | Current state: source, pinned/default ref, last sync result, discovered workflows, bundle errors. |
| `POST /api/platform/workflow-repo/sync` | Trigger the sync pipeline now ("Sync now"). |
| `POST /api/platform/workflow-repo/pin` | Set the operator-pinned ref (`{"ref": "..."}`), stored in Postgres and used by the next sync. |
| `GET /api/platform/workflow-repo/versions` | List released versions to pin from — GitHub-hosted repos only (queries the GitHub tags API with the bootstrap PAT); returns `[]` for other hosts. |

The control-plane UI's workflow-repo page only lets an operator change the
pinned version and trigger a sync; the repo URL and PAT are bootstrap-owned
and are never editable from the UI.

## Publishing Releases

No packaged release has been published yet. Tags `v0.1.0` through `v0.6.0` are
source snapshots without packages or images.

The [release workflow](../.github/workflows/release.yml) runs when a GitHub
release is published. Draft creation and ordinary tag
pushes do not publish artifacts. It resolves the tag to one commit, requires
that commit to be on `main` with a successful CI run (tests are not re-run),
and requires the tag to equal `v` plus the package version in
`pyproject.toml`. Only plain `MAJOR.MINOR.PATCH` versions are accepted; there
are no pre-releases, and development or local versions are rejected.
Update the package version and `uv.lock` before creating the release tag.

Each release builds the images first, records their digests in `release.json`,
embeds that manifest and the Helm chart in the wheel, and publishes to PyPI
last. An installed `sage-run` therefore deploys exactly the images built for
its version. Each release produces:

- A pure-Python `sage_run-VERSION-py3-none-any.whl` and matching
   `sage_run-VERSION.tar.gz` source distribution, published to PyPI and attached
   to the GitHub release. The wheel is built from the sdist and checked with
   Twine. It works on both CPU architectures; dependencies supply their own
   platform-specific wheels where necessary.
- Eight GHCR images under `ghcr.io/ops-workflows/sage-run-<component>:VERSION`:
   `gateway`, `session-manager`, `knowledge-indexer`, `control-plane-ui`,
   `mcp`, `gcp-pubsub-connector`, `servicenow-connector` and `agent-runtime`.
   Each tag contains `linux/amd64` and `linux/arm64` variants, plus build
   provenance and an SBOM. No floating `latest` or major/minor tags are published.

PyPI publishing waits for every image job to succeed. Publication across the
two registries is not atomic: a failed image job can leave some images uploaded,
and a PyPI failure can leave all images uploaded. Rerun failed jobs after fixing
registry access; do not move a released tag or overwrite an existing PyPI
version. A source change requires a new release version.

### Registry Setup

GitHub Packages does not provide a native Python/pip registry. Use PyPI for the
public operator package. GitHub release assets are an additional direct-download
option, not a Python package index.

Use [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) instead
of a long-lived API token or a shared CI account. A maintainer's PyPI account
still owns and manages the project; automation authenticates using GitHub OIDC.
Configure the project's trusted publisher with:

| Setting | Value |
| --- | --- |
| PyPI project | `sage-run` |
| GitHub owner | `ops-workflows` |
| GitHub repository | `sage-run` |
| Workflow filename | `release.yml` |
| GitHub environment | `pypi` |

If the PyPI project does not yet exist and the name is available, configure a
[pending publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).
It does not reserve the name. For an existing project, its owner must add this
publisher. Create the GitHub `pypi` environment with appropriate release-tag
restrictions and, when required, maintainer approval. No `PYPI_API_TOKEN`
secret is needed; only the PyPI job receives `id-token: write`.

GHCR uses the job's `GITHUB_TOKEN` with `packages: write`, not a personal access
token. Permit package creation in the organization and ensure any existing
packages grant this repository Actions access. Images include a source label
linking them to this repository. GHCR packages initially default to private;
make all eight packages public in their package settings for anonymous pulls.
The workflow does not change package visibility.

Only SAGE Run-owned images are published. Third-party infrastructure images
remain upstream dependencies. Publishing `agent-runtime` does not change
workflow `runtime.container_image` settings; pin those explicitly to the
matching version. Bundled third-party software retains its own licensing
and applicable terms.
