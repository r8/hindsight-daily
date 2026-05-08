from collections.abc import Iterator
from datetime import date as _date
from pathlib import Path

import click
from loguru import logger

from .cache import cached_dates, evict, mark_synced, needs_sync
from .collector import collect
from .config import config
from .hindsight import delete, get_client, submit
from .parser import Note, is_empty, parse


def _iter_notes(notes_path: Path) -> Iterator[Note]:
    for entry_date, file in collect(notes_path):
        note = parse(entry_date, file)
        if is_empty(note):
            logger.debug("{} has no content sections, skipping", note.date)
        else:
            yield note


@click.group()
@click.option("-v", "--verbose", is_flag=True, default=None)
@click.pass_context
def cli(ctx: click.Context, verbose: bool | None) -> None:
    if verbose is not None:
        config.set({"verbose": verbose})
    if not config["verbose"].get(bool):
        logger.remove()
        logger.add(lambda msg: click.echo(msg.strip(), err=True), level="INFO")
    ctx.obj = config


@cli.command()
@click.option("--limit", type=int, default=None, help="Maximum number of notes to submit in one run.")
@click.pass_context
def sync(ctx: click.Context, limit: int | None) -> None:
    """Submit new and changed notes to Hindsight, remove notes deleted from the vault."""
    notes_path = Path(ctx.obj["daily_notes_path"].as_filename())

    with get_client() as client:
        synced_dates: set[str] = set()
        submitted = 0
        for note in _iter_notes(notes_path):
            synced_dates.add(str(note.date))
            if needs_sync(note):
                if limit is not None and submitted >= limit:
                    logger.debug("{} needs sync but limit reached, deferring", note.date)
                    continue
                submit(client, note)
                mark_synced(note)
                logger.info("{} synced", note.date)
                submitted += 1
            else:
                logger.debug("{} unchanged, skipping", note.date)

        for date_str in cached_dates() - synced_dates:
            delete(client, date_str)
            evict(date_str)
            logger.info("{} deleted (note removed from vault)", date_str)


@cli.command()
@click.argument("date_str", metavar="DATE")
@click.pass_context
def forget(ctx: click.Context, date_str: str) -> None:
    """Remove a note for DATE (YYYY-MM-DD) from the Hindsight server and local cache."""
    try:
        target = _date.fromisoformat(date_str)
    except ValueError as e:
        raise click.BadParameter(f"expected YYYY-MM-DD, got {date_str!r}") from e

    notes_path = Path(ctx.obj["daily_notes_path"].as_filename())
    if any(d == target for d, _ in collect(notes_path)):
        logger.warning("{} still exists in vault; next `sync` will recreate it", target)

    with get_client() as client:
        delete(client, str(target))
        evict(str(target))
    logger.info("{} forgotten", target)


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show counts of up-to-date, pending, and stale notes."""
    notes_path = Path(ctx.obj["daily_notes_path"].as_filename())
    verbose = ctx.obj["verbose"].get(bool)

    vault_dates: set[str] = set()
    pending: list[str] = []
    up_to_date: list[str] = []

    for note in _iter_notes(notes_path):
        vault_dates.add(str(note.date))
        if needs_sync(note):
            pending.append(str(note.date))
        else:
            up_to_date.append(str(note.date))

    stale = sorted(cached_dates() - vault_dates)

    click.echo(f"up to date  {len(up_to_date):>4}")
    if verbose:
        for d in up_to_date:
            click.echo(f"  {d}")
    click.echo(f"needs sync  {len(pending):>4}")
    if verbose:
        for d in pending:
            click.echo(f"  {d}")
    if stale:
        click.echo(f"stale       {len(stale):>4}  (will be deleted on next sync)")
        if verbose:
            for d in stale:
                click.echo(f"  {d}")
