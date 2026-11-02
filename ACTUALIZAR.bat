@echo off
REM -- Este script se ejecuta desde una COPIA en la carpeta temporal.
REM -- Asi no se pisa a si mismo cuando mas abajo copia los archivos nuevos
REM -- (si el archivo cambia mientras Windows lo esta leyendo, se rompe).
if /i "%~1"=="__copia" goto seguir
copy /Y "%~f0" "%TEMP%\actualizar_comisiones.bat" >nul
call "%TEMP%\actualizar_comisiones.bat" __copia "%~dp0" & exit /b
:seguir
set "DEST=%~2"
cd /d "%DEST%"
title Actualizar - Sistema de Comisiones PF
color 0E
echo.
echo  ============================================
echo    ACTUALIZAR SISTEMA DE COMISIONES PF
echo  ============================================
echo.
echo  Esto descarga la ultima version y actualiza el programa.
echo  Antes de actualizar hace un backup de tus datos y del programa.
echo  Tus datos (comisiones.db) NO se tocan.
echo.
echo  IMPORTANTE: cerra el sistema (la ventana negra) antes de continuar.
echo.
pause

echo.
echo  [Backup] Guardando una copia de tus datos y del programa actual...
if exist "%DEST%comisiones.db" (
    call "%DEST%BACKUP.bat" silencioso
    if errorlevel 1 (
        echo.
        echo  [ERROR] No se pudo hacer el backup de tus datos.
        echo          Por seguridad NO se actualizo nada. Avisame antes de seguir.
        echo.
        pause
        exit /b 1
    )
)
set "HH=%time:~0,2%"
set "HH=%HH: =0%"
set "PROG=%DEST%backups\programa_%date:~6,4%%date:~3,2%%date:~0,2%_%HH%%time:~3,2%"
mkdir "%PROG%" >nul 2>&1
copy /Y "%DEST%*.py" "%PROG%\" >nul 2>&1
copy /Y "%DEST%index.html" "%PROG%\" >nul 2>&1
copy /Y "%DEST%requirements.txt" "%PROG%\" >nul 2>&1
echo  [Backup] Listo. Quedo en la carpeta "backups".

set "TMPZIP=%TEMP%\comisiones_update.zip"
set "TMPDIR=%TEMP%\comisiones_update"

echo.
echo  [1/5] Descargando ultima version...
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri 'https://github.com/pfimport/rutamax/archive/refs/heads/comisiones-standalone.zip' -OutFile '%TMPZIP%' -UseBasicParsing } catch { exit 1 }"
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] No se pudo descargar. Revisa tu conexion a internet e intenta de nuevo.
    echo.
    pause
    exit /b 1
)

echo  [2/5] Descomprimiendo...
if exist "%TMPDIR%" rmdir /s /q "%TMPDIR%" >nul 2>&1
powershell -NoProfile -Command "Expand-Archive -Path '%TMPZIP%' -DestinationPath '%TMPDIR%' -Force"
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] No se pudo descomprimir.
    echo.
    pause
    exit /b 1
)

echo  [3/5] Copiando archivos nuevos (sin tocar tus datos)...
set "SRCDIR="
for /d %%D in ("%TMPDIR%\*") do set "SRCDIR=%%D"
if not defined SRCDIR (
    echo  [ERROR] No se encontro la carpeta descargada.
    pause
    exit /b 1
)
xcopy /Y /E "%SRCDIR%\*" "%DEST%" >nul

echo  [4/6] Instalando componentes nuevos (puede tardar un momento)...
python -m pip install -r "%DEST%requirements.txt" -q >nul 2>&1

echo  [5/6] Borrando cache vieja...
if exist "%DEST%__pycache__" rmdir /s /q "%DEST%__pycache__" >nul 2>&1

echo  [6/6] Apagando el sistema viejo (para que cargue el codigo nuevo)...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 "') do (
    taskkill /PID %%a /F >nul 2>&1
)
del /q "%TMPZIP%" >nul 2>&1
rmdir /s /q "%TMPDIR%" >nul 2>&1

echo.
echo  ============================================
echo    [OK] ACTUALIZACION COMPLETA!
echo  ============================================
echo.
echo  El sistema viejo se apago. Ahora abrilo de nuevo
echo  (con el icono "Comisiones PF" o con INICIAR.bat)
echo  para que cargue todos los cambios.
echo.
pause
