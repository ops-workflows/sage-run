# Kubernetes deployment

Use the workflow checkout as the instance. Configuration and encrypted secrets
live in its platform-config files; no separate values file or combined MCP
image is needed.

Follow [Deployment and operations](../../../docs/deployment.md) before running
these commands: replace template values, configure models/integrations and
encrypt every secret to the correct environment key.

## Local development

Prerequisites: Rancher Desktop Kubernetes with Moby and Traefik, shared
home-directory checkout paths, `kubectl`, Helm and `dev.agekey` in the
workflow repository root (gitignored).

```sh
# Published platform:
uvx --from 'sage-run==1.0.4' sage-run up .
# Local platform changes, no registry or PyPI publish:
/path/to/sage-run/.venv/bin/python -m sage_run up . --source /path/to/sage-run
```

The example Makefile defaults to a sibling `../sage-run`; run `make init` in
that checkout, then `make up` here. Set `SAGE_RUN_DIR` and `SAGE_RUN_SOURCE`
for a different layout. Workflows use the base config and mounted working tree.
`make down` keeps volumes; do not use `--purge` for valuable data.

## First production install and later updates

Prepare a single-node k3s host with qualified gVisor and a root-only key at
`/etc/sage-run/<instance>/age.key`. Configure the production overlay's public
recipient and re-encrypt every base secret for it. Commit and push the ref.

```sh
uvx --from 'sage-run==1.0.4' sage-run deploy . \
  --host my-agent --instance my-workflows --env prod --ref main --plan
uvx --from 'sage-run==1.0.4' sage-run deploy . \
  --host my-agent --instance my-workflows --env prod --ref main
```

The workstation sends the commit over SSH into the host's sole serving
checkout. It does not require a server-side clone or PAT. Later workflow
fetches use the configured GitHub App.

Put instance-owned ingress or other reviewed manifests under `deploy/k8s/`.
CLI deploy applies `*.yaml` there with `${WORKFLOW_REPO_PATH}` replaced by the
host checkout. No generic public ingress is included: provision TLS and
authentication for your environment. Managed extra manifests receive an
ownership label and are pruned when removed from Git. Existing unowned
resources need explicit reviewed adoption; PVC deletion needs migration.

MCP enablement comes from `mcps.enabled`; workflow MCP modules are read from
`mcps/*/mcp_*.py` using the platform image. Built-in connectors have separate
images/Deployments. Custom connector skeletons are authoring examples, not
automatically deployed services.

## Current limits

- UI **Deploy now** handles workflow/config/topology updates through an independent
  Job with persisted status/logs. Platform-version upgrades remain CLI-only.
- Prompt-only changes restart no pods; workflow MCP source changes roll only
  that MCP. Config changes roll consumers; full hot reload and task drain
  remain unfinished.
- Production deploy backs up before apply and keeps 3 deployment copies;
  the 02:00 UTC nightly CronJob keeps 7 nightly copies. Each rotates its own
  category. Backups remain same-disk, not a cross-service atomic snapshot.
- There is no `make deploy`/`make plan` wrapper yet. Use explicit pinned CLI
  commands; review the main guide's stale-lock and recovery instructions.
- GKE, OpenShift and k3d need storage, runtime, image and ingress adaptation;
  `--context` alone does not make them qualified targets.
