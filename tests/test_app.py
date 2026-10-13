
import os
import unittest
from unittest.mock import MagicMock, patch

import app


class ApplicationTests(unittest.TestCase):

    def setUp(self):
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()

    def test_health_identifies_deployed_version(self):
        with patch.dict(os.environ, {"APP_VERSION": "test-version"}):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json,
            {"status": "ok", "version": "test-version"},
        )

    def test_chat_requires_post(self):
        response = self.client.get("/chat")
        self.assertEqual(response.status_code, 405)

    def test_chat_returns_expected_response(self):
        mock_response = MagicMock()
        mock_response.text = "Hello! How can I help you today?"

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with (
            patch("app.get_gemini_client", return_value=mock_client),
            patch("app.langfuse.start_as_current_observation"),
        ):
            response = self.client.post(
                "/chat",
                json={"message": "Hello"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json,
            {"reply": "Hello! How can I help you today?"},
        )
  
        # Both Research Agent and Analysis Agent call Gemini.
        self.assertEqual(
            mock_client.models.generate_content.call_count,
            2,
        )
        
        calls = mock_client.models.generate_content.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertIn("Research Agent", calls[0].kwargs["contents"])
        self.assertIn("Analysis Agent", calls[1].kwargs["contents"])

    def test_invalid_messages_are_rejected(self):
        for payload in (
            {},
            {"message": ""},
            {"message": "   "},
            {"message": 123},
            {"message": None},
        ):
            with self.subTest(payload=payload):
                response = self.client.post("/chat", json=payload)
                self.assertEqual(response.status_code, 400)

    def test_long_message_is_rejected(self):
        response = self.client.post(
            "/chat",
            json={"message": "x" * 1001},
        )
        self.assertEqual(response.status_code, 400)

    def test_malformed_json_is_rejected(self):
        response = self.client.post(
            "/chat",
            data="{invalid json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_gemini_failure_returns_502(self):
        with (
            patch(
                "app.get_gemini_client",
                side_effect=RuntimeError("Simulated Gemini failure"),
            ),
            patch("app.langfuse.start_as_current_observation"),
        ):
            response = self.client.post(
                "/chat",
                json={"message": "Hello"},
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json,
            {"error": "The request could not be completed."},
        )
        
    def test_redact_pii_masks_email_and_phone(self):
        from app import redact_pii

        text = (
            "Contact priya@example.com "
            "or call +91 98765 43210."
        )

        redacted = redact_pii(text)

        self.assertNotIn("priya@example.com", redacted)
        self.assertNotIn("98765 43210", redacted)
        self.assertIn("[REDACTED_EMAIL]", redacted)
        self.assertIn("[REDACTED_PHONE]", redacted)


if __name__ == "__main__":
    unittest.main()
