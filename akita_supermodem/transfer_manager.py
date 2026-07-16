import os
import logging
import threading
from typing import Callable, Dict, Any, Optional

from .crypto import CryptoManager
from .generated import akita_pb2
from .common import AKITA_CONTENT_TYPE
from .config import get_profile

logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOLS = {akita_pb2.PROTOCOL_SUPERMODEM}


class TransferManager:
    """
    Coordinates E2EE Handshakes and delegates to specific protocol handlers.
    """

    def __init__(self, mesh_api, save_function: Callable[[str, bytes], None], profile_name: str = "meshtastic"):
        self.mesh = mesh_api
        self.save_function = save_function
        self.profile = get_profile(profile_name)
        self.pre_shared_key = self._load_pre_shared_key()
        if self.profile.require_authentication and not self.pre_shared_key:
            raise ValueError(
                f"Profile '{self.profile.name}' requires AKITA_SUPERMODEM_PSK for authenticated encryption."
            )
        if self.profile.encryption_enabled and not self.pre_shared_key:
            logger.warning(
                "Encryption is enabled without AKITA_SUPERMODEM_PSK. "
                "Payloads are private, but peer identity is not authenticated."
            )

        # Maps session_id -> CryptoManager
        self.sessions: Dict[str, CryptoManager] = {}
        # Maps session_id -> ProtocolHandler
        self.handlers: Dict[str, object] = {}
        # Maps node_id -> active session_id
        self.node_sessions: Dict[str, str] = {}
        # Maps session_id -> peer node_id
        self.session_peers: Dict[str, str] = {}
        # Maps session_id -> next outbound encrypted message sequence
        self.send_sequences: Dict[str, int] = {}
        # Maps session_id -> received encrypted message sequences for replay rejection
        self.received_sequences: Dict[str, set[int]] = {}
        # Maps session_id -> machine-readable failure reason
        self.session_errors: Dict[str, str] = {}

        self._lock = threading.Lock()

    def _generate_session_id(self) -> str:
        return os.urandom(8).hex()

    def _load_pre_shared_key(self) -> Optional[bytes]:
        raw = os.environ.get("AKITA_SUPERMODEM_PSK", "").strip()
        if not raw:
            return None
        return raw.encode("utf-8")

    def start_transfer(
        self,
        recipient_id: str,
        filepath: str,
        protocol: int = akita_pb2.PROTOCOL_SUPERMODEM,
    ):
        """Initiates a file transfer. Starts with a KeyExchange."""
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError("Only the Supermodem protocol is production-supported in this release.")

        session_id = self._generate_session_id()
        crypto = CryptoManager(self.profile.encryption_enabled, self.pre_shared_key)

        with self._lock:
            self.sessions[session_id] = crypto
            self.node_sessions[recipient_id] = session_id
            self.session_peers[session_id] = recipient_id
            self.send_sequences[session_id] = 0
            self.received_sequences[session_id] = set()
            self.handlers[session_id] = {
                "state": "WAITING_FOR_PEER_KEY",
                "filepath": filepath,
                "protocol": protocol,
                "recipient_id": recipient_id,
            }

        # Send KeyExchange
        kx = akita_pb2.KeyExchange(
            public_key=crypto.get_public_key_bytes(),
            session_id=session_id,
            protocol=protocol,
        )
        msg = akita_pb2.AkitaMessage()
        msg.key_exchange.CopyFrom(kx)

        logger.info(
            f"Initiating Key Exchange with {recipient_id} (Session {session_id})"
        )
        self.mesh.sendData(
            destinationId=recipient_id,
            payload=msg.SerializeToString(),
            portNum=AKITA_CONTENT_TYPE,
        )
        return session_id

    def handle_incoming_message(
        self, sender_id: str, payload: bytes, is_broadcast: bool = False
    ):
        try:
            msg = akita_pb2.AkitaMessage()
            msg.ParseFromString(payload)
        except Exception as e:
            logger.error(f"Failed to parse incoming AkitaMessage: {e}")
            return

        if msg.HasField("key_exchange"):
            self._handle_key_exchange(sender_id, msg.key_exchange)
        elif msg.HasField("encrypted_payload"):
            self._handle_encrypted_payload(sender_id, msg.encrypted_payload)
        else:
            # Fallback for unencrypted messages (if supported)
            logger.warning(
                f"Received unencrypted message type from {sender_id}. Ignoring for E2EE enforcement."
            )

    def _handle_key_exchange(self, sender_id: str, kx: akita_pb2.KeyExchange):
        session_id = kx.session_id
        logger.info(f"Received Key Exchange from {sender_id} (Session {session_id})")
        if kx.protocol not in SUPPORTED_PROTOCOLS:
            logger.error(f"Rejecting unsupported protocol {kx.protocol} from {sender_id}.")
            return

        with self._lock:
            crypto = self.sessions.get(session_id)
            intent = self.handlers.get(session_id)

        if crypto and intent and intent.get("state") == "WAITING_FOR_PEER_KEY":
            # We initiated this, and peer responded with their key
            if crypto.derive_shared_key(kx.public_key, session_id):
                logger.info(f"Handshake complete with {sender_id}. Starting transfer.")
                self._instantiate_handler_and_start(
                    session_id, sender_id, intent["protocol"], intent["filepath"]
                )
            else:
                self.session_errors[session_id] = "key_derivation_failed"
                logger.error("Failed to derive shared key.")
        else:
            # Peer is initiating a new transfer to us
            crypto = CryptoManager(self.profile.encryption_enabled, self.pre_shared_key)
            if crypto.derive_shared_key(kx.public_key, session_id):
                with self._lock:
                    self.sessions[session_id] = crypto
                    self.node_sessions[sender_id] = session_id
                    self.session_peers[session_id] = sender_id
                    self.send_sequences[session_id] = 0
                    self.received_sequences[session_id] = set()

                # Install the receive handler before replying. A fast peer or
                # in-process transport can send encrypted FileStart immediately
                # after receiving our key.
                self._instantiate_handler(session_id, sender_id, kx.protocol)

                # Reply with our public key
                reply_kx = akita_pb2.KeyExchange(
                    public_key=crypto.get_public_key_bytes(),
                    session_id=session_id,
                    protocol=kx.protocol,
                )
                msg = akita_pb2.AkitaMessage()
                msg.key_exchange.CopyFrom(reply_kx)

                self.mesh.sendData(
                    destinationId=sender_id,
                    payload=msg.SerializeToString(),
                    portNum=AKITA_CONTENT_TYPE,
                )
            else:
                self.session_errors[session_id] = "key_derivation_failed"
                logger.error("Failed to derive shared key for incoming connection.")

    def _instantiate_handler(
        self, session_id: str, peer_id: str, protocol: int
    ) -> object:
        from .protocols.supermodem import SupermodemHandler

        crypto = self.sessions[session_id]

        # Function to send encrypted data
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

        handler = None
        if protocol == akita_pb2.PROTOCOL_SUPERMODEM:
            handler = SupermodemHandler(send_encrypted, self.save_function, profile=self.profile)
        else:
            logger.error(f"Unsupported protocol {protocol}")

        with self._lock:
            self.handlers[session_id] = handler

        return handler

    def _instantiate_handler_and_start(
        self, session_id: str, peer_id: str, protocol: int, filepath: str
    ):
        handler = self._instantiate_handler(session_id, peer_id, protocol)
        if handler:
            if not handler.start_transfer(filepath):
                self.session_errors[session_id] = handler.last_error or "transfer_start_failed"

    def _handle_encrypted_payload(
        self, sender_id: str, payload: akita_pb2.EncryptedPayload
    ):
        session_id = payload.session_id
        with self._lock:
            crypto = self.sessions.get(session_id)
            handler = self.handlers.get(session_id)
            received_sequences = self.received_sequences.setdefault(session_id, set())

        if not crypto or not handler:
            logger.error(f"Received encrypted payload for unknown session {session_id}")
            return

        if payload.sequence in received_sequences:
            logger.warning(f"Rejected replayed encrypted payload for session {session_id} sequence {payload.sequence}")
            return

        try:
            associated_data = self._associated_data(session_id, payload.sequence)
            decrypted_bytes = crypto.decrypt(payload.nonce, payload.ciphertext, associated_data)
            inner_msg = akita_pb2.InnerMessage()
            inner_msg.ParseFromString(decrypted_bytes)
            with self._lock:
                self.received_sequences.setdefault(session_id, set()).add(payload.sequence)
            # Pass to specific handler
            handler.handle_message(inner_msg)
        except Exception as e:
            self.session_errors[session_id] = "decrypt_or_parse_failed"
            logger.error(f"Decryption or parsing failed: {e}")

    def check_timeouts(self):
        with self._lock:
            handlers_to_check = list(self.handlers.values())
        for handler in handlers_to_check:
            if hasattr(handler, "check_timeouts") and callable(handler.check_timeouts):
                handler.check_timeouts()

    def get_status(self) -> list[Dict[str, Any]]:
        with self._lock:
            items = list(self.handlers.items())

        statuses: list[Dict[str, Any]] = []
        for session_id, handler in items:
            peer = self.session_peers.get(session_id)
            if isinstance(handler, dict):
                error = self.session_errors.get(session_id)
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
                error = self.session_errors.get(session_id)
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

    def _associated_data(self, session_id: str, sequence: int) -> bytes:
        return b"akita-supermodem-v2|" + session_id.encode("utf-8") + b"|" + sequence.to_bytes(8, "big")
