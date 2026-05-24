import os
import logging
from typing import Callable
from .base import BaseProtocolHandler
from ..generated import akita_pb2

logger = logging.getLogger(__name__)

# YMODEM Constants
SOH = b"\x01"
STX = b"\x02"
EOT = b"\x04"
ACK = b"\x06"
NAK = b"\x15"
CAN = b"\x18"
EOF = b"\x1a"
C = b"C"


class YModemHandler(BaseProtocolHandler):
    """
    YMODEM Protocol Implementation over Akita E2EE Tunnel.
    Supports 1024-byte blocks and CRC16.
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
        self.filename = "ymodem_received.bin"
        self.data_buffer = b""
        self.block_number = 0

    def _send_raw(self, data: bytes):
        msg = akita_pb2.InnerMessage(raw_data=data)
        self.send_inner(msg)

    def start_transfer(self, filepath: str) -> bool:
        if not os.path.exists(filepath):
            return False

        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        with open(filepath, "rb") as f:
            self.data_buffer = f.read()

        self.state = "WAIT_C"
        return True

    def _calc_crc16(self, data: bytes) -> bytes:
        crc = 0
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ 0x1021
                else:
                    crc <<= 1
                crc &= 0xFFFF
        return bytes([crc >> 8, crc & 0xFF])

    def _send_block(self):
        if self.block_number == 0:
            # Block 0 contains filename and size
            payload = (
                self.filename.encode("utf-8")
                + b"\x00"
                + str(len(self.data_buffer)).encode("utf-8")
                + b"\x00"
            )
            chunk = payload.ljust(128, b"\x00")
            header = SOH + bytes([0, 255])
        else:
            if not self.data_buffer:
                self._send_raw(EOT)
                self.state = "WAIT_EOT_ACK"
                return

            chunk = self.data_buffer[:1024]
            # Pad with EOF if less than 1024
            if len(chunk) < 1024:
                chunk += EOF * (1024 - len(chunk))

            header = STX + bytes(
                [self.block_number % 256, (255 - (self.block_number % 256))]
            )

        crc = self._calc_crc16(chunk)
        packet = header + chunk + crc
        self._send_raw(packet)
        self.state = "WAIT_ACK"

    def handle_message(self, msg: akita_pb2.InnerMessage) -> None:
        if not msg.HasField("raw_data"):
            return

        data = msg.raw_data
        if not data:
            return

        if self.state == "WAIT_C":
            if data == C:
                self._send_block()

        elif self.state == "WAIT_ACK":
            if data == ACK:
                if self.block_number > 0:
                    self.data_buffer = self.data_buffer[1024:]
                self.block_number += 1
                # YMODEM waits for 'C' after Block 0 ACK
                if self.block_number == 1:
                    self.state = "WAIT_C2"
                else:
                    self._send_block()
            elif data == NAK:
                self._send_block()
            elif data == CAN:
                self.state = "ABORTED"

        elif self.state == "WAIT_C2":
            if data == C:
                self._send_block()

        elif self.state == "WAIT_EOT_ACK":
            if data == ACK:
                self.state = "WAIT_C_FIN"
            elif data == NAK:
                self._send_raw(EOT)

        elif self.state == "WAIT_C_FIN":
            if data == C:
                # Send empty Block 0 to finish
                chunk = b"\x00" * 128
                header = SOH + bytes([0, 255])
                crc = self._calc_crc16(chunk)
                self._send_raw(header + chunk + crc)
                self.state = "WAIT_FINAL_ACK"

        elif self.state == "WAIT_FINAL_ACK":
            if data == ACK:
                self.state = "COMPLETE"
                logger.info("YMODEM Transfer Complete")

        # Receiver logic
        elif self.state == "INIT":
            self._send_raw(C)
            self.state = "RECEIVING_B0"

        elif self.state in ["RECEIVING_B0", "RECEIVING"]:
            self._handle_incoming_block(data)

    def _handle_incoming_block(self, data: bytes):
        if data == EOT:
            self._send_raw(NAK)
            self.state = "WAIT_SECOND_EOT"
            return

        is_soh = data[0:1] == SOH
        is_stx = data[0:1] == STX

        if not (is_soh or is_stx):
            return

        expected_len = 133 if is_soh else 1029
        if len(data) != expected_len:
            self._send_raw(NAK)
            return

        seq = data[1]
        seq_c = data[2]
        if seq + seq_c != 255:
            self._send_raw(NAK)
            return

        chunk = data[3:-2]
        crc = data[-2:]

        if self._calc_crc16(chunk) != crc:
            self._send_raw(NAK)
            return

        if self.state == "RECEIVING_B0" and seq == 0:
            # Parse filename and size
            if chunk[0] == 0:
                # Empty block 0 = End of session
                self._send_raw(ACK)
                self.state = "COMPLETE"
                return

            parts = chunk.split(b"\x00")
            if parts[0]:
                self.filename = parts[0].decode("utf-8", errors="ignore")
            self._send_raw(ACK)
            self.state = "WAIT_C2_RX"

        elif self.state == "WAIT_C2_RX" or self.state == "RECEIVING":
            if self.state == "WAIT_C2_RX":
                self._send_raw(C)
                self.state = "RECEIVING"
                self.block_number = 1
                return

            if seq == (self.block_number % 256):
                self.data_buffer += chunk
                self.block_number += 1
                self._send_raw(ACK)
            else:
                self._send_raw(NAK)

    def check_timeouts(self) -> None:
        pass

    def cleanup(self) -> None:
        pass
