import click
import sys
from pathlib import Path

# Fix path to allow running as script directly if needed
sys.path.insert(0, str(Path(__file__).parent.parent))

from akita_supermodem.settings import settings  # noqa: E402
from akita_supermodem.server import start_server  # noqa: E402


@click.group()
def cli():
    """Akita Supermodem - Next Generation File Transfer Utility"""
    pass


@cli.command()
def ui():
    """Starts the Web UI dashboard."""
    click.echo(f"Starting Akita Supermodem UI on port {settings.get('ui_port')}...")
    start_server()


@cli.command()
@click.argument("filepath", type=click.Path(exists=True))
@click.option("--recipient", "-r", help="Recipient Node ID (e.g. !ffffffff)")
@click.option("--profile", "-p", help="Network Profile (e.g. meshtastic, wifi)")
def send(filepath, recipient, profile):
    """Sends a file over the mesh network."""
    rec = recipient or settings.get("default_mesh_node")
    prof = profile or settings.get("default_profile")

    click.echo(f"Preparing to send '{filepath}' to {rec} using profile '{prof}'...")
    click.echo("Error: Meshtastic connection not initialized in CLI mode yet.")
    # Implementation of sender logic goes here when fully integrated


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
        settings.set(key, value)
        click.echo(f"Updated: {key} = {value}")


if __name__ == "__main__":
    cli()
