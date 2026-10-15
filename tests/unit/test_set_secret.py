import shutil
import subprocess
import sys
from pathlib import Path

import pyrage
import pytest
import yaml

from shared.lib.crypto import decrypt_secret

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("target", ["set-platform-secret", "set-workflow-secret"])
def test_make_secret_accepts_large_value_from_stdin(tmp_path, monkeypatch, target):
    identity = str(pyrage.x25519.Identity.generate())
    monkeypatch.setenv("AGE_IDENTITY", identity)
    workflow_dir = tmp_path / "workflows" / "example-workflow"
    workflow_dir.mkdir(parents=True)
    platform_file = tmp_path / "platform-config.yaml"
    agent_file = workflow_dir / "agent.yaml"
    platform_file.write_text("secrets: {}\n")
    agent_file.write_text("name: example-workflow\nsecrets: {}\n")
    secret_value = "A" * 6000

    result = subprocess.run(  # noqa: S603
        [
            shutil.which("make"),
            "--no-print-directory",
            "-C",
            str(Path(__file__).resolve().parents[2]),
            target,
            f"MAKE={shutil.which('true')}",
            f"PYTHON={sys.executable}",
            f"HOST_WORKFLOW_REPO_PATH={tmp_path}",
            "WORKFLOW=example-workflow",
            "SECRET_NAME=EXAMPLE_API_TOKEN",
            "SECRET_VALUE_FILE=/dev/stdin",
        ],
        input=secret_value,
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )

    target_file = platform_file if target == "set-platform-secret" else agent_file
    encrypted = yaml.safe_load(target_file.read_text())["secrets"]["EXAMPLE_API_TOKEN"]["encrypted"]
    assert encrypted.startswith("ENC[age,")
    assert decrypt_secret(encrypted, identity=identity) == secret_value
    assert "Secret name:" not in result.stdout + result.stderr
    assert "Secret value:" not in result.stdout + result.stderr
    assert secret_value not in result.stdout + result.stderr
