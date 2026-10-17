import json
import getpass
import io
from contextlib import redirect_stdout
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from database import connect, initialize_database, read_state
from users import check_password, configure_on_startup, create_user, password_hash, reset_password, set_active


class UserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "test.sqlite3"
        initialize_database(self.database)

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

    def test_offline_storage_scope_survives_restart_but_not_database_replacement(self):
        with connect(self.database) as db:
            original = db.execute("SELECT value FROM settings WHERE key = 'storage_scope'").fetchone()[0]
        initialize_database(self.database)
        with connect(self.database) as db:
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key = 'storage_scope'").fetchone()[0], original)
        other = Path(self.temp.name) / "other.sqlite3"
        initialize_database(other)
        with connect(other) as db:
            self.assertNotEqual(db.execute("SELECT value FROM settings WHERE key = 'storage_scope'").fetchone()[0], original)

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

    def startup(self, answers=(), *, interactive=True, password="test password", password_error=None):
        output = io.StringIO()
        with patch("users.sys.stdin.isatty", return_value=interactive), \
                patch("builtins.input", side_effect=answers) as prompt, \
                patch("users.confirmed_password", return_value=password, side_effect=password_error), \
                redirect_stdout(output):
            configure_on_startup(self.database)
        return output.getvalue(), prompt

    def test_startup_offer_creates_first_user(self):
        output, prompt = self.startup(["yes", "Alice"])
        with connect(self.database) as db:
            user = db.execute("SELECT * FROM users").fetchone()
            self.assertEqual(user["username"], "Alice")
            self.assertTrue(check_password("test password", user["password_hash"]))
        self.assertEqual(prompt.call_count, 2)
        self.assertIn("You can now sign in", output)
        self.assertNotIn("test password", output)

    def test_startup_skip_keeps_database_empty_and_provides_instructions(self):
        for answer in ("", "n", "no"):
            with self.subTest(answer=answer):
                output, prompt = self.startup([answer])
                self.assertEqual(prompt.call_count, 1)
                self.assertIn("server will keep running", output)
                self.assertIn("./startLinux.sh manage-users", output)
        with connect(self.database) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users").fetchone()[0], 0)

    def test_startup_noninteractive_never_prompts(self):
        output, prompt = self.startup(interactive=False)
        prompt.assert_not_called()
        self.assertIn("No interactive terminal", output)
        self.assertIn("server will keep running", output)

    def test_existing_or_disabled_users_suppress_startup_offer(self):
        create_user(self.database, "Alice", "test password")
        for disabled in (False, True):
            if disabled:
                set_active(self.database, "Alice", False)
            output, prompt = self.startup()
            prompt.assert_not_called()
            self.assertEqual(output, "")

    def test_cancelled_or_invalid_startup_setup_leaves_no_account(self):
        for error in (EOFError(), KeyboardInterrupt(), getpass.GetPassWarning(), ValueError("Passwords do not match.")):
            with self.subTest(error=type(error).__name__):
                output, _ = self.startup(["y", "Alice"], password_error=error)
                self.assertIn("server will keep running", output)
        output, _ = self.startup(["y", "Alice"], password="short")
        self.assertIn("Setup did not complete", output)
        with connect(self.database) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users").fetchone()[0], 0)

    def test_startup_cannot_create_second_account_after_concurrent_setup(self):
        create_user(self.database, "Alice", "test password")
        with self.assertRaisesRegex(ValueError, "during setup"):
            create_user(self.database, "Bob", "test password", only_if_empty=True)
        with connect(self.database) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
