@echo off
REM Windows shim for the Blender CLI -> forwards to tools/blender_shim.py (bpy pip module).
REM Usage:  set BLENDER_PYTHON=C:\path\to\venv\Scripts\python.exe
REM         set BLENDER_BIN=%CD%\tools\blender.cmd
REM NOTE 1: this file MUST use CRLF line endings. cmd.exe mis-parses LF-only batch
REM         files; on 2026-11-23 a garbled redirection truncated tools/blender_shim.py
REM         to 0 bytes.
REM NOTE 2: keep this file ASCII-only. cmd.exe decodes batch files with the OEM
REM         codepage, so non-ASCII comments break the line parsing.
setlocal
if "%BLENDER_PYTHON%"=="" (
  echo [blender.cmd] set BLENDER_PYTHON to a python that has the bpy module 1>&2
  exit /b 3
)
"%BLENDER_PYTHON%" "%~dp0blender_shim.py" %*
exit /b %ERRORLEVEL%
