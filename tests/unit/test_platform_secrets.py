"""Regression coverage for generic and structured platform secret boundaries."""

from unittest.mock import patch

import pytest
import yaml

from shared.lib.platform_secrets import apply_platform_env_defaults, load_platform_env

pytestmark = pytest.mark.unit


def test_all_structured_provider_tokens_are_excluded_from_generic_secrets(tmp_path):
    config = {
        "github": {"connections": {"git": {"private_key_secret": "GITHUB_KEY"}}},
        "message_bus": {"bot_token_secret": "BOT_TOKEN"},
        "confluence": {"connections": {"wiki": {"token_secret": "WIKI_TOKEN"}}},
        "secrets": {name: {"encrypted": name} for name in ("GITHUB_KEY", "BOT_TOKEN", "WIKI_TOKEN", "LLM_API_KEY")},
    }
    config_path = tmp_path / "platform-config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    with patch("shared.lib.platform_secrets.decrypt_named_secrets", return_value={"LLM_API_KEY": "llm-key"}) as decrypt:
        assert load_platform_env(str(config_path), identity="identity") == {"LLM_API_KEY": "llm-key"}
    decrypt.assert_called_once_with({"LLM_API_KEY": {"encrypted": "LLM_API_KEY"}}, identity="identity")


def test_generic_config_load_without_identity_does_not_decrypt(tmp_path):
    config_path = tmp_path / "platform-config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "config": {"KNOWLEDGE_EMBEDDINGS_DIMENSIONS": 768},
                "secrets": {"LLM_API_KEY": {"encrypted": "ciphertext"}},
            }
        )
    )
    with patch("shared.lib.platform_secrets.decrypt_named_secrets") as decrypt:
        assert load_platform_env(str(config_path)) == {"KNOWLEDGE_EMBEDDINGS_DIMENSIONS": "768"}
    decrypt.assert_not_called()


def test_platform_environment_defaults_preserve_existing_values(tmp_path):
    config_path = tmp_path / "platform-config.yaml"
    config_path.write_text(
        yaml.safe_dump({"config": {"KNOWLEDGE_EMBEDDINGS_BATCH_SIZE": 16, "KNOWLEDGE_EMBEDDINGS_DIMENSIONS": 768}})
    )
    environment = {"KNOWLEDGE_EMBEDDINGS_BATCH_SIZE": "8"}
    apply_platform_env_defaults(environment, path=str(config_path))
    assert environment == {"KNOWLEDGE_EMBEDDINGS_BATCH_SIZE": "8", "KNOWLEDGE_EMBEDDINGS_DIMENSIONS": "768"}
