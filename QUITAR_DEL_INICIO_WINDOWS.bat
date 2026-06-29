@echo off
title Quitar del inicio automatico - Comisiones PF
color 0C
echo.
echo  ============================================
echo    QUITAR DEL INICIO AUTOMATICO DE WINDOWS
echo  ============================================
echo.

set "DESTINO=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ComisionesPF.vbs"

if exist "%DESTINO%" (
    del "%DESTINO%"
    echo  [OK] El inicio automatico fue desactivado.
    echo       El sistema ya no va a arrancar solo al encender la PC.
    echo.
) else (
    echo  El sistema no estaba configurado para iniciar automaticamente.
    echo.
)
pause
