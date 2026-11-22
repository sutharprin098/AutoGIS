from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from qgis.core import QgsApplication, QgsMessageLog, QgsSettings

SETTINGS_PREFIX = "AutoGIS"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = ""

PROVIDERS: list[tuple[str, str, str]] = [
    ("xerj", "Xerj AI (Geospatial & Spatial Reasoning)", "https://api.xerj.ai/v1"),
    ("gemini", "Google Gemini (Fast & Free Tier)", "https://generativelanguage.googleapis.com/v1beta/openai"),
    ("anthropic", "Anthropic (Claude 3.7 / 3.5)", "https://api.anthropic.com/v1"),
    ("openai", "OpenAI (ChatGPT GPT-4o / o3-mini)", "https://api.openai.com/v1"),
    ("deepseek", "DeepSeek (V3 / R1 Reasoner)", "https://api.deepseek.com/v1"),
    ("openrouter", "OpenRouter (All Global Models)", "https://openrouter.ai/api/v1"),
    ("ollama", "Local AI (Ollama / LM Studio - Offline)", "http://127.0.0.1:11434/v1"),
]

PROVIDER_ENDPOINTS: dict[str, str] = {pid: url for pid, _, url in PROVIDERS}

FALLBACK_CHAIN: list[str] = [
    # Free OpenRouter models first — fastest verified working models
    "nvidia/nemotron-3.5-lightning:free",      # ~2.1s, tool_calls verified ✓
    "nvidia/nemotron-3-ultra-550b-a55b:free",  # ~0.9s, tool_calls verified ✓
    "cohere/command-r-plus-08-2024:free",      # Cohere free fallback
    "meta-llama/llama-3.3-70b-instruct:free",  # Llama free fallback
    # Paid models (only reached if user has respective API key)
    "google/gemini-3-flash-preview",
    "google/gemini-2.5-flash",
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "deepseek/deepseek-chat",
]

PROVIDER_MODELS: dict[str, list[tuple[str, str]]] = {
    "xerj": [
        ("xerj/geo-reasoner", "⚡ Xerj Geo-Reasoner (Autonomous GIS)"),
        ("xerj/spatial-gpt", "Xerj Spatial-GPT (Multi-Modal GIS)"),
        ("xerj/doc-intel", "Xerj Document & Corpus Intelligence"),
    ],
    "gemini": [
        ("google/gemini-3-flash-preview", "⚡ Gemini 3 Flash Preview (Fastest & Verified)"),
        ("google/gemini-3.5-flash", "Gemini 3.5 Flash"),
        ("google/gemini-3.8-flash", "Gemini 3.8 Flash"),
        ("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro Preview"),
        ("google/gemini-flash-latest", "Gemini Flash Latest"),
    ],
    "anthropic": [
        ("anthropic/claude-3-7-sonnet-20250219", "⚡ Claude 3.7 Sonnet (Latest)"),
        ("anthropic/claude-3-5-sonnet-20241022", "Claude 3.5 Sonnet"),
        ("anthropic/claude-3-5-haiku-20241022", "Claude 3.5 Haiku"),
        ("anthropic/claude-3-haiku-20240307", "Claude 3 Haiku"),
    ],
    "openai": [
        ("openai/gpt-4o-mini", "⚡ GPT-4o Mini (Fast & Smart)"),
        ("openai/gpt-4o", "GPT-4o (Omni)"),
        ("openai/o3-mini", "OpenAI o3-mini (Reasoning)"),
        ("openai/o1-mini", "OpenAI o1-mini"),
    ],
    "deepseek": [
        ("deepseek/deepseek-chat", "⚡ DeepSeek V3 (Coding & GIS)"),
        ("deepseek/deepseek-reasoner", "DeepSeek R1 (Deep Reasoning)"),
    ],
    "openrouter": [
        ("nvidia/nemotron-3.5-lightning:free", "⚡ Nemotron 3.5 Lightning (Free)"),    # fastest, default
        ("nvidia/nemotron-3-ultra-550b-a55b:free", "Nemotron 3 Ultra 550B (Free)"),
        ("meta-llama/llama-3.3-70b-instruct:free", "Llama 3.3 70B (Free)"),
        ("google/gemma-3-27b-it:free", "Gemma 3 27B (Free)"),
        ("mistralai/mistral-7b-instruct:free", "Mistral 7B (Free)"),
        ("google/gemini-2.5-flash", "Gemini 2.5 Flash"),
        ("openai/gpt-4o-mini", "GPT-4o Mini"),
        ("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5"),
        ("deepseek/deepseek-chat", "DeepSeek V3"),
        ("qwen/qwen-2.5-72b-instruct", "Qwen 2.5 72B"),
    ],
    "ollama": [
        ("ollama/qwen2.5-coder:14b", "Local: Qwen 2.5 Coder 14B (Ollama)"),
        ("ollama/qwen2.5-coder:7b", "Local: Qwen 2.5 Coder 7B (Ollama)"),
        ("ollama/llama3.3:latest", "Local: Llama 3.3 (Ollama)"),
        ("ollama/deepseek-r1:14b", "Local: DeepSeek R1 14B (Ollama)"),
        ("ollama/gemma3:12b", "Local: Gemma 3 12B (Ollama)"),
    ],
}

CURATED_MODELS: list[tuple[str, str]] = [
    ("", "Select Model"),
    # --- Free Models (OpenRouter) ---
    ("nvidia/nemotron-3.5-lightning:free", "⚡ Nemotron 3.5 Lightning (Free) [Recommended]"),
    ("nvidia/nemotron-3-ultra-550b-a55b:free", "Nemotron 3 Ultra 550B (Free)"),
    ("meta-llama/llama-3.3-70b-instruct:free", "Llama 3.3 70B (Free)"),
    ("google/gemma-3-27b-it:free", "Gemma 3 27B (Free)"),
    ("mistralai/mistral-7b-instruct:free", "Mistral 7B (Free)"),
    # --- Xerj AI Models ---
    ("xerj/geo-reasoner", "⚡ Xerj Geo-Reasoner (Spatial AI)"),
    ("xerj/spatial-gpt", "Xerj Spatial-GPT (Multi-Modal)"),
    ("xerj/doc-intel", "Xerj Document & Vector Intelligence"),
    # --- Google Gemini ---
    ("google/gemini-3-flash-preview", "⚡ Gemini 3 Flash Preview [Gemini Key]"),
    ("google/gemini-3.5-flash", "Gemini 3.5 Flash"),
    # --- Anthropic Claude ---
    ("anthropic/claude-3-7-sonnet-20250219", "⚡ Claude 3.7 Sonnet [Claude Key]"),
    ("anthropic/claude-3-5-sonnet-20241022", "Claude 3.5 Sonnet"),
    ("anthropic/claude-3-5-haiku-20241022", "Claude 3.5 Haiku"),
    # --- OpenAI ---
    ("openai/gpt-4o-mini", "GPT-4o Mini [OpenAI Key]"),
    ("openai/gpt-4o", "GPT-4o"),
    ("openai/o3-mini", "OpenAI o3-mini"),
    # --- DeepSeek ---
    ("deepseek/deepseek-chat", "DeepSeek V3 [DeepSeek Key]"),
    ("deepseek/deepseek-reasoner", "DeepSeek R1"),
    # --- Local (Ollama) ---
    ("ollama/qwen2.5-coder:14b", "Local: Qwen 2.5 Coder 14B (Ollama)"),
    ("ollama/qwen2.5-coder:7b", "Local: Qwen 2.5 Coder 7B (Ollama)"),
    ("ollama/llama3.3:latest", "Local: Llama 3.3 (Ollama)"),
]

_MEM_CACHE: dict[str, Any] = {}


def log_info(msg: str) -> None:
    try:
        QgsMessageLog.logMessage(str(msg), "AutoGIS", level=0)
    except Exception as err:
        _ = err


def log_warn(msg: str) -> None:
    try:
        QgsMessageLog.logMessage(str(msg), "AutoGIS", level=1)
    except Exception as err:
        _ = err


def data_dir() -> str:
    try:
        base = QgsApplication.qgisSettingsDirPath()
    except Exception:
        base = os.path.expanduser("~")
    folder = os.path.join(base, "autogis_studio")
    os.makedirs(folder, exist_ok=True)
    return folder


class AutoGISConfig:
    """Unified, provider-neutral configuration manager for AutoGIS."""

    def __init__(self) -> None:
        self._qs = QgsSettings()

    def _k(self, key: str) -> str:
        return f"{SETTINGS_PREFIX}/{key}"

    def get_str(self, key: str, default: str = "") -> str:
        if key in _MEM_CACHE:
            return str(_MEM_CACHE[key])
        try:
            val = self._qs.value(self._k(key), default, type=str)
        except Exception:
            try:
                val = self._qs.value(self._k(key), default)
            except Exception:
                val = default
        res = str(val) if val is not None else default
        _MEM_CACHE[key] = res
        return res

    def set_str(self, key: str, value: str) -> None:
        val = str(value or "").strip()
        _MEM_CACHE[key] = val
        try:
            self._qs.setValue(self._k(key), val)
            self._qs.sync()
        except Exception as err:
            _ = err

    def get_bool(self, key: str, default: bool = True) -> bool:
        raw = self.get_str(key, "1" if default else "0")
        return raw.lower() in ("1", "true", "yes", "on")

    def set_bool(self, key: str, value: bool) -> None:
        self.set_str(key, "1" if value else "0")

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get_str(key, str(default)))
        except (TypeError, ValueError):
            return default

    def set_int(self, key: str, value: int) -> None:
        self.set_str(key, str(int(value)))

    def reset_all(self) -> None:
        """Clear all user keys, selected model, and custom logo back to clean defaults."""
        keys = (
            "active_provider",
            "api_key",
            "gemini_key",
            "openai_key",
            "anthropic_key",
            "deepseek_key",
            "model",
            "custom_logo_path",
            "custom_instructions",
            "gee_project_id",
            "gee_service_account",
            "gee_key_file",
            "gas_server_url",
            "gas_registry_url",
            "gas_api_key",
            "gibd_api_key",
        )
        for k in keys:
            _MEM_CACHE[k] = ""
            try:
                self._qs.remove(self._k(k))
            except Exception as err:
                _ = err
        try:
            self._qs.sync()
        except Exception as err:
            _ = err

    @property
    def active_provider(self) -> str:
        p = self.get_str("active_provider", "gemini")
        return p if p in PROVIDER_ENDPOINTS else "gemini"

    @active_provider.setter
    def active_provider(self, value: str) -> None:
        if value in PROVIDER_ENDPOINTS:
            self.set_str("active_provider", value)

    def get_provider_key(self, provider_id: str) -> str:
        key_map = {
            "xerj": "xerj_key",
            "openrouter": "api_key",
            "gemini": "gemini_key",
            "openai": "openai_key",
            "anthropic": "anthropic_key",
            "deepseek": "deepseek_key",
        }
        k = key_map.get(provider_id, "api_key")
        return self.get_str(k, "")

    def set_provider_key(self, provider_id: str, value: str) -> None:
        key_map = {
            "xerj": "xerj_key",
            "openrouter": "api_key",
            "gemini": "gemini_key",
            "openai": "openai_key",
            "anthropic": "anthropic_key",
            "deepseek": "deepseek_key",
        }
        k = key_map.get(provider_id, "api_key")
        self.set_str(k, value)

    @property
    def gee_project_id(self) -> str:
        return self.get_str("gee_project_id", "")

    @gee_project_id.setter
    def gee_project_id(self, value: str) -> None:
        self.set_str("gee_project_id", value)

    @property
    def gee_service_account(self) -> str:
        return self.get_str("gee_service_account", "")

    @gee_service_account.setter
    def gee_service_account(self, value: str) -> None:
        self.set_str("gee_service_account", value)

    @property
    def gee_key_file(self) -> str:
        return self.get_str("gee_key_file", "")

    @gee_key_file.setter
    def gee_key_file(self, value: str) -> None:
        self.set_str("gee_key_file", value)

    @property
    def custom_logo_path(self) -> str:
        return self.get_str("custom_logo_path", "")

    @custom_logo_path.setter
    def custom_logo_path(self, value: str) -> None:
        self.set_str("custom_logo_path", value)

    @property
    def xerj_key(self) -> str:
        return self.get_str("xerj_key", "")

    @xerj_key.setter
    def xerj_key(self, value: str) -> None:
        self.set_str("xerj_key", value)

    @property
    def api_key(self) -> str:
        return self.get_str("api_key", "")

    @api_key.setter
    def api_key(self, value: str) -> None:
        self.set_str("api_key", value)

    @property
    def gemini_key(self) -> str:
        return self.get_str("gemini_key", "")

    @gemini_key.setter
    def gemini_key(self, value: str) -> None:
        self.set_str("gemini_key", value)

    @property
    def openai_key(self) -> str:
        return self.get_str("openai_key", "")

    @openai_key.setter
    def openai_key(self, value: str) -> None:
        self.set_str("openai_key", value)

    @property
    def anthropic_key(self) -> str:
        return self.get_str("anthropic_key", "")

    @anthropic_key.setter
    def anthropic_key(self, value: str) -> None:
        self.set_str("anthropic_key", value)

    @property
    def deepseek_key(self) -> str:
        return self.get_str("deepseek_key", "")

    @deepseek_key.setter
    def deepseek_key(self, value: str) -> None:
        self.set_str("deepseek_key", value)

    def get_ordered_models(self) -> list[tuple[str, str]]:
        """Return model list prioritizing the user's active provider first."""
        out: list[tuple[str, str]] = [("", "Select Model")]
        seen: set[str] = {""}
        active = self.active_provider
        for mid, mlabel in PROVIDER_MODELS.get(active, []):
            if mid not in seen:
                out.append((mid, mlabel))
                seen.add(mid)
        for mid, mlabel in CURATED_MODELS:
            if mid not in seen:
                out.append((mid, mlabel))
                seen.add(mid)
        return out

    def resolve_connection(self, model_id: str | None = None) -> tuple[str, str, str, str]:
        """Return (provider_type, api_key, base_url, api_model_name)."""
        m = (model_id if model_id is not None else self.model).strip()

        or_key = self.api_key
        gem_key = self.gemini_key
        oai_key = self.openai_key
        ant_key = self.anthropic_key
        ds_key = self.deepseek_key
        xerj_key = self.xerj_key

        # Auto-detect if user pasted a key with known prefix into any provider box
        for k in (or_key, gem_key, oai_key, ant_key, ds_key, xerj_key):
            if k.startswith("sk-or-"):
                or_key = k
            elif k.startswith("AQ.") or k.startswith("AIza"):
                gem_key = k
            elif k.startswith("sk-ant-"):
                ant_key = k
            elif k.startswith("sk-") and not (k.startswith("sk-or-") or k.startswith("sk-ant-")):
                oai_key = k

        # If model is empty, default based on active provider
        if not m:
            if self.active_provider == "gemini":
                m = "google/gemini-3-flash-preview"
            elif self.active_provider == "anthropic":
                m = "anthropic/claude-3-7-sonnet-20250219"
            elif self.active_provider == "xerj":
                m = "xerj/geo-reasoner"
            elif self.active_provider == "openai":
                m = "openai/gpt-4o-mini"
            elif self.active_provider == "deepseek":
                m = "deepseek/deepseek-chat"
            elif self.active_provider == "ollama":
                m = "ollama/qwen2.5-coder:14b"
            elif or_key:
                m = "nvidia/nemotron-3.5-lightning:free"
            elif gem_key:
                m = "google/gemini-3-flash-preview"
            elif ant_key:
                m = "anthropic/claude-3-7-sonnet-20250219"
            elif oai_key:
                m = "openai/gpt-4o-mini"
            elif ds_key:
                m = "deepseek/deepseek-chat"
            elif xerj_key:
                m = "xerj/geo-reasoner"

        if not m and not (or_key or gem_key or oai_key or ant_key or ds_key or xerj_key):
            return ("none", "", self.base_url, "")

        if m.startswith("ollama/") or self.active_provider == "ollama":
            clean_m = m.split("/", 1)[1] if m.startswith("ollama/") else m
            local_url = self.get_str("ollama_url", PROVIDER_ENDPOINTS["ollama"]) or PROVIDER_ENDPOINTS["ollama"]
            return ("ollama", "ollama-local", local_url.rstrip("/"), clean_m)

        # If active provider is openrouter and we have an openrouter key, route directly via openrouter
        if self.active_provider == "openrouter" and or_key:
            return ("openrouter", or_key, PROVIDER_ENDPOINTS["openrouter"], m)

        if (m.startswith("xerj/") or self.active_provider == "xerj") and self.xerj_key:
            clean_m = m.split("/", 1)[1] if "/" in m else (m or "geo-reasoner")
            x_url = self.get_str("xerj_url", PROVIDER_ENDPOINTS.get("xerj", "https://api.xerj.ai/v1")) or "https://api.xerj.ai/v1"
            return ("xerj", self.xerj_key, x_url.rstrip("/"), clean_m)

        if (m.startswith("google/gemini") or m.startswith("gemini-") or self.active_provider == "gemini") and gem_key and not gem_key.startswith("sk-or-"):
            clean_m = m.split("/", 1)[1] if "/" in m else (m or "gemini-3-flash-preview")
            if clean_m in ("", "gemini", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash-lite"):
                clean_m = "gemini-3-flash-preview"
            return ("gemini", gem_key, PROVIDER_ENDPOINTS["gemini"], clean_m)

        if (m.startswith("openai/") or m.startswith("gpt-") or m.startswith("o1") or m.startswith("o3") or self.active_provider == "openai") and oai_key and not oai_key.startswith("sk-or-"):
            clean_m = m.split("/", 1)[1] if "/" in m else (m or "gpt-4o-mini")
            return ("openai", oai_key, PROVIDER_ENDPOINTS["openai"], clean_m)

        if (m.startswith("anthropic/") or m.startswith("claude-") or self.active_provider == "anthropic") and ant_key and not ant_key.startswith("sk-or-"):
            clean_m = m.split("/", 1)[1] if "/" in m else (m or "claude-3-7-sonnet-20250219")
            alias_map = {
                "claude-3.7-sonnet": "claude-3-7-sonnet-20250219",
                "claude-sonnet-4.5": "claude-3-7-sonnet-20250219",
                "claude-3.5-sonnet": "claude-3-5-sonnet-20241022",
                "claude-3.5-haiku": "claude-3-5-haiku-20241022",
                "claude-haiku-4.5": "claude-3-5-haiku-20241022",
                "claude-3-haiku": "claude-3-haiku-20240307",
            }
            clean_m = alias_map.get(clean_m, clean_m)
            return ("anthropic", ant_key, PROVIDER_ENDPOINTS["anthropic"], clean_m)

        if (m.startswith("deepseek/") or m.startswith("deepseek-") or self.active_provider == "deepseek") and ds_key and not ds_key.startswith("sk-or-"):
            clean_m = m.split("/", 1)[1] if "/" in m else (m or "deepseek-chat")
            return ("deepseek", ds_key, PROVIDER_ENDPOINTS["deepseek"], clean_m)

        if or_key:
            return ("openrouter", or_key, PROVIDER_ENDPOINTS["openrouter"], m)

        if gem_key:
            clean_m = m.split("/", 1)[1] if (m.startswith("google/gemini") or m.startswith("gemini-")) else "gemini-3-flash-preview"
            if clean_m in ("", "gemini", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash-lite"):
                clean_m = "gemini-3-flash-preview"
            return ("gemini", gem_key, PROVIDER_ENDPOINTS["gemini"], clean_m)
        if oai_key:
            clean_m = m.split("/", 1)[1] if (m.startswith("openai/") or m.startswith("gpt-")) else "gpt-4o-mini"
            return ("openai", oai_key, PROVIDER_ENDPOINTS["openai"], clean_m)
        if ant_key:
            clean_m = m.split("/", 1)[1] if (m.startswith("anthropic/") or m.startswith("claude-")) else "claude-3-7-sonnet-20250219"
            return ("anthropic", ant_key, PROVIDER_ENDPOINTS["anthropic"], clean_m)
        if ds_key:
            clean_m = m.split("/", 1)[1] if m.startswith("deepseek/") else "deepseek-chat"
            return ("deepseek", ds_key, PROVIDER_ENDPOINTS["deepseek"], clean_m)

        return (self.active_provider, "", PROVIDER_ENDPOINTS.get(self.active_provider, DEFAULT_BASE_URL), m)

    @property
    def model(self) -> str:
        return self.get_str("model", "")

    @model.setter
    def model(self, value: str) -> None:
        self.set_str("model", value)

    @property
    def base_url(self) -> str:
        return (self.get_str("base_url", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")

    @base_url.setter
    def base_url(self, value: str) -> None:
        self.set_str("base_url", (value or DEFAULT_BASE_URL).rstrip("/"))

    @property
    def execution_mode(self) -> str:
        m = self.get_str("execution_mode", "autopilot")
        return m if m in ("autopilot", "ask_write", "chat_only") else "autopilot"

    @execution_mode.setter
    def execution_mode(self, value: str) -> None:
        if value in ("autopilot", "ask_write", "chat_only"):
            self.set_str("execution_mode", value)

    @property
    def custom_instructions(self) -> str:
        return self.get_str("custom_instructions", "")

    @custom_instructions.setter
    def custom_instructions(self, value: str) -> None:
        self.set_str("custom_instructions", value)

    @property
    def auto_fallback_free(self) -> bool:
        return self.get_bool("auto_fallback_free", True)

    @auto_fallback_free.setter
    def auto_fallback_free(self, value: bool) -> None:
        self.set_bool("auto_fallback_free", value)

    @property
    def max_tokens(self) -> int:
        val = self.get_int("max_tokens", 1536)
        return max(256, min(val, 16384))

    @max_tokens.setter
    def max_tokens(self, value: int) -> None:
        self.set_int("max_tokens", max(256, min(int(value), 16384)))

    @property
    def dock_visible(self) -> bool:
        return self.get_bool("dock_visible", True)

    @dock_visible.setter
    def dock_visible(self, value: bool) -> None:
        self.set_bool("dock_visible", value)

    @property
    def xerj_url(self) -> str:
        val = (self.get_str("xerj_url", "http://127.0.0.1:9200") or "http://127.0.0.1:9200").strip().rstrip("/")
        return val

    @xerj_url.setter
    def xerj_url(self, value: str) -> None:
        clean = (value or "http://127.0.0.1:9200").strip().rstrip("/")
        self.set_str("xerj_url", clean)

    @property
    def gas_server_url(self) -> str:
        val = (
            self.get_str("gas_server_url", "https://www.geospatial-agentic-services.online")
            or "https://www.geospatial-agentic-services.online"
        ).strip().rstrip("/")
        return val

    @gas_server_url.setter
    def gas_server_url(self, value: str) -> None:
        clean = (
            value or "https://www.geospatial-agentic-services.online"
        ).strip().rstrip("/")
        self.set_str("gas_server_url", clean)

    @property
    def gas_registry_url(self) -> str:
        val = (
            self.get_str("gas_registry_url", "https://www.geospatial-agentic-services.online/registry")
            or "https://www.geospatial-agentic-services.online/registry"
        ).strip().rstrip("/")
        return val

    @gas_registry_url.setter
    def gas_registry_url(self, value: str) -> None:
        clean = (
            value or "https://www.geospatial-agentic-services.online/registry"
        ).strip().rstrip("/")
        self.set_str("gas_registry_url", clean)

    @property
    def gas_api_key(self) -> str:
        return self.get_str("gas_api_key", "")

    @gas_api_key.setter
    def gas_api_key(self, value: str) -> None:
        self.set_str("gas_api_key", value)

    @property
    def gibd_api_key(self) -> str:
        return self.get_str("gibd_api_key", "")

    @gibd_api_key.setter
    def gibd_api_key(self, value: str) -> None:
        self.set_str("gibd_api_key", value)


class ThreadHistoryStore:
    """Persistent storage for AutoGIS conversation threads."""

    def __init__(self) -> None:
        self._path = os.path.join(data_dir(), "threads.json")
        self._threads: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            self._threads = {}
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._threads = data
        except Exception as exc:
            log_warn(f"Could not load threads.json: {exc}")
            self._threads = {}

    def _save(self) -> None:
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._threads, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except Exception as exc:
            log_warn(f"Could not save threads.json: {exc}")

    def create_thread(self, title: str = "New Session") -> dict:
        tid = "th_" + uuid.uuid4().hex[:10]
        now = time.time()
        thread = {
            "id": tid,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "messages": [],
            "ui_log": [],
        }
        self._threads[tid] = thread
        self._save()
        return thread

    def get_thread(self, thread_id: str) -> dict | None:
        return self._threads.get(thread_id)

    def update_thread(self, thread_id: str, *, title: str | None = None,
                      messages: list[dict] | None = None,
                      ui_entry: dict | None = None) -> None:
        th = self._threads.get(thread_id)
        if th is None:
            th = {
                "id": thread_id,
                "title": title or "Session",
                "created_at": time.time(),
                "updated_at": time.time(),
                "messages": [],
                "ui_log": [],
            }
            self._threads[thread_id] = th
        if title:
            th["title"] = title
        if messages is not None:
            th["messages"] = messages[-60:]
        if ui_entry is not None:
            th.setdefault("ui_log", []).append(ui_entry)
        th["updated_at"] = time.time()
        self._save()

    def delete_thread(self, thread_id: str) -> None:
        if thread_id in self._threads:
            self._threads.pop(thread_id, None)
            self._save()

    def clear_all(self) -> None:
        self._threads.clear()
        self._save()

    def list_threads(self) -> list[dict]:
        items = list(self._threads.values())
        items.sort(key=lambda x: float(x.get("updated_at") or 0), reverse=True)
        return items[:50]
