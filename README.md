# hindsight-daily

[![CI](https://github.com/r8/hindsight-daily/actions/workflows/ci.yml/badge.svg)](https://github.com/r8/hindsight-daily/actions/workflows/ci.yml)

Syncs Obsidian daily notes to [Hindsight](https://hindsight.vectorize.io) so they can be recalled by AI agents.

## How it works

Walks a configured vault directory, finds notes named `YYYY-MM-DD.md`, parses them into structured sections, and submits new or changed notes to Hindsight via its API. Unchanged notes are skipped. Deleted notes are removed from Hindsight.

Change detection uses a content hash (not mtime) because Obsidian plugins frequently touch mtime without changing content.

## Config

Config lives in `~/.config/hindsight-daily/config.yaml` (XDG-compliant):

```yaml
bank_id: your-bank-id
api_key: your-api-key
api_url:                    # optional, for local Hindsight installations
daily_notes_path: /path/to/vault/journals
verbose: false
```

## Usage

```bash
hindsight-daily sync           # sync new and changed notes
hindsight-daily sync --limit 5 # sync at most 5 notes
hindsight-daily status         # show pending/up-to-date counts
hindsight-daily -v status      # show individual note dates
hindsight-daily -v sync        # sync with debug logging
```

## Content structure

Each section of a note is submitted as a separate Hindsight document (e.g. `journal:2024-01-07_001`, `journal:2024-01-07_002`). The `journal:` prefix namespaces documents to avoid collisions with other tools writing to the same bank. The shallowest heading level present in the note becomes the section boundary; deeper headings are merged into their parent section as text blocks. Bullet and ordered lists preserve their markers. Blockquotes and unlabeled code blocks are wrapped in `<quote>` tags so Hindsight distinguishes external content from the user's own writing. Language-tagged code blocks use `<code lang="...">`. Wikilinks in section titles are extracted as scoped entity declarations so Hindsight correctly associates facts with the right entities.
