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
from pathlib import Path

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
        [shutil.which("git") or "git", "-C", str(repo), *args], check=True, capture_output=capture, text=not binary
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

    with tempfile.TemporaryDirectory() as temporary:
        tree = Path(temporary) / "tree"
        materialise(workflow_repo, commit, tree)
        config = load_platform_config(tree / "platform-config.yaml", environment=environment)
        instance.workflow_repo = tree
        if image_tag:
            instance.images = {"registry": "", "tag": image_tag, "pullPolicy": "Never"}
        values = remote_values(instance, config, checkout=checkout, repo_url=repo_url, ref=ref, version=version)
        ciphertexts = infrastructure_ciphertexts(config)
        print(f"Deploy {commit[:12]} ({ref}) of {workflow_repo.name} to {host} as {instance.name} [env={environment}]", flush=True)
        print(f"  checkout {checkout}; key {key_file}; images {values['images']}", flush=True)
        print(f"  workflow MCPs: {', '.join(values['workflowMcps']) or 'none'}", flush=True)
        if plan_only:
            return 0

        _ssh(host, f"sudo test -f {key_file} || {{ echo 'missing host key {key_file}' >&2; exit 1; }}")
        ensure_helm(host)
        sync_checkout(workflow_repo, host, commit, checkout, repo_url)

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
            f"sudo helm upgrade --install {RELEASE_NAME} {remote_tmp}/chart --kubeconfig {KUBECONFIG} "
            f"--namespace {namespace} -f {remote_tmp}/values.json --wait --timeout 15m; rm -rf {remote_tmp}",
        )
        for manifest in sorted((tree / "deploy/k8s").glob("*.yaml")):
            rendered = manifest.read_text(encoding="utf-8").replace("${WORKFLOW_REPO_PATH}", checkout)
            _ssh(host, f"{kubectl} apply -f -", stdin=rendered)
            print(f"  applied {manifest.name}", flush=True)
        selector = f"app.kubernetes.io/component in ({','.join(PLATFORM_COMPONENTS)})"
        _ssh(host, f"{kubectl} rollout restart deployment -l {shlex.quote(selector)} >/dev/null")
        _ssh(host, f"{kubectl} rollout status deployment -l {shlex.quote(selector)} --timeout=10m")
        _ssh(
            host,
            f"{kubectl} exec deploy/gateway -- python -c "
            + shlex.quote(
                "import httpx; r = httpx.post('http://127.0.0.1:8080/api/platform/workflow-repo/sync', timeout=300); "
                "r.raise_for_status(); print('workflows synced')"
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
