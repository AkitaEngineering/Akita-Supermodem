# Production Readiness

Akita Supermodem is ready for secure bench trials and controlled field trials
for non-flight-critical file transfer. It is not yet signed off for production
UAS/UAV operations.

## Current Status

Ready now:

- Encrypted operator path through `TransferManager` for CLI and web UI.
- `uas` profile that requires `AKITA_SUPERMODEM_PSK`.
- X25519 session setup with HKDF key derivation.
- ChaCha20-Poly1305 AEAD with session and sequence associated data.
- Replay rejection for duplicate encrypted payload sequence numbers.
- Adaptive per-piece compression that preserves integrity checks over original
  bytes.
- Resume requests for missing pieces.
- Sender-side on-demand piece reads instead of whole-file buffering.
- Atomic receiver file publish through temporary `.part` files.
- Unit and fake-mesh integration tests.
- Lint and compile verification.

## Remaining Production Gates

These items remain before a production milestone:

- Hardware-in-the-loop tests using the exact radios, antennas, companion
  computer, power system, and enclosure layout.
- RF range and interference tests with measured packet loss, retry counts,
  completion rate, and transfer latency.
- Transport MTU validation for each supported radio/profile combination.
- Long-duration soak tests covering interrupted transfers, duplicate packets,
  corrupt packets, replay attempts, power loss, and receiver restarts.
- Receiver-side streaming assembly for very large payloads so completed files do
  not need to be joined fully in memory.
- Structured progress callbacks and event logs for ground-station/operator UI.
- Operational key-management procedure for PSK creation, rotation, storage, and
  revocation.
- Signed mission/artifact validation outside Supermodem before any aircraft
  software consumes received files.
- Release packaging workflow with versioned artifacts, changelog entries, and
  install/upgrade notes.
- Production runbook covering setup, health checks, expected transfer rates,
  failure modes, recovery, and log collection.

## Definition Of Done

Call the production milestone complete only when:

- All automated tests pass in CI.
- Hardware-in-the-loop tests pass on target equipment.
- A representative field trial completes with documented metrics.
- No open critical or high-severity security findings remain.
- Operator documentation covers secure setup, PSK handling, normal operation,
  and recovery from failed transfers.
- UAS/UAV deployments keep Supermodem outside the flight-control loop and treat
  received files as untrusted input.

## Recommended Next Sprint

1. Add a fake-transport fault-injection suite for loss, duplication, corruption,
   replay, and restart scenarios.
2. Add receiver-side streaming assembly with hash verification.
3. Add structured progress/event callbacks from `TransferManager`.
4. Build a hardware-in-the-loop test script for two Meshtastic devices.
5. Write the PSK/key-management runbook.
