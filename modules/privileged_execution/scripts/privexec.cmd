@echo off
setlocal
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"
if exist "%HERE%\privexec\__init__.py" (
    set "PRIVEXEC_ROOT=%HERE%"
) else (
    for %%I in ("%HERE%\..") do set "PRIVEXEC_ROOT=%%~fI"
)
if defined PYTHONPATH (
    set "PYTHONPATH=%PRIVEXEC_ROOT%;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%PRIVEXEC_ROOT%"
)
where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python -m privexec.cli %*
    exit /b %ERRORLEVEL%
)
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 -m privexec.cli %*
    exit /b %ERRORLEVEL%
)
echo {"ok":false,"error":"Python 3.11+ was not found on PATH."} 1>&2
exit /b 1
