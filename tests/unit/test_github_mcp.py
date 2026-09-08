"""Unit tests for bounded read-only GitHub MCP behavior."""

from __future__ import annotations

import base64
import importlib
import json

import pytest

from shared.lib.platform_secrets import GitHubAppConnection

pytestmark = pytest.mark.unit


def _reload_with_policy(monkeypatch, tmp_path):
    config = tmp_path / "platform-config.yaml"
    config.write_text(
        """mcps:
  config:
    github:
      allowed_hosts: [api.github.com, github.example.com]
      max_results: 5
      max_excerpt_lines: 20
"""
    )
    monkeypatch.setenv("PLATFORM_CONFIG_FILE", str(config))
    import mcps.integrations.mcp_github as github

    return importlib.reload(github)


def _configure_connection(github, monkeypatch, *, api_base_url="https://api.github.com") -> None:
    connection = GitHubAppConnection(
        "public",
        "https://github.com",
        api_base_url,
        "1",
        "2",
        "private-key",
    )
    monkeypatch.setattr(github, "github_app_connection", lambda *args, **kwargs: connection)
    monkeypatch.setattr(github, "github_installation_token", lambda *args, **kwargs: "installation-token")


def _headers(*, issue_write: bool = False) -> dict[str, str]:
    return {
        "x-github-repositories": json.dumps(
            {
                "online": {
                    "connection": "public",
                    "owner": "example",
                    "repo": "online",
                    "allowed_paths": ["src", "deploy"],
                    "issue_write": issue_write,
                }
            }
        ),
    }


def test_repository_context_rejects_unknown_alias_host_and_path(monkeypatch, tmp_path) -> None:
    github = _reload_with_policy(monkeypatch, tmp_path)
    _configure_connection(github, monkeypatch)

    with pytest.raises(ValueError, match="not configured"):
        github._parse_repository_context(_headers(), "unknown")

    _configure_connection(github, monkeypatch, api_base_url="https://untrusted.example.com/api/v3")
    with pytest.raises(ValueError, match="not allowed"):
        github._parse_repository_context(_headers(), "online")

    _configure_connection(github, monkeypatch)
    parsed = github._parse_repository_context(_headers(), "online")
    with pytest.raises(ValueError, match="outside"):
        github._validate_path(parsed, "private/secret.py")


def test_resolve_commit_and_pinned_excerpt(monkeypatch, tmp_path) -> None:
    github = _reload_with_policy(monkeypatch, tmp_path)
    _configure_connection(github, monkeypatch)
    sha = "a" * 40

    def request(_context, path, *, method="GET", params=None, json_body=None):
        if "/commits/" in path:
            return {"sha": sha, "html_url": "https://github.com/example/online/commit/a", "commit": {"message": "fix"}}
        assert path.endswith("/contents/src/app.py")
        assert params == {"ref": sha}
        return {"encoding": "base64", "content": base64.b64encode(b"one\ntwo\nthree\n").decode()}

    monkeypatch.setattr(github, "_request", request)

    resolved = github.resolve_commit("online", "main", headers=_headers())
    excerpt = github.get_file_excerpt("online", "src/app.py", sha, 2, 3, headers=_headers())

    assert resolved["sha"] == sha
    assert excerpt["excerpt"] == "two\nthree"
    assert excerpt["commit_sha"] == sha
    assert (
        "exact 40-character"
        in github.get_file_excerpt("online", "src/app.py", "main", 1, 2, headers=_headers())["error"]
    )


def test_code_search_filters_paths_and_caps_results(monkeypatch, tmp_path) -> None:
    github = _reload_with_policy(monkeypatch, tmp_path)
    _configure_connection(github, monkeypatch)

    monkeypatch.setattr(
        github,
        "_request",
        lambda _context, path, **kwargs: {
            "items": [
                {"path": "src/app.py", "html_url": "https://example/src/app.py"},
                {"path": "private/secret.py", "html_url": "https://example/private/secret.py"},
            ],
            "incomplete_results": False,
        },
    )

    result = github.search_code("online", "GraphWriteException", max_results=50, headers=_headers())

    assert result["matches"] == [{"path": "src/app.py", "url": "https://example/src/app.py"}]
    assert result["count"] == 1


def test_issue_and_pr_search_are_separate_with_zero_and_merge_semantics(monkeypatch, tmp_path) -> None:
    github = _reload_with_policy(monkeypatch, tmp_path)
    _configure_connection(github, monkeypatch)
    calls = []

    def request(_context, path, *, method="GET", params=None, json_body=None):
        calls.append((path, params))
        if path.endswith("/pulls/7"):
            return {
                "merged_at": "2026-08-01T10:00:00Z",
                "base": {"ref": "main"},
                "head": {"sha": "b" * 40},
            }
        if params and "is:pr" in params["q"]:
            return {"items": [{"number": 7, "title": "Fix graph write", "state": "closed", "labels": []}]}
        return {"items": []}

    monkeypatch.setattr(github, "_request", request)

    issues = github.search_issues("online", '"GraphWriteException"', state="all", headers=_headers())
    pull_requests = github.search_pull_requests("online", "graph write", state="closed", headers=_headers())

    assert "is:issue" in issues["query"]
    assert issues["zero_result_semantics"] == "no_match_for_this_query"
    assert "is:pr" in pull_requests["query"]
    assert pull_requests["pull_requests"][0]["merged"] is True
    assert any(path.endswith("/pulls/7") for path, _params in calls)


def test_get_issue_returns_bounded_body_and_recent_comments(monkeypatch, tmp_path) -> None:
    github = _reload_with_policy(monkeypatch, tmp_path)
    _configure_connection(github, monkeypatch)
    calls = []

    def request(_context, path, **_kwargs):
        assert path.endswith("/issues/12")
        return {
            "number": 12,
            "title": "Existing incident",
            "body": "x" * (github.MAX_ISSUE_READ_BODY_CHARS + 10),
            "state": "open",
            "labels": [{"name": "incident"}],
            "html_url": "https://github.com/example/online/issues/12",
            "comments": 7,
        }

    def request_list(_context, path, *, params=None):
        calls.append((path, params))
        page = params["page"]
        first = 1 if page == 1 else 6
        last = 5 if page == 1 else 7
        return [
            {
                "user": {"login": f"operator-{index}"},
                "created_at": "2026-09-01T10:00:00Z",
                "updated_at": "2026-09-01T10:00:00Z",
                "html_url": f"https://github.com/example/online/issues/12#issuecomment-{index}",
                "body": f"status {index}",
            }
            for index in range(first, last + 1)
        ]

    monkeypatch.setattr(github, "_request", request)
    monkeypatch.setattr(github, "_request_list", request_list)

    result = github.get_issue("online", 12, max_comments=5, headers=_headers())

    assert len(result["issue"]["body"]) == github.MAX_ISSUE_READ_BODY_CHARS
    assert result["issue"]["comment_count"] == 7
    assert [comment["author"] for comment in result["issue"]["comments"]] == [
        "operator-3",
        "operator-4",
        "operator-5",
        "operator-6",
        "operator-7",
    ]
    assert calls == [
        ("/repos/example/online/issues/12/comments", {"per_page": 5, "page": 1}),
        ("/repos/example/online/issues/12/comments", {"per_page": 5, "page": 2}),
    ]
    assert "positive" in github.get_issue("online", 0, headers=_headers())["error"]


def test_issue_writes_require_opt_in_and_send_bounded_payloads(monkeypatch, tmp_path) -> None:
    github = _reload_with_policy(monkeypatch, tmp_path)
    _configure_connection(github, monkeypatch)
    calls = []

    def request(_context, path, *, method="GET", params=None, json_body=None):
        calls.append((method, path, json_body))
        return {
            "number": 12,
            "title": (json_body or {}).get("title", "Existing title"),
            "body": (json_body or {}).get("body", ""),
            "state": (json_body or {}).get("state", "open"),
            "labels": [{"name": label} for label in (json_body or {}).get("labels", [])],
            "html_url": "https://github.com/example/online/issues/12",
        }

    monkeypatch.setattr(github, "_request", request)

    denied = github.create_issue("online", "Title", "Body", headers=_headers())
    created = github.create_issue("online", "Title", "Body", labels=["reflection"], headers=_headers(issue_write=True))
    updated = github.update_issue("online", 12, state="closed", labels=[], headers=_headers(issue_write=True))

    assert "disabled" in denied["error"]
    assert created["issue"]["number"] == 12
    assert updated["issue"]["state"] == "closed"
    assert calls == [
        (
            "POST",
            "/repos/example/online/issues",
            {"title": "Title", "body": "Body", "labels": ["reflection"]},
        ),
        ("PATCH", "/repos/example/online/issues/12", {"state": "closed", "labels": []}),
    ]
