import json
import unittest

from local_coding_agent.ollama_adapter import (
    ModelProfile,
    OpenAICompatibleClient,
    OllamaClient,
    OllamaError,
    build_client,
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


def openai_profile(**overrides):
    kwargs = dict(
        name="ling-tiny",
        model="ling-3.0-tiny-q6k",
        endpoint="http://127.0.0.1:8080",
        provider="openai",
        think=False,
        temperature=0,
        num_ctx=8192,
        num_predict=512,
        stop=("<|role_end|>", "<role>"),
    )
    kwargs.update(overrides)
    return ModelProfile(**kwargs)


class OpenAICompatibleClientTests(unittest.TestCase):
    def test_chat_converts_messages_and_normalizes_response(self):
        transport = FakeTransport(
            [
                (
                    200,
                    json.dumps(
                        {
                            "choices": [
                                {
                                    "message": {
                                        "role": "assistant",
                                        "content": "",
                                        "tool_calls": [
                                            {
                                                "id": "call-1",
                                                "function": {
                                                    "name": "read_file",
                                                    "arguments": '{"path": "a.py"}',
                                                },
                                            }
                                        ],
                                    }
                                }
                            ],
                            "usage": {"prompt_tokens": 100, "completion_tokens": 40},
                            "timings": {"prompt_ms": 12.5, "predicted_ms": 250.0},
                        }
                    ).encode("utf-8"),
                )
            ]
        )
        client = OpenAICompatibleClient(openai_profile(), transport=transport)

        result = client.chat(
            [
                {"role": "system", "content": "contract"},
                {"role": "user", "content": "Исправь"},
                {
                    "role": "tool",
                    "tool_name": "read_file",
                    "tool_call_id": "call-1",
                    "content": "содержимое файла",
                },
            ],
            tools=[{"type": "function", "function": {"name": "read_file"}}],
        )

        self.assertEqual(result["message"]["role"], "assistant")
        self.assertEqual(result["message"]["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(result["prompt_eval_count"], 100)
        self.assertEqual(result["eval_count"], 40)
        self.assertEqual(result["prompt_eval_duration"], 12_500_000)
        self.assertEqual(result["eval_duration"], 250_000_000)

        request = transport.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["path"], "/v1/chat/completions")
        payload = json.loads(request["body"].decode("utf-8"))
        self.assertEqual(payload["model"], "ling-3.0-tiny-q6k")
        self.assertEqual(payload["max_tokens"], 512)
        self.assertEqual(payload["tools"][0]["function"]["name"], "read_file")
        messages = payload["messages"]
        self.assertEqual(messages[0], {"role": "system", "content": "contract"})
        self.assertEqual(messages[2]["role"], "tool")
        self.assertEqual(messages[2]["tool_call_id"], "call-1")

    def test_chat_maps_sampling_options_and_stop(self):
        transport = FakeTransport(
            [
                (
                    200,
                    json.dumps(
                        {
                            "choices": [
                                {"message": {"role": "assistant", "content": "done"}}
                            ],
                            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                        }
                    ).encode("utf-8"),
                )
            ]
        )
        client = OpenAICompatibleClient(
            openai_profile(temperature=0.7, top_p=0.8, seed=42), transport=transport
        )
        client.chat([{"role": "user", "content": "hi"}])

        payload = json.loads(transport.requests[0]["body"].decode("utf-8"))
        self.assertEqual(payload["temperature"], 0.7)
        self.assertEqual(payload["top_p"], 0.8)
        self.assertEqual(payload["seed"], 42)
        self.assertEqual(payload["stop"], ["<|role_end|>", "<role>"])
        self.assertEqual(
            payload["chat_template_kwargs"],
            {"thinking_option": "off", "enable_thinking": False},
        )

    def test_available_models_uses_v1_models(self):
        transport = FakeTransport(
            [(200, b'{"data":[{"id":"ling-3.0-tiny-q6k"}]}')]
        )
        client = OpenAICompatibleClient(openai_profile(), transport=transport)

        result = client.available_models()

        self.assertEqual(result, {"models": [{"name": "ling-3.0-tiny-q6k"}]})
        self.assertEqual(transport.requests[0]["method"], "GET")
        self.assertEqual(transport.requests[0]["path"], "/v1/models")

    def test_http_error_is_normalized(self):
        transport = FakeTransport([(503, b'{"error":"server busy"}')])
        client = OpenAICompatibleClient(openai_profile(), transport=transport)

        with self.assertRaises(OllamaError) as ctx:
            client.chat([{"role": "user", "content": "hi"}])

        self.assertEqual(ctx.exception.kind, "http")

    def test_http_error_unwraps_openai_error_object(self):
        transport = FakeTransport(
            [(500, b'{"error":{"message":"model overloaded","type":"server_error"}}')]
        )
        client = OpenAICompatibleClient(openai_profile(), transport=transport)

        with self.assertRaises(OllamaError) as ctx:
            client.chat([{"role": "user", "content": "hi"}])

        self.assertEqual(ctx.exception.kind, "http")
        self.assertIn("model overloaded", str(ctx.exception))

    def test_loaded_models_is_unsupported_not_silent(self):
        client = OpenAICompatibleClient(openai_profile(), transport=FakeTransport([]))

        with self.assertRaises(OllamaError) as ctx:
            client.loaded_models()

        self.assertEqual(ctx.exception.kind, "unsupported")

    def test_unload_model_is_unsupported_not_silent(self):
        client = OpenAICompatibleClient(openai_profile(), transport=FakeTransport([]))

        with self.assertRaises(OllamaError) as ctx:
            client.unload_model()

        self.assertEqual(ctx.exception.kind, "unsupported")

    def test_nonfinite_timings_do_not_raise(self):
        transport = FakeTransport(
            [
                (
                    200,
                    json.dumps(
                        {
                            "choices": [
                                {"message": {"role": "assistant", "content": "done"}}
                            ],
                            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                            "timings": {"prompt_ms": "inf", "predicted_ms": "nan"},
                        }
                    ).encode("utf-8"),
                )
            ]
        )
        client = OpenAICompatibleClient(openai_profile(), transport=transport)

        result = client.chat([{"role": "user", "content": "hi"}])

        self.assertEqual(result["eval_duration"], 0)
        self.assertEqual(result["total_duration"], 0)


class BuildClientTests(unittest.TestCase):
    def test_build_client_dispatches_openai_provider(self):
        self.assertIsInstance(build_client(openai_profile()), OpenAICompatibleClient)

    def test_build_client_defaults_to_ollama(self):
        profile = ModelProfile(
            name="small-coder",
            model="qwen2.5:1.5b",
            endpoint="http://127.0.0.1:11434",
        )
        self.assertIsInstance(build_client(profile), OllamaClient)


if __name__ == "__main__":
    unittest.main()
