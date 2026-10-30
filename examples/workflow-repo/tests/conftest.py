"""Test configuration and installed-wheel helpers for the starter workflow repository."""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PLATFORM_CONFIG_FILE", str(REPO_ROOT / "platform-config.yaml"))

if (
    importlib.util.find_spec("mcps") is None or importlib.util.find_spec("mcps.common") is None
):  # pragma: no cover - fallback for wheels prior to 1.0.6
    from shared.lib.platform_secrets import apply_platform_env_defaults

    try:
        from starlette.middleware.base import BaseHTTPMiddleware
    except ImportError:
        BaseHTTPMiddleware = object  # type: ignore[assignment,misc]

    class _PolicyReloadMiddleware(BaseHTTPMiddleware):  # type: ignore[misc]
        def __init__(self, app: Any, *, reload_policy: Callable[[], None]) -> None:
            if BaseHTTPMiddleware is not object:
                super().__init__(app)
            self.reload_policy = reload_policy

        async def dispatch(self, request: Any, call_next: Callable[..., Any]) -> Any:
            path = Path(os.environ.get("PLATFORM_CONFIG_FILE", "/app/platform-config.yaml"))
            if not (path.parent / ".git/sage-run-deploy.lock.d").exists():
                self.reload_policy()
            return await call_next(request)

    def _bootstrap_platform_env() -> None:
        platform_config_file = os.environ.get("PLATFORM_CONFIG_FILE", "/app/platform-config.yaml")
        age_identity = os.environ.get("AGE_IDENTITY", "")
        try:
            apply_platform_env_defaults(os.environ, path=platform_config_file, identity=age_identity or None)
        except Exception:
            return

    def _extract_bearer_token(headers: dict[str, str]) -> str:
        auth = headers.get("authorization", "")
        return auth[7:] if auth.lower().startswith("bearer ") else ""

    def _require_header(headers: dict[str, str], header_name: str, description: str) -> str:
        value = headers.get(header_name, "").strip()
        if not value:
            raise ValueError(f"{description} must be provided via the {header_name} header")
        return value

    def _validate_base_url(value: str, *, header_name: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"{header_name} must use http or https")
        if not parsed.netloc:
            raise ValueError(f"{header_name} must include a host")
        if parsed.params or parsed.query or parsed.fragment:
            raise ValueError(f"{header_name} must not include params, query strings, or fragments")
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"

    mcps_pkg = sys.modules.setdefault("mcps", types.ModuleType("mcps"))
    mcps_pkg.__path__ = []  # type: ignore[attr-defined]
    common_mod = types.ModuleType("mcps.common")
    common_mod.PolicyReloadMiddleware = _PolicyReloadMiddleware  # type: ignore[attr-defined]
    common_mod.bootstrap_platform_env = _bootstrap_platform_env  # type: ignore[attr-defined]
    common_mod.get_env = lambda name, default="": os.environ.get(name, default)  # type: ignore[attr-defined]
    common_mod.extract_bearer_token = _extract_bearer_token  # type: ignore[attr-defined]
    common_mod.require_header = _require_header  # type: ignore[attr-defined]
    common_mod.validate_base_url = _validate_base_url  # type: ignore[attr-defined]
    mcps_pkg.common = common_mod  # type: ignore[attr-defined]
    sys.modules["mcps.common"] = common_mod

if importlib.util.find_spec("sage_run.testing") is not None:
    from sage_run.testing import is_read_only, load_module, mock_transport_context, tool_fn
else:  # pragma: no cover - fallback for wheels prior to 1.0.6

    def load_module(relative_path: str | Path, module_name: str | None = None, *, repo_root: Path | None = None):
        path = (repo_root or REPO_ROOT) / relative_path
        spec = importlib.util.spec_from_file_location(module_name or path.stem, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name or path.stem] = module
        spec.loader.exec_module(module)
        return module

    def mock_transport_context(monkeypatch):
        import httpx

        requests: list[httpx.Request] = []
        handlers: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return handlers["fn"](request)

        real_client = httpx.Client

        def client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", client)
        yield requests, handlers

    def tool_fn(tool):
        return getattr(tool, "fn", tool)

    def is_read_only(tool) -> bool:
        annotations = getattr(tool, "annotations", None) or getattr(
            getattr(tool, "__fastmcp__", None), "annotations", None
        )
        if annotations is None:
            return False
        dumped = annotations.model_dump() if hasattr(annotations, "model_dump") else annotations
        return dumped.get("read_only_hint", dumped.get("readOnlyHint")) is True


@pytest.fixture
def mock_transport(monkeypatch):
    yield from mock_transport_context(monkeypatch)
