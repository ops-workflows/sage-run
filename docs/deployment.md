# Deployment and operations

Unless explicitly marked **unreleased source**, this guide describes the
**1.0.4 implementation**, not the target design. The unreleased section records
source capabilities under test; it is not a release or production qualification.
Use the workflow repository as the instance, the published `sage-run` CLI as
the operator tool, and Kubernetes as the serving environment. No platform
source checkout or platform image build is required on a production server.

The deployment Job and backup features below require 1.0.2 or newer.
Use **1.0.3 or newer** for production: 1.0.2 can stall while validating large
Postgres dumps over Kubernetes exec because the list reader exits early.
The fix drains the upload and preserves validation errors. Existing 1.0.1
instances do not acquire these features until explicitly upgraded.
Check GitHub Releases for publication status before installing a version.

For direct node-port UI exposure, use 1.0.4 or newer. A host-bound UI uses
`Recreate` so the old pod releases its port before the replacement starts;
expect a brief UI interruption during an image/spec update. UI deployments
without a host port retain Kubernetes' default rolling strategy.

## Deployment Jobs and backups

Version 1.0.2 adds the first workflow/config deployment milestone:

- **Deploy now** replaces Sync/pin in the UI. Production selects `main` or a
  `v`-prefixed tag; local deployment uses the uncommitted working tree.
- Gateway creates a Job from its running, pinned Gateway image with its own
  namespace-scoped deployer service account. The Job survives Gateway restarts.
  The role has trusted operator access to namespace resources and Secrets,
  not cluster-admin or per-Secret isolation.
  The API exposes the latest Job's phase, requested commit, failure and bounded
  decoded logs; reloading the page recovers the Job state. Completed Job/log
  retention is seven days, **not** backup expiry.
- The Job fetches production refs using the named GitHub App connection,
  validates the candidate and keeps the running platform images. An incompatible
  `sage-run` dependency pin, infrastructure changes or database/object-store
  credential rotation are refused; use a reviewed CLI upgrade/migration.
- An atomic directory lock at `.git/sage-run-deploy.lock.d` serializes
  deployment and backup writers. SSH CLI holds the same host lock. Gateway
  mounts the managed checkout read-only; periodic discovery never fetches.
  Existing unmanaged instances retain their old APIs; managed `/sync` and
  `/pin` requests return 410 rather than bypass deployment safety.
  Directory creation, unlike `flock`, coordinates macOS with Rancher's Linux
  shared mount. Forced termination may leave a stale guard: verify all
  deployment/backup Jobs and CLI writers have stopped, then remove only that
  empty lock directory. Never clear a live writer's lock.
- Prompt/skill-only changes rebuild and activate bundles with **no pod
  restarts**. A workflow MCP source checksum rolls only that MCP. Config
  changes currently roll config consumers through pod-template checksums;
  this is **not** in-place hot reload. Image/env/topology changes follow Helm
  reconciliation; the CLI no longer blanket-restarts every Deployment.
- Extra namespace-scoped manifests receive an ownership label. Only owned
  removed resources are pruned; removing a PVC requires explicit migration.
  Name collisions with unowned resources fail before apply. Review and
  explicitly label existing manually applied ingress resources with
  `sage-run/extra=<instance>` before their first managed adoption.
  Checkout-backed `subPath` files, such as Caddy's config, contribute a pod
  checksum so their changes restart the consuming Deployment.
- On apply/activation failure the Job attempts to restore the prior checkout,
  Secret, Helm values and owned extra manifests, then reactivate old bundles.
  It reports failure, not success, if recovery fails. Local deployment cannot
  undo the developer's uncommitted working-tree edits.

Managed production installs enable a nightly Kubernetes CronJob at **02:00 UTC**
and backup before **every** production deployment, including bundle-only
updates. Both use the same implementation:

| Category | Creation and cleanup owner | Retained successful copies |
| --- | --- | --- |
| Deployment | Deployer Job; direct SSH CLI uses an independent pre-deployment backup Job | 3 |
| Nightly | Kubernetes CronJob | 7 |

Each rotates only its own category, only after a verified replacement succeeds.
Failed, incomplete, protected, foreign-instance and legacy directories are not
eligible for successful-set rotation. Cleanup errors are visible and block
deployment rather than silently accepting an unverified backup. Protected or
partial sets need operator attention and may consume additional disk space.

The root-only managed directory is
`/var/backups/sage-run/<instance>/managed`. Backups contain a validated Postgres
dump (including Hindsight schema), checked S3 object exports and inventory,
Hindsight filesystem assets when enabled, encrypted config, a verified Git
bundle, Helm values and a checksum/completion manifest. The private age key
must be secured separately. Backup failure prevents apply and preserves older
good copies. A genuine first install has no existing data to back up; existing
PVCs without a serving Gateway require explicit recovery instead of that bypass.

The backup is an **online** Postgres dump plus an object export that rejects
detected concurrent object changes, not an atomic transaction across Postgres,
MinIO and Hindsight files. Verify restoration against your workloads and pause
writers when a coordinated recovery point is required. Same-disk backup does
not protect against node/disk loss. A manual Compose archive stays outside
`managed/` and is never automatically enrolled or deleted.

Chart controls (Helm values, **not** `platform-config.yaml` fields):
`deployer.enabled`, `backups.enabled`, `backups.hostPath`, `backups.schedule`.
The CLI sets managed mode and production paths; local `up` enables deployment
Jobs but does not schedule backups. No new deployment endpoint supplies
browser authentication: preserve corp IAP and do not expose deployment control
on an unauthenticated network. Active-session drain, full configuration hot
reload, ordered schema migrations and UI platform-version handover remain
unfinished. Avoid service-changing deploys while tasks are active.

| New endpoint | Purpose |
| --- | --- |
| `POST /api/platform/deployments` with `{"ref":"main"}` | Start a Job; 202 means accepted, not deployed |
| `GET /api/platform/deployments` | Latest Job state, requested commit, start/finish timestamps and logs |
| `GET /api/platform/workflow-repo` | Active bundle commit, platform version and deployment capability |

The deployment panel displays available start/finish timestamps in the browser's
local time.

CLI recovery remains independent of the Gateway process. The updated SSH CLI
uses the target release's Gateway image for its backup Job before updating
the serving checkout, then reconciles and activates using the installed CLI's
chart. The target package/images must be published before using this path in
production; an old 1.0.1 image does not contain these commands.

## Current support and unfinished work

| Surface | Released behavior (through 1.0.4) | Not yet implemented or qualified in that release |
| --- | --- | --- |
| Production CLI | Single-node k3s over SSH, committed workflow ref, packaged chart and digest-pinned release images | Generic remote kube-context deployment; multi-node checkout placement |
| Local CLI | Rancher Desktop Kubernetes, working-tree mount, optional platform source builds | Turnkey k3d/kind setup or image import |
| UI | **Deploy now**, independent Job, confirmation and persisted status/logs | Live plan/diff and platform-version handover |
| Reconciliation | Helm topology/image updates, config checksums, per-workflow MCP source checksums, namespace-owned extra pruning | In-place config reload, deploy diff planning and active-session drain |
| Recovery | Pre-deploy and nightly backups, independent 3/7 copy rotation, isolated SQL/object/Git/Hindsight recovery qualification | Ordered schema migrations, coordinated cross-service snapshots and off-host backup |

Serving is Kubernetes-only. Run `up`/`deploy` from the workflow repository;
the platform-root Makefile manages dependency installation, tests and builds.
The isolated `tests/compose.yaml` Postgres fixture and Docker runtime helpers
are test infrastructure only, not a supported deployment mode.

## Prerequisites

### Workstation

- A checkout of the workflow repository, Git, Python 3.11+ and `uv`.
- For production: SSH access to the host, passwordless noninteractive `sudo`,
  and a pushed branch or tag at the exact commit being deployed.
- Use an HTTPS Git origin for GitHub App-authenticated production fetches.
  The operator carries the workstation's origin into the serving checkout;
  an SSH origin cannot use the App's HTTPS installation token.
- For local Kubernetes: `kubectl`, Helm, Rancher Desktop with Kubernetes and
  the Moby engine enabled. Its Docker images must be visible to the cluster.
- For platform development only: a SAGE Run checkout, its development
  dependencies (`make init` in that checkout), and Docker builds.

Use an exact operator version:

```sh
uvx --from 'sage-run==1.0.4' sage-run --version
```

The PyPI project is `sage-run`, not the GitHub organization name. The wheel
contains the chart and a release manifest with GHCR image digests.

### Production server

Provision a Linux node with a qualified k3s/containerd installation, working
cluster DNS, persistent storage/default StorageClass, and enough capacity for
Postgres, MinIO, Hindsight, indexing and concurrent sessions.

The SSH deployer assumes:

- `sudo k3s kubectl` and `/etc/rancher/k3s/k3s.yaml`;
- Git, Python 3, `age` (and `age-keygen` for key creation), tar, curl,
  checksum tools and standard Linux utilities;
- registry access to public GHCR images and upstream infrastructure images;
- access to the configured model, messaging, GitHub App and integration endpoints;
- an instance key already installed at `/etc/sage-run/<instance>/age.key`;
- a working `gvisor` RuntimeClass for production tasks.

It installs Helm **v4.0.5** on the host if needed, verifying its download.
The current SSH installer assumes Linux **amd64**; multi-architecture images
do not make that installer architecture-independent.

There is no automatic host-preparation/doctor command yet. Install k3s and
qualify its sandbox before deploying; do not run an unreviewed install script
on an existing production host.

The qualified reference host uses k3s **v1.36.5+k3s1**, with Traefik and ServiceLB disabled,
and pod/service CIDRs are `172.30.0.0/16` and `172.31.0.0/16`. These are
instance-specific choices to avoid network conflicts, not universal defaults.
Use the [sandbox configuration](security.md#providing-an-outer-sandbox) and
verify Bubblewrap and a complete task as non-root under gVisor. A version
number alone is not a qualification result.

### Managed VM layout

The migrated corp and PS hosts use this layout; `<instance>` is the production
namespace. These are active paths, not instructions to reinstall or replace
the node runtime.

| Path | Purpose / handling |
| --- | --- |
| `/etc/sage-run/<instance>/age.key` | Production age identity: root-only 0600 file, 0700 parent; secure a separate recovery copy |
| `/var/lib/sage-run/<instance>/workflow-repo` | Sole deployment-managed serving checkout; no manual edits or private files |
| `/var/lib/rancher/k3s/` | Active k3s state; `storage/` contains live local-path PVC data, not disposable cache |
| `/var/lib/rancher/k3s/agent/etc/containerd/config-v3.toml.d/gvisor.toml` | Active containerd registration for handler `runsc-pr15008`; verify the effective config for the pinned k3s version |
| `/etc/gvisor/runsc-pr15008.toml` | Active runtime options, including pinned binary/root paths |
| `/opt/gvisor/release-20261019.0-pr15008/` | Keep the complete active `runsc`, shim and `gvisor-bin/` auxiliary binary set |
| `/var/backups/sage-run/<instance>/managed/` | Verified managed recovery sets: 7 nightly / 3 deployment copies |
| `/var/backups/sage-run/<instance>/20261026-pre-compose-cleanup/` | Manual retirement archive; outside managed rotation, no automatic expiry |

PS also retains its manual `20261026-k8s-cutover/final-stopped/` recovery copy
under the instance backup directory. The workflow READMEs record each host's
archives. Retired home-directory checkouts/builds and obsolete Docker runtime
registrations were archived and removed without changing the active Kubernetes
handler. Preserve unrelated home files, SSH/shell/account configuration,
user-managed backups and tooling; never recursively remove a user's home.

## First-time workflow configuration and keys

Start from [examples/workflow-repo](../examples/workflow-repo/). Replace all
template values before deploying; it is deliberately not a runnable tenant.

1. Configure the base `platform-config.yaml` for development/test.
2. Generate a local key once:

   ```sh
   uvx --from 'sage-run==1.0.4' sage-run keygen \
     --out ~/.config/sage-run/dev.agekey
   ```

   Put the printed public recipient in base `config.AGE_PUBLIC_KEY`.
   Do not overwrite an existing key: existing ciphertext depends on it.

3. On the production host, create a separate root-only key:

   ```sh
   sudo install -d -m 700 /etc/sage-run/my-workflows
   sudo sh -c 'umask 077; test ! -e /etc/sage-run/my-workflows/age.key &&
     age-keygen -o /etc/sage-run/my-workflows/age.key'
   sudo age-keygen -y /etc/sage-run/my-workflows/age.key
   ```

   Substitute the actual namespace/instance name. Copy **only the public
   recipient** into `platform-config-prod.yaml` at `config.AGE_PUBLIC_KEY`.
   Keep a separately secured recovery copy of the private key; same-disk data
   backups cannot recover encrypted config after losing this key.

4. Encrypt platform and integration credentials with the CLI from the workflow
   checkout. It prompts without echo and needs only the recipient, not the
   private key:

   ```sh
   uvx --from 'sage-run==1.0.4' sage-run secret set . --env dev --name LLM_API_KEY
   uvx --from 'sage-run==1.0.4' sage-run secret set . --env dev --name PG_PASSWORD
   uvx --from 'sage-run==1.0.4' sage-run secret set . --env dev --name OBJECT_STORE_SECRET_KEY
   uvx --from 'sage-run==1.0.4' sage-run secret set . --env prod --name LLM_API_KEY
   uvx --from 'sage-run==1.0.4' sage-run secret set . --env prod --name PG_PASSWORD
   uvx --from 'sage-run==1.0.4' sage-run secret set . --env prod --name OBJECT_STORE_SECRET_KEY
   uvx --from 'sage-run==1.0.4' sage-run secret set . --env prod \
     --connection example-service --name SERVICE_TOKEN
   ```

   Use `--value-file /secure/path` for multiline credentials. Never put
   plaintext credentials in command arguments, Git or Helm values.

5. Override **every base ciphertext** in the production overlay, including
   GitHub App and messaging credentials, even when the plaintext is identical.
   Mappings merge recursively; lists/scalars replace base values. The
   production environment has one key, not both development and production keys.
6. Set `deployment.public_url`, `deployment.sandbox_profile`, Hindsight model
   settings and any service-specific options. Connections supply per-workflow
   integration URLs and request headers; see [Configuration](configuration.md).
7. Validate, review, commit and push:

   ```sh
   uvx --from 'sage-run==1.0.4' sage-run validate .
   ```

The namespace Secret `sage-run-bootstrap` holds the age identity plus decrypted
`LLM_API_KEY`, `PG_PASSWORD` and `OBJECT_STORE_SECRET_KEY`. The host key is the
only separately managed plaintext credential file, **not** the only plaintext
copy: Kubernetes Secrets and trusted service memory also contain credentials.
Protect cluster-admin access, node storage and backups accordingly.

### Copy-only browser encryption (unreleased source)

Each workflow's **Secrets** tab loads the running Gateway's public recipient and active
environment. `config.AGE_PUBLIC_KEY` comes from the merged base/environment
configuration at startup, so production uses its production recipient rather
than the development key. As with other Settings, an explicit environment
override takes precedence. Confirm the displayed environment and recipient.

Enter a string (including multiline credentials) and encrypt it locally in the
browser. Plaintext is never submitted to an API, saved in browser storage or
written to the repository. Copy the resulting `ENC[age,...]` into the appropriate
`encrypted:` field, then review, commit and deploy normally. There is no secret
save endpoint, Git write or pull-request creation. A missing/invalid active
recipient is an explicit error. The tab rechecks the public recipient before
each encryption and clears the input after success.
During an active checkout writer/deployment, the key endpoint returns a retry
error rather than advertising a possibly transitional recipient.

Use trusted HTTPS or localhost: browser-local encryption does not protect
against modified JavaScript delivered over an untrusted HTTP connection.
On origins where clipboard access is unavailable, select and copy the output
manually. This helper needs no private key; retain the CLI for first-time setup
before an instance/UI exists. It is not shipped in 1.0.4.

### GitHub App access

Initial deploy sends a Git bundle over SSH; no Git clone or PAT is needed on
the server. Later UI syncs fetch through the named App installation in
`github.workflow_repo_connection`.

Register separate GitHub Apps for GitHub.com and each GHES host. The optional
platform-source helper `make create-github-app` performs the browser-approved
manifest handshake and writes private files under
`~/.config/sage-run/github-apps/<host>/` (directory 0700, files 0600).
Install the App on the workflow repository and configure its installation ID.
Encrypt its PEM under the `secrets` entry referenced by `private_key_secret`.
Use `sage-run secret set --name <entry> --value-file /secure/private-key.pem`.
Archive or remove the plaintext helper output securely.

Grant only needed repository permissions: Contents read/write for sync and
reflection changes, Issues read/write for permitted issue operations, Pull
Requests read/write for reflection PRs, and Metadata read. Sync-only access
can be narrower. Never embed a PAT in a remote URL.

## First production deployment

Run from the **workstation's workflow checkout**, with its Git origin set:

```sh
uvx --from 'sage-run==1.0.4' sage-run deploy . \
  --host my-agent --instance my-workflows --env prod --ref main --plan
uvx --from 'sage-run==1.0.4' sage-run deploy . \
  --host my-agent --instance my-workflows --env prod --ref main
```

`--plan` prints the selected commit, images and enabled workflow MCPs. It is
not yet a live diff, readiness check or migration plan.

The deployer:

1. Verifies that the selected commit is pushed to `origin` at `--ref`.
2. Transfers it into `/var/lib/sage-run/<instance>/workflow-repo` as a Git
   bundle, with the same checkout mounted into all services that need it.
3. Decrypts infrastructure credentials on the host using its key and applies
   the Kubernetes Secret. Only ciphertext travels from the workstation.
4. Runs Helm with the installed package's chart and release image digests.
5. Applies committed `deploy/k8s/*.yaml`, substituting
   `${WORKFLOW_REPO_PATH}` with the host checkout path.
6. Reconciles affected Deployments, waits for rollouts and activates workflow
   bundles; workflow-only changes do not require pod restarts.

The checkout is deployment-managed: the CLI force-checks out the commit and
cleans untracked files. **Do not edit it or store private files there.**
Keep keys under `/etc/sage-run` and backups outside the checkout.

Provision/resume workflows and connectors deliberately after checking targets,
credentials and schedules. A new instance starts paused; an existing instance
preserves its operator state.

### Ingress and authentication

SAGE Run does not yet provide application-enforced authorization. Identity
groups are informational. Restrict network access and use an appropriate TLS
and identity boundary before exposure.

An instance can commit ingress manifests under `deploy/k8s/`; CLI deploy applies
them on first install and later updates. A private Caddy Deployment can use the same
workflow checkout for its Caddyfile, validates Google IAP JWTs, and binds node
port 443. Its custom Caddy image is currently **manually built/imported** into
k3s, with `imagePullPolicy: Never`: the manifest is automated, image provisioning
is not. A replacement node must import that exact image before deployment.

Alternatively `deployment.ui.host_ip`/`host_port` exposes the UI directly.
That does not add TLS or authentication. Configure callback reachability for
`POST /webhooks/message/actions/approval`; Gateway validates signed callback
context, independently of browser authentication.

## Ongoing updates: actual behavior

This table describes released behavior through 1.0.4. Selective reload and
diff optimizations in the working source tree are listed separately below.

| Change | Operator action today | Effect |
| --- | --- | --- |
| Prompts, skills, agents, instructions, workflow settings | Push and use **Deploy now**, or run CLI deploy | Rebuilds/promotes bundles with no serving pod restarts |
| Local uncommitted workflow edits | Local **Deploy now**, or `sage-run up` again | Reads the working tree and reconciles only changed pod templates |
| Connections/config | Deploy through UI or CLI | Snapshots settings for new tasks and rolls config consumers; not in-place hot reload |
| MCP/connector enablement, source or service config | Deploy through UI or CLI (local: `up`) | Helm reconciles additions/removals; workflow MCP source changes roll only that MCP |
| Platform/runtime image upgrade | Run the desired exact CLI release's deploy | Chart/images come from that package; workflow image overrides take precedence |
| Database/infrastructure change | Reviewed CLI upgrade/migration after backup | Backup is automated, schema/storage/credential migration is not; UI refuses these changes |

CLI and Job deployment do not blanket-restart services. Image/env/config
checksums change the affected pod templates; workflow-only activation leaves
them unchanged. Full hot reload and bounded active-session drain remain open.

Managed instances reject the legacy Sync/pin writers. Production Deploy now
selects `main` or a `v`-prefixed tag; local uses the working tree.
Platform upgrades and recovery remain CLI operations. There is no published
`make deploy`/`make plan` wrapper in the workflow templates yet: use the commands
above rather than assuming such targets exist.

Running tasks retain their launch environment and bundle. Avoid disruptive
deploys during active work: the shared lock serializes deployment/backup
writers, but there is no active-task drain yet.

### Unreleased source: selective reload and deployment diffs

**Not published or deployed to production.** The following capabilities are
implemented in the source tree and are under test. They do not change the
behavior of an installed 1.0.3/1.0.4 CLI, image or production instance.

The first upgrade from the released 1.0.3/1.0.4 chart can trigger a one-time
consumer rollout as workload annotations, rollout strategies and environment
representation change, even without a reloadable configuration change.
Restart-free config/runtime-only guarantees apply **after adoption of the new
chart and runtime**, not to that initial upgrade.

| Change / consumer | Source behavior |
| --- | --- |
| Runtime environment, model profiles, named connections and bundles | Excluded from workload startup hashes; consumers that read these per task use the activated settings for new work without pod restarts |
| Message-bus startup settings | Affect Gateway, Session Manager and message MCP hashes, not unrelated workloads |
| Knowledge startup settings | Affect Gateway, indexer and knowledge MCP hashes, not unrelated workloads |
| Custom MCP policy or source | Rolls that MCP; bundled integration policy refresh does not imply custom MCP hot reload |
| Bundled Salesforce, GitHub, Splunk, CloudWatch and GCP logging MCP policy | Refreshes per HTTP request; reload is deferred while the checkout writer guard exists |
| ServiceNow connector query/configuration and connection credentials | Checks the successful activation revision every second and reloads in the same process, preserving deduplication and pause state |
| Pub/Sub connector configuration | Reconnects in-process only when its own activated connector configuration changes, not for unrelated workflow changes |
| Gateway schedules | The running process reconciles the scheduler from persisted activation without killing existing handlers |
| Runtime-only image selection | Stored in a ConfigMap and read through the Kubernetes API for each new task; no Session Manager rollout solely for that image change |
| Startup-only infrastructure, database pools, providers, service images or environment settings | Still roll the affected services; these settings are not arbitrary in-process reloads |

MCP Deployments use readiness-gated `RollingUpdate` with `maxUnavailable: 0`.
Singleton Session Manager, connector and indexer Deployments use `Recreate`
to avoid overlapping consumers. This is rollout sequencing, **not** atomic
intake drain or a guarantee that all service-changing deploys are interruption-free.
Running tasks retain their launch-time environment, image and bundle.

Local CLI, SSH CLI and deployment Jobs share a secret-safe Helm resource diff,
logging **create / roll / update / delete** actions. Helm is skipped only when
both rendered manifests **and** Helm values are unchanged. Backup and activation
steps still run; unchanged Helm input does not bypass production backup safety.
This execution-time diff is not a full pre-confirmation/live-plan UI or API.

Atomic intake drain, general configuration hot reload, ordered migrations,
runtime resource/network hardening and UI platform-version handover remain
pending. Platform upgrades and migrations remain reviewed CLI/operator work;
no UI upgrade capability is added by these source changes.

## Local workflow and platform development

Arrange sibling checkouts, or pass an explicit platform source:

```text
work/
  sage-run/
  my-workflows/
```

In the platform checkout run `make init` for its development environment.
Enable Rancher Desktop Kubernetes/Moby, verify the `rancher-desktop` context,
and keep checkouts under a path shared into its VM (home directories work;
host `/tmp` is not assumed shared). Ensure Traefik is available on local port
80. Install `kubectl` and Helm on the workstation.

From the workflow checkout:

```sh
# Published platform images, no platform checkout required:
uvx --from 'sage-run==1.0.4' sage-run up . \
  --identity ~/.config/sage-run/dev.agekey

# Test local platform changes without publishing a package or images:
/path/to/sage-run/.venv/bin/python -m sage_run up . \
  --source /path/to/sage-run --identity ~/.config/sage-run/dev.agekey

# Reuse built images for workflow-only iterations:
/path/to/sage-run/.venv/bin/python -m sage_run up . \
  --source /path/to/sage-run --no-build
```

`--no-build` requires the matching development image tag to exist; supply
`--image-tag <existing-tag>` if the source tree has changed since the build.
Local builds use `imagePullPolicy: Never`. There is no automatic image import
into a different cluster's node image store.

The workflow Makefile's `make up` uses `--source ../sage-run` by default.
Set `SAGE_RUN_DIR=/path/to/sage-run` and `SAGE_RUN_SOURCE=/path/to/sage-run` for
another layout. Commands execute from the workflow checkout, so changing
repositories needs no shared environment-file edit.

Namespaces default to `<repo-folder>-dev`; `--instance` supports additional
instances. Routes use `http://<instance>.localhost` through Traefik.
Node-bound UI ports or custom ingress can still conflict. Use distinct ports
or stop the conflicting workload; namespaces do not isolate host ports.

`--identity` or `SAGE_RUN_AGE_IDENTITY_FILE` overrides
`~/.config/sage-run/dev.agekey`. Base configs must be encrypted to that key.
Separate dev integrations are strongly recommended: a development key does
not make production endpoint values safe to use.

```sh
uvx --from 'sage-run==1.0.4' sage-run status .
uvx --from 'sage-run==1.0.4' sage-run down .  # keeps PVCs and Secrets
# --purge deletes the namespace and its data; use only for disposable instances.
```

## Kubernetes compatibility

The workload chart and launcher use standard Deployments, StatefulSets,
Services, Secrets, PVCs and Jobs, but the operator commands are more specific:

| Target | Current status |
| --- | --- |
| Single-node k3s | Qualified production path; remote `deploy` assumes k3s, SSH/sudo and a host checkout |
| Rancher Desktop Kubernetes | Qualified local path |
| k3d/kind | Plausible, but not turnkey or qualified; requires node volume mappings, image import/registry, ingress and port setup |
| GKE/OpenShift | Standard Kubernetes workloads are reusable, but the current operator path needs adaptation and qualification |

k3d/kind qualification and full GKE/OpenShift profiles or multi-node storage
are not v2 completion requirements. This table documents boundaries rather than
claiming unsupported distributions work end to end.

- `deploy` assumes single-node k3s, SSH/sudo and a hostPath checkout.
- `up --context <name>` selects another context, but still assumes a host
  checkout visible on the node, Traefik routing on workstation port 80 for
  the final sync, and locally built images in the node's image store.
- k3d/kind require explicit volume mapping into nodes, registry/image import,
  storage and ingress/port setup. They are not qualified turnkey targets.
- GKE/OpenShift require storage/checkout distribution, scheduling, ingress,
  security policy and runtime adaptation. The chart has
  `workflowRepo.existingClaim`, but current CLIs do not prepare a shared PVC
  checkout. A multi-node hostPath is not shared storage.
- A newer gVisor fixes only one compatibility dependency. GKE-managed runtime
  versions cannot simply be replaced with a host binary; OpenShift SCC/UID
  policies may reject the fixed runtime UID 1000 or local/CI sandbox privileges.
  Qualification must include the actual session image, Bubblewrap and policies.

The production qualification used k3s v1.36.5+k3s1, RuntimeClass `gvisor`
(handler `runsc-pr15008`) and gVisor release-20261019.0 plus PR 15008 commit
`0ee763a`. Stock release-20260714.0 and release-20261019.0 failed the nested
Bubblewrap loopback probe. A full Claude task passed as UID 1000/group 0;
the root task failed. A passing low-level probe or a release containing the
fix does not replace full-task qualification.

GKE Sandbox's managed gVisor is not automatically equivalent to that pinned
runtime; Autopilot's managed runtime and security restrictions also require
separate validation of nested Bubblewrap and the selected pod profile. Neither
has been qualified here. OpenShift's arbitrary-UID/SCC model requires checking
image and volume permissions as well as admission of runtime security settings;
do not assume the fixed UID or weaker local/CI settings will be admitted.
For multi-node clusters, `workflowRepo.existingClaim` is chart-level plumbing,
not automated checkout distribution: provision explicitly shared storage (for
example RWX), placement and permissions. PS production data remains on-premises.

Do not claim production support from successful Helm rendering alone.

## Backups and recovery

Persistent volumes are live storage, not backups. Project-memory archives and
housekeeping are not a full database/object-store disaster-recovery solution.

Managed production deployment enables the nightly CronJob and pre-deployment
backup Job with **7 nightly + 3 deployment copies**. See
[backup operation and limits](#deployment-jobs-and-backups). Instances still
on 1.0.1 have no such automation until upgraded; manual archives remain manual.

Back up:

- Postgres, including `task_queue`, `control_plane` and `hindsight` schemas;
- MinIO/object storage: project memory, bundles and Knowledge Sources;
- Hindsight filesystem assets where applicable;
- encrypted workflow Git history, pinned package/image references, runtime
  configuration and the separately secured age identity.

Use `pg_dump`/`pg_restore` or another consistent database backup, and coordinated
object-store snapshots/exports. Do not copy live Postgres data files as a
backup. Same-disk backups protect against some operator mistakes, not disk/node
loss; copy them to a separately controlled destination and test restoration.

An operator-created cleanup backup can live at
`/var/backups/sage-run/<instance>/<timestamp>-pre-compose-cleanup`.
Keep a database dump, object-store backup and checksums, with any retained
inactive checkouts private. Such a manual directory has no automatic expiry.
Treat all backup contents as sensitive data.

Application housekeeping separately retains project-memory snapshots (defaults:
10 versions, 90 days), archives old tasks and prunes learning memory. See
[Configuration](configuration.md#housekeeping--retention). It does not rotate
the backup directory above.

### Restore qualification

There is no automatic restore CLI. Rehearse in an isolated namespace before
touching serving data: verify every manifest checksum, restore the dump into a
new database with the matching PostgreSQL tools, restore S3 objects and check
their hashes, then restore Hindsight's archive into a fresh PVC. The archive
has a top-level `hindsight/` directory; mount that directory at
`/home/hindsight/.hindsight` (for example using `subPath: hindsight`) and verify
ownership/permissions for the image's runtime user.

For a `WaitForFirstConsumer` storage class, let a scheduled consumer bind a new
PVC; setting a restore Pod's `nodeName` bypasses scheduling and can leave it
unbound. Start a separate Hindsight instance against the restored database and
PVC, and verify its bank-list API plus restored file bytes. The isolated
qualification used fake local embeddings/model responses; it did not send
production data to a model or exercise semantic recall quality.

## Workflow bundles and activation

Bundles merge platform, repository-shared and workflow-specific assets into
one checksummed release. Root `CLAUDE.md` precedence, skills, hooks, approvals,
messaging and secret scrubbing are unchanged; see
[Workflow authoring](workflow-authoring.md#bundle-assembly).

| Runtime contract | Meaning |
| --- | --- |
| `WORKFLOW_BUNDLE_PATH` | Mounted bundle, where supported by the launcher |
| `WORKFLOW_BUNDLE_URI` | Bundle URI, normally a presigned object-store URL on Kubernetes |
| `WORKFLOW_BUNDLE_CHECKSUM` | SHA-256 of the bundle manifest, verified before execution |

The deployment Job fetches the chosen ref through the App (or reads the local
working tree), validates and reconciles services, then activates bundles and
their matching merged config snapshot. Activation uploads a complete release
before advancing its active pointer; new tasks use that immutable release.

### Compatibility policy

Compatibility compares bundle/platform major versions: newer is blocked,
older warns, equal is accepted.

Workflow repository endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/platform/workflow-repo` | Current checkout/release and sync state |
| `POST /api/platform/workflow-repo/sync` | Legacy unmanaged only; managed instances return 410 |
| `POST /api/platform/workflow-repo/pin` | Legacy unmanaged only; managed instances return 410 |
| `GET /api/platform/workflow-repo/versions` | Version choices through the GitHub App |

## Publishing a platform release

1. Update the exact `X.Y.Z` package version and lockfile/chart metadata.
2. Merge to `main` and wait for successful full CI (lint and tests).
3. Publish a GitHub release tagged `vX.Y.Z`. Tag pushes alone do not publish.
4. The release workflow requires green CI at that commit, builds eight amd64/
   arm64 GHCR images, records their digests in `release.json`, packages the
   chart and publishes PyPI after the protected environment approval.

Operator version selects the platform version; the workflow repo does not
yet have an installed dependency lock.
Use exact CLI pins in automation. Never move a published tag or overwrite a
PyPI version; fixes get a new patch release.

PyPI uses Trusted Publishing: project `sage-run`, owner `ops-workflows`,
repository `sage-run`, workflow `release.yml`, environment `pypi`. GHCR uses
the Actions `GITHUB_TOKEN` with package-write permission. All eight SAGE Run
packages must be public for anonymous production pulls. The workflow does not
change package visibility. Multi-registry publication is not atomic; a partial
failure may leave images published without the wheel.

The eight images are `gateway`, `session-manager`, `knowledge-indexer`,
`control-plane-ui`, `mcp`, `gcp-pubsub-connector`, `servicenow-connector` and
`agent-runtime`. Infrastructure images remain upstream dependencies.
Workflows should inherit the pinned runtime; an explicit
`runtime.container_image` overrides it. Bundled third-party software retains
its own licensing and usage terms.
