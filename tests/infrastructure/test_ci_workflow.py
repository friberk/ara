"""CI verifies main and pull requests, then deploys main to the Purdue-only demo (ARA-107)."""

import json
import subprocess
import unittest

from test_compose_retrieval import ROOT

WORKFLOW = ROOT / ".github/workflows/ci.yaml"
LOAD = "import json, sys, yaml; print(json.dumps(yaml.safe_load(open(sys.argv[1]))))"


def workflow() -> dict:
    result = subprocess.run(
        ["uv", "run", "--no-project", "--quiet", "--with", "pyyaml==6.0.3",
         "python", "-c", LOAD, str(WORKFLOW)],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    # YAML 1.1 reads the bare key `on` as a Boolean.
    data["on"] = data.pop("true", data.get("on"))
    return data


def runs(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


class CiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = workflow()
        cls.jobs = cls.workflow["jobs"]

    def test_runs_for_main_pull_requests_and_manual_dispatch_only(self):
        self.assertEqual(
            self.workflow["on"],
            {"push": {"branches": ["main"]}, "pull_request": None, "workflow_dispatch": None},
        )

    def test_a_newer_run_on_the_same_ref_supersedes_the_older_one(self):
        self.assertIn("github.ref", self.workflow["concurrency"]["group"])

    def test_browser_checks_get_both_synthetic_papers(self):
        commands = runs(self.jobs["verify"])
        self.assertIn("create_pdf.py /tmp/ara-fixtures/research.pdf", commands)
        self.assertIn("create_pdf.py --second /tmp/ara-fixtures/second.pdf", commands)

    def test_deploy_waits_for_verify_and_only_runs_for_main(self):
        deploy = self.jobs["deploy"]
        self.assertEqual(deploy["needs"], "verify")
        self.assertIn("refs/heads/main", deploy["if"])
        self.assertIn("pull_request", deploy["if"])
        self.assertEqual(deploy["environment"], "production")
        self.assertFalse(deploy["concurrency"]["cancel-in-progress"])

    def test_deploy_uses_the_shared_script_and_checks_that_outsiders_are_refused(self):
        commands = runs(self.jobs["deploy"])
        self.assertIn("scripts/deploy.sh", commands)
        self.assertIn("403", commands)

    def test_secrets_reach_commands_only_through_the_environment(self):
        for name, job in self.jobs.items():
            for step in job["steps"]:
                self.assertNotIn("secrets.", step.get("run", ""), f"{name}: {step.get('name')}")


if __name__ == "__main__":
    unittest.main()
