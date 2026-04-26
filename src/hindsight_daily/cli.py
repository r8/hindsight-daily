import click
from loguru import logger
from pathlib import Path
from .config import config
from .cache import cached_dates, evict, needs_sync, mark_synced
from .collector import collect
from .hindsight import delete, get_client, submit
from .parser import parse


@click.group()
@click.option("-v", "--verbose", is_flag=True, default=None)
@click.pass_context
def cli(ctx, verbose):
    if verbose is not None:
        config.set({"verbose": verbose})
    if not config["verbose"].get(bool):
        logger.remove()
        logger.add(lambda msg: click.echo(msg.strip(), err=True), level="INFO")
    ctx.obj = config


@cli.command()
@click.pass_context
def sync(ctx) -> None:
    notes_path = Path(ctx.obj["daily_notes_path"].as_filename())
    client = get_client()

    synced_dates: set[str] = set()
    for entry_date, file in collect(notes_path):
        note = parse(entry_date, file)
        synced_dates.add(str(note.date))
        if needs_sync(note):
            submit(client, note)
            mark_synced(note)
            logger.info("{} synced", note.date)
        else:
            logger.debug("{} unchanged, skipping", note.date)

    for date_str in cached_dates() - synced_dates:
        delete(client, date_str)
        evict(date_str)
        logger.info("{} deleted (note removed from vault)", date_str)
