from collections.abc import Iterator
from datetime import date as _date
from pathlib import Path
from typing import Any

import click
from loguru import logger

from .cache import cached_dates, close_cache, evict, mark_synced, needs_sync
from .collector import DuplicateNoteError, collect
from .config import Settings, SettingsError, load_settings
from .hindsight import HindsightSubmitError, delete, get_client, submit
from .parser import Note, is_empty, parse


class IsoDate(click.ParamType):
    name = "date"

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> _date:
        if isinstance(value, _date):
            return value
        try:
            return _date.fromisoformat(value)
        except ValueError:
            self.fail(f"expected YYYY-MM-DD, got {value!r}", param, ctx)


def _settings(ctx: click.Context) -> Settings:
    """Load and validate the configuration, and set up logging to match it.

    Deferred out of the group callback so `--help` still works on a broken config.
    """
    try:
        settings = load_settings(verbose_override=ctx.obj)
    except SettingsError as exc:
        raise click.UsageError(str(exc)) from exc
    if not settings.verbose:
        logger.remove()
        logger.add(lambda msg: click.echo(msg.strip(), err=True), level="INFO")
    ctx.call_on_close(close_cache)
    return settings


def _collect(notes_path: Path) -> list[tuple[_date, Path]]:
    try:
        return collect(notes_path)
    except DuplicateNoteError as exc:
        raise click.ClickException(str(exc)) from exc


def _iter_notes(notes_path: Path) -> Iterator[Note]:
    for entry_date, file in _collect(notes_path):
        note = parse(entry_date, file)
        if is_empty(note):
            logger.debug("{} has no content sections, skipping", note.date)
        else:
            yield note


@click.group()
@click.option("-v", "--verbose", is_flag=True, default=None)
@click.pass_context
def cli(ctx: click.Context, verbose: bool | None) -> None:
    ctx.obj = verbose


@cli.command()
@click.option("--limit", type=int, default=None, help="Maximum number of notes to submit in one run.")
@click.option("--date", "target", type=IsoDate(), metavar="DATE", default=None,
              help="Sync only the note for DATE (YYYY-MM-DD); skips the deletion phase.")
@click.option("--prune", is_flag=True,
              help="Allow the deletion phase to run even when the vault yields no notes at all.")
@click.pass_context
def sync(ctx: click.Context, limit: int | None, target: _date | None, prune: bool) -> None:
    """Submit new and changed notes to Hindsight, remove notes deleted from the vault."""
    settings = _settings(ctx)

    with get_client(settings) as client:
        if target is not None:
            for entry_date, file in _collect(settings.notes_path):
                if entry_date != target:
                    continue
                note = parse(entry_date, file)
                if is_empty(note):
                    logger.info("{} has no content sections, skipping", note.date)
                elif needs_sync(note):
                    try:
                        submit(client, settings, note)
                    except HindsightSubmitError as exc:
                        raise click.ClickException(str(exc)) from exc
                    mark_synced(note)
                    logger.info("{} synced", note.date)
                else:
                    logger.info("{} unchanged, skipping", note.date)
                return
            raise click.ClickException(f"no note found for {target}")

        vault_dates: set[_date] = set()
        submitted = 0
        failed = 0
        for note in _iter_notes(settings.notes_path):
            vault_dates.add(note.date)
            if needs_sync(note):
                if limit is not None and submitted >= limit:
                    logger.debug("{} needs sync but limit reached, deferring", note.date)
                    continue
                try:
                    submit(client, settings, note)
                except HindsightSubmitError as exc:
                    logger.error("{}", exc)
                    failed += 1
                    continue
                mark_synced(note)
                logger.info("{} synced", note.date)
                submitted += 1
            else:
                logger.debug("{} unchanged, skipping", note.date)

        stale_dates = cached_dates() - vault_dates
        if stale_dates and not vault_dates and not prune:
            # An unmounted vault or a mistyped path looks exactly like "every note was deleted".
            raise click.ClickException(
                f"vault has no notes but the cache holds {len(stale_dates)}; refusing to delete them. "
                f"Check {settings.notes_path}, or pass --prune if the vault really is empty."
            )

        for stale in sorted(stale_dates):
            delete(client, settings, stale)
            evict(stale)
            logger.info("{} deleted (note removed from vault)", stale)

    if failed:
        raise click.ClickException(f"{failed} note(s) failed to sync")


@cli.command()
@click.argument("target", metavar="DATE", type=IsoDate())
@click.pass_context
def forget(ctx: click.Context, target: _date) -> None:
    """Remove a note for DATE (YYYY-MM-DD) from the Hindsight server and local cache."""
    settings = _settings(ctx)
    if any(d == target for d, _ in _collect(settings.notes_path)):
        logger.warning("{} still exists in vault; next `sync` will recreate it", target)

    with get_client(settings) as client:
        delete(client, settings, target)
        evict(target)
    logger.info("{} forgotten", target)


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show counts of up-to-date, pending, and stale notes."""
    settings = _settings(ctx)

    vault_dates: set[_date] = set()
    pending: list[_date] = []
    up_to_date: list[_date] = []

    for note in _iter_notes(settings.notes_path):
        vault_dates.add(note.date)
        if needs_sync(note):
            pending.append(note.date)
        else:
            up_to_date.append(note.date)

    stale = sorted(cached_dates() - vault_dates)

    click.echo(f"up to date  {len(up_to_date):>4}")
    if settings.verbose:
        for d in up_to_date:
            click.echo(f"  {d}")
    click.echo(f"needs sync  {len(pending):>4}")
    if settings.verbose:
        for d in pending:
            click.echo(f"  {d}")
    if stale:
        click.echo(f"stale       {len(stale):>4}  (will be deleted on next sync)")
        if settings.verbose:
            for d in stale:
                click.echo(f"  {d}")
