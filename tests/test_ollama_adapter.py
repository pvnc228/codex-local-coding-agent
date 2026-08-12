import json
import unittest

from local_coding_agent.ollama_adapter import (
    ModelProfile,
    OllamaClient,
    OllamaError,
)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, path, body, headers, timeout):
        self.requests.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "headers": headers,
                "timeout": timeout,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class OllamaClientTests(unittest.TestCase):
    def setUp(self):
        self.profile = ModelProfile(
            name="small-coder",
            model="qwen2.5:1.5b",
            endpoint="http://127.0.0.1:11434",
            think=False,
            temperature=0,
            num_ctx=4096,
            num_predict=256,
            keep_alive="10m",
            timeout_seconds=7,
        )

    def test_chat_sends_utf8_request_with_profile_limits(self):
        transport = FakeTransport(
            [
                (
                    200,
                    json.dumps(
                        {"message": {"role": "assistant", "content": "готово"}},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            ]
        )
        client = OllamaClient(self.profile, transport=transport)

        result = client.chat(
            [{"role": "user", "content": "Исправь русский текст"}],
            tools=[{"type": "function", "function": {"name": "read_file"}}],
        )

        self.assertEqual(result["message"]["content"], "готово")
        request = transport.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["path"], "/api/chat")
        self.assertEqual(request["headers"]["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(request["timeout"], 7)
        payload = json.loads(request["body"].decode("utf-8"))
        self.assertEqual(payload["model"], "qwen2.5:1.5b")
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["think"])
        self.assertEqual(payload["keep_alive"], "10m")
        self.assertEqual(payload["options"], {"temperature": 0, "num_ctx": 4096, "num_predict": 256})
        self.assertEqual(payload["messages"][0]["content"], "Исправь русский текст")
        self.assertEqual(payload["tools"][0]["function"]["name"], "read_file")

    def test_loaded_models_uses_get_api_ps_and_returns_json(self):
        transport = FakeTransport([(200, b'{"models":[{"name":"qwen2.5:1.5b"}]}')])
        client = OllamaClient(self.profile, transport=transport)

        result = client.loaded_models()

        self.assertEqual(result["models"][0]["name"], "qwen2.5:1.5b")
        self.assertEqual(transport.requests[0]["method"], "GET")
        self.assertEqual(transport.requests[0]["path"], "/api/ps")
        self.assertIsNone(transport.requests[0]["body"])

    def test_http_and_invalid_json_fail_as_normalized_ollama_errors(self):
        http_transport = FakeTransport([(503, b'{"error":"model unavailable"}')])
        client = OllamaClient(self.profile, transport=http_transport)

        with self.assertRaisesRegex(OllamaError, "HTTP 503") as http_error:
            client.chat([])
        self.assertEqual(http_error.exception.kind, "http")

        invalid_transport = FakeTransport([(200, b"not-json")])
        client = OllamaClient(self.profile, transport=invalid_transport)

        with self.assertRaisesRegex(OllamaError, "invalid JSON") as json_error:
            client.loaded_models()
        self.assertEqual(json_error.exception.kind, "invalid_json")


if __name__ == "__main__":
    unittest.main()
