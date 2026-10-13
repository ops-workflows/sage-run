from __future__ import annotations

import json
import stat
from http.client import HTTPConnection
from io import BytesIO
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlencode

import pytest

from scripts import create_github_app as setup

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://github.com/acme/", ("https://github.com", "acme")),
        ("ghes.example/Platform-Ops", ("https://ghes.example", "Platform-Ops")),
        ("https://ghes.example/organizations/acme/settings/apps", ("https://ghes.example", "acme")),
        ("https://ghes.example/organizations/acme/settings/apps/existing", ("https://ghes.example", "acme")),
    ],
)
def test_parse_organization(value, expected):
    assert setup.parse_organization(value) == expected


@pytest.mark.parametrize(
    "value",
    ["http://github.com/acme", "https://user:secret@ghes.example/acme", "https://github.com/acme/repo", "acme"],
)
def test_invalid_organization(value):
    with pytest.raises(ValueError, match="organization URL"):
        setup.parse_organization(value)


def test_manifest_matches_reference_permissions_without_webhooks_or_oauth():
    manifest = setup.build_manifest("sage-ops", "https://ghes.example/acme", "http://127.0.0.1:8765/callback")
    assert manifest["default_permissions"] == {
        "contents": "write",
        "issues": "write",
        "metadata": "read",
        "pull_requests": "write",
    }
    assert manifest["default_events"] == []
    assert manifest["public"] is False
    assert manifest["hook_attributes"]["active"] is False
    assert manifest["request_oauth_on_install"] is False


@pytest.mark.parametrize("base", ["https://github.com", "https://ghes.example"])
def test_conversion_uses_correct_host_without_authentication(monkeypatch, base):
    calls = []

    def fake_open(request, timeout):
        calls.append(request)
        assert timeout == 30
        return BytesIO(b'{"id": 123, "pem": "test-private-key"}')

    monkeypatch.setattr(setup, "urlopen", fake_open)
    assert setup.convert_manifest(base, "test-code")["id"] == 123
    assert calls[0].full_url == setup.api_base_url(base) + "/app-manifests/test-code/conversions"
    assert calls[0].method == "POST"
    assert not calls[0].has_header("Authorization")


def test_conversion_error_does_not_expose_code_or_response(monkeypatch):
    def fake_open(request, timeout):
        raise HTTPError(request.full_url, 422, "private-response", {}, BytesIO(b"secret"))

    monkeypatch.setattr(setup, "urlopen", fake_open)
    with pytest.raises(RuntimeError) as caught:
        setup.convert_manifest("https://github.com", "private-code")
    assert "HTTP 422" in str(caught.value)
    assert "private" not in str(caught.value)
    assert "secret" not in str(caught.value)


def test_credentials_saved_privately_without_overwriting(tmp_path: Path):
    payload = {
        "id": 123,
        "slug": "sage-ops",
        "pem": "test-private-key",
        "client_secret": "test-client-secret",
        "html_url": "https://ghes.example/github-apps/sage-ops",
    }
    setup.save_credentials(tmp_path, "https://ghes.example", "acme", payload)
    for filename in ("credentials.json", "private-key.pem", "connection.json"):
        assert stat.S_IMODE((tmp_path / filename).stat().st_mode) == 0o600
    assert json.loads((tmp_path / "credentials.json").read_text()) == payload
    connection = json.loads((tmp_path / "connection.json").read_text())
    assert connection["api_base_url"] == "https://ghes.example/api/v3"
    assert connection["installation_id"] is None
    assert connection["installation_url"] == "https://ghes.example/github-apps/sage-ops/installations/new"
    assert "test-private-key" not in json.dumps(connection)
    with pytest.raises(FileExistsError):
        setup.save_credentials(tmp_path, "https://ghes.example", "acme", payload)


def local_request(server, target, headers=None):
    worker = Thread(target=server.handle_request)
    worker.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        connection.request("GET", target, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read().decode(), dict(response.getheaders())
    finally:
        connection.close()
        worker.join(timeout=2)
        assert not worker.is_alive()


def test_loopback_form_and_callback_validate_state_and_do_not_log_codes(capsys):
    with setup.RegistrationServer("https://ghes.example", "acme", "<sage & ops>", 0) as server:
        assert server.server_address[0] == "127.0.0.1"
        status_code, body, headers = local_request(server, server.start_path)
        assert status_code == 200
        assert "https://ghes.example/organizations/acme/settings/apps/new?state=" in body
        assert "&lt;sage &amp; ops&gt;" in body
        assert headers["Cache-Control"] == "no-store"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert local_request(server, "/callback?state=wrong&code=private-code")[0] == 400
        assert local_request(server, "/callback?state=%C3%A9&code=private-code")[0] == 400
        assert server.code is None
        state = server.start_path.rsplit("/", 1)[1]
        target = "/callback?" + urlencode({"state": state, "code": "private-code"})
        assert local_request(server, target, {"Host": "attacker.example"})[0] == 403
        assert local_request(server, target + "&code=duplicate")[0] == 400
        status_code, body, _ = local_request(server, target)
        assert status_code == 200
        assert "private-code" not in body
        assert server.wait_for_code(1) == "private-code"
        assert local_request(server, target)[0] == 400
    assert capsys.readouterr().err == ""


def test_callback_timeout(monkeypatch):
    with setup.RegistrationServer("https://github.com", "acme", "sage", 0) as server:
        clock = iter([0, 2])
        monkeypatch.setattr(setup.time, "monotonic", lambda: next(clock))
        with pytest.raises(RuntimeError, match="timed out"):
            server.wait_for_code(1)


def test_output_directory_is_private_and_never_reused(tmp_path):
    directory = setup.create_output_directory(str(tmp_path / "app"), "https://ghes.example", "acme")
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    with pytest.raises(FileExistsError):
        setup.create_output_directory(str(directory), "https://ghes.example", "acme")


def test_default_output_is_outside_checkout_and_unique(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.Path, "home", lambda: tmp_path)
    first = setup.create_output_directory(None, "https://github.com", "acme")
    second = setup.create_output_directory(None, "https://github.com", "acme")
    assert first != second
    assert first.parent == tmp_path / ".config/sage-run/github-apps/github.com"
    assert stat.S_IMODE(first.stat().st_mode) == 0o700


def test_main_cancellation_does_not_register_or_write(monkeypatch, tmp_path):
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    destination = tmp_path / "app"
    assert setup.main(["--org", "github.com/acme", "--name", "sage", "--output-dir", str(destination)]) == 0
    assert not destination.exists()


def test_main_completes_with_mocked_github_without_printing_secrets(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    monkeypatch.setattr(setup.RegistrationServer, "wait_for_code", lambda self, timeout: "private-code")
    payload = {
        "id": 123,
        "slug": "sage",
        "pem": "test-private-key",
        "client_secret": "test-client-secret",
        "html_url": "https://github.com/apps/sage",
    }
    monkeypatch.setattr(setup, "convert_manifest", lambda base, code: payload)
    destination = tmp_path / "app"
    assert (
        setup.main(
            [
                "--org",
                "github.com/acme",
                "--name",
                "sage",
                "--output-dir",
                str(destination),
                "--port",
                "0",
                "--no-browser",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Created App ID: 123" in output
    assert "test-private-key" not in output
    assert "test-client-secret" not in output
    assert "private-code" not in output
    assert (destination / "private-key.pem").read_text() == "test-private-key"
