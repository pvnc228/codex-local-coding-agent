import unittest

from local_coding_agent.profiles import get_profile, list_profiles


class ModelProfileTests(unittest.TestCase):
    def test_builtin_profiles_are_named_and_have_bounded_defaults(self):
        names = list_profiles()

        self.assertEqual(names, ("bonsai-64k", "qwen2.5-1.5b", "qwen2.5-coder"))
        profile = get_profile("qwen2.5-coder")
        self.assertEqual(profile.model, "qwen2.5-coder:latest")
        self.assertFalse(profile.think)
        self.assertEqual(profile.temperature, 0)
        self.assertLessEqual(profile.num_ctx, 8192)
        self.assertLessEqual(profile.num_predict, 512)

    def test_profile_endpoint_can_be_overridden_without_mutating_registry(self):
        profile = get_profile("qwen2.5-1.5b", endpoint="http://127.0.0.1:9999")

        self.assertEqual(profile.endpoint, "http://127.0.0.1:9999")
        self.assertEqual(get_profile("qwen2.5-1.5b").endpoint, "http://127.0.0.1:11434")


if __name__ == "__main__":
    unittest.main()
