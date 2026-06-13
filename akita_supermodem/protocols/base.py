import abc
from typing import Callable
from ..config import NetworkProfile, get_profile


class BaseProtocolHandler(abc.ABC):
    """
    Abstract base class for all file transfer protocols.
    Each protocol must implement the logic to send and receive files.
    """

    def __init__(
        self,
        mesh_interface=None,
        crypto_manager=None,
        save_function: Callable[[str, bytes], None] = None,
        recipient_id: str = None,
        profile: NetworkProfile = None,
    ):
        self.mesh = mesh_interface
        self.crypto = crypto_manager
        self.save = save_function
        self.recipient_id = recipient_id
        self.profile = profile or get_profile("meshtastic")

    @abc.abstractmethod
    def start_transfer(self, filepath: str) -> bool:
        """Initiates a file transfer."""
        ...

    @abc.abstractmethod
    def handle_message(self, sender_id: str, message) -> None:
        """Handles an incoming message intended for this protocol."""
        ...

    @abc.abstractmethod
    def check_timeouts(self) -> None:
        """Periodic tick to check timeouts and perform state transitions."""
        ...

    @abc.abstractmethod
    def cleanup(self) -> None:
        """Cleans up any protocol state."""
        ...
