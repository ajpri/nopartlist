"""Process-local sessions: stopping or restarting the server logs everyone out."""
from http.cookies import CookieError, SimpleCookie
import secrets
import threading
import time

from database import connect
from users import check_password, password_hash

SESSION_SECONDS = 168 * 3600
COOKIE_NAME = "nplSession"


class Authentication:
    def __init__(self, database, secure_cookie=False):
        self.database = database
        self.secure_cookie = secure_cookie
        self.sessions = {}
        self.attempts = {}
        self.lock = threading.RLock()
        self.dummy_hash = password_hash(secrets.token_urlsafe(32))

    def cookie(self, token, max_age):
        cookie = SimpleCookie()
        cookie[COOKIE_NAME] = token
        cookie[COOKIE_NAME]["path"] = "/"
        cookie[COOKIE_NAME]["max-age"] = max_age
        cookie[COOKIE_NAME]["httponly"] = True
        cookie[COOKIE_NAME]["samesite"] = "Lax"
        if self.secure_cookie:
            cookie[COOKIE_NAME]["secure"] = True
        return cookie.output(header="").strip()

    def get_session(self, cookie_header):
        try:
            cookie = SimpleCookie(cookie_header or "")
            token = cookie[COOKIE_NAME].value if COOKIE_NAME in cookie else ""
        except CookieError:
            token = ""
        now = time.time()
        with self.lock:
            for expired in [key for key, value in self.sessions.items() if value["expiresAt"] <= now]:
                self.sessions.pop(expired, None)
            session = self.sessions.get(token)
            if session and session.get("userId"):
                with connect(self.database) as db:
                    user = db.execute("SELECT id, username, active, auth_version FROM users WHERE id = ?",
                                      (session["userId"],)).fetchone()
                if not user or not user["active"] or user["auth_version"] != session["authVersion"]:
                    self.sessions.pop(token, None)
                    session = None
            return token, session

    def new_session(self, old_token="", user=None):
        lifetime = SESSION_SECONDS if user else 600
        session = {"csrfToken": secrets.token_urlsafe(32), "expiresAt": time.time() + lifetime}
        if user:
            session.update(userId=user["id"], username=user["username"], authVersion=user["auth_version"])
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions.pop(old_token, None)
            if len(self.sessions) >= 10000:
                # Bound anonymous sessions without evicting signed-in users.
                for key, value in list(self.sessions.items()):
                    if not value.get("userId"):
                        del self.sessions[key]
                        break
                else:
                    raise ValueError("Too many sessions. Try again later.")
            self.sessions[token] = session
        return session, self.cookie(token, lifetime)

    def csrf_valid(self, session, received):
        return bool(session and received and secrets.compare_digest(session["csrfToken"].encode(), received.encode()))

    def login(self, username, password, address):
        now = time.time()
        with self.lock:
            for key in [key for key, value in self.attempts.items() if now - value[0] >= 60]:
                del self.attempts[key]
            attempts = self.attempts.setdefault(address, [now, 0])
            if attempts[1] >= 5:
                return None, 429
            attempts[1] += 1
        with connect(self.database) as db:
            user = db.execute("SELECT * FROM users WHERE username_key = ?", (username.strip().casefold(),)).fetchone()
        valid = check_password(password, user["password_hash"] if user else self.dummy_hash)
        if not user or not user["active"] or not valid:
            return None, 401
        with self.lock:
            self.attempts.pop(address, None)
        return user, 200

    def logout(self, token):
        with self.lock:
            self.sessions.pop(token, None)
