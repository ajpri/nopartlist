import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import build_opener, ProxyHandler


ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(sys.platform == 'win32', 'Windows launcher requires Windows')
class WindowsLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='list launcher ')
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        for name in ('startWindows.ps1', 'startWindows.bat', 'server.py', 'index.html',
                     'login.html', 'auth.py', 'database.py', 'users.py'):
            shutil.copy2(ROOT / name, self.project / name)
        self.env = {**os.environ, 'PYTHON': sys.executable}

    def command(self, *args):
        return ['cmd.exe', '/d', '/c', str(self.project / 'startWindows.bat'), *args]

    def run_launcher(self, *args, env=None, input=None):
        return subprocess.run(self.command(*args), cwd=ROOT.parent, env=env or self.env,
                              input=input, capture_output=True, text=True, timeout=20)

    def free_port(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return str(sock.getsockname()[1])

    def test_check_from_another_directory_is_read_only(self):
        result = self.run_launcher('--check', '--port', self.free_port())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Checks passed', result.stdout)
        self.assertFalse((self.project / 'no_part_list.sqlite3').exists())

    def test_occupied_port(self):
        with socket.socket() as sock:
            sock.bind(('0.0.0.0', 0))
            sock.listen()
            result = self.run_launcher('--check', '--port', str(sock.getsockname()[1]))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unavailable', result.stderr)

    def test_invalid_arguments(self):
        for args in (('--port',), ('--port', '0'), ('--port', '65536'),
                     ('--port', 'hello'), ('--unknown',)):
            with self.subTest(args=args):
                self.assertNotEqual(self.run_launcher(*args).returncode, 0)

    def test_missing_file_and_dependency(self):
        (self.project / 'index.html').unlink()
        result = self.run_launcher('--check')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing index.html', result.stderr)
        result = self.run_launcher('--yes', '--check', env={**self.env, 'PYTHON': 'missing-python.exe'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Dependency check failed', result.stderr)
        self.assertFalse((self.project / 'no_part_list.sqlite3').exists())

    def test_manage_users_ignores_occupied_server_port(self):
        with socket.socket() as sock:
            sock.bind(('0.0.0.0', 0))
            sock.listen()
            result = self.run_launcher('manage-users', '--port', str(sock.getsockname()[1]), input='6\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('List users', result.stdout)
        self.assertNotIn('Starting No Part List', result.stdout)

    def test_startup_serves_http(self):
        port = self.free_port()
        process = subprocess.Popen(self.command('--port', port, '--secure-cookie'),
                                   cwd=ROOT.parent, env=self.env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            opener = build_opener(ProxyHandler({}))
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    self.fail(f'Launcher exited: {process.communicate()}')
                try:
                    with opener.open(f'http://127.0.0.1:{port}/api/session', timeout=0.3) as response:
                        session = json.load(response)
                        self.assertIsNone(session['user'])
                        self.assertTrue(session['setupRequired'])
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                self.fail('Server did not become ready')
        finally:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            process.communicate(timeout=10)


if __name__ == '__main__':
    unittest.main()
