import subprocess
import sys
from pathlib import Path

import pyrage
import pytest
import yaml

from shared.lib.crypto import decrypt_secret

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("connection", [None, "integration"])
def test_secret_cli_accepts_large_value_from_stdin(tmp_path, connection):
    key = pyrage.x25519.Identity.generate()
    identity = str(key)
    platform_file = tmp_path / "platform-config.yaml"
    platform_file.write_text(f"config:\n  AGE_PUBLIC_KEY: {key.to_public()}\nsecrets: {{}}\n")
    secret_value = "A" * 6000

    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "sage_run",
            "secret",
            "set",
            str(tmp_path),
            "--name",
            "EXAMPLE_API_TOKEN",
            "--value-file",
            "/dev/stdin",
            *(["--connection", connection] if connection else []),
        ],
        cwd=Path(__file__).resolve().parents[2],
        input=secret_value,
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )

    config = yaml.safe_load(platform_file.read_text())
    target = config["connections"][connection] if connection else config
    encrypted = target["secrets"]["EXAMPLE_API_TOKEN"]["encrypted"]
    assert encrypted.startswith("ENC[age,")
    assert decrypt_secret(encrypted, identity=identity) == secret_value
    assert "Secret name:" not in result.stdout + result.stderr
    assert "Secret value:" not in result.stdout + result.stderr
    assert secret_value not in result.stdout + result.stderr
