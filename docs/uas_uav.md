# UAS/UAV Readiness Notes

Akita Supermodem can be useful in UAS/UAV workflows, but it should be treated as a
mission data transfer layer, not as a flight-control or command-and-control link.

## Current Readiness

Status: ready for bench trials and controlled field trials with
non-flight-critical UAS/UAV mission data.

The repository has a working chunked file-transfer protocol, integrity checks,
resume requests, Meshtastic-oriented profiles, PSK-authenticated encryption for
the `uas` profile, replay rejection for encrypted packets, opportunistic
compression, and a passing unit test suite. That is enough for bench trials and
controlled field experiments moving non-critical files.

Before production deployment around UAS/UAV systems, the project still needs
hardware-in-the-loop validation, flight-test evidence, and aircraft-specific
mission-file validation outside this library.

See [Production Readiness](production_readiness.md) for the full milestone
checklist.

## Suitable First UAS/UAV Uses

Use Supermodem first for non-flight-critical payloads:

- Pulling compressed flight logs after landing.
- Sending mission artifacts to a ground station, such as small images, CSV data,
  sensor snapshots, or health reports.
- Moving geofence, route, or payload configuration files only when the autopilot
  validates them before use.
- Recovering delayed payload data over low-bandwidth mesh links.
- Ground-to-ground relay between field operators and a base station.

Avoid using it for:

- Primary command and control.
- Real-time detect-and-avoid.
- Safety-critical telemetry required for maintaining controlled flight.
- Anything that must meet hard latency bounds.
- Direct firmware flashing without an independent signed-image verification step.

## Production Gates For UAS/UAV

These items should be complete before calling the UAS/UAV integration
production-ready:

- Operator entry points use the encrypted `TransferManager` path by default.
- The `uas` profile requires `AKITA_SUPERMODEM_PSK` so peer sessions are bound
  to a shared trust anchor.
- Encrypted payload sequence numbers are authenticated and replayed payloads are
  rejected.
- Transfer status exposes clear `pending`, `active`, `complete`, `failed`, and
  `aborted` states with machine-readable error reasons.
- Sender paths avoid whole-file buffering for large payloads.
- Compressible payloads are compressed without changing integrity checks over
  the original bytes.
- Packet sizing is validated against the actual transport MTU in use.
- Rate limiting is profile-driven and tested against the target radios.
- Receiver writes use atomic temp files and only publish verified complete files.
- Logs include session ID, peer ID, filename, byte counts, retry counts, and final
  status without leaking sensitive payload contents.
- Tests cover encrypted handshakes, corrupt packets, interrupted transfers,
  duplicate packets, replay attempts, power loss, and resumed transfers.
- Hardware-in-the-loop tests run on the target companion computer, radio, antenna
  layout, and expected RF environment.
- The aircraft software treats received files as untrusted input and performs its
  own schema, signature, bounds, and mission-safety validation.

## Recommended Architecture

For UAS/UAV deployments, keep Supermodem outside the flight-control loop.

Recommended placement:

1. Companion computer or payload controller runs Akita Supermodem.
2. Autopilot remains on its normal control and telemetry links.
3. Supermodem stores received artifacts in a staging directory.
4. A separate mission service validates staged files before handing them to any
   autopilot, payload, or analytics process.
5. Ground station displays transfer status independently from flight-critical
   telemetry.

## Near-Term Implementation Focus

The next development pass should prioritize:

- Hardware-in-the-loop tests with the exact radios and companion computers.
- Transport MTU discovery or per-radio packet-size validation.
- Streaming receiver assembly for very large payloads.
- More fault injection for replayed packets, power loss, and long RF outages.
- Add structured progress callbacks for ground-station display.

## Field Trial Checklist

Start with ground-only testing, then progress carefully:

- Bench test with fake transport and fault injection.
- Bench test with two Meshtastic devices cabled or nearby at low power.
- Ground range test with representative antennas and enclosure placement.
- Vehicle-on-ground test with the actual companion computer and power system.
- Captive or non-critical flight test moving small post-flight artifacts only.
- Expand payload size and distance only after transfer failures are understood
  and recover cleanly.
