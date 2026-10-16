#!/usr/bin/env python3
"""No Part List's local HTTP server and SQLite persistence (standard library only)."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent
MAX_BODY = 10 * 1024 * 1024


def validate_state(state):
    if not isinstance(state, dict) or not isinstance(state.get("lists"), list):
        raise ValueError("State must contain a lists array.")
    if state.get("theme") not in ("light", "dark"):
        raise ValueError("Theme must be light or dark.")
    ids = set()
    for item in state["lists"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid list.")
        list_id = item.get("id")
        if not isinstance(list_id, str) or not list_id or list_id in ids:
            raise ValueError("List IDs must be unique nonempty strings.")
        ids.add(list_id)
        if any(not isinstance(item.get(key), str) for key in ("title", "date", "notes")):
            raise ValueError("List title, date and notes must be strings.")
        if not isinstance(item.get("tasks"), list):
            raise ValueError("Tasks must be an array.")
        for task in item["tasks"]:
            if (not isinstance(task, dict) or not isinstance(task.get("text"), str)
                    or not isinstance(task.get("done"), bool)):
                raise ValueError("Invalid task.")
    if state.get("currentId") not in ids and not (not ids and state.get("currentId") is None):
        raise ValueError("Current list must exist.")
    return state


def initialize_database(path):
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS app_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            revision INTEGER NOT NULL,
            data TEXT NOT NULL
        )""")
        db.execute("INSERT OR IGNORE INTO app_state VALUES (1, 0, 'null')")


def make_handler(database):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, body, content_type="application/json; charset=utf-8"):
            data = json.dumps(body).encode() if content_type.startswith("application/json") else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                return self.respond(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path != "/api/state":
                return self.respond(404, {"error": "Not found"})
            with sqlite3.connect(database) as db:
                revision, data = db.execute("SELECT revision, data FROM app_state WHERE id = 1").fetchone()
            self.respond(200, {"revision": revision, "state": json.loads(data)})

        def do_PUT(self):
            if self.path != "/api/state":
                return self.respond(404, {"error": "Not found"})
            # JSON-only requests prevent cross-origin form submissions.
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                return self.respond(415, {"error": "Expected application/json"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    return self.respond(413, {"error": "Request must be between 1 byte and 10 MiB"})
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or type(payload.get("revision")) is not int:
                    raise ValueError("Expected an integer revision.")
                state = validate_state(payload.get("state"))
            except (ValueError, UnicodeDecodeError) as exc:
                return self.respond(400, {"error": str(exc)})
            with sqlite3.connect(database) as db:
                result = db.execute(
                    "UPDATE app_state SET data = ?, revision = revision + 1 WHERE id = 1 AND revision = ?",
                    (json.dumps(state), payload["revision"]),
                )
                if result.rowcount != 1:
                    return self.respond(409, {"error": "Data changed in another tab. Export your changes before reloading."})
            self.respond(200, {"revision": payload["revision"] + 1})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1998)
    parser.add_argument("--database", type=Path, default=ROOT / "no_part_list.sqlite3")
    args = parser.parse_args()
    initialize_database(args.database)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.database))
    print(f"No Part List: http://{args.host}:{args.port} (database: {args.database})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
