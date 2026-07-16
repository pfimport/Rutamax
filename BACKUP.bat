@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ── Modo: "silencioso" = sin pausa al final (llamado desde INICIAR.bat)
set MODO=%1

if not "%MODO%"=="silencioso" (
    title Backup - Sistema de Comisiones PF
    color 0B
    echo.
    echo  ============================================
    echo    BACKUP - SISTEMA DE COMISIONES PF
    echo  ============================================
    echo.
)

REM ── Verificar que existe la base de datos
if not exist "comisiones.db" (
    if not "%MODO%"=="silencioso" (
        echo  [!] No se encontro comisiones.db - ejecuta desde la carpeta del sistema.
        pause
    )
    exit /b 1
)

REM ── Crear carpeta backups local
if not exist "backups" mkdir "backups"

REM ── Nombre con fecha y hora
set DIA=%date:~0,2%
set MES=%date:~3,2%
set ANIO=%date:~6,4%
set HORA=%time:~0,2%
set MIN=%time:~3,2%
set HORA=%HORA: =0%
set NOMBRE=comisiones_%ANIO%%MES%%DIA%_%HORA%%MIN%.db

REM ── Copia local
copy /Y "comisiones.db" "backups\%NOMBRE%" >nul
if %errorlevel% neq 0 (
    if not "%MODO%"=="silencioso" echo  [ERROR] No se pudo crear el backup local.
    exit /b 1
)

REM ── Detectar y copiar a la nube (OneDrive o Google Drive)
set CLOUD_NOMBRE=
set CLOUD_DEST=

if defined OneDrive (
    set CLOUD_DEST=%OneDrive%\Backups\ComisionesPF
    set CLOUD_NOMBRE=OneDrive
) else if exist "%USERPROFILE%\OneDrive" (
    set CLOUD_DEST=%USERPROFILE%\OneDrive\Backups\ComisionesPF
    set CLOUD_NOMBRE=OneDrive
) else if exist "%USERPROFILE%\Google Drive" (
    set CLOUD_DEST=%USERPROFILE%\Google Drive\Backups\ComisionesPF
    set CLOUD_NOMBRE=Google Drive
) else if exist "%USERPROFILE%\Mi unidad" (
    set CLOUD_DEST=%USERPROFILE%\Mi unidad\Backups\ComisionesPF
    set CLOUD_NOMBRE=Google Drive
) else if exist "%USERPROFILE%\Dropbox" (
    set CLOUD_DEST=%USERPROFILE%\Dropbox\Backups\ComisionesPF
    set CLOUD_NOMBRE=Dropbox
)

if defined CLOUD_DEST (
    if not exist "%CLOUD_DEST%" mkdir "%CLOUD_DEST%" >nul 2>&1
    copy /Y "comisiones.db" "%CLOUD_DEST%\%NOMBRE%" >nul 2>&1
)

REM ── Limpiar backups locales: conservar solo los ultimos 30
set /a CONT=0
for /f "delims=" %%F in ('dir /b /o-d "backups\comisiones_*.db" 2^>nul') do (
    set /a CONT+=1
    if !CONT! GTR 30 del "backups\%%F" >nul 2>&1
)

REM ── Mostrar resultado
if not "%MODO%"=="silencioso" (
    echo  [OK] Backup creado: backups\%NOMBRE%
    if defined CLOUD_NOMBRE echo  [OK] Copia en %CLOUD_NOMBRE%: %CLOUD_DEST%\%NOMBRE%
    if not defined CLOUD_NOMBRE (
        echo.
        echo  Consejo: si installas OneDrive o Google Drive, los backups
        echo  tambien se van a copiar automaticamente a la nube.
    )
    echo.
    echo  Se conservan los ultimos 30 backups locales.
    echo.
    pause
)
