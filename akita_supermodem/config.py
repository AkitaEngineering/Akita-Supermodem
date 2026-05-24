from dataclasses import dataclass
from typing import Dict


@dataclass
class NetworkProfile:
    """Configuration profile for different network types."""

    name: str
    piece_size: int
    initial_delay: float
    max_delay: float
    timeout: float
    max_retries: int
    encryption_enabled: bool


# Default predefined profiles
NETWORK_PROFILES: Dict[str, NetworkProfile] = {
    "meshtastic": NetworkProfile(
        name="meshtastic",
        piece_size=128,  # Small packets to avoid fragmentation/MTU issues
        initial_delay=2.0,  # Very slow rate-limiting to avoid flooding the mesh
        max_delay=10.0,
        timeout=30.0,
        max_retries=5,
        encryption_enabled=True,  # E2EE strongly enforced
    ),
    "lora": NetworkProfile(
        name="lora",
        piece_size=256,
        initial_delay=1.0,
        max_delay=5.0,
        timeout=15.0,
        max_retries=5,
        encryption_enabled=True,
    ),
    "bluetooth": NetworkProfile(
        name="bluetooth",
        piece_size=512,
        initial_delay=0.1,
        max_delay=1.0,
        timeout=5.0,
        max_retries=3,
        encryption_enabled=True,
    ),
    "wifi": NetworkProfile(
        name="wifi",
        piece_size=4096,  # Larger chunks over reliable high-bandwidth
        initial_delay=0.01,
        max_delay=0.5,
        timeout=3.0,
        max_retries=3,
        encryption_enabled=True,  # Could be toggled off for raw speed if desired
    ),
}


def get_profile(name: str) -> NetworkProfile:
    """Returns the requested network profile, defaulting to 'meshtastic' if not found."""
    return NETWORK_PROFILES.get(name.lower(), NETWORK_PROFILES["meshtastic"])
