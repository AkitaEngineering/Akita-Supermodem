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
- Protobuf stub module for testing without requiring protoc compiler

### Changed
- Replaced all `print()` statements with proper logging calls
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

### Planned
- Progress callback mechanism for UI integration
- Configuration file support
- Performance metrics and transfer speed tracking
- Integration tests for end-to-end scenarios

