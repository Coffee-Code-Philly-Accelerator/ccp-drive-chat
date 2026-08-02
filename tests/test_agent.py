import unittest
from types import SimpleNamespace
from unittest import mock

from pydantic import ValidationError

import agent
from agent import AskDocsRequest, _drive_query_value, _format_doc_context


class AgentTests(unittest.TestCase):
    def test_question_validation(self):
        self.assertEqual(AskDocsRequest(question="  when is meetup?  ").question, "when is meetup?")
        with self.assertRaises(ValidationError):
            AskDocsRequest(question="")

    def test_drive_query_escaping(self):
        self.assertEqual(_drive_query_value("abc'123"), "abc\\'123")

    def test_format_doc_context(self):
        context = _format_doc_context([
            {"name": "Handbook", "url": "https://example.com", "text": "Meetups happen weekly."}
        ])
        self.assertIn("Document: Handbook", context)
        self.assertIn("Meetups happen weekly.", context)

    def test_fetch_docs_uses_composio_drive_connection(self):
        client = object()
        files = [
            {
                "id": "doc-1",
                "name": "Handbook",
                "mimeType": "application/vnd.google-apps.document",
                "webViewLink": "https://drive.example/doc-1",
                "modifiedTime": "2026-08-02T00:00:00Z",
            }
        ]
        with (
            mock.patch.dict(
                "os.environ",
                {
                    "GOOGLE_DRIVE_FOLDER_ID": "folder-123",
                    "COMPOSIO_API_KEY": "key",
                    "CCP_DOCS_MAX_FILES": "2",
                },
                clear=True,
            ),
            mock.patch.object(agent, "_composio_client", return_value=client) as composio_client,
            mock.patch.object(agent, "_drive_connected_account_id", return_value="acct-1") as account_id,
            mock.patch.object(agent, "_list_files", return_value=files) as list_files,
            mock.patch.object(agent, "_file_text", return_value="Meetups happen weekly.") as file_text,
        ):
            docs = agent._fetch_docs()

        composio_client.assert_called_once_with()
        account_id.assert_called_once_with(client)
        list_files.assert_called_once_with(client, "acct-1", "folder-123", 2)
        file_text.assert_called_once_with(client, "acct-1", files[0])
        self.assertEqual(docs[0]["name"], "Handbook")
        self.assertEqual(docs[0]["text"], "Meetups happen weekly.")

    def test_fetch_docs_requires_composio_key(self):
        with (
            mock.patch.dict("os.environ", {"GOOGLE_DRIVE_FOLDER_ID": "folder-123"}, clear=True),
            self.assertRaisesRegex(RuntimeError, "COMPOSIO_API_KEY"),
        ):
            agent._fetch_docs()

    def test_fetch_docs_skips_sensitive_file_names(self):
        client = object()
        files = [
            {"id": "secret-1", "name": "Datadog API key", "mimeType": "application/vnd.google-apps.document"},
            {"id": "secret-2", "name": "SonOfAnton creds", "mimeType": "application/vnd.google-apps.document"},
            {"id": "doc-1", "name": "Handbook", "mimeType": "application/vnd.google-apps.document"},
        ]
        with (
            mock.patch.dict(
                "os.environ",
                {"GOOGLE_DRIVE_FOLDER_ID": "folder-123", "COMPOSIO_API_KEY": "key"},
                clear=True,
            ),
            mock.patch.object(agent, "_composio_client", return_value=client),
            mock.patch.object(agent, "_drive_connected_account_id", return_value="acct-1"),
            mock.patch.object(agent, "_list_files", return_value=files),
            mock.patch.object(agent, "_file_text", return_value="Meetups happen weekly.") as file_text,
        ):
            docs = agent._fetch_docs()

        file_text.assert_called_once_with(client, "acct-1", files[2])
        self.assertEqual([doc["name"] for doc in docs], ["Handbook"])

    def test_fetch_docs_skips_sensitive_file_content(self):
        client = object()
        files = [
            {"id": "doc-1", "name": "Notes", "mimeType": "application/vnd.google-apps.document"},
            {"id": "doc-2", "name": "Handbook", "mimeType": "application/vnd.google-apps.document"},
        ]
        with (
            mock.patch.dict(
                "os.environ",
                {"GOOGLE_DRIVE_FOLDER_ID": "folder-123", "COMPOSIO_API_KEY": "key"},
                clear=True,
            ),
            mock.patch.object(agent, "_composio_client", return_value=client),
            mock.patch.object(agent, "_drive_connected_account_id", return_value="acct-1"),
            mock.patch.object(agent, "_list_files", return_value=files),
            mock.patch.object(
                agent,
                "_file_text",
                side_effect=["Access token: " + ("a" * 36), "Meetups happen weekly."],
            ),
        ):
            docs = agent._fetch_docs()

        self.assertEqual([doc["name"] for doc in docs], ["Handbook"])

    def test_drive_connected_account_id_uses_default_user(self):
        client = SimpleNamespace(
            connected_accounts=SimpleNamespace(
                list=mock.Mock(return_value=SimpleNamespace(items=[SimpleNamespace(id="acct-1")]))
            )
        )
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(agent._drive_connected_account_id(client), "acct-1")
        client.connected_accounts.list.assert_called_once_with(
            account_type="ALL",
            toolkit_slugs=["googledrive"],
            user_ids=["default"],
            statuses=["ACTIVE"],
            limit=1,
        )

    def test_drive_connected_account_id_uses_configured_account(self):
        client = SimpleNamespace(connected_accounts=SimpleNamespace(list=mock.Mock()))
        with mock.patch.dict("os.environ", {"GOOGLEDRIVE_CONNECTED_ACCOUNT_ID": "acct-configured"}):
            self.assertEqual(agent._drive_connected_account_id(client), "acct-configured")
        client.connected_accounts.list.assert_not_called()

    def test_response_text_prefers_string_payloads(self):
        response = SimpleNamespace(data={"content": "  hello docs  "})
        self.assertEqual(agent._response_text(response), "hello docs")

    def test_redact_secret_values(self):
        text = "key " + "dak_" + ("a" * 36)
        self.assertEqual(agent._redact_secret_values(text), "key [REDACTED_SECRET]")

    def test_proxy_get_raises_google_drive_errors(self):
        client = SimpleNamespace(
            tools=SimpleNamespace(proxy=mock.Mock(return_value=SimpleNamespace(status=403, data="denied")))
        )
        with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
            agent._proxy_get(client, "acct-1", "https://example.com", {})


if __name__ == "__main__":
    unittest.main()
