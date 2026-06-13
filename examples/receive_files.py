"""Compatibility wrapper for receiving files with the Akita CLI."""

import sys

from akita_supermodem.cli import cli


if __name__ == "__main__":
    sys.argv = [sys.argv[0], "receive", *sys.argv[1:]]
    cli()
