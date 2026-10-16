import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent.parent


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="list launcher ")
        self.project = Path(self.temp.name)
        for name in ("startLinux.sh", "server.py", "index.html"):
            shutil.copy2(ROOT / name, self.project / name)
        self.env = {**os.environ, "PYTHON": sys.executable}

    def tearDown(self):
        self.temp.cleanup()

    def run_launcher(self, *args, env=None):
        return subprocess.run([str(self.project / "startLinux.sh"), *args],
                              cwd="/tmp", env=env or self.env, capture_output=True,
                              text=True, timeout=10)

    def free_port(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def test_check_is_read_only_from_another_directory(self):
        result = self.run_launcher("--check", "--port", str(self.free_port()))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Checks passed", result.stdout)
        self.assertFalse((self.project / "no_part_list.sqlite3").exists())

    def test_occupied_port_has_clear_error(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            result = self.run_launcher("--check", "--port", str(sock.getsockname()[1]))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unavailable", result.stderr)

    def test_invalid_arguments(self):
        for args in (("--port",), ("--port", "0"), ("--port", "65536"),
                     ("--port", "hello"), ("--unknown",)):
            with self.subTest(args=args):
                self.assertNotEqual(self.run_launcher(*args).returncode, 0)

    def test_dependency_install_requires_consent_and_check_never_installs(self):
        # Fake package tools: this test never installs system software.
        bin_dir = self.project / "bin"
        bin_dir.mkdir()
        python = bin_dir / "test-python"
        installer = bin_dir / "apt-get"
        installer.write_text('''#!/bin/bash
echo "$*" >> "$INSTALL_LOG"
if [[ $1 == install ]]; then
    printf '#!/bin/bash\\nexit 0\\n' > "$PYTHON"
    chmod +x "$PYTHON"
fi
''')
        installer.chmod(0o755)
        sudo = bin_dir / "sudo"
        sudo.write_text('#!/bin/bash\nexec "$@"\n')
        sudo.chmod(0o755)
        log = self.project / "install.log"
        env = {**self.env, "PATH": f"{bin_dir}:/usr/bin:/bin",
               "PYTHON": str(python), "INSTALL_LOG": str(log)}
        check = self.run_launcher("--yes", "--check", env=env)
        self.assertNotEqual(check.returncode, 0)
        self.assertFalse(log.exists())
        declined = self.run_launcher(env=env)
        self.assertNotEqual(declined.returncode, 0)
        self.assertIn("Noninteractive", declined.stderr)
        self.assertFalse(log.exists())
        accepted = self.run_launcher("--yes", env=env)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(log.read_text().splitlines(), ["update", "install -y python3 libpython3-stdlib"])

    def test_startup_http_and_shutdown(self):
        port = self.free_port()
        process = subprocess.Popen(
            [str(self.project / "startLinux.sh"), "--port", str(port)],
            cwd="/tmp", env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    self.fail(f"Launcher exited: {process.communicate()}")
                try:
                    with urlopen(f"http://127.0.0.1:{port}/api/state", timeout=0.3) as response:
                        self.assertEqual(json.load(response), {"revision": 0, "state": None})
                    break
                except (OSError, URLError):
                    time.sleep(0.05)
            else:
                self.fail("Server did not become ready")
            process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn("Press Ctrl+C to stop", stdout)
            self.assertIn(f"0.0.0.0:{port}", stdout)
            with socket.socket() as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", port))
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()


if __name__ == "__main__":
    unittest.main()
