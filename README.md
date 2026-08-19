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
bank_id: your-bank-id
api_key: your-api-key
api_url:                    # optional, for local Hindsight installations
daily_notes_path: /path/to/vault/journals
verbose: false
retain_timeout: 1800        # optional, max seconds to wait for a note to be ingested
retain_poll_interval: 3     # optional, initial seconds between ingestion status checks
```

Notes are submitted asynchronously: the server queues the ingestion and `sync` polls it to
completion before marking the note as synced. Large notes can take the server several minutes,
so raise `retain_timeout` if a note reports that it is still being ingested.

## Usage

```bash
hindsight-daily sync             # sync new and changed notes
hindsight-daily sync --limit 5   # sync at most 5 notes
hindsight-daily sync --date DATE # sync just one note
hindsight-daily forget DATE      # remove a note from server and cache
hindsight-daily status           # show pending/up-to-date counts
hindsight-daily -v status        # show individual note dates
hindsight-daily -v sync          # sync with debug logging
```

## Content structure

Each section of a note is submitted as a separate Hindsight document (e.g. `journal:2024-01-07_001`, `journal:2024-01-07_002`). The `journal:` prefix namespaces documents to avoid collisions with other tools writing to the same bank. The shallowest heading level present in the note becomes the section boundary; deeper headings are merged into their parent section as text blocks. Bullet and ordered lists preserve their markers. Blockquotes and unlabeled code blocks are wrapped in `<quote>` tags so Hindsight distinguishes external content from the user's own writing. Language-tagged code blocks use `<code lang="...">`. Wikilinks in section titles are extracted as scoped entity declarations so Hindsight correctly associates facts with the right entities.
