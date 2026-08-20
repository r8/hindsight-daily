# Changelog

## [Unreleased]

### Changed

- **Breaking:** `api_url` is now required. The client has no built-in default, so a configuration
  without it never actually worked — it failed with an `AttributeError` instead of a message
- Validate `bank_id`, `api_url`, and `daily_notes_path` when a command starts and report problems
  as plain errors naming the config file, instead of confuse tracebacks. A malformed config no
  longer breaks `--help`
- Refuse to delete every cached note when the vault yields no notes at all, so an unmounted
  vault or a mistyped path no longer wipes the bank. Pass `--prune` when the vault really is empty
- Reject two vault files claiming the same date instead of letting them overwrite each other on
  the server every run. The error names both paths

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

- Page through the document listing when cleaning up a date, so sections removed from a long note
  are no longer left behind on the server

## [0.2.0] - 2026-05-08

### Added

- Add `forget` command to remove the note from server and cache 

## [0.1.0] - 2026-05-06

- Initial release
