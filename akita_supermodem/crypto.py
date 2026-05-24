import os
import logging
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

logger = logging.getLogger(__name__)


class CryptoManager:
    """
    Manages End-to-End Encryption (E2EE) for Akita Supermodem.
    Uses X25519 for ECDH key exchange and ChaCha20-Poly1305 for AEAD.
    """

    def __init__(self, encryption_enabled: bool = True):
        self.encryption_enabled = encryption_enabled
        if self.encryption_enabled:
            # Generate our ephemeral X25519 keypair for a session
            self._private_key = x25519.X25519PrivateKey.generate()
            self._public_key = self._private_key.public_key()
        else:
            self._private_key = None
            self._public_key = None
            
        self._shared_key = None
        self._chacha = None

    def get_public_key_bytes(self) -> bytes:
        """Returns the public key in raw bytes format (32 bytes)."""
        if not self.encryption_enabled:
            return b'\x00' * 32
            
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )

    def derive_shared_key(self, peer_public_key_bytes: bytes) -> bool:
        """
        Derives the shared secret from the peer's raw public key bytes.
        """
        if not self.encryption_enabled:
            self._shared_key = b'\x00' * 32
            return True
            
        if len(peer_public_key_bytes) != 32:
            logger.error("Invalid peer public key length. Must be 32 bytes.")
            return False

        try:
            peer_public_key = x25519.X25519PublicKey.from_public_bytes(
                peer_public_key_bytes
            )
            # The shared key derived from X25519 is 32 bytes, perfect for ChaCha20-Poly1305
            self._shared_key = self._private_key.exchange(peer_public_key)
            self._chacha = ChaCha20Poly1305(self._shared_key)
            logger.debug("Successfully derived shared key and initialized cipher.")
            return True
        except Exception as e:
            logger.error(f"Error deriving shared key: {e}")
            return False

    def is_ready(self) -> bool:
        """Returns True if the shared key has been derived and cipher is ready."""
        if not self.encryption_enabled:
            return self._shared_key is not None
        return self._chacha is not None

    def encrypt(self, data: bytes) -> tuple[bytes, bytes]:
        """
        Encrypts data using ChaCha20-Poly1305.

        Returns:
            A tuple of (nonce, ciphertext). The ciphertext includes the 16-byte MAC.
        """
        if not self.is_ready():
            raise RuntimeError(
                "CryptoManager is not ready. Must derive shared key first."
            )

        if not self.encryption_enabled:
            return b'\x00' * 12, data

        # ChaCha20-Poly1305 requires a 12-byte nonce
        nonce = os.urandom(12)
        # encrypt(nonce, data, associated_data)
        # associated_data is None here, but could be used to bind the packet to the session
        ciphertext = self._chacha.encrypt(nonce, data, None)
        return nonce, ciphertext

    def decrypt(self, nonce: bytes, ciphertext: bytes) -> bytes:
        """
        Decrypts data using ChaCha20-Poly1305 and verifies its MAC.

        Returns:
            The decrypted bytes.
        Raises:
            cryptography.exceptions.InvalidTag if MAC verification fails.
        """
        if not self.is_ready():
            raise RuntimeError(
                "CryptoManager is not ready. Must derive shared key first."
            )

        if not self.encryption_enabled:
            return ciphertext

        if len(nonce) != 12:
            raise ValueError(f"Invalid nonce length. Expected 12, got {len(nonce)}")

        # This will raise InvalidTag if the data was tampered with
        return self._chacha.decrypt(nonce, ciphertext, None)
