@echo off
title MediHome
cd /d "%~dp0"

if not exist venv (
  echo Virtual environment not found.
  echo Run SETUP_MEDIHOME.bat first.
  pause
  exit /b 1
)

call venv\Scripts\activate.bat
echo Starting MediHome...
python app.py
pause
