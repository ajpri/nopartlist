# Windows counterpart to startLinux.sh; compatible with Windows PowerShell 5.1.
$ErrorActionPreference = 'Stop'

function Show-Usage {
    @'
Usage: .\startWindows.bat [--yes] [--check] [--port PORT] [--open] [--secure-cookie]
       .\startWindows.bat manage-users
  --yes            Accept Python installation without prompting.
  --check          Check dependencies, project files and port; make no changes.
  --port PORT      Use a different port (default: 1998; all interfaces).
  --open           Open your default browser after startup.
  --secure-cookie  Use Secure cookies when serving behind HTTPS.
  manage-users     Manage accounts without starting a server.
  --help           Show this help.

Requires Python 3.10+ with SQLite. No pip packages are needed.
Set PYTHON to a Python executable to override automatic discovery.
Runs in the foreground; Ctrl+C stops the server.
'@ | Write-Output
}

$acceptInstall = $false
$check = $false
$open = $false
$manage = $false
$secureCookie = $false
$port = 1998
$browserJob = $null

function Find-Python {
    $candidates = @()
    if ($env:PYTHON) {
        $candidates += @{ Command = $env:PYTHON; Prefix = @() }
    } else {
        $candidates += @{ Command = 'py'; Prefix = @('-3') }
        $candidates += @{ Command = 'python'; Prefix = @() }
        $candidates += @{ Command = 'python3'; Prefix = @() }
        # A new installation may not yet be on this process's PATH.
        $patterns = @(
            "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe",
            "$env:ProgramFiles\Python*\python.exe"
        )
        foreach ($pattern in $patterns) {
            foreach ($file in (Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)) {
                $candidates += @{ Command = $file.FullName; Prefix = @() }
            }
        }
    }
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Command -ErrorAction SilentlyContinue)) { continue }
        try {
            $prefix = $candidate.Prefix
            & $candidate.Command @prefix -c "import sys, sqlite3, http.server, hashlib; assert sys.version_info >= (3, 10); assert callable(hashlib.pbkdf2_hmac); sqlite3.connect(':memory:').close()" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch { }
    }
    return $null
}

try {
    for ($i = 0; $i -lt $args.Count; $i++) {
        switch -CaseSensitive ($args[$i]) {
            '--yes' { $acceptInstall = $true }
            '--check' { $check = $true }
            '--open' { $open = $true }
            'manage-users' { $manage = $true }
            '--secure-cookie' { $secureCookie = $true }
            { $_ -in '--help', '-h' } { Show-Usage; exit 0 }
            '--port' {
                $i++
                if ($i -ge $args.Count -or $args[$i] -notmatch '^[0-9]{1,5}$') {
                    throw '--port requires a number between 1 and 65535.'
                }
                $port = [int]$args[$i]
            }
            default { throw "Unknown option: $($args[$i]). Use --help for usage." }
        }
    }
    if ($port -lt 1 -or $port -gt 65535) { throw 'Port must be between 1 and 65535.' }
    if ($env:OS -ne 'Windows_NT') { throw 'This launcher requires Windows.' }
    Set-Location -LiteralPath $PSScriptRoot

    $python = Find-Python
    if (-not $python) {
        Write-Output 'Missing or incompatible dependency: Python 3.10+ with SQLite support.'
        if ($check) { throw 'Dependency check failed. Run without --check to offer installation.' }
        if ($env:PYTHON) { throw 'PYTHON is not compatible. Set it to a Python 3.10+ executable with SQLite support.' }
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw 'Install Python 3.10+ from python.org (with SQLite and the Python launcher), then rerun.'
        }
        Write-Output 'Proposed installation: winget install --id Python.Python.3.13 --exact --source winget --scope user --accept-source-agreements --accept-package-agreements'
        if (-not $acceptInstall) {
            if ([Console]::IsInputRedirected -or -not [Environment]::UserInteractive) {
                throw 'Noninteractive session: install Python manually or pass --yes.'
            }
            $answer = Read-Host 'Install Python now? [y/N]'
            if ($answer -notmatch '^(?i:y|yes)$') { throw 'Installation declined.' }
        }
        & winget install --id Python.Python.3.13 --exact --source winget --scope user --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
        $python = Find-Python
        if (-not $python) { throw 'Python is still unavailable. Reopen your terminal or set PYTHON to its executable.' }
    }
    $pythonCommand = $python.Command
    $pythonPrefix = $python.Prefix
    if ($manage -and -not $check) {
        & $pythonCommand @pythonPrefix (Join-Path $PSScriptRoot 'users.py')
        exit $LASTEXITCODE
    }

    $preflight = @'
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
        sock.bind(("0.0.0.0", int(sys.argv[1])))
except OSError as exc:
    sys.exit(f"Error: Port {sys.argv[1]} is unavailable ({exc}). Stop the existing server or choose --port PORT.")
'@
    $preflight | & $pythonCommand @pythonPrefix - $port
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($check) {
        Write-Output "Checks passed. Ready to listen on 0.0.0.0:$port"
        exit 0
    }
    if ($open) {
        $browserJob = Start-Job -ArgumentList $port -ScriptBlock {
            param($serverPort)
            $url = "http://127.0.0.1:$serverPort"
            for ($attempt = 0; $attempt -lt 40; $attempt++) {
                try {
                    $request = [System.Net.WebRequest]::Create($url)
                    $request.Proxy = $null
                    $request.Timeout = 500
                    $response = $request.GetResponse()
                    $response.Close()
                    Start-Process $url
                    return
                } catch { Start-Sleep -Milliseconds 250 }
            }
            Write-Output "Browser opening skipped: server did not become ready. Open $url manually."
        }
    }
    Write-Output "Starting No Part List on 0.0.0.0:$port"
    Write-Output "Open http://127.0.0.1:$port locally, or use this computer's network address."
    Write-Output 'Press Ctrl+C to stop.'
    $serverArgs = @((Join-Path $PSScriptRoot 'server.py'), '--host', '0.0.0.0', '--port', "$port")
    if ($secureCookie) { $serverArgs += '--secure-cookie' }
    & $pythonCommand @pythonPrefix @serverArgs
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine("Error: $($_.Exception.Message)")
    exit 1
} finally {
    if ($browserJob) {
        Stop-Job $browserJob -ErrorAction SilentlyContinue
        Receive-Job $browserJob -ErrorAction SilentlyContinue
        Remove-Job $browserJob -Force -ErrorAction SilentlyContinue
    }
}
