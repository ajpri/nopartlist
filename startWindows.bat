@echo off
setlocal
pushd "%~dp0" || exit /b 1
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0startWindows.ps1" %*
set "launcherExit=%ERRORLEVEL%"
popd
exit /b %launcherExit%
