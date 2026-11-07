' Desktop Weather Widget launcher: starts widget.py silently (no console window).
' Tries common Python installations in order, falls back to "pythonw" on PATH.
Option Explicit
Dim fso, sh, folder, widget, py, pp, vf, latest
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
widget = folder & "\widget.py"
py = ""

' 1) DeepSeek Harness bundled Python (this machine)
Dim dsh
dsh = "C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"
If py = "" And fso.FileExists(dsh) Then py = dsh

' 2) py launcher
If py = "" And fso.FileExists(sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Launcher\pyw.exe") Then _
    py = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Launcher\pyw.exe"

' 3) latest Python3x under %LOCALAPPDATA%\Programs\Python
pp = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python"
If py = "" And fso.FolderExists(pp) Then
    For Each vf In fso.GetFolder(pp).SubFolders
        If InStr(vf.Name, "Python3") = 1 Then
            If fso.FileExists(vf.Path & "\pythonw.exe") Then latest = vf.Path & "\pythonw.exe"
        End If
    Next
    py = latest
End If

' 4) pythonw on PATH
If py = "" Then py = "pythonw"

sh.CurrentDirectory = folder
If Right(LCase(py), Len("pyw.exe")) = "pyw.exe" And InStr(py, "Launcher") > 0 Then
    sh.Run Chr(34) & py & Chr(34) & " -3 " & Chr(34) & widget & Chr(34), 0, False
Else
    sh.Run Chr(34) & py & Chr(34) & " " & Chr(34) & widget & Chr(34), 0, False
End If
