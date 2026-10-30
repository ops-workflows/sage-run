"""Shared test utilities for workflow repository MCP and configuration tests."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx


def load_module(
    relative_path: str | Path,
    module_name: str | None = None,
    *,
    repo_root: Path | None = None,
) -> ModuleType:
    """Import a workflow MCP or connector module directly from its file path."""
    path = Path(relative_path)
    if not path.is_absolute():
        base = repo_root if repo_root is not None else Path.cwd()
        path = base / path
    resolved = path.resolve()
    name = module_name or resolved.stem
    parent = str(resolved.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec = importlib.util.spec_from_file_location(name, resolved)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module specification from {resolved}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def mock_transport_context(
    monkeypatch: Any,
) -> Iterator[tuple[list[httpx.Request], dict[str, Any]]]:
    """Route httpx.Client and httpx.AsyncClient through a MockTransport and record requests."""
    requests: list[httpx.Request] = []
    handlers: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handlers["fn"](request)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    real_async_client = httpx.AsyncClient

    def client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    def async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(httpx, "AsyncClient", async_client)
    yield requests, handlers


def tool_fn(tool_obj: Any) -> Callable[..., Any]:
    """Return the plain function behind a FastMCP tool decorator."""
    return getattr(tool_obj, "fn", tool_obj)


def is_read_only(tool_obj: Any) -> bool:
    """Return True when a FastMCP tool carries readOnlyHint / read_only_hint."""
    annotations = getattr(tool_obj, "annotations", None)
    if annotations is None and hasattr(tool_obj, "__fastmcp__"):
        annotations = getattr(tool_obj.__fastmcp__, "annotations", None)
    if annotations is None:
        return False
    if hasattr(annotations, "model_dump"):
        dumped = annotations.model_dump()
        return dumped.get("read_only_hint", dumped.get("readOnlyHint")) is True
    if isinstance(annotations, dict):
        return annotations.get("read_only_hint", annotations.get("readOnlyHint")) is True
    return bool(getattr(annotations, "read_only_hint", getattr(annotations, "readOnlyHint", False)))


def platform_hooks_dir() -> Path:
    """Locate the packaged platform hooks directory."""
    import hooks

    return Path(hooks.__file__).resolve().parent
