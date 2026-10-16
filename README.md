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
There is no authentication; anyone who can reach the server can read and change
the lists, so use a trusted network.

Optional server flags: `--port 1998`, `--host 127.0.0.1` (local access only),
and `--database /path/to/data.sqlite3`.

## Existing browser data

On the first run with an empty database, the app migrates old localStorage data
if it is available at the current origin. Browser storage belongs to a specific
address and port: if the old app ran elsewhere, export its lists there and use
**Import** in the new app. The old browser copy is retained as a backup, but
future changes save to SQLite. Import replaces the current lists; Undo can
restore them during the session.

Save failures appear beside the task count and retry after connection failures.
If another tab changes the database, export any unsaved edits before reloading.
An unsaved-changes prompt helps prevent closing a tab before saving finishes.

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
