' This script reads ztb data and send to client windows (shall not be
' minimized), one line per time.
' It is a quick-and-dirty, yet working version.

Option Explicit
Dim fso, Wsh, AutoIt, objStream
set fso = CreateObject("Scripting.FileSystemObject")
set Wsh = CreateObject("WScript.Shell")
set AutoIt = CreateObject("AutoItX3.Control")
Set objStream = CreateObject("ADODB.Stream")
objStream.CharSet = "utf-8"
objStream.Open

Dim sFolder, objFile, strData
sFolder = Wscript.Arguments.Item(0)
If sFolder = "" Then
    Wscript.Echo "No Folder parameter was passed"
    Wscript.Quit
End If
For each objFile in fso.GetFolder(sFolder).Files
  dim flag
  flag = sFolder + "\" + objFile.name + ".is-new"
  If fso.GetExtensionName(objFile.name) = "log" and fso.FileExists(flag) Then
    objStream.LoadFromFile(objFile)
    objStream.LineSeparator = 10
    Do Until objStream.EOS
      strData = trim(objStream.ReadText(-2))
      if (strData <> "" and left(strData, 1) <> "#") Then
        SendIt strData
      end if
    Loop
    fso.DeleteFile(flag)
  End If
Next
objStream.Close

Sub SendIt(strData)
  Dim titles, title
  titles = Array("Client0", "Client1")
  For Each title in titles
    Wscript.Sleep(10000)
    Dim j
    for j = 1 to 3
      Wsh.AppActivate title
    next
    AutoIt.WinSetState title, "", AutoIt.SW_SHOW
    AutoIt.WinWaitActive title
    AutoIt.Send strData + "{CTRLDOWN}{ENTER}{CTRLUP}"
  Next
End Sub

