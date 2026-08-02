"""Answer Code & Coffee questions from Google Drive documents."""

import asyncio
import json
import os
import re
import urllib.request
from urllib.parse import quote

from dispatch_agents import BasePayload, fn, llm
from pydantic import field_validator

_GOOGLE_DRIVE_API = "https://www.googleapis.com/drive/v3"
_GOOGLEDRIVE_TOOLKIT = "googledrive"
_COMPOSIO_USER_ID = "default"
_MAX_CONTEXT_CHARS = 18_000
_DOC_CHARS = 3_000
_SENSITIVE_NAME_RE = re.compile(
    r"\b(api[- ]?key|auth|bearer|credential|credentials|creds|password|secret|token)\b",
    re.IGNORECASE,
)
_SENSITIVE_TEXT_RE = re.compile(
    r"(?im)^\s*(api[- ]?key|access token|bearer token|client secret|credential|credentials|password)\s*[:=]",
    re.IGNORECASE,
)
_SECRET_VALUE_RES = [
    re.compile(r"\bak_[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bdak_[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
]
_EXPORT_MIMES = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
}


class AskDocsRequest(BasePayload):
    question: str

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be empty")
        if len(value) > 500:
            raise ValueError("question must be 500 characters or fewer")
        return value


class AskDocsResponse(BasePayload):
    answer: str
    citations: list[str]


@fn(name="ask_code_coffee_docs")
async def ask_code_coffee_docs(payload: AskDocsRequest) -> AskDocsResponse:
    docs = await asyncio.to_thread(_fetch_docs)
    if not docs:
        return AskDocsResponse(
            answer="I could not find readable Code & Coffee Drive documents right now.",
            citations=[],
        )

    response = await llm.chat(
        payload.question,
        system=(
            "You answer questions about Code & Coffee Philadelphia using only "
            "the Google Drive document excerpts below. If the answer is not in "
            "the documents, say you do not know from the docs. Keep answers "
            "concise and cite document names or URLs when useful. You may answer "
            "questions about which documents were read using the document names "
            "and URLs in the excerpts.\n\n"
            f"{_format_doc_context(docs)}"
        ),
    )
    return AskDocsResponse(
        answer=(response.content or "").strip(),
        citations=[doc["url"] for doc in docs if doc.get("url")],
    )


def _fetch_docs() -> list[dict]:
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    if not folder_id:
        raise RuntimeError("GOOGLE_DRIVE_FOLDER_ID is not configured")

    client = _composio_client()
    connected_account_id = _drive_connected_account_id(client)
    files = _list_files(
        client,
        connected_account_id,
        folder_id,
        int(os.environ.get("CCP_DOCS_MAX_FILES", "8")),
    )
    docs = []
    for item in files:
        if _looks_sensitive_name(item.get("name", "")):
            continue
        text = _file_text(client, connected_account_id, item)
        if _looks_sensitive_text(text):
            continue
        if text:
            docs.append({
                "name": item.get("name", "Untitled"),
                "url": item.get("webViewLink", ""),
                "modified_time": item.get("modifiedTime", ""),
                "text": _redact_secret_values(text)[:_DOC_CHARS],
            })
    return docs


def _composio_client():
    api_key = os.environ.get("COMPOSIO_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("COMPOSIO_API_KEY is not configured")
    from composio import Composio

    return Composio(api_key=api_key)


def _drive_connected_account_id(client) -> str:
    connected_account_id = os.environ.get("GOOGLEDRIVE_CONNECTED_ACCOUNT_ID", "").strip()
    if connected_account_id:
        return connected_account_id

    user_id = (
        os.environ.get("COMPOSIO_USER_ID", _COMPOSIO_USER_ID).strip()
        or _COMPOSIO_USER_ID
    )
    accounts = client.connected_accounts.list(
        account_type="ALL",
        toolkit_slugs=[_GOOGLEDRIVE_TOOLKIT],
        user_ids=[user_id],
        statuses=["ACTIVE"],
        limit=1,
    ).items
    if not accounts:
        raise RuntimeError(f"No active Google Drive Composio account for user {user_id}")
    return accounts[0].id


def _list_files(client, connected_account_id: str, folder_id: str, max_files: int) -> list[dict]:
    query = f"'{_drive_query_value(folder_id)}' in parents and trashed = false"
    result = _proxy_data(
        client,
        connected_account_id,
        f"{_GOOGLE_DRIVE_API}/files",
        {
            "q": query,
            "pageSize": max(1, max_files),
            "orderBy": "modifiedTime desc",
            "fields": "files(id,name,mimeType,webViewLink,modifiedTime)",
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
        },
    )
    return result.get("files", []) if isinstance(result, dict) else []


def _file_text(client, connected_account_id: str, item: dict) -> str:
    mime_type = item.get("mimeType", "")
    if mime_type in _EXPORT_MIMES:
        return _proxy_text(
            client,
            connected_account_id,
            f"{_GOOGLE_DRIVE_API}/files/{quote(item['id'], safe='')}/export",
            {"mimeType": _EXPORT_MIMES[mime_type]},
        )
    if mime_type.startswith("text/") or mime_type in {"application/json"}:
        return _proxy_text(
            client,
            connected_account_id,
            f"{_GOOGLE_DRIVE_API}/files/{quote(item['id'], safe='')}",
            {"alt": "media"},
        )
    return ""


def _proxy_data(client, connected_account_id: str, endpoint: str, query: dict[str, object]) -> object:
    response = _proxy_get(client, connected_account_id, endpoint, query)
    return getattr(response, "data", None)


def _proxy_text(client, connected_account_id: str, endpoint: str, query: dict[str, object]) -> str:
    response = _proxy_get(client, connected_account_id, endpoint, query)
    return _response_text(response)


def _proxy_get(client, connected_account_id: str, endpoint: str, query: dict[str, object]):
    response = client.tools.proxy(
        endpoint=endpoint,
        method="GET",
        connected_account_id=connected_account_id,
        parameters=_proxy_query_parameters(query),
    )
    status = int(getattr(response, "status", 0) or 0)
    if status >= 400:
        raise RuntimeError(
            f"Google Drive proxy returned HTTP {status}: {getattr(response, 'data', '')}"
        )
    return response


def _proxy_query_parameters(query: dict[str, object]) -> list[dict[str, str]]:
    return [{"type": "query", "name": name, "value": str(value)} for name, value in query.items()]


def _response_text(response) -> str:
    data = getattr(response, "data", None)
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace").strip()
    if isinstance(data, dict):
        for key in ("text", "content", "body", "data"):
            value = data.get(key)
            if isinstance(value, str):
                return value.strip()

    binary_data = getattr(response, "binary_data", None)
    if hasattr(binary_data, "model_dump"):
        binary_data = binary_data.model_dump()
    if isinstance(binary_data, dict) and binary_data.get("url"):
        return _download_url_text(str(binary_data["url"]))
    if isinstance(data, dict):
        return json.dumps(data, ensure_ascii=False).strip()
    return ""


def _download_url_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace").strip()


def _looks_sensitive_name(name: str) -> bool:
    return bool(_SENSITIVE_NAME_RE.search(name))


def _looks_sensitive_text(text: str) -> bool:
    return bool(text and (_SENSITIVE_TEXT_RE.search(text) or _contains_secret_value(text)))


def _contains_secret_value(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_VALUE_RES)


def _redact_secret_values(text: str) -> str:
    for pattern in _SECRET_VALUE_RES:
        text = pattern.sub("[REDACTED_SECRET]", text)
    return text


def _format_doc_context(docs: list[dict]) -> str:
    parts = []
    used = 0
    for doc in docs:
        block = "\n".join(
            part
            for part in (
                f"Document: {doc.get('name', 'Untitled')}",
                f"URL: {doc.get('url', '')}",
                f"Modified: {doc.get('modified_time', '')}",
                "Excerpt:",
                doc.get("text", "").strip(),
            )
            if part
        )
        remaining = _MAX_CONTEXT_CHARS - used
        if remaining <= 0:
            break
        if len(block) > remaining:
            block = block[: max(0, remaining - 3)].rstrip() + "..."
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


def _drive_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _demo() -> None:
    assert _drive_query_value("abc'123") == "abc\\'123"
    context = _format_doc_context([
        {"name": "Handbook", "url": "https://example.com", "text": "Meetups happen weekly."}
    ])
    assert "Document: Handbook" in context
    assert "Meetups happen weekly." in context


if __name__ == "__main__":
    _demo()
