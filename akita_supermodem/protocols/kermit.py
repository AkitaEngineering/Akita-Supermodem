import os
import logging
from typing import Callable
from .base import BaseProtocolHandler
from ..generated import akita_pb2

logger = logging.getLogger(__name__)


class KermitHandler(BaseProtocolHandler):
    """
    Kermit Protocol Implementation over Akita E2EE Tunnel.
    Minimal implementation supporting standard Kermit packets.
    """

    def __init__(
        self,
        send_function: Callable[[akita_pb2.InnerMessage], None],
        save_function: Callable[[str, bytes], None],
        profile=None,
    ):
        super().__init__(None, None, save_function, profile=profile)
        self.send_inner = send_function
        self.state = "INIT"
        self.filepath = None
        self.filename = "kermit_received.bin"
        self.data_buffer = b""
        self.seq = 0

    def _send_raw(self, data: bytes):
        msg = akita_pb2.InnerMessage(raw_data=data)
        self.send_inner(msg)

    def _to_char(self, val: int) -> bytes:
        return bytes([(val + 32) & 0xFF])

    def _calc_checksum(self, packet: bytes) -> bytes:
        s = sum(packet)
        return self._to_char(((s + ((s & 0xC0) >> 6)) & 0x3F))

    def _build_packet(self, p_type: bytes, data: bytes) -> bytes:
        # MARK + LEN + SEQ + TYPE + DATA + CHECK + CR
        # Simplified Kermit packet formatting
        packet_len = len(data) + 3  # seq, type, check
        body = self._to_char(packet_len) + self._to_char(self.seq) + p_type + data
        check = self._calc_checksum(body)
        return b"\x01" + body + check + b"\x0d"

    def start_transfer(self, filepath: str) -> bool:
        if not os.path.exists(filepath):
            return False

        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        with open(filepath, "rb") as f:
            self.data_buffer = f.read()

        self.state = "WAIT_SEND_INIT_ACK"
        # Send Send-Init (S)
        self._send_raw(self._build_packet(b"S", b""))
        return True

    def _send_file_header(self):
        self.seq = (self.seq + 1) % 64
        self._send_raw(self._build_packet(b"F", self.filename.encode("utf-8")))
        self.state = "WAIT_FILE_ACK"

    def _send_data(self):
        if not self.data_buffer:
            self.seq = (self.seq + 1) % 64
            self._send_raw(self._build_packet(b"Z", b""))  # EOF
            self.state = "WAIT_EOF_ACK"
            return

        chunk = self.data_buffer[:90]  # Max Kermit data length roughly
        self.data_buffer = self.data_buffer[90:]

        # In a full Kermit, we must encode control chars using prefix.
        # Over Meshtastic E2EE we can just pass raw data, but for strict compliance:
        encoded = chunk.replace(b"\x01", b"#A").replace(b"\x0d", b"#M")

        self.seq = (self.seq + 1) % 64
        self._send_raw(self._build_packet(b"D", encoded))
        self.state = "WAIT_DATA_ACK"

    def handle_message(self, msg: akita_pb2.InnerMessage) -> None:
        if not msg.HasField("raw_data"):
            return

        data = msg.raw_data
        if len(data) < 5 or data[0:1] != b"\x01":
            return

        p_type = data[3:4]

        if p_type == b"Y":  # ACK
            if self.state == "WAIT_SEND_INIT_ACK":
                self._send_file_header()
            elif self.state == "WAIT_FILE_ACK":
                self._send_data()
            elif self.state == "WAIT_DATA_ACK":
                self._send_data()
            elif self.state == "WAIT_EOF_ACK":
                self.seq = (self.seq + 1) % 64
                self._send_raw(self._build_packet(b"B", b""))  # EOT (Break)
                self.state = "WAIT_EOT_ACK"
            elif self.state == "WAIT_EOT_ACK":
                self.state = "COMPLETE"
                logger.info("Kermit Transfer Complete")

        elif p_type == b"N":  # NAK
            pass  # Resend last packet in full implementation

        # Receiver logic omitted for brevity, follows inverse pattern.

    def check_timeouts(self) -> None:
        pass

    def cleanup(self) -> None:
        pass
