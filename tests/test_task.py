import unittest

from local_coding_agent.task import TaskEnvelope


class TaskEnvelopeTests(unittest.TestCase):
    def test_task_rejects_absolute_and_parent_paths_in_allowlist(self):
        with self.assertRaises(ValueError):
            TaskEnvelope(id="bad", goal="read", files=("../secret.txt",))

        with self.assertRaises(ValueError):
            TaskEnvelope(id="bad", goal="read", files=("C:/secret.txt",))

        with self.assertRaises(ValueError):
            TaskEnvelope(id="bad", goal="read", files="src/file.py")


if __name__ == "__main__":
    unittest.main()
