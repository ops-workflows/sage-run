"""Deploy a workflow repository commit to a remote single-node k3s host over SSH.

Everything secret stays on the host: the instance Secret is built there from
the host's age key (``/etc/sage-run/<instance>/age.key``), which decrypts the
infrastructure secrets in the committed config. The laptop sends the commit (as
a git bundle), the chart and secret-free Helm values.
"""

from __future__ import annotations

import io
import json
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sage_run.deployment import EXTRA_KINDS, extra_manifests, job_manifest, owned_extras, validate_ref
from sage_run.local import (
    BOOTSTRAP_SECRET,
    INFRASTRUCTURE_SECRETS,
    PLATFORM_COMPONENTS,
    RELEASE_NAME,
    Instance,
    _chart_path,
    instance_name,
    release_images,
    render_values,
)
from shared.lib.platform_config import load_platform_config

KEY_DIR = "/etc/sage-run"
STATE_DIR = "/var/lib/sage-run"
KUBECONFIG = "/etc/rancher/k3s/k3s.yaml"
HELM_VERSION = "v4.0.5"

# Runs on the host with root: decrypts infrastructure secrets with the host key and
# applies the instance Secret. Reads {"namespace", "key", "ciphertexts"} from stdin.
_INSTANCE_KEY_PROGRAM = r"""
import base64, json, secrets, subprocess, sys
request = json.load(sys.stdin)
kubectl = ["k3s", "kubectl", "-n", request["namespace"]]
identity = [line for line in open(request["key"]).read().splitlines() if line.startswith("AGE-SECRET-KEY-")]
if len(identity) != 1:
    sys.exit("host key file must contain exactly one AGE-SECRET-KEY")
data = {}
existing = subprocess.run(kubectl + ["get", "secret", request["secret"], "-o", "json", "--ignore-not-found"],
                          capture_output=True, text=True, check=True).stdout
if existing.strip():
    data = {k: base64.b64decode(v).decode() for k, v in (json.loads(existing).get("data") or {}).items()}
for name, ciphertext in request["ciphertexts"].items():
    blob = base64.b64decode(ciphertext[len("ENC[age,"):-1])
    data[name] = subprocess.run(["age", "-d", "-i", request["key"]], input=blob, capture_output=True,
                                check=True).stdout.decode()
if "LLM_API_KEY" not in data:
    sys.exit("config has no LLM_API_KEY secret for this environment")
for name in ("PG_PASSWORD", "OBJECT_STORE_SECRET_KEY"):
    data.setdefault(name, secrets.token_urlsafe(24))
data["AGE_IDENTITY"] = identity[0]
manifest = {"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
            "metadata": {"name": request["secret"], "namespace": request["namespace"]}, "stringData": data}
subprocess.run(kubectl + ["apply", "-f", "-"], input=json.dumps(manifest), text=True, check=True,
               stdout=subprocess.DEVNULL)
print("instance secret updated:", ", ".join(sorted(data)))
"""


def _git(repo: Path, *args: str, capture: bool = True, binary: bool = False) -> str | bytes:
    result = subprocess.run(  # noqa: S603 - fixed git invocation
        [shutil.which("git") or "git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
        check=True,
        capture_output=capture,
        text=not binary,
    )
    return result.stdout


def _ssh(host: str, command: str, *, stdin: bytes | str | None = None, capture: bool = False) -> str:
    data = stdin.encode() if isinstance(stdin, str) else stdin
    result = subprocess.run(  # noqa: S603 - fixed ssh invocation
        [shutil.which("ssh") or "ssh", "-o", "BatchMode=yes", host, command],
        input=data,
        check=True,
        capture_output=capture,
    )
    return result.stdout.decode() if capture else ""


def materialise(workflow_repo: Path, commit: str, target: Path) -> None:
    archive = _git(workflow_repo, "archive", "--format=tar", commit, binary=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(target, filter="data")


def infrastructure_ciphertexts(config: dict) -> dict[str, str]:
    platform_secrets = config.get("secrets") or {}
    ciphertexts: dict[str, str] = {}
    for name in INFRASTRUCTURE_SECRETS:
        value = str((platform_secrets.get(name) or {}).get("encrypted") or "")
        if value.startswith("ENC[age,"):
            ciphertexts[name] = value
    if "LLM_API_KEY" not in ciphertexts:
        raise ValueError("platform config has no encrypted LLM_API_KEY for this environment")
    return ciphertexts


def remote_values(instance: Instance, config: dict, *, checkout: str, repo_url: str, ref: str, version: str) -> dict:
    values = render_values(instance, config)
    values["workflowRepo"] = {
        "hostPath": checkout,
        "source": "remote" if repo_url else "local",
        "url": repo_url,
        "ref": ref,
    }
    values["ingress"] = {"enabled": False}
    values["deployer"] = {"enabled": True}
    values["backups"] = {
        "enabled": True,
        "hostPath": f"/var/backups/sage-run/{instance.name}/managed",
    }
    ui = (config.get("deployment") or {}).get("ui") or {}
    if ui:
        values["controlPlaneUi"] = {"hostIP": str(ui.get("host_ip") or ""), "hostPort": int(ui.get("host_port") or 0)}
    if not values.get("images"):
        values["images"] = release_images(version)
    return values


def ensure_helm(host: str) -> None:
    script = f"""set -e
if command -v helm >/dev/null && helm version --short | grep -q '^{HELM_VERSION}'; then exit 0; fi
tmp=$(mktemp -d)
curl -fsSL -o $tmp/helm.tgz https://get.helm.sh/helm-{HELM_VERSION}-linux-amd64.tar.gz
curl -fsSL -o $tmp/helm.tgz.sha256sum https://get.helm.sh/helm-{HELM_VERSION}-linux-amd64.tar.gz.sha256sum
(cd $tmp && sed 's#  .*#  helm.tgz#' helm.tgz.sha256sum | sha256sum -c -)
tar -xzf $tmp/helm.tgz -C $tmp linux-amd64/helm
sudo install -m 0755 $tmp/linux-amd64/helm /usr/local/bin/helm
rm -rf $tmp
"""
    _ssh(host, script)


@contextmanager
def remote_deploy_lock(host: str, checkout: str, *, plan_only: bool) -> Iterator[None]:
    if plan_only:
        yield
        return
    path = shlex.quote(checkout)
    guard = shlex.quote(f"{checkout}/.git/sage-run-deploy.lock.d")
    holder = (
        f"lock={guard}; "
        'mkdir "$lock" || { echo "Deployment/backup lock exists; if stale, stop all writers before removing it" >&2; '
        "exit 1; }; "
        """trap 'rmdir "$lock"' EXIT; trap 'exit 1' HUP INT TERM; echo locked; cat >/dev/null"""
    )
    script = (
        f"set -e; sudo mkdir -p {path}; "
        f"if ! sudo test -d {path}/.git; then sudo git -C {path} init -q; fi; "
        f"sudo sh -c {shlex.quote(holder)}"
    )
    process = subprocess.Popen(  # noqa: S603 - fixed SSH command, quoted host checkout
        [shutil.which("ssh") or "ssh", "-o", "BatchMode=yes", host, script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        if process.stdout is None or process.stdout.readline().strip() != "locked":
            raise ValueError("Cannot acquire deployment lock; another deployment/backup may be running")
        yield
    finally:
        if process.stdin:
            process.stdin.close()
        process.wait(timeout=30)
        if process.stdout:
            process.stdout.close()


def pre_deploy_backup(host: str, namespace: str, values: dict, *, remote_tmp: str) -> None:
    kubectl = f"sudo k3s kubectl -n {shlex.quote(namespace)}"
    raw = _ssh(host, f"{kubectl} get deployment gateway -o json --ignore-not-found", capture=True)
    if not raw.strip():
        claims = json.loads(_ssh(host, f"{kubectl} get pvc -o json", capture=True))["items"]
        if claims:
            raise ValueError("Existing PVCs without a Gateway need explicit recovery, not an unbacked first install")
        print("First install: no existing Gateway/data to back up", flush=True)
        return
    gateway = json.loads(raw)
    pods = json.loads(_ssh(host, f"{kubectl} get pods -l app.kubernetes.io/component=gateway -o json", capture=True))[
        "items"
    ]
    nodes = {pod["spec"].get("nodeName") for pod in pods if not pod["metadata"].get("deletionTimestamp")}
    if len(nodes) != 1 or None in nodes:
        raise ValueError("Cannot identify the serving node for the deployment backup")
    gateway["metadata"].setdefault("annotations", {})["sage-run/node"] = nodes.pop()
    current = json.loads(
        _ssh(
            host,
            f"sudo helm get values {RELEASE_NAME} -n {shlex.quote(namespace)} --kubeconfig {KUBECONFIG} --all -o json",
            capture=True,
        )
    )
    hindsight_enabled = current["infrastructure"]["hindsight"]["enabled"]
    container = gateway["spec"]["template"]["spec"]["containers"][0]
    container["env"] = [
        item
        for item in container.get("env", [])
        if item["name"] not in {"SAGE_RUN_BACKUP_HOST_PATH", "SAGE_RUN_BACKUP_HINDSIGHT"}
    ] + [
        {"name": "SAGE_RUN_BACKUP_HOST_PATH", "value": values["backups"]["hostPath"]},
        {"name": "SAGE_RUN_BACKUP_HINDSIGHT", "value": str(hindsight_enabled).lower()},
    ]
    job = job_manifest(gateway, namespace=namespace, ref="main")
    job["metadata"]["labels"] = {"sage-run/backup": "deployment"}
    name = job["metadata"]["name"]
    desired_images = values["images"]
    image = (desired_images.get("overrides") or {}).get("gateway")
    if not image:
        registry = desired_images.get("registry", "ghcr.io/ops-workflows")
        prefix = desired_images.get("prefix", "sage-run-")
        image = f"{registry + '/' if registry else ''}{prefix}gateway:{desired_images['tag']}"
    backup = job["spec"]["template"]["spec"]["containers"][0]
    backup["image"] = image
    backup["imagePullPolicy"] = desired_images.get("pullPolicy", "IfNotPresent")
    backup["command"] = [
        "python",
        "-c",
        "from pathlib import Path; from shared.lib.config import settings; "
        "from sage_run.backups import create_backup; "
        "create_backup(namespace=settings.kubernetes_namespace, kind='deployment', "
        "checkout=Path(settings.workflow_repo_local_path))",
    ]
    # Install only namespace RBAC before backup; no serving state is changed.
    _ssh(
        host,
        f"set -e; sudo helm template {RELEASE_NAME} {shlex.quote(remote_tmp)}/chart "
        f"-n {shlex.quote(namespace)} -f {shlex.quote(remote_tmp)}/values.json "
        f"--show-only templates/deployer-rbac.yaml | {kubectl} apply -f -",
    )
    _ssh(host, f"{kubectl} create -f -", stdin=json.dumps(job))
    print(f"Verifying pre-deployment backup Job {name}", flush=True)
    deadline = time.monotonic() + 3600
    while time.monotonic() < deadline:
        state = json.loads(_ssh(host, f"{kubectl} get job {name} -o json", capture=True)).get("status") or {}
        conditions = state.get("conditions") or []
        failed = any(item["type"] == "Failed" and item["status"] == "True" for item in conditions)
        complete = any(item["type"] == "Complete" and item["status"] == "True" for item in conditions)
        if failed or complete:
            _ssh(host, f"{kubectl} logs job/{name} --tail=100")
            if failed:
                raise ValueError("Pre-deployment backup failed; serving checkout and release were not changed")
            return
        time.sleep(3)
    raise ValueError(f"Backup Job {name} did not finish; inspect it before retrying")


def deploy(
    workflow_repo: Path,
    *,
    host: str,
    environment: str,
    ref: str,
    name: str | None,
    image_tag: str | None,
    version: str,
    plan_only: bool = False,
) -> int:
    ref = validate_ref(ref, remote=True)
    workflow_repo = workflow_repo.expanduser().resolve()
    commit = str(_git(workflow_repo, "rev-parse", "--verify", f"{ref}^{{commit}}")).strip()
    repo_url = str(_git(workflow_repo, "remote", "get-url", "origin")).strip() if _has_origin(workflow_repo) else ""
    if repo_url:
        published = str(_git(workflow_repo, "ls-remote", "origin", ref)).split()
        if commit not in published[0::2]:
            message = f"{ref} on origin is not {commit[:12]}; push it first (Gateway sync fetches from origin)"
            if not plan_only:
                raise ValueError(message)
            print(f"warning: {message}")
    instance = Instance(workflow_repo, instance_name(workflow_repo, name or workflow_repo.name), local=False)
    instance.environment = environment
    instance.sandbox_profile = ""
    key_file = f"{KEY_DIR}/{instance.name}/age.key"
    checkout = f"{STATE_DIR}/{instance.name}/workflow-repo"

    with tempfile.TemporaryDirectory() as temporary, remote_deploy_lock(host, checkout, plan_only=plan_only):
        tree = Path(temporary) / "tree"
        materialise(workflow_repo, commit, tree)
        config = load_platform_config(tree / "platform-config.yaml", environment=environment)
        instance.workflow_repo = tree
        if image_tag:
            instance.images = {"registry": "", "tag": image_tag, "pullPolicy": "Never"}
        values = remote_values(instance, config, checkout=checkout, repo_url=repo_url, ref=ref, version=version)
        ciphertexts = infrastructure_ciphertexts(config)
        print(
            f"Deploy {commit[:12]} ({ref}) of {workflow_repo.name} to {host} as {instance.name} [env={environment}]",
            flush=True,
        )
        print(f"  checkout {checkout}; key {key_file}; images {values['images']}", flush=True)
        print(f"  workflow MCPs: {', '.join(values['workflowMcps']) or 'none'}", flush=True)
        if plan_only:
            return 0

        _ssh(host, f"sudo test -f {key_file} || {{ echo 'missing host key {key_file}' >&2; exit 1; }}")
        ensure_helm(host)
        remote_tmp = _ssh(host, "mktemp -d", capture=True).strip()
        bundle = io.BytesIO()
        with tarfile.open(fileobj=bundle, mode="w:gz") as tar:
            tar.add(_chart_path(None), arcname="chart")
            payload = json.dumps(values).encode()
            info = tarfile.TarInfo("values.json")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        _ssh(host, f"tar -xzf - -C {remote_tmp}", stdin=bundle.getvalue())

        namespace = shlex.quote(instance.name)
        kubectl = f"sudo k3s kubectl -n {namespace}"
        _ssh(
            host,
            f"sudo k3s kubectl create namespace {namespace} --dry-run=client -o yaml | sudo k3s kubectl apply -f -",
        )
        extras = extra_manifests(tree, host_checkout=checkout, namespace=instance.name)
        live = json.loads(_ssh(host, f"{kubectl} get {','.join(EXTRA_KINDS)} -o json", capture=True))
        old_extras = owned_extras(live["items"], instance.name, desired=extras)
        if any(kind == "PersistentVolumeClaim" for kind, _ in old_extras.keys() - extras.keys()):
            raise ValueError("Removing an extra PVC requires an explicit storage migration")
        pre_deploy_backup(host, instance.name, values, remote_tmp=remote_tmp)
        sync_checkout(workflow_repo, host, commit, checkout, repo_url)
        request = json.dumps(
            {"namespace": instance.name, "key": key_file, "secret": BOOTSTRAP_SECRET, "ciphertexts": ciphertexts}
        )
        _ssh(
            host,
            f"sudo python3 -c {shlex.quote(_INSTANCE_KEY_PROGRAM)}",
            stdin=request,
        )
        _ssh(
            host,
            f"set -e; sudo helm upgrade --install {RELEASE_NAME} {remote_tmp}/chart --kubeconfig {KUBECONFIG} "
            f"--namespace {namespace} -f {remote_tmp}/values.json --wait --timeout 15m; rm -rf {remote_tmp}",
        )
        for kind, extra_name in old_extras.keys() - extras.keys():
            _ssh(host, f"{kubectl} delete {kind} {shlex.quote(extra_name)}")
        for key, document in extras.items():
            _ssh(host, f"{kubectl} apply -f -", stdin=json.dumps(document))
            print(f"  applied {key[0]}/{key[1]}", flush=True)
        selector = f"app.kubernetes.io/component in ({','.join(PLATFORM_COMPONENTS)})"
        _ssh(host, f"{kubectl} rollout status deployment -l {shlex.quote(selector)} --timeout=10m")
        _ssh(
            host,
            f"{kubectl} exec deploy/gateway -- python -c "
            + shlex.quote(
                "import asyncio; from sage_run.incluster import activate_checkout; "
                f"asyncio.run(activate_checkout({ref!r})); print('workflows activated')"
            ),
        )
    print(f"Deployed {commit[:12]} to {instance.name} on {host}", flush=True)
    return 0


def _has_origin(workflow_repo: Path) -> bool:
    remotes = str(_git(workflow_repo, "remote")).split()
    return "origin" in remotes


def sync_checkout(workflow_repo: Path, host: str, commit: str, checkout: str, repo_url: str) -> None:
    """Move the host checkout to ``commit`` from a git bundle (no clone credentials needed)."""
    ref = "refs/sage-run/deploy"
    _git(workflow_repo, "update-ref", ref, commit)
    try:
        bundle = _git(workflow_repo, "bundle", "create", "-", ref, binary=True)
    finally:
        _git(workflow_repo, "update-ref", "-d", ref)
    quoted = shlex.quote(checkout)
    url = shlex.quote(repo_url)
    set_origin = (
        f"sudo git remote add origin {url} 2>/dev/null || sudo git remote set-url origin {url}" if repo_url else "true"
    )
    script = f"""set -e
sudo mkdir -p {quoted}
cd {quoted}
sudo git config --global --add safe.directory {quoted} 2>/dev/null || true
[ -d .git ] || sudo git init -q
tmp=$(mktemp); cat > $tmp
sudo git fetch -q $tmp {ref}:{ref}
rm -f $tmp
sudo git checkout -q --force --detach {commit}
sudo git clean -q -fdx
{set_origin}
echo "checkout at $(sudo git rev-parse --short=12 HEAD)"
"""
    _ssh(host, script, stdin=bundle)
