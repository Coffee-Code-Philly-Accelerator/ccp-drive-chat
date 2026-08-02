# ccp-drive-chat

Blaxel/Dispatch agent that answers Code & Coffee Philadelphia questions from Google Drive documents.

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

The deployed agent also needs a Google service account JSON secret:

```bash
GOOGLE_SERVICE_ACCOUNT_JSON=<service-account-json>
```

The secret value must be a Google service account JSON object with read access to the configured Drive folder.

## Development

```bash
uv sync
uv run python -m unittest discover -s tests
uv run dispatch agent validate --path . --force
```

## Blaxel

The Blaxel deployment is configured in `blaxel.toml`.

```bash
bl serve -s GOOGLE_SERVICE_ACCOUNT_JSON='<service-account-json>'
bl run agent ccp-drive-chat --local --data '{"inputs":{"question":"When is the next meetup?"}}'
bl deploy -s GOOGLE_SERVICE_ACCOUNT_JSON='<service-account-json>'
```

The Blaxel agent uses the `sandbox-openai` model gateway by default.

## Dispatch

The legacy Dispatch deployment entrypoint is configured in `dispatch.yaml`.
