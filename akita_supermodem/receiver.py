# akita_supermodem/receiver.py

"""
Contains the AkitaReceiver class for managing incoming file transfers.
"""

import time
import hashlib
import os
from typing import Callable, Dict, Any, Optional, List, Set

# Use relative imports within the package
from .common import AKITA_CONTENT_TYPE, calculate_hash, DEFAULT_TIMEOUT, DEFAULT_MAX_RETRIES
# Import generated protobuf code using relative path
# Ensure akita_pb2.py is generated in the 'generated' subdirectory
try:
    from .generated import akita_pb2
except ImportError:
    print("ERROR: Cannot import generated protobuf code (akita_pb2.py).")
    print("Please run the protoc command specified in README.md first.")
    # Optionally raise the error or exit
    raise


# Type hint for the callback functions
SaveFunction = Callable[[str, bytes], None]  # Args: filename, data
SendFunction = Callable[[str, bytes, int], None] # Args: node_id, payload, portNum

class AkitaReceiver:
    """
    Manages the receiving side of Akita Supermodem file transfers.
    Handles incoming pieces, requests retransmissions, verifies integrity,
    and assembles the final file.
    """
    def __init__(self,
                 save_function: SaveFunction,
                 send_function: SendFunction,
                 initial_timeout: float = DEFAULT_TIMEOUT,
                 max_retries: int = DEFAULT_MAX_RETRIES,
                 request_interval: float = 10.0): # How often to check for timeouts/send requests
        """
        Initializes the AkitaReceiver.

        Args:
            save_function: A callback function to save the completed file.
                           It receives (filename: str, data: bytes).
            send_function: A callback function to send data back to the sender
                           (used for ResumeRequest). It receives
                           (node_id: str, payload: bytes, portNum: int).
            initial_timeout: Seconds to wait for a piece before considering it timed out.
                             (Note: Current implementation uses periodic checks, not per-piece timeouts).
            max_retries: Maximum number of times to request a specific missing piece.
            request_interval: Seconds between periodic checks for sending ResumeRequests.
        """
        if not callable(save_function):
            raise ValueError("save_function must be a callable function.")
        if not callable(send_function):
             raise ValueError("send_function must be a callable function.")

        self.save = save_function
        self.send = send_function
        self.initial_timeout = initial_timeout # Stored but not used for per-piece timeouts currently
        self.max_retries = max_retries
        self.request_interval = request_interval

        # Stores state of ongoing transfers, keyed by a unique transfer ID
        # For direct messages: sender_id
        # For broadcasts: f"broadcast_{sender_id}" (or potentially hash of FileStart)
        self.active_transfers: Dict[str, Dict[str, Any]] = {}

        # Timestamp of the last time ResumeRequests were potentially sent for each transfer
        self.last_request_time: Dict[str, float] = {}

        print(f"AkitaReceiver initialized. Max Retries: {max_retries}, Request Interval: {request_interval}s")

    def _get_transfer_id(self, sender_id: str, is_broadcast: bool) -> str:
        """Generates a unique ID for the transfer."""
        # Simple approach: Use sender ID for direct, prefix for broadcast.
        # Could be made more robust (e.g., hash FileStart content) if sender ID reuse
        # or multiple simultaneous broadcasts from one sender are concerns.
        return f"broadcast_{sender_id}" if is_broadcast else sender_id

    def handle_file_start(self, sender_id: str, file_start: akita_pb2.FileStart, is_broadcast: bool = False):
        """Handles an incoming FileStart message."""
        transfer_id = self._get_transfer_id(sender_id, is_broadcast)

        if transfer_id in self.active_transfers:
            # Handle potential duplicate FileStart for an ongoing transfer
            # Maybe reset state or just log a warning?
            print(f"Warning: Received duplicate FILE_START for transfer_id {transfer_id}. Re-initializing state.")
            # Optionally, you could compare the new FileStart with the old one.
            # If they differ significantly, it might be a new file entirely.
            # For now, let's overwrite/reset.
            self.cleanup_transfer(transfer_id) # Clean up old state before re-initializing


        filename = file_start.filename
        total_size = file_start.total_size
        piece_size = file_start.piece_size
        merkle_root = file_start.merkle_root if file_start.HasField("merkle_root") else None
        piece_hashes = list(file_start.piece_hashes)

        if piece_size == 0 and total_size > 0:
             print(f"Error: Received FILE_START with piece_size=0 but total_size>0 from {sender_id}. Aborting transfer.")
             return
        elif piece_size == 0 and total_size == 0:
             num_pieces = 0 # Handle empty file case
        elif piece_size > 0:
             num_pieces = (total_size + piece_size - 1) // piece_size
        else:
             print(f"Error: Received FILE_START with invalid piece_size ({piece_size}) from {sender_id}. Aborting transfer.")
             return


        print(f"[Receiver] Received FILE_START from {sender_id} {'(Broadcast)' if is_broadcast else ''}")
        print(f"  File: '{filename}', Size: {total_size}, Pieces: {num_pieces}, Piece Size: {piece_size}")
        if merkle_root:
            print(f"  Merkle Root: {merkle_root[:10]}...")
        elif piece_hashes:
            # Validate number of hashes if provided
            if len(piece_hashes) != num_pieces:
                 print(f"  Warning: Number of piece hashes ({len(piece_hashes)}) does not match calculated number of pieces ({num_pieces}).")
                 # Decide how to handle: Abort? Proceed without hash check?
                 # For now, log warning but proceed. Hash checks later will be partial.
            print(f"  Using {len(piece_hashes)} individual piece hashes.")
        else:
             # Only warn if the file is not empty
             if total_size > 0:
                 print("  Warning: No Merkle root or piece hashes provided for non-empty file.")


        # Initialize transfer state
        self.active_transfers[transfer_id] = {
            "filename": filename,
            "total_size": total_size,
            "piece_size": piece_size,
            "merkle_root": merkle_root,
            "piece_hashes": piece_hashes, # Expected hashes
            "num_pieces": num_pieces,
            "received_pieces": {},       # Stores piece_index -> piece_data
            "received_hashes": {},       # Stores piece_index -> calculated_hash
            "missing_indices": set(range(num_pieces)), # Initially, all pieces are missing
            "requested_indices": set(),    # Pieces currently requested in a ResumeRequest
            "retry_count": {},           # piece_index -> number of times requested
            "is_broadcast": is_broadcast,
            "source_node": sender_id,    # Original sender ID
            "start_time": time.time(),   # Track start time
            "last_activity_time": time.time(), # Track any activity
            "transfer_complete": False,
            "failed": False,
        }
        self.last_request_time[transfer_id] = 0 # Allow immediate first request if needed

        if num_pieces == 0 and total_size == 0:
             print(f"[Receiver] Received empty file '{filename}'. Assembling immediately.")
             # Need to pass the transfer dict to the save function
             self._assemble_and_save(transfer_id, self.active_transfers[transfer_id])
        elif num_pieces > 0:
             # Don't send ResumeRequest immediately on FileStart. Wait for pieces or timeout.
             print(f"  Waiting for pieces...")


    def handle_piece_data(self, sender_id: str, piece_data: akita_pb2.PieceData, is_broadcast: bool = False):
        """Handles an incoming PieceData message."""
        transfer_id = self._get_transfer_id(sender_id, is_broadcast)

        if transfer_id not in self.active_transfers:
            # Received a piece for a transfer we don't know about.
            print(f"Warning: Received PIECE_DATA for unknown transfer_id {transfer_id} from {sender_id}. Ignoring.")
            return

        transfer = self.active_transfers[transfer_id]
        if transfer.get("transfer_complete", False) or transfer.get("failed", False):
            # print(f"Info: Received PIECE_DATA for already completed/failed transfer {transfer_id}. Ignoring.")
            return

        index = piece_data.piece_index
        data = piece_data.data
        num_pieces_total = transfer.get("num_pieces", 0)

        # --- Validate Piece Index ---
        if not (0 <= index < num_pieces_total):
            print(f"Error: Received PIECE_DATA with out-of-bounds index {index} (max: {num_pieces_total-1}) for transfer {transfer_id}. Ignoring.")
            return

        # --- Check if Already Received ---
        if index in transfer.get("received_pieces", {}):
            # print(f"Debug: Received duplicate PIECE_DATA for index {index}. Ignoring.")
            # Optionally, re-verify hash if concerned about corruption during retransmission?
            return

        # --- Store Piece and Calculate Hash ---
        print(f"  Received PIECE_DATA {index}/{num_pieces_total-1} ({len(data)} bytes) for '{transfer.get('filename', 'unknown')}'")
        if "received_pieces" not in transfer: transfer["received_pieces"] = {}
        if "received_hashes" not in transfer: transfer["received_hashes"] = {}
        transfer["received_pieces"][index] = data
        transfer["received_hashes"][index] = calculate_hash(data)
        transfer["last_activity_time"] = time.time()

        # --- Update State Tracking ---
        if "missing_indices" not in transfer: transfer["missing_indices"] = set(range(num_pieces_total))
        if "requested_indices" not in transfer: transfer["requested_indices"] = set()

        transfer["missing_indices"].discard(index)
        transfer["requested_indices"].discard(index) # No longer waiting for this specific request
        if index in transfer.get("retry_count", {}):
            del transfer["retry_count"][index] # Reset retry count on successful receipt


        # --- Check if Complete ---
        # Check completion immediately after receiving a piece
        self._check_and_assemble(transfer_id)


    def _check_for_missing_or_corrupt(self, transfer_id: str) -> Set[int]:
        """
        Identifies pieces that are missing or have hash mismatches based on current state.
        Also handles retry limits.

        Returns:
            A set of indices that need to be requested. Returns empty set if transfer is complete/failed.
        """
        if transfer_id not in self.active_transfers:
            return set()

        transfer = self.active_transfers[transfer_id]
        if transfer.get("transfer_complete", False) or transfer.get("failed", False):
            return set()

        num_pieces_total = transfer.get("num_pieces", 0)
        received_pieces_keys = set(transfer.get("received_pieces", {}).keys())
        needs_request: Set[int] = set()

        # 1. Identify pieces never received
        currently_missing = set(range(num_pieces_total)) - received_pieces_keys
        needs_request.update(currently_missing)

        # 2. Check for hash mismatches (only if individual hashes were provided)
        #    This check is more reliably done when *all* pieces are thought to be received,
        #    but we can do a preliminary check here if desired. Let's focus this check
        #    in the _check_and_assemble verification step for simplicity.
        #    If a hash mismatch is found there, it will add the index back to missing_indices.

        # 3. Handle Retry Limits for pieces we know are missing
        failed_pieces: Set[int] = set()
        retry_counts = transfer.get("retry_count", {})
        # Check retries only for pieces currently considered missing
        check_retries_for = needs_request.copy()

        for index in check_retries_for:
            retries = retry_counts.get(index, 0)
            # Note: Retry count is incremented when *sending* the request.
            # So, if count is already >= max_retries, it means we've requested it max times.
            if retries >= self.max_retries:
                print(f"[Receiver] Reached max retries ({self.max_retries}) for piece {index} of '{transfer.get('filename', 'unknown')}'. Marking transfer as failed.")
                transfer["failed"] = True
                failed_pieces.add(index)
                needs_request.discard(index) # Give up requesting this piece

        if transfer.get("failed", False):
             print(f"Transfer {transfer_id} failed due to max retries reached for pieces: {failed_pieces}")
             self.cleanup_transfer(transfer_id) # Clean up immediately on failure
             return set() # Don't request anything if failed

        return needs_request


    def _send_resume_request(self, transfer_id: str, missing_indices_set: Set[int]):
        """Constructs and sends a ResumeRequest message."""
        if transfer_id not in self.active_transfers:
            return
        transfer = self.active_transfers[transfer_id]

        # Don't send requests for broadcasts or completed/failed transfers
        if transfer.get("is_broadcast", False) or \
           transfer.get("transfer_complete", False) or \
           transfer.get("failed", False):
            return

        if not missing_indices_set:
            # print("Debug: _send_resume_request called with empty missing_indices_set.")
            return

        sender_id = transfer.get("source_node")
        if not sender_id:
             print(f"Error: Cannot send ResumeRequest for {transfer_id}, source_node unknown.")
             return

        missing_indices = sorted(list(missing_indices_set))

        # Acknowledge all pieces successfully received *and* hash-verified so far
        # For simplicity and robustness, let's ACK all currently held pieces.
        # The sender can re-verify if needed.
        acknowledged_indices = sorted(list(transfer.get("received_pieces", {}).keys()))

        print(f"[Receiver] Sending RESUME_REQUEST to {sender_id} for transfer '{transfer.get('filename', 'unknown')}'")
        print(f"  Requesting pieces: {missing_indices}")
        # print(f"  Acknowledging pieces: {acknowledged_indices}") # Can be verbose

        # --- Construct and Send ---
        resume_request_proto = akita_pb2.ResumeRequest(
            missing_indices=missing_indices,
            acknowledged_indices=acknowledged_indices
        )
        akita_message = akita_pb2.AkitaMessage()
        akita_message.resume_request.CopyFrom(resume_request_proto)
        payload = akita_message.SerializeToString()

        try:
            self.send(sender_id, payload, AKITA_CONTENT_TYPE)
            # Mark these pieces as requested and update retry counts
            current_time = time.time()
            if "requested_indices" not in transfer: transfer["requested_indices"] = set()
            if "retry_count" not in transfer: transfer["retry_count"] = {}
            for index in missing_indices:
                transfer["requested_indices"].add(index)
                # Increment retry count *when sending the request*
                transfer["retry_count"][index] = transfer["retry_count"].get(index, 0) + 1
            self.last_request_time[transfer_id] = current_time

        except Exception as e:
            print(f"Error sending RESUME_REQUEST via callback: {e}")


    def _calculate_merkle_root(self, num_pieces: int, received_hashes: Dict[int, str]) -> Optional[str]:
        """Calculates the Merkle root from the received pieces' hashes."""
        if num_pieces == 0:
             return calculate_hash(b'')

        # Ensure we have hashes for all pieces in the correct order
        hashes_in_order: List[Optional[str]] = [received_hashes.get(i) for i in range(num_pieces)]

        # If any hash is missing, cannot calculate the root reliably
        if None in hashes_in_order:
            print("  Cannot calculate Merkle root: Not all piece hashes are available.")
            return None

        # Proceed with calculation if all hashes are present
        valid_hashes: List[str] = [h for h in hashes_in_order if h is not None] # Should be all now
        if len(valid_hashes) != num_pieces: # Sanity check
             print("  Cannot calculate Merkle root: Mismatch between valid hashes and num_pieces.")
             return None

        # Convert hex strings to bytes for hashing
        try:
            tree: List[bytes] = [bytes.fromhex(h) for h in valid_hashes]
        except ValueError as e:
             print(f"  Error decoding hex hash during Merkle calculation: {e}")
             return None


        while len(tree) > 1:
            next_level: List[bytes] = []
            for i in range(0, len(tree), 2):
                left = tree[i]
                right = tree[i + 1] if i + 1 < len(tree) else left # Duplicate last if odd
                combined_hash = hashlib.sha256(left + right).digest()
                next_level.append(combined_hash)
            tree = next_level

        return tree[0].hex() if tree else None


    def _assemble_and_save(self, transfer_id: str, transfer: Dict[str, Any]):
        """Assembles the received pieces and calls the save callback."""
        if transfer.get("transfer_complete", False) or transfer.get("failed", False):
             return # Already done or failed

        filename = transfer.get("filename", "unknown_file")
        num_pieces = transfer.get("num_pieces", 0)
        total_size = transfer.get("total_size", 0)
        received_pieces = transfer.get("received_pieces", {})

        print(f"[Receiver] Assembling file '{filename}' ({num_pieces} pieces)...")

        # Ensure all pieces are present before assembling
        if len(received_pieces) != num_pieces:
             print(f"Error: Cannot assemble '{filename}', expected {num_pieces} pieces, got {len(received_pieces)}.")
             # This case should ideally be caught by _check_and_assemble before calling this
             transfer["failed"] = True
             self.cleanup_transfer(transfer_id)
             return


        # Assemble data in correct order
        full_data_list: List[bytes] = []
        current_size = 0
        try:
            for i in range(num_pieces):
                piece_data = received_pieces.get(i)
                if piece_data is None:
                     # This should not happen if the check above passed
                     raise ValueError(f"Assembly error: Missing piece data for index {i}")
                full_data_list.append(piece_data)
                current_size += len(piece_data)

            full_data = b"".join(full_data_list)

            # Final size check
            if current_size != total_size:
                 # This is a significant issue, likely indicating corruption or protocol error
                 print(f"CRITICAL ERROR: Assembled file size ({current_size}) does not match expected size ({total_size}) for '{filename}'. Discarding file.")
                 transfer["failed"] = True
                 self.cleanup_transfer(transfer_id)
                 return # Do not save corrupt file

            # Call the user-provided save function
            self.save(filename, full_data)

            transfer["transfer_complete"] = True
            print(f"File '{filename}' assembly complete and saved.")

        except Exception as e:
            print(f"Error during file assembly or saving for '{filename}': {e}")
            transfer["failed"] = True # Mark as failed if assembly/save fails

        finally:
            # Clean up the transfer state after completion or failure attempt
            # Cleanup happens within this function or if explicitly marked failed earlier
            if transfer.get("transfer_complete", False) or transfer.get("failed", False):
                 self.cleanup_transfer(transfer_id)


    def _check_and_assemble(self, transfer_id: str):
        """
        Checks if a transfer is complete and verified. If so, assembles it.
        If not complete, determines if a ResumeRequest should be sent (called by periodic check).
        This function primarily focuses on the completion check after receiving a piece.
        """
        if transfer_id not in self.active_transfers:
            return
        transfer = self.active_transfers[transfer_id]

        if transfer.get("transfer_complete", False) or transfer.get("failed", False):
            return

        num_pieces = transfer.get("num_pieces", 0)
        received_count = len(transfer.get("received_pieces", {}))

        # --- Check if all pieces received ---
        if received_count == num_pieces:
            print(f"All {num_pieces} pieces received for '{transfer.get('filename', 'unknown')}'. Verifying integrity...")

            # --- Perform Integrity Verification ---
            verification_passed = False
            if transfer.get("merkle_root"):
                # Verify using Merkle Root
                expected_root = transfer["merkle_root"]
                calculated_root = self._calculate_merkle_root(num_pieces, transfer.get("received_hashes", {}))
                if calculated_root and calculated_root == expected_root:
                    print("  Merkle Root verification successful.")
                    verification_passed = True
                else:
                    print(f"  Merkle Root MISMATCH! Expected: {expected_root[:10]}..., Calculated: {str(calculated_root)[:10]}...")
                    # If root mismatches, assume all pieces *could* be bad. Request all again.
                    missing_set = set(range(num_pieces))
                    # Clear existing data to force re-download
                    transfer["received_pieces"] = {}
                    transfer["received_hashes"] = {}
                    transfer["missing_indices"] = missing_set
                    transfer["retry_count"] = {} # Reset retries
                    # Send request immediately upon detecting mismatch
                    self._send_resume_request(transfer_id, missing_set)
                    return # Don't assemble yet
            elif transfer.get("piece_hashes"):
                # Verify using individual piece hashes
                print("  Verifying individual piece hashes...")
                expected_hashes = transfer["piece_hashes"]
                received_hashes = transfer.get("received_hashes", {})
                all_hashes_match = True
                mismatched_indices: Set[int] = set()

                # Check if the number of expected hashes matches num_pieces for a full check
                if len(expected_hashes) != num_pieces:
                     print(f"  Warning: Number of expected hashes ({len(expected_hashes)}) differs from number of pieces ({num_pieces}). Partial verification only.")
                     # Perform check only for pieces where we have an expected hash
                     check_up_to = min(len(expected_hashes), num_pieces)
                else:
                     check_up_to = num_pieces

                for i in range(check_up_to):
                    received_hash = received_hashes.get(i)
                    expected_hash = expected_hashes[i]
                    if received_hash is None:
                         print(f"  Missing received data/hash for piece {i} during verification.")
                         all_hashes_match = False
                         mismatched_indices.add(i)
                    elif received_hash != expected_hash:
                        print(f"  Hash mismatch for piece {i}!")
                        all_hashes_match = False
                        mismatched_indices.add(i)

                if all_hashes_match and len(expected_hashes) == num_pieces :
                    print("  Individual hash verification successful.")
                    verification_passed = True
                elif all_hashes_match and len(expected_hashes) != num_pieces:
                     print("  Partial hash verification passed (hashes matched where available). Assuming OK.")
                     verification_passed = True # Risky, but proceed if hashes matched where possible
                else:
                    print(f"  Individual hash verification failed for pieces: {mismatched_indices}.")
                    # Request only the mismatched/missing pieces
                    missing_set = mismatched_indices.copy()
                    # Clear bad piece data
                    for index in mismatched_indices:
                         if index in transfer.get("received_pieces", {}): del transfer["received_pieces"][index]
                         if index in transfer.get("received_hashes", {}): del transfer["received_hashes"][index]
                    if "missing_indices" not in transfer: transfer["missing_indices"] = set()
                    transfer["missing_indices"].update(missing_set)
                    # Send request immediately
                    self._send_resume_request(transfer_id, missing_set)
                    return # Don't assemble yet
            else:
                # No hashes or Merkle root provided
                if total_size > 0: # Only warn if file expected content
                     print("  Warning: No integrity information provided. Assuming data is correct based on piece count.")
                verification_passed = True # Assemble based on piece count only

            # --- Assemble if Verification Passed ---
            if verification_passed:
                self._assemble_and_save(transfer_id, transfer)

        # --- Else (Not All Pieces Received): Do nothing here, wait for periodic check ---
        # else:
        #    pass # Wait for check_all_transfers_for_timeouts to send requests


    def check_all_transfers_for_timeouts(self):
         """
         Periodically call this method (e.g., in the main loop) to check all
         active transfers and send ResumeRequests if pieces are missing based on
         the request interval. Also checks for overall transfer inactivity.
         """
         # print("Running periodic check for all transfers...")
         current_time = time.time()
         all_transfer_ids = list(self.active_transfers.keys()) # Copy keys for safe iteration
         inactivity_timeout = 300.0 # Example: 5 minutes of no activity

         for transfer_id in all_transfer_ids:
             if transfer_id not in self.active_transfers: continue # Might have been cleaned up
             transfer = self.active_transfers[transfer_id]

             if transfer.get("transfer_complete", False) or transfer.get("failed", False):
                 continue

             # Check overall transfer inactivity timeout
             last_activity = transfer.get("last_activity_time", transfer.get("start_time", 0))
             if current_time - last_activity > inactivity_timeout:
                  print(f"Transfer {transfer_id} ('{transfer.get('filename', 'unknown')}') timed out due to inactivity ({inactivity_timeout}s). Marking as failed.")
                  transfer["failed"] = True
                  self.cleanup_transfer(transfer_id)
                  continue

             # Check if it's time to send a ResumeRequest based on interval
             # Only send if not a broadcast
             if not transfer.get("is_broadcast", False):
                 last_req = self.last_request_time.get(transfer_id, 0)
                 if current_time - last_req >= self.request_interval:
                     needed_indices = self._check_for_missing_or_corrupt(transfer_id)
                     if needed_indices:
                         print(f"Periodic Check Trigger: Requesting {len(needed_indices)} pieces for {transfer_id}")
                         self._send_resume_request(transfer_id, needed_indices)
                     else:
                         # If nothing is needed, update last_request_time anyway
                         # to reset the interval timer.
                         self.last_request_time[transfer_id] = current_time


    def cleanup_transfer(self, transfer_id: str):
        """Removes state for a completed or failed transfer."""
        if transfer_id in self.active_transfers:
            status = "completed" if self.active_transfers[transfer_id].get("transfer_complete") else "failed" if self.active_transfers[transfer_id].get("failed") else "aborted"
            filename = self.active_transfers[transfer_id].get('filename', 'unknown file')
            print(f"Cleaning up transfer state for transfer_id {transfer_id} (File: {filename}, Status: {status})")
            del self.active_transfers[transfer_id]
        if transfer_id in self.last_request_time:
            del self.last_request_time[transfer_id]

    # Potential additions:
    # - More sophisticated timeout logic per piece (requires tracking request times per piece)
    # - Explicit handling of Acknowledgement messages (if protocol uses them)
