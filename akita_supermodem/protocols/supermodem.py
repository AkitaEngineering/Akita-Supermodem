import os
import time
import logging
import threading
import zlib
from typing import Callable, Dict, Any, List

from .base import BaseProtocolHandler
from ..generated import akita_pb2
from ..common import (
    calculate_hash,
    calculate_merkle_root,
    sanitize_filename,
    MAX_FILE_SIZE,
    MAX_PIECE_SIZE,
    MIN_PIECE_SIZE,
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
        self.last_error = None

        self._lock = threading.Lock()

    def start_transfer(self, filepath: str) -> bool:
        if not os.path.exists(filepath):
            logger.error(f"File not found: {filepath}")
            self.last_error = "file_not_found"
            return False
        if not os.path.isfile(filepath):
            logger.error(f"Path is not a file: {filepath}")
            self.last_error = "not_a_file"
            return False

        total_size = os.path.getsize(filepath)
        if total_size > MAX_FILE_SIZE:
            logger.error(f"File is larger than supported maximum: {total_size} > {MAX_FILE_SIZE}")
            self.last_error = "file_too_large"
            return False

        num_pieces = (
            (total_size + self.piece_size - 1) // self.piece_size
            if total_size > 0
            else 0
        )

        piece_hashes: List[str] = []

        try:
            with open(filepath, "rb") as f:
                for _ in range(num_pieces):
                    piece = f.read(self.piece_size)
                    if not piece:
                        break
                    piece_hashes.append(calculate_hash(piece))
        except Exception as e:
            logger.error(f"Error reading file {filepath}: {e}")
            self.last_error = "read_error"
            return False

        if len(piece_hashes) != num_pieces:
            logger.error(
                f"Expected {num_pieces} pieces while hashing '{filepath}', got {len(piece_hashes)}."
            )
            self.last_error = "short_read"
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
                "piece_hashes": piece_hashes,
                "sent_pieces": [False] * num_pieces,
                "acknowledged_pieces": [False] * num_pieces,
                "delay": self.profile.initial_delay,
                "retry_count": 0,
                "complete": False,
                "failed": False,
                "compressed_pieces": 0,
                "wire_data_bytes": 0,
                "plain_data_bytes": 0,
            }

        self.send_inner(msg)

        # Send pieces
        self._send_pieces(list(range(num_pieces)))
        return True

    def _read_piece(self, index: int) -> bytes | None:
        with self._lock:
            if not self.transfer_state:
                return None
            filepath = self.transfer_state["filepath"]
            num_pieces = self.transfer_state["num_pieces"]
            total_size = self.transfer_state["total_size"]

        if not (0 <= index < num_pieces):
            logger.warning(f"Requested invalid piece index {index}.")
            return None

        offset = index * self.piece_size
        length = min(self.piece_size, total_size - offset)
        try:
            with open(filepath, "rb") as f:
                f.seek(offset)
                data = f.read(length)
        except OSError as e:
            logger.error(f"Failed to read piece {index} from '{filepath}': {e}")
            return None

        if len(data) != length:
            logger.error(f"Short read for piece {index}: expected {length}, got {len(data)}.")
            return None
        return data

    def _send_pieces(self, indices: List[int]):
        with self._lock:
            if not self.transfer_state or self.transfer_state.get("complete"):
                return
            delay = self.transfer_state["delay"]
            num_pieces = self.transfer_state["num_pieces"]

        for i in indices:
            with self._lock:
                if self.transfer_state.get("complete"):
                    break

            if not (0 <= i < num_pieces):
                logger.warning(f"Skipping invalid outbound piece index {i}.")
                continue

            data = self._read_piece(i)
            if data is None:
                with self._lock:
                    self.transfer_state["complete"] = True
                    self.transfer_state["failed"] = True
                    self.last_error = "piece_read_error"
                break

            piece_proto = self._build_piece_data(i, data)
            msg = akita_pb2.InnerMessage()
            msg.piece_data.CopyFrom(piece_proto)

            self.send_inner(msg)

            with self._lock:
                self.transfer_state["sent_pieces"][i] = True
                self.transfer_state["plain_data_bytes"] += len(data)
                self.transfer_state["wire_data_bytes"] += len(piece_proto.data)
                if piece_proto.compressed:
                    self.transfer_state["compressed_pieces"] += 1
            time.sleep(delay)

    def _build_piece_data(self, index: int, data: bytes) -> akita_pb2.PieceData:
        if (
            self.profile.compression_enabled
            and len(data) >= self.profile.compression_min_bytes
        ):
            compressed = zlib.compress(data, self.profile.compression_level)
            if len(compressed) < len(data):
                return akita_pb2.PieceData(
                    piece_index=index,
                    data=compressed,
                    compressed=True,
                    original_size=len(data),
                )
        return akita_pb2.PieceData(
            piece_index=index,
            data=data,
            compressed=False,
            original_size=len(data),
        )

    def handle_message(self, msg: akita_pb2.InnerMessage) -> None:
        if msg.HasField("file_start"):
            self._handle_file_start(msg.file_start)
        elif msg.HasField("piece_data"):
            self._handle_piece_data(msg.piece_data)
        elif msg.HasField("resume_request"):
            self._handle_resume_request(msg.resume_request)
        elif msg.HasField("acknowledgement"):
            self._handle_acknowledgement(msg.acknowledgement)

    def _handle_file_start(self, fs: akita_pb2.FileStart):
        total_size = fs.total_size
        piece_size = fs.piece_size
        if total_size > MAX_FILE_SIZE:
            logger.error(f"Rejecting transfer above maximum size: {total_size} > {MAX_FILE_SIZE}.")
            self.last_error = "file_too_large"
            return
        if total_size > 0 and not (MIN_PIECE_SIZE <= piece_size <= MAX_PIECE_SIZE):
            logger.error(f"Rejecting transfer with invalid piece size: {piece_size}.")
            self.last_error = "invalid_piece_size"
            return
        if total_size == 0 and piece_size == 0:
            piece_size = self.piece_size
        elif total_size > 0 and piece_size == 0:
            logger.error("Rejecting non-empty transfer with zero piece size.")
            self.last_error = "invalid_piece_size"
            return

        num_pieces = (
            (total_size + piece_size - 1) // piece_size
            if total_size > 0
            else 0
        )
        piece_hashes = list(fs.piece_hashes)
        if piece_hashes and len(piece_hashes) != num_pieces:
            logger.error(
                f"Rejecting transfer with {len(piece_hashes)} piece hashes for {num_pieces} pieces."
            )
            self.last_error = "hash_count_mismatch"
            return

        with self._lock:
            self.receive_state = {
                "filename": fs.filename,
                "total_size": total_size,
                "piece_size": piece_size,
                "num_pieces": num_pieces,
                "merkle_root": fs.merkle_root if fs.HasField("merkle_root") else None,
                "piece_hashes": piece_hashes,
                "received_pieces": {},
                "received_hashes": {},
                "missing_indices": set(range(num_pieces)),
                "complete": False,
                "failed": False,
            }

        if num_pieces == 0 and total_size == 0:
            self._assemble()

    def _handle_piece_data(self, piece: akita_pb2.PieceData):
        request_missing = False
        with self._lock:
            if not self.receive_state or self.receive_state.get("complete") or self.receive_state.get("failed"):
                return
            index = piece.piece_index
            num_pieces = self.receive_state["num_pieces"]
            if not (0 <= index < num_pieces):
                logger.warning(f"Ignoring out-of-range piece index {index}.")
                return
            if index in self.receive_state["received_pieces"]:
                return

            expected_len = self.receive_state["piece_size"]
            if index == num_pieces - 1:
                remainder = self.receive_state["total_size"] % self.receive_state["piece_size"]
                expected_len = remainder or self.receive_state["piece_size"]

            piece_bytes = piece.data
            if piece.compressed:
                try:
                    decompressor = zlib.decompressobj()
                    piece_bytes = decompressor.decompress(piece.data, expected_len + 1)
                    if not decompressor.eof or decompressor.unconsumed_tail:
                        raise zlib.error("compressed piece exceeds expected size")
                except zlib.error:
                    logger.warning(f"Rejecting piece {index}: decompression failed.")
                    request_missing = True
                    piece_bytes = b""
                if not request_missing and len(piece_bytes) != piece.original_size:
                    logger.warning(
                        f"Rejecting piece {index}: decompressed size expected "
                        f"{piece.original_size}, got {len(piece_bytes)}."
                    )
                    request_missing = True

            if not request_missing and len(piece_bytes) != expected_len:
                logger.warning(
                    f"Rejecting piece {index}: expected {expected_len} bytes, got {len(piece_bytes)}."
                )
                request_missing = True
            if not request_missing:
                piece_hash = calculate_hash(piece_bytes)
                piece_hashes = self.receive_state.get("piece_hashes", [])
                if piece_hashes and piece_hash != piece_hashes[index]:
                    logger.warning(f"Rejecting piece {index}: hash mismatch.")
                    request_missing = True
                else:
                    self.receive_state["received_pieces"][index] = piece_bytes
                    self.receive_state["received_hashes"][index] = piece_hash
                    self.receive_state["missing_indices"].discard(index)

        if request_missing:
            self._send_resume_request()
            return

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

    def _handle_acknowledgement(self, ack: akita_pb2.Acknowledgement):
        with self._lock:
            if not self.transfer_state or self.transfer_state.get("complete"):
                return
            if 0 <= ack.piece_index < self.transfer_state["num_pieces"]:
                self.transfer_state["acknowledged_pieces"][ack.piece_index] = True
            if all(self.transfer_state["acknowledged_pieces"]):
                self.transfer_state["complete"] = True
                logger.info("Transfer completed successfully.")

    def _check_assembly(self):
        should_assemble = False
        should_request = False
        with self._lock:
            if self.receive_state.get("complete"):
                return
            if (
                len(self.receive_state["received_pieces"])
                == self.receive_state["num_pieces"]
            ):
                num_pieces = self.receive_state["num_pieces"]
                received_hashes = self.receive_state.get("received_hashes", {})
                merkle_root = self.receive_state.get("merkle_root")
                piece_hashes = self.receive_state.get("piece_hashes", [])

                if merkle_root:
                    calculated_root = calculate_merkle_root(
                        [received_hashes[i] for i in range(num_pieces)]
                    )
                    if calculated_root == merkle_root:
                        should_assemble = True
                    else:
                        logger.warning("Merkle root mismatch; requesting all pieces again.")
                        self.receive_state["received_pieces"].clear()
                        self.receive_state["received_hashes"].clear()
                        self.receive_state["missing_indices"] = set(range(num_pieces))
                        should_request = True
                elif piece_hashes:
                    mismatched = {
                        i
                        for i in range(num_pieces)
                        if received_hashes.get(i) != piece_hashes[i]
                    }
                    if mismatched:
                        logger.warning(f"Piece hash verification failed for: {sorted(mismatched)}.")
                        for i in mismatched:
                            self.receive_state["received_pieces"].pop(i, None)
                            self.receive_state["received_hashes"].pop(i, None)
                        self.receive_state["missing_indices"].update(mismatched)
                        should_request = True
                    else:
                        should_assemble = True
                else:
                    logger.warning("No integrity metadata provided; assembling by piece count and size only.")
                    should_assemble = True

        if should_assemble:
            self._assemble()
        elif should_request:
            self._send_resume_request()

    def _assemble(self):
        with self._lock:
            pieces = [
                self.receive_state["received_pieces"][i]
                for i in range(self.receive_state["num_pieces"])
            ]
            data = b"".join(pieces)
            if len(data) != self.receive_state["total_size"]:
                logger.error(
                    f"Rejecting assembled data for '{self.receive_state['filename']}': "
                    f"expected {self.receive_state['total_size']} bytes, got {len(data)}."
                )
                self.receive_state["failed"] = True
                self.last_error = "assembled_size_mismatch"
                return
            safe_name = sanitize_filename(self.receive_state["filename"])
            self.receive_state["complete"] = True

        if self.save:
            self.save(safe_name, data)
        self._send_resume_request(force=True)

    def _send_resume_request(self, force: bool = False):
        with self._lock:
            if not self.receive_state or self.receive_state.get("failed"):
                return
            missing = sorted(self.receive_state["missing_indices"])
            acked = sorted(self.receive_state["received_pieces"].keys())
            if not force and not missing:
                return

        req = akita_pb2.ResumeRequest(
            missing_indices=missing,
            acknowledged_indices=acked,
        )
        msg = akita_pb2.InnerMessage()
        msg.resume_request.CopyFrom(req)
        self.send_inner(msg)

    def check_timeouts(self) -> None:
        current_time = time.time()
        should_request = False
        with self._lock:
            if not self.receive_state or self.receive_state.get("complete"):
                return
            if current_time - self.last_request_time > self.request_interval:
                should_request = bool(self.receive_state["missing_indices"])
                self.last_request_time = current_time

        if should_request:
            self._send_resume_request()

    def cleanup(self) -> None:
        with self._lock:
            self.transfer_state.clear()
            self.receive_state.clear()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            if self.transfer_state:
                num_pieces = self.transfer_state.get("num_pieces", 0)
                sent = sum(1 for value in self.transfer_state.get("sent_pieces", []) if value)
                acked = sum(1 for value in self.transfer_state.get("acknowledged_pieces", []) if value)
                complete = bool(self.transfer_state.get("complete"))
                failed = bool(self.transfer_state.get("failed"))
                total_size = self.transfer_state.get("total_size", 0)
                piece_size = self.piece_size
                return {
                    "direction": "send",
                    "filename": os.path.basename(self.transfer_state.get("filepath", "")),
                    "state": "failed" if failed else ("complete" if complete else "active"),
                    "total_size": total_size,
                    "piece_size": piece_size,
                    "num_pieces": num_pieces,
                    "sent_pieces": sent,
                    "acknowledged_pieces": acked,
                    "compressed_pieces": self.transfer_state.get("compressed_pieces", 0),
                    "wire_data_bytes": self.transfer_state.get("wire_data_bytes", 0),
                    "plain_data_bytes": self.transfer_state.get("plain_data_bytes", 0),
                    "complete": complete,
                    "failed": failed,
                    "error": self.last_error,
                }

            if self.receive_state:
                num_pieces = self.receive_state.get("num_pieces", 0)
                received = len(self.receive_state.get("received_pieces", {}))
                complete = bool(self.receive_state.get("complete"))
                failed = bool(self.receive_state.get("failed"))
                return {
                    "direction": "receive",
                    "filename": self.receive_state.get("filename"),
                    "state": "failed" if failed else ("complete" if complete else "active"),
                    "total_size": self.receive_state.get("total_size", 0),
                    "piece_size": self.receive_state.get("piece_size", self.piece_size),
                    "num_pieces": num_pieces,
                    "received_pieces": received,
                    "complete": complete,
                    "failed": failed,
                    "error": self.last_error,
                }

        return {
            "direction": "idle",
            "filename": None,
            "state": "idle",
            "total_size": 0,
            "piece_size": self.piece_size,
            "num_pieces": 0,
            "complete": False,
            "failed": False,
            "error": self.last_error,
        }
