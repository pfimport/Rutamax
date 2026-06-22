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

echo  Iniciando... aguarda unos segundos.
echo.
echo  El sistema se va a abrir automaticamente en tu navegador.
echo.
echo  *** NO CIERRES ESTA VENTANA mientras uses el sistema ***
echo      Para cerrar el sistema, cerrá esta ventana.
echo.
echo  ============================================
echo.

REM Abrir el navegador luego de 3 segundos
start /min cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"

python -m uvicorn app:app --host 127.0.0.1 --port 8000

echo.
echo  El servidor se detuvo.
pause
