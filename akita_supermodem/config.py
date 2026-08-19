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
    require_authentication: bool = True
    compression_enabled: bool = False
    compression_min_bytes: int = 256
    compression_level: int = 6
    max_payload_bytes: int = 220
    send_window: int = 4
    max_resume_indices: int = 32
    handshake_retries: int = 3
    inactivity_timeout: float = 300.0


# Default predefined profiles
NETWORK_PROFILES: Dict[str, NetworkProfile] = {
    "meshtastic": NetworkProfile(
        name="meshtastic",
        piece_size=128,
        initial_delay=1.5,
        max_delay=10.0,
        timeout=20.0,
        max_retries=6,
        encryption_enabled=True,
        require_authentication=True,
        compression_enabled=True,
        compression_min_bytes=96,
        max_payload_bytes=256,
        send_window=3,
        max_resume_indices=24,
        handshake_retries=4,
        inactivity_timeout=300.0,
    ),
    "lora": NetworkProfile(
        name="lora",
        piece_size=256,
        initial_delay=1.0,
        max_delay=5.0,
        timeout=15.0,
        max_retries=6,
        encryption_enabled=True,
        require_authentication=True,
        compression_enabled=True,
        compression_min_bytes=128,
        max_payload_bytes=384,
        send_window=4,
        max_resume_indices=32,
        handshake_retries=4,
        inactivity_timeout=240.0,
    ),
    "bluetooth": NetworkProfile(
        name="bluetooth",
        piece_size=512,
        initial_delay=0.1,
        max_delay=1.0,
        timeout=5.0,
        max_retries=4,
        encryption_enabled=True,
        require_authentication=True,
        compression_enabled=True,
        compression_min_bytes=256,
        max_payload_bytes=512,
        send_window=8,
        max_resume_indices=64,
        handshake_retries=3,
        inactivity_timeout=180.0,
    ),
    "wifi": NetworkProfile(
        name="wifi",
        piece_size=4096,
        initial_delay=0.01,
        max_delay=0.5,
        timeout=3.0,
        max_retries=4,
        encryption_enabled=True,
        require_authentication=True,
        compression_enabled=False,
        max_payload_bytes=8192,
        send_window=16,
        max_resume_indices=128,
        handshake_retries=3,
        inactivity_timeout=120.0,
    ),
    "uas": NetworkProfile(
        name="uas",
        piece_size=128,
        initial_delay=1.25,
        max_delay=8.0,
        timeout=15.0,
        max_retries=6,
        encryption_enabled=True,
        require_authentication=True,
        compression_enabled=True,
        compression_min_bytes=96,
        compression_level=6,
        max_payload_bytes=256,
        send_window=3,
        max_resume_indices=24,
        handshake_retries=5,
        inactivity_timeout=240.0,
    ),
}


def get_profile(name: str) -> NetworkProfile:
    """Returns a copy of the requested network profile."""
    key = (name or "").strip().lower()
    if key not in NETWORK_PROFILES:
        known = ", ".join(sorted(NETWORK_PROFILES))
        raise ValueError(f"Unknown profile {name!r}. Choose one of: {known}")
    return replace(NETWORK_PROFILES[key])
