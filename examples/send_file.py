"""Compatibility wrapper for sending a file with the Akita CLI.

Usage:
    python examples/send_file.py RECIPIENT_ID FILEPATH [CLI_OPTIONS...]
"""

import sys

from akita_supermodem.cli import cli


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.argv = [sys.argv[0], "send", "--help"]
    else:
        recipient_id = sys.argv[1]
        filepath = sys.argv[2]
        sys.argv = [sys.argv[0], "send", filepath, "--recipient", recipient_id, *sys.argv[3:]]
    cli()
