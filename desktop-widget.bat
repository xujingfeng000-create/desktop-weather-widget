@echo off
rem Desktop Weather Widget debug launcher: keeps a console so you can see errors
cd /d "%~dp0"
set "PY="
if exist "C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" set "PY=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if "%PY%"=="" where python >nul 2>&1 && (set "PY=python") || (echo Python not found. Please install Python 3.8+. & pause & exit /b 1)
"%PY%" widget.py
pause
