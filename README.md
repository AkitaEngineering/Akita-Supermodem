# Akita Supermodem

**Organization:** Akita Engineering  
**Contact:** info@akitaengineering.com  
**Website:** [www.akitaengineering.com](https://www.akitaengineering.com)  
**Version:** 0.1.0  
**License:** GPLv3  

---

Akita Supermodem is a Python library implementing a robust file transfer protocol designed for low-bandwidth, potentially unreliable mesh networks like Meshtastic. It breaks files into pieces, uses hashing (individual or Merkle Tree) for integrity, and features a resume mechanism to handle packet loss.

## Features

* **File Segmentation:** Transfers large files by splitting them into smaller pieces.
* **Integrity Checking:** Uses SHA256 hashes for individual pieces and optional Merkle Trees for overall file verification.
* **Resume Capability:** Receivers can request missing or corrupted pieces, allowing transfers to recover from interruptions.
* **Rate Control:** Sender adjusts transmission speed based on acknowledgements and retries.
* **Protocol Buffers:** Uses efficient Protobuf messages for communication.
* **Meshtastic Integration:** Designed to work as a module within the Meshtastic ecosystem using a specific PortNum.
* **Memory Efficient:** Streams large files in chunks instead of loading entire files into memory.
* **Thread Safe:** Full thread-safety support for concurrent transfers.
* **Error Tracking:** Comprehensive error tracking and failure detection.
* **Logging:** Professional logging system with configurable log levels.
* **Security:** Filename sanitization prevents path traversal attacks.




## Installation

1. **Prerequisites:**
   * Python 3.7+
   * `pip` (Python package installer)
   * Meshtastic device/interface for actual usage
   * `protoc` (Protocol Buffer Compiler) - Optional, only needed if regenerating protobuf code

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
   The repository includes pre-generated protobuf code (`akita_supermodem/generated/akita_pb2.py`) for immediate use. If you need to regenerate it (e.g., after modifying the protocol):
   ```bash
   # Note: The proto/akita.proto file is not included in the repository
   # For regeneration, obtain the .proto file and run:
   protoc --python_out=./akita_supermodem/generated --proto_path=./proto ./proto/akita.proto
   ```

5. **(Optional) Install the package locally:**
   ```bash
   pip install .
   ```

## Usage

See the `examples/` directory and the [Usage Guide](docs/usage.md) for detailed integration steps.

**Core Concepts:**

* **`AkitaSender`**: Initiates and manages outgoing file transfers. Requires a `meshtastic` interface object. Features memory-efficient streaming, error tracking, and thread-safe operation.
* **`AkitaReceiver`**: Manages incoming transfers, requests missing pieces, and saves files. Requires callbacks for saving data and sending responses. Automatically sanitizes filenames for security.
* **Callbacks**: Your application needs an `on_receive` callback registered with Meshtastic to route incoming Akita packets (identified by `AKITA_CONTENT_TYPE` PortNum) to the correct `AkitaReceiver` or `AkitaSender` methods.
* **Logging**: The library uses Python's `logging` module. Configure logging in your application:
  ```python
  import logging
  logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
  ```

## Code Quality

The codebase follows Python best practices with:
- Comprehensive test coverage (16 tests passing)
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
* [Code Review Status](CODE_REVIEW_STATUS.md)
* [Improvements Summary](IMPROVEMENTS_SUMMARY.md)
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
