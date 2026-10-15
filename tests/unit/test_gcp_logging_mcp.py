"""Unit tests for the GCP Logging MCP platform policy."""

from __future__ import annotations

import base64
import importlib
import json

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

pytestmark = pytest.mark.unit


def _reload_with_policy(monkeypatch, tmp_path):
    config = tmp_path / "platform-config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "mcps": {
                    "config": {
                        "gcp-logging": {
                            "allowed_projects": ["example-prod-1234"],
                            "max_results": 50,
                            "max_window_hours": 6,
                            "max_evidence_bytes": 8192,
                        }
                    }
                }
            }
        )
    )
    monkeypatch.setenv("PLATFORM_CONFIG_FILE", str(config))
    import mcps.integrations.mcp_gcp_logging as gcp_logging

    return importlib.reload(gcp_logging)


def _private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _headers(*, task_id: str = "task-1", project: str = "example-prod-1234", key: str | None = None) -> dict[str, str]:
    info = {
        "type": "service_account",
        "client_email": "reader@example-prod-1234.iam.gserviceaccount.com",
        "private_key": key or "unused",
        "private_key_id": "key-1",
        "token_uri": "https://attacker.example/token",
    }
    # Service account JSON from the console may contain literal newlines inside strings.
    raw = json.dumps(info).replace("\\n", "\n")
    return {
        "x-task-workflow": "online-alerts-investigator",
        "x-task-id": task_id,
        "x-gcp-project-id": project,
        "x-gcp-service-account-b64": base64.b64encode(raw.encode()).decode(),
    }


def test_rejected_requests_do_not_call_gcp_or_consume_budget(monkeypatch, tmp_path) -> None:
    gcp_logging = _reload_with_policy(monkeypatch, tmp_path)
    calls: list[dict] = []
    monkeypatch.setattr(gcp_logging, "_list_entries", lambda _info, body: calls.append(body) or {"entries": []})
    headers = _headers()

    for _ in range(6):
        assert (
            "not allowed" in gcp_logging.search_app_errors("-1h", headers=_headers(project="other-project-1"))["error"]
        )
        assert "6-hour limit" in gcp_logging.search_app_errors("-2d", headers=headers)["error"]
        assert "service name" in gcp_logging.search_app_errors("-1h", service_name='x" OR "y', headers=headers)["error"]
        assert "identifier" in gcp_logging.search_app_errors("-1h", event="a b", headers=headers)["error"]
        assert "safe absolute" in gcp_logging.search_cloud_run_5xx("-1h", path="no-slash", headers=headers)["error"]
        placeholder = {**headers, "x-gcp-service-account-b64": "REPLACE_WITH_BASE64_SERVICE_ACCOUNT_JSON"}
        assert "not configured" in gcp_logging.search_app_errors("-1h", headers=placeholder)["error"]

    assert calls == []
    for _ in range(5):
        assert "error" not in gcp_logging.search_app_errors("-1h", headers=headers)
    with pytest.raises(PermissionError, match=r"GCP Logging MCP task call budget exhausted \(5 calls\)"):
        gcp_logging.search_app_errors("-1h", headers=headers)


def _middleware_entry(timestamp: str, products: str, business_id: str = "1234567-8") -> dict:
    return {
        "timestamp": timestamp,
        "logName": "projects/example-prod-1234/logs/run.googleapis.com%2Fstderr",
        "resource": {"type": "cloud_run_revision", "labels": {"service_name": "api-prod", "revision_name": "r1"}},
        "jsonPayload": {
            "caller": "online-api/internal/api/middleware/logger_middleware.go:38",
            "level": "error",
            "event": "CloudRun5xx",
            "method": "GET",
            "path": "/private/customer-admin/online-models/c6d82fa1-b696-052d-70f0-169f4096d151",
            "status": 500,
            "error": (
                f"Internal Server Error: failed to query bulk prices: Commercial products = {products}, "
                f"account ACC123456 for businessId {business_id}: salesforce call failed with status 500"
            ),
            "email": "user@example.com",
            "clientIP": "203.0.113.7",
            "queryString": "onlineModelCodes=abc",
            "sessionID": "session-secret",
            "user": "someone",
        },
    }


def test_cloud_run_5xx_reads_app_logs_and_groups_failure_reason(monkeypatch, tmp_path) -> None:
    gcp_logging = _reload_with_policy(monkeypatch, tmp_path)
    captured: dict = {}

    def list_entries(_info, body):
        captured.update(body)
        return {
            "entries": [
                _middleware_entry(
                    "2026-10-15T06:43:00Z",
                    "8580c80b-a94d-c632-3742-686b6bd87a14, 83c52d05-533f-84d4-1386-b30f697bcdbe",
                ),
                _middleware_entry(
                    "2026-10-15T06:44:00Z",
                    "911de6ae-085a-d1e9-6351-aaac391bea34, 1de5c141f-20ef-84be-1975-74e26da7c644, 33-b8d6-bcd0-7851",
                    business_id="7654321-9",
                ),
            ],
            "nextPageToken": "next",
        }

    monkeypatch.setattr(gcp_logging, "_list_entries", list_entries)
    result = gcp_logging.search_cloud_run_5xx(
        "2026-10-15T06:30:00+00:00",
        "2026-10-15T07:00:00+00:00",
        service_name="api-prod",
        headers=_headers(),
    )

    assert captured["resourceNames"] == ["projects/example-prod-1234"]
    assert captured["pageSize"] == 50
    assert 'resource.labels.service_name="api-prod"' in captured["filter"]
    assert 'log_id("run.googleapis.com/stderr")' in captured["filter"]
    assert "jsonPayload.status>=500" in captured["filter"]
    assert result["total_results"] == 2
    assert result["warnings"] == ["more_entries_available"]
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    sample = group["samples"][0]
    assert group["count"] == 2
    assert sample["path"] == "/private/customer-admin/online-models/{id}"
    assert sample["status"] == "500"
    assert sample["event"] == "CloudRun5xx"
    assert sample["error"] == (
        "Internal Server Error: failed to query bulk prices: Commercial products = <ids>, "
        "account ACC<n> for businessId <n>: salesforce call failed with status 500"
    )
    serialized = json.dumps(result)
    for leaked in ("user@example.com", "203.0.113.7", "onlineModelCodes", "session-secret", "someone"):
        assert leaked not in serialized


def test_app_errors_filter_reason_logs_not_severity(monkeypatch, tmp_path) -> None:
    gcp_logging = _reload_with_policy(monkeypatch, tmp_path)
    captured: dict = {}

    def list_entries(_info, body):
        captured.update(body)
        return {
            "entries": [
                {
                    "timestamp": f"2026-10-15T06:4{index}:00Z",
                    "resource": {"type": "cloud_run_revision", "labels": {"service_name": "api-prod"}},
                    "jsonPayload": {
                        "caller": "online-api/internal/clients/creditcheck/credit_check_client.go:101",
                        "level": "warn",
                        "error": f'Post "https://credit.example/": context deadline exceeded u{index}@example.com',
                        "response_body": "secret body",
                    },
                }
                for index in range(3)
            ]
        }

    monkeypatch.setattr(gcp_logging, "_list_entries", list_entries)
    result = gcp_logging.search_app_errors("-1h", event="CloudRun5xx", contains='deadline "x"', headers=_headers())

    assert "jsonPayload.error:*" in captured["filter"]
    assert "severity>=" not in captured["filter"]
    assert 'jsonPayload.event="CloudRun5xx"' in captured["filter"]
    assert 'jsonPayload.error:"deadline \\"x\\""' in captured["filter"]
    assert result["groups"][0]["count"] == 3
    assert result["groups"][0]["samples"][0]["level"] == "warn"
    assert "@example.com" not in json.dumps(result)
    assert "secret body" not in json.dumps(result)

    gcp_logging.search_app_errors("-1h", include_warnings=False, headers=_headers(task_id="task-2"))
    assert '(jsonPayload.level="error" OR severity>=ERROR)' in captured["filter"]


def test_access_token_uses_fixed_google_token_endpoint(monkeypatch, tmp_path) -> None:
    gcp_logging = _reload_with_policy(monkeypatch, tmp_path)
    key = _private_key_pem()
    requests: list[tuple[str, dict]] = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"access_token": "token-1", "expires_in": 3600}

    def post(url, data, timeout):
        requests.append((url, data))
        return Response()

    monkeypatch.setattr(gcp_logging.httpx, "post", post)
    info = gcp_logging._service_account(_headers(key=key))

    assert gcp_logging._access_token(info) == "token-1"
    assert gcp_logging._access_token(info) == "token-1"
    assert len(requests) == 1
    url, data = requests[0]
    assert url == "https://oauth2.googleapis.com/token"
    claims = jwt.decode(data["assertion"], options={"verify_signature": False})
    assert claims["aud"] == "https://oauth2.googleapis.com/token"
    assert claims["scope"] == "https://www.googleapis.com/auth/logging.read"
    assert claims["iss"] == "reader@example-prod-1234.iam.gserviceaccount.com"
