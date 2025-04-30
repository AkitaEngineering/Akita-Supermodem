# akita_supermodem/sender.py

"""
Contains the AkitaSender class for initiating and managing file transfers.
"""

import time
import hashlib
import os
from typing import Optional, Dict, Any, List

# Use relative imports within the package
from .common import AKITA_CONTENT_TYPE, calculate_hash, DEFAULT_PIECE_SIZE
# Import generated protobuf code using relative path
# Ensure akita_pb2.py is generated in the 'generated' subdirectory
try:
    from .generated import akita_pb2
except ImportError:
    print("ERROR: Cannot import generated protobuf code (akita_pb2.py).")
    print("Please run the protoc command specified in README.md first.")
    # Optionally raise the error or exit
    raise

# Assume meshtastic library is installed
try:
    import meshtastic
    import meshtastic.serial_interface
    # Define MeshInterface type hint for clarity if meshtastic is available
    MeshInterface = meshtastic.serial_interface.SerialInterface # Or other interface types
except ImportError:
    print("Warning: meshtastic library not found. AkitaSender will not be able to send data.")
    # Define a placeholder type if meshtastic is not installed
    class MeshInterface:
        def sendData(self, *args, **kwargs):
            print("Error: meshtastic library not installed. Cannot send data.")
            pass # No-op sendData


class AkitaSender:
    """
    Manages the sending side of an Akita Supermodem file transfer over Meshtastic.
    """
    def __init__(self,
                 mesh_api: MeshInterface,
                 piece_size: int = DEFAULT_PIECE_SIZE,
                 use_merkle_root: bool = True,
                 initial_delay: float = 0.2, # Slightly increased default delay
                 min_delay: float = 0.05,
                 max_delay: float = 1.0,
                 retry_threshold: int = 3):
        """
        Initializes the AkitaSender.

        Args:
            mesh_api: An initialized Meshtastic interface object (e.g., SerialInterface).
            piece_size: The size (in bytes) to split the file into.
            use_merkle_root: If True, calculate and send a Merkle root for verification.
                             Otherwise, send individual piece hashes.
            initial_delay: Initial delay (in seconds) between sending pieces.
            min_delay: Minimum delay between pieces.
            max_delay: Maximum delay between pieces (rate control).
            retry_threshold: Number of resume requests with missing pieces before
                             increasing the send delay.
        """
        if mesh_api is None:
             raise ValueError("mesh_api cannot be None. Provide a valid Meshtastic interface.")
        self.mesh = mesh_api
        self.piece_size = piece_size
        self.use_merkle_root = use_merkle_root
        self.initial_delay = initial_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.retry_threshold = retry_threshold

        # Store active transfers, keyed by recipient_id
        self.active_transfers: Dict[str, Dict[str, Any]] = {}
        # Store send delay per recipient
        self.send_delays: Dict[str, float] = {}
        # Store retry counts per recipient (for rate control)
        self.retry_counts: Dict[str, int] = {}

        print(f"AkitaSender initialized. Piece Size: {piece_size}, Merkle Root: {use_merkle_root}")

    def start_transfer(self, recipient_id: str, filepath: str):
        """
        Starts transferring a file to the specified recipient.

        Args:
            recipient_id: The Meshtastic node ID of the recipient.
            filepath: The path to the file to send.

        Returns:
            bool: True if the transfer initiation was successful, False otherwise.
        """
        if not os.path.exists(filepath):
            print(f"Error: File not found: {filepath}")
            return False
        if not os.path.isfile(filepath):
             print(f"Error: Path is not a file: {filepath}")
             return False

        try:
            with open(filepath, "rb") as f:
                file_data = f.read()
        except Exception as e:
            print(f"Error reading file {filepath}: {e}")
            return False

        total_size = len(file_data)
        if total_size == 0:
             print(f"Warning: File is empty: {filepath}. Sending FileStart but no pieces.")
             # Allow sending empty files if desired, handle num_pieces=0 case

        # Calculate number of pieces carefully, handling zero size
        num_pieces = (total_size + self.piece_size - 1) // self.piece_size if total_size > 0 else 0

        print(f"Preparing transfer '{os.path.basename(filepath)}' ({total_size} bytes, {num_pieces} pieces) to {recipient_id}")

        piece_hashes: List[str] = []
        pieces: List[bytes] = []

        for i in range(num_pieces):
            start = i * self.piece_size
            end = min((i + 1) * self.piece_size, total_size)
            piece = file_data[start:end]
            piece_hash = calculate_hash(piece)
            piece_hashes.append(piece_hash)
            pieces.append(piece)

        # --- Construct FileStart message ---
        file_start_proto = akita_pb2.FileStart(
            filename=os.path.basename(filepath),
            total_size=total_size,
            piece_size=self.piece_size,
        )

        merkle_root: Optional[str] = None
        if self.use_merkle_root and num_pieces > 0:
            merkle_root = self._calculate_merkle_root(piece_hashes)
            if merkle_root:
                file_start_proto.merkle_root = merkle_root
                print(f"  Calculated Merkle Root: {merkle_root[:10]}...")
            else:
                 print("  Warning: Could not calculate Merkle root, sending individual hashes.")
                 file_start_proto.piece_hashes.extend(piece_hashes)
        elif num_pieces > 0:
             print("  Sending individual piece hashes.")
             file_start_proto.piece_hashes.extend(piece_hashes)
        else:
             print("  No pieces to hash (empty file).")


        # --- Wrap in AkitaMessage and Send ---
        akita_message = akita_pb2.AkitaMessage()
        akita_message.file_start.CopyFrom(file_start_proto) # Use CopyFrom for nested messages
        payload = akita_message.SerializeToString()

        print(f"Sending FILE_START to {recipient_id}...")
        try:
            # Use PortNum for Meshtastic v2+
            self.mesh.sendData(
                destinationId=recipient_id,
                payload=payload,
                portNum=AKITA_CONTENT_TYPE,
                # Optional: Set wantAck=True if you want MAC layer ACK,
                # but Akita handles reliability at the application layer.
                # wantAck=False (default) might be better for throughput.
            )
        except Exception as e:
             print(f"Error sending FILE_START via Meshtastic: {e}")
             return False


        # --- Store Transfer State ---
        self.active_transfers[recipient_id] = {
            "filepath": filepath,
            "filename": os.path.basename(filepath),
            "total_size": total_size,
            "num_pieces": num_pieces,
            "piece_size": self.piece_size,
            "pieces": pieces,
            "piece_hashes": piece_hashes, # Store hashes for potential resends
            "merkle_root": merkle_root,
            "sent_pieces": [False] * num_pieces, # Track initial send attempt
            "acknowledged_pieces": [False] * num_pieces, # Track confirmed ACKs
            "transfer_complete": False,
        }
        self.send_delays[recipient_id] = self.initial_delay
        self.retry_counts[recipient_id] = 0

        # --- Start Sending Pieces ---
        if num_pieces > 0:
            self._send_pieces(recipient_id, list(range(num_pieces))) # Send all initially
        else:
            print("File is empty, no pieces to send.")
            # Mark transfer as potentially complete if empty
            if recipient_id in self.active_transfers:
                 self.active_transfers[recipient_id]["transfer_complete"] = True


        return True


    def _calculate_merkle_root(self, hashes: List[str]) -> Optional[str]:
        """Calculates the Merkle root for a list of hex-encoded hashes."""
        if not hashes:
            return calculate_hash(b'') # Hash of empty data

        # Convert hex strings to bytes for hashing
        try:
            tree: List[bytes] = [bytes.fromhex(h) for h in hashes]
        except ValueError as e:
            print(f"Error decoding hex hash: {e}. Cannot calculate Merkle root.")
            return None


        if not tree: # Should not happen if hashes is not empty, but safety check
             return None

        while len(tree) > 1:
            next_level: List[bytes] = []
            for i in range(0, len(tree), 2):
                left = tree[i]
                # If odd number of nodes, duplicate the last one
                right = tree[i + 1] if i + 1 < len(tree) else left
                # Combine and hash
                combined_hash = hashlib.sha256(left + right).digest()
                next_level.append(combined_hash)
            tree = next_level

        # Return the final root hash as a hex string
        return tree[0].hex() if tree else None

    def _get_piece_data(self, recipient_id: str, index: int) -> Optional[bytes]:
        """Safely retrieves piece data for a given transfer and index."""
        transfer = self.active_transfers.get(recipient_id)
        if transfer and 0 <= index < transfer["num_pieces"]:
            try:
                return transfer["pieces"][index]
            except IndexError:
                 print(f"Error: Index {index} out of range for pieces list (len: {len(transfer.get('pieces', []))}) for {recipient_id}.")
                 return None
        # print(f"Warning: Could not get piece data for index {index}, recipient {recipient_id}. Transfer active: {transfer is not None}")
        return None

    def _send_pieces(self, recipient_id: str, indices_to_send: List[int]):
        """Sends the specified pieces to the recipient with rate limiting."""
        transfer = self.active_transfers.get(recipient_id)
        if not transfer or transfer.get("transfer_complete", False):
            # print(f"Debug: _send_pieces called for {recipient_id} but no active/incomplete transfer found.")
            return

        current_delay = self.send_delays.get(recipient_id, self.initial_delay)
        print(f"Sending pieces {indices_to_send} to {recipient_id} with delay {current_delay:.3f}s")

        num_pieces_total = transfer.get("num_pieces", 0)

        for i in indices_to_send:
            if not (0 <= i < num_pieces_total):
                print(f"Warning: Invalid piece index {i} requested for sending to {recipient_id}.")
                continue

            # Check if already acknowledged (no need to resend unless explicitly asked)
            # Note: The current logic sends all in indices_to_send regardless of ACK status,
            # which is correct for handling ResumeRequests.
            # if i < len(transfer["acknowledged_pieces"]) and transfer["acknowledged_pieces"][i]:
            #     continue

            piece_data = self._get_piece_data(recipient_id, i)
            if piece_data:
                piece_data_proto = akita_pb2.PieceData(piece_index=i, data=piece_data)
                akita_message = akita_pb2.AkitaMessage()
                akita_message.piece_data.CopyFrom(piece_data_proto)
                payload = akita_message.SerializeToString()

                print(f"  Sending PIECE_DATA {i}/{num_pieces_total-1} ({len(payload)} bytes)...")
                try:
                    self.mesh.sendData(
                        destinationId=recipient_id,
                        payload=payload,
                        portNum=AKITA_CONTENT_TYPE
                    )
                    # Mark as *attempted* send for initial burst
                    if i < len(transfer["sent_pieces"]) and not transfer["sent_pieces"][i]:
                         transfer["sent_pieces"][i] = True
                except Exception as e:
                     print(f"  Error sending PIECE_DATA {i} via Meshtastic: {e}")
                     # Decide if we should retry immediately or wait for ResumeRequest

                # Apply delay *after* sending each piece
                time.sleep(current_delay)
            else:
                print(f"Error: Could not retrieve data for piece {i} for recipient {recipient_id}.")

        print(f"Finished sending batch of pieces to {recipient_id}.")


    def handle_resume_request(self, sender_id: str, resume_request_proto: akita_pb2.ResumeRequest):
        """Handles a ResumeRequest from a receiver."""
        transfer = self.active_transfers.get(sender_id)
        if not transfer:
            print(f"Received RESUME_REQUEST from {sender_id} but no active transfer found for them.")
            return
        if transfer.get("transfer_complete", False):
             print(f"Received RESUME_REQUEST from {sender_id} for an already completed transfer.")
             # Optionally send a confirmation or ignore
             return


        missing_indices = sorted(list(set(resume_request_proto.missing_indices))) # Ensure unique and sorted
        acknowledged_indices = resume_request_proto.acknowledged_indices
        num_pieces_total = transfer.get("num_pieces", 0)

        print(f"[Sender] Received RESUME_REQUEST from {sender_id}:")
        print(f"  ACKed Indices: {list(acknowledged_indices)}")
        print(f"  Missing Indices: {missing_indices}")

        # --- Update Acknowledged Status ---
        all_acked = True
        acked_count = 0
        if "acknowledged_pieces" not in transfer or len(transfer["acknowledged_pieces"]) != num_pieces_total:
             transfer["acknowledged_pieces"] = [False] * num_pieces_total # Initialize if needed

        for index in range(num_pieces_total):
            if index in acknowledged_indices:
                if not transfer["acknowledged_pieces"][index]:
                    # print(f"  Marking piece {index} as acknowledged.")
                    transfer["acknowledged_pieces"][index] = True
                acked_count += 1 # Count ACKs received in this message
            # Check overall completion status based on stored ACK state
            if not transfer["acknowledged_pieces"][index]:
                all_acked = False # Still waiting for some pieces

        print(f"  Total acknowledged (cumulative): {sum(transfer['acknowledged_pieces'])}/{num_pieces_total}")

        if all_acked and not missing_indices:
            # Check if the transfer wasn't already marked complete
            if not transfer.get("transfer_complete", False):
                print(f"[Sender] Transfer to {sender_id} successfully acknowledged as complete.")
                transfer["transfer_complete"] = True
                # Optionally trigger cleanup after a delay?
                # self.cleanup_transfer(sender_id)
            return # Nothing more to do

        # --- Adjust Rate Control based on Missing Pieces ---
        if missing_indices:
            self.retry_counts[sender_id] = self.retry_counts.get(sender_id, 0) + 1
            print(f"  Retry count for {sender_id}: {self.retry_counts[sender_id]}")
            if self.retry_counts[sender_id] >= self.retry_threshold:
                current_delay = self.send_delays.get(sender_id, self.initial_delay)
                new_delay = min(current_delay * 1.5, self.max_delay)
                if new_delay > current_delay:
                    self.send_delays[sender_id] = new_delay
                    print(f"  [Rate Control] High retry count from {sender_id}. Increasing delay to {new_delay:.3f}s")
                # Reset counter after adjusting delay
                self.retry_counts[sender_id] = 0
        else:
            # If no missing pieces were reported, maybe decrease delay slightly?
            # Or just reset the retry counter.
            self.retry_counts[sender_id] = 0
            # Optional: Decrease delay slowly if things are going well
            # current_delay = self.send_delays.get(sender_id, self.initial_delay)
            # new_delay = max(current_delay * 0.9, self.min_delay)
            # self.send_delays[sender_id] = new_delay


        # --- Resend Missing Pieces ---
        if missing_indices:
            print(f"[Sender] Resending {len(missing_indices)} missing pieces to {sender_id}.")
            # Filter out invalid indices just in case
            valid_missing_indices = [idx for idx in missing_indices if 0 <= idx < num_pieces_total]
            if len(valid_missing_indices) != len(missing_indices):
                 print(f"Warning: ResumeRequest contained invalid indices: {set(missing_indices) - set(valid_missing_indices)}")

            if valid_missing_indices:
                 self._send_pieces(sender_id, valid_missing_indices)
            else:
                 print("No valid missing pieces to resend.")
        else:
            print("[Sender] No missing pieces reported in this ResumeRequest.")

    def cleanup_transfer(self, recipient_id: str):
        """Removes state for a completed or failed transfer."""
        if recipient_id in self.active_transfers:
            filename = self.active_transfers[recipient_id].get('filename', 'unknown file')
            print(f"Cleaning up transfer state for recipient {recipient_id} (File: {filename})")
            del self.active_transfers[recipient_id]
        if recipient_id in self.send_delays:
            del self.send_delays[recipient_id]
        if recipient_id in self.retry_counts:
            del self.retry_counts[recipient_id]

    # Potential additions:
    # - Method to cancel a transfer
    # - Method to query transfer status (is_complete, progress)
    # - Method to handle transfer timeouts on the sender side
