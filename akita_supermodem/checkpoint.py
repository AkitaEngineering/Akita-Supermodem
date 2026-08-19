import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger(__name__)

CHECKPOINT_INFO = b"akita-checkpoint-v1"


class SessionCheckpointStore:
    """PSK-sealed receive-session checkpoints for process restart resume."""

    def __init__(self, root: str | Path, pre_shared_key: bytes):
        self.root = Path(root)
        self.pre_shared_key = pre_shared_key
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, session_id: str) -> Path:
        return self.root / session_id

    def staging_path(self, session_id: str) -> Path:
        return self.path_for(session_id) / "staging.part"

    def save(self, session_id: str, payload: dict[str, Any]) -> None:
        session_dir = self.path_for(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        blob = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = ChaCha20Poly1305(self._wrap_key(session_id)).encrypt(
            nonce, blob, session_id.encode("utf-8")
        )
        target = session_dir / "session.chk"
        temp = session_dir / ".session.chk.part"
        temp.write_bytes(nonce + ciphertext)
        os.replace(temp, target)

    def load(self, session_id: str) -> Optional[dict[str, Any]]:
        target = self.path_for(session_id) / "session.chk"
        if not target.exists():
            return None
        raw = target.read_bytes()
        if len(raw) < 13:
            logger.warning("Ignoring truncated checkpoint for session %s", session_id)
            return None
        nonce, ciphertext = raw[:12], raw[12:]
        try:
            blob = ChaCha20Poly1305(self._wrap_key(session_id)).decrypt(
                nonce, ciphertext, session_id.encode("utf-8")
            )
            return json.loads(blob.decode("utf-8"))
        except Exception as e:
            logger.error("Failed to open checkpoint for session %s: %s", session_id, e)
            return None

    def delete(self, session_id: str) -> None:
        session_dir = self.path_for(session_id)
        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)

    def _wrap_key(self, session_id: str) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=session_id.encode("utf-8"),
            info=CHECKPOINT_INFO,
        ).derive(self.pre_shared_key)
