# Akita Supermodem Usage Guide

Akita Supermodem ships two production entry points:

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
- `--profile meshtastic|lora|bluetooth|wifi` applies the configured packet size and timing profile.
- `--piece-size 128` overrides the selected profile's piece size for a send.
- `--timeout 300` controls how long the sender waits for completion acknowledgement.

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

For direct integration, create an `AkitaSender` for outbound transfers and an `AkitaReceiver` for inbound transfers. Route Meshtastic packets with `AKITA_CONTENT_TYPE` to the appropriate handler:

```python
from akita_supermodem.common import AKITA_CONTENT_TYPE
from akita_supermodem.generated import akita_pb2
from akita_supermodem.receiver import AkitaReceiver
from akita_supermodem.sender import AkitaSender

sender = AkitaSender(mesh_api=mesh_interface)
receiver = AkitaReceiver(save_function=save_file, send_function=send_data)


def on_receive(packet, interface):
    payload = packet.get("decoded", {}).get("payload")
    portnum = packet.get("decoded", {}).get("portnum")
    if not payload or portnum != AKITA_CONTENT_TYPE:
        return

    message = akita_pb2.AkitaMessage()
    message.ParseFromString(payload)
    sender_id = packet.get("fromId") or packet.get("from")
    is_broadcast = False

    if message.HasField("file_start"):
        receiver.handle_file_start(sender_id, message.file_start, is_broadcast)
    elif message.HasField("piece_data"):
        receiver.handle_piece_data(sender_id, message.piece_data, is_broadcast)
    elif message.HasField("resume_request"):
        sender.handle_resume_request(sender_id, message.resume_request)
```

Configure logging in the host application:

```python
import logging

logging.basicConfig(level=logging.INFO)
```

## Security And Reliability

- Filenames are sanitized before saving to prevent path traversal.
- Piece hashes and Merkle roots are verified before assembly.
- Missing or corrupt pieces are requested again until retry limits are reached.
- Sender state is protected by locks for concurrent callback access.
