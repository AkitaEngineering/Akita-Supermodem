try:
    from .transfer_manager import TransferManager
    from .crypto import CryptoManager
except (ImportError, TypeError):
    TransferManager = None
    CryptoManager = None

from .common import (
    AKITA_CONTENT_TYPE,
    DEFAULT_PIECE_SIZE,
    DEFAULT_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_INITIAL_DELAY,
    DEFAULT_MAX_DELAY,
    DEFAULT_DELAY_INCREMENT,
    MIN_PIECE_SIZE,
    MAX_PIECE_SIZE,
    MAX_FILE_SIZE,
    sanitize_filename,
    calculate_hash,
    calculate_merkle_root,
)

__version__ = "0.1.0"

__all__ = [
    "TransferManager",
    "CryptoManager",
    "AKITA_CONTENT_TYPE",
    "DEFAULT_PIECE_SIZE",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_INITIAL_DELAY",
    "DEFAULT_MAX_DELAY",
    "DEFAULT_DELAY_INCREMENT",
    "MIN_PIECE_SIZE",
    "MAX_PIECE_SIZE",
    "MAX_FILE_SIZE",
    "sanitize_filename",
    "calculate_hash",
    "calculate_merkle_root",
]
