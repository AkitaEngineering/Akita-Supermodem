# Akita Supermodem Documentation

Welcome to the documentation for Akita Supermodem.

## Overview

Akita Supermodem provides a robust file transfer mechanism suitable for low-bandwidth mesh networks like Meshtastic. It handles file segmentation, integrity checking, and retransmission of lost data.

## Key Components

* **Transfer Manager (`TransferManager`):** Secure default API used by the CLI
  and web UI. It handles key exchange, encrypted payloads, replay rejection, and
  protocol dispatch.
* **Supermodem Protocol:** Implements chunking, resume requests, integrity
  checks, adaptive compression, and send/receive state.
* **Legacy Sender/Receiver:** `AkitaSender` and `AkitaReceiver` remain available
  for compatibility, but new integrations should prefer `TransferManager`.
* **Meshtastic Integration:** Relies on a Meshtastic interface object
  (`meshtastic.SerialInterface` or similar) for network communication.
* **Logging:** Uses Python's standard `logging` module for all output. Configure
  logging levels as needed for your application.

## Getting Started

1.  **Installation:** Follow the instructions in the main [README.md](../README.md). The repository includes generated Python protobuf code; install `protoc` only if you modify `akita.proto`.
2.  **Usage:** See the [Usage Guide](usage.md) for CLI, UI, and Python integration examples.
3.  **Testing:** Run `python -m pytest tests/ -q` to verify your installation.
4.  **Logging:** Configure logging in your application to see transfer progress and debug information.

## Contents

* [Protocol Details](protocol.md)
* [Usage Guide](usage.md)
* [Production Readiness](production_readiness.md)
* [UAS/UAV Readiness Notes](uas_uav.md)
* [Examples](../examples/)
* [Improvements Summary](../IMPROVEMENTS_SUMMARY.md) - Recent enhancements and improvements

## Recent Improvements

Version 0.1.0 includes significant improvements:

* **Thread Safety:** Full thread-safe operation for concurrent transfers
* **Memory Efficiency:** Large files are streamed in chunks instead of loaded entirely into memory
* **Error Tracking:** Comprehensive error tracking and automatic failure detection
* **Authenticated Encryption:** Secure transfer path with PSK-authenticated sessions for the `uas` profile
* **Replay Resistance:** Encrypted payload sequence numbers are authenticated and rejected on replay
* **Adaptive Compression:** Compressible chunks are compressed only when it reduces payload size
* **Logging:** Professional logging system replacing print statements
* **Security:** Filename sanitization prevents path traversal attacks
* **Testing:** Comprehensive unit test suite

See [IMPROVEMENTS_SUMMARY.md](../IMPROVEMENTS_SUMMARY.md) for complete details.

