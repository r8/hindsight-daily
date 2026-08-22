# Changelog

## [Unreleased]

### Changed

- Upgrading from 0.2.0: delete the cache directory to re-submit notes with the improved parsing.
  The content hash is unchanged, so already-synced notes otherwise keep their existing content on
  the server
- **Breaking:** `api_url` is now required. The client has no built-in default, so a configuration
  without it never actually worked — it failed with an `AttributeError` instead of a message
- Validate `bank_id`, `api_url`, and `daily_notes_path` when a command starts and report problems
  as plain errors naming the config file, instead of confuse tracebacks. A malformed config no
  longer breaks `--help`
- Refuse to delete every cached note when the vault yields no notes at all, so an unmounted
  vault or a mistyped path no longer wipes the bank. Pass `--prune` when the vault really is empty
- Reject two vault files claiming the same date instead of letting them overwrite each other on
  the server every run. The error names both paths
- `sync --date` now removes a note that has become empty, matching what a full sync does. It
  previously logged a skip and left the old content on the server indefinitely
- Submit notes asynchronously and poll the server until ingestion completes, so large notes no
  longer fail with a request timeout; wait limits are configurable via `retain_timeout` and
  `retain_poll_interval`
- Report sync failures as a single error message and a non-zero exit code instead of a traceback,
  and keep syncing the remaining notes

### Fixed

- Preserve nested lists, ordered-list start numbers, multi-paragraph list items, indented code,
  HTML blocks, tables and thematic breaks, all of which the section parser used to drop silently
- Stop classifying notes made only of indented code or an HTML block as empty. Such a note was
  skipped, which kept its date out of the vault set, which made the deletion phase remove it from
  the server
- Retain replacements before removing the sections they supersede, so a failed or interrupted
  submit no longer leaves the server missing sections it had before
- Return early when a note produces no sections, instead of deleting all of its documents
  from the server and reporting success
- Strip Obsidian heading (`#`) and block (`^`) anchors from wikilinks before extracting
  entities, so `[[Project#Meeting notes]]` and `[[Project]]` no longer become two entities
- Report failures from the deletion phase and from `forget` as plain errors rather than
  tracebacks, and keep the cache entry when a deletion did not actually happen
- Distinguish listing, cleanup and retain failures instead of labelling all three
  `retain request failed`, and show errors as `TimeoutError: timed out` rather than
  a bare `TimeoutError()`
- Confirm the sections are on the server when a retain operation stops being tracked. The
  server purges completed operations, but a restart that dropped an in-flight one looked
  identical, and the note would have been marked synced without ever being ingested
- Check operation status before sleeping, so a note the server ingests quickly no longer costs
  a full `retain_poll_interval` before anyone looks at it
- Treat an unrecognized sub-batch status as a failure instead of logging it as progress and
  marking the note synced
- Stop importing a private helper from `hindsight-client`, and cap the dependency below 0.6,
  since this code reads the client's operation statuses directly
- Reject `--limit` below zero, and reject `--date` combined with `--limit`, which was silently
  ignored
- Always print the `stale` row in `status`, so the output shape does not depend on the data,
  and say when `sync --date` skips the deletion phase
- Add `sync --reconcile-remote`, which finds stale notes by diffing the server against the
  vault instead of trusting local cache history. Use it when the cache was lost or the vault
  is synced across machines; it assumes this vault is the only writer of `journal:` documents

- Page through the document listing when cleaning up a date, so sections removed from a long note
  are no longer left behind on the server

## [0.2.0] - 2026-05-08

### Added

- Add `forget` command to remove the note from server and cache 

## [0.1.0] - 2026-05-06

- Initial release
