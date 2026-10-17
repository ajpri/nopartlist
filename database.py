"""SQLite schema and owner-scoped list storage."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import uuid

DEFAULT_DATABASE = Path(__file__).resolve().parent / "no_part_list.sqlite3"


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize_database(path):
    with connect(path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                username_key TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                auth_version INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS user_state (
                user_id INTEGER PRIMARY KEY REFERENCES users(id),
                revision INTEGER NOT NULL DEFAULT 0,
                current_id TEXT,
                theme TEXT NOT NULL DEFAULT 'dark',
                initialized INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL REFERENCES users(id),
                client_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                data TEXT NOT NULL,
                UNIQUE(owner_id, client_id)
            );
            CREATE TABLE IF NOT EXISTS recoveries (
                user_id INTEGER NOT NULL REFERENCES users(id),
                recovery_id TEXT NOT NULL,
                snapshot TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(user_id, recovery_id)
            );
        """)


def read_state(db, user_id):
    row = db.execute("SELECT * FROM user_state WHERE user_id = ?", (user_id,)).fetchone()
    if not row["initialized"]:
        return row["revision"], None
    lists = [json.loads(item["data"]) for item in db.execute(
        "SELECT data FROM lists WHERE owner_id = ? ORDER BY position", (user_id,))]
    return row["revision"], {"currentId": row["current_id"], "theme": row["theme"], "lists": lists}


def write_state(db, user_id, revision, state):
    result = db.execute("""UPDATE user_state SET revision = revision + 1,
        current_id = ?, theme = ?, initialized = 1 WHERE user_id = ? AND revision = ?""",
        (state["currentId"], state["theme"], user_id, revision))
    if result.rowcount != 1:
        return False
    # Preserve internal list identities across edits for future sharing support.
    existing = {row["client_id"] for row in db.execute(
        "SELECT client_id FROM lists WHERE owner_id = ?", (user_id,))}
    for position, item in enumerate(state["lists"]):
        existing.discard(item["id"])
        db.execute("""INSERT INTO lists (owner_id, client_id, position, data) VALUES (?, ?, ?, ?)
            ON CONFLICT(owner_id, client_id) DO UPDATE SET position = excluded.position, data = excluded.data""",
            (user_id, item["id"], position, json.dumps(item)))
    db.executemany("DELETE FROM lists WHERE owner_id = ? AND client_id = ?",
                   [(user_id, list_id) for list_id in existing])
    return True


def recover_state(db, user_id, recovery_id, snapshot):
    """Preserve a losing snapshot and append changed lists without replacing winners.

    The caller holds an IMMEDIATE transaction. Recovery IDs make retries safe
    even when the first response was lost after committing.
    """
    revision, current = read_state(db, user_id)
    inserted = db.execute("INSERT OR IGNORE INTO recoveries (user_id, recovery_id, snapshot) VALUES (?, ?, ?)",
                          (user_id, recovery_id, json.dumps(snapshot))).rowcount
    if not inserted:
        return revision, current, 0
    current = current or {"currentId": None, "theme": snapshot["theme"], "lists": []}
    existing = {item["id"]: item for item in current["lists"]}
    recovered = []
    for item in snapshot["lists"]:
        if existing.get(item["id"]) != item:
            recovered.append({**item, "id": uuid.uuid4().hex,
                              "title": f"{item['title'] or 'Untitled'} (Recovered)"})
    if recovered:
        current["lists"].extend(recovered)
        current["currentId"] = recovered[0]["id"]
        write_state(db, user_id, revision, current)
        revision += 1
    return revision, current, len(recovered)


def claim_legacy_state(db, user_id):
    """Called inside the first account's transaction; no later user inherits data."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_state'").fetchone():
        return
    legacy = db.execute("SELECT revision, data FROM app_state WHERE id = 1").fetchone()
    if legacy and json.loads(legacy["data"]) is not None:
        state = json.loads(legacy["data"])
        write_state(db, user_id, 0, state)
        db.execute("UPDATE user_state SET revision = ? WHERE user_id = ?", (legacy["revision"], user_id))
    # Drop only after the transaction has safely transferred the original lists.
    db.execute("DROP TABLE app_state")
