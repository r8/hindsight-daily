# hindsight-daily

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
hindsight-daily sync        # sync new and changed notes
hindsight-daily -v sync     # with debug logging
```

## Content structure

Each note is submitted as a JSON document with sections grouped by `##` headings. Sub-headings (`###`, `####`) are merged into their parent section. Blockquotes and unlabeled code blocks are wrapped in `<quote>` tags so Hindsight distinguishes external content from the user's own writing. Language-tagged code blocks use `<code lang="...">`.
