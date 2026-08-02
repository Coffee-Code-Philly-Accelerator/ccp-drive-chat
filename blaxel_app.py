"""Blaxel HTTP adapter for the Code & Coffee Drive Q&A agent."""

import asyncio
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

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
    from blaxel.core import bl_model as bl_model_core
    from blaxel.openai.model import DynamicHeadersHTTPClient
    from openai import AsyncOpenAI

    model_name = os.environ.get("BLAXEL_MODEL", "sandbox-openai")
    url, model_type, provider_model = await bl_model_core(model_name).get_parameters()
    if model_type != "openai":
        raise RuntimeError(f"Blaxel model {model_name!r} is not OpenAI-compatible")

    system = (
        "You answer questions about Code & Coffee Philadelphia using only "
        "the Google Drive document excerpts below. If the answer is not in "
        "the documents, say you do not know from the docs. Keep answers "
        "concise and cite document names or URLs when useful.\n\n"
        f"{_format_doc_context(docs)}"
    )

    async with DynamicHeadersHTTPClient(base_url=f"{url}/v1") as http_client:
        client = AsyncOpenAI(
            base_url=f"{url}/v1",
            api_key="replaced",
            http_client=http_client,
        )
        response = await client.chat.completions.create(
            model=provider_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
        )
    return (response.choices[0].message.content or "").strip()


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
