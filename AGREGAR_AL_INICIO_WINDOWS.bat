@echo off
cd /d "%~dp0"
title Agregar al inicio automatico - Comisiones PF
color 0B
echo.
echo  ============================================
echo    AGREGAR AL INICIO AUTOMATICO DE WINDOWS
echo  ============================================
echo.

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "ORIGEN=%~dp0INICIAR_SILENCIOSO.vbs"
set "DESTINO=%STARTUP%\ComisionesPF.vbs"

copy /Y "%ORIGEN%" "%DESTINO%" >nul

if %errorlevel% == 0 (
    echo  [OK] Listo! El sistema de comisiones ahora se va a
    echo       iniciar automaticamente cada vez que enciendas
    echo       la computadora.
    echo.
    echo  Va a quedar minimizado en la barra de tareas.
    echo  Para abrirlo: http://localhost:8000
    echo.
    echo  Para desactivarlo: ejecuta QUITAR_DEL_INICIO_WINDOWS.bat
    echo.
) else (
    echo  [ERROR] No se pudo configurar el inicio automatico.
    echo  Intentalo haciendo clic derecho en este archivo y
    echo  seleccionando "Ejecutar como administrador".
    echo.
)
pause
