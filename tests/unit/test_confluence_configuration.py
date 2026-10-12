"""Confluence connection and typed Knowledge configuration contracts."""

from unittest.mock import call, patch

import pytest
import yaml
from pydantic import ValidationError

from shared.lib.config import Settings, _apply_platform_overrides
from shared.lib.platform_secrets import apply_platform_env_defaults, load_confluence_connections, load_platform_env

pytestmark = pytest.mark.unit


@pytest.fixture
def platform_file(tmp_path):
    config = {
        "confluence": {
            "connections": {
                " corporate-wiki ": {
                    "base_url": " https://COMPANY.atlassian.net/wiki/// ",
                    "username": " service@company.example ",
                    "auth_type": " BASIC ",
                    "token_secret": "WIKI_TOKEN",
                }
            }
        },
        "secrets": {"WIKI_TOKEN": {"encrypted": "wiki-ciphertext"}, "LLM_API_KEY": {"encrypted": "llm-ciphertext"}},
    }
    config_path = tmp_path / "platform-config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    return config_path


def test_metadata_load_does_not_decrypt(platform_file):
    with patch("shared.lib.platform_secrets.decrypt_named_secrets") as decrypt:
        connection = load_confluence_connections(str(platform_file))["corporate-wiki"]
    decrypt.assert_not_called()
    assert connection.name == "corporate-wiki"
    assert connection.base_url == "https://company.atlassian.net/wiki"
    assert connection.username == "service@company.example"
    assert connection.auth_type == "basic"
    assert connection.token == ""


def test_only_referenced_token_is_decrypted_and_never_in_repr(platform_file):
    with patch(
        "shared.lib.platform_secrets.decrypt_named_secrets", return_value={"WIKI_TOKEN": "private-token"}
    ) as decrypt:
        connection = load_confluence_connections(str(platform_file), identity="identity")["corporate-wiki"]
    decrypt.assert_called_once_with({"WIKI_TOKEN": {"encrypted": "wiki-ciphertext"}}, identity="identity")
    assert connection.token == "private-token"
    assert "private-token" not in repr(connection)


def test_confluence_token_is_excluded_from_generic_injection(platform_file):
    with patch("shared.lib.platform_secrets.decrypt_named_secrets", return_value={"LLM_API_KEY": "llm-key"}) as decrypt:
        loaded = load_platform_env(str(platform_file), identity="identity")
    decrypt.assert_called_once_with({"LLM_API_KEY": {"encrypted": "llm-ciphertext"}}, identity="identity")
    assert loaded == {"LLM_API_KEY": "llm-key"}


@pytest.mark.parametrize("base_url", ["http://localhost:1234/wiki/", "http://127.0.0.1/wiki", "http://[::1]/wiki"])
def test_loopback_http_is_allowed_for_local_tests(platform_file, base_url):
    config = yaml.safe_load(platform_file.read_text())
    config["confluence"]["connections"][" corporate-wiki "]["base_url"] = base_url
    platform_file.write_text(yaml.safe_dump(config))
    assert load_confluence_connections(str(platform_file))["corporate-wiki"].base_url == base_url.rstrip("/")


@pytest.mark.parametrize(
    "base_url",
    [
        "http://company.example/wiki",
        "https://service:token@company.example/wiki",
        "https://company.example/wiki?token=private",
        "https://company.example/wiki#fragment",
        "https://company.example:invalid/wiki",
        "https:///wiki",
        "company.example/wiki",
        "file:///wiki",
    ],
)
def test_unsafe_connection_urls_are_rejected_without_echoing_them(platform_file, base_url):
    config = yaml.safe_load(platform_file.read_text())
    config["confluence"]["connections"][" corporate-wiki "]["base_url"] = base_url
    platform_file.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError) as error:
        load_confluence_connections(str(platform_file))
    assert base_url not in str(error.value)


@pytest.mark.parametrize("auth_type,username", [("bearer", "service@example.test"), ("basic", "")])
def test_first_release_requires_basic_authentication(platform_file, auth_type, username):
    config = yaml.safe_load(platform_file.read_text())
    connection = config["confluence"]["connections"][" corporate-wiki "]
    connection.update(auth_type=auth_type, username=username)
    platform_file.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError, match="requires basic authentication"):
        load_confluence_connections(str(platform_file))


def test_missing_token_reference_is_safe(platform_file):
    config = yaml.safe_load(platform_file.read_text())
    del config["secrets"]["WIKI_TOKEN"]
    platform_file.write_text(yaml.safe_dump(config))
    with patch("shared.lib.platform_secrets.decrypt_named_secrets") as decrypt:
        connection = load_confluence_connections(str(platform_file), identity="identity")["corporate-wiki"]
    decrypt.assert_not_called()
    assert connection.token == ""


@pytest.mark.parametrize("contents", ["", "confluence: {}", "confluence: {connections: []}", "confluence: []"])
def test_absent_connections_are_empty(tmp_path, contents):
    config_path = tmp_path / "platform-config.yaml"
    config_path.write_text(contents)
    assert load_confluence_connections(str(config_path)) == {}
    assert load_confluence_connections(str(tmp_path / "missing.yaml")) == {}


def test_knowledge_settings_defaults_and_caller_owned_key_fallback(monkeypatch):
    for name in Settings.model_fields:
        if name.startswith("knowledge_"):
            monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("LLM_API_KEY", "caller-bootstrap-key")
    settings = Settings(platform_config_file="")
    assert settings.knowledge_embeddings_openai_base_url == "http://model-gateway:1235/v1"
    assert settings.knowledge_embeddings_openai_model == ""
    assert settings.knowledge_embeddings_dimensions == 0
    assert settings.knowledge_embeddings_openai_api_key == ""
    assert settings.knowledge_embeddings_batch_size == 16
    assert settings.knowledge_embeddings_timeout_sec == 60
    assert not settings.knowledge_rerank_enabled
    assert settings.knowledge_rerank_base_url == "http://model-gateway:1235"
    assert settings.knowledge_rerank_model == ""
    assert settings.knowledge_rerank_timeout_sec == 3
    assert settings.knowledge_rerank_candidates == 20
    assert not settings.knowledge_require_explicit_source_grants
    assert settings.knowledge_source_max_pages == 10000
    assert settings.knowledge_source_max_chunks == 100000
    assert settings.knowledge_source_fetch_concurrency == 8
    assert settings.knowledge_source_request_timeout_sec == 60
    assert settings.knowledge_source_request_retries == 3


@pytest.fixture
def knowledge_platform_file(platform_file, monkeypatch):
    for name in Settings.model_fields:
        if name.startswith("knowledge_"):
            monkeypatch.delenv(name.upper(), raising=False)
    config = yaml.safe_load(platform_file.read_text())
    config["knowledge"] = {
        "embeddings": {
            "provider": " OPENAI_COMPATIBLE ",
            "base_url": " http://localhost:1235/v1 ",
            "model": " embedding-model ",
            "dimensions": 768,
            "api_key_secret": "EMBEDDING_KEY",
            "batch_size": 8,
            "timeout_sec": 12.5,
        },
        "rerank": {
            "enabled": True,
            "base_url": "http://localhost:1235",
            "model": "reranker-model",
            "timeout_sec": 2.5,
            "candidates": 10,
        },
        "require_explicit_source_grants": True,
    }
    config["secrets"]["EMBEDDING_KEY"] = {"encrypted": "embedding-ciphertext"}
    platform_file.write_text(yaml.safe_dump(config))
    return platform_file


@pytest.mark.parametrize("identity", [None, ""])
def test_structured_knowledge_maps_without_identity(knowledge_platform_file, identity):
    with patch("shared.lib.platform_secrets.decrypt_named_secrets") as decrypt:
        loaded = load_platform_env(str(knowledge_platform_file), identity=identity)
    decrypt.assert_not_called()
    assert loaded == {
        "KNOWLEDGE_EMBEDDINGS_OPENAI_BASE_URL": "http://localhost:1235/v1",
        "KNOWLEDGE_EMBEDDINGS_OPENAI_MODEL": "embedding-model",
        "KNOWLEDGE_EMBEDDINGS_DIMENSIONS": "768",
        "KNOWLEDGE_EMBEDDINGS_BATCH_SIZE": "8",
        "KNOWLEDGE_EMBEDDINGS_TIMEOUT_SEC": "12.5",
        "KNOWLEDGE_RERANK_ENABLED": "True",
        "KNOWLEDGE_RERANK_BASE_URL": "http://localhost:1235",
        "KNOWLEDGE_RERANK_MODEL": "reranker-model",
        "KNOWLEDGE_RERANK_TIMEOUT_SEC": "2.5",
        "KNOWLEDGE_RERANK_CANDIDATES": "10",
        "KNOWLEDGE_REQUIRE_EXPLICIT_SOURCE_GRANTS": "True",
    }


def test_structured_knowledge_values_are_applied_as_typed_settings(knowledge_platform_file):
    settings = Settings(platform_config_file="")
    _apply_platform_overrides(settings, load_platform_env(str(knowledge_platform_file)))
    assert settings.knowledge_embeddings_openai_base_url == "http://localhost:1235/v1"
    assert settings.knowledge_embeddings_openai_model == "embedding-model"
    assert settings.knowledge_embeddings_dimensions == 768
    assert settings.knowledge_embeddings_batch_size == 8
    assert settings.knowledge_embeddings_timeout_sec == 12.5
    assert settings.knowledge_rerank_enabled is True
    assert settings.knowledge_rerank_base_url == "http://localhost:1235"
    assert settings.knowledge_rerank_model == "reranker-model"
    assert settings.knowledge_rerank_timeout_sec == 2.5
    assert settings.knowledge_rerank_candidates == 10
    assert settings.knowledge_require_explicit_source_grants is True


@pytest.mark.parametrize(
    "knowledge",
    [None, {}, {"embeddings": None}, {"rerank": {}}, {"embeddings": {"provider": "openai_compatible"}}],
)
def test_absent_structured_knowledge_preserves_defaults(knowledge_platform_file, knowledge):
    config = yaml.safe_load(knowledge_platform_file.read_text())
    config["knowledge"] = knowledge
    knowledge_platform_file.write_text(yaml.safe_dump(config))
    settings = Settings(platform_config_file="")
    defaults = settings.model_dump()
    with patch("shared.lib.platform_secrets.decrypt_named_secrets") as decrypt:
        loaded = load_platform_env(str(knowledge_platform_file))
    decrypt.assert_not_called()
    assert loaded == {}
    _apply_platform_overrides(settings, loaded)
    assert settings.model_dump() == defaults


def test_partial_structured_knowledge_preserves_omitted_defaults(knowledge_platform_file):
    config = yaml.safe_load(knowledge_platform_file.read_text())
    config["knowledge"] = {
        "embeddings": {"model": "embedding-model", "base_url": None, "dimensions": 0},
        "rerank": {"enabled": False},
        "require_explicit_source_grants": False,
    }
    knowledge_platform_file.write_text(yaml.safe_dump(config))
    loaded = load_platform_env(str(knowledge_platform_file))
    assert loaded == {
        "KNOWLEDGE_EMBEDDINGS_OPENAI_MODEL": "embedding-model",
        "KNOWLEDGE_EMBEDDINGS_DIMENSIONS": "0",
        "KNOWLEDGE_RERANK_ENABLED": "False",
        "KNOWLEDGE_REQUIRE_EXPLICIT_SOURCE_GRANTS": "False",
    }
    settings = Settings(platform_config_file="")
    _apply_platform_overrides(settings, loaded)
    assert settings.knowledge_embeddings_openai_base_url == "http://model-gateway:1235/v1"
    assert settings.knowledge_embeddings_batch_size == 16
    assert settings.knowledge_rerank_candidates == 20


@pytest.mark.parametrize(
    "env_var,value",
    [
        ("KNOWLEDGE_EMBEDDINGS_OPENAI_BASE_URL", "http://override:1235/v1"),
        ("KNOWLEDGE_EMBEDDINGS_OPENAI_MODEL", "override-model"),
        ("KNOWLEDGE_EMBEDDINGS_DIMENSIONS", 512),
        ("KNOWLEDGE_EMBEDDINGS_BATCH_SIZE", 4),
        ("KNOWLEDGE_EMBEDDINGS_TIMEOUT_SEC", 5.5),
        ("KNOWLEDGE_RERANK_ENABLED", False),
        ("KNOWLEDGE_RERANK_BASE_URL", "http://override:1235"),
        ("KNOWLEDGE_RERANK_MODEL", "override-reranker"),
        ("KNOWLEDGE_RERANK_TIMEOUT_SEC", 1.5),
        ("KNOWLEDGE_RERANK_CANDIDATES", 5),
        ("KNOWLEDGE_REQUIRE_EXPLICIT_SOURCE_GRANTS", False),
    ],
)
def test_structured_knowledge_override_precedence(knowledge_platform_file, monkeypatch, env_var, value):
    config = yaml.safe_load(knowledge_platform_file.read_text())
    typed_values = load_platform_env(str(knowledge_platform_file))
    config["config"] = {env_var: value}
    knowledge_platform_file.write_text(yaml.safe_dump(config))
    loaded = load_platform_env(str(knowledge_platform_file))
    assert loaded == {**typed_values, env_var: str(value)}
    settings = Settings(platform_config_file="")
    _apply_platform_overrides(settings, loaded)
    assert getattr(settings, env_var.lower()) == value

    monkeypatch.setenv(env_var, typed_values[env_var])
    settings = Settings(platform_config_file="")
    explicit_value = getattr(settings, env_var.lower())
    _apply_platform_overrides(settings, loaded)
    assert getattr(settings, env_var.lower()) == explicit_value
    environment = {env_var: typed_values[env_var]}
    apply_platform_env_defaults(environment, path=str(knowledge_platform_file))
    assert environment == {**loaded, env_var: typed_values[env_var]}


def test_embedding_key_is_only_decrypted_for_dedicated_env_and_not_repr(knowledge_platform_file):
    with patch(
        "shared.lib.platform_secrets.decrypt_named_secrets",
        side_effect=[{"LLM_API_KEY": "llm-key"}, {"EMBEDDING_KEY": "private-embedding-key"}],
    ) as decrypt:
        loaded = load_platform_env(str(knowledge_platform_file), identity="identity")
    assert decrypt.call_args_list == [
        call({"LLM_API_KEY": {"encrypted": "llm-ciphertext"}}, identity="identity"),
        call({"EMBEDDING_KEY": {"encrypted": "embedding-ciphertext"}}, identity="identity"),
    ]
    assert loaded["KNOWLEDGE_EMBEDDINGS_OPENAI_API_KEY"] == "private-embedding-key"
    assert "EMBEDDING_KEY" not in loaded
    assert "WIKI_TOKEN" not in loaded
    settings = Settings(platform_config_file="")
    _apply_platform_overrides(settings, loaded)
    assert settings.knowledge_embeddings_openai_api_key == "private-embedding-key"
    assert "private-embedding-key" not in repr(settings)
    assert "embedding-ciphertext" not in repr(settings)


@pytest.mark.parametrize("override", ["environment", "config"])
def test_overridden_embedding_key_is_not_decrypted(knowledge_platform_file, monkeypatch, override):
    env_var = "KNOWLEDGE_EMBEDDINGS_OPENAI_API_KEY"
    if override == "environment":
        monkeypatch.setenv(env_var, "explicit-key")
    else:
        config = yaml.safe_load(knowledge_platform_file.read_text())
        config["config"] = {env_var: "explicit-key"}
        knowledge_platform_file.write_text(yaml.safe_dump(config))
    with patch("shared.lib.platform_secrets.decrypt_named_secrets", return_value={"LLM_API_KEY": "llm-key"}) as decrypt:
        loaded = load_platform_env(str(knowledge_platform_file), identity="identity")
    decrypt.assert_called_once_with({"LLM_API_KEY": {"encrypted": "llm-ciphertext"}}, identity="identity")
    assert "EMBEDDING_KEY" not in loaded
    settings = Settings(platform_config_file="")
    _apply_platform_overrides(settings, loaded)
    assert settings.knowledge_embeddings_openai_api_key == "explicit-key"


def test_embedding_key_decryption_skips_empty_generic_batch(knowledge_platform_file):
    config = yaml.safe_load(knowledge_platform_file.read_text())
    del config["secrets"]["LLM_API_KEY"]
    knowledge_platform_file.write_text(yaml.safe_dump(config))
    with patch("shared.lib.platform_secrets.decrypt_named_secrets", return_value={}) as decrypt:
        loaded = load_platform_env(str(knowledge_platform_file), identity="identity")
    decrypt.assert_called_once_with({"EMBEDDING_KEY": {"encrypted": "embedding-ciphertext"}}, identity="identity")
    assert "KNOWLEDGE_EMBEDDINGS_OPENAI_API_KEY" not in loaded
    assert loaded["KNOWLEDGE_EMBEDDINGS_DIMENSIONS"] == "768"


@pytest.mark.parametrize("secret_spec", [None, "private-marker", {}, {"encrypted": 123}, {"encrypted": ""}])
def test_missing_or_malformed_embedding_secret_is_safe(knowledge_platform_file, secret_spec, caplog):
    config = yaml.safe_load(knowledge_platform_file.read_text())
    config["knowledge"]["embeddings"]["api_key_secret"] = "private-marker"
    config["secrets"] = {"private-marker": secret_spec} if secret_spec is not None else {}
    knowledge_platform_file.write_text(yaml.safe_dump(config))
    with (
        patch("shared.lib.platform_secrets.decrypt_named_secrets") as decrypt,
        pytest.raises(ValueError, match="knowledge.embeddings.api_key_secret") as error,
    ):
        load_platform_env(str(knowledge_platform_file), identity="identity")
    decrypt.assert_not_called()
    assert "private-marker" not in str(error.value) + repr(error.value) + caplog.text


@pytest.mark.parametrize(
    "knowledge",
    [
        "private-marker",
        [],
        {"private-marker": "private-marker"},
        {"embeddings": []},
        {"embeddings": {"provider": "private-marker"}},
        {"embeddings": {"provider": ["private-marker"]}},
        {"embeddings": {"openaiBaseUrl": "private-marker"}},
        {"embeddings": {"api_key": "private-marker"}},
        {"embeddings": {"base_url": {"token": "private-marker"}}},
        {"embeddings": {"model": False}},
        {"embeddings": {"api_key_secret": ["private-marker"]}},
        {"embeddings": {"dimensions": -1}},
        {"embeddings": {"dimensions": True}},
        {"embeddings": {"dimensions": 1.5}},
        {"embeddings": {"batch_size": 0}},
        {"embeddings": {"timeout_sec": 0}},
        {"embeddings": {"timeout_sec": float("inf")}},
        {"rerank": "private-marker"},
        {"rerank": {"provider": "private-marker"}},
        {"rerank": {"timeoutSec": 1}},
        {"rerank": {"enabled": "private-marker"}},
        {"rerank": {"base_url": ["private-marker"]}},
        {"rerank": {"model": {"token": "private-marker"}}},
        {"rerank": {"timeout_sec": -1}},
        {"rerank": {"timeout_sec": float("nan")}},
        {"rerank": {"candidates": 0}},
        {"requireExplicitSourceGrants": True},
        {"require_explicit_source_grants": "private-marker"},
    ],
)
def test_invalid_structured_knowledge_is_rejected_without_secret_details(knowledge_platform_file, knowledge, caplog):
    config = yaml.safe_load(knowledge_platform_file.read_text())
    config["knowledge"] = knowledge
    knowledge_platform_file.write_text(yaml.safe_dump(config))
    with (
        patch("shared.lib.platform_secrets.decrypt_named_secrets") as decrypt,
        pytest.raises(ValueError, match="Invalid knowledge configuration") as error,
    ):
        load_platform_env(str(knowledge_platform_file), identity="identity")
    decrypt.assert_not_called()
    assert "private-marker" not in str(error.value) + repr(error.value) + caplog.text


def test_platform_overrides_remain_typed_and_environment_wins(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_EMBEDDINGS_BATCH_SIZE", "7")
    for name in ("DIMENSIONS", "TIMEOUT_SEC", "OPENAI_API_KEY"):
        monkeypatch.delenv(f"KNOWLEDGE_EMBEDDINGS_{name}", raising=False)
    monkeypatch.delenv("KNOWLEDGE_RERANK_ENABLED", raising=False)
    monkeypatch.delenv("KNOWLEDGE_REQUIRE_EXPLICIT_SOURCE_GRANTS", raising=False)
    settings = Settings(platform_config_file="")
    _apply_platform_overrides(
        settings,
        {
            "KNOWLEDGE_EMBEDDINGS_DIMENSIONS": "768",
            "KNOWLEDGE_EMBEDDINGS_BATCH_SIZE": "16",
            "KNOWLEDGE_EMBEDDINGS_TIMEOUT_SEC": "12.5",
            "KNOWLEDGE_EMBEDDINGS_OPENAI_API_KEY": "embedding-key",
            "KNOWLEDGE_RERANK_ENABLED": "true",
            "KNOWLEDGE_REQUIRE_EXPLICIT_SOURCE_GRANTS": "true",
        },
    )
    assert settings.knowledge_embeddings_dimensions == 768
    assert settings.knowledge_embeddings_batch_size == 7
    assert settings.knowledge_embeddings_timeout_sec == 12.5
    assert settings.knowledge_rerank_enabled is True
    assert settings.knowledge_require_explicit_source_grants is True
    assert settings.knowledge_embeddings_openai_api_key == "embedding-key"
    assert "embedding-key" not in repr(settings)


@pytest.mark.parametrize(
    "name,value",
    [
        ("knowledge_embeddings_dimensions", -1),
        ("knowledge_embeddings_batch_size", 0),
        ("knowledge_embeddings_timeout_sec", 0),
        ("knowledge_rerank_timeout_sec", -1),
        ("knowledge_rerank_candidates", 0),
        ("knowledge_source_max_pages", 0),
        ("knowledge_source_max_chunks", -1),
        ("knowledge_source_fetch_concurrency", 0),
        ("knowledge_source_request_timeout_sec", 0),
        ("knowledge_source_request_retries", -1),
    ],
)
def test_invalid_knowledge_budgets_are_rejected(name, value):
    with pytest.raises(ValidationError):
        Settings(platform_config_file="", **{name: value})
