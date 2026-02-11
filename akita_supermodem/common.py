# akita_supermodem/common.py

"""
Common constants and potentially shared utility functions for Akita Supermodem.
"""

import hashlib
import os
import logging

# Set up module-level logger
logger = logging.getLogger(__name__)

# Meshtastic PortNum used for Akita Supermodem packets.
# Choose a unique number within the Meshtastic private app range (e.g., 64-255)
# Or use the standard dynamic port range (e.g., 1024+).
# Using 123 as originally specified. Ensure this doesn't clash with other apps.
AKITA_CONTENT_TYPE = 123  # In Meshtastic v2+, this refers to the PortNum

# Standard hash algorithm used throughout the protocol
HASH_ALGORITHM = "sha256"


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


def sanitize_filename(filename: str) -> str:
    """
    Sanitizes a filename to prevent path traversal attacks and remove dangerous characters.

    Args:
        filename: The original filename (potentially unsafe).

    Returns:
        A sanitized filename safe for use in file operations.
    """
    # Remove any path components (prevents directory traversal)
    safe = os.path.basename(filename)
    # Remove any remaining dangerous characters, keep alphanumeric and safe punctuation
    safe = "".join(c for c in safe if c.isalnum() or c in "._-")
    # Ensure it's not empty or just dots (handle any number of dots)
    if not safe or safe.strip(".") == "":
        return "unnamed_file"
    # Limit length to prevent filesystem issues
    if len(safe) > 255:
        name, ext = os.path.splitext(safe)
        safe = name[: 255 - len(ext)] + ext
    return safe


# You could add other shared constants or simple utilities here if needed.
# For example, default piece size, timeout values if they need to be consistent
# across sender/receiver and potentially configurable.

DEFAULT_PIECE_SIZE = 1024  # Default bytes per piece
DEFAULT_TIMEOUT = 5.0  # Default seconds before requesting retransmission
DEFAULT_MAX_RETRIES = 3  # Default max retries for a piece

# Rate control constants
DEFAULT_INITIAL_DELAY = 0.1  # Initial delay between piece sends (seconds)
DEFAULT_MAX_DELAY = 2.0  # Maximum delay between piece sends (seconds)
DEFAULT_DELAY_INCREMENT = 0.1  # Delay increment on packet loss (seconds)

# Transfer limits
MAX_PIECE_SIZE = 1024 * 1024  # Maximum piece size (1MB)
MIN_PIECE_SIZE = 64  # Minimum piece size (64 bytes)
MAX_FILE_SIZE = 1024 * 1024 * 1024 * 10  # Maximum file size (10GB)


def calculate_merkle_root(hashes: list[str]) -> str | None:
    """
    Calculates the Merkle root for a list of hex-encoded SHA256 hashes.

    This function builds a Merkle tree by repeatedly hashing pairs of nodes
    until a single root hash remains. If there's an odd number of nodes at any
    level, the last node is duplicated.

    Args:
        hashes: List of hex-encoded hash strings. Must be valid hex strings
                representing SHA256 hashes.

    Returns:
        The hex-encoded Merkle root hash, or None if the input is invalid
        or empty (empty list returns hash of empty bytes).

    Example:
        >>> hashes = ["abc123...", "def456..."]
        >>> root = calculate_merkle_root(hashes)
    """
    import hashlib

    if not hashes:
        return calculate_hash(b"")  # Hash of empty data

    # Convert hex strings to bytes for hashing
    try:
        tree: list[bytes] = [bytes.fromhex(h) for h in hashes]
    except ValueError as e:
        logger.error(f"Error decoding hex hash: {e}. Cannot calculate Merkle root.")
        return None

    if not tree:  # Safety check
        return None

    # Build Merkle tree by repeatedly hashing pairs
    while len(tree) > 1:
        next_level: list[bytes] = []
        for i in range(0, len(tree), 2):
            left = tree[i]
            # If odd number of nodes, duplicate the last one
            right = tree[i + 1] if i + 1 < len(tree) else left
            # Combine and hash
            combined_hash = hashlib.sha256(left + right).digest()
            next_level.append(combined_hash)
        tree = next_level

    # Return the final root hash as a hex string
    return tree[0].hex() if tree else None
