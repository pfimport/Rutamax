Dim WShell, carpeta
Set WShell = CreateObject("WScript.Shell")
carpeta = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
' Inicia el servidor minimizado en la barra de tareas (sin abrir el navegador)
WShell.Run "cmd /c """ & carpeta & "INICIAR.bat"" silencioso", 7, False
