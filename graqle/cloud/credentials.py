"""Graqle Cloud credentials — local API key storage.

Stores cloud API key in ~/.graqle/credentials.json.
Used by Studio cloud features and `graq login` command.
No signup required for local features — cloud is optional.
"""

# ── graqle:intelligence ──
# module: graqle.cloud.credentials
# risk: LOW (impact radius: 2 modules)
# consumers: test_login, test_credentials
# dependencies: __future__, json, logging, dataclasses, pathlib +1 more
# constraints: none
# ── /graqle:intelligence ──

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("graqle.cloud.credentials")

CREDENTIALS_DIR = Path.home() / ".graqle"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"


@dataclass
class CloudCredentials:
    """Cloud connection credentials."""
    api_key: str = ""
    email: str = ""
    plan: str = "free"  # free, pro, team, enterprise
    cloud_url: str = "https://api.graqle.com"
    connected: bool = False

    @property
    def is_authenticated(self) -> bool:
        return bool(self.api_key) and self.connected

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_key": self.api_key,
            "email": self.email,
            "plan": self.plan,
            "cloud_url": self.cloud_url,
            "connected": self.connected,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CloudCredentials:
        return cls(
            api_key=data.get("api_key", ""),
            email=data.get("email", ""),
            plan=data.get("plan", "free"),
            cloud_url=data.get("cloud_url", "https://api.graqle.com"),
            connected=data.get("connected", False),
        )


def load_credentials() -> CloudCredentials:
    """Load credentials from ~/.graqle/credentials.json.

    Returns default (unauthenticated) credentials if file doesn't exist.
    """
    if not CREDENTIALS_FILE.exists():
        return CloudCredentials()
    try:
        data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
        return CloudCredentials.from_dict(data)
    except Exception as e:
        logger.warning("Failed to load credentials: %s", e)
        return CloudCredentials()


def save_credentials(creds: CloudCredentials) -> None:
    """Save credentials to ~/.graqle/credentials.json."""
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(
        json.dumps(creds.to_dict(), indent=2),
        encoding="utf-8",
    )
    logger.info("Credentials saved to %s", CREDENTIALS_FILE)


def clear_credentials() -> None:
    """Remove stored credentials."""
    if CREDENTIALS_FILE.exists():
        CREDENTIALS_FILE.unlink()
        logger.info("Credentials cleared")


def get_cloud_status() -> dict[str, Any]:
    """Get cloud connection status for Studio display."""
    creds = load_credentials()
    return {
        "connected": creds.is_authenticated,
        "email": creds.email if creds.is_authenticated else "",
        "plan": creds.plan,
        "cloud_url": creds.cloud_url,
    }
