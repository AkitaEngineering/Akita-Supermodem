import click
import logging
import os
import time
from pathlib import Path

from akita_supermodem.common import (
    AKITA_CONTENT_TYPE,
    DEFAULT_MAX_RETRIES,
    DEFAULT_PIECE_SIZE,
    DEFAULT_TIMEOUT,
    MAX_PIECE_SIZE,
    MIN_PIECE_SIZE,
    sanitize_filename,
)
from akita_supermodem.config import get_profile
from akita_supermodem.settings import settings  # noqa: E402
from akita_supermodem.server import start_server  # noqa: E402
from akita_supermodem.transfer_manager import TransferManager

logger = logging.getLogger(__name__)


@click.group()
def cli():
    """Akita Supermodem - Next Generation File Transfer Utility"""
    logging.basicConfig(level=getattr(logging, settings.get("log_level", "INFO")))


@cli.command()
def ui():
    """Starts the Web UI dashboard."""
    click.echo(f"Starting Akita Supermodem UI on port {settings.get('ui_port')}...")
    start_server()


@cli.command()
@click.argument("filepath", type=click.Path(exists=True))
@click.option("--recipient", "-r", help="Recipient Node ID (e.g. !ffffffff)")
@click.option("--profile", "-p", help="Network Profile (e.g. meshtastic, wifi)")
@click.option("--port", help="Serial port or device path for the Meshtastic device.")
@click.option("--piece-size", type=int)
@click.option("--timeout", type=float, default=300.0, show_default=True)
def send(filepath, recipient, profile, port, piece_size, timeout):
    """Sends a file over the mesh network."""
    rec = recipient or settings.get("default_mesh_node")
    prof = get_profile(profile or settings.get("default_profile"))
    if not rec or not rec.startswith("!"):
        raise click.ClickException("Recipient must be a Meshtastic node ID such as !aabbccdd.")
    if piece_size is not None and not MIN_PIECE_SIZE <= piece_size <= MAX_PIECE_SIZE:
        raise click.ClickException(f"piece-size must be between {MIN_PIECE_SIZE} and {MAX_PIECE_SIZE} bytes.")

    interface = _connect_mesh(port)
    manager = TransferManager(interface, save_function=lambda _name, _data: None, profile_name=prof.name)
    manager.profile.piece_size = piece_size or prof.piece_size or DEFAULT_PIECE_SIZE

    def on_receive(packet, _interface):
        payload = packet.get("decoded", {}).get("payload")
        portnum = packet.get("decoded", {}).get("portnum")
        if not payload or portnum != AKITA_CONTENT_TYPE:
            return
        sender_id = packet.get("fromId") or packet.get("from")
        if sender_id:
            manager.handle_incoming_message(sender_id, payload)

    try:
        interface.add_on_receive(on_receive)
        manager.start_transfer(rec, filepath)
        click.echo(f"Transfer started: {Path(filepath).name} -> {rec}")
        started = time.time()
        while time.time() - started < timeout:
            manager.check_timeouts()
            states = manager.get_status()
            failed = next((state for state in states if state.get("failed")), None)
            if failed:
                raise click.ClickException(f"Transfer failed: {failed.get('error') or 'unknown error'}")
            if any(state.get("direction") == "send" and state.get("complete") for state in states):
                click.echo("Transfer acknowledged as complete.")
                return
            time.sleep(1)
        raise click.ClickException(f"Transfer was not acknowledged within {timeout:.0f} seconds.")
    finally:
        interface.close()


@cli.command()
@click.option("--port", help="Serial port or device path for the Meshtastic device.")
@click.option("--output-dir", type=click.Path(file_okay=False), default="received_files", show_default=True)
@click.option("--timeout", type=float, default=DEFAULT_TIMEOUT, show_default=True)
@click.option("--retries", type=int, default=DEFAULT_MAX_RETRIES, show_default=True)
@click.option("--interval", type=float, default=10.0, show_default=True)
def receive(port, output_dir, timeout, retries, interval):
    """Receives files over the mesh network."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    interface = _connect_mesh(port)

    def save_file(filename: str, data: bytes):
        safe = sanitize_filename(filename)
        target = output_path / safe
        base, ext = os.path.splitext(safe)
        counter = 1
        while target.exists():
            target = output_path / f"{base}_{counter}{ext}"
            counter += 1
        temp_target = target.with_name(f".{target.name}.part")
        temp_target.write_bytes(data)
        os.replace(temp_target, target)
        click.echo(f"Saved {target} ({len(data)} bytes)")

    profile_name = settings.get("default_profile")
    manager = TransferManager(interface, save_function=save_file, profile_name=profile_name)
    manager.profile.timeout = interval
    manager.profile.max_retries = retries

    def on_receive(packet, _interface):
        payload = packet.get("decoded", {}).get("payload")
        portnum = packet.get("decoded", {}).get("portnum")
        if not payload or portnum != AKITA_CONTENT_TYPE:
            return
        sender_id = packet.get("fromId") or packet.get("from")
        if not sender_id:
            return
        manager.handle_incoming_message(sender_id, payload)

    try:
        interface.add_on_receive(on_receive)
        click.echo(f"Receiving Akita transfers into {output_path.resolve()}")
        while True:
            manager.check_timeouts()
            time.sleep(5)
    except KeyboardInterrupt:
        click.echo("Receiver stopped.")
    finally:
        interface.close()


@cli.command()
@click.argument("key", required=False)
@click.argument("value", required=False)
def config(key, value):
    """View or modify configuration settings.

    If no arguments are provided, lists all settings.
    If KEY is provided, displays its value.
    If KEY and VALUE are provided, updates the setting.
    """
    if not key:
        click.echo("Current Configuration:")
        for k, v in settings.get_all().items():
            click.echo(f"  {k} = {v}")
    elif not value:
        val = settings.get(key)
        if val is not None:
            click.echo(f"{key} = {val}")
        else:
            click.echo(f"Setting '{key}' not found.")
    else:
        try:
            settings.set(key, value)
        except (KeyError, ValueError, TypeError, OSError) as e:
            raise click.ClickException(str(e)) from e
        click.echo(f"Updated: {key} = {settings.get(key)}")


def _connect_mesh(device_port=None):
    try:
        import meshtastic.serial_interface
    except ImportError as e:
        raise click.ClickException(f"Meshtastic is not installed: {e}") from e

    try:
        click.echo(f"Connecting to Meshtastic device {device_port or '(auto)'}...")
        return (
            meshtastic.serial_interface.SerialInterface(device=device_port)
            if device_port
            else meshtastic.serial_interface.SerialInterface()
        )
    except Exception as e:
        raise click.ClickException(f"Unable to connect to Meshtastic device: {e}") from e


if __name__ == "__main__":
    cli()
