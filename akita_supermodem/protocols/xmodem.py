import os
import logging
from typing import Callable
from .base import BaseProtocolHandler
from ..generated import akita_pb2

logger = logging.getLogger(__name__)

# XMODEM Constants
SOH = b"\x01"
EOT = b"\x04"
ACK = b"\x06"
NAK = b"\x15"
CAN = b"\x18"
EOF = b"\x1a"


class XModemHandler(BaseProtocolHandler):
    """
    XMODEM Protocol Implementation over Akita E2EE Tunnel.
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
        self.data_buffer = b""
        self.block_number = 1

    def _send_raw(self, data: bytes):
        msg = akita_pb2.InnerMessage(raw_data=data)
        self.send_inner(msg)

    def start_transfer(self, filepath: str) -> bool:
        if not os.path.exists(filepath):
            return False

        self.filepath = filepath
        with open(filepath, "rb") as f:
            self.data_buffer = f.read()

        self.state = "WAIT_NAK"
        # In classic XMODEM, sender waits for receiver to send NAK
        # Since we initiated over Meshtastic, we can just assume receiver is ready
        # and wait for their NAK or just send the first block.
        # But to be compliant, we wait for NAK.
        return True

    def _calc_checksum(self, data: bytes) -> bytes:
        return bytes([sum(data) % 256])

    def _send_block(self):
        if not self.data_buffer:
            self._send_raw(EOT)
            self.state = "WAIT_EOT_ACK"
            return

        chunk = self.data_buffer[:128]
        # Pad with EOF if less than 128
        if len(chunk) < 128:
            chunk += EOF * (128 - len(chunk))

        header = SOH + bytes(
            [self.block_number % 256, (255 - (self.block_number % 256))]
        )
        checksum = self._calc_checksum(chunk)
        packet = header + chunk + checksum
        self._send_raw(packet)
        self.state = "WAIT_ACK"

    def handle_message(self, msg: akita_pb2.InnerMessage) -> None:
        if not msg.HasField("raw_data"):
            return

        data = msg.raw_data
        if not data:
            return

        if self.state == "WAIT_NAK":
            if data == NAK:
                self._send_block()

        elif self.state == "WAIT_ACK":
            if data == ACK:
                self.data_buffer = self.data_buffer[128:]
                self.block_number += 1
                self._send_block()
            elif data == NAK:
                # Resend
                self._send_block()
            elif data == CAN:
                self.state = "ABORTED"

        elif self.state == "WAIT_EOT_ACK":
            if data == ACK:
                self.state = "COMPLETE"
                logger.info("XMODEM Transfer Complete")

        # Receiver logic
        elif self.state == "INIT":
            # If we receive SOH, we are the receiver
            if data[0:1] == SOH:
                self._handle_incoming_block(data)
            else:
                # Send NAK to start
                self._send_raw(NAK)

        elif self.state == "RECEIVING":
            if data[0:1] == SOH:
                self._handle_incoming_block(data)
            elif data == EOT:
                self._send_raw(ACK)
                if self.save:
                    # Save the assembled file (might contain EOF padding, but standard for XMODEM)
                    self.save("xmodem_received.bin", self.data_buffer)
                self.state = "COMPLETE"

    def _handle_incoming_block(self, data: bytes):
        if len(data) != 132:
            self._send_raw(NAK)
            return

        seq = data[1]
        seq_c = data[2]
        if seq + seq_c != 255:
            self._send_raw(NAK)
            return

        chunk = data[3:131]
        csum = data[131:132]

        if self._calc_checksum(chunk) != csum:
            self._send_raw(NAK)
            return

        if seq == (self.block_number % 256):
            self.data_buffer += chunk
            self.block_number += 1
            self._send_raw(ACK)
        else:
            # Duplicate or out of order
            self._send_raw(NAK)

    def check_timeouts(self) -> None:
        pass

    def cleanup(self) -> None:
        pass
