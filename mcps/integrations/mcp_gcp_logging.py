"""GCP Logging MCP Server — use for read-only Cloud Logging evidence behind GCP Cloud Monitoring alerts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
import jwt
from fastmcp import FastMCP
from fastmcp.dependencies import CurrentHeaders
from starlette.responses import JSONResponse

from mcps.common import bootstrap_platform_env
from mcps.evidence import compile_redaction_patterns, fit_evidence_budget, redact_text
from shared.lib.platform_secrets import load_mcp_server_config
from shared.lib.task_call_budget import TaskCallBudget

bootstrap_platform_env()

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105 - public OAuth endpoint, not a credential
ENTRIES_LIST_URL = "https://logging.googleapis.com/v2/entries:list"
LOGGING_READ_SCOPE = "https://www.googleapis.com/auth/logging.read"
PROJECT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
SERVICE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
EVENT_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
APP_LOG_FILTER = '(log_id("run.googleapis.com/stderr") OR log_id("run.googleapis.com/stdout"))'
# Only these structured payload fields are projected; identity, client, query, and session fields are dropped.
SAFE_PAYLOAD_FIELDS = ("caller", "level", "event", "method", "path", "status", "attempt", "retryCount")
_CONFIG_PATH = os.environ.get("PLATFORM_CONFIG_FILE", "/app/platform-config.yaml")
_POLICY = load_mcp_server_config(_CONFIG_PATH, "gcp-logging")
_EVIDENCE_POLICY = load_mcp_server_config(_CONFIG_PATH, "evidence")
_REDACTION_PATTERNS = compile_redaction_patterns(_EVIDENCE_POLICY.get("redaction_patterns"))
ALLOWED_PROJECTS = frozenset(str(value) for value in _POLICY.get("allowed_projects", []) if str(value).strip())
MAX_RESULTS = max(1, min(int(_POLICY.get("max_results") or 200), 1_000))
MAX_WINDOW_SECONDS = max(1, min(int(_POLICY.get("max_window_hours") or 24), 168)) * 3_600
MAX_EVIDENCE_BYTES = max(8_192, min(int(_POLICY.get("max_evidence_bytes") or 65_536), 262_144))
REQUEST_TIMEOUT_SEC = 20.0
MAX_EVIDENCE_GROUPS = 20
MAX_ERROR_CHARS = 600
_ANY_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
# Applications sometimes log truncated or concatenated UUIDs; three or more hex segments are treated as one ID.
_HEX_FRAGMENT_RE = re.compile(r"\b[0-9a-f]+(?:-[0-9a-f]+){3,}\b", re.I)
_HEX_ID_RE = re.compile(r"\b[0-9a-f]{24,64}\b", re.I)
_ID_LIST_RE = re.compile(r"<id>(?:\s*,\s*<id>)+")
_LONG_NUMBER_RE = re.compile(r"\d{5,}(?:-\d\b)?")
_PATH_RE = re.compile(r"^/[^\s?#]{0,1024}$")
ONLINE_ALERTS_WORKFLOW = "online-alerts-investigator"
ONLINE_ALERTS_GCP_CALL_LIMIT = 5
task_call_budget = TaskCallBudget(
    limit=ONLINE_ALERTS_GCP_CALL_LIMIT,
    max_tasks=10_000,
    resource_name="GCP Logging MCP",
    exhausted_instruction="Return the provider evidence already collected; do not retry.",
)
_token_cache: dict[str, tuple[str, float]] = {}
_token_lock = threading.Lock()

mcp = FastMCP("GCP Logging MCP Server")


def _header(headers: dict[str, str] | Any, name: str) -> str:
    return str(headers.get(name, "")).strip() if isinstance(headers, dict) else ""


def _enforce_online_alert_budget(headers: dict[str, str] | Any) -> None:
    if _header(headers, "x-task-workflow").lower() == ONLINE_ALERTS_WORKFLOW and _header(headers, "x-task-id"):
        task_call_budget.consume(_header(headers, "x-task-id"))


def _project(headers: dict[str, str]) -> str:
    project = _header(headers, "x-gcp-project-id")
    if not PROJECT_PATTERN.fullmatch(project):
        raise ValueError("x-gcp-project-id must be a GCP project ID")
    if project not in ALLOWED_PROJECTS:
        raise ValueError("GCP project is not allowed by platform policy")
    return project


def _service_account(headers: dict[str, str]) -> dict[str, str]:
    encoded = _header(headers, "x-gcp-service-account-b64")
    try:
        info = json.loads(base64.b64decode(encoded, validate=True), strict=False)
    except (binascii.Error, ValueError):
        raise ValueError("GCP service account credentials are not configured for this workflow") from None
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise ValueError("GCP credentials must be a service account key")
    if not all(isinstance(info.get(key), str) and info[key] for key in ("client_email", "private_key")):
        raise ValueError("GCP service account key is missing client_email or private_key")
    return info


def _access_token(info: dict[str, str]) -> str:
    cache_key = hashlib.sha256(f"{info['client_email']}\x1f{info.get('private_key_id', '')}".encode()).hexdigest()
    now = time.time()
    with _token_lock:
        cached = _token_cache.get(cache_key)
        if cached and cached[1] - 60 > now:
            return cached[0]
    issued = int(now)
    assertion = jwt.encode(
        {
            "iss": info["client_email"],
            "scope": LOGGING_READ_SCOPE,
            "aud": TOKEN_URI,
            "iat": issued,
            "exp": issued + 3600,
        },
        info["private_key"],
        algorithm="RS256",
        headers={"kid": info["private_key_id"]} if info.get("private_key_id") else None,
    )
    response = httpx.post(
        TOKEN_URI,
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        timeout=REQUEST_TIMEOUT_SEC,
    )
    if response.status_code != 200:
        raise PermissionError(f"GCP token exchange failed with HTTP {response.status_code}")
    payload = response.json()
    token = str(payload.get("access_token") or "")
    if not token:
        raise PermissionError("GCP token exchange returned no access token")
    with _token_lock:
        if len(_token_cache) >= 32:
            _token_cache.clear()
        _token_cache[cache_key] = (token, now + int(payload.get("expires_in") or 3600))
    return token


def _list_entries(info: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(
        ENTRIES_LIST_URL,
        json=body,
        headers={"Authorization": f"Bearer {_access_token(info)}"},
        timeout=REQUEST_TIMEOUT_SEC,
    )
    if response.status_code != 200:
        try:
            message = str(response.json().get("error", {}).get("message") or "")
        except ValueError:
            message = ""
        raise PermissionError(f"GCP Logging API returned HTTP {response.status_code}: {_redact(message)[:300]}")
    return response.json()


def _parse_time(value: str, now: float) -> float | None:
    candidate = value.strip()
    if candidate == "now":
        return now
    relative = re.fullmatch(r"-(\d{1,4})([mhd])", candidate)
    if relative:
        return now - int(relative.group(1)) * {"m": 60, "h": 3_600, "d": 86_400}[relative.group(2)]
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.timestamp() if parsed.tzinfo else None


def _time_range(start_time: str, end_time: str) -> tuple[str, str] | str:
    now = time.time()
    start = _parse_time(start_time, now)
    end = _parse_time(end_time, now)
    if start is None or end is None:
        return "GCP times must be relative (-15m, -1h, -1d), now, or ISO 8601 with a timezone"
    end = min(end, now)
    if start >= end:
        return "GCP start time must be before end time"
    if end - start > MAX_WINDOW_SECONDS:
        return f"GCP time window exceeds the {MAX_WINDOW_SECONDS // 3_600}-hour limit"

    def iso(value: float) -> str:
        return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")

    return iso(start), iso(end)


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _redact(value: Any) -> str:
    return redact_text(value, _REDACTION_PATTERNS)


def _canonical_ids(value: str) -> str:
    value = _HEX_ID_RE.sub("<id>", _HEX_FRAGMENT_RE.sub("<id>", value))
    return _LONG_NUMBER_RE.sub("<n>", _ID_LIST_RE.sub("<ids>", value))


def _path_template(path: str) -> str:
    path = path.split("?", 1)[0].split("#", 1)[0]
    return re.sub(r"/(?=\d+(?:/|$))\d+", "/{id}", _ANY_UUID_RE.sub("{id}", _HEX_ID_RE.sub("{id}", path)))


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    labels = entry.get("resource", {}).get("labels", {}) if isinstance(entry.get("resource"), dict) else {}
    labels = labels if isinstance(labels, dict) else {}
    payload = entry.get("jsonPayload") if isinstance(entry.get("jsonPayload"), dict) else {}
    raw_error = payload.get("error") or payload.get("message") or entry.get("textPayload") or ""
    error = _redact(_canonical_ids(str(raw_error)))
    fields = {name: _redact(_canonical_ids(str(payload[name]))) for name in SAFE_PAYLOAD_FIELDS if name in payload}
    if "path" in fields:
        fields["path"] = _path_template(str(payload["path"]))
    return {
        "timestamp": str(entry.get("timestamp") or ""),
        "service": str(labels.get("service_name") or ""),
        "revision": str(labels.get("revision_name") or ""),
        "message": _redact(_canonical_ids(str(payload.get("message") or "")))[:200],
        "error": error[:MAX_ERROR_CHARS],
        "error_truncated": len(error) > MAX_ERROR_CHARS,
        **fields,
    }


def compact_gcp_evidence(
    entries: list[dict[str, Any]],
    *,
    request: dict[str, Any],
    truncated_by_page: bool,
    max_samples_per_group: int,
) -> dict[str, Any]:
    """Group structured application log entries into bounded, redacted occurrence summaries."""
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        row = _normalize_entry(entry)
        key = tuple(
            str(row.get(name, ""))
            for name in ("service", "caller", "event", "level", "method", "path", "status", "error")
        )
        grouped.setdefault(key, []).append(row)

    groups = []
    for members in grouped.values():
        ordered = sorted(members, key=lambda item: item["timestamp"])
        groups.append(
            {
                "count": len(members),
                "first_seen": ordered[0]["timestamp"],
                "last_seen": ordered[-1]["timestamp"],
                "samples": ordered[: max(1, min(max_samples_per_group, 5))],
            }
        )
    groups.sort(key=lambda group: (-group["count"], group["first_seen"]))
    bundle = {
        "schema_version": 1,
        "provider": "gcp-logging",
        "request": request,
        "total_results": len(entries),
        "groups": groups[:MAX_EVIDENCE_GROUPS],
        "warnings": ["more_entries_available"] if truncated_by_page else [],
        "truncated": truncated_by_page
        or len(groups) > MAX_EVIDENCE_GROUPS
        or any(sample["error_truncated"] for group in groups for sample in group["samples"]),
    }
    return fit_evidence_budget(bundle, MAX_EVIDENCE_BYTES)


def _search(
    filters: list[str],
    *,
    headers: dict[str, str],
    start_time: str,
    end_time: str,
    limit: int,
    samples_per_group: int,
    request: dict[str, Any],
) -> dict[str, Any]:
    window = _time_range(start_time, end_time)
    if isinstance(window, str):
        return {"error": window, "groups": []}
    try:
        project = _project(headers)
        info = _service_account(headers)
    except ValueError as exc:
        return {"error": str(exc), "groups": []}
    _enforce_online_alert_budget(headers)
    start_iso, end_iso = window
    query = " AND ".join([*filters, f'timestamp>="{start_iso}"', f'timestamp<="{end_iso}"'])
    page_size = max(1, min(limit, MAX_RESULTS))
    try:
        response = _list_entries(
            info,
            {
                "resourceNames": [f"projects/{project}"],
                "filter": query,
                "orderBy": "timestamp asc",
                "pageSize": page_size,
            },
        )
    except (httpx.HTTPError, PermissionError, ValueError, jwt.PyJWTError) as exc:
        return {"error": f"GCP Logging request failed: {exc}", "groups": []}
    entries = response.get("entries") if isinstance(response.get("entries"), list) else []
    return compact_gcp_evidence(
        entries,
        request={**request, "project": project, "start_time": start_iso, "end_time": end_iso, "filter": query},
        truncated_by_page=bool(response.get("nextPageToken")),
        max_samples_per_group=samples_per_group,
    )


def _service_filters(service_name: str | None) -> list[str] | str:
    filters = ['resource.type="cloud_run_revision"', APP_LOG_FILTER]
    if service_name:
        if not SERVICE_NAME_PATTERN.fullmatch(service_name):
            return "service_name must be an exact Cloud Run service name"
        filters.append(f"resource.labels.service_name={_quote(service_name)}")
    return filters


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def search_app_errors(
    start_time: Annotated[
        str,
        "Start derived from the alert Started at time, as ISO 8601 with timezone or relative time.",
    ],
    end_time: Annotated[str, "End time as ISO 8601 with timezone or now; future values are clamped to now."] = "now",
    service_name: Annotated[str | None, "Optional exact Cloud Run service name; omit for the primary query."] = None,
    event: Annotated[
        str | None, "Optional exact jsonPayload.event marker counted by a log-based alert metric, such as CloudRun5xx."
    ] = None,
    include_warnings: Annotated[
        bool, "Include warn-level application errors such as retried downstream timeouts."
    ] = True,
    contains: Annotated[
        str | None, "Optional exact text from one observed error signature for a single correlation."
    ] = None,
    limit: Annotated[int, "Maximum log entries to group, capped by platform policy."] = 100,
    samples_per_group: Annotated[int, "Redacted samples retained per occurrence group, maximum 5."] = 2,
    headers: dict[str, str] = CurrentHeaders(),
) -> dict[str, Any]:
    """Group structured application error logs that carry the failure reason; Cloud Run request logs only carry the status."""
    filters = _service_filters(service_name)
    if isinstance(filters, str):
        return {"error": filters, "groups": []}
    filters.append("jsonPayload.error:*")
    if event:
        if not EVENT_PATTERN.fullmatch(event):
            return {"error": "event must be an identifier such as CloudRun5xx", "groups": []}
        filters.append(f"jsonPayload.event={_quote(event)}")
    if not include_warnings:
        filters.append('(jsonPayload.level="error" OR severity>=ERROR)')
    if contains:
        if len(contains) > 200 or any(char in contains for char in "\r\n"):
            return {"error": "contains must be one line of at most 200 characters", "groups": []}
        filters.append(f"jsonPayload.error:{_quote(contains)}")
    return _search(
        filters,
        headers=headers,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        samples_per_group=samples_per_group,
        request={"tool": "search_app_errors"},
    )


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def search_cloud_run_5xx(
    start_time: Annotated[
        str,
        "Start derived from the alert Started at time, as ISO 8601 with timezone or relative time.",
    ],
    end_time: Annotated[str, "End time as ISO 8601 with timezone or now; future values are clamped to now."] = "now",
    service_name: Annotated[str | None, "Optional exact Cloud Run service name; omit for the primary query."] = None,
    path: Annotated[str | None, "Optional exact request path prefix for one endpoint correlation."] = None,
    limit: Annotated[int, "Maximum log entries to group, capped by platform policy."] = 100,
    samples_per_group: Annotated[int, "Redacted samples retained per occurrence group, maximum 5."] = 2,
    headers: dict[str, str] = CurrentHeaders(),
) -> dict[str, Any]:
    """Group application request logs with HTTP status 500 or higher by endpoint, status, and logged failure reason."""
    filters = _service_filters(service_name)
    if isinstance(filters, str):
        return {"error": filters, "groups": []}
    filters.append("jsonPayload.status>=500")
    if path:
        if not _PATH_RE.fullmatch(path):
            return {"error": "path must be a safe absolute request path", "groups": []}
        filters.append(f"jsonPayload.path:{_quote(path)}")
    return _search(
        filters,
        headers=headers,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        samples_per_group=samples_per_group,
        request={"tool": "search_cloud_run_5xx"},
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):
    return JSONResponse({"status": "ok", "service": "mcp-gcp-logging"})


app = mcp.http_app(path="/mcp", transport="streamable-http", stateless_http=False)
