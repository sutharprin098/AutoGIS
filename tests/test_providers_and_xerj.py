from __future__ import annotations

import pytest
from core.config import AutoGISConfig, PROVIDER_ENDPOINTS, PROVIDER_MODELS, PROVIDERS
from core.agent_engine import repair_and_parse_json


def test_gemini_new_key_and_model_routing():
    cfg = AutoGISConfig()
    cfg.active_provider = "gemini"
    cfg.set_provider_key("gemini", "AQ.MockGCPServiceAccountKeyPattern123456789")

    # 1. Default model auto-selection when empty
    ptype, key, base_url, model = cfg.resolve_connection("")
    assert ptype == "gemini"
    assert key.startswith("AQ.")
    assert model == "gemini-3-flash-preview"

    # 2. Rewrite deprecated models to working gemini-3-flash-preview
    for dep in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "google/gemini-2.5-flash"):
        _, _, _, resolved_m = cfg.resolve_connection(dep)
        assert resolved_m == "gemini-3-flash-preview"

    # 3. Explicit modern model
    _, _, _, resolved_m = cfg.resolve_connection("google/gemini-3.5-flash")
    assert resolved_m == "gemini-3.5-flash"


def test_anthropic_claude_connection_and_alias_mapping():
    cfg = AutoGISConfig()
    cfg.active_provider = "anthropic"
    cfg.set_provider_key("anthropic", "sk-ant-api03-abcdef123456789")

    # 1. Default model auto-selection
    ptype, key, base_url, model = cfg.resolve_connection("")
    assert ptype == "anthropic"
    assert key.startswith("sk-ant-")
    assert model == "claude-3-7-sonnet-20250219"
    assert "anthropic.com" in base_url

    # 2. Alias mapping checks
    alias_tests = [
        ("claude-3.7-sonnet", "claude-3-7-sonnet-20250219"),
        ("claude-sonnet-4.5", "claude-3-7-sonnet-20250219"),
        ("claude-3.5-sonnet", "claude-3-5-sonnet-20241022"),
        ("claude-3.5-haiku", "claude-3-5-haiku-20241022"),
        ("anthropic/claude-3-5-sonnet-20241022", "claude-3-5-sonnet-20241022"),
    ]
    for in_m, expected_out in alias_tests:
        _, _, _, resolved = cfg.resolve_connection(in_m)
        assert resolved == expected_out


def test_xerj_ai_provider_and_dual_options():
    cfg = AutoGISConfig()

    # 1. Xerj AI in PROVIDERS registry
    prov_ids = [p[0] for p in PROVIDERS]
    assert "xerj" in prov_ids
    assert "anthropic" in prov_ids
    assert "gemini" in prov_ids

    # 2. Xerj AI Models listed
    xerj_models = [m[0] for m in PROVIDER_MODELS["xerj"]]
    assert "xerj/geo-reasoner" in xerj_models
    assert "xerj/spatial-gpt" in xerj_models
    assert "xerj/doc-intel" in xerj_models

    # 3. Xerj AI as active LLM provider
    cfg.active_provider = "xerj"
    cfg.set_provider_key("xerj", "xerj-cloud-live-token-998877")
    ptype, key, base_url, model = cfg.resolve_connection("")
    assert ptype == "xerj"
    assert key == "xerj-cloud-live-token-998877"
    assert model == "geo-reasoner"

    # 4. Xerj AI dedicated options independent of primary LLM:
    # User can set primary AI to Claude, but still configure Xerj Cloud Key + Local Daemon!
    cfg.active_provider = "anthropic"
    cfg.set_provider_key("anthropic", "sk-ant-claude-test")
    cfg.xerj_key = "xerj-doc-specialist-key"
    cfg.xerj_url = "http://127.0.0.1:9200"

    assert cfg.xerj_key == "xerj-doc-specialist-key"
    assert cfg.xerj_url == "http://127.0.0.1:9200"
    # Primary LLM still resolves to Claude
    p_type, _, _, p_mod = cfg.resolve_connection()
    assert p_type == "anthropic"
    assert p_mod == "claude-3-7-sonnet-20250219"


def test_key_auto_detection_by_prefix():
    cfg = AutoGISConfig()

    # Auto-detects Gemini key from prefix
    cfg.active_provider = "gemini"
    cfg.gemini_key = "AQ.TestGeminiNewKeyFormat1234"
    ptype, key, _, _ = cfg.resolve_connection("gemini-3-flash-preview")
    assert ptype == "gemini"
    assert key.startswith("AQ.")

    # Auto-detects Anthropic key from prefix
    cfg.active_provider = "anthropic"
    cfg.anthropic_key = "sk-ant-TestAnthropicKeyFormat1234"
    ptype, key, _, _ = cfg.resolve_connection("claude-3.7-sonnet")
    assert ptype == "anthropic"
    assert key.startswith("sk-ant-")
