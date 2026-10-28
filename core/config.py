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
    ("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai"),
    ("openai", "OpenAI (ChatGPT)", "https://api.openai.com/v1"),
    ("anthropic", "Anthropic (Claude)", "https://api.anthropic.com/v1"),
    ("deepseek", "DeepSeek", "https://api.deepseek.com/v1"),
    ("openrouter", "OpenRouter (All Models)", "https://openrouter.ai/api/v1"),
]

PROVIDER_ENDPOINTS: dict[str, str] = {pid: url for pid, _, url in PROVIDERS}

FALLBACK_CHAIN: list[str] = [
    "google/gemini-2.5-flash",
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "deepseek/deepseek-chat",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
]

PROVIDER_MODELS: dict[str, list[tuple[str, str]]] = {
    "gemini": [
        ("google/gemini-2.5-flash", "Gemini 2.5 Flash"),
        ("google/gemini-2.5-pro", "Gemini 2.5 Pro"),
        ("google/gemini-2.0-flash", "Gemini 2.0 Flash"),
    ],
    "openai": [
        ("openai/gpt-4o-mini", "GPT-4o Mini"),
        ("openai/gpt-4o", "GPT-4o"),
        ("openai/o3-mini", "OpenAI o3-mini"),
    ],
    "anthropic": [
        ("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5"),
        ("anthropic/claude-haiku-4.5", "Claude Haiku 4.5"),
        ("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet"),
    ],
    "deepseek": [
        ("deepseek/deepseek-chat", "DeepSeek V3"),
        ("deepseek/deepseek-reasoner", "DeepSeek R1"),
    ],
    "openrouter": [
        ("nvidia/nemotron-3-ultra-550b-a55b:free", "Nemotron 3 Ultra (Free)"),
        ("nvidia/nemotron-3.5-lightning:free", "Nemotron 3.5 Fast (Free)"),
        ("google/gemma-4-31b-it:free", "Gemma 4 31B (Free)"),
        ("deepseek/deepseek-chat-v3-0324:free", "DeepSeek V3 (Free)"),
        ("meta-llama/llama-3.3-70b-instruct:free", "Llama 3.3 70B (Free)"),
        ("google/gemini-2.5-flash", "Gemini 2.5 Flash"),
        ("openai/gpt-4o-mini", "GPT-4o Mini"),
        ("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5"),
        ("deepseek/deepseek-chat", "DeepSeek V3"),
        ("qwen/qwen-2.5-72b-instruct", "Qwen 2.5 72B"),
    ],
}

CURATED_MODELS: list[tuple[str, str]] = [
    ("", "Select Model"),
    ("google/gemini-2.5-flash", "Gemini 2.5 Flash"),
    ("google/gemini-2.5-pro", "Gemini 2.5 Pro"),
    ("google/gemini-2.0-flash", "Gemini 2.0 Flash"),
    ("openai/gpt-4o-mini", "GPT-4o Mini"),
    ("openai/gpt-4o", "GPT-4o"),
    ("openai/o3-mini", "OpenAI o3-mini"),
    ("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5"),
    ("anthropic/claude-haiku-4.5", "Claude Haiku 4.5"),
    ("deepseek/deepseek-chat", "DeepSeek V3"),
    ("deepseek/deepseek-reasoner", "DeepSeek R1"),
    ("qwen/qwen-2.5-72b-instruct", "Qwen 2.5 72B"),
    ("meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B"),
    ("nvidia/nemotron-3-ultra-550b-a55b:free", "Nemotron 3 Ultra (Free)"),
    ("nvidia/nemotron-3.5-lightning:free", "Nemotron 3.5 Fast (Free)"),
    ("google/gemma-4-31b-it:free", "Gemma 4 31B (Free)"),
    ("deepseek/deepseek-chat-v3-0324:free", "DeepSeek V3 (Free)"),
    ("meta-llama/llama-3.3-70b-instruct:free", "Llama 3.3 70B (Free)"),
]

_MEM_CACHE: dict[str, Any] = {}


def log_info(msg: str) -> None:
    try:
        QgsMessageLog.logMessage(str(msg), "AutoGIS", level=0)
    except Exception:
        pass


def log_warn(msg: str) -> None:
    try:
        QgsMessageLog.logMessage(str(msg), "AutoGIS", level=1)
    except Exception:
        pass


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
            val = self._qs.value(self._k(key), default)
        res = str(val) if val is not None else default
        _MEM_CACHE[key] = res
        return res

    def set_str(self, key: str, value: str) -> None:
        val = str(value or "").strip()
        _MEM_CACHE[key] = val
        try:
            self._qs.setValue(self._k(key), val)
            self._qs.sync()
        except Exception:
            pass

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
        )
        for k in keys:
            _MEM_CACHE[k] = ""
            try:
                self._qs.remove(self._k(k))
            except Exception:
                pass
        try:
            self._qs.sync()
        except Exception:
            pass

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
            "openrouter": "api_key",
            "gemini": "gemini_key",
            "openai": "openai_key",
            "anthropic": "anthropic_key",
            "deepseek": "deepseek_key",
        }
        k = key_map.get(provider_id, "api_key")
        self.set_str(k, value)

    @property
    def custom_logo_path(self) -> str:
        return self.get_str("custom_logo_path", "")

    @custom_logo_path.setter
    def custom_logo_path(self, value: str) -> None:
        self.set_str("custom_logo_path", value)

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
        if not m:
            return ("none", "", self.base_url, "")

        or_key = self.api_key
        gem_key = self.gemini_key
        oai_key = self.openai_key
        ant_key = self.anthropic_key
        ds_key = self.deepseek_key

        # Auto-detect if user pasted an OpenRouter key (sk-or-...) into any provider box
        for k in (or_key, gem_key, oai_key, ant_key, ds_key):
            if k.startswith("sk-or-"):
                or_key = k
                break

        # If active provider is openrouter and we have an openrouter key, route directly via openrouter
        if self.active_provider == "openrouter" and or_key:
            return ("openrouter", or_key, PROVIDER_ENDPOINTS["openrouter"], m)

        if (m.startswith("google/gemini") or m.startswith("gemini-")) and gem_key and not gem_key.startswith("sk-or-"):
            clean_m = m.split("/", 1)[1] if "/" in m else m
            return ("gemini", gem_key, PROVIDER_ENDPOINTS["gemini"], clean_m)

        if (m.startswith("openai/") or m.startswith("gpt-") or m.startswith("o1") or m.startswith("o3")) and oai_key and not oai_key.startswith("sk-or-"):
            clean_m = m.split("/", 1)[1] if "/" in m else m
            return ("openai", oai_key, PROVIDER_ENDPOINTS["openai"], clean_m)

        if (m.startswith("anthropic/") or m.startswith("claude-")) and ant_key and not ant_key.startswith("sk-or-"):
            clean_m = m.split("/", 1)[1] if "/" in m else m
            return ("anthropic", ant_key, PROVIDER_ENDPOINTS["anthropic"], clean_m)

        if (m.startswith("deepseek/") or m.startswith("deepseek-")) and ds_key and not ds_key.startswith("sk-or-"):
            clean_m = m.split("/", 1)[1] if "/" in m else m
            return ("deepseek", ds_key, PROVIDER_ENDPOINTS["deepseek"], clean_m)

        if or_key:
            return ("openrouter", or_key, PROVIDER_ENDPOINTS["openrouter"], m)

        if gem_key:
            clean_m = m.split("/", 1)[1] if (m.startswith("google/gemini") or m.startswith("gemini-")) else "gemini-2.5-flash"
            return ("gemini", gem_key, PROVIDER_ENDPOINTS["gemini"], clean_m)
        if oai_key:
            clean_m = m.split("/", 1)[1] if (m.startswith("openai/") or m.startswith("gpt-")) else "gpt-4o-mini"
            return ("openai", oai_key, PROVIDER_ENDPOINTS["openai"], clean_m)
        if ant_key:
            clean_m = m.split("/", 1)[1] if (m.startswith("anthropic/") or m.startswith("claude-")) else "claude-haiku-4-5"
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
