@echo off
rem Remove DesktopWidget autostart task and stop the running widget
schtasks /delete /tn "DesktopWidget" /f
taskkill /im pythonw.exe /f >nul 2>&1
echo DesktopWidget autostart removed.
pause
