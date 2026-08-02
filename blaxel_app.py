"""Blaxel HTTP adapter for the Code & Coffee Drive Q&A agent."""

import asyncio
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agent import AskDocsRequest, AskDocsResponse, _fetch_docs, _format_doc_context

logger = logging.getLogger(__name__)


def _question_from_body(body: Any) -> str:
    if isinstance(body, dict):
        data = body.get("inputs", body)
        if isinstance(data, dict):
            if "payload" in data and isinstance(data["payload"], dict):
                data = data["payload"]
            return str(data["question"])
        return str(data)
    return str(body)


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


async def _model_answer(question: str, docs: list[dict]) -> str:
    from blaxel.core.common import settings

    model_name = os.environ.get("BLAXEL_MODEL", "sandbox-openai")
    provider_model = os.environ.get("BLAXEL_PROVIDER_MODEL", "gpt-4o-mini")
    url = _model_url(model_name)

    system = (
        "You answer questions about Code & Coffee Philadelphia using only "
        "the Google Drive document excerpts below. If the answer is not in "
        "the documents, say you do not know from the docs. Keep answers "
        "concise and cite document names or URLs when useful. You may answer "
        "questions about which documents were read using the document names "
        "and URLs in the excerpts.\n\n"
        f"{_format_doc_context(docs)}"
    )

    response = await asyncio.to_thread(
        _post_json,
        f"{url}/v1/chat/completions",
        {
            "model": provider_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
        },
        settings.headers,
        90,
    )
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError("Blaxel model returned no choices")
    message = choices[0].get("message") or {}
    return str(message.get("content") or "").strip()


def _model_url(model_name: str) -> str:
    configured = os.environ.get("BLAXEL_MODEL_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    workspace = os.environ.get("BLAXEL_WORKSPACE", "coffee-code-philly")
    return f"https://run.blaxel.ai/{workspace}/models/{model_name}"


def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: int) -> dict:
    body = json.dumps(payload).encode()
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            **headers,
            "accept": "application/json",
            "content-type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read()
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from Blaxel model: {response_body[:1000]}") from exc
    return json.loads(response_body or b"{}")


async def ask_code_coffee_docs(payload: dict[str, Any] | AskDocsRequest) -> AskDocsResponse:
    request = payload if isinstance(payload, AskDocsRequest) else AskDocsRequest(**payload)
    docs = await asyncio.to_thread(_fetch_docs)
    if not docs:
        return AskDocsResponse(
            answer="I could not find readable Code & Coffee Drive documents right now.",
            citations=[],
        )
    answer = await _model_answer(request.question, docs)
    return AskDocsResponse(answer=answer, citations=[doc["url"] for doc in docs if doc.get("url")])


class BlaxelHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"ok": True})
            return
        if self.path == "/functions":
            self._send_json(200, {"functions": ["ask_code_coffee_docs"]})
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        try:
            body = self._json_body()
            question = _question_from_body(body)
            response = asyncio.run(ask_code_coffee_docs({"question": question}))
            self._send_json(200, response)
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:
            logger.exception("Blaxel invocation failed")
            self._send_json(500, {"error": str(exc)})

    def _json_body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode()
        return json.loads(raw) if raw else {}

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, default=_json_default).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        logger.info(format, *args)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "1338"))
    ThreadingHTTPServer((host, port), BlaxelHandler).serve_forever()


if __name__ == "__main__":
    main()
