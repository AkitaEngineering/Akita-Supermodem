# akita_supermodem/__init__.py

# Make key classes and constants available when importing the package
# Use try/except to allow importing common utilities even if protobuf code isn't generated
try:
    from .sender import AkitaSender
    from .receiver import AkitaReceiver
except ImportError:
    # Protobuf code not generated yet - allow partial imports for testing
    AkitaSender = None
    AkitaReceiver = None

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

# You might also want to expose the generated protobuf message types if needed directly
# from .generated import akita_pb2

__version__ = "0.1.0"  # Keep in sync with pyproject.toml

__all__ = [
    "AkitaSender",
    "AkitaReceiver",
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
    # "akita_pb2", # Uncomment if you want to expose protobuf definitions directly
]

print(f"Akita Supermodem Package Initialized (Version: {__version__})")
