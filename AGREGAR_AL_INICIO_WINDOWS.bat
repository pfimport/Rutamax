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
set "DESTINO=%STARTUP%\ComisionesPF.vbs"

REM Generar el acceso en la carpeta de Inicio con la RUTA ABSOLUTA a ESTE INICIAR.bat
> "%DESTINO%" echo Set WShell = CreateObject("WScript.Shell")
>> "%DESTINO%" echo WShell.Run "cmd /c ""%~dp0INICIAR.bat"" silencioso", 7, False

if exist "%DESTINO%" (
    echo  [OK] Listo! El sistema se va a iniciar solo cada vez que
    echo       enciendas la computadora, minimizado en la barra.
    echo.
    echo  Para abrirlo: usa el icono "Comisiones PF" del escritorio
    echo  o entra a http://localhost:8000
    echo.
    echo  Para desactivarlo: ejecuta QUITAR_DEL_INICIO_WINDOWS.bat
    echo.
) else (
    echo  [ERROR] No se pudo configurar el inicio automatico.
    echo  Proba haciendo clic derecho en este archivo y
    echo  "Ejecutar como administrador".
    echo.
)
pause
