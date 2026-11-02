"""Unit tests for workflow-repository PR proposal controls."""

from __future__ import annotations

import pytest

from mcps.core import mcp_platform
from shared.lib.github_app import GitHubAppError
from shared.lib.platform_secrets import GitHubAppConnection

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("workflow_repo_url", "connection", "expected"),
    [
        (
            "https://github.com/acme/corp-workflows.git",
            GitHubAppConnection("public", "https://github.com", "https://api.github.com", "1", "2", "key"),
            ("https://api.github.com", "acme", "corp-workflows", "installation-token"),
        ),
        (
            "https://github.company.example/acme/corp-workflows",
            GitHubAppConnection(
                "enterprise",
                "https://github.company.example",
                "https://github.company.example/api/v3",
                "3",
                "4",
                "key",
            ),
            ("https://github.company.example/api/v3", "acme", "corp-workflows", "installation-token"),
        ),
    ],
)
def test_workflow_github_context_uses_selected_connection(monkeypatch, workflow_repo_url, connection, expected):
    monkeypatch.setattr(mcp_platform, "WORKFLOW_REPO_URL", workflow_repo_url)
    monkeypatch.setattr(mcp_platform, "load_workflow_repo_github_connection", lambda path: connection.name)
    monkeypatch.setattr(mcp_platform, "github_app_connection", lambda *args, **kwargs: connection)
    monkeypatch.setattr(mcp_platform, "github_installation_token", lambda *args, **kwargs: "installation-token")
    assert mcp_platform._workflow_github_context() == expected


def test_workflow_github_context_rejects_repo_on_other_host(monkeypatch):
    connection = GitHubAppConnection("public", "https://github.com", "https://api.github.com", "1", "2", "key")
    monkeypatch.setattr(mcp_platform, "WORKFLOW_REPO_URL", "https://other.example/acme/workflows.git")
    monkeypatch.setattr(mcp_platform, "load_workflow_repo_github_connection", lambda path: connection.name)
    monkeypatch.setattr(mcp_platform, "github_app_connection", lambda *args, **kwargs: connection)
    with pytest.raises(GitHubAppError, match="does not belong"):
        mcp_platform._workflow_github_context()


@pytest.mark.parametrize(
    "file_path",
    [
        "skills/private-shared/SKILL.md",
        "workflows/example-workflow/agents/coordinator.md",
        "workflows/example-workflow/CLAUDE.md",
        "workflows/example-workflow/skills/triage/SKILL.md",
    ],
)
def test_validate_skill_path_allows_only_private_workflow_repo_content(file_path):
    mcp_platform._validate_skill_path(file_path)


@pytest.mark.parametrize(
    "file_path",
    [
        "skills/reflect/README.md",
        "workflows/example-workflow/README.md",
        "../skills/private-shared/SKILL.md",
        "CLAUDE.md",
    ],
)
def test_validate_skill_path_rejects_non_updatable_paths(file_path):
    with pytest.raises(ValueError, match="relative|platform-core files are read-only"):
        mcp_platform._validate_skill_path(file_path)


@pytest.mark.parametrize(
    ("raw_path", "workflow", "expected"),
    [
        (
            "skills/query-plans/SKILL.md",
            "platform-ops-assistant",
            "workflows/platform-ops-assistant/skills/query-plans/SKILL.md",
        ),
        (
            "./skills/query-plans/SKILL.md",
            "platform-ops-assistant",
            "workflows/platform-ops-assistant/skills/query-plans/SKILL.md",
        ),
        (
            ".claude/skills/query-plans/SKILL.md",
            "platform-ops-assistant",
            "workflows/platform-ops-assistant/skills/query-plans/SKILL.md",
        ),
        (
            "/workspace/skills/query-plans/SKILL.md",
            "platform-ops-assistant",
            "workflows/platform-ops-assistant/skills/query-plans/SKILL.md",
        ),
        (
            "agents/ops-inventory-resolver.md",
            "platform-ops-assistant",
            "workflows/platform-ops-assistant/agents/ops-inventory-resolver.md",
        ),
        (
            ".claude/agents/ops-inventory-resolver.md",
            "platform-ops-assistant",
            "workflows/platform-ops-assistant/agents/ops-inventory-resolver.md",
        ),
        ("CLAUDE.md", "platform-ops-assistant", "workflows/platform-ops-assistant/CLAUDE.md"),
        (
            "workflows/platform-ops-assistant/skills/query-plans/SKILL.md",
            "platform-ops-assistant",
            "workflows/platform-ops-assistant/skills/query-plans/SKILL.md",
        ),
        ("skills/private-shared/SKILL.md", None, "skills/private-shared/SKILL.md"),
    ],
)
def test_normalize_skill_path_prefixes_workflow_when_present(raw_path, workflow, expected):
    normalized = mcp_platform._normalize_skill_path(raw_path, workflow)
    assert normalized == expected
    mcp_platform._validate_skill_path(normalized)


def test_propose_skill_update_prefixes_workflow_path_and_deduplicates_title(monkeypatch):
    monkeypatch.setattr(
        mcp_platform,
        "_workflow_github_context",
        lambda: ("https://api.github.com", "acme", "corp-workflows", "token"),
    )
    put_calls = []
    pr_calls = []

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None, params=None):
            if url == "https://api.github.com/repos/acme/corp-workflows":
                return FakeResponse(200, {"default_branch": "main"})
            if url == "https://api.github.com/repos/acme/corp-workflows/git/ref/heads/main":
                return FakeResponse(200, {"object": {"sha": "base-sha"}})
            if (
                url
                == "https://api.github.com/repos/acme/corp-workflows/contents/workflows/platform-ops-assistant/skills/query-plans/SKILL.md"
            ):
                return FakeResponse(200, {"sha": "existing-skill-sha"})
            return FakeResponse(404, {})

        def post(self, url, headers=None, json=None):
            if url.endswith("/pulls"):
                pr_calls.append(json)
                return FakeResponse(201, {"number": 7, "html_url": "https://github.com/acme/corp-workflows/pull/7"})
            return FakeResponse(201, {})

        def put(self, url, headers=None, json=None):
            put_calls.append((url, json))
            return FakeResponse(200, {})

    monkeypatch.setattr(mcp_platform.httpx, "Client", FakeClient)

    result = mcp_platform.propose_skill_update(
        file_path="skills/query-plans/SKILL.md",
        content="# Updated\n",
        title="[reflect] query-plans: tighten role filter",
        description="Observed in weekly traces.",
        headers={"x-task-id": "task-1", "x-task-workflow": "platform-ops-assistant"},
    )

    assert result["status"] == "pr_created"
    assert result["file_path"] == "workflows/platform-ops-assistant/skills/query-plans/SKILL.md"
    assert len(put_calls) == 1
    assert put_calls[0][0].endswith("/contents/workflows/platform-ops-assistant/skills/query-plans/SKILL.md")
    assert put_calls[0][1]["sha"] == "existing-skill-sha"
    assert put_calls[0][1]["message"] == "query-plans: tighten role filter"
    assert pr_calls[0]["title"] == "[reflect] query-plans: tighten role filter"


def test_propose_skill_update_falls_back_to_existing_shared_repo_skill(monkeypatch):
    monkeypatch.setattr(
        mcp_platform,
        "_workflow_github_context",
        lambda: ("https://api.github.com", "acme", "corp-workflows", "token"),
    )
    put_calls = []

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers=None, params=None):
            if url == "https://api.github.com/repos/acme/corp-workflows":
                return FakeResponse(200, {"default_branch": "main"})
            if url == "https://api.github.com/repos/acme/corp-workflows/git/ref/heads/main":
                return FakeResponse(200, {"object": {"sha": "base-sha"}})
            if url == "https://api.github.com/repos/acme/corp-workflows/contents/skills/team-shared/SKILL.md":
                return FakeResponse(200, {"sha": "shared-skill-sha"})
            return FakeResponse(404, {})

        def post(self, url, headers=None, json=None):
            if url.endswith("/pulls"):
                return FakeResponse(201, {"number": 8, "html_url": "https://github.com/acme/corp-workflows/pull/8"})
            return FakeResponse(201, {})

        def put(self, url, headers=None, json=None):
            put_calls.append((url, json))
            return FakeResponse(200, {})

    monkeypatch.setattr(mcp_platform.httpx, "Client", FakeClient)

    result = mcp_platform.propose_skill_update(
        file_path="skills/team-shared/SKILL.md",
        content="# Updated shared\n",
        title="team-shared: update guidance",
        description="Shared skill update.",
        headers={"x-task-id": "task-2", "x-task-workflow": "platform-ops-assistant"},
    )

    assert result["file_path"] == "skills/team-shared/SKILL.md"
    assert put_calls[0][0].endswith("/contents/skills/team-shared/SKILL.md")
    assert put_calls[0][1]["sha"] == "shared-skill-sha"
