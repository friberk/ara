"""The demo runs built code behind a Caddy that only answers Purdue clients (ARA-107)."""

import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from test_compose_retrieval import ROOT, compose_services

DEPLOY = ("compose.yaml", "compose.deploy.yaml")
BACKEND = {"api", "worker", "migrate", "storage-init"}
# Prefixes announced by Purdue University's AS17 (RIPEstat announced-prefixes, 2026-10-10).
# Campus and VPN clients reach the internet from these addresses.
PURDUE = {
    "128.10.0.0/16",
    "128.46.0.0/16",
    "128.210.0.0/16",
    "128.211.0.0/16",
    "192.5.40.0/24",
    "192.5.48.0/24",
    "192.5.91.0/24",
    "192.5.102.0/24",
    "192.12.63.0/24",
    "192.31.0.0/24",
    "2607:ac80::/32",
    "2001:18e8:800::/44",
}
# Health checks on the server itself.
LOOPBACK = {"127.0.0.1/8", "::1"}
UPLOAD_LIMIT = 25 * 1024 * 1024


def caddy_image() -> str:
    lines = (ROOT / "docker/caddy.Dockerfile").read_text().splitlines()
    return [line.split()[1] for line in lines if line.startswith("FROM caddy:")][-1]


def walk(node):
    yield node
    children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()
    for child in children:
        yield from walk(child)


def adapted_caddyfile() -> dict:
    result = subprocess.run(
        [
            "docker", "run", "--rm", "-e", "SITE_ADDRESS=demo.example.org",
            "-v", f"{ROOT / 'docker/Caddyfile'}:/etc/caddy/Caddyfile:ro",
            caddy_image(), "caddy", "adapt", "--config", "/etc/caddy/Caddyfile",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


class DeployComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.services = compose_services(*DEPLOY, SITE_ADDRESS="demo.example.org")

    def test_backend_runs_the_image_code_without_reload_or_runtime_installs(self):
        for name in BACKEND:
            service = self.services[name]
            binds = [volume for volume in service.get("volumes", []) if volume["type"] == "bind"]
            self.assertEqual(binds, [], name)
            command = service["command"]
            self.assertNotIn("--reload", command, name)
            self.assertNotEqual(command[:2], ["uv", "run"], name)
            self.assertNotIn("app.jobs.development_worker", command, name)

    def test_the_vite_dev_server_does_not_start(self):
        self.assertNotIn("frontend", self.services)

    def test_caddy_sees_real_client_addresses_and_keeps_its_certificates(self):
        caddy = self.services["caddy"]
        self.assertEqual(caddy["network_mode"], "host")
        named = {volume["target"] for volume in caddy["volumes"] if volume["type"] == "volume"}
        self.assertEqual(named, {"/data", "/config"})
        self.assertEqual(caddy["depends_on"]["api"]["condition"], "service_healthy")

    def test_the_api_port_stays_on_loopback(self):
        hosts = {port["host_ip"] for port in self.services["api"]["ports"]}
        self.assertEqual(hosts, {"127.0.0.1"})


class CaddyfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = adapted_caddyfile()

    def test_only_purdue_prefixes_and_loopback_are_allowed(self):
        ranges = {
            cidr
            for node in walk(self.config)
            if isinstance(node, dict) and "remote_ip" in node
            for cidr in node["remote_ip"]["ranges"]
        }
        self.assertEqual(ranges, PURDUE | LOOPBACK)

    def test_uploads_up_to_the_app_limit_pass_the_proxy(self):
        limits = [
            node["max_size"]
            for node in walk(self.config)
            if isinstance(node, dict) and node.get("handler") == "request_body"
        ]
        self.assertEqual(len(limits), 1)
        self.assertGreater(limits[0], UPLOAD_LIMIT)

    def test_api_requests_go_to_the_published_api_port(self):
        dials = {
            upstream["dial"]
            for node in walk(self.config)
            if isinstance(node, dict) and node.get("handler") == "reverse_proxy"
            for upstream in node["upstreams"]
        }
        self.assertEqual(dials, {"127.0.0.1:8000"})


class CaddySiteTests(unittest.TestCase):
    """Runs the real Caddyfile; the host reaches it through Docker's port mapping, not loopback."""

    @classmethod
    def setUpClass(cls):
        site = tempfile.TemporaryDirectory()
        cls.addClassCleanup(site.cleanup)
        Path(site.name, "index.html").write_text("<title>ARA shell</title>")
        Path(site.name, "app.js").write_text("console.log('bundled asset')")
        started = subprocess.run(
            [
                "docker", "run", "-d", "--rm", "-e", "SITE_ADDRESS=http://:8080",
                "-p", "127.0.0.1::8080",
                "-v", f"{ROOT / 'docker/Caddyfile'}:/etc/caddy/Caddyfile:ro",
                "-v", f"{site.name}:/srv:ro",
                caddy_image(),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        cls.container = started.stdout.strip()
        cls.addClassCleanup(
            subprocess.run, ["docker", "rm", "-f", cls.container], capture_output=True
        )
        port = subprocess.run(
            ["docker", "port", cls.container, "8080/tcp"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split(":")[-1].strip()
        cls.outside = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        while True:
            try:
                urllib.request.urlopen(cls.outside, timeout=2).close()
                break
            except urllib.error.HTTPError:
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)

    def from_loopback(self, path: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", "exec", self.container, "wget", "-qO-", f"http://127.0.0.1:8080{path}"],
            capture_output=True,
            text=True,
        )

    def test_clients_outside_purdue_are_refused_with_a_reason(self):
        with self.assertRaises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(f"{self.outside}/papers/1", timeout=5)
        self.assertEqual(refused.exception.code, 403)
        self.assertIn("Purdue", refused.exception.read().decode())

    def test_client_side_routes_load_the_app_shell(self):
        result = self.from_loopback("/papers/1/chats/2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ARA shell", result.stdout)

    def test_built_assets_are_served_as_files(self):
        self.assertIn("bundled asset", self.from_loopback("/app.js").stdout)

    def test_api_and_health_paths_are_proxied_not_answered_by_the_shell(self):
        # Nothing listens on the container's 127.0.0.1:8000, so a proxied request is a 502.
        for path in ("/api/v1/documents", "/health/ready"):
            result = self.from_loopback(path)
            self.assertNotEqual(result.returncode, 0, path)
            self.assertIn("502", result.stderr, path)


if __name__ == "__main__":
    unittest.main()
