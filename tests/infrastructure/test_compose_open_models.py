"""Open models run only with the open-models profile and the experimental flag (ARA-090)."""

from pathlib import Path
import unittest

from test_compose_retrieval import compose_services

OPEN_MODEL_SERVICES = {"ollama", "model-worker"}


def flags(services) -> dict:
    return {
        name: service["environment"].get("EXPERIMENTAL_OPEN_MODELS")
        for name, service in services.items()
        if name in {"api", "worker", "model-worker"}
    }


class ComposeOpenModelTests(unittest.TestCase):
    def test_default_stack_has_no_open_model_services_and_the_flag_off(self):
        services = compose_services("compose.yaml")
        self.assertFalse(OPEN_MODEL_SERVICES & set(services))
        self.assertEqual(flags(services), {"api": "false", "worker": "false"})

    def test_profile_and_flag_bring_back_the_runtime_and_its_worker(self):
        services = compose_services(
            "compose.yaml", COMPOSE_PROFILES="open-models", EXPERIMENTAL_OPEN_MODELS="true"
        )
        self.assertLessEqual(OPEN_MODEL_SERVICES, set(services))
        self.assertEqual(set(flags(services).values()), {"true"})

    def test_weights_volume_is_kept_while_the_profile_is_off(self):
        compose = (Path(__file__).resolve().parents[2] / "compose.yaml").read_text()
        self.assertIn("\n  ollama-models:\n", compose.split("\nvolumes:\n", 1)[1])

    def test_suites_pin_the_flag_off_and_browser_fixtures_turn_it_on(self):
        tests = compose_services("compose.yaml", "compose.test.yaml")
        self.assertEqual(set(flags(tests).values()), {"false"})
        browser = compose_services("compose.yaml", "compose.test.yaml", "compose.e2e.yaml")
        self.assertIn("model-worker", browser)
        self.assertNotIn("ollama", browser)
        self.assertEqual(set(flags(browser).values()), {"true"})


if __name__ == "__main__":
    unittest.main()
