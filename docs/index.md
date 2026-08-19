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
* [PSK And Artifact Signing Runbook](key_management.md)
* [Hardware Test Plan](hardware_test_plan.md)
* [Release Runbook](release_runbook.md)
* [UAS/UAV Readiness Notes](uas_uav.md)
* [Examples](../examples/)
* [Change Log](../CHANGELOG.md)

## Recent Improvements

Version 0.2.1 (2026-08-19) includes:

* **CRC-32C:** Castagnoli CRC on every piece and the assembled file, plus SHA-256 Merkle checks
* **Sliding Window:** Worker-thread sender with a small in-flight window for slow, lossy radio links
* **Authenticated Encryption:** Every profile requires a 16+ byte `AKITA_SUPERMODEM_PSK`
* **Replay Window:** Duplicate and stale encrypted sequences are rejected
* **Handshake Retry:** Lost key-exchange packets are retried, then the transfer fails cleanly
* **Save Failures:** A failed publish no longer reports the transfer as complete
* **Testing and CI:** Fake-mesh integration tests plus GitHub Actions
* **Restart resume:** PSK-sealed receive checkpoints survive a receiver process crash
* **HITL:** `akita-supermodem hitl` runs a two-radio bench transfer and signs the result

See [CHANGELOG.md](../CHANGELOG.md) for the full history.

