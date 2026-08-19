import click
import logging
import os
import time
from pathlib import Path

from akita_supermodem.common import (
    AKITA_CONTENT_TYPE,
    DEFAULT_MAX_RETRIES,
    DEFAULT_PIECE_SIZE,
    MAX_PIECE_SIZE,
    MIN_PIECE_SIZE,
    publish_file,
    sanitize_filename,
)
from akita_supermodem.config import NETWORK_PROFILES, get_profile
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
    try:
        prof = get_profile(profile or settings.get("default_profile"))
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    if not rec or not rec.startswith("!"):
        raise click.ClickException("Recipient must be a Meshtastic node ID such as !aabbccdd.")
    if rec == "!ffffffff":
        raise click.ClickException(
            "Refusing to send an encrypted transfer to the broadcast node !ffffffff. "
            "Pass --recipient with a specific Meshtastic node ID."
        )
    if piece_size is not None and not MIN_PIECE_SIZE <= piece_size <= MAX_PIECE_SIZE:
        raise click.ClickException(f"piece-size must be between {MIN_PIECE_SIZE} and {MAX_PIECE_SIZE} bytes.")

    interface = _connect_mesh(port)
    try:
        manager = TransferManager(interface, save_function=lambda _name, _data: None, profile_name=prof.name)
    except ValueError as e:
        interface.close()
        raise click.ClickException(str(e)) from e
    manager.profile.piece_size = piece_size or prof.piece_size or DEFAULT_PIECE_SIZE

    def on_receive(packet, _interface):
        payload = packet.get("decoded", {}).get("payload")
        portnum = packet.get("decoded", {}).get("portnum")
        if not payload or portnum != AKITA_CONTENT_TYPE:
            return
        sender_id = packet.get("fromId") or packet.get("from")
        if not sender_id:
            return
        try:
            manager.handle_incoming_message(sender_id, payload)
        except Exception as e:
            logger.error("Failed handling incoming mesh packet: %s", e)

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
        manager.close()
        interface.close()


@cli.command()
@click.option("--port", help="Serial port or device path for the Meshtastic device.")
@click.option("--output-dir", type=click.Path(file_okay=False), default="received_files", show_default=True)
@click.option("--profile", "-p", type=click.Choice(sorted(NETWORK_PROFILES)), default=None)
@click.option("--timeout", type=float, default=300.0, show_default=True, help="Inactivity timeout in seconds.")
@click.option("--retries", type=int, default=DEFAULT_MAX_RETRIES, show_default=True)
@click.option("--interval", type=float, default=10.0, show_default=True)
def receive(port, output_dir, profile, timeout, retries, interval):
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

    def save_file_path(filename: str, source_path: str):
        safe = sanitize_filename(filename)
        target = output_path / safe
        base, ext = os.path.splitext(safe)
        counter = 1
        while target.exists():
            target = output_path / f"{base}_{counter}{ext}"
            counter += 1
        publish_file(source_path, target)
        click.echo(f"Saved {target} ({target.stat().st_size} bytes)")

    try:
        profile_name = (profile or settings.get("default_profile") or "meshtastic")
        get_profile(profile_name)
        manager = TransferManager(
            interface,
            save_function=save_file,
            profile_name=profile_name,
            save_path_function=save_file_path,
        )
    except ValueError as e:
        interface.close()
        raise click.ClickException(str(e)) from e
    manager.profile.timeout = interval
    manager.profile.max_retries = retries
    manager.profile.inactivity_timeout = timeout

    def on_receive(packet, _interface):
        payload = packet.get("decoded", {}).get("payload")
        portnum = packet.get("decoded", {}).get("portnum")
        if not payload or portnum != AKITA_CONTENT_TYPE:
            return
        sender_id = packet.get("fromId") or packet.get("from")
        if not sender_id:
            return
        try:
            manager.handle_incoming_message(sender_id, payload)
        except Exception as e:
            logger.error("Failed handling incoming mesh packet: %s", e)

    try:
        interface.add_on_receive(on_receive)
        click.echo(f"Receiving Akita transfers into {output_path.resolve()}")
        while True:
            manager.check_timeouts()
            time.sleep(5)
    except KeyboardInterrupt:
        click.echo("Receiver stopped.")
    finally:
        manager.close()
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


@cli.command()
@click.option("--out-dir", type=click.Path(file_okay=False), default=".", show_default=True)
def keygen(out_dir):
    """Generate an Ed25519 artifact-signing keypair."""
    from akita_supermodem.artifact_signing import generate_keypair

    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    private_key, public_key = generate_keypair()
    private_path = directory / "akita_ed25519.key"
    public_path = directory / "akita_ed25519.pub"
    if private_path.exists() or public_path.exists():
        raise click.ClickException(f"Refusing to overwrite keys in {directory}")
    private_path.write_bytes(private_key)
    public_path.write_bytes(public_key)
    os.chmod(private_path, 0o600)
    click.echo(f"Wrote {private_path} and {public_path}")


@cli.command()
@click.argument("filepath", type=click.Path(exists=True, dir_okay=False))
@click.option("--key", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--output", type=click.Path(dir_okay=False))
def sign(filepath, key, output):
    """Sign a file with a raw Ed25519 private key."""
    from akita_supermodem.artifact_signing import sign_file

    signature = sign_file(Path(key).read_bytes(), filepath)
    target = Path(output) if output else Path(filepath).with_suffix(Path(filepath).suffix + ".sig")
    target.write_bytes(signature)
    click.echo(f"Wrote {target} ({len(signature)} bytes)")


@cli.command()
@click.argument("filepath", type=click.Path(exists=True, dir_okay=False))
@click.option("--public-key", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--signature", type=click.Path(exists=True, dir_okay=False), required=True)
def verify(filepath, public_key, signature):
    """Verify a file against an Ed25519 signature."""
    from akita_supermodem.artifact_signing import verify_file

    if verify_file(Path(public_key).read_bytes(), filepath, Path(signature).read_bytes()):
        click.echo("Signature valid.")
        return
    raise click.ClickException("Signature verification failed.")


@cli.command()
@click.option("--sender-port", required=True, help="Serial port for the sending radio.")
@click.option("--receiver-port", required=True, help="Serial port for the receiving radio.")
@click.option("--file", "filepath", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--profile", "-p", default="uas", show_default=True)
@click.option("--timeout", type=float, default=180.0, show_default=True)
@click.option("--output-dir", type=click.Path(file_okay=False), default="hitl_received", show_default=True)
def hitl(sender_port, receiver_port, filepath, profile, timeout, output_dir):
    """Hardware-in-the-loop transfer between two local Meshtastic devices."""
    from akita_supermodem.artifact_signing import generate_keypair, sign_file, verify_file
    from akita_supermodem.common import calculate_hash, crc32c_file

    try:
        get_profile(profile)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    received = {}

    def save_file(filename: str, data: bytes):
        safe = sanitize_filename(filename)
        target = output_path / safe
        target.write_bytes(data)
        received[safe] = target

    def save_file_path(filename: str, source_path: str):
        safe = sanitize_filename(filename)
        target = output_path / safe
        publish_file(source_path, target)
        received[safe] = target

    sender_iface = _connect_mesh(sender_port)
    receiver_iface = _connect_mesh(receiver_port)
    sender = receiver = None
    try:
        sender = TransferManager(sender_iface, save_function=lambda _n, _d: None, profile_name=profile)
        receiver = TransferManager(
            receiver_iface,
            save_function=save_file,
            save_path_function=save_file_path,
            profile_name=profile,
        )

        def on_receive(manager):
            def _handler(packet, _interface):
                payload = packet.get("decoded", {}).get("payload")
                portnum = packet.get("decoded", {}).get("portnum")
                if not payload or portnum != AKITA_CONTENT_TYPE:
                    return
                sender_id = packet.get("fromId") or packet.get("from")
                if sender_id:
                    manager.handle_incoming_message(sender_id, payload)

            return _handler

        sender_iface.add_on_receive(on_receive(sender))
        receiver_iface.add_on_receive(on_receive(receiver))

        source = Path(filepath)
        click.echo(f"HITL send {source.name} ({source.stat().st_size} bytes) profile={profile}")
        sender.start_transfer(_local_node_id(receiver_iface), str(source))
        started = time.time()
        while time.time() - started < timeout:
            sender.check_timeouts()
            receiver.check_timeouts()
            sender_states = sender.get_status()
            receiver_states = receiver.get_status()
            if any(state.get("failed") for state in sender_states + receiver_states):
                failed = next(state for state in sender_states + receiver_states if state.get("failed"))
                raise click.ClickException(f"HITL transfer failed: {failed.get('error')}")
            if any(state.get("complete") for state in receiver_states) and received:
                break
            time.sleep(0.25)
        else:
            raise click.ClickException(f"HITL transfer did not finish within {timeout:.0f}s.")

        saved = next(iter(received.values()))
        source_hash = calculate_hash(source.read_bytes())
        dest_hash = calculate_hash(saved.read_bytes())
        if source_hash != dest_hash or crc32c_file(source) != crc32c_file(saved):
            raise click.ClickException("HITL integrity mismatch after transfer.")
        private_key, public_key = generate_keypair()
        signature = sign_file(private_key, saved)
        if not verify_file(public_key, saved, signature):
            raise click.ClickException("HITL artifact signature check failed.")
        click.echo(f"HITL passed: {saved} sha256={dest_hash} crc32c={crc32c_file(saved):08x}")
    finally:
        if sender:
            sender.close()
        if receiver:
            receiver.close()
        sender_iface.close()
        receiver_iface.close()


def _local_node_id(interface) -> str:
    my_info = getattr(interface, "myInfo", None)
    if my_info is not None:
        user = getattr(my_info, "user", None)
        node_id = getattr(user, "id", None) if user is not None else None
        if node_id:
            return str(node_id)
    raise click.ClickException("Unable to read the receiver radio node ID from Meshtastic.")


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
