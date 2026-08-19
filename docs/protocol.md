# Akita Supermodem Protocol

This document describes the Protocol Buffer messages and the communication flow used by Akita Supermodem.

## Protobuf Definition

The protocol messages are defined in `akita_supermodem/proto/akita.proto`.

```protobuf
// akita.proto contents (reference)
syntax = "proto3";

package akita; // Optional: Add a package name for better organization

// Message sent by the sender to initiate a file transfer.
message FileStart {
  // The base name of the file being sent (e.g., "image.jpg").
  string filename = 1;
  // Total size of the file in bytes.
  uint64 total_size = 2;
  // The size of each piece/chunk in bytes (except possibly the last one).
  // Must be > 0 if total_size > 0.
  uint32 piece_size = 3;
  // Optional: The root hash (hex string) of a Merkle tree built from piece hashes (SHA256).
  // Provides efficient integrity verification for the entire file.
  optional string merkle_root = 4;
  // List of SHA256 hashes (hex strings) for each piece. Used if merkle_root is not provided,
  // or for verifying individual pieces upon receipt. The number of hashes should
  // match the calculated number of pieces.
  repeated string piece_hashes = 5;
  // CRC-32C (Castagnoli) of the entire original file.
  optional uint32 file_crc32c = 6;
}

// Message carrying a single piece (chunk) of the file data.
message PieceData {
  // The zero-based index of this piece in the sequence.
  uint32 piece_index = 1;
  // The raw bytes of the file piece.
  bytes data = 2;
  // True when data is zlib-compressed.
  bool compressed = 3;
  // Original uncompressed piece size.
  uint32 original_size = 4;
  // CRC-32C of the original uncompressed piece bytes.
  optional uint32 crc32c = 5;
}

// Message sent by the receiver to the sender to request missing pieces
// and acknowledge received ones.
message ResumeRequest {
  // List of piece indices that the receiver needs (missing or corrupted).
  repeated uint32 missing_indices = 1;
  // List of piece indices that the receiver has successfully received and verified (best effort).
  // Helps the sender track progress and potentially adjust rate.
  repeated uint32 acknowledged_indices = 2;
}

// Message sent by the receiver to acknowledge receipt of a specific piece.
// Note: Currently unused in the Python implementation, acknowledgements are
// bundled within ResumeRequest. Could be used for simpler, immediate ACKs if needed.
message Acknowledgement {
  // The zero-based index of the piece being acknowledged.
  uint32 piece_index = 1;
}

message KeyExchange {
  bytes public_key = 1;
  string session_id = 2;
  ProtocolType protocol = 3;
}

message EncryptedPayload {
  string session_id = 1;
  bytes nonce = 2;
  bytes ciphertext = 3;
  uint64 sequence = 4;
}

// Wrapper message containing one of the specific Akita message types.
// This allows sending different control/data messages over the same channel (PortNum).
message AkitaMessage {
  oneof payload {
    KeyExchange key_exchange = 1;
    EncryptedPayload encrypted_payload = 2;
    FileStart file_start = 3;
    PieceData piece_data = 4;
    ResumeRequest resume_request = 5;
    Acknowledgement acknowledgement = 6;
  }
}
```
# Message Types

## AkitaMessage
A wrapper message containing one of the specific payloads below. All Akita communication uses this wrapper.

## FileStart
- Sent by the Sender to initiate a transfer.
- Contains essential metadata: `filename`, `total_size`, `piece_size`.
- Includes integrity information: either an optional `merkle_root` (SHA256 Merkle Tree root of all piece hashes) or a list of individual `piece_hashes` (SHA256). Merkle root is preferred for efficiency when available.

## PieceData
- Sent by the Sender to transmit a chunk of the file.
- Contains the zero-based `piece_index` and piece bytes.
- If `compressed` is true, `data` is zlib-compressed and `original_size` records the uncompressed size.
- `crc32c` is CRC-32C of the original uncompressed bytes. Receivers reject mismatches immediately, before SHA-256 or Merkle checks.

## EncryptedPayload
- Carries encrypted `InnerMessage` bytes.
- `sequence` is included in AEAD associated data with the session ID.
- Receivers reject duplicate or stale encrypted sequence numbers for the same session using a sliding window.

## Key Derivation And Authentication
- Peers exchange ephemeral X25519 public keys in `KeyExchange`.
- Session keys are derived with HKDF-SHA256 from the X25519 shared secret.
- When configured, `AKITA_SUPERMODEM_PSK` is used as the HKDF salt to bind the
  session to a shared trust anchor.
- HKDF info includes the protocol label, session ID, and both public keys.
- Every operator profile requires `AKITA_SUPERMODEM_PSK` of at least 16 bytes.
- Duplicate `KeyExchange` packets for an existing session are ignored or
  re-answered; they do not replace the live session.

## Compression
- Senders compress a piece only when the compressed form is smaller than the original.
- Receivers decompress with a bounded expected output size before length and hash verification.
- Integrity checks are still calculated over the original uncompressed bytes.

## ResumeRequest
- Sent by the Receiver to the Sender.
- Contains `missing_indices`: a list of pieces the receiver needs (either never received, timed out, or failed hash check).
- Contains `acknowledged_indices`: a list of pieces the receiver has successfully received and verified (if possible). This helps the sender track progress and potentially adjust sending rate.

## Acknowledgement
- A simpler ACK for a single piece.
- Supported by protocol handlers that need individual piece acknowledgement. The default sender also tracks completion through `ResumeRequest.acknowledged_indices`.

---

# Communication Flow

## Initiation (Sender -> Receiver)
1. Sender reads the file, splits it into pieces, calculates hashes (and optionally Merkle root).
2. Sender sends an `AkitaMessage` containing a `FileStart` payload to the Receiver.
3. Sender starts a worker thread and sends a sliding window of `PieceData` packets. The radio receive callback is not blocked. A profile delay is applied between pieces inside the window.

## Receiving Pieces (Receiver)
1. Receiver gets the `FileStart` message and initializes the transfer state (expected size, pieces, hashes, etc.).
2. Receiver listens for `PieceData` messages.
3. For each valid `PieceData` received:
   - Stores the piece data.
   - Calculates the hash of the received data.
   - Marks the piece index as received.

## Requesting Missing Data (Receiver -> Sender)
1. The Receiver periodically checks its state (e.g., every `request_interval` seconds or after receiving a piece).
2. It identifies missing pieces based on:
   - Indices never received.
   - Indices where the received hash doesn't match the expected hash (if individual hashes were provided in `FileStart` - checked during final verification).
   - Indices that were previously requested but haven't arrived (handled by retry limits and periodic requests).
3. If missing pieces are found and the transfer is not a broadcast:
   - The Receiver constructs an `AkitaMessage` with a `ResumeRequest` payload.
   - `missing_indices` lists the needed pieces.
   - `acknowledged_indices` lists all pieces received so far.
   - The Receiver sends this message back to the original Sender.
   - The Receiver increments retry counts for the requested pieces. If a piece exceeds `max_retries`, the transfer might be marked as failed.

## Handling Resumes (Sender)
1. Sender receives the `ResumeRequest`.
2. It updates its internal state regarding which pieces the receiver has acknowledged.
3. It identifies the `missing_indices` from the request.
4. It resends `PieceData` messages only for the indices listed in `missing_indices`.
5. **Rate Control:** If the `ResumeRequest` frequently contains missing pieces (indicating packet loss), the Sender increases the delay between sending subsequent pieces (up to `max_delay`) to potentially improve reliability. It resets a retry counter after adjusting the delay or upon receiving a request with no missing pieces.

## Completion Verification (Receiver)
1. Once the Receiver has received data for all expected piece indices (`len(received_pieces) == num_pieces`):
   - **Merkle Root Check:** If `FileStart` provided a `merkle_root`, the Receiver calculates the Merkle root from the hashes of all received pieces. If it matches the expected root, verification passes. If not, it indicates corruption, and the receiver requests all pieces again via `ResumeRequest`.
   - **Individual Hash Check:** If `FileStart` provided `piece_hashes`, the Receiver compares the calculated hash of each received piece against the corresponding expected hash. If all match, verification passes. If any mismatch, it requests the specific mismatched pieces via `ResumeRequest`.
   - **No Hashes:** If no integrity info was provided, the Receiver assumes completion once all pieces are received (less reliable).

## Assembly & Save (Receiver)
1. If verification passes, the Receiver assembles the pieces in the correct order.
2. It calls the `save_function` callback provided during initialization, passing the original filename and the assembled byte data.
3. The transfer state is cleaned up.

## Sender Completion
1. The sender knows the transfer is likely complete when it receives a `ResumeRequest` where all pieces are listed in `acknowledged_indices` and `missing_indices` is empty.
2. It marks the transfer as complete internally.

---

# Meshtastic Transport
- Akita messages (serialized `AkitaMessage` protobufs) are sent as the payload of Meshtastic `sendData` calls.
- A specific `portNum` (defined as `AKITA_CONTENT_TYPE` in the implementation) is used to distinguish Akita messages.


