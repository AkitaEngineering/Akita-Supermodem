# Hardware Test Plan

This plan defines the hardware-in-the-loop work that remains outside pure code
and simulation.

## Required Equipment

- Two target radios or Meshtastic devices.
- Target companion computer or payload controller.
- Representative antennas, cabling, enclosure, and power system.
- Ground-station computer.
- Known-good test artifact set.

## Preflight Bench Test

1. Install the same package version on both endpoints.
2. Set `AKITA_SUPERMODEM_PSK` on both endpoints.
3. Confirm profile selection with `akita-supermodem config default_profile uas`.
4. Transfer a 1 KB artifact.
5. Transfer a 100 KB artifact.
6. Confirm received hashes and signatures.
7. Capture logs from both endpoints.

## RF Test Matrix

Record these metrics for each run:

- Profile and piece size.
- Distance and antenna configuration.
- Environment notes.
- File size and compressed wire bytes.
- Transfer duration.
- Missing-piece request count.
- Retry count.
- Completion or failure status.
- Operator-visible error messages.

Run at minimum:

- Near-field bench.
- Vehicle-on-ground with final enclosure and power system.
- Short outdoor range.
- Representative mission range.
- Interference scenario if legally and safely available.

## Acceptance Criteria

Before production sign-off:

- Repeated transfers complete at expected range.
- Failures are visible to operators and recover cleanly.
- No received artifact is published before verification completes.
- Logs contain enough session, peer, retry, and status detail to diagnose
  failures.
- UAS/UAV mission software validates signatures and schema before use.
