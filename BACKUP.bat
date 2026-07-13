@echo off
cd /d "%~dp0"
title Backup - Sistema de Comisiones PF
color 0B
echo.
echo  ============================================
echo    BACKUP - SISTEMA DE COMISIONES PF
echo  ============================================
echo.

REM -- Crear carpeta backups si no existe --
if not exist "backups" mkdir "backups"

REM -- Nombre del backup con fecha y hora --
set DIA=%date:~0,2%
set MES=%date:~3,2%
set ANIO=%date:~6,4%
set HORA=%time:~0,2%
set MIN=%time:~3,2%
set HORA=%HORA: =0%

set NOMBRE=comisiones_%ANIO%%MES%%DIA%_%HORA%%MIN%.db

REM -- Verificar que existe la base de datos --
if not exist "comisiones.db" (
    echo  [!] No se encontro el archivo comisiones.db
    echo      Asegurate de ejecutar este archivo desde la carpeta del sistema.
    echo.
    pause
    exit /b 1
)

REM -- Copiar la base de datos --
copy /Y "comisiones.db" "backups\%NOMBRE%" >nul

if %errorlevel% == 0 (
    echo  [OK] Backup creado exitosamente:
    echo.
    echo       backups\%NOMBRE%
    echo.
    echo  Ahora podes reemplazar los archivos del ZIP sin miedo.
    echo  Si algo falla, copiá ese archivo de vuelta como comisiones.db
    echo.
) else (
    echo  [ERROR] No se pudo crear el backup.
    echo.
)
pause
