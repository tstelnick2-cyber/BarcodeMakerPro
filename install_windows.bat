@echo off
setlocal
pushd "%~dp0"

echo Installing Python dependencies...
python -m pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo Failed to install dependencies.
    popd
    exit /b 1
)

echo Creating desktop and Start Menu shortcuts...
set "SCRIPT=%~dp0windows_barcode_app.py"
set "WORKDIR=%~dp0"
set "SHORTCUT_NAME=BarcodeMakerPro.lnk"
set "DESKTOP_SHORTCUT=%USERPROFILE%\Desktop\%SHORTCUT_NAME%"
set "START_MENU_SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\%SHORTCUT_NAME%"

powershell -NoProfile -Command "${
  $w = New-Object -ComObject WScript.Shell;
  foreach ($path in @('%DESKTOP_SHORTCUT%', '%START_MENU_SHORTCUT%')) {
    $shortcut = $w.CreateShortcut($path);
    $shortcut.TargetPath = 'python';
    $shortcut.Arguments = '"%SCRIPT%" --gui';
    $shortcut.WorkingDirectory = '%WORKDIR%';
    $shortcut.IconLocation = '$env:SystemRoot\\System32\\shell32.dll,1';
    $shortcut.Save();
  }
}"

if %ERRORLEVEL% neq 0 (
    echo Failed to create shortcuts. You can still run the app with run_windows.bat.
    popd
    exit /b 1
)

echo Installation complete.
echo Desktop shortcut created: %DESKTOP_SHORTCUT%
echo Start Menu shortcut created: %START_MENU_SHORTCUT%
popd
exit /b 0
