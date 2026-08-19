# Changelog

## [Unreleased]

### Changed

- Submit notes asynchronously and poll the server until ingestion completes, so large notes no
  longer fail with a request timeout; wait limits are configurable via `retain_timeout` and
  `retain_poll_interval`
- Report sync failures as a single error message and a non-zero exit code instead of a traceback,
  and keep syncing the remaining notes

### Fixed

- Page through the document listing when cleaning up a date, so sections removed from a long note
  are no longer left behind on the server

## [0.2.0] - 2026-05-08

### Added

- Add `forget` command to remove the note from server and cache 

## [0.1.0] - 2026-05-06

- Initial release
