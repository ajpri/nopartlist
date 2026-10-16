# No Part List

A list and notes app served by Python, with data saved in SQLite.

## Run

Requires Python 3.10 or newer. No packages to install.

On Linux, the launcher checks Python and SQLite, offers to install missing
system dependencies, and starts the server:

```sh
./startLinux.sh
```

It works from any current directory. `--check` performs checks without installing
anything or creating a database; `--yes` accepts dependency installation;
`--port 2000` changes the port; `--open` opens your default browser after startup.
Use `--secure-cookie` when serving the app behind HTTPS.
Set `PYTHON=/path/to/python3` to use a specific Python executable.
Automatic installation supports apt, dnf, yum, pacman, zypper, and apk and uses
sudo for system packages when needed. Pacman updates the system to avoid partial
upgrades. Older distributions may require installing Python 3.10+ manually.
No Python packages, virtual environment, or Node.js are needed to run the app.

The launcher is inspired by the
[wellbeing-agent Linux bootstrap](https://github.com/ajpri/wellbeing-agent/tree/feature/linux-bootstrap).

Or start Python directly:

```sh
python3 server.py
```

Open http://127.0.0.1:1998. Keep the server running while using the app.
Stop it with Ctrl+C. Lists, tasks, selected list, and theme are stored in
`no_part_list.sqlite3` beside `server.py` and survive server restarts.
The database is excluded from Git. Back it up while the server is stopped,
or use **Export all** to download JSON.

The server and Linux launcher listen on all interfaces (`0.0.0.0`) by default.
Open `http://<this-computer-ip>:1998` from another device on your network.
Sign-in is required. Each account has its own lists, tasks, notes, selected list,
and theme. Accounts are independent of No Part Finance. Sharing and collaboration
are not enabled. Lists have explicit owners and stable internal identities to
allow future sharing without mixing accounts' data.

For internet access, put the app behind a properly configured HTTPS reverse
proxy and use `--secure-cookie`. Keep the Python port private to the proxy.
The built-in server is intended for trusted self-hosted use. On plain HTTP,
passwords and session cookies are not encrypted in transit.

Optional server flags: `--port 1998`, `--host 127.0.0.1` (local access only),
`--secure-cookie`, and `--database /path/to/data.sqlite3`.

## Accounts and sessions

There are no default credentials and no public signup. Create the first account
at startup: when the database has no users, both `./startLinux.sh` and
`python3 server.py` offer **Create the first user now?** in the terminal.
Accept to enter a username and a hidden, confirmed password. The first account
receives any existing lists.

Press Enter or answer no to skip setup. Cancellation or invalid input also leaves
the server running with sign-in blocked until an account is created. In a
noninteractive session (such as a service), setup is skipped automatically;
the server prints account-management instructions. Existing users suppress the
prompt, including when all accounts are disabled; use user management to enable
an account. `--yes` accepts dependency installation only, not account creation.
The browser never offers signup.

You can also create the first account later from an interactive terminal:

```sh
./startLinux.sh manage-users
```

This menu can create or list users, reset passwords, and disable or enable
accounts. **The server can stay running:** open a second terminal, change to the
project directory, and run `./startLinux.sh manage-users`. This starts only user
management; it does not stop, restart, or launch another server. No separate
launcher is needed.

Changes take effect immediately, without downtime: new users can sign in as
soon as they are created; password resets and disabling or enabling accounts
revoke their existing sessions. Other users remain signed in and can keep
working. Password entry is hidden.
Passwords must be 8–128 characters and are stored as salted PBKDF2-SHA256 hashes.
Direct commands are also available:

```sh
python3 users.py create austin
python3 users.py list
python3 users.py reset-password austin
python3 users.py disable austin
python3 users.py enable austin
```

For a custom database, put `--database /path/to/data.sqlite3` before the command.
The first user created receives all lists already in the original single-user
database, atomically. Later users start with empty lists. Disabling an account
retains its lists. Password resets, disabling, and enabling revoke that account's
existing sessions.

Sessions last **168 hours (7 days) from sign-in**. They use HttpOnly, SameSite
cookies and server-side CSRF tokens. Sessions live only in the server process:
stopping or restarting it logs everyone out, including after a crash.
Signing out revokes the current session. Failed sign-ins are limited to five
attempts per minute per connecting IP address; behind a reverse proxy that IP
may be shared by all users.

## Existing browser data

Export lists from the old browser app and use **Import** after signing into the
account that should own them. Browser storage is no longer imported automatically,
so another account using the same browser cannot inherit old private lists.
Import replaces only the signed-in user's lists; Undo can restore them during
the session. Existing data already in SQLite is assigned to the first account.

Save failures appear beside the task count and retry after connection failures.
If another tab changes the database, export any unsaved edits before reloading.
An unsaved-changes prompt helps prevent closing a tab before saving finishes.
If a session expires, export unsaved edits before following **Sign in again**.
An old tab cannot save to a different user's account after an account switch.

## Check

```sh
python3 -m unittest discover -s tests -v
```

Calendar-date regression checks require Node.js and cover six time zones:

```sh
node tests/test_dates.js
```

## GitHub

The repository uses `main`. After creating an empty GitHub repository:

```sh
git remote add origin <your-repository-url>
git push -u origin main
```
