@echo off
cd /d "%~dp0"
python redstone_music_studio.py
if errorlevel 1 pause
