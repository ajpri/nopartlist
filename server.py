#!/usr/bin/env python3
"""No Part List's local HTTP server and SQLite persistence (standard library only)."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from auth import Authentication
from database import DEFAULT_DATABASE, connect, initialize_database, read_state, write_state
from users import validate_username

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
    current_id = state.get("currentId")
    if not isinstance(current_id, (str, type(None))):
        raise ValueError("Current list must be a string ID or null.")
    if current_id not in ids and not (not ids and current_id is None):
        raise ValueError("Current list must exist.")
    return state


def make_handler(database, secure_cookie=False):
    # A fresh handler factory belongs to one server run, so sessions never survive restart.
    authentication = Authentication(database, secure_cookie)

    class Handler(BaseHTTPRequestHandler):
        auth = authentication

        def respond(self, status, body, content_type="application/json; charset=utf-8", cookie=None):
            data = json.dumps(body).encode() if content_type.startswith("application/json") else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(data)

        def session(self):
            return self.auth.get_session(self.headers.get("Cookie"))

        def require_user(self, csrf=True):
            token, session = self.session()
            if not session or not session.get("userId"):
                self.respond(401, {"error": "Sign in required. Your session may have expired or the server restarted."})
                return None
            if csrf and not self.auth.csrf_valid(session, self.headers.get("X-CSRF-Token", "")):
                self.respond(403, {"error": "Session changed. Export unsaved edits, then reload and sign in again."})
                return None
            return token, session

        def read_json(self):
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                self.respond(415, {"error": "Expected application/json"})
                return None
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    self.respond(413, {"error": "Request must be between 1 byte and 10 MiB"})
                    return None
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object.")
                return payload
            except (ValueError, UnicodeDecodeError) as exc:
                self.respond(400, {"error": str(exc)})
                return None

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                _, session = self.session()
                filename = "index.html" if session and session.get("userId") else "login.html"
                return self.respond(200, (ROOT / filename).read_bytes(), "text/html; charset=utf-8")
            if path == "/api/session":
                token, session = self.session()
                cookie = None
                if not session:
                    try:
                        session, cookie = self.auth.new_session(token)
                    except ValueError as exc:
                        return self.respond(429, {"error": str(exc)})
                with connect(database) as db:
                    setup_required = not db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
                return self.respond(200, {
                    "user": {"id": session["userId"], "username": session["username"]} if session.get("userId") else None,
                    "csrfToken": session["csrfToken"], "expiresAt": session["expiresAt"],
                    "setupRequired": setup_required,
                }, cookie=cookie)
            if path != "/api/state":
                return self.respond(404, {"error": "Not found"})
            authorized = self.require_user()
            if authorized:
                with connect(database) as db:
                    revision, state = read_state(db, authorized[1]["userId"])
                self.respond(200, {"revision": revision, "state": state})

        def do_POST(self):
            if self.path not in ("/api/login", "/api/logout"):
                return self.respond(404, {"error": "Not found"})
            payload = self.read_json()
            if payload is None:
                return
            token, session = self.session()
            if not self.auth.csrf_valid(session, self.headers.get("X-CSRF-Token", "")):
                return self.respond(403, {"error": "Sign-in form expired. Reload and try again."})
            if self.path == "/api/logout":
                self.auth.logout(token)
                return self.respond(200, {"status": "ok"}, cookie=self.auth.cookie("", 0))
            username, password = payload.get("username"), payload.get("password")
            if not isinstance(username, str) or not isinstance(password, str) or len(username) > 64:
                return self.respond(400, {"error": "Username and password are required."})
            try:
                username = validate_username(username)
            except ValueError:
                return self.respond(400, {"error": "Invalid username."})
            user, status = self.auth.login(username, password, self.client_address[0])
            if status != 200:
                message = "Please wait a minute before trying again." if status == 429 else "Invalid username or password."
                return self.respond(status, {"error": message})
            try:
                _, cookie = self.auth.new_session(token, user)
            except ValueError as exc:
                return self.respond(429, {"error": str(exc)})
            self.respond(200, {"status": "ok"}, cookie=cookie)

        def do_PUT(self):
            if self.path != "/api/state":
                return self.respond(404, {"error": "Not found"})
            authorized = self.require_user()
            if not authorized:
                return
            session = authorized[1]
            payload = self.read_json()
            if payload is None:
                return
            try:
                if type(payload.get("revision")) is not int:
                    raise ValueError("Expected an integer revision.")
                state = validate_state(payload.get("state"))
            except ValueError as exc:
                return self.respond(400, {"error": str(exc)})
            with connect(database) as db:
                db.execute("BEGIN IMMEDIATE")
                # Password resets and disabling a user revoke even an in-flight write.
                user = db.execute("SELECT active, auth_version FROM users WHERE id = ?", (session["userId"],)).fetchone()
                if not user or not user["active"] or user["auth_version"] != session["authVersion"]:
                    return self.respond(401, {"error": "Session revoked. Sign in again."})
                if not write_state(db, session["userId"], payload["revision"], state):
                    return self.respond(409, {"error": "Data changed in another tab. Export your changes before reloading."})
            self.respond(200, {"revision": payload["revision"] + 1})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=1998)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--secure-cookie", action="store_true", help="Use Secure cookies when deployed behind HTTPS")
    args = parser.parse_args()
    initialize_database(args.database)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.database, args.secure_cookie))
    with connect(args.database) as db:
        if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            print("No users configured. Run ./startLinux.sh manage-users or python3 users.py create USERNAME.", flush=True)
    print(f"No Part List: http://{args.host}:{args.port} (database: {args.database})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
