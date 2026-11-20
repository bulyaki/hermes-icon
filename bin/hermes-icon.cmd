@echo off
setlocal enabledelayedexpansion

if "%~1"=="--version" (
  echo hermes-icon 0.1.2
  exit /b 0
)
if "%~1"=="-V" (
  echo hermes-icon 0.1.2
  exit /b 0
)

set "PY="
if defined HERMES_PYTHON (
  if exist "%HERMES_PYTHON%" set "PY=%HERMES_PYTHON%"
)

if not defined PY if defined HERMES_HOME (
  for /d %%I in ("%HERMES_HOME%\installs\*") do (
    for /d %%E in ("%%~I\environments\*") do (
      if not defined PY if exist "%%~E\venv\Scripts\python.exe" set "PY=%%~E\venv\Scripts\python.exe"
    )
  )
)

if not defined PY if defined USERPROFILE (
  for /d %%I in ("%USERPROFILE%\.hermes\installs\*") do (
    for /d %%E in ("%%~I\environments\*") do (
      if not defined PY if exist "%%~E\venv\Scripts\python.exe" set "PY=%%~E\venv\Scripts\python.exe"
    )
  )
)

if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)

if not defined PY (
  where py >nul 2>&1 && (
    set "PYTHONPATH="
    set "PYTHONHOME="
    py -3 -I "%~dp0..\run.py" %*
    exit /b !errorlevel!
  )
)

if not defined PY (
  echo hermes-icon: could not locate Python interpreter 1>&2
  exit /b 1
)

set "PYTHONPATH="
set "PYTHONHOME="
"%PY%" -I "%~dp0..\run.py" %*
exit /b %errorlevel%
