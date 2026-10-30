"""Local Google Earth Engine credential helpers for AutoGIS.

Credentials are read from the user's local QGIS settings or an explicitly selected
service-account JSON file. They are never sent to the AutoGIS web portal.
"""
from __future__ import annotations

import json
import os
from typing import Any

from qgis.core import QgsSettings

PREFIX = "AutoGIS/gee"


def _settings() -> QgsSettings:
    return QgsSettings()


def get_gee_config() -> dict[str, str]:
    settings = _settings()
    return {
        "project_id": str(settings.value(f"{PREFIX}/project_id", "", type=str) or "").strip(),
        "service_account": str(settings.value(f"{PREFIX}/service_account", "", type=str) or "").strip(),
        "key_file": str(settings.value(f"{PREFIX}/key_file", "", type=str) or "").strip(),
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
    settings = _settings()
    settings.setValue(f"{PREFIX}/project_id", project_id)
    settings.setValue(f"{PREFIX}/service_account", service_account)
    settings.setValue(f"{PREFIX}/key_file", key_file)
    settings.sync()


def initialize_earth_engine() -> tuple[bool, str]:
    """Initialize the Earth Engine Python API with the user's local credentials."""
    config = get_gee_config()
    project_id = config["project_id"]
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
        return False, f"Earth Engine initialization failed: {exc}"
