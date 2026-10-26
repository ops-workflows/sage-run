# Contributing

Thanks for contributing to SAGE Run.

## Public Core Boundary

This repository is the public platform core. Contributions should not include:

- Company-specific workflows
- Customer names, hostnames, channels, or incident examples
- Plaintext secrets, tokens, private keys, or encrypted secrets from a private deployment
- Private connector implementations

Put workflow-specific assets in a workflow repository and test them through bundle assembly.

## Development Checks

Run focused tests for the area you changed, then the unit suite:

```sh
python -m pytest -q tests/unit
```

Run lint and formatting checks:

```sh
python -m ruff check .
python -m ruff format --check .
```

For UI changes:

```sh
cd control-plane-ui
npm ci
npm run build
```

For deployment changes, render templates where possible:

```sh
helm template sage-run sage_run/chart \
  --set workflowRepo.hostPath=/tmp/workflows \
  >/tmp/sage-run-helm.yaml
```

For an actual local instance, run `sage-run up` from the workflow checkout,
optionally with `--source /path/to/sage-run`. See
[Deployment](docs/deployment.md) for Rancher Desktop prerequisites and current
portability limits. The platform Makefile manages tests and builds, not a
serving stack. Its only Compose manifest is the isolated Postgres fixture at
`tests/compose.yaml`; Docker runtime helpers live in
`tests/runtime/docker_support.py` and are injected by test fixtures.

## Workflow Bundle Checks

Use the bundle CLI to validate workflow repo changes:

```sh
python scripts/build_workflow_bundle.py my-workflow \
  --workflow-root /path/to/workflow-repo \
  --output /tmp/sage-run-bundles
```

Bundle validation rejects plaintext-looking secrets. Store sensitive values through encrypted config or deployment secret managers.

## Pull Requests

Please include:

- What behavior changed
- What public/private boundary was affected
- What validation commands passed
- Any deployment or migration notes
