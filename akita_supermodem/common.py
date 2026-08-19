# akita_supermodem/common.py

"""
Common constants and potentially shared utility functions for Akita Supermodem.
"""

import hashlib
import logging
import os
import shutil
from pathlib import Path

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

# Authenticated encryption requires a high-entropy shared secret.
MIN_PSK_BYTES = 16
REPLAY_WINDOW = 4096

# CRC-32C (Castagnoli, poly 0x1EDC6F41). Stronger Hamming detection than
# ZMODEM/YMODEM CRC-32 and hardware-friendly. Combined with SHA-256 Merkle
# checks this is cryptographic integrity plus cheap per-piece rejection.
_CRC32C_POLY = 0x82F63B78


def _crc32c_table() -> list[int]:
    table = []
    for index in range(256):
        crc = index
        for _ in range(8):
            crc = (crc >> 1) ^ _CRC32C_POLY if crc & 1 else crc >> 1
        table.append(crc)
    return table


_CRC32C_TABLE = _crc32c_table()


class Crc32c:
    """Incremental CRC-32C over streamed bytes."""

    def __init__(self) -> None:
        self._crc = 0xFFFFFFFF

    def update(self, data: bytes) -> "Crc32c":
        crc = self._crc
        table = _CRC32C_TABLE
        for byte in data:
            crc = table[(crc ^ byte) & 0xFF] ^ (crc >> 8)
        self._crc = crc
        return self

    def digest(self) -> int:
        return self._crc ^ 0xFFFFFFFF


def crc32c(data: bytes) -> int:
    """Returns the CRC-32C of data as an unsigned 32-bit integer."""
    return Crc32c().update(data).digest()


def publish_file(source: str | Path, destination: str | Path) -> None:
    """Atomically publish source onto destination, including across filesystems."""
    source_path = Path(source)
    destination_path = Path(destination)
    try:
        os.replace(source_path, destination_path)
    except OSError:
        shutil.move(str(source_path), str(destination_path))


def crc32c_file(filepath: str, chunk_size: int = 65536) -> int:
    """Returns the CRC-32C of a file without loading it all into memory."""
    digest = Crc32c()
    with open(filepath, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.digest()


class ReplayGuard:
    """Bounded sliding-window replay detector for encrypted sequence numbers."""

    def __init__(self, window: int = REPLAY_WINDOW) -> None:
        self.window = window
        self.max_seen = -1
        self.seen: set[int] = set()

    def accept(self, sequence: int) -> bool:
        if sequence < 0:
            return False
        if sequence in self.seen:
            return False
        if self.max_seen >= 0 and sequence < self.max_seen - self.window:
            return False
        self.seen.add(sequence)
        if sequence > self.max_seen:
            self.max_seen = sequence
        cutoff = self.max_seen - self.window
        if cutoff >= 0 and len(self.seen) > self.window:
            self.seen = {item for item in self.seen if item > cutoff}
        return True

    def snapshot(self) -> dict:
        return {"max_seen": self.max_seen, "seen": sorted(self.seen)}

    def restore(self, data: dict | None) -> None:
        if not data:
            return
        self.max_seen = int(data.get("max_seen", -1))
        self.seen = {int(item) for item in data.get("seen", [])}


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
