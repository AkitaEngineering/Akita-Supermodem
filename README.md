# Akita Supermodem

**Organization:** Akita Engineering  
**Contact:** info@akitaengineering.com  
**Website:** [www.akitaengineering.com](https://www.akitaengineering.com)  
**Version:** 0.2.1  
**License:** GPLv3  

---

Akita Supermodem is a Python library implementing a robust file transfer protocol designed for low-bandwidth, potentially unreliable mesh networks like Meshtastic. It breaks files into pieces, uses hashing (individual or Merkle Tree) for integrity, and features a resume mechanism to handle packet loss.

## Features

* **File Segmentation:** Transfers large files by splitting them into smaller pieces.
* **Integrity Checking:** CRC-32C on every piece and the assembled file, plus SHA-256 hashes and a Merkle tree for cryptographic verification.
* **Resume Capability:** Receivers can request missing or corrupted pieces, allowing transfers to recover from interruptions.
* **Rate Control:** Sender adjusts transmission speed based on acknowledgements and retries.
* **Protocol Buffers:** Uses checked-in generated Protobuf messages for communication.
* **Meshtastic Integration:** Designed to work as a module within the Meshtastic ecosystem using a specific PortNum.
* **Memory Efficient:** Streams outbound files in chunks instead of loading entire files into memory.
* **Authenticated Encryption Path:** CLI and web UI use the encrypted `TransferManager`. Every profile requires `AKITA_SUPERMODEM_PSK` (16+ bytes).
* **Replay Resistance:** Encrypted packets carry sequence numbers bound into AEAD associated data, rejected with a sliding window.
* **Adaptive Compression:** Compressible pieces are compressed only when doing so reduces radio payload bytes.
* **Thread Safe:** Full thread-safety support for concurrent transfers.
* **Error Tracking:** Comprehensive error tracking and failure detection.
* **Logging:** Professional logging system with configurable log levels.
* **Security:** Filename sanitization prevents path traversal attacks.

## Installation

1. **Prerequisites:**
   * Python 3.10+
   * `pip` (Python package installer)
   * Meshtastic device/interface for actual usage
   * `protoc` (Protocol Buffer Compiler) - Optional, only needed when regenerating protobuf code

2. **Clone the repository:**
   ```bash
   git clone https://github.com/AkitaEngineering/akita-supermodem.git
   cd akita-supermodem
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Protobuf Code:**
   The repository includes generated protobuf code (`akita_supermodem/generated/akita_pb2.py`) for immediate use. If you need to regenerate it after modifying the protocol:
   ```bash
   protoc --python_out=./akita_supermodem/generated --proto_path=./akita_supermodem/proto ./akita_supermodem/proto/akita.proto
   ```

5. **(Optional) Install the package locally:**
   ```bash
   pip install .
   ```

## Usage

See the `examples/` directory and the [Usage Guide](docs/usage.md) for detailed integration steps.

Start the web UI:
```bash
akita-supermodem ui
```

Send and receive from the CLI:
```bash
akita-supermodem send ./file.bin --recipient !aabbccdd
akita-supermodem receive --output-dir received_files
```

Set the same high-entropy PSK on both endpoints before any send or receive:
```bash
export AKITA_SUPERMODEM_PSK="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
akita-supermodem send ./flight-log.bin --recipient !aabbccdd --profile uas
```

**Core Concepts:**

* **`TransferManager`**: Secure default API for new integrations. It handles key exchange, encrypted payloads, replay rejection, compression, status reporting, and protocol dispatch.
* **`SupermodemHandler`**: Implements the active file-transfer protocol: chunking, resume requests, integrity checks, rate control, and adaptive compression.
* **Profiles**: Network profiles tune piece size, send window, retry behavior, rate limits, encryption, and compression. All profiles require `AKITA_SUPERMODEM_PSK`.
* **Legacy APIs**: `AkitaSender` and `AkitaReceiver` remain available for compatibility, but CLI, web UI, and new integrations should use `TransferManager`.
* **Logging**: The library uses Python's `logging` module. Configure logging in your application:
  ```python
  import logging
  logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
  ```

## Code Quality

The codebase follows Python best practices with:
- Comprehensive test coverage (unit and fake-mesh integration tests)
- Linting with flake8 (120 char line limit, PEP 8 compliance)
- Type hints and documentation
- Thread-safe implementation
- Memory-efficient file handling

Run linting:
```bash
pip install flake8
flake8 akita_supermodem/ examples/ tests/ --max-line-length=120
```

## Documentation

* [Protocol Details](docs/protocol.md)
* [Usage Guide](docs/usage.md)
* [Production Readiness](docs/production_readiness.md)
* [UAS/UAV Readiness Notes](docs/uas_uav.md)
* [PSK And Artifact Signing Runbook](docs/key_management.md)
* [Hardware Test Plan](docs/hardware_test_plan.md)
* [Release Runbook](docs/release_runbook.md)
* [Change Log](CHANGELOG.md)

## Version History

See [CHANGELOG.md](CHANGELOG.md) for detailed version history and changes.

## Contributing

Contributions are welcome! Please fork the repository, create a feature branch, add your changes (including tests), ensure code quality, and submit a Pull Request.

**Development Guidelines:**
- Follow existing code style and conventions (PEP 8, 120 char line limit)
- Add unit tests for new functionality
- Update documentation as needed
- Ensure all tests pass (`python -m pytest tests/ -v`)
- Run linting (`flake8 akita_supermodem/ examples/ tests/ --max-line-length=120`)
- Use the logging module instead of print statements

## License

This project is licensed under the GPLv3 License - see the [LICENSE](LICENSE) file for details.
