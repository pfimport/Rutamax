@echo off
cd /d "%~dp0"
title Inventario de sistemas - SOLO LECTURA
color 0B
echo.
echo  ============================================
echo    INVENTARIO DE SISTEMAS EN ESTA PC
echo  ============================================
echo.
echo  Busca todas las copias de este sistema y sistemas parecidos.
echo  SOLO LEE: no modifica, mueve ni borra nada.
echo  Puede tardar unos minutos (revisa tambien Google Drive).
echo.
python "%~dp0escanear_sistemas.py"
echo.
echo  El informe quedo en el Escritorio: inventario_sistemas.txt
echo  Mandame ese archivo (o una captura) para decidir que sobra.
echo.
pause
