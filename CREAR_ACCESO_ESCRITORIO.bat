@echo off
cd /d "%~dp0"
title Crear acceso directo - Comisiones PF
color 0A
echo.
echo  ============================================
echo    CREAR ACCESO DIRECTO EN EL ESCRITORIO
echo  ============================================
echo.
echo  Esto crea un icono "Comisiones PF" en tu escritorio.
echo  Con un solo clic abre el sistema y el navegador juntos.
echo.

powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$desktop = $ws.SpecialFolders('Desktop');" ^
  "$lnk = $ws.CreateShortcut([System.IO.Path]::Combine($desktop,'Comisiones PF.lnk'));" ^
  "$lnk.TargetPath = '%~dp0ABRIR_COMISIONES.bat';" ^
  "$lnk.WorkingDirectory = '%~dp0';" ^
  "$lnk.IconLocation = 'shell32.dll,220';" ^
  "$lnk.Description = 'Abrir Sistema de Comisiones PF';" ^
  "$lnk.Save()"

if %errorlevel%==0 (
    echo  [OK] Listo! Ya tenes el icono "Comisiones PF" en el escritorio.
    echo.
    echo  De ahora en mas, para abrir el sistema hace doble clic en ese icono.
) else (
    echo  [!] No se pudo crear el acceso directo.
)
echo.
pause
