import unittest

from local_coding_agent.memory import MemoryBudgetError, ModelMemoryManager


class FakeMemoryClient:
    def __init__(self, models):
        self.models = {model["name"]: dict(model) for model in models}
        self.unloaded = []

    def loaded_models(self):
        return {"models": list(self.models.values())}

    def unload_model(self, model=None):
        target = model or ""
        self.unloaded.append(target)
        self.models.pop(target, None)
        return {"done": True, "model": target}


class MemoryManagerTests(unittest.TestCase):
    def test_snapshot_reports_total_vram_and_model_details(self):
        client = FakeMemoryClient(
            [
                {"name": "small", "size_vram": 100, "size": 200, "expires_at": "later"},
                {"name": "large", "size_vram": 300, "size": 500, "expires_at": "later"},
            ]
        )

        snapshot = ModelMemoryManager(client).snapshot()

        self.assertEqual(snapshot.total_vram_bytes, 400)
        self.assertEqual([model.name for model in snapshot.models], ["small", "large"])
        self.assertEqual(snapshot.as_dict()["total_vram_bytes"], 400)

    def test_enforce_limit_unloads_largest_unprotected_models(self):
        client = FakeMemoryClient(
            [
                {"name": "small", "size_vram": 100},
                {"name": "large", "size_vram": 300},
            ]
        )

        snapshot = ModelMemoryManager(client).enforce_limit(150, keep=("small",))

        self.assertEqual(client.unloaded, ["large"])
        self.assertEqual(snapshot.total_vram_bytes, 100)
        self.assertEqual([model.name for model in snapshot.models], ["small"])

    def test_enforce_limit_fails_when_protected_models_exceed_budget(self):
        client = FakeMemoryClient([{"name": "large", "size_vram": 300}])

        with self.assertRaisesRegex(MemoryBudgetError, "protected"):
            ModelMemoryManager(client).enforce_limit(150, keep=("large",))

    def test_unload_all_releases_every_loaded_model(self):
        client = FakeMemoryClient(
            [{"name": "one", "size_vram": 100}, {"name": "two", "size_vram": 200}]
        )

        snapshot = ModelMemoryManager(client).unload_all()

        self.assertEqual(set(client.unloaded), {"one", "two"})
        self.assertEqual(snapshot.total_vram_bytes, 0)


if __name__ == "__main__":
    unittest.main()
