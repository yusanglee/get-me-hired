@echo off
rem get-me-hired launcher for Windows: gmh <command> [args]
where py >nul 2>nul && (py -3 -I -X utf8 "%~dp0gmh.py" %* & exit /b %ERRORLEVEL%)
python -I -X utf8 "%~dp0gmh.py" %*
