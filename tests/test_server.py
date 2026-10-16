import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from server import initialize_database, make_handler


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "test.sqlite3"
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

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop_server()
        self.temp.cleanup()

    def request(self, path="/api/state", payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(self.url + path, data=data,
                          method="GET" if data is None else "PUT",
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

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
                        {**self.state, "lists": self.state["lists"] * 2}):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.request(payload={"revision": 1, "state": invalid})[0], 400)
        self.assertEqual(json.loads(self.request()[1])["state"], self.state)

    def test_only_app_and_api_are_exposed(self):
        self.assertIn(b"No Part List", self.request("/")[1])
        for path in ("/server.py", "/test.sqlite3", "/../server.py", "/.git/config"):
            self.assertEqual(self.request(path)[0], 404)


if __name__ == "__main__":
    unittest.main()
