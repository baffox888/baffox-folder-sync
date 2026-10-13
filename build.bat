@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -r requirements.txt || goto :err
python -m PyInstaller --noconfirm --clean file_sync.spec || goto :err
echo.
echo 打包完成: dist\BaffoxFolderSync.exe
pause
exit /b 0
:err
echo 打包失败，请检查上面的错误信息。
pause
exit /b 1
