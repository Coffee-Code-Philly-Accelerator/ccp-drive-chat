# ccp-drive-chat

Dispatch agent that answers Code & Coffee Philadelphia questions from Google Drive documents.

## What It Does

`ccp-drive-chat` exposes one Dispatch function, `ask_code_coffee_docs`, that:

- validates a short user question
- reads recent files from a configured Google Drive folder
- exports Google Docs, Slides, and Sheets into text
- asks the Dispatch LLM to answer using only those document excerpts
- returns an answer plus Drive document citations

This is intentionally small. It does not maintain a vector index or document cache.

## Configuration

Set these values before deployment:

```bash
GOOGLE_DRIVE_FOLDER_ID=<drive-folder-id>
CCP_DOCS_MAX_FILES=8
```

The deployed agent also needs this Dispatch secret:

```bash
/shared/google-drive-service-account-json
```

The secret value must be a Google service account JSON object with read access to the configured Drive folder.

## Development

```bash
uv sync
uv run python -m unittest discover -s tests
uv run dispatch agent validate --path . --force
```

## Dispatch

The deployment entrypoint is configured in `dispatch.yaml`.

