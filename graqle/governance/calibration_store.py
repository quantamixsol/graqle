# ------------------------------------------------------------------
# PATENT NOTICE -- Quantamix Solutions B.V.
#
# This module implements methods covered by European Patent
# Application EP26166054.2 (Divisional, Claims F-J), owned by
# Quantamix Solutions B.V.
#
# Use of this software is permitted under the graqle license.
# Reimplementation of the patented methods outside this software
# requires a separate patent license.
#
# Contact: support@quantamixsolutions.com
# ------------------------------------------------------------------

"""Versioned Calibration Model Persistence (R20 ADR-203).

Stores fitted calibration models at .graqle/calibration/{version}.json
with an index of all models for audit and rollback.

Each calibration run is versioned — never overwritten. The "active"
model is tracked via a symlink or current.json pointer.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graqle.governance.calibration import CalibrationModel

logger = logging.getLogger("graqle.governance.calibration_store")

_DEFAULT_DIR = ".graqle/calibration"
_CURRENT_FILE = "current.json"
_INDEX_FILE = "index.json"


class CalibrationStore:
    """Append-only versioned calibration model store.

    Storage layout:
        .graqle/calibration/
          {version}.json       - individual calibration models
          current.json         - pointer to active model
          index.json           - chronological index of all models

    Parameters
    ----------
    store_dir:
        Directory for calibration files. Created if missing.
    """

    def __init__(self, store_dir: str | Path | None = None) -> None:
        if store_dir is None:
            store_dir = _DEFAULT_DIR
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def store_dir(self) -> Path:
        return self._dir

    def save(self, model: CalibrationModel, make_active: bool = True) -> Path:
        """Persist a calibration model and optionally mark it active.

        Returns the path where the model was written.
        """
        version = model.version
        file_path = self._dir / f"{version}.json"

        # Atomic write: temp file + rename
        tmp_path = file_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(model.model_dump(mode="json"), f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)

        # Update index
        self._append_index({
            "version": version,
            "method": model.method,
            "status": model.status,
            "n_samples": model.n_samples,
            "ece": model.ece,
            "ece_passed": model.ece_passed,
            "created_at": model.created_at.isoformat() if isinstance(model.created_at, datetime) else str(model.created_at),
            "file": f"{version}.json",
        })

        # Update current pointer
        if make_active and model.status == "calibrated":
            self._set_current(version)

        logger.debug("Calibration model saved: %s (status=%s, ece=%s)",
                     version, model.status, model.ece)
        return file_path

    def load(self, version: str) -> CalibrationModel:
        """Load a specific calibration model by version."""
        file_path = self._dir / f"{version}.json"
        if not file_path.exists():
            raise FileNotFoundError(f"Calibration model not found: {version}")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return CalibrationModel(**data)

    def load_current(self) -> CalibrationModel | None:
        """Load the currently active calibration model, if any."""
        current = self._dir / _CURRENT_FILE
        if not current.exists():
            return None
        try:
            with open(current, "r", encoding="utf-8") as f:
                pointer = json.load(f)
            version = pointer.get("version")
            if version:
                return self.load(version)
        except (json.JSONDecodeError, FileNotFoundError):
            return None
        return None

    def list_versions(self) -> list[dict[str, Any]]:
        """List all calibration versions in chronological order."""
        index = self._read_index()
        return index

    def _set_current(self, version: str) -> None:
        """Update the current.json pointer to point to a version."""
        current = self._dir / _CURRENT_FILE
        tmp = current.with_suffix(".json.tmp")
        pointer = {
            "version": version,
            "activated_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pointer, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, current)

    def _append_index(self, entry: dict[str, Any]) -> None:
        """Append an entry to the chronological index."""
        index = self._read_index()
        index.append(entry)
        index_path = self._dir / _INDEX_FILE
        tmp = index_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, index_path)

    def _read_index(self) -> list[dict[str, Any]]:
        """Read the chronological index (empty if missing)."""
        index_path = self._dir / _INDEX_FILE
        if not index_path.exists():
            return []
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
