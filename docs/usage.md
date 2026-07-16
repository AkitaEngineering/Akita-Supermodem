# Akita Supermodem Usage Guide

Akita Supermodem ships two supported operator entry points:

- `akita-supermodem send` and `akita-supermodem receive` for terminal workflows.
- `akita-supermodem ui` for the FastAPI web dashboard.

The Python APIs remain available for applications that need to embed transfer behavior directly.

## Install

```bash
pip install .
```

The repository includes generated protobuf code in `akita_supermodem/generated/akita_pb2.py`. Regenerate it only after changing `akita_supermodem/proto/akita.proto`.

## CLI

Send a file:

```bash
akita-supermodem send ./path/to/file.bin --recipient !aabbccdd
```

Receive files:

```bash
akita-supermodem receive --output-dir received_files
```

Useful options:

- `--port /dev/ttyUSB0` selects a Meshtastic serial device. Without it, Meshtastic auto-detection is used.
- `--profile meshtastic|lora|bluetooth|wifi|uas` applies the configured packet size and timing profile.
- `--piece-size 128` overrides the selected profile's piece size for a send.
- `--timeout 300` controls how long the sender waits for completion acknowledgement.

For UAS/UAV trials, set a shared PSK on both endpoints and use the `uas` profile:

```bash
export AKITA_SUPERMODEM_PSK="replace-with-a-high-entropy-shared-secret"
akita-supermodem send ./flight-log.bin --recipient !aabbccdd --profile uas
```

## Web UI

Start the dashboard:

```bash
akita-supermodem ui
```

Open `http://127.0.0.1:8080` by default. The UI can:

- Connect or disconnect the Meshtastic interface.
- Update validated settings.
- Start a transfer by recipient node ID and local file path.
- Display active send and receive transfer status.

## Python Integration

For new integrations, use `TransferManager`. It is the same encrypted path used
by the CLI and web UI.

```python
import os

from akita_supermodem.common import AKITA_CONTENT_TYPE
from akita_supermodem.transfer_manager import TransferManager

os.environ["AKITA_SUPERMODEM_PSK"] = "replace-with-a-high-entropy-shared-secret"


def save_file(filename: str, data: bytes) -> None:
    with open(filename, "wb") as f:
        f.write(data)


manager = TransferManager(
    mesh_api=mesh_interface,
    save_function=save_file,
    profile_name="uas",
)


def on_receive(packet, interface):
    payload = packet.get("decoded", {}).get("payload")
    portnum = packet.get("decoded", {}).get("portnum")
    if not payload or portnum != AKITA_CONTENT_TYPE:
        return

    sender_id = packet.get("fromId") or packet.get("from")
    if sender_id:
        manager.handle_incoming_message(sender_id, payload)


mesh_interface.add_on_receive(on_receive)
manager.start_transfer("!aabbccdd", "./flight-log.bin")
```

For long-running applications, call `manager.check_timeouts()` periodically and
surface `manager.get_status()` in your operator UI.

Configure logging in the host application:

```python
import logging

logging.basicConfig(level=logging.INFO)
```

## Security And Reliability

- CLI and web UI transfers use the encrypted `TransferManager` path.
- The `uas` profile requires `AKITA_SUPERMODEM_PSK` so the X25519 session is bound to a shared trust anchor.
- Session keys are derived from X25519, the PSK when configured, the session ID, and both public keys.
- Encrypted payloads include sequence numbers that are authenticated and rejected on replay.
- Compressible file pieces are compressed only when the compressed bytes are smaller than the original piece.
- Filenames are sanitized before saving to prevent path traversal.
- Completed files are written through temporary `.part` files and atomically renamed into place.
- Piece hashes and Merkle roots are verified before assembly.
- Missing or corrupt pieces are requested again until retry limits are reached.
- Sender state is protected by locks for concurrent callback access.
