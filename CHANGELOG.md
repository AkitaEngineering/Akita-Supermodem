# Changelog

All notable changes to Akita Supermodem will be documented in this file.

## [0.2.1] - 2026-08-19

### Added
- PSK-sealed receive checkpoints so a receiver process crash can resume the same session
- Fake-mesh fault injection for corrupt packets, long outages, receiver restart, and sequential soak
- `akita-supermodem hitl` hardware-in-the-loop command for two local Meshtastic devices
- `akita-supermodem keygen`, `sign`, and `verify` for Ed25519 mission artifacts
- `scripts/package_release.sh` release rehearsal

### Changed
- Damaged encrypted packets are dropped instead of failing the whole session

## [0.2.0] - 2026-08-19

### Added
- CRC-32C (Castagnoli) on every piece and on the assembled file, in addition to SHA-256 Merkle verification
- Sliding-window sender on a worker thread so the radio receive callback is never blocked
- Bounded selective-NAK resume batches sized for Meshtastic/UAS links
- Handshake retry and handshake timeout
- Bounded replay window for encrypted sequence numbers
- Inactivity timeout and max-retry failure on the secure receive path
- GitHub Actions CI for tests, lint, and compile
- `uas` profile in the web UI
- `--profile` and a working inactivity `--timeout` on `akita-supermodem receive`

### Changed
- All network profiles require `AKITA_SUPERMODEM_PSK` of at least 16 bytes
- Unknown profile names now raise instead of silently falling back to Meshtastic
- Encrypted transfers refuse the broadcast node `!ffffffff`
- Receiver publish happens only after verification; save failures mark the transfer failed
- Protobuf runtime pin is `>=7.35.1,<8.0.0` to match the checked-in generated code

### Fixed
- Duplicate `KeyExchange` packets after handshake no longer crash the initiator
- Legacy receiver deadlocks on empty files, duplicate `FileStart`, and max-retry cleanup
- Transfer status is no longer reported complete when the final save fails
- CLI receive `--timeout` and `--retries` now apply to the secure transfer path

### Security
- Authenticated encryption is mandatory on the CLI and web UI path
- Short PSKs are rejected
- Duplicate or stale encrypted sequences are rejected with a sliding window

## [0.1.0] - 2024

### Added
- Comprehensive unit test suite covering core functionality
- Thread-safe operation with `threading.Lock` for concurrent transfers
- Memory-efficient file streaming for large files
- Error tracking for send failures with automatic failure detection
- Professional logging system using Python's `logging` module
- Filename sanitization function to prevent path traversal attacks
- Checked-in generated protobuf module for runtime use without requiring protoc during installation

### Changed
- Replaced package-level stdout writes with proper logging calls
- File reading now streams in chunks instead of loading entire file into memory
- Improved error handling with better error messages and context
- Enhanced thread safety throughout sender and receiver classes
- Updated `__init__.py` to gracefully handle missing protobuf code

### Fixed
- Fixed deadlock issues in receiver when calling `_send_resume_request` while holding locks
- Fixed filename sanitization to handle edge cases (e.g., "...")
- Fixed missing import in example scripts
- Fixed undefined variable references in receiver verification code
- Improved lock management to prevent race conditions

### Security
- Added `sanitize_filename()` function to prevent path traversal attacks
- Filenames are automatically sanitized before saving received files

### Documentation
- Updated README.md with new features and testing information
- Updated usage guide with logging configuration examples
- Added IMPROVEMENTS_SUMMARY.md documenting all enhancements
- Added CHANGELOG.md for version tracking

## [Unreleased]

### Added
- Secure `TransferManager` path for CLI and web UI transfers
- `uas` network profile requiring `AKITA_SUPERMODEM_PSK`
- PSK-bound X25519/HKDF session key derivation
- ChaCha20-Poly1305 associated data binding for session IDs and encrypted payload sequence numbers
- Replay rejection for duplicate encrypted payload sequence numbers
- Adaptive per-piece compression with bounded decompression on receive
- Receiver-side streaming staging to temporary files
- Structured transfer progress/event callbacks
- Software MTU budget checks per profile
- Ed25519 artifact signing helpers
- Fake-mesh integration tests for encrypted transfer, replay rejection, wrong PSK handling, and compression
- Production readiness checklist
- UAS/UAV readiness notes
- PSK/key-management, hardware-test, and release runbooks
- `.flake8` configuration excluding checked-in generated protobuf code

### Changed
- CLI and web UI now route packets through `TransferManager` instead of the legacy plaintext sender/receiver path
- Legacy sender reads pieces on demand instead of retaining all piece bytes in memory
- Receiver save paths publish verified files through atomic `.part` renames
- Documentation now presents `TransferManager` as the default integration API

### Security
- Encrypted sessions derive keys from X25519 shared secret, optional PSK, session ID, and both public keys
- The `uas` profile refuses to start without `AKITA_SUPERMODEM_PSK`
- Decryption and key failures surface as failed session status

### Planned
- Hardware-in-the-loop test scripts for target radios
- Transport MTU validation per radio/profile

