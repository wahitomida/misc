@echo off
setlocal
set "PATH=C:\Program Files\Git\cmd;%PATH%"
cd /d "C:\Users\hiita\OneDrive\workspace"
"C:\Program Files\Git\cmd\git.exe" --version
"C:\Program Files\Git\cmd\git.exe" config user.name "hiita"
"C:\Program Files\Git\cmd\git.exe" config user.email "hiita@example.com"
if not exist .git (
  "C:\Program Files\Git\cmd\git.exe" init
)
"C:\Program Files\Git\cmd\git.exe" remote remove origin 2>nul
"C:\Program Files\Git\cmd\git.exe" remote add origin https://github.com/wahitomida/misc.git
"C:\Program Files\Git\cmd\git.exe" branch -M main
"C:\Program Files\Git\cmd\git.exe" add .
for /f "delims=" %%c in ('"C:\Program Files\Git\cmd\git.exe" status --porcelain') do set "has_changes=1"
if defined has_changes (
  "C:\Program Files\Git\cmd\git.exe" commit -m "Initial commit from setup script"
) else (
  echo No changes to commit
)
"C:\Program Files\Git\cmd\git.exe" push -u origin main
endlocal
