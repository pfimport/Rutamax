@echo off
cd /d "%~dp0"
title Sistema de Comisiones PF
color 0A
echo.
echo  ============================================
echo    SISTEMA DE COMISIONES PF
echo  ============================================
echo.

REM -- Verificar que esta instalado --
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] Python no encontrado. Ejecuta primero INSTALAR.bat
    pause
    exit /b 1
)

REM -- Liberar puerto 8000 si esta ocupado --
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 "') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo  Iniciando... aguarda unos segundos.
echo.
echo  El sistema se va a abrir automaticamente en tu navegador.
echo.
echo  *** NO CIERRES ESTA VENTANA mientras uses el sistema ***
echo      Para cerrar el sistema, cerrá esta ventana.
echo.
echo  ============================================
echo.

REM Abrir el navegador luego de 3 segundos (no abre si es inicio automatico de Windows)
if not "%1"=="silencioso" (
    start /min cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"
)

python -m uvicorn app:app --host 127.0.0.1 --port 8000

echo.
echo  El servidor se detuvo.
pause
