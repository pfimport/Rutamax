@echo off
cd /d "%~dp0"

REM ============================================================
REM  Abre el sistema de Comisiones de la forma mas facil:
REM  - Si el servidor ya esta corriendo, solo abre el navegador
REM  - Si no esta corriendo, lo inicia y abre el navegador solo
REM ============================================================

REM Verificar si el puerto 8000 ya esta escuchando (servidor activo)
netstat -aon 2>nul | findstr ":8000 " | findstr "LISTENING" >nul 2>&1

if %errorlevel%==0 (
    REM El servidor ya esta corriendo: solo abrir el navegador
    start "" http://localhost:8000
) else (
    REM El servidor NO esta corriendo: iniciarlo (INICIAR.bat abre el navegador solo)
    start "" "%~dp0INICIAR.bat"
)

exit /b
