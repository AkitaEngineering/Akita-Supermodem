# Akita Supermodem Usage Guide

This guide explains how to use the `AkitaSender` and `AkitaReceiver` classes in your Python application that interacts with a Meshtastic network.

## Prerequisites

* Ensure Akita Supermodem is installed (`pip install .` or `pip install -r requirements.txt` after cloning).
* Make sure the protobuf code is generated (`protoc ...` command from README), or use the included stub for testing.
* Have the `meshtastic` Python library installed.
* Have a configured Meshtastic device connected and accessible via the `meshtastic` library (e.g., `meshtastic.SerialInterface`).
* Configure logging in your application (see Logging section below).

## Logging Configuration

Akita Supermodem uses Python's standard `logging` module. Configure logging before using the library:

```python
import logging

# Basic configuration
logging.basicConfig(
    level=logging.INFO,  # Use DEBUG for verbose output, WARNING for less output
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Or configure specific loggers
logger = logging.getLogger('akita_supermodem')
logger.setLevel(logging.DEBUG)
```

**Log Levels:**
- `DEBUG`: Detailed information for debugging (piece-by-piece transfers)
- `INFO`: General informational messages (transfer start/complete, resume requests)
- `WARNING`: Warning messages (missing pieces, hash mismatches)
- `ERROR`: Error messages (send failures, protocol errors)
- `CRITICAL`: Critical errors (file corruption, transfer failures)

## Core Components

* **`AkitaSender(mesh_api, ...)`**: Manages sending files. Requires the Meshtastic interface object. Features memory-efficient streaming and thread-safe operation.
* **`AkitaReceiver(save_function, send_function, ...)`**: Manages receiving files. Requires callback functions for saving completed files and for sending `ResumeRequest` messages back. Automatically sanitizes filenames for security.
* **`on_receive` Callback**: A function you register with the Meshtastic interface (`mesh_api.add_on_receive(your_callback)`) to process incoming packets. This callback needs to:
    * Check if the packet's `portNum` matches `AKITA_CONTENT_TYPE`.
    * Deserialize the payload into an `akita_pb2.AkitaMessage`.
    * Route the message to the appropriate handler (`receiver.handle_file_start`, `receiver.handle_piece_data`, `sender.handle_resume_request`).

## Example Integration

```python
import meshtastic
import meshtastic.serial_interface
import time
import os
import sys
import argparse # Added for command-line arguments in example

# Import Akita components
try:
    from akita_supermodem import AkitaSender, AkitaReceiver, AKITA_CONTENT_TYPE
    from akita_supermodem.generated import akita_pb2 # Import generated protobuf code
except ImportError as e:
    print(f"Error importing Akita components: {e}. Ensure installation and protoc generation.")
    sys.exit(1)


# --- Global Variables (or manage scope appropriately) ---
mesh_interface: meshtastic.serial_interface.SerialInterface = None
sender: AkitaSender = None
receiver: AkitaReceiver = None

# --- Receiver Callbacks ---
def my_save_function(filename: str, data: bytes):
    """Saves the completed file."""
    save_dir = "downloaded_files" # Define save directory
    os.makedirs(save_dir, exist_ok=True) # Create directory if it doesn't exist

    # Filename is already sanitized by AkitaReceiver, but we can add additional uniqueness
    safe_filename = filename  # Already sanitized by receiver
    base, ext = os.path.splitext(safe_filename)
    counter = 1
    filepath = os.path.join(save_dir, safe_filename)
    while os.path.exists(filepath):
         filepath = os.path.join(save_dir, f"{base}_{counter}{ext}")
         counter += 1

    print(f"\n[SAVE] Saving received file to: {filepath}")
    try:
        with open(filepath, "wb") as f:
            f.write(data)
        print(f"[SAVE] File '{os.path.basename(filepath)}' saved successfully ({len(data)} bytes).")
    except Exception as e:
        print(f"[SAVE] Error saving file '{os.path.basename(filepath)}': {e}")

def my_send_function(node_id: str, payload: bytes, portNum: int):
    """Sends data (ResumeRequest) back via Meshtastic."""
    global mesh_interface
    if mesh_interface:
        print(f"  [SEND->Mesh] Sending {len(payload)} bytes to {node_id} on port {portNum}")
        try:
            # Ensure correct arguments for sendData based on meshtastic version
            mesh_interface.sendData(
                payload=payload,
                destinationId=node_id,
                portNum=portNum
                # Optional: wantAck=True, channelIndex=0 etc.
            )
        except Exception as e:
            print(f"  [SEND->Mesh] Error sending data: {e}")
    else:
        print("  [SEND->Mesh] Error: Mesh interface not available.")

# --- Meshtastic Packet Handler ---
def my_on_receive(packet, interface): # Matched function signature for add_on_receive
    """Processes incoming Meshtastic packets."""
    global sender, receiver # Access global instances

    # Basic check for packet structure
    if not isinstance(packet, dict):
        # print(f"Debug: Received non-dict packet: {packet}")
        return

    decoded_packet = packet.get('decoded')
    if not isinstance(decoded_packet, dict):
        # print(f"Debug: Packet has no 'decoded' dictionary: {packet}")
        return

    payload = decoded_packet.get('payload')
    portnum = decoded_packet.get('portnum')
    from_id = packet.get('from') # Node ID (e.g., !aabbccdd)

    # Check if it's an Akita message using the correct PortNum
    if payload and isinstance(payload, bytes) and portnum == AKITA_CONTENT_TYPE and from_id:
        try:
            akita_message = akita_pb2.AkitaMessage()
            akita_message.ParseFromString(payload)
            is_bcast = packet.get('to') == meshtastic.BROADCAST_ADDR # Check standard broadcast ID

            print(f"\n[AKITA RX] From: {from_id} {'(BCAST)' if is_bcast else ''}")

            if akita_message.HasField('file_start'):
                print("  Type: FileStart")
                if receiver:
                    receiver.handle_file_start(from_id, akita_message.file_start, is_bcast)
                else: print("  Receiver not initialized.")
            elif akita_message.HasField('piece_data'):
                # Avoid printing every piece
                # print("  Type: PieceData")
                if receiver:
                    receiver.handle_piece_data(from_id, akita_message.piece_data, is_bcast)
                else: print("  Receiver not initialized.")
            elif akita_message.HasField('resume_request'):
                print("  Type: ResumeRequest")
                if sender:
                    # Route to sender if this node is also sending to that source
                    sender.handle_resume_request(from_id, akita_message.resume_request)
                else: print("  Sender not initialized (cannot handle resume).")
            else:
                print("  Type: Unknown Akita Payload")

        except Exception as e:
            print(f"  Error processing Akita message from {from_id}: {e}")
            # import traceback
            # traceback.print_exc()
    # else:
        # Handle non-Akita packets if needed
        # if portnum != AKITA_CONTENT_TYPE and from_id: # Check from_id exists
        #     print(f"Received non-Akita packet on port {portnum} from {from_id}")
        pass

# --- Main Application Logic ---
def main_app():
    global mesh_interface, sender, receiver
    
    # Configure logging
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description="Run Akita Supermodem node (Send/Receive).")
    parser.add_argument("--send", metavar="FILE", help="Send the specified file.")
    parser.add_argument("--to", metavar="NODE_ID", help="Recipient Node ID (e.g., !aabbccdd) for sending.")
    parser.add_argument("--port", help="Serial port for Meshtastic device (optional, auto-detects).")
    parser.add_argument("--listen", action="store_true", help="Run in listen mode to receive files.")

    args = parser.parse_args()

    # Validate arguments
    if not args.listen and not (args.send and args.to):
        parser.error("Must specify either --listen or both --send FILE --to NODE_ID")
    if args.send and not args.to:
        parser.error("--to NODE_ID is required when using --send")
    if args.to and not args.send:
        parser.error("--send FILE is required when using --to")
    if args.send and not os.path.exists(args.send):
        parser.error(f"File not found: {args.send}")


    try:
        # 1. Connect to Meshtastic
        print("Connecting to Meshtastic...")
        # Use devPath argument which is correct for meshtastic.SerialInterface
        mesh_interface = meshtastic.serial_interface.SerialInterface(devPath=args.port)
        my_id = mesh_interface.myInfo.node_id
        print(f"Connected. My Node ID: {my_id}")

        # 2. Initialize Akita Sender and Receiver
        # Initialize both if the node might send *and* receive, even if only one mode is active now.
        # The inactive component will just sit idle.
        print("Initializing Akita components...")
        sender = AkitaSender(mesh_api=mesh_interface)
        receiver = AkitaReceiver(save_function=my_save_function, send_function=my_send_function)

        # 3. Register the receive callback
        print("Registering receive callback...")
        mesh_interface.add_on_receive(my_on_receive)
        time.sleep(2) # Allow registration and node DB population

        # 4. Perform Action (Send or Listen)
        if args.send:
            print(f"\nAttempting to send '{args.send}' to {args.to}...")
            success = sender.start_transfer(args.to, args.send)
            if success:
                print("Send initiated. Monitoring progress (requires receiver ACKs)...")
                # Keep running to handle potential ResumeRequests
                # Add a timeout mechanism for sending here if desired (e.g., check sender state)
            else:
                print("Failed to initiate send.")
            # After initiating send, fall through to the listening loop to handle ACKs/Resumes

        if args.listen or args.send: # Always listen if sending (for ACKs) or explicitly listening
            print("\nNode running. Listening for Akita messages...")
            print("Press Ctrl+C to exit.")
            while True:
                # Periodically check receiver for timeouts/needed requests
                if receiver:
                    receiver.check_all_transfers_for_timeouts()
                # Add check for sender timeout/completion here if needed
                # e.g., check sender.active_transfers[args.to].get("transfer_complete")
                time.sleep(5) # Adjust check interval as needed

    except KeyboardInterrupt:
        print("\nExiting application...")
    except meshtastic.MeshtasticError as e:
         print(f"\nMeshtastic connection error: {e}")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if mesh_interface:
            print("Closing Meshtastic connection.")
            mesh_interface.close()

if __name__ == "__main__":
    # Protobuf check (redundant if imports worked, but good practice)
    try:
         from akita_supermodem.generated import akita_pb2
    except ImportError:
         print("ERROR: Protobuf definitions not found. Run 'protoc' command first.")
         sys.exit(1)

    main_app()

## Key Considerations

### Error Handling
The examples provide basic error handling. Robust applications should implement more comprehensive checks:
- File existence and permissions
- Meshtastic connection state
- Message parsing errors
- Transfer timeout handling

### Threading/Async
Akita Supermodem is fully thread-safe and supports concurrent transfers. For more complex applications, especially GUIs or services:
- The library uses `threading.Lock` internally for thread safety
- Consider running the Meshtastic interface and Akita logic in separate threads
- The meshtastic library offers `ThreadedSerialInterface` which can help manage this
- Multiple transfers can run concurrently safely

### Memory Management
- Large files are automatically streamed in chunks (no need to load entire file into memory)
- The sender reads files piece-by-piece to minimize memory usage
- For very large files, consider adjusting `piece_size` parameter

### Security
- Filenames are automatically sanitized by the receiver to prevent path traversal attacks
- The `sanitize_filename()` function removes dangerous characters and path components
- Received files are saved with sanitized filenames only

### State Management
