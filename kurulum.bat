@echo off
chcp 65001 >nul
title Sanal Yoklama Sistemi - Kurulum
cd /d "%~dp0"

echo ==========================================
echo   Sanal Yoklama Sistemi - Ilk Kurulum
echo ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [HATA] Python bulunamadi. https://www.python.org/downloads/ adresinden
    echo kurup "Add Python to PATH" secenegini isaretleyin.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [1/4] Sanal ortam olusturuluyor...
    python -m venv .venv
) else (
    echo [1/4] Sanal ortam zaten var, atlaniyor.
)

echo [2/4] Bagimliliklar kuruluyor...
call .venv\Scripts\python.exe -m pip install --upgrade pip >nul
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo [HATA] Paketler kurulamadi.
    pause
    exit /b 1
)

echo [3/4] Veritabani hazirlaniyor...
set FLASK_APP=run.py
call .venv\Scripts\python.exe -m flask init-db

echo.
set /p SEED=Ornek veri (ogrenci + gecmis yoklama) eklensin mi? [E/h]:
if /i "%SEED%"=="h" goto son
echo [4/4] Ornek veri ekleniyor...
call .venv\Scripts\python.exe seed.py

:son
echo.
echo Kurulum tamamlandi. Uygulamayi baslatmak icin baslat.bat dosyasini calistirin.
pause
