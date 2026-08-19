import logging
import os
import tempfile
import threading
import time
import zlib
from typing import Any, Callable, Dict, List, Optional

from .base import BaseProtocolHandler
from ..common import (
    MAX_FILE_SIZE,
    MAX_PIECE_SIZE,
    MIN_PIECE_SIZE,
    Crc32c,
    calculate_hash,
    calculate_merkle_root,
    crc32c,
    crc32c_file,
    sanitize_filename,
)
from ..generated import akita_pb2

logger = logging.getLogger(__name__)


class SupermodemHandler(BaseProtocolHandler):
    """
    Native Akita Supermodem protocol.

    Sends on a worker thread with a sliding window so the radio receive
    callback is never blocked. Pieces carry CRC-32C plus SHA-256 Merkle
    integrity; missing pieces are requested in small selective-NAK batches.
    """

    def __init__(
        self,
        send_function: Callable[[akita_pb2.InnerMessage], None],
        save_function: Callable[[str, bytes], None],
        profile=None,
        save_path_function: Optional[Callable[[str, str], None]] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        session_id: Optional[str] = None,
        checkpoint_dir: Optional[str] = None,
    ):
        super().__init__(None, None, save_function, profile=profile)
        self.send_inner = send_function
        self.save_path = save_path_function
        self.event_callback = event_callback
        self.session_id = session_id
        self.checkpoint_dir = checkpoint_dir
        self.piece_size = self.profile.piece_size

        self.transfer_state: Dict[str, Any] = {}
        self.receive_state: Dict[str, Any] = {}

        self.retry_threshold = self.profile.max_retries
        self.request_interval = self.profile.timeout
        self.last_request_time = 0.0
        self.last_error = None

        self._lock = threading.RLock()
        self._send_wakeup = threading.Event()
        self._stop_event = threading.Event()
        self._send_thread: Optional[threading.Thread] = None

    def start_transfer(self, filepath: str) -> bool:
        if not os.path.exists(filepath):
            logger.error("File not found: %s", filepath)
            self.last_error = "file_not_found"
            return False
        if not os.path.isfile(filepath):
            logger.error("Path is not a file: %s", filepath)
            self.last_error = "not_a_file"
            return False

        total_size = os.path.getsize(filepath)
        if total_size > MAX_FILE_SIZE:
            logger.error("File is larger than supported maximum: %s > %s", total_size, MAX_FILE_SIZE)
            self.last_error = "file_too_large"
            return False

        num_pieces = (
            (total_size + self.piece_size - 1) // self.piece_size
            if total_size > 0
            else 0
        )

        piece_hashes: List[str] = []
        digest = Crc32c()
        try:
            with open(filepath, "rb") as handle:
                for _ in range(num_pieces):
                    piece = handle.read(self.piece_size)
                    if not piece:
                        break
                    piece_hashes.append(calculate_hash(piece))
                    digest.update(piece)
            file_crc = digest.digest()
        except Exception as e:
            logger.error("Error reading file %s: %s", filepath, e)
            self.last_error = "read_error"
            return False

        if len(piece_hashes) != num_pieces:
            logger.error(
                "Expected %s pieces while hashing '%s', got %s.",
                num_pieces,
                filepath,
                len(piece_hashes),
            )
            self.last_error = "short_read"
            return False

        fs_proto = akita_pb2.FileStart(
            filename=os.path.basename(filepath),
            total_size=total_size,
            piece_size=self.piece_size,
            file_crc32c=file_crc,
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
                "file_crc32c": file_crc,
                "sent_pieces": [False] * num_pieces,
                "acknowledged_pieces": [False] * num_pieces,
                "requested_indices": [],
                "delay": self.profile.initial_delay,
                "retry_count": 0,
                "complete": False,
                "failed": False,
                "compressed_pieces": 0,
                "wire_data_bytes": 0,
                "plain_data_bytes": 0,
            }

        self.send_inner(msg)
        self._emit_event(
            "transfer_started",
            direction="send",
            filename=os.path.basename(filepath),
            total_size=total_size,
            num_pieces=num_pieces,
        )
        if num_pieces == 0:
            return True
        self._start_send_thread()
        return True

    def _start_send_thread(self) -> None:
        if self._send_thread and self._send_thread.is_alive():
            self._send_wakeup.set()
            return
        self._stop_event.clear()
        self._send_thread = threading.Thread(
            target=self._send_loop,
            name="akita-send",
            daemon=True,
        )
        self._send_thread.start()

    def _send_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    if not self.transfer_state:
                        return
                    if self.transfer_state.get("complete") or self.transfer_state.get("failed"):
                        return
                indices = self._next_send_window()
                if indices:
                    self._send_pieces(indices)
                    continue
                self._send_wakeup.wait(self.request_interval)
                self._send_wakeup.clear()
        except Exception as e:
            logger.error("Send loop failed: %s", e)
            with self._lock:
                if self.transfer_state:
                    self.transfer_state["complete"] = True
                    self.transfer_state["failed"] = True
                self.last_error = "send_loop_error"

    def _next_send_window(self) -> List[int]:
        with self._lock:
            state = self.transfer_state
            if not state or state.get("complete") or state.get("failed"):
                return []
            num_pieces = state["num_pieces"]
            sent = state["sent_pieces"]
            acked = state["acknowledged_pieces"]
            requested = [
                index for index in state.get("requested_indices", [])
                if 0 <= index < num_pieces and not acked[index]
            ]
            in_flight = sum(
                1
                for index in range(num_pieces)
                if sent[index] and not acked[index] and index not in requested
            )
            slots = max(0, self.profile.send_window - in_flight)
            candidates: List[int] = []
            seen = set()
            for index in requested:
                if index not in seen:
                    candidates.append(index)
                    seen.add(index)
            for index in range(num_pieces):
                if not sent[index] and not acked[index] and index not in seen:
                    candidates.append(index)
                    seen.add(index)
            if not candidates and slots == 0:
                # Lost trailing window or receiver restart: recycle unacked pieces.
                candidates = [
                    index for index in range(num_pieces) if not acked[index]
                ]
                return candidates[: self.profile.send_window]
            return candidates[:slots]

    def _read_piece(self, index: int) -> bytes | None:
        with self._lock:
            if not self.transfer_state:
                return None
            filepath = self.transfer_state["filepath"]
            num_pieces = self.transfer_state["num_pieces"]
            total_size = self.transfer_state["total_size"]

        if not (0 <= index < num_pieces):
            logger.warning("Requested invalid piece index %s.", index)
            return None

        offset = index * self.piece_size
        length = min(self.piece_size, total_size - offset)
        try:
            with open(filepath, "rb") as handle:
                handle.seek(offset)
                data = handle.read(length)
        except OSError as e:
            logger.error("Failed to read piece %s from '%s': %s", index, filepath, e)
            return None

        if len(data) != length:
            logger.error("Short read for piece %s: expected %s, got %s.", index, length, len(data))
            return None
        return data

    def _send_pieces(self, indices: List[int]):
        with self._lock:
            if not self.transfer_state or self.transfer_state.get("complete"):
                return
            delay = self.transfer_state["delay"]
            num_pieces = self.transfer_state["num_pieces"]

        for i in indices:
            if self._stop_event.is_set():
                return
            with self._lock:
                if self.transfer_state.get("complete") or self.transfer_state.get("failed"):
                    break

            if not (0 <= i < num_pieces):
                logger.warning("Skipping invalid outbound piece index %s.", i)
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
                requested = self.transfer_state.get("requested_indices", [])
                if i in requested:
                    self.transfer_state["requested_indices"] = [idx for idx in requested if idx != i]
                self.transfer_state["plain_data_bytes"] += len(data)
                self.transfer_state["wire_data_bytes"] += len(piece_proto.data)
                if piece_proto.compressed:
                    self.transfer_state["compressed_pieces"] += 1
            self._emit_event(
                "piece_sent",
                direction="send",
                piece_index=i,
                num_pieces=num_pieces,
                wire_bytes=len(piece_proto.data),
                plain_bytes=len(data),
                compressed=piece_proto.compressed,
                crc32c=piece_proto.crc32c,
            )
            if delay > 0:
                time.sleep(delay)

    def _build_piece_data(self, index: int, data: bytes) -> akita_pb2.PieceData:
        piece_crc = crc32c(data)
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
                    crc32c=piece_crc,
                )
        return akita_pb2.PieceData(
            piece_index=index,
            data=data,
            compressed=False,
            original_size=len(data),
            crc32c=piece_crc,
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
            logger.error("Rejecting transfer above maximum size: %s > %s.", total_size, MAX_FILE_SIZE)
            self.last_error = "file_too_large"
            return
        if total_size > 0 and not (MIN_PIECE_SIZE <= piece_size <= MAX_PIECE_SIZE):
            logger.error("Rejecting transfer with invalid piece size: %s.", piece_size)
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
                "Rejecting transfer with %s piece hashes for %s pieces.",
                len(piece_hashes),
                num_pieces,
            )
            self.last_error = "hash_count_mismatch"
            return

        with self._lock:
            self._cleanup_receive_temp_locked()

        if self.checkpoint_dir:
            os.makedirs(self.checkpoint_dir, exist_ok=True)
            temp_path = os.path.join(self.checkpoint_dir, "staging.part")
            with open(temp_path, "wb"):
                pass
        else:
            temp_file = tempfile.NamedTemporaryFile(prefix="akita_receive_", suffix=".part", delete=False)
            temp_path = temp_file.name
            temp_file.close()

        with self._lock:
            self.receive_state = {
                "filename": fs.filename,
                "total_size": total_size,
                "piece_size": piece_size,
                "num_pieces": num_pieces,
                "merkle_root": fs.merkle_root if fs.HasField("merkle_root") else None,
                "piece_hashes": piece_hashes,
                "file_crc32c": fs.file_crc32c if fs.HasField("file_crc32c") else None,
                "received_indices": set(),
                "received_hashes": {},
                "retry_count": {},
                "missing_hint": 0,
                "pieces_since_ack": 0,
                "complete": False,
                "failed": False,
                "temp_path": temp_path,
                "temp_published": False,
                "last_activity": time.time(),
            }
        self._emit_event(
            "transfer_started",
            direction="receive",
            filename=fs.filename,
            total_size=total_size,
            num_pieces=num_pieces,
        )

        if num_pieces == 0 and total_size == 0:
            self._assemble()

    def _expected_piece_len(self, index: int, num_pieces: int, piece_size: int, total_size: int) -> int:
        if index == num_pieces - 1:
            remainder = total_size % piece_size
            return remainder or piece_size
        return piece_size

    def _missing_prefix(self, limit: int) -> List[int]:
        received = self.receive_state["received_indices"]
        num_pieces = self.receive_state["num_pieces"]
        hint = min(self.receive_state.get("missing_hint", 0), num_pieces)
        missing: List[int] = []
        index = hint
        scanned = 0
        while scanned < num_pieces and len(missing) < limit:
            if index not in received:
                missing.append(index)
                if len(missing) == 1:
                    self.receive_state["missing_hint"] = index
            index = (index + 1) % num_pieces if num_pieces else 0
            scanned += 1
            if index == hint:
                break
        if not missing:
            self.receive_state["missing_hint"] = num_pieces
        return missing

    def _handle_piece_data(self, piece: akita_pb2.PieceData):
        request_missing = False
        should_ack = False
        with self._lock:
            if not self.receive_state or self.receive_state.get("complete") or self.receive_state.get("failed"):
                return
            index = piece.piece_index
            num_pieces = self.receive_state["num_pieces"]
            if not (0 <= index < num_pieces):
                logger.warning("Ignoring out-of-range piece index %s.", index)
                return
            if index in self.receive_state["received_indices"]:
                return

            expected_len = self._expected_piece_len(
                index,
                num_pieces,
                self.receive_state["piece_size"],
                self.receive_state["total_size"],
            )

            piece_bytes = piece.data
            if piece.compressed:
                try:
                    decompressor = zlib.decompressobj()
                    piece_bytes = decompressor.decompress(piece.data, expected_len + 1)
                    if not decompressor.eof or decompressor.unconsumed_tail:
                        raise zlib.error("compressed piece exceeds expected size")
                except zlib.error:
                    logger.warning("Rejecting piece %s: decompression failed.", index)
                    request_missing = True
                    piece_bytes = b""
                if not request_missing and len(piece_bytes) != piece.original_size:
                    logger.warning(
                        "Rejecting piece %s: decompressed size expected %s, got %s.",
                        index,
                        piece.original_size,
                        len(piece_bytes),
                    )
                    request_missing = True

            if not request_missing and len(piece_bytes) != expected_len:
                logger.warning(
                    "Rejecting piece %s: expected %s bytes, got %s.",
                    index,
                    expected_len,
                    len(piece_bytes),
                )
                request_missing = True

            if not request_missing and piece.HasField("crc32c") and crc32c(piece_bytes) != piece.crc32c:
                logger.warning("Rejecting piece %s: CRC-32C mismatch.", index)
                request_missing = True

            received_count = 0
            if not request_missing:
                piece_hash = calculate_hash(piece_bytes)
                piece_hashes = self.receive_state.get("piece_hashes", [])
                if piece_hashes and piece_hash != piece_hashes[index]:
                    logger.warning("Rejecting piece %s: hash mismatch.", index)
                    request_missing = True
                else:
                    temp_path = self.receive_state["temp_path"]
                    offset = index * self.receive_state["piece_size"]
                    try:
                        with open(temp_path, "r+b") as handle:
                            handle.seek(offset)
                            handle.write(piece_bytes)
                    except OSError as e:
                        logger.error("Failed writing piece %s to staging file: %s", index, e)
                        self.receive_state["failed"] = True
                        self.last_error = "staging_write_failed"
                        return
                    self.receive_state["received_indices"].add(index)
                    self.receive_state["received_hashes"][index] = piece_hash
                    self.receive_state["retry_count"].pop(index, None)
                    if index == self.receive_state.get("missing_hint", 0):
                        self.receive_state["missing_hint"] = index + 1
                    self.receive_state["last_activity"] = time.time()
                    self.receive_state["pieces_since_ack"] += 1
                    received_count = len(self.receive_state["received_indices"])
                    lowest_missing = self._missing_prefix(1)
                    gap = bool(lowest_missing) and lowest_missing[0] < index
                    if (
                        gap
                        or self.receive_state["pieces_since_ack"] >= self.profile.send_window
                        or received_count == num_pieces
                    ):
                        should_ack = True
                        self.receive_state["pieces_since_ack"] = 0

        if not request_missing and received_count:
            self._emit_event(
                "piece_received",
                direction="receive",
                piece_index=index,
                received_pieces=received_count,
                num_pieces=num_pieces,
            )

        if request_missing:
            self._note_retry(index)
            self._send_resume_request()
            return

        if should_ack:
            self._send_resume_request()

        self._check_assembly()

    def _note_retry(self, index: Optional[int] = None) -> None:
        with self._lock:
            if not self.receive_state:
                return
            retries = self.receive_state.setdefault("retry_count", {})
            targets = [index] if index is not None else self._missing_prefix(self.profile.max_resume_indices)
            for item in targets:
                retries[item] = retries.get(item, 0) + 1
                if retries[item] >= self.profile.max_retries:
                    logger.error(
                        "Reached max retries (%s) for piece %s. Marking transfer as failed.",
                        self.profile.max_retries,
                        item,
                    )
                    self.receive_state["failed"] = True
                    self.last_error = "max_retries_exceeded"
                    self._emit_event(
                        "transfer_failed",
                        direction="receive",
                        error="max_retries_exceeded",
                    )

    def _handle_resume_request(self, req: akita_pb2.ResumeRequest):
        with self._lock:
            if not self.transfer_state or self.transfer_state.get("complete"):
                return

            num_pieces = self.transfer_state["num_pieces"]
            for idx in req.acknowledged_indices:
                if 0 <= idx < num_pieces:
                    self.transfer_state["acknowledged_pieces"][idx] = True

            if num_pieces == 0 or all(self.transfer_state["acknowledged_pieces"]):
                self.transfer_state["complete"] = True
                logger.info("Transfer completed successfully.")
                self._send_wakeup.set()
                return

            missing = [idx for idx in req.missing_indices if 0 <= idx < num_pieces]
            if missing:
                self.transfer_state["retry_count"] += 1
                if self.transfer_state["retry_count"] >= self.retry_threshold:
                    self.transfer_state["delay"] = min(
                        self.transfer_state["delay"] * 1.5, self.profile.max_delay
                    )
                    self.transfer_state["retry_count"] = 0
                for idx in missing:
                    self.transfer_state["sent_pieces"][idx] = False
                requested = self.transfer_state.setdefault("requested_indices", [])
                for idx in missing:
                    if idx not in requested:
                        requested.append(idx)
            else:
                self.transfer_state["retry_count"] = 0

        self._send_wakeup.set()

    def _handle_acknowledgement(self, ack: akita_pb2.Acknowledgement):
        with self._lock:
            if not self.transfer_state or self.transfer_state.get("complete"):
                return
            if 0 <= ack.piece_index < self.transfer_state["num_pieces"]:
                self.transfer_state["acknowledged_pieces"][ack.piece_index] = True
            if self.transfer_state["num_pieces"] == 0 or all(self.transfer_state["acknowledged_pieces"]):
                self.transfer_state["complete"] = True
                logger.info("Transfer completed successfully.")
        self._send_wakeup.set()

    def _check_assembly(self):
        should_assemble = False
        should_request = False
        with self._lock:
            if not self.receive_state or self.receive_state.get("complete") or self.receive_state.get("failed"):
                return
            num_pieces = self.receive_state["num_pieces"]
            if len(self.receive_state["received_indices"]) != num_pieces:
                return
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
                    self.receive_state["received_indices"].clear()
                    self.receive_state["received_hashes"].clear()
                    self.receive_state["missing_hint"] = 0
                    self._reset_staging_file(self.receive_state)
                    should_request = True
            elif piece_hashes:
                mismatched = {
                    i
                    for i in range(num_pieces)
                    if received_hashes.get(i) != piece_hashes[i]
                }
                if mismatched:
                    logger.warning("Piece hash verification failed for: %s.", sorted(mismatched))
                    for i in mismatched:
                        self.receive_state["received_indices"].discard(i)
                        self.receive_state["received_hashes"].pop(i, None)
                    self.receive_state["missing_hint"] = min(mismatched)
                    should_request = True
                else:
                    should_assemble = True
            else:
                logger.warning("No Merkle metadata provided; assembling with CRC-32C and piece count.")
                should_assemble = True

        if should_assemble:
            self._assemble()
        elif should_request:
            self._send_resume_request()

    def _assemble(self):
        with self._lock:
            if not self.receive_state or self.receive_state.get("complete") or self.receive_state.get("failed"):
                return
            if len(self.receive_state["received_indices"]) != self.receive_state["num_pieces"]:
                logger.error(
                    "Rejecting assembled data for '%s': incomplete staging file.",
                    self.receive_state["filename"],
                )
                self.receive_state["failed"] = True
                self.last_error = "incomplete_staging_file"
                return
            temp_path = self.receive_state["temp_path"]
            expected_size = self.receive_state["total_size"]
            expected_crc = self.receive_state.get("file_crc32c")
            safe_name = sanitize_filename(self.receive_state["filename"])

        staged_size = os.path.getsize(temp_path) if os.path.exists(temp_path) else -1
        if staged_size != expected_size:
            logger.error(
                "Rejecting assembled data for '%s': expected %s bytes, got %s.",
                safe_name,
                expected_size,
                staged_size,
            )
            with self._lock:
                if self.receive_state:
                    self.receive_state["failed"] = True
                self.last_error = "assembled_size_mismatch"
            return

        if expected_crc is not None:
            try:
                actual_crc = crc32c_file(temp_path)
            except OSError as e:
                logger.error("Failed hashing staged file %s: %s", temp_path, e)
                with self._lock:
                    if self.receive_state:
                        self.receive_state["failed"] = True
                    self.last_error = "staging_crc_failed"
                return
            if actual_crc != expected_crc:
                logger.error(
                    "Rejecting assembled data for '%s': file CRC-32C mismatch.",
                    safe_name,
                )
                with self._lock:
                    if self.receive_state:
                        self.receive_state["failed"] = True
                    self.last_error = "file_crc_mismatch"
                return

        try:
            if self.save_path:
                self.save_path(safe_name, temp_path)
            elif self.save:
                with open(temp_path, "rb") as handle:
                    self.save(safe_name, handle.read())
                try:
                    os.unlink(temp_path)
                except OSError as e:
                    logger.warning("Failed removing staging file %s: %s", temp_path, e)
            else:
                raise RuntimeError("no save callback configured")
        except Exception as e:
            logger.error("Failed publishing received file '%s': %s", safe_name, e)
            with self._lock:
                if self.receive_state:
                    self.receive_state["failed"] = True
                self.last_error = "save_failed"
            self._emit_event(
                "transfer_failed",
                direction="receive",
                filename=safe_name,
                error="save_failed",
            )
            return

        with self._lock:
            if self.receive_state:
                self.receive_state["complete"] = True
                self.receive_state["temp_published"] = True
        self._emit_event(
            "transfer_complete",
            direction="receive",
            filename=safe_name,
            total_size=staged_size,
        )
        self._send_resume_request(force=True)

    def _send_resume_request(self, force: bool = False):
        with self._lock:
            if not self.receive_state or self.receive_state.get("failed"):
                return
            missing = self._missing_prefix(self.profile.max_resume_indices)
            acked = sorted(self.receive_state["received_indices"])
            if not force and not missing:
                return
            self.last_request_time = time.time()

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
            if not self.receive_state or self.receive_state.get("complete") or self.receive_state.get("failed"):
                return
            last_activity = self.receive_state.get("last_activity", current_time)
            if current_time - last_activity > self.profile.inactivity_timeout:
                self.receive_state["failed"] = True
                self.last_error = "inactivity_timeout"
                logger.warning("Receive transfer timed out due to inactivity.")
                self._emit_event(
                    "transfer_failed",
                    direction="receive",
                    error="inactivity_timeout",
                )
                return
            interval = max(self.request_interval, 0.25)
            if current_time - self.last_request_time > interval:
                missing = self._missing_prefix(1)
                should_request = bool(missing)
                self.last_request_time = current_time

        if should_request:
            self._note_retry()
            if not (self.receive_state and self.receive_state.get("failed")):
                self._send_resume_request()

    def export_receive_state(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self.receive_state or self.receive_state.get("complete"):
                return None
            return {
                "filename": self.receive_state.get("filename"),
                "total_size": self.receive_state.get("total_size", 0),
                "piece_size": self.receive_state.get("piece_size", self.piece_size),
                "num_pieces": self.receive_state.get("num_pieces", 0),
                "merkle_root": self.receive_state.get("merkle_root"),
                "piece_hashes": list(self.receive_state.get("piece_hashes") or []),
                "file_crc32c": self.receive_state.get("file_crc32c"),
                "received_indices": sorted(self.receive_state.get("received_indices") or []),
                "received_hashes": {
                    str(index): digest
                    for index, digest in (self.receive_state.get("received_hashes") or {}).items()
                },
                "retry_count": {
                    str(index): count
                    for index, count in (self.receive_state.get("retry_count") or {}).items()
                },
                "missing_hint": self.receive_state.get("missing_hint", 0),
                "temp_path": self.receive_state.get("temp_path"),
                "failed": bool(self.receive_state.get("failed")),
            }

    def restore_receive_state(self, payload: Dict[str, Any]) -> bool:
        temp_path = payload.get("temp_path")
        if not temp_path or not os.path.exists(temp_path):
            logger.error("Cannot restore receive session: staging file missing.")
            return False
        with self._lock:
            self.receive_state = {
                "filename": payload.get("filename", "unnamed_file"),
                "total_size": int(payload.get("total_size", 0)),
                "piece_size": int(payload.get("piece_size", self.piece_size)),
                "num_pieces": int(payload.get("num_pieces", 0)),
                "merkle_root": payload.get("merkle_root"),
                "piece_hashes": list(payload.get("piece_hashes") or []),
                "file_crc32c": payload.get("file_crc32c"),
                "received_indices": set(int(index) for index in payload.get("received_indices") or []),
                "received_hashes": {
                    int(index): digest
                    for index, digest in (payload.get("received_hashes") or {}).items()
                },
                "retry_count": {
                    int(index): int(count)
                    for index, count in (payload.get("retry_count") or {}).items()
                },
                "missing_hint": int(payload.get("missing_hint", 0)),
                "pieces_since_ack": 0,
                "complete": False,
                "failed": bool(payload.get("failed")),
                "temp_path": temp_path,
                "temp_published": False,
                "last_activity": time.time(),
            }
        return True

    def cleanup(self) -> None:
        self._stop_event.set()
        self._send_wakeup.set()
        thread = self._send_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        with self._lock:
            self._cleanup_receive_temp_locked()
            self.transfer_state.clear()
            self.receive_state.clear()

    def _reset_staging_file(self, receive_state: Dict[str, Any]) -> None:
        temp_path = receive_state.get("temp_path")
        if not temp_path:
            return
        try:
            with open(temp_path, "wb"):
                pass
        except OSError as e:
            logger.error("Failed resetting staging file %s: %s", temp_path, e)
            receive_state["failed"] = True
            self.last_error = "staging_reset_failed"

    def _cleanup_receive_temp_locked(self) -> None:
        temp_path = self.receive_state.get("temp_path") if self.receive_state else None
        if self.checkpoint_dir or not temp_path or self.receive_state.get("temp_published"):
            return
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError as e:
            logger.warning("Failed removing staging file %s: %s", temp_path, e)

    def _emit_event(self, event: str, **fields: Any) -> None:
        if not self.event_callback:
            return
        try:
            self.event_callback({"event": event, **fields})
        except Exception as e:
            logger.warning("Protocol event callback failed for %s: %s", event, e)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            if self.transfer_state:
                num_pieces = self.transfer_state.get("num_pieces", 0)
                sent = sum(1 for value in self.transfer_state.get("sent_pieces", []) if value)
                acked = sum(1 for value in self.transfer_state.get("acknowledged_pieces", []) if value)
                complete = bool(self.transfer_state.get("complete"))
                failed = bool(self.transfer_state.get("failed"))
                total_size = self.transfer_state.get("total_size", 0)
                return {
                    "direction": "send",
                    "filename": os.path.basename(self.transfer_state.get("filepath", "")),
                    "state": "failed" if failed else ("complete" if complete else "active"),
                    "total_size": total_size,
                    "piece_size": self.piece_size,
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
                received = len(self.receive_state.get("received_indices", set()))
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
