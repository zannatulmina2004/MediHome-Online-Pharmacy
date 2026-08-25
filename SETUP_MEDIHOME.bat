@echo off
title MediHome Setup
echo ==========================================
echo        MediHome - First Time Setup
echo ==========================================
echo.

if not exist venv (
  echo Creating virtual environment...
  python -m venv venv
)

call venv\Scripts\activate.bat
echo Installing Python packages...
python -m pip install --upgrade pip
pip install -r requirements.txt

if not exist .env (
  copy .env.example .env >nul
  echo Created .env from .env.example
)

echo.
echo Setup complete.
echo Edit .env if your MySQL root password is not blank.
echo Then make sure MySQL is running and run RUN_MEDIHOME.bat
pause
