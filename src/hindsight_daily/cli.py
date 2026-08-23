import datetime
from collections.abc import Iterator
from enum import Enum, auto
from pathlib import Path
from typing import Any

import click
from loguru import logger

from .cache import cached_dates, close_cache, evict, is_cached, mark_synced, needs_sync
from .collector import DuplicateNoteError, collect
from .config import Settings, SettingsError, load_settings
from .hindsight import HindsightError, delete, get_client, list_journal_dates, submit
from .parser import Note, is_empty, parse


class IsoDate(click.ParamType):
    name = "date"

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> datetime.date:
        if isinstance(value, datetime.date):
            return value
        try:
            return datetime.date.fromisoformat(value)
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


def _collect(notes_path: Path) -> list[tuple[datetime.date, Path]]:
    try:
        return collect(notes_path)
    except DuplicateNoteError as exc:
        raise click.ClickException(str(exc)) from exc


def _iter_notes(notes_path: Path) -> Iterator[Note]:
    for entry_date, file in _collect(notes_path):
        yield parse(entry_date, file)


class Outcome(Enum):
    SUBMITTED = auto()
    UNCHANGED = auto()
    DEFERRED = auto()
    EMPTY = auto()


def _sync_one(
    client: Any, settings: Settings, note: Note, *, limit_reached: bool = False
) -> Outcome:
    """Bring one note in line with the server.

    The only place that decides what syncing a note means, so `sync` and `sync --date`
    cannot drift apart. Raises HindsightSubmitError; callers decide how loud that is.
    """
    if is_empty(note):
        if is_cached(note.date):
            delete(client, settings, note.date)
            evict(note.date)
            logger.info("{} removed; note is now empty", note.date)
        else:
            logger.debug("{} has no content sections, skipping", note.date)
        return Outcome.EMPTY

    if not needs_sync(note):
        logger.debug("{} unchanged, skipping", note.date)
        return Outcome.UNCHANGED

    if limit_reached:
        logger.debug("{} needs sync but limit reached, deferring", note.date)
        return Outcome.DEFERRED

    submit(client, settings, note)
    mark_synced(note)
    logger.info("{} synced", note.date)
    return Outcome.SUBMITTED


@click.group()
@click.option("-v", "--verbose", is_flag=True, default=None)
@click.pass_context
def cli(ctx: click.Context, verbose: bool | None) -> None:
    ctx.obj = verbose


@cli.command()
@click.option("--limit", type=click.IntRange(min=0), default=None,
              help="Maximum number of notes to submit in one run.")
@click.option("--date", "target", type=IsoDate(), metavar="DATE", default=None,
              help="Sync only the note for DATE (YYYY-MM-DD); skips the deletion phase.")
@click.option("--prune", is_flag=True,
              help="Allow the deletion phase to run even when the vault yields no notes at all.")
@click.option("--reconcile-remote", is_flag=True,
              help="Also treat dates the server holds but the vault does not as stale, instead of "
                   "trusting local cache history. Only safe when this vault is the sole writer of "
                   "journal documents to the bank.")
@click.pass_context
def sync(ctx: click.Context, limit: int | None, target: datetime.date | None, prune: bool,
         reconcile_remote: bool) -> None:
    """Submit new and changed notes to Hindsight, remove notes deleted from the vault."""
    if target is not None:
        conflicting = [
            name for name, given in
            (("--limit", limit is not None), ("--prune", prune), ("--reconcile-remote", reconcile_remote))
            if given
        ]
        if conflicting:
            raise click.UsageError(
                f"{', '.join(conflicting)} does not apply to --date, which syncs a single note "
                f"and skips the deletion phase"
            )
    settings = _settings(ctx)

    with get_client(settings) as client:
        if target is not None:
            for entry_date, file in _collect(settings.notes_path):
                if entry_date != target:
                    continue
                try:
                    _sync_one(client, settings, parse(entry_date, file))
                except HindsightError as exc:
                    raise click.ClickException(str(exc)) from exc
                logger.info("--date given, skipping the deletion phase")
                return
            raise click.ClickException(f"no note found for {target}")

        vault_dates: set[datetime.date] = set()
        submitted = 0
        failed = 0
        for note in _iter_notes(settings.notes_path):
            try:
                outcome = _sync_one(
                    client, settings, note,
                    limit_reached=limit is not None and submitted >= limit,
                )
            except HindsightError as exc:
                logger.error("{}", exc)
                # Still a vault note, so it must not be treated as stale and deleted.
                vault_dates.add(note.date)
                failed += 1
                continue
            if outcome is not Outcome.EMPTY:
                vault_dates.add(note.date)
            if outcome is Outcome.SUBMITTED:
                submitted += 1

        stale_dates = cached_dates() - vault_dates
        if reconcile_remote:
            try:
                stale_dates |= list_journal_dates(client, settings) - vault_dates
            except HindsightError as exc:
                logger.error("{}", exc)
                failed += 1
        if stale_dates and not vault_dates and not prune:
            # An unmounted vault or a mistyped path looks exactly like "every note was deleted".
            raise click.ClickException(
                f"vault has no notes but the cache holds {len(stale_dates)}; refusing to delete them. "
                f"Check {settings.notes_path}, or pass --prune if the vault really is empty."
            )

        for stale in sorted(stale_dates):
            try:
                delete(client, settings, stale)
            except HindsightError as exc:
                logger.error("{}", exc)
                failed += 1
                continue
            evict(stale)
            logger.info("{} deleted (note removed from vault)", stale)

    if failed:
        raise click.ClickException(f"{failed} note(s) failed to sync")


@cli.command()
@click.argument("target", metavar="DATE", type=IsoDate())
@click.pass_context
def forget(ctx: click.Context, target: datetime.date) -> None:
    """Remove a note for DATE (YYYY-MM-DD) from the Hindsight server and local cache."""
    settings = _settings(ctx)
    if any(d == target for d, _ in _collect(settings.notes_path)):
        logger.warning("{} still exists in vault; next `sync` will recreate it", target)

    with get_client(settings) as client:
        try:
            delete(client, settings, target)
        except HindsightError as exc:
            raise click.ClickException(str(exc)) from exc
        evict(target)
    logger.info("{} forgotten", target)


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show counts of up-to-date, pending, and stale notes."""
    settings = _settings(ctx)

    vault_dates: set[datetime.date] = set()
    pending: list[datetime.date] = []
    up_to_date: list[datetime.date] = []

    for note in _iter_notes(settings.notes_path):
        if is_empty(note):
            logger.debug("{} has no content sections, skipping", note.date)
            continue
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
    click.echo(f"stale       {len(stale):>4}  (will be deleted on next sync)")
    if settings.verbose:
        for d in stale:
            click.echo(f"  {d}")
