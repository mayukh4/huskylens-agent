import os
"""Home Assistant REST API controller for gesture-triggered smart home actions."""

import logging
import requests

logger = logging.getLogger(__name__)

HA_URL = "http://192.168.40.23:8123"
HA_TOKEN = os.environ.get("HA_TOKEN", "")


class HAController:
    def __init__(self, base_url=HA_URL, token=HA_TOKEN):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def toggle(self, entity_id: str) -> bool:
        """Toggle a switch entity. Returns True on success."""
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
        """Get the current state of an entity."""
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
