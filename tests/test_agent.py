import unittest

from pydantic import ValidationError

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


if __name__ == "__main__":
    unittest.main()
