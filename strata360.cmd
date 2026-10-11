@echo off
rem Launcher for Windows: runs the strata360 CLI with the project environment. Override the interpreter with STRATA_PYTHON.
set "ROOT=%~dp0"
if "%STRATA_PYTHON%"=="" set "STRATA_PYTHON=%ROOT%.venv\Scripts\python.exe"
set "PYTHONPATH=%ROOT%src"
set "PYTHONWARNINGS=ignore"
"%STRATA_PYTHON%" -m strata360 %*
