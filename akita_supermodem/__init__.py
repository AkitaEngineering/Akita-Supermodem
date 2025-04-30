# akita_supermodem/__init__.py

# Make key classes and constants available when importing the package
from .sender import AkitaSender
from .receiver import AkitaReceiver
from .common import AKITA_CONTENT_TYPE

# You might also want to expose the generated protobuf message types if needed directly
# from .generated import akita_pb2

__version__ = "0.1.0" # Keep in sync with pyproject.toml

__all__ = [
    "AkitaSender",
    "AkitaReceiver",
    "AKITA_CONTENT_TYPE",
    # "akita_pb2", # Uncomment if you want to expose protobuf definitions directly
]

print(f"Akita Supermodem Package Initialized (Version: {__version__})")

