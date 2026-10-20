"""Command-line entry points."""

import functools

import typer

app = typer.Typer()


@functools.cache
def config_path() -> str:
    """Return the config path."""
    return "fixture.yaml"


@app.command("sync-all")
def sync_all(dry_run: bool = False) -> None:
    """Synchronise everything."""
    print(config_path(), dry_run)
