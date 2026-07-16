from dataclasses import dataclass, replace
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
    require_authentication: bool = False
    compression_enabled: bool = False
    compression_min_bytes: int = 256
    compression_level: int = 6


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
        compression_enabled=True,
        compression_min_bytes=96,
    ),
    "lora": NetworkProfile(
        name="lora",
        piece_size=256,
        initial_delay=1.0,
        max_delay=5.0,
        timeout=15.0,
        max_retries=5,
        encryption_enabled=True,
        compression_enabled=True,
        compression_min_bytes=128,
    ),
    "bluetooth": NetworkProfile(
        name="bluetooth",
        piece_size=512,
        initial_delay=0.1,
        max_delay=1.0,
        timeout=5.0,
        max_retries=3,
        encryption_enabled=True,
        compression_enabled=True,
        compression_min_bytes=256,
    ),
    "wifi": NetworkProfile(
        name="wifi",
        piece_size=4096,  # Larger chunks over reliable high-bandwidth
        initial_delay=0.01,
        max_delay=0.5,
        timeout=3.0,
        max_retries=3,
        encryption_enabled=True,  # Could be toggled off for raw speed if desired
        compression_enabled=False,
    ),
    "uas": NetworkProfile(
        name="uas",
        piece_size=128,
        initial_delay=2.0,
        max_delay=10.0,
        timeout=20.0,
        max_retries=5,
        encryption_enabled=True,
        require_authentication=True,
        compression_enabled=True,
        compression_min_bytes=96,
        compression_level=6,
    ),
}


def get_profile(name: str) -> NetworkProfile:
    """Returns the requested network profile, defaulting to 'meshtastic' if not found."""
    profile = NETWORK_PROFILES.get(name.lower(), NETWORK_PROFILES["meshtastic"])
    return replace(profile)
