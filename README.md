# Akita Supermodem

**Organization:** Akita Engineering
**Contact:** info@akitaengineering.com
**Website:** [www.akitaengineering.com](https://www.akitaengineering.com)

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

1.  **Prerequisites:**
    * Python 3.7+
    * `pip` (Python package installer)
    * `protoc` (Protocol Buffer Compiler) - Optional for testing, required for production. See: [Protocol Buffer Compiler Installation](https://grpc.io/docs/protoc-installation/)

2.  **Clone the repository:**
    ```bash
    git clone [https://github.com/AkitaEngineering/akita-supermodem.git](https://github.com/AkitaEngineering/akita-supermodem.git)
    cd akita-supermodem
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Generate Protobuf code (Production):**
    For production use, generate the actual protobuf code:
    ```bash
    protoc --python_out=./akita_supermodem/generated --proto_path=./akita_supermodem/proto ./akita_supermodem/proto/akita.proto
    # Create __init__.py if it doesn't exist (needed for package recognition)
    touch ./akita_supermodem/generated/__init__.py
    ```
    This creates `akita_supermodem/generated/akita_pb2.py`.
    
    **Note:** A stub protobuf module is included for testing purposes. The stub allows tests to run without requiring `protoc`, but for production use, you should generate the actual protobuf code using `protoc`.

5.  **(Optional) Install the package locally:**
    For development or making the package importable:
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

## Testing

Run the test suite to verify installation:

```bash
python -m unittest discover tests
# or
python -m unittest tests.test_common tests.test_sender tests.test_receiver -v
```

All tests should pass. The test suite includes:
- Common utility tests (hashing, filename sanitization)
- Sender functionality tests
- Receiver functionality tests

## Documentation

* [Protocol Details](docs/protocol.md)
* [Usage Guide](docs/usage.md)
* [Improvements Summary](IMPROVEMENTS_SUMMARY.md) - Details of recent enhancements

## Version History

See [CHANGELOG.md](CHANGELOG.md) for detailed version history and changes.

## Contributing

Contributions are welcome! Please fork the repository, create a feature branch, add your changes (including tests), ensure code quality, and submit a Pull Request.

**Development Guidelines:**
- Follow existing code style and conventions
- Add unit tests for new functionality
- Update documentation as needed
- Ensure all tests pass before submitting
- Use the logging module instead of print statements

## License

This project is licensed under the GPLv3 License - see the [LICENSE](LICENSE) file for details.
