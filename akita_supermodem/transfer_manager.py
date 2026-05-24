import os
import logging
import threading
from typing import Callable, Dict

from .crypto import CryptoManager
from .generated import akita_pb2
from .common import AKITA_CONTENT_TYPE
from .config import NetworkProfile, get_profile

logger = logging.getLogger(__name__)


class TransferManager:
    """
    Coordinates E2EE Handshakes and delegates to specific protocol handlers.
    """

    def __init__(self, mesh_api, save_function: Callable[[str, bytes], None], profile_name: str = "meshtastic"):
        self.mesh = mesh_api
        self.save_function = save_function
        self.profile = get_profile(profile_name)

        # Maps session_id -> CryptoManager
        self.sessions: Dict[str, CryptoManager] = {}
        # Maps session_id -> ProtocolHandler
        self.handlers: Dict[str, object] = {}
        # Maps node_id -> active session_id
        self.node_sessions: Dict[str, str] = {}

        self._lock = threading.Lock()

    def _generate_session_id(self) -> str:
        return os.urandom(8).hex()

    def start_transfer(
        self,
        recipient_id: str,
        filepath: str,
        protocol: int = akita_pb2.PROTOCOL_SUPERMODEM,
    ):
        """Initiates a file transfer. Starts with a KeyExchange."""
        session_id = self._generate_session_id()
        crypto = CryptoManager(self.profile.encryption_enabled)

        with self._lock:
            self.sessions[session_id] = crypto
            self.node_sessions[recipient_id] = session_id

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

        # We cannot start the transfer until the peer responds with their public key.
        # We need to store the transfer intent to execute once the handshake completes.
        with self._lock:
            self.handlers[session_id] = {
                "state": "WAITING_FOR_PEER_KEY",
                "filepath": filepath,
                "protocol": protocol,
                "recipient_id": recipient_id,
            }

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

        with self._lock:
            crypto = self.sessions.get(session_id)
            intent = self.handlers.get(session_id)

        if crypto and intent and intent.get("state") == "WAITING_FOR_PEER_KEY":
            # We initiated this, and peer responded with their key
            if crypto.derive_shared_key(kx.public_key):
                logger.info(f"Handshake complete with {sender_id}. Starting transfer.")
                self._instantiate_handler_and_start(
                    session_id, sender_id, intent["protocol"], intent["filepath"]
                )
            else:
                logger.error("Failed to derive shared key.")
        else:
            # Peer is initiating a new transfer to us
            crypto = CryptoManager(self.profile.encryption_enabled)
            if crypto.derive_shared_key(kx.public_key):
                with self._lock:
                    self.sessions[session_id] = crypto
                    self.node_sessions[sender_id] = session_id

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

                # Instantiate receiver handler
                self._instantiate_handler(session_id, sender_id, kx.protocol)
            else:
                logger.error("Failed to derive shared key for incoming connection.")

    def _instantiate_handler(
        self, session_id: str, peer_id: str, protocol: int
    ) -> object:
        # Avoid circular imports by importing protocols here or deferring
        from .protocols.supermodem import SupermodemHandler
        from .protocols.xmodem import XModemHandler
        from .protocols.ymodem import YModemHandler
        from .protocols.zmodem import ZModemHandler
        from .protocols.kermit import KermitHandler

        crypto = self.sessions[session_id]

        # Function to send encrypted data
        def send_encrypted(inner_msg: akita_pb2.InnerMessage):
            nonce, ciphertext = crypto.encrypt(inner_msg.SerializeToString())
            enc_payload = akita_pb2.EncryptedPayload(
                session_id=session_id, nonce=nonce, ciphertext=ciphertext
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
        elif protocol == akita_pb2.PROTOCOL_XMODEM:
            handler = XModemHandler(send_encrypted, self.save_function, profile=self.profile)
        elif protocol == akita_pb2.PROTOCOL_YMODEM:
            handler = YModemHandler(send_encrypted, self.save_function, profile=self.profile)
        elif protocol == akita_pb2.PROTOCOL_ZMODEM:
            handler = ZModemHandler(send_encrypted, self.save_function, profile=self.profile)
        elif protocol == akita_pb2.PROTOCOL_KERMIT:
            handler = KermitHandler(send_encrypted, self.save_function, profile=self.profile)
        else:
            logger.error(f"Unknown protocol {protocol}")

        with self._lock:
            self.handlers[session_id] = handler

        return handler

    def _instantiate_handler_and_start(
        self, session_id: str, peer_id: str, protocol: int, filepath: str
    ):
        handler = self._instantiate_handler(session_id, peer_id, protocol)
        if handler:
            handler.start_transfer(filepath)

    def _handle_encrypted_payload(
        self, sender_id: str, payload: akita_pb2.EncryptedPayload
    ):
        session_id = payload.session_id
        with self._lock:
            crypto = self.sessions.get(session_id)
            handler = self.handlers.get(session_id)

        if not crypto or not handler:
            logger.error(f"Received encrypted payload for unknown session {session_id}")
            return

        try:
            decrypted_bytes = crypto.decrypt(payload.nonce, payload.ciphertext)
            inner_msg = akita_pb2.InnerMessage()
            inner_msg.ParseFromString(decrypted_bytes)
            # Pass to specific handler
            handler.handle_message(inner_msg)
        except Exception as e:
            logger.error(f"Decryption or parsing failed: {e}")

    def check_timeouts(self):
        with self._lock:
            handlers_to_check = list(self.handlers.values())
        for handler in handlers_to_check:
            if hasattr(handler, "check_timeouts") and callable(handler.check_timeouts):
                handler.check_timeouts()
