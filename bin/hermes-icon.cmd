@echo off
setlocal enabledelayedexpansion

if "%~1"=="--version" (
  echo hermes-icon 0.1.10
  exit /b 0
)
if "%~1"=="-V" (
  echo hermes-icon 0.1.10
  exit /b 0
)

set "PY="
if defined HERMES_PYTHON (
  if exist "%HERMES_PYTHON%" set "PY=%HERMES_PYTHON%"
)

if not defined PY if defined HERMES_ICON_STATE_DIR (
  if exist "%HERMES_ICON_STATE_DIR%\.venv\Scripts\python.exe" set "PY=%HERMES_ICON_STATE_DIR%\.venv\Scripts\python.exe"
)

if not defined PY if defined USERPROFILE (
  if exist "%USERPROFILE%\.hermes\icon-replacer\.venv\Scripts\python.exe" set "PY=%USERPROFILE%\.hermes\icon-replacer\.venv\Scripts\python.exe"
)

if not defined PY if defined HERMES_HOME (
  if exist "%HERMES_HOME%\icon-replacer\.venv\Scripts\python.exe" set "PY=%HERMES_HOME%\icon-replacer\.venv\Scripts\python.exe"
  if not defined PY for /d %%I in ("%HERMES_HOME%\installs\*") do (
    for /d %%E in ("%%~I\environments\*") do (
      if not defined PY if exist "%%~E\venv\Scripts\python.exe" set "PY=%%~E\venv\Scripts\python.exe"
    )
  )
  if not defined PY if exist "%HERMES_HOME%\hermes-agent\.venv\Scripts\python.exe" set "PY=%HERMES_HOME%\hermes-agent\.venv\Scripts\python.exe"
  if not defined PY if exist "%HERMES_HOME%\hermes-agent\venv\Scripts\python.exe" set "PY=%HERMES_HOME%\hermes-agent\venv\Scripts\python.exe"
)

if not defined PY if defined LOCALAPPDATA (
  if exist "%LOCALAPPDATA%\hermes\icon-replacer\.venv\Scripts\python.exe" set "PY=%LOCALAPPDATA%\hermes\icon-replacer\.venv\Scripts\python.exe"
  if not defined PY for /d %%I in ("%LOCALAPPDATA%\hermes\installs\*") do (
    for /d %%E in ("%%~I\environments\*") do (
      if not defined PY if exist "%%~E\venv\Scripts\python.exe" set "PY=%%~E\venv\Scripts\python.exe"
    )
  )
  if not defined PY if exist "%LOCALAPPDATA%\hermes\hermes-agent\.venv\Scripts\python.exe" set "PY=%LOCALAPPDATA%\hermes\hermes-agent\.venv\Scripts\python.exe"
  if not defined PY if exist "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" set "PY=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
)

if not defined PY if defined USERPROFILE (
  if exist "%USERPROFILE%\.hermes\icon-replacer\.venv\Scripts\python.exe" set "PY=%USERPROFILE%\.hermes\icon-replacer\.venv\Scripts\python.exe"
  if not defined PY for /d %%I in ("%USERPROFILE%\.hermes\installs\*") do (
    for /d %%E in ("%%~I\environments\*") do (
      if not defined PY if exist "%%~E\venv\Scripts\python.exe" set "PY=%%~E\venv\Scripts\python.exe"
    )
  )
  if not defined PY if exist "%USERPROFILE%\.hermes\hermes-agent\.venv\Scripts\python.exe" set "PY=%USERPROFILE%\.hermes\hermes-agent\.venv\Scripts\python.exe"
  if not defined PY if exist "%USERPROFILE%\.hermes\hermes-agent\venv\Scripts\python.exe" set "PY=%USERPROFILE%\.hermes\hermes-agent\venv\Scripts\python.exe"
)

if not defined PY if defined LOCALAPPDATA (
  if exist "%LOCALAPPDATA%\Programs\Hermes\resources\agent-payload\venv\Scripts\python.exe" set "PY=%LOCALAPPDATA%\Programs\Hermes\resources\agent-payload\venv\Scripts\python.exe"
  if not defined PY if exist "%LOCALAPPDATA%\hermes-desktop\resources\agent-payload\venv\Scripts\python.exe" set "PY=%LOCALAPPDATA%\hermes-desktop\resources\agent-payload\venv\Scripts\python.exe"
  if not defined PY for /d %%T in ("%LOCALAPPDATA%\Programs\Hermes\resources\agent-payload\tools\python-*") do (
    if not defined PY if exist "%%~T\python.exe" set "PY=%%~T\python.exe"
  )
  if not defined PY for /d %%T in ("%LOCALAPPDATA%\hermes-desktop\resources\agent-payload\tools\python-*") do (
    if not defined PY if exist "%%~T\python.exe" set "PY=%%~T\python.exe"
  )
)

if not defined PY if defined ProgramFiles (
  if exist "%ProgramFiles%\Hermes\resources\agent-payload\venv\Scripts\python.exe" set "PY=%ProgramFiles%\Hermes\resources\agent-payload\venv\Scripts\python.exe"
  if not defined PY for /d %%T in ("%ProgramFiles%\Hermes\resources\agent-payload\tools\python-*") do (
    if not defined PY if exist "%%~T\python.exe" set "PY=%%~T\python.exe"
  )
)

if not defined PY (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    echo %%~P | findstr /i /c:"\Microsoft\WindowsApps\" >nul || (
      if not defined PY set "PY=%%~P"
    )
  )
)

if not defined PY (
  where py >nul 2>&1 && (
    set "PYTHONPATH="
    set "PYTHONHOME="
    py -3 -I "%~dp0..\run.py" %*
    exit /b !errorlevel!
  )
)

if not defined PY if defined LOCALAPPDATA (
  for /d %%P in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if not defined PY if exist "%%~P\python.exe" set "PY=%%~P\python.exe"
  )
)

if not defined PY if defined USERPROFILE (
  for /d %%P in ("%USERPROFILE%\scoop\apps\python*") do (
    if not defined PY if exist "%%~P\current\python.exe" set "PY=%%~P\current\python.exe"
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
