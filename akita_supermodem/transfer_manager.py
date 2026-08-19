import logging
import os
import threading
import time
from typing import Any, Callable, Dict, Optional

from pathlib import Path

from .checkpoint import SessionCheckpointStore
from .common import AKITA_CONTENT_TYPE, MIN_PSK_BYTES, REPLAY_WINDOW, ReplayGuard
from .config import get_profile
from .crypto import CryptoManager
from .generated import akita_pb2

logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOLS = {akita_pb2.PROTOCOL_SUPERMODEM}


class TransferManager:
    """
    Coordinates authenticated E2EE handshakes and delegates to protocol handlers.
    """

    def __init__(
        self,
        mesh_api,
        save_function: Callable[[str, bytes], None],
        profile_name: str = "meshtastic",
        save_path_function: Optional[Callable[[str, str], None]] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        checkpoint_dir: Optional[str] = None,
    ):
        self.mesh = mesh_api
        self.save_function = save_function
        self.save_path_function = save_path_function
        self.event_callback = event_callback
        self.profile = get_profile(profile_name)
        self.pre_shared_key = self._load_pre_shared_key()
        if self.profile.encryption_enabled and not self.pre_shared_key:
            raise ValueError(
                f"Profile '{self.profile.name}' requires AKITA_SUPERMODEM_PSK "
                f"({MIN_PSK_BYTES}+ byte high-entropy secret) for encrypted transfers."
            )
        if not self.profile.encryption_enabled:
            raise ValueError(
                f"Profile '{self.profile.name}' must keep encryption enabled."
            )

        self.sessions: Dict[str, CryptoManager] = {}
        self.handlers: Dict[str, object] = {}
        self.node_sessions: Dict[str, str] = {}
        self.session_peers: Dict[str, str] = {}
        self.session_roles: Dict[str, str] = {}
        self.send_sequences: Dict[str, int] = {}
        self.received_sequences: Dict[str, ReplayGuard] = {}
        self.session_errors: Dict[str, str] = {}
        self.handshake_started: Dict[str, float] = {}
        self.handshake_attempts: Dict[str, int] = {}
        self.checkpoint_store: Optional[SessionCheckpointStore] = None
        if self.pre_shared_key:
            root = checkpoint_dir or os.environ.get("AKITA_CHECKPOINT_DIR") or str(
                Path(os.environ.get("AKITA_CONFIG_DIR", Path.home() / ".config" / "akita_supermodem"))
                / "checkpoints"
            )
            self.checkpoint_store = SessionCheckpointStore(root, self.pre_shared_key)

        self._lock = threading.RLock()

    def _generate_session_id(self) -> str:
        return os.urandom(8).hex()

    def _load_pre_shared_key(self) -> Optional[bytes]:
        raw = os.environ.get("AKITA_SUPERMODEM_PSK", "").strip()
        if not raw:
            return None
        key = raw.encode("utf-8")
        if len(key) < MIN_PSK_BYTES:
            raise ValueError(
                f"AKITA_SUPERMODEM_PSK must be at least {MIN_PSK_BYTES} bytes. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return key

    def start_transfer(
        self,
        recipient_id: str,
        filepath: str,
        protocol: int = akita_pb2.PROTOCOL_SUPERMODEM,
    ):
        """Initiates a file transfer. Starts with a KeyExchange."""
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError("Only the Supermodem protocol is production-supported in this release.")
        self._validate_profile_mtu()

        session_id = self._generate_session_id()
        crypto = CryptoManager(self.profile.encryption_enabled, self.pre_shared_key)

        with self._lock:
            self.sessions[session_id] = crypto
            self.node_sessions[recipient_id] = session_id
            self.session_peers[session_id] = recipient_id
            self.session_roles[session_id] = "initiator"
            self.send_sequences[session_id] = 0
            self.received_sequences[session_id] = ReplayGuard(REPLAY_WINDOW)
            self.handshake_started[session_id] = time.time()
            self.handshake_attempts[session_id] = 1
            self.handlers[session_id] = {
                "state": "WAITING_FOR_PEER_KEY",
                "filepath": filepath,
                "protocol": protocol,
                "recipient_id": recipient_id,
            }

        logger.info("Initiating Key Exchange with %s (Session %s)", recipient_id, session_id)
        self._emit_event(
            "handshake_started",
            session_id=session_id,
            peer=recipient_id,
            protocol=protocol,
        )
        self._send_key_exchange(recipient_id, session_id, protocol, crypto)
        return session_id

    def handle_incoming_message(
        self, sender_id: str, payload: bytes, is_broadcast: bool = False
    ):
        try:
            msg = akita_pb2.AkitaMessage()
            msg.ParseFromString(payload)
        except Exception as e:
            logger.error("Failed to parse incoming AkitaMessage: %s", e)
            return

        if msg.HasField("key_exchange"):
            self._handle_key_exchange(sender_id, msg.key_exchange)
        elif msg.HasField("encrypted_payload"):
            self._handle_encrypted_payload(sender_id, msg.encrypted_payload)
        else:
            logger.warning(
                "Received unencrypted message type from %s. Ignoring for E2EE enforcement.",
                sender_id,
            )

    def _send_key_exchange(
        self, destination_id: str, session_id: str, protocol: int, crypto: CryptoManager
    ) -> None:
        kx = akita_pb2.KeyExchange(
            public_key=crypto.get_public_key_bytes(),
            session_id=session_id,
            protocol=protocol,
        )
        msg = akita_pb2.AkitaMessage()
        msg.key_exchange.CopyFrom(kx)
        self.mesh.sendData(
            destinationId=destination_id,
            payload=msg.SerializeToString(),
            portNum=AKITA_CONTENT_TYPE,
        )

    def _handle_key_exchange(self, sender_id: str, kx: akita_pb2.KeyExchange):
        session_id = kx.session_id
        logger.info("Received Key Exchange from %s (Session %s)", sender_id, session_id)
        if kx.protocol not in SUPPORTED_PROTOCOLS:
            logger.error("Rejecting unsupported protocol %s from %s.", kx.protocol, sender_id)
            return

        with self._lock:
            crypto = self.sessions.get(session_id)
            intent = self.handlers.get(session_id)
            role = self.session_roles.get(session_id)

        if isinstance(intent, dict) and intent.get("state") == "WAITING_FOR_PEER_KEY":
            if crypto.derive_shared_key(kx.public_key, session_id):
                logger.info("Handshake complete with %s. Starting transfer.", sender_id)
                self._emit_event("handshake_complete", session_id=session_id, peer=sender_id)
                self._instantiate_handler_and_start(
                    session_id, sender_id, intent["protocol"], intent["filepath"]
                )
            else:
                with self._lock:
                    self.session_errors[session_id] = "key_derivation_failed"
                self._emit_event(
                    "transfer_failed",
                    session_id=session_id,
                    peer=sender_id,
                    error="key_derivation_failed",
                )
                logger.error("Failed to derive shared key.")
            return

        if crypto is not None:
            # Duplicate or retried handshake for an existing session.
            if role == "responder":
                logger.info("Replaying key-exchange reply for session %s", session_id)
                self._send_key_exchange(sender_id, session_id, kx.protocol, crypto)
            else:
                logger.info("Ignoring duplicate key exchange for session %s", session_id)
            return

        crypto = CryptoManager(self.profile.encryption_enabled, self.pre_shared_key)
        if crypto.derive_shared_key(kx.public_key, session_id):
            with self._lock:
                self.sessions[session_id] = crypto
                self.node_sessions[sender_id] = session_id
                self.session_peers[session_id] = sender_id
                self.session_roles[session_id] = "responder"
                self.send_sequences[session_id] = 0
                self.received_sequences[session_id] = ReplayGuard(REPLAY_WINDOW)

            self._instantiate_handler(session_id, sender_id, kx.protocol)
            self._emit_event("handshake_complete", session_id=session_id, peer=sender_id)
            self._send_key_exchange(sender_id, session_id, kx.protocol, crypto)
        else:
            with self._lock:
                self.session_errors[session_id] = "key_derivation_failed"
            self._emit_event(
                "transfer_failed",
                session_id=session_id,
                peer=sender_id,
                error="key_derivation_failed",
            )
            logger.error("Failed to derive shared key for incoming connection.")

    def _instantiate_handler(
        self, session_id: str, peer_id: str, protocol: int
    ) -> object:
        from .protocols.supermodem import SupermodemHandler

        crypto = self.sessions[session_id]

        def send_encrypted(inner_msg: akita_pb2.InnerMessage):
            with self._lock:
                sequence = self.send_sequences.get(session_id, 0)
                self.send_sequences[session_id] = sequence + 1
            associated_data = self._associated_data(session_id, sequence)
            nonce, ciphertext = crypto.encrypt(inner_msg.SerializeToString(), associated_data)
            enc_payload = akita_pb2.EncryptedPayload(
                session_id=session_id,
                nonce=nonce,
                ciphertext=ciphertext,
                sequence=sequence,
            )
            out_msg = akita_pb2.AkitaMessage()
            out_msg.encrypted_payload.CopyFrom(enc_payload)
            self.mesh.sendData(
                destinationId=peer_id,
                payload=out_msg.SerializeToString(),
                portNum=AKITA_CONTENT_TYPE,
            )
            self._emit_event(
                "encrypted_payload_sent",
                session_id=session_id,
                peer=peer_id,
                sequence=sequence,
                payload_bytes=len(out_msg.SerializeToString()),
            )

        handler = None
        if protocol == akita_pb2.PROTOCOL_SUPERMODEM:
            handler = SupermodemHandler(
                send_encrypted,
                self.save_function,
                profile=self.profile,
                save_path_function=self.save_path_function,
                event_callback=lambda event: self._on_protocol_event(
                    session_id, peer_id, event
                ),
                session_id=session_id,
                checkpoint_dir=(
                    str(self.checkpoint_store.path_for(session_id))
                    if self.checkpoint_store
                    else None
                ),
            )
        else:
            logger.error("Unsupported protocol %s", protocol)

        with self._lock:
            self.handlers[session_id] = handler

        return handler

    def _instantiate_handler_and_start(
        self, session_id: str, peer_id: str, protocol: int, filepath: str
    ):
        handler = self._instantiate_handler(session_id, peer_id, protocol)
        if handler:
            if not handler.start_transfer(filepath):
                with self._lock:
                    self.session_errors[session_id] = handler.last_error or "transfer_start_failed"
                self._emit_event(
                    "transfer_failed",
                    session_id=session_id,
                    peer=peer_id,
                    error=self.session_errors[session_id],
                )

    def _handle_encrypted_payload(
        self, sender_id: str, payload: akita_pb2.EncryptedPayload
    ):
        session_id = payload.session_id
        with self._lock:
            crypto = self.sessions.get(session_id)
            handler = self.handlers.get(session_id)
            replay_guard = self.received_sequences.setdefault(
                session_id, ReplayGuard(REPLAY_WINDOW)
            )

        if not crypto or not hasattr(handler, "handle_message"):
            if self._restore_session(sender_id, session_id):
                with self._lock:
                    crypto = self.sessions.get(session_id)
                    handler = self.handlers.get(session_id)
                    replay_guard = self.received_sequences.setdefault(
                        session_id, ReplayGuard(REPLAY_WINDOW)
                    )
            else:
                logger.error("Received encrypted payload for unknown session %s", session_id)
                return

        if not crypto or not hasattr(handler, "handle_message"):
            logger.error("Received encrypted payload for unrestorable session %s", session_id)
            return

        if not replay_guard.accept(payload.sequence):
            logger.warning(
                "Rejected replayed or stale encrypted payload for session %s sequence %s",
                session_id,
                payload.sequence,
            )
            self._emit_event(
                "replay_rejected",
                session_id=session_id,
                peer=sender_id,
                sequence=payload.sequence,
            )
            return

        try:
            associated_data = self._associated_data(session_id, payload.sequence)
            decrypted_bytes = crypto.decrypt(payload.nonce, payload.ciphertext, associated_data)
            inner_msg = akita_pb2.InnerMessage()
            inner_msg.ParseFromString(decrypted_bytes)
            handler.handle_message(inner_msg)
        except Exception as e:
            # Bit errors on a lossy radio look like decrypt failures. Drop the
            # packet and keep the session alive so selective-NAK can recover.
            self._emit_event(
                "decrypt_failed",
                session_id=session_id,
                peer=sender_id,
                sequence=payload.sequence,
                error=str(e),
            )
            logger.warning("Dropping damaged encrypted payload for session %s: %s", session_id, e)
            self._persist_session(session_id)

    def check_timeouts(self):
        now = time.time()
        handshake_retries = []
        failed_handshakes = []
        with self._lock:
            handlers_to_check = list(self.handlers.items())
            for session_id, handler in handlers_to_check:
                if not (isinstance(handler, dict) and handler.get("state") == "WAITING_FOR_PEER_KEY"):
                    continue
                started = self.handshake_started.get(session_id, now)
                attempts = self.handshake_attempts.get(session_id, 1)
                if now - started < self.profile.timeout:
                    continue
                if attempts < self.profile.handshake_retries:
                    handshake_retries.append((session_id, handler, attempts))
                    self.handshake_started[session_id] = now
                    self.handshake_attempts[session_id] = attempts + 1
                else:
                    failed_handshakes.append((session_id, handler))
                    self.session_errors[session_id] = "handshake_timeout"

        for session_id, handler, attempts in handshake_retries:
            crypto = self.sessions.get(session_id)
            if not crypto:
                continue
            logger.warning(
                "Retrying key exchange for session %s (attempt %s)",
                session_id,
                attempts + 1,
            )
            self._send_key_exchange(
                handler["recipient_id"], session_id, handler["protocol"], crypto
            )

        for session_id, handler in failed_handshakes:
            self._emit_event(
                "transfer_failed",
                session_id=session_id,
                peer=handler.get("recipient_id"),
                error="handshake_timeout",
            )

        for _session_id, handler in handlers_to_check:
            if hasattr(handler, "check_timeouts") and callable(handler.check_timeouts):
                handler.check_timeouts()

    def get_status(self) -> list[Dict[str, Any]]:
        with self._lock:
            items = list(self.handlers.items())
            peers = dict(self.session_peers)
            errors = dict(self.session_errors)

        statuses: list[Dict[str, Any]] = []
        for session_id, handler in items:
            peer = peers.get(session_id)
            if isinstance(handler, dict):
                error = errors.get(session_id)
                statuses.append(
                    {
                        "session_id": session_id,
                        "peer": peer or handler.get("recipient_id"),
                        "direction": "send",
                        "filename": os.path.basename(handler.get("filepath", "")),
                        "state": "failed" if error else handler.get("state", "pending"),
                        "complete": False,
                        "failed": bool(error),
                        "error": error,
                        "authenticated": bool(self.pre_shared_key),
                        "encrypted": self.profile.encryption_enabled,
                    }
                )
            elif hasattr(handler, "get_status") and callable(handler.get_status):
                status = handler.get_status()
                error = errors.get(session_id)
                if error:
                    status["state"] = "failed"
                    status["failed"] = True
                    status["error"] = error
                status["session_id"] = session_id
                status["peer"] = peer
                status["authenticated"] = bool(self.pre_shared_key)
                status["encrypted"] = self.profile.encryption_enabled
                statuses.append(status)
        return statuses

    def wait(self, timeout: float = 30.0) -> list[Dict[str, Any]]:
        """Blocks until every session is complete or failed, or timeout expires."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.check_timeouts()
            statuses = self.get_status()
            if statuses and all(state.get("complete") or state.get("failed") for state in statuses):
                return statuses
            time.sleep(0.02)
        return self.get_status()

    def close(self) -> None:
        with self._lock:
            handlers = list(self.handlers.values())
        for handler in handlers:
            if hasattr(handler, "cleanup") and callable(handler.cleanup):
                try:
                    handler.cleanup()
                except Exception as e:
                    logger.warning("Handler cleanup failed: %s", e)

    def _on_protocol_event(self, session_id: str, peer_id: str, event: Dict[str, Any]) -> None:
        name = event.get("event", "protocol_event")
        self._emit_event(
            name,
            session_id=session_id,
            peer=peer_id,
            **{key: value for key, value in event.items() if key != "event"},
        )
        if name in {"piece_received", "transfer_started", "piece_sent"}:
            self._persist_session(session_id)
        if name in {"transfer_complete", "transfer_failed"}:
            self._forget_checkpoint(session_id)

    def _persist_session(self, session_id: str) -> None:
        if not self.checkpoint_store:
            return
        with self._lock:
            crypto = self.sessions.get(session_id)
            handler = self.handlers.get(session_id)
            role = self.session_roles.get(session_id)
            peer = self.session_peers.get(session_id)
            send_sequence = self.send_sequences.get(session_id, 0)
            replay = self.received_sequences.get(session_id)
        if role != "responder" or not crypto or not hasattr(handler, "export_receive_state"):
            return
        receive_state = handler.export_receive_state()
        shared_key = crypto.export_shared_key()
        if not receive_state or not shared_key:
            return
        payload = {
            "session_id": session_id,
            "peer": peer,
            "role": role,
            "protocol": akita_pb2.PROTOCOL_SUPERMODEM,
            "send_sequence": send_sequence,
            "replay": replay.snapshot() if replay else {},
            "shared_key": shared_key.hex(),
            "receive": receive_state,
        }
        try:
            self.checkpoint_store.save(session_id, payload)
        except OSError as e:
            logger.warning("Failed to persist session %s: %s", session_id, e)

    def _restore_session(self, sender_id: str, session_id: str) -> bool:
        if not self.checkpoint_store:
            return False
        payload = self.checkpoint_store.load(session_id)
        if not payload or payload.get("role") != "responder":
            return False
        try:
            shared_key = bytes.fromhex(payload["shared_key"])
        except (KeyError, ValueError):
            return False
        crypto = CryptoManager.from_shared_key(
            shared_key, self.profile.encryption_enabled, self.pre_shared_key
        )
        replay = ReplayGuard(REPLAY_WINDOW)
        replay.restore(payload.get("replay"))
        with self._lock:
            self.sessions[session_id] = crypto
            self.node_sessions[sender_id] = session_id
            self.session_peers[session_id] = sender_id
            self.session_roles[session_id] = "responder"
            self.send_sequences[session_id] = int(payload.get("send_sequence", 0))
            self.received_sequences[session_id] = replay
        handler = self._instantiate_handler(
            session_id, sender_id, int(payload.get("protocol", akita_pb2.PROTOCOL_SUPERMODEM))
        )
        if not handler or not handler.restore_receive_state(payload.get("receive") or {}):
            return False
        logger.info("Restored receive session %s from checkpoint.", session_id)
        self._emit_event("session_restored", session_id=session_id, peer=sender_id)
        if hasattr(handler, "_send_resume_request"):
            handler._send_resume_request()
        return True

    def _forget_checkpoint(self, session_id: str) -> None:
        if self.checkpoint_store:
            self.checkpoint_store.delete(session_id)

    def _associated_data(self, session_id: str, sequence: int) -> bytes:
        return b"akita-supermodem-v2|" + session_id.encode("utf-8") + b"|" + sequence.to_bytes(8, "big")

    def _validate_profile_mtu(self) -> None:
        estimated_piece_payload = self.profile.piece_size + 96
        if estimated_piece_payload > self.profile.max_payload_bytes:
            raise ValueError(
                f"Profile '{self.profile.name}' piece_size={self.profile.piece_size} exceeds "
                f"max_payload_bytes={self.profile.max_payload_bytes} after protocol overhead."
            )

    def _emit_event(self, event: str, **fields: Any) -> None:
        if not self.event_callback:
            return
        payload = {"event": event, **fields}
        try:
            self.event_callback(payload)
        except Exception as e:
            logger.warning("Event callback failed for %s: %s", event, e)
