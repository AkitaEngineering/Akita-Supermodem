import json
import logging
import os
from pathlib import Path
from typing import Dict, Any

from .config import NETWORK_PROFILES

logger = logging.getLogger(__name__)

# Default to a config folder in the user's home directory
DEFAULT_CONFIG_DIR = Path(os.environ.get("AKITA_CONFIG_DIR", Path.home() / ".config" / "akita_supermodem"))
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "default_mesh_node": "!ffffffff",
    "default_profile": "meshtastic",
    "ui_port": 8080,
    "ui_host": "127.0.0.1",
    "log_level": "INFO",
}


class SettingsManager:
    """Manages persistent application settings using a JSON file."""

    def __init__(self, config_file: Path = DEFAULT_CONFIG_FILE):
        self.config_file = Path(config_file)
        self.settings: Dict[str, Any] = DEFAULT_SETTINGS.copy()
        self.load()

    def load(self):
        """Loads settings from the JSON file if it exists."""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    loaded = json.load(f)
                    for key, value in loaded.items():
                        try:
                            self.settings[key] = self._validate(key, value)
                        except (KeyError, ValueError, TypeError) as e:
                            logger.warning(f"Ignoring invalid setting {key!r}: {e}")
                logger.info(f"Loaded settings from {self.config_file}")
            except Exception as e:
                logger.error(f"Failed to load settings: {e}")
        else:
            try:
                self.save()
            except OSError as e:
                logger.warning(f"Could not create default settings file: {e}")

    def save(self):
        """Saves current settings to the JSON file."""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, "w") as f:
                json.dump(self.settings, f, indent=4)
            logger.debug(f"Saved settings to {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            raise OSError(f"Failed to save settings to {self.config_file}: {e}") from e

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def _validate(self, key: str, value: Any) -> Any:
        if key not in DEFAULT_SETTINGS:
            raise KeyError(f"Unknown setting: {key}")
        if key == "ui_port":
            port = int(value)
            if not 1 <= port <= 65535:
                raise ValueError("ui_port must be between 1 and 65535")
            return port
        if key == "ui_host":
            host = str(value).strip()
            if not host:
                raise ValueError("ui_host cannot be empty")
            return host
        if key == "default_profile":
            profile = str(value).strip().lower()
            if profile not in NETWORK_PROFILES:
                raise ValueError(f"default_profile must be one of: {', '.join(sorted(NETWORK_PROFILES))}")
            return profile
        if key == "default_mesh_node":
            node = str(value).strip()
            if not node.startswith("!"):
                raise ValueError("default_mesh_node must be a Meshtastic node ID such as !aabbccdd")
            return node
        if key == "log_level":
            level = str(value).strip().upper()
            if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
                raise ValueError("log_level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
            return level
        return value

    def set(self, key: str, value: Any):
        validated = self._validate(key, value)
        previous = self.settings.get(key)
        self.settings[key] = validated
        try:
            self.save()
        except OSError:
            self.settings[key] = previous
            raise

    def get_all(self) -> Dict[str, Any]:
        return self.settings.copy()


# Global singleton
settings = SettingsManager()
