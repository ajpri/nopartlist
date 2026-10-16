#!/usr/bin/env python3
"""Command-line account management; passwords are read from a protected prompt."""
import argparse
import getpass
import hashlib
import hmac
import secrets
import sqlite3
import sys
import unicodedata
import warnings

from database import DEFAULT_DATABASE, claim_legacy_state, connect, initialize_database

PASSWORD_ITERATIONS = 600_000


def validate_username(username):
    if not isinstance(username, str):
        raise ValueError("Username is required.")
    username = username.strip()
    if not 1 <= len(username) <= 64 or any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in username):
        raise ValueError("Username must be 1–64 characters without control characters.")
    return username


def password_hash(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise ValueError("Password must contain 8–128 characters.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest.hex()}"


def check_password(password, stored):
    if not isinstance(password, str) or len(password) > 128:
        return False
    method, iterations, salt, expected = stored.split("$")
    if method != "pbkdf2_sha256":
        return False
    try:
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    except UnicodeError:
        return False
    return hmac.compare_digest(actual.hex(), expected)


def create_user(path, username, password, *, only_if_empty=False):
    username = validate_username(username)
    hashed = password_hash(password)
    initialize_database(path)
    try:
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            first = not db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            if only_if_empty and not first:
                raise ValueError("Another user was created during setup. Use manage-users to manage accounts.")
            user_id = db.execute("INSERT INTO users (username, username_key, password_hash) VALUES (?, ?, ?)",
                                 (username, username.casefold(), hashed)).lastrowid
            db.execute("INSERT INTO user_state (user_id) VALUES (?)", (user_id,))
            if first:
                claim_legacy_state(db, user_id)
            return user_id
    except sqlite3.IntegrityError as exc:
        raise ValueError("That username already exists.") from exc


def reset_password(path, username, password):
    username = validate_username(username)
    hashed = password_hash(password)
    with connect(path) as db:
        result = db.execute("UPDATE users SET password_hash = ?, auth_version = auth_version + 1 WHERE username_key = ?",
                            (hashed, username.casefold()))
        if not result.rowcount:
            raise ValueError("User not found.")


def set_active(path, username, active):
    username = validate_username(username)
    with connect(path) as db:
        result = db.execute("UPDATE users SET active = ?, auth_version = auth_version + 1 WHERE username_key = ?",
                            (int(active), username.casefold()))
        if not result.rowcount:
            raise ValueError("User not found.")


def confirmed_password():
    print("Use 8–128 characters. Password input is hidden.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("Password: ")
        confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match.")
    return password


def configure_on_startup(path):
    with connect(path) as db:
        if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return
    print("No users configured. Sign-in requires an account. The first user will own any existing lists.", flush=True)
    try:
        if not sys.stdin.isatty():
            print("No interactive terminal available; first-user setup skipped.")
        elif input("Create the first user now? [y/N; Enter skips] ").strip().lower() in {"y", "yes"}:
            username = validate_username(input("Username: "))
            create_user(path, username, confirmed_password(), only_if_empty=True)
            print("User created. You can now sign in.", flush=True)
            return
        else:
            print("First-user setup skipped.")
    except (EOFError, KeyboardInterrupt, OSError, getpass.GetPassWarning):
        print("\nSetup cancelled or protected password input unavailable.")
    except (ValueError, sqlite3.Error) as exc:
        print(f"Setup did not complete: {exc}")
    print("The server will keep running; sign-in stays blocked until an account exists.\n"
          "In another terminal, run ./startLinux.sh manage-users or python3 users.py create USERNAME.", flush=True)


def list_users(path):
    with connect(path) as db:
        for row in db.execute("SELECT username, active FROM users ORDER BY username_key"):
            print(f"{row['username']} ({'active' if row['active'] else 'disabled'})")


def manage_users(path):
    while True:
        print("\n1. List users\n2. Create user\n3. Reset password\n4. Disable user\n5. Enable user\n6. Exit")
        choice = input("Choose: ").strip()
        try:
            if choice == "1":
                list_users(path)
            elif choice in {"2", "3", "4", "5"}:
                username = input("Username: ")
                if choice == "2":
                    create_user(path, username, confirmed_password())
                elif choice == "3":
                    reset_password(path, username, confirmed_password())
                else:
                    set_active(path, username, choice == "5")
                print("User updated.")
            elif choice == "6":
                return
            else:
                print("Choose a listed number.")
        except (ValueError, sqlite3.Error) as exc:
            print(str(exc))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("list")
    for name in ("create", "reset-password", "disable", "enable"):
        command = commands.add_parser(name)
        command.add_argument("username")
    args = parser.parse_args()
    initialize_database(args.database)
    try:
        if args.command is None:
            manage_users(args.database)
        elif args.command == "list":
            list_users(args.database)
        elif args.command == "create":
            create_user(args.database, args.username, confirmed_password())
            print("User created. The first user owns any existing lists.")
        elif args.command == "reset-password":
            reset_password(args.database, args.username, confirmed_password())
            print("Password reset; existing sessions revoked.")
        else:
            set_active(args.database, args.username, args.command == "enable")
            print("User updated; existing sessions revoked. Lists retained.")
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        parser.exit(1, "\nCancelled. Use an interactive terminal with protected password input.\n")
    except (ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
