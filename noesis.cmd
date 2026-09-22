@echo off
rem noesis — launcher della console (Windows nativo).
setlocal
set "DIR=%~dp0"
set "SCRIPT=%DIR%tools\noesis.py"

if exist "%DIR%.venv\Scripts\python.exe" goto :venv
where uv >nul 2>nul && goto :uv
where python >nul 2>nul && goto :py

echo Python o uv non trovati: installa uv da https://docs.astral.sh/uv/ 1>&2
exit /b 1

:venv
"%DIR%.venv\Scripts\python.exe" "%SCRIPT%" %*
exit /b %errorlevel%

:uv
uv run --no-project python "%SCRIPT%" %*
exit /b %errorlevel%

:py
python "%SCRIPT%" %*
exit /b %errorlevel%
