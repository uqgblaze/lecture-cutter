@echo off
cd /d "%~dp0"
where py >nul 2>&1 && py -3 "%~dp0lecture_cutter.py" && exit /b
where python >nul 2>&1 && python "%~dp0lecture_cutter.py" && exit /b
echo ERROR: Python not found. Install Python 3 from https://python.org
pause
