import json
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Default to a config folder in the user's home directory
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "akita_supermodem"
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
                    self.settings.update(loaded)
                logger.info(f"Loaded settings from {self.config_file}")
            except Exception as e:
                logger.error(f"Failed to load settings: {e}")
        else:
            self.save()  # Create with defaults

    def save(self):
        """Saves current settings to the JSON file."""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, "w") as f:
                json.dump(self.settings, f, indent=4)
            logger.debug(f"Saved settings to {self.config_file}")
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any):
        self.settings[key] = value
        self.save()

    def get_all(self) -> Dict[str, Any]:
        return self.settings.copy()


# Global singleton
settings = SettingsManager()
