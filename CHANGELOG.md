# Changelog

All notable changes to Akita Supermodem will be documented in this file.

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
- Fake-mesh integration tests for encrypted transfer, replay rejection, wrong PSK handling, and compression
- Production readiness checklist
- UAS/UAV readiness notes
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
- Receiver-side streaming assembly for very large payloads
- Structured progress callbacks and event logs
- Transport MTU validation per radio/profile

