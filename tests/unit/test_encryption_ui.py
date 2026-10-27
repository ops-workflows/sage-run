"""The UI receives only the running environment recipient; ciphertext is age interoperable."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from pyrage import x25519

from gateway.main import app
from shared.lib.config import _apply_platform_secret_defaults, settings
from shared.lib.crypto import decrypt_secret

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["", "prod"])
async def test_key_endpoint_returns_only_active_public_metadata(monkeypatch, environment):
    identity = x25519.Identity.generate()
    public_key = str(identity.to_public())
    monkeypatch.setattr(settings, "age_public_key", public_key)
    monkeypatch.setenv("SAGE_RUN_ENV", environment)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/platform/encryption-key")
        assert response.status_code == 200
        assert response.json() == {"public_key": public_key, "environment": environment or "dev"}
        assert str(identity) not in response.text
        assert (await client.post("/api/platform/encryption-key", json={"value": "no-write-api"})).status_code == 405


@pytest.mark.asyncio
@pytest.mark.parametrize("public_key", ["", "age1invalid"])
async def test_missing_or_invalid_recipient_fails_explicitly(monkeypatch, public_key):
    monkeypatch.setattr(settings, "age_public_key", public_key)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/platform/encryption-key")
    assert response.status_code == 503
    assert "no valid age public key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_key_is_not_exposed_while_a_deployment_can_change_it(monkeypatch, tmp_path):
    guard = tmp_path / ".git/sage-run-deploy.lock.d"
    guard.mkdir(parents=True)
    monkeypatch.setattr(settings, "workflow_repo_local_path", str(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/platform/encryption-key")
    assert response.status_code == 409
    assert "retry encryption" in response.json()["detail"]


@pytest.mark.asyncio
async def test_public_recipient_uses_startup_prod_overlay_not_pending_checkout(monkeypatch, tmp_path):
    dev_key = str(x25519.Identity.generate().to_public())
    prod_key = str(x25519.Identity.generate().to_public())
    base = tmp_path / "platform-config.yaml"
    overlay = tmp_path / "platform-config-prod.yaml"
    base.write_text(f"config:\n  AGE_PUBLIC_KEY: {dev_key}\n")
    overlay.write_text(f"config:\n  AGE_PUBLIC_KEY: {prod_key}\n")
    monkeypatch.setenv("SAGE_RUN_ENV", "prod")
    monkeypatch.delenv("AGE_PUBLIC_KEY", raising=False)
    monkeypatch.setattr(settings, "platform_config_file", str(base))
    monkeypatch.setattr(settings, "age_public_key", "")
    monkeypatch.setattr(settings, "_message_bus", settings.message_bus)
    _apply_platform_secret_defaults()
    overlay.write_text(f"config:\n  AGE_PUBLIC_KEY: {dev_key}\n")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/platform/encryption-key")
    assert response.json() == {"public_key": prod_key, "environment": "prod"}


def test_browser_ciphertext_decrypts_with_platform_pyrage():
    ui = Path(__file__).resolve().parents[2] / "control-plane-ui"
    if not shutil.which("node") or not (ui / "node_modules/age-encryption").is_dir():
        pytest.skip("Node and UI dependencies required for browser/Python interoperability")
    identity = x25519.Identity.generate()
    plaintext = "  token\npässword 🔑\n"
    script = """
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const { plaintext, publicKey } = JSON.parse(readFileSync(0, 'utf8'));
const source = readFileSync('src/lib/secret-encryption.ts', 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText.replace("'age-encryption'", JSON.stringify(import.meta.resolve('age-encryption')));
const { encryptSecret } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
console.log(await encryptSecret(plaintext, publicKey));
"""
    result = subprocess.run(  # noqa: S603 - fixed test script, synthetic data on stdin
        [shutil.which("node"), "--input-type=module", "-e", script],
        cwd=ui,
        input=json.dumps({"plaintext": plaintext, "publicKey": str(identity.to_public())}),
        text=True,
        capture_output=True,
        check=True,
    )
    assert decrypt_secret(result.stdout.strip(), identity=str(identity)) == plaintext
