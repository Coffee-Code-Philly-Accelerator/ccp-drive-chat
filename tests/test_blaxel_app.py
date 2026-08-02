import asyncio
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import blaxel_app


def test_question_from_body_accepts_blaxel_inputs_string():
    assert blaxel_app._question_from_body({"inputs": "when is meetup?"}) == "when is meetup?"


def test_question_from_body_accepts_nested_question():
    assert blaxel_app._question_from_body({"inputs": {"question": "when is meetup?"}}) == "when is meetup?"


def test_question_from_body_accepts_payload_shape():
    assert (
        blaxel_app._question_from_body(
            {"inputs": {"function": "ask_code_coffee_docs", "payload": {"question": "when?"}}}
        )
        == "when?"
    )


def test_ask_code_coffee_docs_returns_empty_docs_message():
    with mock.patch.object(blaxel_app, "_fetch_docs", return_value=[]):
        response = asyncio.run(blaxel_app.ask_code_coffee_docs({"question": "when?"}))
    assert response.answer == "I could not find readable Code & Coffee Drive documents right now."
    assert response.citations == []


def test_model_url_defaults_to_workspace_gateway():
    with mock.patch.dict("os.environ", {}, clear=True):
        assert (
            blaxel_app._model_url("sandbox-openai")
            == "https://run.blaxel.ai/coffee-code-philly/models/sandbox-openai"
        )


def test_model_url_accepts_configured_url():
    with mock.patch.dict("os.environ", {"BLAXEL_MODEL_URL": "https://example.test/model/"}):
        assert blaxel_app._model_url("ignored") == "https://example.test/model"


def test_model_answer_posts_to_gateway():
    class FakeSettings:
        headers = {"Authorization": "Bearer test"}

    def fake_post_json(url, payload, headers, timeout):
        assert url == "https://run.blaxel.ai/coffee-code-philly/models/sandbox-openai/v1/chat/completions"
        assert payload["model"] == "gpt-4o-mini"
        assert payload["messages"][1] == {"role": "user", "content": "when?"}
        assert headers == FakeSettings.headers
        assert timeout == 90
        return {"choices": [{"message": {"content": "Meetups happen weekly."}}]}

    with (
        mock.patch.dict("os.environ", {}, clear=True),
        mock.patch.dict("sys.modules", {"blaxel.core.common": mock.Mock(settings=FakeSettings)}),
        mock.patch.object(blaxel_app, "_post_json", fake_post_json),
    ):
        answer = asyncio.run(blaxel_app._model_answer("when?", [{"name": "Handbook", "text": "weekly"}]))
    assert answer == "Meetups happen weekly."


def test_http_post_root():
    async def fake_ask(payload):
        return {"answer": payload["question"], "citations": []}

    server = ThreadingHTTPServer(("127.0.0.1", 0), blaxel_app.BlaxelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    try:
        with mock.patch.object(blaxel_app, "ask_code_coffee_docs", fake_ask):
            thread.start()
            body = json.dumps({"inputs": {"question": "hello"}}).encode()
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                data = json.loads(response.read().decode())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert data == {"answer": "hello", "citations": []}


def test_http_post_bad_request():
    server = ThreadingHTTPServer(("127.0.0.1", 0), blaxel_app.BlaxelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    try:
        thread.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/",
            data=b'{"inputs": {}}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            data = json.loads(exc.read().decode())
            status = exc.code
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert status == 400
    assert "question" in data["error"]
