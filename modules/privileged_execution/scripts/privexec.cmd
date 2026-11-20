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
if errorlevel 1 goto try_py
python -m privexec.cli %*
exit /b %ERRORLEVEL%

:try_py
where py >nul 2>nul
if errorlevel 1 goto no_python
py -3 -m privexec.cli %*
exit /b %ERRORLEVEL%

:no_python
echo {"ok":false,"error":"Python 3.11+ was not found on PATH."} 1>&2
exit /b 1
