# Production Readiness

Akita Supermodem 0.2.1 (2026-08-19) is ready for secure bench trials and
controlled field trials for non-flight-critical file transfer. It is not yet
signed off for production UAS/UAV operations.

## Current Status

Ready now:

- Encrypted operator path through `TransferManager` for CLI and web UI.
- Every network profile requires a 16+ byte `AKITA_SUPERMODEM_PSK`.
- X25519 session setup with HKDF key derivation.
- ChaCha20-Poly1305 AEAD with session and sequence associated data.
- Sliding-window replay rejection for encrypted payload sequence numbers.
- CRC-32C on each piece and the assembled file, plus SHA-256 Merkle verification.
- Sliding-window sender on a worker thread so radio receive stays live.
- Adaptive per-piece compression that preserves integrity checks over original
  bytes.
- Selective-NAK resume requests for missing pieces, capped for small radio MTUs.
- Handshake retry and timeout, receive inactivity timeout, and max-retry failure.
- Sender-side on-demand piece reads instead of whole-file buffering.
- Receiver-side streaming staging to temporary files for the secure transfer path.
- Atomic receiver file publish through temporary `.part` files; save failures fail
  the transfer.
- Structured progress/event callbacks from `TransferManager`.
- Software MTU budget checks per profile.
- Ed25519 artifact signing helpers for downstream mission validation.
- PSK/key-management, hardware-test, and release runbooks.
- PSK-sealed receive checkpoints for process-restart resume.
- Fault-injection tests for corrupt packets, outages, receiver restart, and soak.
- `akita-supermodem hitl` for two-radio bench tests.
- Artifact keygen/sign/verify CLI.
- Unit and fake-mesh integration tests, plus GitHub Actions CI.
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

1. Run `akita-supermodem hitl` on the target radios and record the RF matrix in
   [Hardware Test Plan](hardware_test_plan.md).
2. Rehearse packaging with `scripts/package_release.sh`.
3. Point the consuming mission service at `akita-supermodem verify` before use.
