"""Answer Code & Coffee questions from Google Drive documents."""

import asyncio
import io
import json
import os

from dispatch_agents import BasePayload, fn, llm
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from pydantic import field_validator

_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
_MAX_CONTEXT_CHARS = 18_000
_DOC_CHARS = 3_000
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
            "concise and cite document names or URLs when useful.\n\n"
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

    service = _drive_service()
    files = _list_files(service, folder_id, int(os.environ.get("CCP_DOCS_MAX_FILES", "8")))
    docs = []
    for item in files:
        text = _file_text(service, item)
        if text:
            docs.append({
                "name": item.get("name", "Untitled"),
                "url": item.get("webViewLink", ""),
                "modified_time": item.get("modifiedTime", ""),
                "text": text[:_DOC_CHARS],
            })
    return docs


def _drive_service():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not configured")
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(raw),
        scopes=[_DRIVE_SCOPE],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _list_files(service, folder_id: str, max_files: int) -> list[dict]:
    query = f"'{_drive_query_value(folder_id)}' in parents and trashed = false"
    result = service.files().list(
        q=query,
        pageSize=max(1, max_files),
        orderBy="modifiedTime desc",
        fields="files(id,name,mimeType,webViewLink,modifiedTime)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
    ).execute()
    return result.get("files", [])


def _file_text(service, item: dict) -> str:
    mime_type = item.get("mimeType", "")
    if mime_type in _EXPORT_MIMES:
        request = service.files().export_media(
            fileId=item["id"],
            mimeType=_EXPORT_MIMES[mime_type],
        )
        return _download_text(request)
    if mime_type.startswith("text/") or mime_type in {"application/json"}:
        return _download_text(service.files().get_media(fileId=item["id"]))
    return ""


def _download_text(request) -> str:
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue().decode("utf-8", errors="replace").strip()


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
