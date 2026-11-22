from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsProject,
)

from .config import log_info, log_warn


@dataclass
class ProjectCheckpoint:
    id: str
    timestamp: float
    description: str
    crs_authid: str
    layer_ids: set[str]
    layer_names: dict[str, str]
    active_layer_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ProjectCheckpointManager:
    """Manages transactional checkpoints and one-click undo for QGIS project state."""

    _instance: ProjectCheckpointManager | None = None

    def __init__(self, iface=None, max_history: int = 15) -> None:
        self._iface = iface
        self._history: list[ProjectCheckpoint] = []
        self._max_history = max_history

    @classmethod
    def get_instance(cls, iface=None) -> ProjectCheckpointManager:
        if cls._instance is None:
            cls._instance = ProjectCheckpointManager(iface=iface)
        elif iface is not None:
            cls._instance._iface = iface
        return cls._instance

    def create_checkpoint(self, description: str = "") -> ProjectCheckpoint:
        """Capture the current state of QgsProject (CRS, loaded layers, active layer)."""
        proj = QgsProject.instance()
        proj_crs = proj.crs()
        crs_authid = proj_crs.authid() if proj_crs.isValid() else "EPSG:4326"

        active_id = None
        if self._iface and self._iface.activeLayer():
            active_id = self._iface.activeLayer().id()

        layers_map = proj.mapLayers()
        layer_ids = set(layers_map.keys())
        layer_names = {lid: lyr.name() for lid, lyr in layers_map.items()}

        checkpoint = ProjectCheckpoint(
            id=f"chk_{uuid.uuid4().hex[:8]}",
            timestamp=time.time(),
            description=description or "Manual Checkpoint",
            crs_authid=crs_authid,
            layer_ids=layer_ids,
            layer_names=layer_names,
            active_layer_id=active_id,
        )

        self._history.append(checkpoint)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        log_info(f"AutoGIS Checkpoint created: '{checkpoint.description}' (Layers: {len(layer_ids)})")
        return checkpoint

    def can_undo(self) -> bool:
        return len(self._history) > 0

    def get_last_checkpoint_description(self) -> str:
        if not self._history:
            return ""
        return self._history[-1].description

    def rollback(self) -> dict[str, Any]:
        """Roll back project to the most recent checkpoint state.

        Removes any layers that were added after the checkpoint was taken,
        restores the project CRS if altered, and refreshes the canvas.
        """
        if not self._history:
            return {"status": "failed", "error": "No checkpoints available to undo."}

        checkpoint = self._history.pop()
        proj = QgsProject.instance()

        current_layers = dict(proj.mapLayers())
        removed_layer_names: list[str] = []

        # Find layers added after this checkpoint
        for lid, lyr in current_layers.items():
            if lid not in checkpoint.layer_ids:
                lyr_name = lyr.name()
                try:
                    proj.removeMapLayer(lid)
                    removed_layer_names.append(lyr_name)
                except Exception as exc:
                    log_warn(f"Failed to remove layer {lyr_name} during rollback: {exc}")

        # Restore project CRS if changed
        current_crs = proj.crs().authid() if proj.crs().isValid() else ""
        if checkpoint.crs_authid and current_crs != checkpoint.crs_authid:
            try:
                restored_crs = QgsCoordinateReferenceSystem(checkpoint.crs_authid)
                if restored_crs.isValid():
                    proj.setCrs(restored_crs)
            except Exception as crs_exc:
                log_warn(f"Failed to restore CRS {checkpoint.crs_authid}: {crs_exc}")

        # Restore active layer if still valid
        if self._iface and checkpoint.active_layer_id:
            restored_lyr = proj.mapLayer(checkpoint.active_layer_id)
            if restored_lyr:
                try:
                    self._iface.setActiveLayer(restored_lyr)
                except Exception as _err:
                    _ = _err

        # Refresh map canvas
        if self._iface and self._iface.mapCanvas():
            try:
                self._iface.mapCanvas().refresh()
            except Exception as _err:
                _ = _err

        msg = f"Successfully rolled back to: '{checkpoint.description}'"
        if removed_layer_names:
            msg += f" (Removed {len(removed_layer_names)} newly added layer(s): {', '.join(removed_layer_names)})"

        log_info(f"AutoGIS Rollback: {msg}")
        return {
            "status": "success",
            "message": msg,
            "checkpoint_id": checkpoint.id,
            "checkpoint_description": checkpoint.description,
            "removed_layers": removed_layer_names,
            "remaining_checkpoints": len(self._history),
        }

    def clear(self) -> None:
        self._history.clear()
