# ccp-drive-chat

Blaxel/Dispatch agent that answers Code & Coffee Philadelphia questions from Google Drive documents.

## What It Does

`ccp-drive-chat` exposes one function, `ask_code_coffee_docs`, that:

- validates a short user question
- reads recent files from a configured Google Drive folder through Composio
- exports Google Docs, Slides, and Sheets into text
- asks an LLM to answer using only those document excerpts
- returns an answer plus Drive document citations

This is intentionally small. It does not maintain a vector index or document cache.

## Configuration

Set these values before deployment:

```bash
COMPOSIO_API_KEY=<composio-project-api-key>
COMPOSIO_USER_ID=default
GOOGLEDRIVE_CONNECTED_ACCOUNT_ID=<optional-connected-account-id>
GOOGLE_DRIVE_FOLDER_ID=<drive-folder-id>
CCP_DOCS_MAX_FILES=8
```

The Composio user, or the explicit `GOOGLEDRIVE_CONNECTED_ACCOUNT_ID`, must have an active Google Drive connection that can read the configured folder.

## Development

```bash
uv sync
uv run python -m unittest discover -s tests
uv run dispatch agent validate --path . --force
```

## Blaxel

The Blaxel deployment is configured in `blaxel.toml`.

```bash
bl serve -s COMPOSIO_API_KEY='<composio-project-api-key>'
bl run agent ccp-drive-chat --local --data '{"inputs":{"question":"When is the next meetup?"}}'
bl deploy -s COMPOSIO_API_KEY='<composio-project-api-key>'
```

The Blaxel agent uses the `sandbox-openai` model gateway by default.

## Dispatch

The legacy Dispatch deployment entrypoint is configured in `dispatch.yaml`.
