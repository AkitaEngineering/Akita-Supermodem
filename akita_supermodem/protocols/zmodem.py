import os
import struct
import logging
from typing import Callable
from .base import BaseProtocolHandler
from ..generated import akita_pb2

logger = logging.getLogger(__name__)

# Basic ZMODEM constants
ZPAD = b"*"
ZDLE = b"\x18"
ZBIN = b"A"
ZHEX = b"B"
ZBIN32 = b"C"

# Frame Types
ZRQINIT = 0
ZRINIT = 1
ZSINIT = 2
ZACK = 3
ZFILE = 4
ZSKIP = 5
ZNAK = 6
ZABORT = 7
ZFIN = 8
ZRPOS = 9
ZDATA = 10
ZEOF = 11


class ZModemHandler(BaseProtocolHandler):
    """
    ZMODEM Protocol Implementation over Akita E2EE Tunnel.
    Simplified ZMODEM implementation.
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
        self.filename = "zmodem_received.bin"
        self.data_buffer = b""
        self.position = 0

    def _send_raw(self, data: bytes):
        msg = akita_pb2.InnerMessage(raw_data=data)
        self.send_inner(msg)

    def _calc_crc32(self, data: bytes) -> int:
        import zlib

        return zlib.crc32(data) & 0xFFFFFFFF

    def _create_hex_frame(
        self, frame_type: int, p0: int, p1: int, p2: int, p3: int
    ) -> bytes:
        header = bytes([frame_type, p0, p1, p2, p3])
        crc = self._calc_crc32(header)
        # hex encoding of header and crc
        # ZPAD ZPAD ZDLE ZHEX hex(type) hex(p0) hex(p1) hex(p2) hex(p3) hex(crc1) hex(crc2) hex(crc3) hex(crc4) CR LF XON
        hex_str = header.hex().encode("ascii") + struct.pack("<I", crc).hex().encode(
            "ascii"
        )
        return ZPAD + ZPAD + ZDLE + ZHEX + hex_str + b"\r\n\x11"

    def _create_bin32_frame(self, frame_type: int, pos: int) -> bytes:
        header = struct.pack("<BI", frame_type, pos)
        crc = self._calc_crc32(header)
        return ZPAD + ZDLE + ZBIN32 + header + struct.pack("<I", crc)

    def start_transfer(self, filepath: str) -> bool:
        if not os.path.exists(filepath):
            return False

        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        with open(filepath, "rb") as f:
            self.data_buffer = f.read()

        self.state = "WAIT_ZRINIT"
        # Send ZRQINIT
        self._send_raw(self._create_hex_frame(ZRQINIT, 0, 0, 0, 0))
        return True

    def _send_file_header(self):
        # Send ZFILE frame
        self._send_raw(self._create_hex_frame(ZFILE, 0, 0, 0, 0))
        # Send data block with filename and size
        payload = (
            self.filename.encode("utf-8")
            + b"\x00"
            + str(len(self.data_buffer)).encode("utf-8")
            + b"\x00"
        )
        # ZMODEM subpacket formatting simplified
        crc = struct.pack("<I", self._calc_crc32(payload))
        self._send_raw(payload + ZDLE + b"\x68" + crc)  # ZCRCE (end of frame)
        self.state = "WAIT_ZRPOS"

    def _send_data_packets(self, offset: int):
        self.position = offset
        self._send_raw(self._create_bin32_frame(ZDATA, offset))

        while self.position < len(self.data_buffer):
            chunk = self.data_buffer[self.position : self.position + 1024]
            self.position += len(chunk)

            # ZCRCG (more to come) or ZCRCE (end)
            term = b"\x69" if self.position < len(self.data_buffer) else b"\x68"
            crc = struct.pack("<I", self._calc_crc32(chunk))
            self._send_raw(chunk + ZDLE + term + crc)

        # Send ZEOF
        self._send_raw(self._create_hex_frame(ZEOF, 0, 0, 0, 0))
        self.state = "WAIT_ZEOF_ACK"

    def handle_message(self, msg: akita_pb2.InnerMessage) -> None:
        if not msg.HasField("raw_data"):
            return

        data = msg.raw_data

        # Super simplified parsing, assuming complete frames arrive over E2EE tunnel
        if ZDLE + ZHEX in data:
            idx = data.find(ZDLE + ZHEX)
            hex_data = data[idx + 2 : idx + 2 + 28]
            if len(hex_data) >= 10:
                frame_type = int(hex_data[0:2], 16)

                if self.state == "WAIT_ZRINIT" and frame_type == ZRINIT:
                    self._send_file_header()

                elif self.state == "WAIT_ZRPOS" and frame_type == ZRPOS:
                    # Parse position from hex frame
                    p0 = int(hex_data[2:4], 16)
                    p1 = int(hex_data[4:6], 16)
                    p2 = int(hex_data[6:8], 16)
                    p3 = int(hex_data[8:10], 16)
                    offset = p0 | (p1 << 8) | (p2 << 16) | (p3 << 24)
                    self._send_data_packets(offset)

                elif self.state == "WAIT_ZEOF_ACK" and frame_type == ZRINIT:
                    self._send_raw(self._create_hex_frame(ZFIN, 0, 0, 0, 0))
                    self.state = "WAIT_ZFIN_ACK"

                elif self.state == "WAIT_ZFIN_ACK" and frame_type == ZFIN:
                    self._send_raw(b"OO")  # Over and out
                    self.state = "COMPLETE"
                    logger.info("ZMODEM Transfer Complete")

        # Receiver logic
        elif self.state == "INIT":
            if ZRQINIT in data:  # simplification
                self._send_raw(self._create_hex_frame(ZRINIT, 0, 0, 0, 0))
                self.state = "WAIT_ZFILE"

        # Further strict ZMODEM receiver parsing is complex and omitted for brevity.
        # This skeleton provides the structure needed to satisfy the protocol handler.

    def check_timeouts(self) -> None:
        pass

    def cleanup(self) -> None:
        pass
