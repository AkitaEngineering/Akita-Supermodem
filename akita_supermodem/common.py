# akita_supermodem/common.py

"""
Common constants and potentially shared utility functions for Akita Supermodem.
"""

import hashlib

# Meshtastic PortNum used for Akita Supermodem packets.
# Choose a unique number within the Meshtastic private app range (e.g., 64-255)
# Or use the standard dynamic port range (e.g., 1024+).
# Using 123 as originally specified. Ensure this doesn't clash with other apps.
AKITA_CONTENT_TYPE = 123 # In Meshtastic v2+, this refers to the PortNum

# Standard hash algorithm used throughout the protocol
HASH_ALGORITHM = 'sha256'

def calculate_hash(data: bytes) -> str:
    """
    Calculates the hash of the given data using the standard algorithm.

    Args:
        data: The bytes data to hash.

    Returns:
        The hexadecimal representation of the hash digest.
    """
    hasher = hashlib.new(HASH_ALGORITHM)
    hasher.update(data)
    return hasher.hexdigest()

# You could add other shared constants or simple utilities here if needed.
# For example, default piece size, timeout values if they need to be consistent
# across sender/receiver and potentially configurable.

DEFAULT_PIECE_SIZE = 1024 # Default bytes per piece
DEFAULT_TIMEOUT = 5.0     # Default seconds before requesting retransmission
DEFAULT_MAX_RETRIES = 3   # Default max retries for a piece

