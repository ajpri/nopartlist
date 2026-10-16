import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from server import initialize_database, make_handler
from database import connect
from users import create_user, reset_password, set_active
from support import Client
from unittest.mock import patch
from auth import SESSION_SECONDS
import time


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "test.sqlite3"
        create_user(self.database, "alice", "test password")
        self.state = {
            "currentId": "one", "theme": "dark", "lists": [
                {"id": "one", "title": "A list", "date": "2026-10-15",
                 "notes": "Some notes", "tasks": [{"text": "A task", "done": True}]}
            ],
        }
        self.start_server()

    def start_server(self):
        initialize_database(self.database)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.database))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.client = Client(self.url)
        self.client.login("alice")

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop_server()
        self.temp.cleanup()

    def request(self, path="/api/state", payload=None):
        return self.client.request(path, payload)

    def test_round_trip_and_restart(self):
        self.assertEqual(json.loads(self.request()[1]), {"revision": 0, "state": None})
        self.assertEqual(self.request(payload={"revision": 0, "state": self.state})[0], 200)
        self.stop_server()
        self.start_server()
        self.assertEqual(json.loads(self.request()[1]), {"revision": 1, "state": self.state})

    def test_stale_writer_cannot_overwrite(self):
        self.request(payload={"revision": 0, "state": self.state})
        changed = copy.deepcopy(self.state)
        changed["lists"][0]["title"] = "Stale edit"
        self.assertEqual(self.request(payload={"revision": 0, "state": changed})[0], 409)
        self.assertEqual(json.loads(self.request()[1])["state"], self.state)

    def test_invalid_data_does_not_replace_saved_state(self):
        self.request(payload={"revision": 0, "state": self.state})
        for invalid in (None, {}, {**self.state, "currentId": "missing"},
                        {**self.state, "currentId": []},
                        {**self.state, "lists": self.state["lists"] * 2}):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.request(payload={"revision": 1, "state": invalid})[0], 400)
        self.assertEqual(json.loads(self.request()[1])["state"], self.state)

    def test_only_app_and_api_are_exposed(self):
        self.assertIn(b"No Part List", self.request("/")[1])
        for path in ("/server.py", "/test.sqlite3", "/../server.py", "/.git/config"):
            self.assertEqual(self.request(path)[0], 404)

    def test_unauthenticated_api_and_login_page(self):
        anonymous = Client(self.url)
        self.assertEqual(anonymous.request()[0], 401)
        self.assertEqual(anonymous.request(payload={"revision": 0, "state": self.state})[0], 401)
        self.assertIn(b"Sign In", anonymous.request("/")[1])
        self.assertNotIn(b'id="tasks"', anonymous.request("/index.html")[1])

    def test_each_user_has_independent_lists_and_preferences(self):
        create_user(self.database, "bob", "test password")
        self.request(payload={"revision": 0, "state": self.state})
        bob = Client(self.url)
        bob.login("bob")
        self.assertEqual(json.loads(bob.request()[1]), {"revision": 0, "state": None})
        bob_state = copy.deepcopy(self.state)
        bob_state["theme"] = "light"
        bob_state["lists"][0]["title"] = "Bob's private list"
        self.assertEqual(bob.request(payload={"revision": 0, "state": bob_state})[0], 200)
        self.assertEqual(json.loads(self.request()[1])["state"], self.state)
        self.assertEqual(json.loads(bob.request()[1])["state"], bob_state)
        # A caller cannot select another user's storage using query/body fields.
        self.assertEqual(json.loads(bob.request("/api/state?userId=1")[1])["state"], bob_state)
        bob.request(payload={"revision": 1, "state": bob_state, "userId": 1})
        self.assertEqual(json.loads(self.request()[1])["state"], self.state)

    def test_csrf_and_stale_tab_cannot_write_to_another_account(self):
        self.assertEqual(self.client.request(payload={"revision": 0, "state": self.state}, csrf=False)[0], 403)
        old_csrf = self.client.csrf
        create_user(self.database, "bob", "test password")
        self.client.login("bob")
        self.client.csrf = old_csrf
        self.assertEqual(self.request(payload={"revision": 0, "state": self.state})[0], 403)
        self.assertEqual(self.request()[0], 403)

    def test_168_hour_expiry_and_cookie_flags(self):
        now = time.time()
        with patch("auth.time.time", return_value=now):
            self.client.login("alice")
            session = json.loads(self.client.request("/api/session")[1])
            self.assertEqual(session["expiresAt"], now + SESSION_SECONDS)
        # The cookie jar retains cookies at the real clock time; move only the server clock.
        with patch("auth.time.time", return_value=now + SESSION_SECONDS - 1):
            self.assertEqual(self.request()[0], 200)
        with patch("auth.time.time", return_value=now + SESSION_SECONDS):
            self.assertEqual(self.request()[0], 401)
        cookie = self.server.RequestHandlerClass.auth.cookie("test", SESSION_SECONDS)
        for flag in ("HttpOnly", "SameSite=Lax", "Max-Age=604800", "Path=/"):
            self.assertIn(flag, cookie)
        self.server.RequestHandlerClass.auth.secure_cookie = True
        self.assertIn("Secure", self.server.RequestHandlerClass.auth.cookie("test", SESSION_SECONDS))

    def test_logout_and_restart_revoke_sessions(self):
        old_client = self.client
        self.assertEqual(old_client.request("/api/logout", {}, method="POST")[0], 200)
        self.assertEqual(old_client.request()[0], 401)
        old_client.login("alice")
        self.stop_server()
        self.start_server()
        old_client.url = self.url
        self.assertEqual(old_client.request()[0], 401)

    def test_password_reset_and_disable_revoke_sessions_without_losing_lists(self):
        self.request(payload={"revision": 0, "state": self.state})
        reset_password(self.database, "alice", "new password")
        self.assertEqual(self.request()[0], 401)
        self.client.login("alice", "new password")
        set_active(self.database, "alice", False)
        self.assertEqual(self.request()[0], 401)
        set_active(self.database, "alice", True)
        self.client.login("alice", "new password")
        self.assertEqual(json.loads(self.request()[1])["state"], self.state)

    def test_login_requires_csrf_and_limits_failed_attempts(self):
        anonymous = Client(self.url)
        payload = {"username": "alice", "password": "wrong password"}
        self.assertEqual(anonymous.request("/api/login", payload, method="POST")[0], 403)
        _, body = anonymous.request("/api/session")
        anonymous.csrf = json.loads(body)["csrfToken"]
        for _ in range(5):
            self.assertEqual(anonymous.request("/api/login", payload, method="POST")[0], 401)
        self.assertEqual(anonymous.request("/api/login", payload, method="POST")[0], 429)

    def test_list_identity_survives_edit(self):
        self.request(payload={"revision": 0, "state": self.state})
        with connect(self.database) as db:
            original = db.execute("SELECT id FROM lists").fetchone()[0]
        self.request(payload={"revision": 1, "state": self.state})
        with connect(self.database) as db:
            self.assertEqual(db.execute("SELECT id FROM lists").fetchone()[0], original)


if __name__ == "__main__":
    unittest.main()
