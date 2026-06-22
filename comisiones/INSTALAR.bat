@echo off
cd /d "%~dp0"
title Instalador - Sistema de Comisiones PF
color 0B
echo.
echo  ============================================
echo    SISTEMA DE COMISIONES PF ^| INSTALACION
echo  ============================================
echo.

REM -- Verificar Python --
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] Python no esta instalado en tu PC.
    echo.
    echo  Se va a abrir la pagina de descarga de Python.
    echo  Descarga e instala Python 3.x para Windows.
    echo.
    echo  MUY IMPORTANTE durante la instalacion de Python:
    echo  Marca la casilla que dice "Add Python to PATH"
    echo  antes de hacer clic en Install Now.
    echo.
    start https://www.python.org/downloads/
    echo  Una vez que instales Python, volvé a ejecutar este archivo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo  [OK] %PYVER% detectado
echo.
echo  Instalando componentes necesarios...
echo  (Esto puede tardar 1-2 minutos la primera vez)
echo.

pip install fastapi "uvicorn[standard]" requests python-dotenv --quiet 2>&1

if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] No se pudieron instalar los componentes.
    echo  Verifica que tenes conexion a internet e intentá de nuevo.
    pause
    exit /b 1
)

echo.
echo  ============================================
echo   ^>^> INSTALACION COMPLETADA CON EXITO! ^<^<
echo  ============================================
echo.
echo  Para usar el sistema todos los dias:
echo    --^> Doble clic en INICIAR.bat
echo.
pause
