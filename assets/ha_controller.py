"""Home Assistant REST API controller for gesture-triggered smart home actions.

Optional: if HA_URL or HA_TOKEN is unset, the controller is disabled and all
calls are no-ops. This lets tars-vision run without a Home Assistant instance.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

HA_URL = os.environ.get("HA_URL", "")
HA_TOKEN = os.environ.get("HA_TOKEN", "")


class HAController:
    def __init__(self, base_url=HA_URL, token=HA_TOKEN):
        self.enabled = bool(base_url and token)
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        } if self.enabled else {}

    def toggle(self, entity_id: str) -> bool:
        """Toggle a switch entity. Returns True on success. No-op when disabled."""
        if not self.enabled:
            logger.info(f"HA not configured — skipping toggle of {entity_id}")
            return False
        try:
            resp = requests.post(
                f"{self.base_url}/api/services/switch/toggle",
                json={"entity_id": entity_id},
                headers=self.headers,
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"HA toggle {entity_id} failed: {e}")
            return False

    def get_state(self, entity_id: str) -> str:
        """Get the current state of an entity. Returns 'unknown' when disabled."""
        if not self.enabled:
            return "unknown"
        try:
            resp = requests.get(
                f"{self.base_url}/api/states/{entity_id}",
                headers=self.headers,
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("state", "unknown")
        except Exception as e:
            logger.error(f"HA get_state {entity_id} failed: {e}")
        return "unknown"
