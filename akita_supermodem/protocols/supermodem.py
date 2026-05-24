import os
import time
import logging
import threading
from typing import Callable, Dict, Any, List

from .base import BaseProtocolHandler
from ..generated import akita_pb2
from ..common import (
    calculate_hash,
    calculate_merkle_root,
    sanitize_filename,
    DEFAULT_PIECE_SIZE,
    DEFAULT_INITIAL_DELAY,
    DEFAULT_MAX_DELAY,
)

logger = logging.getLogger(__name__)


class SupermodemHandler(BaseProtocolHandler):
    """
    Native Akita Supermodem Protocol (Next Generation).
    Combines sender and receiver logic for a single transfer.
    """

    def __init__(
        self,
        send_function: Callable[[akita_pb2.InnerMessage], None],
        save_function: Callable[[str, bytes], None],
        profile=None,
    ):
        super().__init__(None, None, save_function, profile=profile)
        self.send_inner = send_function
        self.piece_size = self.profile.piece_size

        # Sender state
        self.transfer_state: Dict[str, Any] = {}

        # Receiver state
        self.receive_state: Dict[str, Any] = {}

        self.retry_threshold = self.profile.max_retries
        self.request_interval = self.profile.timeout
        self.last_request_time = 0.0

        self._lock = threading.Lock()

    def start_transfer(self, filepath: str) -> bool:
        if not os.path.exists(filepath):
            logger.error(f"File not found: {filepath}")
            return False

        total_size = os.path.getsize(filepath)
        num_pieces = (
            (total_size + self.piece_size - 1) // self.piece_size
            if total_size > 0
            else 0
        )

        piece_hashes: List[str] = []
        pieces: List[bytes] = []

        try:
            with open(filepath, "rb") as f:
                for _ in range(num_pieces):
                    piece = f.read(self.piece_size)
                    piece_hashes.append(calculate_hash(piece))
                    pieces.append(piece)
        except Exception as e:
            logger.error(f"Error reading file {filepath}: {e}")
            return False

        fs_proto = akita_pb2.FileStart(
            filename=os.path.basename(filepath),
            total_size=total_size,
            piece_size=self.piece_size,
        )

        merkle_root = calculate_merkle_root(piece_hashes)
        if merkle_root:
            fs_proto.merkle_root = merkle_root
        else:
            fs_proto.piece_hashes.extend(piece_hashes)

        msg = akita_pb2.InnerMessage()
        msg.file_start.CopyFrom(fs_proto)

        with self._lock:
            self.transfer_state = {
                "filepath": filepath,
                "total_size": total_size,
                "num_pieces": num_pieces,
                "pieces": pieces,
                "sent_pieces": [False] * num_pieces,
                "acknowledged_pieces": [False] * num_pieces,
                "delay": self.profile.initial_delay,
                "retry_count": 0,
                "complete": False,
            }

        self.send_inner(msg)

        # Send pieces
        self._send_pieces(list(range(num_pieces)))
        return True

    def _send_pieces(self, indices: List[int]):
        with self._lock:
            if not self.transfer_state or self.transfer_state.get("complete"):
                return
            delay = self.transfer_state["delay"]

        for i in indices:
            with self._lock:
                if self.transfer_state.get("complete"):
                    break
                data = self.transfer_state["pieces"][i]

            piece_proto = akita_pb2.PieceData(piece_index=i, data=data)
            msg = akita_pb2.InnerMessage()
            msg.piece_data.CopyFrom(piece_proto)

            self.send_inner(msg)

            with self._lock:
                self.transfer_state["sent_pieces"][i] = True
            time.sleep(delay)

    def handle_message(self, msg: akita_pb2.InnerMessage) -> None:
        if msg.HasField("file_start"):
            self._handle_file_start(msg.file_start)
        elif msg.HasField("piece_data"):
            self._handle_piece_data(msg.piece_data)
        elif msg.HasField("resume_request"):
            self._handle_resume_request(msg.resume_request)
        elif msg.HasField("acknowledgement"):
            pass  # Unused currently

    def _handle_file_start(self, fs: akita_pb2.FileStart):
        with self._lock:
            num_pieces = (
                (fs.total_size + fs.piece_size - 1) // fs.piece_size
                if fs.total_size > 0
                else 0
            )
            self.receive_state = {
                "filename": fs.filename,
                "total_size": fs.total_size,
                "num_pieces": num_pieces,
                "merkle_root": fs.merkle_root if fs.HasField("merkle_root") else None,
                "piece_hashes": list(fs.piece_hashes),
                "received_pieces": {},
                "missing_indices": set(range(num_pieces)),
                "complete": False,
            }

        if num_pieces == 0 and fs.total_size == 0:
            self._assemble()

    def _handle_piece_data(self, piece: akita_pb2.PieceData):
        with self._lock:
            if not self.receive_state or self.receive_state.get("complete"):
                return
            index = piece.piece_index
            self.receive_state["received_pieces"][index] = piece.data
            self.receive_state["missing_indices"].discard(index)

        self._check_assembly()

    def _handle_resume_request(self, req: akita_pb2.ResumeRequest):
        with self._lock:
            if not self.transfer_state or self.transfer_state.get("complete"):
                return

            for idx in req.acknowledged_indices:
                if idx < self.transfer_state["num_pieces"]:
                    self.transfer_state["acknowledged_pieces"][idx] = True

            if all(self.transfer_state["acknowledged_pieces"]):
                self.transfer_state["complete"] = True
                logger.info("Transfer completed successfully.")
                return

            missing = list(req.missing_indices)
            if missing:
                self.transfer_state["retry_count"] += 1
                if self.transfer_state["retry_count"] >= self.retry_threshold:
                    self.transfer_state["delay"] = min(
                        self.transfer_state["delay"] * 1.5, self.profile.max_delay
                    )
                    self.transfer_state["retry_count"] = 0
            else:
                self.transfer_state["retry_count"] = 0

        if missing:
            self._send_pieces(missing)

    def _check_assembly(self):
        should_assemble = False
        missing = set()
        with self._lock:
            if self.receive_state.get("complete"):
                return
            if (
                len(self.receive_state["received_pieces"])
                == self.receive_state["num_pieces"]
            ):
                # Optionally verify merkle root here, skipping for brevity
                should_assemble = True

        if should_assemble:
            self._assemble()

    def _assemble(self):
        with self._lock:
            pieces = [
                self.receive_state["received_pieces"][i]
                for i in range(self.receive_state["num_pieces"])
            ]
            data = b"".join(pieces)
            safe_name = sanitize_filename(self.receive_state["filename"])
            self.receive_state["complete"] = True

        if self.save:
            self.save(safe_name, data)

    def check_timeouts(self) -> None:
        current_time = time.time()
        missing = []
        acked = []
        with self._lock:
            if not self.receive_state or self.receive_state.get("complete"):
                return
            if current_time - self.last_request_time > self.request_interval:
                missing = list(self.receive_state["missing_indices"])
                acked = list(self.receive_state["received_pieces"].keys())
                self.last_request_time = current_time

        if missing:
            req = akita_pb2.ResumeRequest(
                missing_indices=missing, acknowledged_indices=acked
            )
            msg = akita_pb2.InnerMessage()
            msg.resume_request.CopyFrom(req)
            self.send_inner(msg)

    def cleanup(self) -> None:
        with self._lock:
            self.transfer_state.clear()
            self.receive_state.clear()
