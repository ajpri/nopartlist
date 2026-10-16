# No Part List

A list and notes app served by Python, with data saved in SQLite.

## Run

Requires Python 3.10 or newer. No packages to install.

```sh
python3 server.py
```

Open http://127.0.0.1:1998. Keep the server running while using the app.
Stop it with Ctrl+C. Lists, tasks, selected list, and theme are stored in
`no_part_list.sqlite3` beside `server.py` and survive server restarts.
The database is excluded from Git. Back it up while the server is stopped,
or use **Export all** to download JSON.

Optional flags: `--port 1998`, `--host 127.0.0.1`, and `--database /path/to/data.sqlite3`.
The default binds to this computer only. There is no authentication; only expose
it to a network you trust.

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

## GitHub

The repository uses `main`. After creating an empty GitHub repository:

```sh
git remote add origin <your-repository-url>
git push -u origin main
```
