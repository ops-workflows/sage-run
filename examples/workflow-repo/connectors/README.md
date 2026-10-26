# Connectors

Source connectors read from external systems and write tasks to the platform
task queue. Generic connector implementations (GCP Pub/Sub, ServiceNow) live
in the public platform repo under `connectors/`; a workflow repo only
configures **instances** of them through `platform-config.yaml`, and can add
its own custom connector implementations here.

See [docs/connectors.md](../../../docs/connectors.md) in the platform repo
for the connector model and the full instance schema for each shipped
connector.

## Enabling and configuring an instance

```yaml
connectors:
  enabled:
    - my-connector-instance      # instance ids, not directory names
  instances:
    my-connector-instance:
      type: gcp-pubsub           # a built-in connector type
      source: { ... }
      target: { ... }
      parsing: { ... }
      coalescing: { ... }
```

`connectors.enabled` lists instance ids to run and surfaces them in the
platform connectors catalog. `connectors.instances.<id>` holds the full
instance definition; `${VAR}` placeholders resolve from `config:` values,
`secrets:`, and the process environment at load time. A shipped generic
connector automatically selects its one enabled instance of the matching type.
Set `CONNECTOR_INSTANCE_ID` only when one deployment must select from multiple
enabled instances of that type.

## Adding a custom connector

See [custom-connector-example/](custom-connector-example/) for a minimal
skeleton to copy and adapt:

1. Add `connectors/<name>/main.py` here (or in the platform repo, if it's
   generic enough to be reusable), loading its instance with
   `shared.lib.platform_secrets.load_connector_instance(path, instance_id)`
   and enqueuing tasks via `shared.lib.task_queue.create_task()`.
2. Define one or more instances of it under `connectors.instances` in
   `platform-config.yaml`.
3. Supply an explicit image and reviewed Kubernetes Deployment under
   `deploy/k8s/`, with its instance selector, mounted config and necessary
   Secret references, or add a supported built-in type in the platform.

Unlike workflow MCPs, custom connectors are not automatically discovered or
run from this directory. Built-in types run in separate connector images and
Deployments, not in MCP containers. The current chart creates one Deployment
per enabled type, not per instance; multiple instances of a type need explicit
selection/deployment design.
