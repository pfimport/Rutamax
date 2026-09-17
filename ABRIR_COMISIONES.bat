@echo off
cd /d "%~dp0"
title Abriendo Comisiones PF...

REM ============================================================
REM  Abre el sistema de Comisiones sin errores:
REM  - Si ya esta prendido, abre el navegador al toque
REM  - Si esta apagado, lo prende, ESPERA a que este listo,
REM    y recien ahi abre el navegador (nunca muestra error)
REM ============================================================

REM ¿El servidor ya esta escuchando en el puerto 8000?
netstat -aon 2>nul | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto abrir

REM No esta prendido: iniciarlo en segundo plano (sin que abra el el navegador)
start "" "%~dp0INICIAR.bat" silencioso

color 0A
echo.
echo  ============================================
echo    ABRIENDO SISTEMA DE COMISIONES PF
echo  ============================================
echo.
echo  Prendiendo el sistema, aguarda unos segundos...
echo.

REM Esperar hasta que el servidor responda (maximo ~40 seg)
set /a intentos=0
:esperar
timeout /t 1 /nobreak >nul
netstat -aon 2>nul | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto abrir
set /a intentos+=1
if %intentos% lss 40 goto esperar

REM Si llego aca, algo fallo al iniciar
color 0C
echo.
echo  [!] El sistema tardo demasiado en iniciar.
echo      Proba abrir INICIAR.bat directamente para ver si hay algun error.
echo.
pause
exit /b 1

:abrir
start "" http://localhost:8000
exit /b
