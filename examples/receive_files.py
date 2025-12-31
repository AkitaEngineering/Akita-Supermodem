# examples/receive_files.py

"""
Example script to run the AkitaReceiver and listen for incoming files.

This script initializes a Meshtastic connection, creates an AkitaReceiver,
registers callbacks for saving files and sending ResumeRequests, and then
enters a loop, periodically checking for transfer timeouts or needed requests.
"""

import sys
import time
import argparse
import os
import logging

# Attempt to import meshtastic and Akita components
try:
    import meshtastic
    import meshtastic.serial_interface
    # Sender might not be strictly needed unless this node *also* sends files,
    # but the receiver needs a way to send ResumeRequests back.
    # from akita_supermodem.sender import AkitaSender
    from akita_supermodem.receiver import AkitaReceiver
    from akita_supermodem.common import AKITA_CONTENT_TYPE, DEFAULT_TIMEOUT, DEFAULT_MAX_RETRIES, sanitize_filename
    # Ensure generated protobuf code is available
    from akita_supermodem.generated import akita_pb2
except ImportError as e:
    print(f"Error importing required libraries: {e}")
    print("Please ensure 'meshtastic', 'protobuf' are installed")
    print("and the Akita protobuf code has been generated (run protoc).")
    print("See README.md for details.")
    sys.exit(1)


# Global instances (or manage scope appropriately)
# sender: AkitaSender = None # Only needed if this node also sends files
receiver: AkitaReceiver = None
mesh_interface: meshtastic.serial_interface.SerialInterface = None

def get_meshtastic_interface(device_port=None):
    """Connects to the Meshtastic device via Serial."""
    try:
        print(f"Connecting to Meshtastic device {'at ' + device_port if device_port else ' (default port)'}...")
        if device_port:
            interface = meshtastic.serial_interface.SerialInterface(device=device_port)
        else:
            interface = meshtastic.serial_interface.SerialInterface() # Auto-detect
        print("Connection successful.")
        # Optional: Print node info after connection stabilizes
        time.sleep(1) # Give interface time to initialize
        my_node_num = interface.myInfo.my_node_num
        my_node_id = interface.myInfo.node_id
        print(f"My Node ID: {my_node_id}, Node Num: {my_node_num}")
        return interface
    except meshtastic.MeshtasticError as e:
        print(f"Error connecting to Meshtastic device: {e}")
        print("Ensure the device is connected, powered on, and permissions are correct.")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred during Meshtastic connection: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

# --- Receiver Callbacks ---
def save_file_callback(filename: str, data: bytes):
    """Callback function passed to AkitaReceiver to save the completed file."""
    save_dir = "received_files" # Directory to save files
    if not os.path.exists(save_dir):
        try:
            os.makedirs(save_dir)
            print(f"Created directory: {save_dir}")
        except OSError as e:
             print(f"Error creating directory {save_dir}: {e}. Saving to current directory instead.")
             save_dir = "." # Fallback to current directory

    # Sanitize filename to prevent path traversal attacks
    safe_filename = sanitize_filename(filename)
    # Avoid overwriting existing files by adding a number suffix
    base, ext = os.path.splitext(safe_filename)
    counter = 1
    filepath = os.path.join(save_dir, safe_filename)
    while os.path.exists(filepath):
         filepath = os.path.join(save_dir, f"{base}_{counter}{ext}")
         counter += 1


    print(f"\n[Receiver] Attempting to save file to: {filepath}")
    try:
        with open(filepath, "wb") as f:
            f.write(data)
        print(f"[Receiver] File '{os.path.basename(filepath)}' saved successfully ({len(data)} bytes).")
    except Exception as e:
        print(f"[Receiver] Error saving file '{os.path.basename(filepath)}': {e}")

def send_data_callback(node_id: str, payload: bytes, portNum: int):
    """
    Callback function passed to AkitaReceiver, allowing it to send
    ResumeRequest messages back to the sender via the Meshtastic interface.
    """
    global mesh_interface
    if mesh_interface:
        try:
            print(f"  [Receiver->Mesh] Sending ResumeRequest ({len(payload)} bytes) to {node_id} via PortNum {portNum}")
            mesh_interface.sendData(
                destinationId=node_id,
                payload=payload,
                portNum=portNum,
                # Optional: Increase reliability for control messages?
                # wantAck=True, # Request low-level ACK for resume requests? Might slow things down.
                # channelIndex=0 # Ensure it goes out on primary channel? Or let Meshtastic decide?
            )
        except Exception as e:
            print(f"  [Receiver->Mesh] Error sending data via Meshtastic: {e}")
    else:
        print("  [Receiver->Mesh] Error: Meshtastic interface not available for sending data.")


# --- Meshtastic Packet Handling ---
def on_receive_akita(packet, interface):
    """
    Callback for Meshtastic packets. Routes Akita messages to the receiver.
    """
    global receiver # Access global receiver instance

    payload = packet.get('decoded', {}).get('payload')
    portnum = packet.get('decoded', {}).get('portnum') # Use portnum for v2+

    # Check if it's an Akita message based on PortNum
    if payload and portnum == AKITA_CONTENT_TYPE:
        try:
            akita_message = akita_pb2.AkitaMessage()
            akita_message.ParseFromString(payload)
            sender_node_id = packet['from'] # Node ID of the message sender
            sender_node_num = packet.get('fromId') # Node Num if available
            is_broadcast = packet.get('to') == meshtastic.BROADCAST_ADDR

            print(f"\n[Akita RX] Received Akita message from {sender_node_id} ({sender_node_num or 'N/A'}) {'(Broadcast)' if is_broadcast else ''}")

            if akita_message.HasField('file_start'):
                print("  Type: FileStart")
                if receiver:
                    # Route FileStart to the receiver instance
                    receiver.handle_file_start(sender_node_id, akita_message.file_start, is_broadcast)
                else:
                     print("  Error: Receiver not initialized, cannot handle FileStart.")

            elif akita_message.HasField('piece_data'):
                 # Don't print every piece data message, can be very verbose
                 # print("  Type: PieceData")
                 if receiver:
                     # Route PieceData to the receiver instance
                     receiver.handle_piece_data(sender_node_id, akita_message.piece_data, is_broadcast)
                 else:
                      print("  Error: Receiver not initialized, cannot handle PieceData.")

            elif akita_message.HasField('resume_request'):
                # Receiver script normally shouldn't receive ResumeRequests unless it was *also* sending
                print("  Type: ResumeRequest (Unexpected in basic receiver script)")
                # If this node were also a sender, you'd route this to sender.handle_resume_request

            elif akita_message.HasField('acknowledgement'):
                 print("  Type: Acknowledgement (Currently unused by default logic)")
                 pass
            else:
                 print("  Type: Unknown Akita Payload")

        except Exception as e:
            print(f"  Error processing incoming Akita message: {e}")
            # import traceback
            # traceback.print_exc() # Uncomment for detailed debugging
    # else:
        # Optional: Log other non-Akita packet types
        # try:
        #     log_msg = f"\n[Other RX] From: {packet.get('fromId', 'N/A')} To: {packet.get('toId', 'N/A')} Port: {portnum}"
        #     if packet.get('decoded', {}).get('text'):
        #          log_msg += f" Text: {packet['decoded']['text']}"
        #     print(log_msg)
        # except Exception:
        #      print("\n[Other RX] Received non-Akita packet (could not decode fully).")


def main():
    global receiver, mesh_interface # Allow modification

    parser = argparse.ArgumentParser(description="Run the Akita Supermodem receiver to listen for files over Meshtastic.")
    parser.add_argument("-p", "--port", help="Serial port or device path for Meshtastic device. Default: Auto-detect.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=f"Timeout value (currently used for inactivity check, default: {DEFAULT_TIMEOUT}s).")
    parser.add_argument("--retries", type=int, default=DEFAULT_MAX_RETRIES, help=f"Max times to request a missing piece (default: {DEFAULT_MAX_RETRIES}).")
    parser.add_argument("--interval", type=float, default=15.0, help="Seconds between periodic checks for sending missing piece requests (default: 15.0).")

    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # --- Initialize Meshtastic and Akita Receiver ---
    mesh_interface = get_meshtastic_interface(args.port)

    # Initialize Receiver, passing the callbacks
    receiver = AkitaReceiver(
        save_function=save_file_callback,
        send_function=send_data_callback, # Use the callback that sends via mesh_interface
        initial_timeout=args.timeout,     # Pass timeout value
        max_retries=args.retries,
        request_interval=args.interval
    )

    # If this node also needed to send files, initialize AkitaSender here:
    # sender = AkitaSender(mesh_api=mesh_interface)


    # --- Register Callback ---
    print("Registering receive callback...")
    # pub.subscribe(on_receive_akita, "meshtastic.receive") # Older pubsub method
    mesh_interface.add_on_receive(on_receive_akita) # Current method
    time.sleep(2) # Allow registration


    # --- Run Main Loop ---
    print("\nAkita Receiver started. Listening for incoming file transfers...")
    print(f"Received files will be saved to the '{os.path.abspath('received_files')}' directory.")
    print("Press Ctrl+C to exit.")

    try:
        while True:
            # Periodically check for transfers that might need ResumeRequests sent
            # or have timed out due to inactivity.
            if receiver:
                receiver.check_all_transfers_for_timeouts()

            # Sleep for a short duration before the next check
            time.sleep(5) # Check every 5 seconds (adjust as needed)

    except KeyboardInterrupt:
        print("\nUser interrupted. Exiting receiver script...")
    except Exception as e:
         print(f"\nAn unexpected error occurred in main loop: {e}")
         import traceback
         traceback.print_exc()
    finally:
        # Clean up any remaining receiver state? (Cleanup happens on completion/failure now)
        # if receiver:
        #     active_ids = list(receiver.active_transfers.keys())
        #     for transfer_id in active_ids:
        #          receiver.cleanup_transfer(transfer_id) # Ensure cleanup on exit

        # Close Meshtastic connection
        if mesh_interface:
            print("Closing Meshtastic connection...")
            mesh_interface.close()
        print("Receiver finished.")

if __name__ == "__main__":
    main()
