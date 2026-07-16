from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def generate_keypair() -> tuple[bytes, bytes]:
    """Generates an Ed25519 signing keypair as raw private/public bytes."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_bytes, public_bytes


def sign_bytes(private_key_bytes: bytes, data: bytes) -> bytes:
    """Signs bytes with a raw Ed25519 private key."""
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    return private_key.sign(data)


def verify_bytes(public_key_bytes: bytes, data: bytes, signature: bytes) -> bool:
    """Returns True when signature is valid for data and public key."""
    public_key = ed25519.Ed25519PublicKey.from_public_bytes(public_key_bytes)
    try:
        public_key.verify(signature, data)
        return True
    except InvalidSignature:
        return False


def sign_file(private_key_bytes: bytes, filepath: str | Path) -> bytes:
    """Signs a file's current bytes with a raw Ed25519 private key."""
    return sign_bytes(private_key_bytes, Path(filepath).read_bytes())


def verify_file(public_key_bytes: bytes, filepath: str | Path, signature: bytes) -> bool:
    """Returns True when signature is valid for a file's current bytes."""
    return verify_bytes(public_key_bytes, Path(filepath).read_bytes(), signature)
