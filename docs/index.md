# Akita Supermodem Documentation

Welcome to the documentation for Akita Supermodem.

## Overview

Akita Supermodem provides a robust file transfer mechanism suitable for low-bandwidth mesh networks like Meshtastic. It handles file segmentation, integrity checking, and retransmission of lost data.

## Key Components

* **Protocol:** Defines the messages exchanged between sender and receiver. See [Protocol Details](protocol.md).
* **Sender (`AkitaSender`):** Class responsible for initiating transfers and sending file pieces. Features memory-efficient streaming, error tracking, and thread-safe operation.
* **Receiver (`AkitaReceiver`):** Class responsible for receiving pieces, managing state, requesting missing data, and assembling the final file. Automatically sanitizes filenames for security.
* **Meshtastic Integration:** Relies on a Meshtastic interface object (`meshtastic.SerialInterface` or similar) for network communication.
* **Logging:** Uses Python's standard `logging` module for all output. Configure logging levels as needed for your application.

## Getting Started

1.  **Installation:** Follow the instructions in the main [README.md](../README.md). Ensure you have `protoc` installed and generate the necessary Python code from `akita.proto` (or use the included stub for testing).
2.  **Usage:** See the [Usage Guide](usage.md) for examples on how to integrate the sender and receiver into your Meshtastic application.
3.  **Testing:** Run `python -m unittest discover tests` to verify your installation.
4.  **Logging:** Configure logging in your application to see transfer progress and debug information.

## Contents

* [Protocol Details](protocol.md)
* [Usage Guide](usage.md)
* [Examples](../examples/)
* [Improvements Summary](../IMPROVEMENTS_SUMMARY.md) - Recent enhancements and improvements

## Recent Improvements

Version 0.1.0 includes significant improvements:

* **Thread Safety:** Full thread-safe operation for concurrent transfers
* **Memory Efficiency:** Large files are streamed in chunks instead of loaded entirely into memory
* **Error Tracking:** Comprehensive error tracking and automatic failure detection
* **Logging:** Professional logging system replacing print statements
* **Security:** Filename sanitization prevents path traversal attacks
* **Testing:** Comprehensive unit test suite

See [IMPROVEMENTS_SUMMARY.md](../IMPROVEMENTS_SUMMARY.md) for complete details.

