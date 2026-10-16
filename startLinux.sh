#!/usr/bin/env bash
# Linux launcher inspired by ajpri/wellbeing-agent's linux-bootstrap branch.
set -Eeuo pipefail

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
usage() {
    cat <<'HELP'
Usage: ./startLinux.sh [--yes] [--check] [--port PORT] [--open] [--secure-cookie]
       ./startLinux.sh manage-users
  --yes       Accept dependency installation without prompting.
  --check     Check dependencies, project files and port; make no changes.
  --port PORT Use a different port (default: 1998; listens on all interfaces).
  --open      Open the app in your default browser when starting.
  --secure-cookie  Use Secure cookies when serving behind HTTPS.
  manage-users     Manage accounts in the terminal without starting a server.
  --help      Show this help.

Requires Python 3.10+ with SQLite support. No pip packages are needed.
Runs in the foreground; Ctrl+C stops the server.
HELP
}

YES=false
CHECK=false
OPEN=false
MANAGE=false
SECURE_COOKIE=()
PORT=1998
while (($#)); do
    case "$1" in
        --yes) YES=true ;;
        --check) CHECK=true ;;
        --open) OPEN=true ;;
        manage-users) MANAGE=true ;;
        --secure-cookie) SECURE_COOKIE=(--secure-cookie) ;;
        --port)
            (($# >= 2)) || die '--port requires a number.'
            PORT=$2
            shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Unknown option: $1. Use --help for usage." ;;
    esac
    shift
done
[[ $PORT =~ ^[0-9]{1,5}$ ]] || die 'Port must be a number between 1 and 65535.'
PORT=$((10#$PORT))
((PORT >= 1 && PORT <= 65535)) || die 'Port must be between 1 and 65535.'
[[ $(uname -s) == Linux ]] || die 'This launcher requires Linux.'
PROJECT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd -- "$PROJECT_DIR"

python_ready() {
    command -v "$PYTHON_BIN" >/dev/null 2>&1 &&
        "$PYTHON_BIN" -c 'import sys, sqlite3, http.server, hashlib; assert sys.version_info >= (3, 10); assert callable(hashlib.pbkdf2_hmac); sqlite3.connect(":memory:").close()' >/dev/null 2>&1
}
PYTHON_BIN=${PYTHON:-python3}
if ! python_ready; then
    printf 'Missing or incompatible dependency: Python 3.10+ with SQLite support.\n'
    $CHECK && die 'Dependency check failed. Run without --check to offer installation.'
    # Use the distribution package manager; no downloaded installer scripts.
    if command -v apt-get >/dev/null 2>&1; then
        INSTALL=(apt-get install -y python3 libpython3-stdlib)
        UPDATE=(apt-get update)
    elif command -v dnf >/dev/null 2>&1; then
        INSTALL=(dnf install -y python3 python3-libs)
        UPDATE=()
    elif command -v yum >/dev/null 2>&1; then
        INSTALL=(yum install -y python3 python3-libs)
        UPDATE=()
    elif command -v pacman >/dev/null 2>&1; then
        INSTALL=(pacman -Syu --needed --noconfirm python)
        UPDATE=()
    elif command -v zypper >/dev/null 2>&1; then
        INSTALL=(zypper --non-interactive install python3 python3-base)
        UPDATE=()
    elif command -v apk >/dev/null 2>&1; then
        INSTALL=(apk add python3)
        UPDATE=()
    else
        die 'No supported package manager found. Install Python 3.10+ with sqlite3 manually, then rerun.'
    fi
    PRIVILEGE=()
    if ((EUID != 0)); then
        command -v sudo >/dev/null 2>&1 || die 'sudo is required to install system packages. Ask your administrator to install Python 3.10+ with SQLite support.'
        PRIVILEGE=(sudo)
    fi
    printf '\nProposed installation commands:\n'
    if ((${#UPDATE[@]})); then
        printf '  '; printf '%q ' "${PRIVILEGE[@]}" "${UPDATE[@]}"; printf '\n'
    fi
    printf '  '; printf '%q ' "${PRIVILEGE[@]}" "${INSTALL[@]}"; printf '\n'
    if ! $YES; then
        [[ -t 0 ]] || die 'Noninteractive session: install dependencies manually or pass --yes.'
        read -r -p 'Install these dependencies now? [y/N] ' answer || die 'Installation cancelled.'
        case "$answer" in y|Y|yes|YES) ;; *) die 'Installation declined.' ;; esac
    fi
    if ((${#UPDATE[@]})); then
        "${PRIVILEGE[@]}" "${UPDATE[@]}" || die 'Package index update failed.'
    fi
    "${PRIVILEGE[@]}" "${INSTALL[@]}" || die 'Dependency installation failed.'
    hash -r
    python_ready || die 'Python is still missing, too old, or lacks SQLite. Install Python 3.10+ manually or set PYTHON to a compatible executable.'
fi

if $MANAGE && ! $CHECK; then
    exec "$PYTHON_BIN" "$PROJECT_DIR/users.py"
fi

"$PYTHON_BIN" - "$PORT" <<'PY'
import os
from pathlib import Path
import socket
import sys

for name in ("server.py", "index.html", "login.html", "database.py", "auth.py", "users.py"):
    if not Path(name).is_file():
        sys.exit(f"Error: Missing {name}; run from a complete project checkout.")
database = Path("no_part_list.sqlite3")
if not os.access(Path.cwd(), os.W_OK) or (database.exists() and not os.access(database, os.W_OK)):
    sys.exit("Error: Project directory and database must be writable for SQLite saves.")
try:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", int(sys.argv[1])))
except OSError as exc:
    sys.exit(f"Error: Port {sys.argv[1]} is unavailable ({exc.strerror}). Stop the existing server or choose --port PORT.")
PY

if $CHECK; then
    printf 'Checks passed. Ready to listen on 0.0.0.0:%s\n' "$PORT"
    exit 0
fi
if $OPEN; then
    # Poll before opening, without leaving a long-lived launcher process.
    "$PYTHON_BIN" - "$PORT" <<'PY' &
import sys
import time
import urllib.request
import webbrowser

url = f"http://127.0.0.1:{sys.argv[1]}"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for _ in range(40):
    try:
        with opener.open(url, timeout=0.5) as response:
            if response.status == 200:
                if not webbrowser.open(url):
                    print(f"Could not open a browser. Open {url} manually.", file=sys.stderr)
                break
    except OSError:
        time.sleep(0.25)
else:
    print("Browser opening skipped: server did not become ready.", file=sys.stderr)
PY
fi
printf 'Starting No Part List on 0.0.0.0:%s\nOpen http://127.0.0.1:%s locally, or use this computer\x27s network address.\nPress Ctrl+C to stop.\n' "$PORT" "$PORT"
# One server: exec forwards signals directly and preserves its exit status.
exec "$PYTHON_BIN" "$PROJECT_DIR/server.py" --host 0.0.0.0 --port "$PORT" "${SECURE_COOKIE[@]}"
