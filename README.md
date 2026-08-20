# hindsight-daily

[![CI](https://github.com/r8/hindsight-daily/actions/workflows/ci.yml/badge.svg)](https://github.com/r8/hindsight-daily/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/hindsight-daily.svg)](https://pypi.org/project/hindsight-daily/)

Syncs Obsidian daily notes to [Hindsight](https://hindsight.vectorize.io) so they can be recalled by AI agents.

## How it works

Walks a configured vault directory, finds notes named `YYYY-MM-DD.md`, parses them into structured sections, and submits new or changed notes to Hindsight via its API. Unchanged notes are skipped. Deleted notes are removed from Hindsight.

Change detection uses a content hash (not mtime) because Obsidian plugins frequently touch mtime without changing content.

## Installation

```bash
uv tool install hindsight-daily
```

or with pip:

```bash
pip install hindsight-daily
```

## Config

Config lives in `~/.config/hindsight-daily/config.yaml` (XDG-compliant):

```yaml
bank_id: your-bank-id       # required
api_key: your-api-key
api_url: https://your-hindsight-host   # required
daily_notes_path: /path/to/vault/journals   # required, must be an existing directory
verbose: false
retain_timeout: 1800        # optional, max seconds to wait for a note to be ingested
retain_poll_interval: 3     # optional, initial seconds between ingestion status checks
```

`bank_id`, `api_url`, and `daily_notes_path` are required and validated when a command starts;
anything missing is reported as a plain error naming the config file.

### Cache

Sync state lives in a local cache (`~/Library/Caches/hindsight-daily` on macOS,
`~/.cache/hindsight-daily` on Linux), which records the content hash last submitted for each date.
It is keyed by date alone, so **switching `bank_id` will not re-upload anything** — every note
still reports as unchanged. Delete the cache directory when pointing the tool at a different bank.

Notes are submitted asynchronously: the server queues the ingestion and `sync` polls it to
completion before marking the note as synced. Large notes can take the server several minutes,
so raise `retain_timeout` if a note reports that it is still being ingested.

## Usage

```bash
hindsight-daily sync             # sync new and changed notes
hindsight-daily sync --limit 5   # sync at most 5 notes
hindsight-daily sync --date DATE # sync just one note
hindsight-daily sync --prune     # allow deletion even when the vault is empty
hindsight-daily forget DATE      # remove a note from server and cache
hindsight-daily status           # show pending/up-to-date counts
hindsight-daily -v status        # show individual note dates
hindsight-daily -v sync          # sync with debug logging
```

## Content structure

Each section of a note is submitted as a separate Hindsight document (e.g. `journal:2024-01-07_001`, `journal:2024-01-07_002`). The `journal:` prefix namespaces documents to avoid collisions with other tools writing to the same bank. The shallowest top-level heading level present in the note becomes the section boundary; deeper headings are merged into their parent section as text blocks. Section content is sliced out of the original markdown rather than reassembled, so nested lists, ordered-list numbering, tables, HTML and other constructs are preserved as written. Blockquotes, unlabeled code blocks and indented code are wrapped in `<quote>` tags so Hindsight distinguishes external content from the user's own writing. Language-tagged code blocks use `<code lang="...">`. Wikilinks in section titles are extracted as scoped entity declarations so Hindsight correctly associates facts with the right entities.
