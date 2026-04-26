import click
from pathlib import Path
from .config import config
from .collector import collect
from .parser import parse


@click.group()
@click.option("-v", "--verbose", is_flag=True, default=None)
@click.pass_context
def cli(ctx, verbose):
    if verbose is not None:
        config.set({"verbose": verbose})
    ctx.obj = config


@cli.command()
@click.pass_context
def sync(ctx) -> None:
    notes_path = Path(ctx.obj["daily_notes_path"].as_filename())

    for entry_date, file in collect(notes_path):
        note = parse(entry_date, file)
        print(note)
