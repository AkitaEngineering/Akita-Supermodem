# examples/send_file.py

"""
Example script to send a file using AkitaSender.

This script initializes a Meshtastic connection, creates an AkitaSender,
and an AkitaReceiver (to handle incoming ResumeRequests), starts a file
transfer, and then listens for ResumeRequests to resend missing pieces.
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
    from akita_supermodem.sender import AkitaSender
    from akita_supermodem.receiver import AkitaReceiver  # Needed to handle ACKs/Resumes
    from akita_supermodem.common import AKITA_CONTENT_TYPE, DEFAULT_PIECE_SIZE

    # Ensure generated protobuf code is available
    from akita_supermodem.generated import akita_pb2
except ImportError as e:
    print(f"Error importing required libraries: {e}")
    print("Please ensure 'meshtastic', 'protobuf' are installed")
    print("and the Akita protobuf code has been generated (run protoc).")
    print("See README.md for details.")
    sys.exit(1)


# Global instances (or manage scope appropriately in a larger application)
sender: AkitaSender = None
receiver: AkitaReceiver = None  # Need receiver logic to handle ACKs/Resumes from recipient
mesh_interface: meshtastic.serial_interface.SerialInterface = None


def get_meshtastic_interface(device_port=None):
    """Connects to the Meshtastic device via Serial."""
    try:
        print(f"Connecting to Meshtastic device {'at ' + device_port if device_port else ' (default port)'}...")
        if device_port:
            interface = meshtastic.serial_interface.SerialInterface(device=device_port)
        else:
            interface = meshtastic.serial_interface.SerialInterface()  # Auto-detect
        print("Connection successful.")
        # Optional: Print node info after connection stabilizes
        time.sleep(1)  # Give interface time to initialize
        my_node_num = interface.myInfo.my_node_num
        my_node_id = interface.myInfo.node_id
        print(f"My Node ID: {my_node_id}, Node Num: {my_node_num}")
        return interface
    except meshtastic.MeshtasticError as e:
        print(f"Error connecting to Meshtastic device: {e}")
        print(
            "Ensure the device is connected, powered on, and permissions are correct "
            "(e.g., user in 'dialout' group on Linux)."
        )
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred during Meshtastic connection: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


# --- Receiver Setup (Needed on Sender side ONLY to process ResumeRequests) ---
def dummy_save_file(filename, data):
    # The sender script doesn't save incoming files. This callback is required by
    # AkitaReceiver but should ideally never be called in this script's context.
    print(
        f"[SENDER SCRIPT WARNING] Dummy save callback invoked for file '{filename}' - "
        f"this indicates an unexpected incoming transfer."
    )
    pass


def dummy_send_data(node_id, payload, content_type):
    # The sender script's receiver logic should *not* be sending ResumeRequests itself.
    print(f"[SENDER SCRIPT WARNING] Dummy send callback invoked to node {node_id} - this should not happen.")
    pass


def on_receive_akita(packet, interface):
    """
    Callback for Meshtastic packets. Routes Akita messages.
    In this sender script, we primarily care about routing ResumeRequests
    back to our sender instance.
    """

    payload = packet.get("decoded", {}).get("payload")
    portnum = packet.get("decoded", {}).get("portnum")  # Use portnum for v2+

    # Check if it's an Akita message based on PortNum
    if payload and portnum == AKITA_CONTENT_TYPE:
        try:
            akita_message = akita_pb2.AkitaMessage()
            akita_message.ParseFromString(payload)
            sender_node_id = packet["from"]  # Node ID of the message sender
            sender_node_num = packet.get("fromId")  # Node Num if available

            print(f"\n[Akita RX] Received Akita message from {sender_node_id} ({sender_node_num or 'N/A'})")

            if akita_message.HasField("file_start"):
                # Sender script normally shouldn't receive FileStart
                print("  Type: FileStart (Unexpected in sender script)")
                # If you wanted this script to *also* receive files, you'd handle it here.

            elif akita_message.HasField("piece_data"):
                # Sender script normally shouldn't receive PieceData
                print("  Type: PieceData (Unexpected in sender script)")

            elif akita_message.HasField("resume_request"):
                print(f"  Type: ResumeRequest from {sender_node_id}")
                if sender:
                    # Route ResumeRequest to the sender instance to handle resends
                    sender.handle_resume_request(sender_node_id, akita_message.resume_request)
                else:
                    print("  Error: Sender instance not initialized, cannot handle ResumeRequest.")

            elif akita_message.HasField("acknowledgement"):
                # Handle simple ACK if implemented in the protocol later
                print("  Type: Acknowledgement (Currently unused by default logic)")
                pass
            else:
                print("  Type: Unknown Akita Payload")

        except Exception as e:
            print(f"  Error processing incoming Akita message: {e}")
            # import traceback
            # traceback.print_exc() # Uncomment for detailed debugging
    # else:
    # Optional: Log other non-Akita packet types if needed for debugging
    # try:
    #     log_msg = f"\n[Other RX] From: {packet.get('fromId', 'N/A')} To: {packet.get('toId', 'N/A')} Port: {portnum}"
    #     if packet.get('decoded', {}).get('text'):
    #          log_msg += f" Text: {packet['decoded']['text']}"
    #     print(log_msg)
    # except Exception:
    #      print("\n[Other RX] Received non-Akita packet (could not decode fully).")


def main():
    global sender, receiver, mesh_interface  # Allow modification

    parser = argparse.ArgumentParser(description="Send a file using Akita Supermodem over Meshtastic.")
    parser.add_argument("recipient_id", help="Meshtastic Node ID of the recipient (e.g., !aabbccdd).")
    parser.add_argument("filepath", help="Path to the file to send.")
    parser.add_argument(
        "-p",
        "--port",
        help="Serial port or device path for Meshtastic device (e.g., /dev/ttyUSB0, COM3). Default: Auto-detect.",
    )
    parser.add_argument(
        "--piece-size",
        type=int,
        default=DEFAULT_PIECE_SIZE,
        help=f"Size of file pieces in bytes (default: {DEFAULT_PIECE_SIZE}).",
    )
    parser.add_argument("--no-merkle", action="store_true", help="Disable Merkle root, send individual hashes instead.")
    parser.add_argument(
        "--delay", type=float, default=0.2, help="Initial delay between sending pieces (seconds, default: 0.2)."
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Overall transfer timeout in seconds (default: 300). Sender gives up if no "
             "completion ACK after this time.",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    if not args.recipient_id.startswith("!"):
        print("Warning: Recipient ID usually starts with '!', e.g., !aabbccdd. Ensure format is correct.")
    if not os.path.exists(args.filepath) or not os.path.isfile(args.filepath):
        print(f"Error: File not found or is not a file: {args.filepath}")
        sys.exit(1)

    # --- Initialize Meshtastic and Akita ---
    mesh_interface = get_meshtastic_interface(args.port)
    sender = AkitaSender(
        mesh_api=mesh_interface,
        piece_size=args.piece_size,
        use_merkle_root=(not args.no_merkle),
        initial_delay=args.delay,
    )
    # Initialize receiver stub ONLY to handle incoming ResumeRequests directed at this node
    # It uses dummy callbacks because this script isn't meant to save files or send its own requests.
    receiver = AkitaReceiver(save_function=dummy_save_file, send_function=dummy_send_data)

    # --- Register Callback ---
    print("Registering receive callback...")
    # pub.subscribe(on_receive_akita, "meshtastic.receive") # Older pubsub method
    mesh_interface.add_on_receive(on_receive_akita)  # Current method
    # Give it a moment for registration and potential initial nodeDB exchange
    time.sleep(2)

    # --- Start Transfer ---
    print(f"\nStarting transfer of '{os.path.basename(args.filepath)}' to {args.recipient_id}...")
    start_time = time.time()
    success = sender.start_transfer(args.recipient_id, args.filepath)

    if not success:
        print("Failed to initiate transfer (e.g., file error, initial send error).")
        if mesh_interface:
            mesh_interface.close()
        sys.exit(1)

    print("\nTransfer initiated. Sender is running.")
    print("Listening for ResumeRequests from the recipient to handle retransmissions.")
    print(f"Will wait up to {args.timeout} seconds for transfer completion acknowledgement.")
    print("Press Ctrl+C to exit manually.")

    transfer_complete = False
    try:
        # Keep running to allow sender to handle ResumeRequests
        while time.time() - start_time < args.timeout:
            # Check if the sender has marked the transfer as complete based on ACKs
            transfer_state = sender.active_transfers.get(args.recipient_id)
            if transfer_state and transfer_state.get("transfer_complete"):
                print(f"\n[SUCCESS] Transfer to {args.recipient_id} acknowledged as complete by sender.")
                transfer_complete = True
                break  # Exit loop once complete

            time.sleep(1)  # Main loop delay

        if not transfer_complete:
            print(f"\n[TIMEOUT] Transfer did not complete within {args.timeout} seconds.")

    except KeyboardInterrupt:
        print("\nUser interrupted. Exiting sender script...")
    except Exception as e:
        print(f"\nAn unexpected error occurred in main loop: {e}")
        import traceback

        traceback.print_exc()
    finally:
        # Clean up sender state for this transfer
        if sender:
            sender.cleanup_transfer(args.recipient_id)
        # Close Meshtastic connection
        if mesh_interface:
            print("Closing Meshtastic connection...")
            mesh_interface.close()
        print("Sender finished.")
        sys.exit(0 if transfer_complete else 1)  # Exit code 0 on success, 1 on failure/timeout


if __name__ == "__main__":
    main()
