@echo off
chcp 65001 >nul
title Sanal Yoklama Sistemi
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [HATA] Once kurulum.bat dosyasini calistirin.
    pause
    exit /b 1
)

echo Sunucu baslatiliyor...
echo Tarayicidan http://localhost:5000 adresini acin.
echo Durdurmak icin bu pencerede Ctrl+C tuslayin.
echo.

start "" http://localhost:5000
call .venv\Scripts\python.exe run.py
pause
