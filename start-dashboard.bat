@echo off
REM Launch the diet dashboard (local web UI) and open it in the default browser.
REM %~dp0 resolves to this script's own folder (the project root) at runtime,
REM so the project path never needs to be hard-coded (encoding-safe, ASCII only).
cd /d "%~dp0"

REM Pick the uv invocation ONCE, based only on whether uv.exe is on PATH.
REM (Do not fall back on run failures like "port in use" - that would hide the
REM real error and confusingly retry the same command.)
where uv >nul 2>nul
if errorlevel 1 (set "RUNNER=py -m uv run") else (set "RUNNER=uv run")

echo Starting diet dashboard on http://127.0.0.1:8770 ...
start "diet dashboard" cmd /k "%RUNNER% diet serve"
timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:8770"
exit /b
