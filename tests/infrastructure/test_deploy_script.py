"""scripts/deploy.sh ships the committed tree and never touches the server's .env (ARA-107)."""

import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from test_compose_retrieval import ROOT

SCRIPT = ROOT / "scripts/deploy.sh"
TARGET = "ara-deploy@203.0.113.7"
# Records each ssh call's arguments and standard input instead of connecting.
FAKE_SSH = """#!/bin/sh
n=$(ls "$SSH_LOG" | grep -c args)
printf '%s\\n' "$@" > "$SSH_LOG/$n.args"
cat > "$SSH_LOG/$n.stdin"
"""


class DeployScriptTests(unittest.TestCase):
    def deploy(self, *arguments, **env):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        stub, log = Path(directory.name, "bin"), Path(directory.name, "log")
        stub.mkdir()
        log.mkdir()
        (stub / "ssh").write_text(FAKE_SSH)
        (stub / "ssh").chmod(0o755)
        result = subprocess.run(
            ["bash", str(SCRIPT), *arguments],
            cwd=ROOT,
            env={**os.environ, "PATH": f"{stub}:{os.environ['PATH']}", "SSH_LOG": str(log), **env},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        calls = [
            (path.read_text().splitlines(), path.with_suffix(".stdin").read_bytes())
            for path in sorted(log.glob("*.args"))
        ]
        return result, calls

    def test_ships_the_committed_tree_and_rebuilds_with_the_env_kept(self):
        result, calls = self.deploy(TARGET, SITE_HOST="demo.example.org")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(calls)
        self.assertEqual({arguments[0] for arguments, _ in calls}, {TARGET})
        shipped = [stdin for _, stdin in calls if stdin]
        self.assertEqual(len(shipped), 1)
        with tarfile.open(fileobj=io.BytesIO(shipped[0])) as archive:
            names = set(archive.getnames())
        self.assertIn("compose.yaml", names)
        self.assertNotIn(".env", names)
        self.assertFalse({name for name in names if name.startswith(".superpowers")})
        remote = "\n".join(line for arguments, _ in calls for line in arguments[1:])
        self.assertIn("--delete", remote)
        self.assertIn("--exclude=/.env", remote)
        self.assertIn("up -d --build --wait --remove-orphans", remote)
        self.assertIn("--resolve demo.example.org:443:127.0.0.1", remote)

    def test_refuses_to_run_without_a_target_or_site(self):
        for arguments, env in (((), {"SITE_HOST": "demo.example.org"}), ((TARGET,), {})):
            result, calls = self.deploy(*arguments, **{"SITE_HOST": "", **env})
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
