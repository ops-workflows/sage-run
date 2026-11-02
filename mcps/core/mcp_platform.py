"""Platform MCP Server — use for internal workflow handoffs and instruction-update PR proposals."""

from __future__ import annotations

import base64
import re
import time
from typing import Annotated, Any

import httpx
from fastmcp import FastMCP
from fastmcp.dependencies import CurrentHeaders
from starlette.responses import JSONResponse

from mcps.common import bootstrap_platform_env, get_env
from shared.lib.github_app import (
    GitHubAppError,
    github_app_connection,
    github_installation_token,
    github_repository_coordinates,
)
from shared.lib.platform_secrets import load_workflow_repo_github_connection

bootstrap_platform_env()

GATEWAY_URL = get_env("GATEWAY_URL", "http://gateway:8080")
WORKFLOW_REPO_URL = get_env("WORKFLOW_REPO_URL", "")
PLATFORM_CONFIG_FILE = get_env("PLATFORM_CONFIG_FILE", "/app/platform-config.yaml")
AGE_IDENTITY = get_env("AGE_IDENTITY", "")

mcp = FastMCP("Platform MCP Server")


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _workflow_github_context() -> tuple[str, str, str, str]:
    connection_name = load_workflow_repo_github_connection(PLATFORM_CONFIG_FILE)
    if not connection_name:
        raise GitHubAppError("github.workflow_repo_connection is required for reflection PRs")
    connection = github_app_connection(
        connection_name,
        platform_config_file=PLATFORM_CONFIG_FILE,
        age_identity=AGE_IDENTITY or None,
    )
    owner, repo = github_repository_coordinates(WORKFLOW_REPO_URL, connection)
    token = github_installation_token(
        connection_name,
        platform_config_file=PLATFORM_CONFIG_FILE,
        age_identity=AGE_IDENTITY or None,
    )
    return connection.api_base_url, owner, repo, token


def _strip_workspace_prefix(file_path: str) -> str:
    normalized = file_path.strip()
    if normalized.startswith("/workspace/"):
        normalized = normalized.removeprefix("/workspace/")
    while normalized.startswith("./"):
        normalized = normalized.removeprefix("./")
    if normalized.startswith(".claude/"):
        normalized = normalized.removeprefix(".claude/")
    return normalized


def _normalize_skill_path(file_path: str, workflow: str | None = None) -> str:
    normalized = _strip_workspace_prefix(file_path)
    workflow_name = (workflow or "").strip().strip("/")
    if (
        workflow_name
        and ".." not in workflow_name
        and "/" not in workflow_name
        and not normalized.startswith("workflows/")
        and (
            normalized == "CLAUDE.md"
            or re.fullmatch(r"agents/[^/]+\.md", normalized)
            or re.fullmatch(r"skills/[^/]+/SKILL\.md", normalized)
        )
    ):
        return f"workflows/{workflow_name}/{normalized}"
    return normalized


def _validate_skill_path(file_path: str) -> None:
    if ".." in file_path or file_path.startswith("/"):
        raise ValueError("Path must be relative and must not contain '..'")
    private_shared_skill = re.fullmatch(r"skills/[^/]+/SKILL\.md", file_path)
    workflow_instruction = re.fullmatch(r"workflows/[^/]+/(?:CLAUDE\.md|agents/[^/]+\.md)", file_path)
    workflow_skill = re.fullmatch(r"workflows/[^/]+/skills/[^/]+/SKILL\.md", file_path)
    if not (private_shared_skill or workflow_instruction or workflow_skill):
        raise ValueError(
            "Updates are limited to workflow instructions/skills or workflow-repo shared skills; "
            "platform-core files are read-only"
        )


@mcp.tool(annotations={"openWorldHint": True})
def create_workflow_task(
    workflow: Annotated[str, "Target workflow name for the new task."],
    prompt: Annotated[str, "Prompt to enqueue for the target workflow."],
    message_channel: Annotated[str | None, "Optional message channel override for the follow-up task."] = None,
    message_thread: Annotated[str | None, "Optional message thread root override for the follow-up task."] = None,
    metadata: Annotated[dict[str, Any] | None, "Optional structured metadata for the created task."] = None,
    headers: dict[str, str] = CurrentHeaders(),
) -> dict[str, Any]:
    """Use this to enqueue a follow-up task in another SAGE Run workflow when visible handoff text is not enough."""
    payload_metadata = dict(metadata or {})
    payload_metadata.setdefault("source", "workflow-handoff")
    if headers.get("x-task-id"):
        payload_metadata.setdefault("source_task_id", headers["x-task-id"])
    if headers.get("x-task-workflow"):
        payload_metadata.setdefault("source_workflow", headers["x-task-workflow"])

    default_channel = headers.get("x-message-channel") or None
    default_thread = headers.get("x-message-thread-id") or None
    if workflow == "documentation":
        default_channel = "documentation"

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{GATEWAY_URL}/tasks",
            json={
                "workflow": workflow,
                "prompt": prompt,
                "channel": "platform",
                "metadata": payload_metadata,
                "message_channel": message_channel or default_channel,
                "message_thread": message_thread or default_thread,
            },
        )
        response.raise_for_status()
        return response.json()


@mcp.tool(annotations={"openWorldHint": True})
def propose_skill_update(
    file_path: Annotated[str, "Repository-relative or workflow-relative path to a skill or agent markdown file."],
    content: Annotated[str, "Complete updated file content."],
    title: Annotated[str, "Short PR title describing the change."],
    description: Annotated[str, "PR body describing the evidence and reasoning for the update."],
    headers: dict[str, str] = CurrentHeaders(),
) -> dict[str, Any]:
    """Use this during reflection to propose a reusable skill or agent update as a GitHub PR."""
    raw_relative = _strip_workspace_prefix(file_path)
    file_path = _normalize_skill_path(file_path, headers.get("x-task-workflow"))
    _validate_skill_path(file_path)
    clean_title = re.sub(r"^(?:\[reflect\]\s*)+", "", title.strip(), flags=re.IGNORECASE)
    pr_title = f"[reflect] {clean_title}" if clean_title else "[reflect] Skill update"
    try:
        api_base_url, owner, repo, token = _workflow_github_context()
    except GitHubAppError as exc:
        return {"error": str(exc)}

    repo_api = f"{api_base_url}/repos/{owner}/{repo}"
    github_headers = _github_headers(token)

    with httpx.Client(timeout=30.0) as client:
        repo_response = client.get(repo_api, headers=github_headers)
        repo_response.raise_for_status()
        default_branch = repo_response.json()["default_branch"]

        ref_response = client.get(f"{repo_api}/git/ref/heads/{default_branch}", headers=github_headers)
        ref_response.raise_for_status()
        base_sha = ref_response.json()["object"]["sha"]

        existing = client.get(
            f"{repo_api}/contents/{file_path}",
            headers=github_headers,
            params={"ref": default_branch},
        )
        if (
            existing.status_code != 200
            and raw_relative != file_path
            and re.fullmatch(r"skills/[^/]+/SKILL\.md", raw_relative)
        ):
            shared_existing = client.get(
                f"{repo_api}/contents/{raw_relative}",
                headers=github_headers,
                params={"ref": default_branch},
            )
            if shared_existing.status_code == 200:
                file_path = raw_relative
                existing = shared_existing
        file_sha = existing.json().get("sha") if existing.status_code == 200 else None

        slug = re.sub(r"[^a-zA-Z0-9-]", "-", file_path.split("/")[-1].replace(".md", ""))
        branch_name = f"reflect/{slug}-{int(time.time())}"
        client.post(
            f"{repo_api}/git/refs",
            headers=github_headers,
            json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        ).raise_for_status()

        file_payload: dict[str, Any] = {
            "message": clean_title or title,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch_name,
        }
        if file_sha:
            file_payload["sha"] = file_sha

        client.put(
            f"{repo_api}/contents/{file_path}",
            headers=github_headers,
            json=file_payload,
        ).raise_for_status()

        source_info = []
        if headers.get("x-task-id"):
            source_info.append(f"Task: `{headers['x-task-id']}`")
        if headers.get("x-task-workflow"):
            source_info.append(f"Workflow: `{headers['x-task-workflow']}`")
        source_section = "\n".join(source_info) if source_info else "Manual reflection"
        pr_body = (
            f"{description}\n\n---\n**Source**: {source_section}\n"
            "**Auto-generated** by agent reflection - requires human review before merge."
        )

        pr_response = client.post(
            f"{repo_api}/pulls",
            headers=github_headers,
            json={
                "title": pr_title,
                "head": branch_name,
                "base": default_branch,
                "body": pr_body,
            },
        )
        pr_response.raise_for_status()
        pr_data = pr_response.json()

    return {
        "status": "pr_created",
        "pr_number": pr_data["number"],
        "pr_url": pr_data["html_url"],
        "branch": branch_name,
        "file_path": file_path,
    }


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):
    return JSONResponse({"status": "ok", "service": "mcp-platform"})


app = mcp.http_app(path="/mcp", transport="streamable-http", stateless_http=False)
