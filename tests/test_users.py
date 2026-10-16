import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from database import connect, read_state
from users import check_password, create_user, password_hash, reset_password


class UserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "test.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_lists_assigned_only_to_first_user_and_survive_reinitialization(self):
        state = {"currentId": "legacy", "theme": "light", "lists": [
            {"id": "legacy", "title": "Existing", "date": "2026-10-15", "notes": "Keep me", "tasks": []}
        ]}
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE app_state (id INTEGER PRIMARY KEY, revision INTEGER, data TEXT)")
            db.execute("INSERT INTO app_state VALUES (1, 42, ?)", (json.dumps(state),))
        first = create_user(self.database, "Alice", "test password")
        second = create_user(self.database, "Bob", "test password")
        with connect(self.database) as db:
            self.assertEqual(read_state(db, first), (42, state))
            self.assertEqual(read_state(db, second), (0, None))
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name = 'app_state'").fetchone())
            self.assertEqual(db.execute("SELECT owner_id FROM lists").fetchone()[0], first)

    def test_passwords_are_salted_and_verified(self):
        one = password_hash("test password")
        two = password_hash("test password")
        self.assertNotEqual(one, two)
        self.assertNotIn("test password", one)
        self.assertTrue(check_password("test password", one))
        self.assertFalse(check_password("wrong password", one))
        self.assertFalse(check_password("x" * 129, one))
        self.assertFalse(check_password("\ud800", one))

    def test_user_validation_and_case_insensitive_uniqueness(self):
        create_user(self.database, "Alice", "test password")
        for username, password in ((" alice ", "test password"), ("", "test password"),
                                   ("bad\nname", "test password"), ("bob", "short")):
            with self.subTest(username=username):
                with self.assertRaises(ValueError):
                    create_user(self.database, username, password)
        with self.assertRaises(ValueError):
            reset_password(self.database, "missing", "test password")

    def test_cli_list_and_disable_do_not_start_server_or_print_passwords(self):
        create_user(self.database, "Alice", "test password")
        script = str(Path(__file__).resolve().parent.parent / "users.py")
        for args in (("disable", "Alice"), ("list",)):
            result = subprocess.run([sys.executable, script, "--database", str(self.database), *args],
                                    capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("test password", result.stdout)
        self.assertIn("Alice (disabled)", result.stdout)


if __name__ == "__main__":
    unittest.main()
