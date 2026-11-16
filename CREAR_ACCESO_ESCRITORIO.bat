@echo off
cd /d "%~dp0"
title Crear accesos directos - Comisiones PF
color 0A
echo.
echo  ============================================
echo    CREAR ACCESOS DIRECTOS EN EL ESCRITORIO
echo  ============================================
echo.
echo  Esto crea DOS iconos juntos en tu escritorio:
echo    - "Comisiones PF"             abre el sistema
echo    - "Comisiones PF - Actualizar"  lo actualiza (con backup)
echo.
echo  Apuntan a ESTA carpeta:
echo    %~dp0
echo.

powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$desktop = $ws.SpecialFolders('Desktop');" ^
  "$a = $ws.CreateShortcut([System.IO.Path]::Combine($desktop,'Comisiones PF.lnk'));" ^
  "$a.TargetPath = '%~dp0ABRIR_COMISIONES.bat';" ^
  "$a.WorkingDirectory = '%~dp0';" ^
  "$a.IconLocation = 'shell32.dll,220';" ^
  "$a.Description = 'Abrir Sistema de Comisiones PF';" ^
  "$a.Save();" ^
  "$b = $ws.CreateShortcut([System.IO.Path]::Combine($desktop,'Comisiones PF - Actualizar.lnk'));" ^
  "$b.TargetPath = '%~dp0ACTUALIZAR.bat';" ^
  "$b.WorkingDirectory = '%~dp0';" ^
  "$b.IconLocation = 'shell32.dll,238';" ^
  "$b.Description = 'Actualizar Sistema de Comisiones PF (hace backup antes)';" ^
  "$b.Save()"

if %errorlevel%==0 (
    echo  [OK] Listo! Ya tenes los dos iconos en el escritorio.
    echo.
    echo  Para abrir el sistema:      "Comisiones PF"
    echo  Para actualizarlo:          "Comisiones PF - Actualizar"
) else (
    echo  [!] No se pudieron crear los accesos directos.
)
echo.
pause
