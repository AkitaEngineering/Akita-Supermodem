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
- Receiver-side streaming staging to temporary files for the secure transfer path.
- Atomic receiver file publish through temporary `.part` files.
- Structured progress/event callbacks from `TransferManager`.
- Software MTU budget checks per profile.
- Ed25519 artifact signing helpers for downstream mission validation.
- PSK/key-management, hardware-test, and release runbooks.
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
- Production release rehearsal using the release runbook and a versioned package
  artifact.
- Operational sign-off that the PSK/key-management and artifact-signing runbooks
  are followed by the field team.

Supporting docs:

- [PSK And Artifact Signing Runbook](key_management.md)
- [Hardware Test Plan](hardware_test_plan.md)
- [Release Runbook](release_runbook.md)

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

1. Expand fake-transport fault injection for receiver restarts and long outages.
2. Build a hardware-in-the-loop test script for two Meshtastic devices.
3. Run the RF test matrix in [Hardware Test Plan](hardware_test_plan.md).
4. Rehearse packaging and rollback using [Release Runbook](release_runbook.md).
5. Validate the consuming mission service against signed artifacts.
