import os
import logging
from typing import Optional
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger(__name__)


class CryptoManager:
    """
    Manages End-to-End Encryption (E2EE) for Akita Supermodem.
    Uses X25519 for ECDH key exchange and ChaCha20-Poly1305 for AEAD.
    """

    def __init__(self, encryption_enabled: bool = True, pre_shared_key: Optional[bytes] = None):
        self.encryption_enabled = encryption_enabled
        self.pre_shared_key = pre_shared_key
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

    def derive_shared_key(self, peer_public_key_bytes: bytes, session_id: str = "") -> bool:
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
            local_public_key_bytes = self.get_public_key_bytes()
            transcript_keys = sorted([local_public_key_bytes, peer_public_key_bytes])
            shared_secret = self._private_key.exchange(peer_public_key)
            self._shared_key = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=self.pre_shared_key,
                info=(
                    b"akita-supermodem-v2|"
                    + session_id.encode("utf-8")
                    + b"|"
                    + transcript_keys[0]
                    + transcript_keys[1]
                ),
            ).derive(shared_secret)
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

    def encrypt(self, data: bytes, associated_data: bytes | None = None) -> tuple[bytes, bytes]:
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
        ciphertext = self._chacha.encrypt(nonce, data, associated_data)
        return nonce, ciphertext

    def decrypt(self, nonce: bytes, ciphertext: bytes, associated_data: bytes | None = None) -> bytes:
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
        return self._chacha.decrypt(nonce, ciphertext, associated_data)
