"""Local Google Earth Engine credential helpers for AutoGIS.

Credentials are read from the user's local QGIS settings or an explicitly selected
service-account JSON file. They are never sent to the AutoGIS web portal.
"""
from __future__ import annotations

import json
import os
from typing import Any

from .config import AutoGISConfig

def get_oauth_credentials_project() -> str:
    """Read default project ID from ~/.config/earthengine/credentials if present."""
    cred_path = os.path.expanduser("~/.config/earthengine/credentials")
    if os.path.isfile(cred_path):
        try:
            with open(cred_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                proj = str(data.get("project") or data.get("project_id") or data.get("quota_project_id") or "").strip()
                if proj:
                    return proj
        except Exception as err:
            _ = err
    return ""


def get_gee_config() -> dict[str, str]:
    config = AutoGISConfig()
    proj = config.gee_project_id.strip() or get_oauth_credentials_project()
    return {
        "project_id": proj,
        "service_account": config.gee_service_account,
        "key_file": config.gee_key_file,
    }


def save_gee_config(project_id: str, service_account: str = "", key_file: str = "") -> None:
    """Persist local Earth Engine project and optional service-account file path."""
    project_id = (project_id or "").strip()
    service_account = (service_account or "").strip()
    key_file = os.path.abspath(os.path.expanduser(key_file.strip())) if key_file.strip() else ""
    if key_file and not os.path.isfile(key_file):
        raise FileNotFoundError("The selected Earth Engine service-account JSON file does not exist.")
    if key_file:
        with open(key_file, "r", encoding="utf-8") as fh:
            payload: Any = json.load(fh)
        if not isinstance(payload, dict) or not payload.get("private_key") or not payload.get("client_email"):
            raise ValueError("The JSON file is not a valid service-account key.")
        if service_account and service_account != str(payload["client_email"]):
            raise ValueError("The service-account email does not match the selected JSON key.")
        service_account = str(payload["client_email"])
    config = AutoGISConfig()
    config.gee_project_id = project_id
    config.gee_service_account = service_account
    config.gee_key_file = key_file


def initialize_earth_engine(override_project: str = "") -> tuple[bool, str]:
    """Initialize the Earth Engine Python API with the user's local credentials."""
    config = get_gee_config()
    project_id = (override_project or config["project_id"] or get_oauth_credentials_project()).strip()
    if not project_id:
        return False, "Set your Google Earth Engine Cloud Project ID in AutoGIS Settings."
    try:
        import ee  # type: ignore
        key_file = config["key_file"]
        if key_file:
            credentials = ee.ServiceAccountCredentials(config["service_account"], key_file)
            ee.Initialize(credentials, project=project_id)
        else:
            # Uses the user's local Earth Engine OAuth credentials.
            ee.Initialize(project=project_id)
        return True, f"Earth Engine initialized for project {project_id}."
    except ImportError:
        return False, "Earth Engine API is not installed in this QGIS Python environment (pip install earthengine-api)."
    except Exception as exc:
        fallback_proj = get_oauth_credentials_project()
        if fallback_proj and fallback_proj != project_id:
            try:
                import ee  # type: ignore
                ee.Initialize(project=fallback_proj)
                AutoGISConfig().gee_project_id = fallback_proj
                return True, f"Earth Engine initialized for project {fallback_proj}."
            except Exception as err2:
                _ = err2
        return False, f"Earth Engine initialization failed: {exc}"
